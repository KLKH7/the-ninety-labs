"""Run fan questions x paraphrases x match times through the Ask and grade each answer, offline.

    # the truth table, once (reads the answer key; grading only):
    uv run python -m ninety.eval.ask_grade.run truth --run ~/ninety-notes/demo-engine-v2/out/seed8324 \\
        --work runs/demo-8324-final-work --insights runs/demo-8324-final/final-work/insights.json \\
        --cache <scratch>/truth-8324.npz --out ninety/eval/ask_grade/truth-8324.json.gz
    # grade the code path (no model, no cost):
    uv run python -m ninety.eval.ask_grade.run grade --insights <insights.json[.gz]> --label main \\
        --out runs/ask-grade/main.jsonl
    # rebuild the insights from the package first (#424 computes possession into them):
    uv run python -m ninety.eval.ask_grade.run grade --rebuild-insights runs/demo-8324-final ...
    # before/after per intent for a PR, both refs graded by this checkout's rules (paste it in the PR):
    uv run python -m ninety.eval.ask_grade.run --compare origin/main HEAD
    # the model path on a ~10% sample (costs money; NINETY_DEMO_PASSCODE must be set; stops at $1.50):
    uv run python -m ninety.eval.ask_grade.run grade --model ...

The answer key is read only by `truth`; `grade` reads the frozen truth table it wrote, so CI grades
without it. Nothing on the live path imports this package (tests/test_ask_grade.py).
"""

from __future__ import annotations

import argparse
import asyncio
import collections
import gzip
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from ninety.eval.ask_grade import grade as G

HERE = Path(__file__).parent
TIMES = (600.0, 2030.0, 2700.0, 3600.0, 5100.0, 5400.0)  # 10', 33:50, 45', 60', 85', full time
TRUTH_TABLE = HERE / "truth-8324.json.gz"
SESSION = "ask-grade"
MODEL_SHARE = 0.10  # design: about one answer in ten goes through the model
SPEND_CAP_USD = 1.50  # the coordinator's cap for one model run
PASSCODE_ENV = "NINETY_DEMO_PASSCODE"


def load_insights(path: Path):
    from ninety.intel.match_insights import MatchInsights

    raw = path.read_bytes()
    if path.suffix == ".gz":
        raw = gzip.decompress(raw)
    return MatchInsights.from_dict(json.loads(raw))


def rebuild_insights(package: Path, out: Path) -> Path:
    """The insights rebuilt from a package's tracked frames, detected events and scorebug, by the
    checked-out code's own builder (ninety/intel/match_insights.main), in a child process so its
    memory is returned. Run it through ~/ninety-notes/heavy.sh."""
    work = package / "final-work"
    detected = work / "detected.sided.jsonl"
    if not detected.exists():
        detected = package / "detected.jsonl"
    cmd = [
        sys.executable,
        "-m",
        "ninety.intel.match_insights",
        str(package / "tracked.json"),
        str(detected),
        str(package / "clip.json"),
        "--clip",
        "seed8324-match",
        "--out",
        str(out),
        "--scorebug",
        str(package / "scorebug.jsonl"),
    ]
    if (package / "association.json").exists():
        cmd += ["--association", str(package / "association.json")]
    if (work / "identity_feed.jsonl").exists():
        cmd += ["--identity-feed", str(work / "identity_feed.jsonl")]
        vision = (
            package.parent / f"{package.name}-work" / "vision"
        )  # the segments' runs, as the package built
        if vision.exists():
            cmd += ["--broadcast-vision", str(vision)]
    subprocess.run(cmd, check=True)
    return out


