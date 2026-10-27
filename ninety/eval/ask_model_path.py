"""The Ask's model path measured: each step's latency, tokens and cost, and the Judge on insight facts.

    uv run python -m ninety.eval.ask_model_path latency --insights <insights.json> --arm before
    uv run python -m ninety.eval.ask_model_path judge --insights <insights.json>
    uv run python -m ninety.eval.ask_model_path report

`latency` asks the published match Companion (and the Judge, where the arm runs it) a fixed list of
demo-match questions through `answer_match`, as the API does in Live mode, with every model call
timed and its tokens read off the reply (agents_live.Observed). It stops at --max-calls model calls.
The `before` arm ran on the code before the per-step budgets (one 10 s limit, the Judge on every
model answer); `after` runs the code as it is. Rows go to docs/eval/ask-model-path/latency-<arm>.jsonl.

`judge` measures the Judge on the match path's own sentences: true claims are code's sentences for
confident insight facts of the demo match (`code_texts`, which the code check passes), planted claims
are the same sentences with one defect each (ninety/eval/insight_claims.py's `plants`). Each claim
goes through the code check (`_verify`) and to the Judge twice, under its published instructions
(written for events) and under MATCH_INSTRUCTIONS (written for insight facts), both as local
definitions on the same model. Rows go to docs/eval/ask-model-path/judge.jsonl.

Both cost model tokens; each run logs its spend, and the report adds them up.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import random
import statistics
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path

from ninety.agents import companion_match as cm
from ninety.agents.contracts import Question
from ninety.agents.factcheck import Claim
from ninety.eval import agents_live as al
from ninety.eval import insight_claims
from ninety.eval import latency_cost as lc

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs/eval/ask-model-path"
REPORT = ROOT / "docs/eval/ask-model-path.md"
# Demo-match questions, each at the moment a fan would ask it (agents-live's moments, seed 8324),
# plus two the red-team set asks often. Fixed before any run.
QUESTIONS = (
    ("What led to that goal?", 735.72),
    ("Where are London Athletic outnumbering Lisbon Esportes?", 3609.2),
    ("Who had more of the ball in the first half?", 2703.0),
    ("Which pass cut through London Athletic's lines just now?", 5330.16),
    ("Who has run the furthest?", 4000.0),
)
PER_KIND = 4  # judge set: true claims per fact kind, planted claims per defect kind
SEED = 8324  # the sample's shuffle, fixed


def _commit() -> str:
    return subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True,
                          cwd=ROOT).stdout.strip()


def _insights(path: str):
    from ninety.intel.match_insights import MatchInsights

    return MatchInsights.from_dict(json.loads(Path(path).read_text()))


async def latency(args) -> None:
    from ninety.agents import credentials

    insights = _insights(args.insights)
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"latency-{args.arm}.jsonl"
    trace = al.Trace(path, args.max_calls, budget_usd=args.max_usd)
    trace.write("run_start", arm=args.arm, commit=_commit(), match=insights.clip, judge=args.judge,
                at=datetime.now(UTC).isoformat(timespec="seconds"))
    try:
        async with credentials.new_credential() as credential:
            await credentials.sign_in(credential)
            async with al.companion_models(trace, credential) as (ask, judge):
                for text, t in QUESTIONS[: args.questions]:
                    trace.scope = {"question": text}
                    t0 = time.perf_counter()
                    r = await cm.answer_match(Question("ask-model-path", None, text, t), insights, ask,
                                              judge if args.judge else None, timeout=args.timeout)
                    trace.write("ask_done", ms=round((time.perf_counter() - t0) * 1000, 1), source=r.source,
                                status=r.answer.status, text=r.answer.text, reasons=list(r.reasons),
                                tools=[c["name"] for c in r.tools])
    except al.OverBudget as e:
        trace.write("stopped", reason=str(e))
    trace.scope = {}
    trace.write("run_end", calls=trace.calls, usd=round(trace.usd, 6))
    print(f"{path}: {trace.calls} calls, ${trace.usd:.4f}")


def judge_set(insights) -> tuple[list[dict], dict]:
    """True and planted claims on the demo match's insight facts, PER_KIND of each kind, shuffled
    with a fixed seed so the sample does not depend on dict order."""
    rows = insight_claims.facts_and_summaries(insights)
    known = {f["id"]: {**f, "clubs": insights.fixture.clubs} for f in rows}
    by_kind: dict[str, dict] = {}
    for f in rows:
        if f.get("confident", True):
            by_kind.setdefault(f["kind"], f)
    rng = random.Random(SEED)
    rng.shuffle(rows)
    true, planted = {}, {}
    for f in rows:
        if not f.get("confident", True):
            continue
        texts = cm.code_texts({**known[f["id"]], "confident": True})
        if not texts:
            continue
        text = texts[0]
        if len(true.setdefault(f["kind"], [])) < PER_KIND:
            true[f["kind"]].append({"label": "true", "kind": f["kind"], "text": text, "evidence": [f["id"]]})
        other = next((g for k, g in by_kind.items() if k != f["kind"]), None)
        for kind, claim in insight_claims.plants(text, known[f["id"]], insights, other):
            if kind == "uncited" or (claim.text == text and claim.evidence == [f["id"]]):
                continue  # an uncited claim gives the Judge no evidence to read
            if len(planted.setdefault(kind, [])) < PER_KIND:
                planted[kind].append({"label": "planted", "kind": kind, "text": claim.text,
                                      "evidence": list(claim.evidence)})
    out = [c for group in (*true.values(), *planted.values()) for c in group]
    for c in out:
        c["code_ok"] = cm._verify(Claim(c["text"], c["evidence"]), known, insights).ok
    return out, known


class Counting:
    """An agent whose calls are counted and capped, with the tokens each reply reports."""

    def __init__(self, agent, cap: dict):
        self.agent, self.cap = agent, cap

    async def run(self, prompt, **kwargs):
        if self.cap["calls"] >= self.cap["max_calls"]:
            raise al.OverBudget("judge set call cap reached")
        self.cap["calls"] += 1
        t0 = time.perf_counter()
        reply = await self.agent.run(prompt, **kwargs)
        usage = getattr(reply, "usage_details", None)
        usage = usage if isinstance(usage, dict) else vars(usage) if usage is not None else {}
        t_in, t_out = usage.get("input_token_count") or 0, usage.get("output_token_count") or 0
        self.cap["usd"] += float(lc.price(lc.INPUT) * t_in + lc.price(lc.OUTPUT) * t_out)
        self.cap["ms"].append((time.perf_counter() - t0) * 1000)
        return reply


async def judge_run(args) -> None:
    from agent_framework import Agent

    from ninety.agents import credentials, foundry
    from ninety.agents.judge import INSTRUCTIONS, MATCH_INSTRUCTIONS, Judgement
    from ninety.agents.judge import judge as run_judge

    insights = _insights(args.insights)
    claims, known = judge_set(insights)
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / "judge.jsonl"
    cap = {"calls": 0, "max_calls": args.max_calls, "usd": 0.0, "ms": []}
    with path.open("w") as f:
        f.write(json.dumps({"kind": "run_start", "commit": _commit(), "match": insights.clip,
                            "claims": len(claims),
                            "at": datetime.now(UTC).isoformat(timespec="seconds")}) + "\n")
    async with credentials.new_credential() as credential:
        await credentials.sign_in(credential)
        client = foundry.chat_client(credential)
        arms = {
            name: Counting(Agent(client=client, name="judge", instructions=text,
                                 default_options={"response_format": Judgement, "temperature": 0}), cap)
            for name, text in (("events", INSTRUCTIONS), ("insights", MATCH_INSTRUCTIONS))
        }
        sem = asyncio.Semaphore(2)  # 4 drew rate-limit retries

        async def one(c: dict, arm: str) -> dict:
            async with sem:
                evidence = [cm._for_prompt(known[i]) for i in c["evidence"]]
                try:
                    claim = Claim(c["text"], c["evidence"])
                    v = await run_judge(arms[arm], claim, evidence, timeout_seconds=30)
                except al.OverBudget:  # this claim stays unmeasured; the others keep their answers
                    return {**c, "arm": arm, "judge_ok": None, "reasons": ["not asked: call cap"]}
                return {**c, "arm": arm, "judge_ok": v.ok, "reasons": v.reasons, "category": v.category}

        rows = await asyncio.gather(*(one(c, arm) for c in claims for arm in arms))
    with path.open("a") as f:
        for r in rows:
            f.write(json.dumps(r, separators=(",", ":")) + "\n")
        ms = sorted(cap["ms"])
        f.write(json.dumps({"kind": "run_end", "calls": cap["calls"], "usd": round(cap["usd"], 6),
                            "ms_p50": round(statistics.median(ms), 1) if ms else None}) + "\n")
    print(f"{path}: {cap['calls']} calls, ${cap['usd']:.4f}")


def _rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _pct(xs: list[float], q: float) -> float | None:
    """The q-quantile by the nearest rank: with a handful of samples it is a value that was observed."""
    if not xs:
        return None
    xs = sorted(xs)
    return xs[min(len(xs), math.ceil(q * len(xs))) - 1]


def _step(row: dict) -> str:
    """A model call's step: the Judge, or the Companion's plan or answer, read off its prompt."""
    if row["role"] == "judge":
        return "judge"
    return "plan" if '"step":"plan"' in row["prompt"][:20] else "answer"


# The agents-live run on the demo match (#417) asked the same published agents (companion-match:4,
# judge:4) eight questions under the same code: its Companion runs are "before" samples too. Its
# drills (a Judge forced down, a Companion forced slow) are faults it injected, so they are left out.
AGENTS_LIVE = ROOT / "docs/eval/agents-live/seed8324/trace.jsonl"
BUDGET_FACTOR, BUDGET_STEP_S = 1.5, 0.5  # design: a step's budget is 1.5 x its p95, rounded up to 0.5 s
LOST_RUN_USD = 0.0769  # the first judge-set run: capped mid-way, its answers discarded unrecorded


def budget_for(p95_ms: float) -> float:
    return math.ceil(p95_ms / 1000 * BUDGET_FACTOR / BUDGET_STEP_S) * BUDGET_STEP_S


def _asks(rows: list[dict], calls_by: str) -> list[dict]:
    """One row per question: who answered, why not the model, its total time, its model cost."""
    usd: dict[str, float] = {}
    for r in rows:
        if r["kind"] == "model_call":
            usd[r.get(calls_by)] = usd.get(r.get(calls_by), 0.0) + r["usd"]
    done = "ask_done" if calls_by == "question" else "companion_done"
    return [{"source": r["source"], "reasons": r["reasons"], "ms": r["ms"],
             "usd": round(usd.get(r.get(calls_by), 0), 6)}
            for r in rows if r["kind"] == done and r.get("run", "companion") == "companion"]


def summary(asks: list[dict]) -> dict:
    ms = [a["ms"] for a in asks]
    model = [a for a in asks if a["source"] == "model"]
    return {
        "questions": len(asks),
        "code_fallbacks": len(asks) - len(model),
        "fallback_reasons": sorted({r for a in asks for r in a["reasons"]}),
        "ms_p50": statistics.median(ms) if ms else None,
        "ms_p95": _pct(ms, 0.95),
        "usd_per_answer": round(sum(a["usd"] for a in asks) / len(asks), 6) if asks else None,
    }


def report() -> dict:
    live = [r for r in _rows(AGENTS_LIVE) if r.get("run") == "companion"]
    before, after = _rows(OUT / "latency-before.jsonl"), _rows(OUT / "latency-after.jsonl")
    samples: dict[str, list[float]] = {"plan": [], "answer": [], "judge": []}
    for r in [*live, *before, *after]:
        if r["kind"] == "model_call" and not r.get("error"):
            samples[_step(r)].append(r["ms"])
    steps = {k: {"n": len(v), "p50_ms": statistics.median(v), "p95_ms": _pct(v, 0.95), "max_ms": max(v),
                 "budget_s": budget_for(_pct(v, 0.95))} for k, v in samples.items()}
    judged = [r for r in _rows(OUT / "judge.jsonl") if "arm" in r]
    judge: dict[str, dict] = {}
    for arm in sorted({r["arm"] for r in judged}):
        rs = [r for r in judged if r["arm"] == arm and r["judge_ok"] is not None]
        cell = {}
        for label in ("true", "planted"):
            for code in (True, False):
                group = [r for r in rs if r["label"] == label and r["code_ok"] is code]
                cell[f"{label}, code {'passed' if code else 'rejected'}"] = {
                    "claims": len(group), "judge_rejected": sum(not r["judge_ok"] for r in group)}
        judge[arm] = cell
    runs = [*(r for r in [*before, *after] if r["kind"] == "run_end"),
            *(r for r in _rows(OUT / "judge.jsonl") if r.get("kind") == "run_end")]
    return {
        "match": "seed8324-match",
        "steps": steps,
        "before": summary(_asks(live, "key") + _asks(before, "question")),
        "after": summary(_asks(after, "question")),
        "judge": judge,
        "judge_escapes": [{"arm": r["arm"], "kind": r["kind"], "text": r["text"], "judge_ok": r["judge_ok"]}
                          for r in judged if r["label"] == "planted" and r["code_ok"]],
        "spend_usd": round(sum(r["usd"] for r in runs) + LOST_RUN_USD, 4),
    }


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    lat = sub.add_parser("latency")
    lat.add_argument("--insights", required=True)
    lat.add_argument("--arm", choices=("before", "after"), required=True)
    lat.add_argument("--judge", action=argparse.BooleanOptionalAction, default=True)
    lat.add_argument("--questions", type=int, default=3)
    lat.add_argument("--timeout", type=float, default=cm.TIMEOUT_S)
    lat.add_argument("--max-calls", type=int, default=10)
    lat.add_argument("--max-usd", type=float, default=0.05)
    jd = sub.add_parser("judge")
    jd.add_argument("--insights", required=True)
    jd.add_argument("--max-calls", type=int, default=260)
    sub.add_parser("report")
    args = p.parse_args(argv)
    if args.cmd == "latency":
        asyncio.run(latency(args))
    elif args.cmd == "judge":
        asyncio.run(judge_run(args))
    else:
        body = report()
        (OUT / "report.json").write_text(json.dumps(body, indent=1) + "\n")
        print(json.dumps(body, indent=1))


if __name__ == "__main__":
    main()