def holds(insights, it: dict, t: float) -> bool | None:
    """Do the insights hold a fact this intent could be answered from, by time t?"""
    m = it["metric"]
    minute = G.now_minute(t)
    facts = insights.facts

    def any_fact(kind, pred=lambda f: True):
        return any((f.get("t") or 0) <= t and pred(f) for f in facts.get(kind, []))

    def row(key):
        rows = (
            {r["key"]: r for r in getattr(insights, "stats", {}).get("rows", [])}
            if isinstance(getattr(insights, "stats", None), dict)
            else {}
        )
        r = rows.get(key)
        return bool(r) and any(
            s.get("minute_to", 0) <= minute and (s.get("home") is not None or s.get("away") is not None)
            for s in r["series"]
        )

    if m is None or m == "unmeasured":
        return None
    if m in ("score", "leader", "goals", "goal_build_up_home"):
        return True  # the scorebug always reads a score; the goals are facts or "no goal yet"
    if m == "possession_home":
        return any_fact(
            "possession", lambda f: f.get("metric") == "possession_share" and f.get("confident")
        ) or row("possession")
    if m in ("territory", "territory_leader"):
        return any_fact("territory") or row("territory")
    if m in ("passes", "completion"):
        return any_fact("pass")
    if m in ("shots", "on_target"):
        return any_fact("shot")
    if m == "corners":
        return row("corner")
    if m == "out_of_play":
        return row("throw_in") or row("goal_kick")
    if m.startswith("involvement"):
        return any_fact("pass", lambda f: f.get("player"))
    if m in ("peak_speed", "distance"):
        return any_fact("running")
    return None


def questions(intents: list[dict]) -> list[tuple[dict, dict]]:
    return [(it, q) for it in intents for q in it["questions"]]


def model_sample(intents: list[dict], times=TIMES) -> set[tuple[str, str, float]]:
    """The model's sample, stratified by intent: in each intent, the MODEL_SHARE of its (question,
    time) pairs (at least one) that sort first by a hash, so the sample is fixed and spread over every
    intent, its paraphrases and the times."""
    import math

    out = set()
    for it in intents:
        pairs = [(q["q"], t) for q in it["questions"] for t in times]
        pairs.sort(key=lambda p: hashlib.sha256(f"{it['id']}|{p[0]}|{p[1]:g}".encode()).hexdigest())
        out |= {(it["id"], q, t) for q, t in pairs[: max(1, math.ceil(MODEL_SHARE * len(pairs)))]}
    return out


def ask_code(insights, q: str, t: float) -> dict:
    from ninety.agents import companion_match as cm
    from ninety.agents.contracts import Question

    t0 = time.perf_counter()
    try:
        a, calls = cm.code_match_answer(Question(SESSION, None, q, float(t)), insights, suggest=False)
        rec = {
            "status": a.status,
            "text": a.text,
            "t_to": a.t_to,
            "metric": a.metric,
            "value": a.value,
            "evidence": list(a.evidence),
            "tools": [c.get("name") for c in calls],
            "source": "code",
        }
    except Exception as exc:  # noqa: BLE001  a crash is graded as no answer, and kept
        rec = {
            "status": "error",
            "text": "",
            "t_to": None,
            "error": repr(exc)[:300],
            "tools": [],
            "source": "code",
        }
    rec["latency_s"] = round(time.perf_counter() - t0, 3)
    return rec


def run(
    insights, intents: list[dict], table: dict, tol: dict, clubs: dict, times=TIMES, answer=None
) -> list[dict]:
    """Every question at every time, graded. `answer(it, q, t)` overrides the code path."""
    roster = table["_roster"]
    out = []
    for t in times:
        for it, qd in questions(intents):
            q = qd["q"]
            w = G.window_of(it, q, t)
            ans = answer(it, q, t) if answer else ask_code(insights, q, t)
            ans["leak"] = leaks(insights, ans.get("evidence") or [], t)
            tv = table.get(G.wkey(it, t, w))
            g = G.grade(it, q, t, ans, tv, tol, clubs, roster, holds(insights, it, t))
            if "code_answer" in ans:  # the model's answer: code's to the same question graded beside it
                ca = ans["code_answer"]
                ca["leak"] = leaks(insights, ca.get("evidence") or [], t)
                cg = G.grade(it, q, t, ca, tv, tol, clubs, roster, holds(insights, it, t))
                ans["code_core"] = G.core_passed(cg["checks"])
                ans["parity"] = G.headline(ans.get("text") or "") == G.headline(ca.get("text") or "")
            out.append(
                {
                    "intent": it["id"],
                    "q": q,
                    "chip": qd.get("chip"),
                    "t": t,
                    "window": list(w),
                    "clubs_asked": G.clubs_in(q, clubs),
                    **ans,
                    **g,
                }
            )
    consistency(out)
    for r in out:
        r["pass"] = G.passed(r["checks"])
        r["core"] = G.core_passed(r["checks"])
    return out


# A cited aggregate's id names its source facts' kind and its minutes ("shots:all:m1-34", "terr:home:m20-34").
AGGREGATE_KINDS = {
    "shots": ("shot",),
    "terr": ("territory",),
    "po": ("pass_options",),
    "cp": ("counter_press",),
    "ov": ("overload",),
    "pt": ("pass_type",),
    "style": ("pass_type", "pass"),
    "top": ("line_break",),
    "score": ("goal", "scorebug"),
    "poss": ("possession",),
}


def leaks(insights, evidence: list[str], t: float) -> list[str]:
    """The cited ids that use something from after t: a fact timed after t, or an aggregate one of
    whose source facts (same kind, same side, inside its minutes) is timed after t. Aggregates of a
    kind with no source facts in the insights (set pieces, the Laws) cannot be checked and are not
    counted."""
    import re

    by_id = {f["id"]: f for v in insights.facts.values() for f in v}
    out = []
    for e in evidence:
        f = by_id.get(e)
        if f is not None:
            if f.get("t") is not None and float(f["t"]) > t:
                out.append(e)
            continue
        parts = e.split(":")
        kinds = AGGREGATE_KINDS.get(parts[0])
        m = re.search(r":m(\d+)(?:-(\d+))?$", e)
        if not kinds or not m:
            continue
        lo, hi = (int(m.group(1)), int(m.group(2))) if m.group(2) else (1, int(m.group(1)))
        side = next((p for p in parts if p in ("home", "away")), None)
        for k in kinds:
            if any(
                g.get("t") is not None
                and float(g["t"]) > t
                and lo <= int(g.get("minute") or 0) <= hi
                and (side is None or g.get("team") in (None, side))
                for g in insights.facts.get(k, [])
            ):
                out.append(e)
                break
    return out


def consistency(rows: list[dict]) -> None:
    """The same headline across an intent's paraphrases at one time, same window and same club
    asked about; the modal headline is the reference. A group of one does not apply."""
    groups = collections.defaultdict(list)
    for r in rows:
        groups[(r["intent"], r["t"], tuple(r["window"]), tuple(sorted(r["clubs_asked"])))].append(r)
    for g in groups.values():
        heads = [G.headline(r.get("text") or "") for r in g]
        modal = collections.Counter(heads).most_common(1)[0][0]
        for r, h in zip(g, heads, strict=True):
            r["checks"]["consistent"] = None if len(g) < 2 else h == modal


def _rate(xs) -> float | None:
    xs = list(xs)
    return round(sum(xs) / len(xs), 3) if xs else None


def summarise(rows: list[dict]) -> dict:
    """Per intent and overall: the core pass rate (the headline: answered, relevant, correct, no
    false "not known"), the all-checks pass rate, and each check's own rate where it applies."""

    def block(rs):
        d = {"n": len(rs), "core": _rate(r["core"] for r in rs), "pass": _rate(r["pass"] for r in rs)}
        for c in G.CHECKS:
            d[c] = _rate(r["checks"][c] for r in rs if r["checks"].get(c) is not None)
        return d

    per = {
        iid: block([r for r in rows if r["intent"] == iid])
        for iid in dict.fromkeys(r["intent"] for r in rows)
    }
    chips = [r for r in rows if r.get("chip")]
    return {**block(rows), "chips": block(chips) if chips else {}, "intents": per}


# ---- the model path (costs money) -----------------------------------------------------------------


THROTTLE_BACKOFF_S = (2.0, 5.0, 10.0, 20.0)  # design: a shared deployment's throttling clears in seconds


class _Metered:
    """An agent whose replies' token usage (as the service reports it) is added up."""

    def __init__(self, agent, usage: dict):
        self._agent, self._usage = agent, usage

    async def run(self, *args, **kwargs):
        for wait in (*THROTTLE_BACKOFF_S, None):  # a throttled call (HTTP 429) waits and is tried again
            try:
                reply = await self._agent.run(*args, **kwargs)
                break
            except Exception as exc:  # noqa: BLE001  the SDK's rate-limit error has no stable type
                if wait is None or ("429" not in str(exc) and "rate" not in str(exc).lower()):
                    raise
                await asyncio.sleep(wait)
        u = getattr(reply, "usage_details", None)
        u = u if isinstance(u, dict) else vars(u) if u is not None else {}
        self._usage["in"] += int(u.get("input_token_count") or 0)
        self._usage["out"] += int(u.get("output_token_count") or 0)
        self._usage["calls"] += 1
        return reply

    def __getattr__(self, name):
        return getattr(self._agent, name)


def model_answerer(insights, intents: list[dict], log: list[dict]):
    """answer(it, q, t) through companion_match.answer_match with the Foundry agents (Companion and
    Judge) on the stratified sample (model_sample), with code's answer to the same question kept
    beside it; code's answer elsewhere. Each model answer logs its latency, the tokens the service
    reported and their price (ninety/eval/latency_cost.PRICES); no model call starts once
    SPEND_CAP_USD is spent."""
    if not os.environ.get(PASSCODE_ENV):
        raise SystemExit(f"--model needs {PASSCODE_ENV} set in the environment (it is never printed)")
    from ninety.eval.latency_cost import INPUT, OUTPUT, price

    sample = model_sample(intents)
    spent = {"usd": 0.0}
    loop = asyncio.new_event_loop()
    state: dict = {}

    async def setup():
        import contextlib

        from ninety.agents import companion_match as cm
        from ninety.agents import credentials, foundry
        from ninety.agents.judge import judge as run_judge
        from ninety.agents.judge import judge_agent

        stack = contextlib.AsyncExitStack()
        credential = await stack.enter_async_context(credentials.new_credential())
        await credentials.sign_in(credential)
        client = foundry.chat_client(credential)
        usage = {"in": 0, "out": 0, "calls": 0}
        match_ag = _Metered(cm.companion_match_agent(client), usage)
        judge_ag = _Metered(judge_agent(client), usage)

        async def ask(prompt):
            return (await match_ag.run(prompt)).text

        async def judge(claim, evidence):
            return await run_judge(judge_ag, claim, evidence)

        state.update(stack=stack, ask=ask, judge=judge, usage=usage)

    loop.run_until_complete(setup())

    def answer(it, q, t):
        if (it["id"], q, t) not in sample:
            return ask_code(insights, q, t)
        if spent["usd"] >= SPEND_CAP_USD:
            rec = ask_code(insights, q, t)
            rec["model_skipped"] = "spend cap"
            return rec
        from ninety.agents import companion_match as cm
        from ninety.agents.contracts import Question

        state["usage"].update({"in": 0, "out": 0, "calls": 0})
        t0 = time.perf_counter()
        try:
            r = loop.run_until_complete(
                cm.answer_match(
                    Question(SESSION, None, q, float(t)), insights, ask=state["ask"], judge=state["judge"]
                )
            )
            a = r.answer
            rec = {
                "status": a.status,
                "text": a.text,
                "t_to": a.t_to,
                "metric": a.metric,
                "value": a.value,
                "evidence": list(a.evidence),
                "tools": [c.get("name") for c in r.tools],
                "source": r.source,
                "reasons": list(r.reasons),
            }
        except Exception as exc:  # noqa: BLE001  kept and graded as no answer
            rec = {
                "status": "error",
                "text": "",
                "t_to": None,
                "error": repr(exc)[:300],
                "tools": [],
                "source": "error",
                "reasons": [type(exc).__name__],
            }
        u = state["usage"]
        usd = float(price(INPUT) * u["in"] + price(OUTPUT) * u["out"])
        spent["usd"] += usd
        rec.update(
            latency_s=round(time.perf_counter() - t0, 3),
            tokens_in=u["in"],
            tokens_out=u["out"],
            model_calls=u["calls"],
            usd=round(usd, 6),
            model=True,
        )
        rec["code_answer"] = ask_code(insights, q, t)
        log.append(
            {
                "intent": it["id"],
                "q": q,
                "t": t,
                "latency_s": rec["latency_s"],
                "usd": rec["usd"],
                "source": rec["source"],
                "reasons": rec.get("reasons", []),
            }
        )
        print(
            f"model {len(log)} {it['id']} {rec['source']} {rec['latency_s']:.1f}s ${spent['usd']:.4f}",
            file=sys.stderr,
            flush=True,
        )
        return rec

    def close():
        loop.run_until_complete(state["stack"].aclose())
        loop.close()

    answer.close = close
    answer.spent = spent
    return answer


def model_report(rows: list[dict], log: list[dict], spent: float) -> dict:
    """Model vs code on the same sampled questions: core pass of each, headline parity, the
    fallback rate and its reasons, latency and cost."""
    import math

    m = [r for r in rows if r.get("model")]
    if not m:
        return {"answers": 0}
    lat = sorted(r["latency_s"] for r in m)

    def pc(p):
        return lat[max(0, math.ceil(p * len(lat)) - 1)]

    fell = [r for r in m if r.get("source") != "model"]
    reasons = collections.Counter(x for r in fell for x in (r.get("reasons") or ["(none)"]))
    per = {}
    for iid in dict.fromkeys(r["intent"] for r in m):
        rs = [r for r in m if r["intent"] == iid]
        per[iid] = {
            "n": len(rs),
            "model_core": _rate(r["core"] for r in rs),
            "code_core": _rate(r["code_core"] for r in rs),
            "parity": _rate(r["parity"] for r in rs),
        }
    return {
        "answers": len(m),
        "model_core": _rate(r["core"] for r in m),
        "code_core_same_questions": _rate(r["code_core"] for r in m),
        "headline_parity": _rate(r["parity"] for r in m),
        "fallback_rate": round(len(fell) / len(m), 3),
        "fallback_reasons": dict(reasons.most_common()),
        "latency_p50_s": pc(0.5),
        "latency_p95_s": pc(0.95),
        "latency_max_s": lat[-1],
        "usd": round(spent, 4),
        "usd_per_answer": round(spent / len(m), 5),
        "tokens_in": sum(r.get("tokens_in", 0) for r in m),
        "tokens_out": sum(r.get("tokens_out", 0) for r in m),
        "cap_usd": SPEND_CAP_USD,
        "skipped_at_cap": sum(1 for r in rows if r.get("model_skipped")),
        "intents": per,
    }


# ---- CLI ---------------------------------------------------------------------------------------


def cmd_truth(args) -> None:
    from ninety.eval.ask_grade import truth as T

    insights = load_insights(args.insights)
    tr = T.load(args.run, args.work, args.cache, insights.fixture)
    intents, _ = G.load_intents()
    tab = T.table(tr, [it for it in intents if it["kind"] != "chip"], list(TIMES), G.windows)
    tab["_roster"] = [[v["name"], v["team"]] for v in tr.names.values()]
    T.save(tab, args.out)
    print(f"{args.out}: {len(tab) - 1} truth values")


def cmd_grade(args) -> None:
    from ninety.eval.ask_grade import truth as T

    if args.rebuild_insights:
        args.insights = rebuild_insights(args.rebuild_insights, args.out.with_suffix(".insights.json"))
    insights = load_insights(args.insights)
    intents, clubs = G.load_intents()
    table = T.read(args.truth_table)
    tol = G.load_tolerances()
    log: list[dict] = []
    answer = model_answerer(insights, intents, log) if args.model else None
    try:
        rows = run(insights, intents, table, tol, clubs, answer=answer)
    finally:
        if answer is not None:
            answer.close()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("".join(json.dumps(r, default=str) + "\n" for r in rows))
    s = summarise(rows)
    s["label"] = args.label
    if args.model:
        s["model"] = model_report(rows, log, answer.spent["usd"])
        print(json.dumps({k: v for k, v in s["model"].items() if k != "intents"}))
    args.out.with_suffix(".summary.json").write_text(json.dumps(s, indent=1) + "\n")
    print(
        json.dumps(
            {
                "label": args.label,
                "n": s["n"],
                "core": s["core"],
                "pass": s["pass"],
                "chips_core": s["chips"].get("core"),
                "chips_answered": s["chips"].get("answered"),
            }
        )
    )
    for iid, d in s["intents"].items():
        print(
            f"{iid:14} pass {d['pass']:.2f}  "
            + "  ".join(
                f"{k[:7]} {'-' if d[k] is None else f'{d[k]:.2f}'}" for k in d if k not in ("n", "pass")
            )
        )


FIXTURE = HERE.parents[2] / "tests" / "fixtures" / "ask-grade-insights-8324.json.gz"
BASELINE = HERE / "baseline.json"
RATCHETED = ("core", *G.CHECKS, "pass")  # each column, per intent and overall: may only go up


def ratchet_rates(insights_path: Path = FIXTURE) -> dict:
    """The ratcheted rates of the code path on the frozen fixture: overall and per intent."""
    from ninety.eval.ask_grade import truth as T

    intents, clubs = G.load_intents()
    rows = run(load_insights(insights_path), intents, T.read(TRUTH_TABLE), G.load_tolerances(), clubs)
    s = summarise(rows)
    return {
        "all": {c: s[c] for c in RATCHETED},
        "chips": {c: s["chips"][c] for c in RATCHETED},
        "intents": {k: {c: v[c] for c in RATCHETED} for k, v in s["intents"].items()},
    }


def cmd_baseline(args) -> None:
    rates = ratchet_rates(args.insights)
    body = {
        "about": "The Ask's code path on tests/fixtures/ask-grade-insights-8324.json.gz, graded by "
        "ninety/eval/ask_grade. tests/test_ask_grade.py fails if any rate here goes down; raise it with "
        "`uv run python -m ninety.eval.ask_grade.run baseline` when a change raises it. A change to how the "
        "insights are built refreshes the fixture first (gzip the insights `grade --rebuild-insights "
        "runs/demo-8324-final` writes with that code) in the same PR.",
        **rates,
    }
    BASELINE.write_text(json.dumps(body, indent=1) + "\n")
    print(f"{BASELINE}: core {rates['all']['core']}, all checks {rates['all']['pass']}")


EXPORT = ("ninety", "schemas", "docs/GROUNDING.md", "pyproject.toml")  # what a ref needs to answer


def _graded_ref(ref: str, insights: Path | None, package: Path | None, work: Path) -> list[dict]:
    """Grade one git ref's Ask: export the ref (git archive), put this checkout's grader in it, so
    both sides of a comparison are graded by the same rules, and run `grade` with the export first
    on the path."""
    import shutil
    import tarfile
    import tempfile

    root = HERE.parents[2]
    work.mkdir(parents=True)
    with tempfile.TemporaryFile() as tar:
        subprocess.run(["git", "archive", ref, *EXPORT], cwd=root, stdout=tar, check=True)
        tar.seek(0)
        with tarfile.open(fileobj=tar) as tf:
            tf.extractall(work, filter="data")
    dest = work / "ninety" / "eval" / "ask_grade"
    shutil.rmtree(dest, ignore_errors=True)
    shutil.copytree(HERE, dest, ignore=shutil.ignore_patterns("__pycache__"))
    out = work / "rows.jsonl"
    src = ["--rebuild-insights", str(package)] if package else ["--insights", str(insights)]
    cmd = [
        sys.executable,
        "-m",
        "ninety.eval.ask_grade.run",
        "grade",
        *src,
        "--label",
        ref,
        "--out",
        str(out),
    ]
    subprocess.run(
        cmd, cwd=work, env={**os.environ, "PYTHONPATH": str(work)}, check=True, stdout=subprocess.DEVNULL
    )
    return [json.loads(x) for x in out.read_text().splitlines() if x.strip()]


def delta_table(before: str, after: str, a: dict, b: dict) -> str:
    """Markdown: the core pass rate per intent before and after, then every check over all answers."""

    def pct(v):
        return "–" if v is None else f"{100 * v:.0f}%"

    def diff(x, y):
        return "" if x is None or y is None or round(100 * (y - x)) == 0 else f"{100 * (y - x):+.0f}"

    lines = [f"| Intent (core pass) | {before} | {after} | Δ |", "|---|---|---|---|"]
    for iid in a["intents"]:
        x, y = a["intents"][iid].get("core"), b["intents"].get(iid, {}).get("core")
        lines.append(f"| {iid} | {pct(x)} | {pct(y)} | {diff(x, y)} |")
    lines.append(
        f"| **all** | **{pct(a['core'])}** | **{pct(b['core'])}** | **{diff(a['core'], b['core'])}** |"
    )
    lines.append(
        f"| chips | {pct(a['chips'].get('core'))} | {pct(b['chips'].get('core'))} | "
        f"{diff(a['chips'].get('core'), b['chips'].get('core'))} |"
    )
    lines += ["", f"| Check (all answers) | {before} | {after} | Δ |", "|---|---|---|---|"]
    for c in (*G.CHECKS, "pass"):
        lines.append(
            f"| {'all checks' if c == 'pass' else c} | {pct(a.get(c))} | {pct(b.get(c))} | "
            f"{diff(a.get(c), b.get(c))} |"
        )
    return "\n".join(lines)


def cmd_compare(args) -> None:
    import tempfile

    with tempfile.TemporaryDirectory(prefix="ask-grade-compare-") as tmp:
        sums = []
        for i, ref in enumerate(args.refs):
            rows = _graded_ref(ref, args.insights, args.rebuild_insights, Path(tmp) / str(i))
            sums.append(summarise(rows))
    print(delta_table(args.refs[0], args.refs[1], *sums))


def main(argv: list[str] | None = None) -> None:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "--compare":  # `run.py --compare REF_A REF_B ...` is `run.py compare ...`
        argv[0] = "compare"
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("truth", help="write the frozen truth table (reads the answer key)")
    t.add_argument(
        "--run", type=Path, required=True, help="the full simulated run (events.jsonl, frames.jsonl)"
    )
    t.add_argument("--work", type=Path, required=True, help="the footage's work folder (clips/*/meta.json)")
    t.add_argument(
        "--insights", type=Path, required=True, help="any insights of the match, for its team sheets"
    )
    t.add_argument("--cache", type=Path, required=True, help="the frame cache (.npz; built if missing)")
    t.add_argument("--out", type=Path, default=TRUTH_TABLE)
    g = sub.add_parser("grade", help="ask every question and grade the answers")
    g.add_argument("--insights", type=Path)
    g.add_argument(
        "--rebuild-insights",
        type=Path,
        default=None,
        metavar="PACKAGE",
        help="rebuild the insights from a package (tracked.json, detected, scorebug) first",
    )
    g.add_argument("--truth-table", type=Path, default=TRUTH_TABLE)
    g.add_argument("--label", default="run")
    g.add_argument("--out", type=Path, required=True)
    g.add_argument(
        "--model",
        action="store_true",
        help=f"answer ~{MODEL_SHARE:.0%} through the Foundry agents (costs money; {PASSCODE_ENV})",
    )
    b = sub.add_parser("baseline", help="write baseline.json from the frozen fixture (code path)")
    b.add_argument("--insights", type=Path, default=FIXTURE)
    c = sub.add_parser(
        "compare", help="grade two git refs with this checkout's grader; print a per-intent delta table"
    )
    c.add_argument("refs", nargs=2, metavar="REF")
    c.add_argument("--insights", type=Path, default=FIXTURE, help="the insights both refs answer from")
    c.add_argument(
        "--rebuild-insights",
        type=Path,
        default=None,
        metavar="PACKAGE",
        help="rebuild the insights with each ref's own code from a package (heavy: use heavy.sh)",
    )
    args = ap.parse_args(argv)
    if args.cmd == "compare":
        cmd_compare(args)
    elif args.cmd == "truth":
        cmd_truth(args)
    elif args.cmd == "baseline":
        cmd_baseline(args)
    else:
        if args.insights is None and args.rebuild_insights is None:
            ap.error("grade needs --insights or --rebuild-insights")
        cmd_grade(args)


if __name__ == "__main__":
    main()
