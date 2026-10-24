"""Tool-choice accuracy of the Companion on match questions: does it call the tool that answers?

Scored on the labelled questions in docs/eval/companion-tools-questions.json (held-out seeds
920001 and 920002, labelled before any score). A plan is right when it calls the labelled tool, at
most three tools in all, or calls none for a question no tool answers. Two planners are scored
apart, never pooled (deterministic and model-graded results stay apart):

- code: the keyword router (`companion_match.route`), free, always run;
- model: the Companion's plan step, only with --live, which calls the published model and costs
  money (tell the Coordinator first). A request the model never answered is counted apart from
  a wrong plan (lesson 131). With --live the model's answers are also run over the stand-in match
  (docs/eval/standin-insights-seed7.json), fact-checked and judged, and timed end to end.

    uv run python -m ninety.eval.companion_tools --out docs/eval/companion-tools.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import time
from collections import Counter
from decimal import Decimal
from pathlib import Path

from ninety.agents import companion_match as cm
from ninety.agents.contracts import Question

QUESTIONS = Path(__file__).resolve().parents[2] / "docs" / "eval" / "companion-tools-questions.json"


class _Clubs:
    """Just enough of MatchInsights for the plan step: the two clubs."""

    def __init__(self, names):
        self.fixture = type("F", (), {"clubs": {"home": names[0], "away": names[1]}})()


def right(chosen: list[str], label: str | None) -> bool:
    if label is None:
        return not chosen
    return label in chosen and len(chosen) <= cm.MAX_TOOLS


def score(plans: list[tuple[dict, list[str] | None]]) -> dict:
    answered = [(q, c) for q, c in plans if c is not None]
    ok = [right(c, q["tool"]) for q, c in answered]
    by_tool: dict[str, list[bool]] = {}
    for (q, _), r in zip(answered, ok, strict=True):
        by_tool.setdefault(str(q["tool"]), []).append(r)
    return {
        "questions": len(plans),
        "answered": len(answered),
        "unanswered": len(plans) - len(answered),
        "right": sum(ok),
        "accuracy": round(sum(ok) / len(ok), 3) if ok else None,
        "by_tool": {t: f"{sum(v)}/{len(v)}" for t, v in sorted(by_tool.items())},
        "wrong": [
            {"text": q["text"], "label": q["tool"], "chose": c}
            for (q, c), r in zip(answered, ok, strict=True)
            if not r
        ],
    }


async def model_plans(questions: list[dict], ask) -> tuple[list, list[float]]:
    out, ms = [], []
    for q in questions:
        names = cm_clubs(q)
        question = Question("eval", None, q["text"], 60.0 * (q["minute"] - 1) + 30)
        t0 = time.perf_counter()
        try:
            reply = await ask(cm.plan_prompt(question, _Clubs(names)))
            ms.append((time.perf_counter() - t0) * 1000)
            body = cm.first_object(reply)  # the plan only, as the service reads it
            out.append((q, [c["name"] for c in cm._calls(body, _Clubs(names), q["minute"])]))
        except Exception:  # noqa: BLE001  an outage or malformed reply: not answered, counted apart
            out.append((q, None))
    return out, ms


def cm_clubs(q: dict) -> list[str]:
    return SEEDS[str(q["seed"])]


SEEDS: dict[str, list[str]] = {}


def follow_up_quality(answers: list[tuple[str, tuple[str, ...]]], mi) -> dict:
    """For each answered question's suggestions: are there three, can the tools answer each now
    (re-checked through the code path), and is none a repeat (of the question, of each other, or of
    the question's topic: the same tools)?"""
    rows, full, ok_all = [], 0, 0
    for question, ups, answer_club in answers:
        q_tools = set(cm.route(question))
        answerable = [cm.answerable(u, mi, 60.0 * mi.minutes - 1) for u in ups]
        named = [c for c in mi.fixture.clubs.values() if c.lower() in question.lower()]
        # Relevant: a suggestion names the club asked about, or the club the answer was about.
        allowed = {*named, answer_club} - {None}
        off_club = len(named) == 1 and any(
            c.lower() in u.lower() for u in ups for c in mi.fixture.clubs.values() if c not in allowed
        )
        repeat = (
            len(set(ups)) != len(ups)
            or any(u.lower() == question.lower() for u in ups)
            or any(q_tools and set(cm.route(u)) == q_tools for u in ups)
        )
        good = len(ups) == cm.FOLLOW_UP_COUNT and all(answerable) and not repeat and not off_club
        full += len(ups) == cm.FOLLOW_UP_COUNT
        ok_all += good
        rows.append(
            {
                "question": question,
                "follow_ups": list(ups),
                "answerable": answerable,
                "repeat": repeat,
                "off_club": off_club,
            }
        )
    n = len(answers)
    return {
        "questions": n,
        "three_offered": full,
        "all_good": ok_all,
        "answerable": f"{sum(sum(r['answerable']) for r in rows)}/{sum(len(r['follow_ups']) for r in rows)}",
        "repeats": sum(r["repeat"] for r in rows),
        "off_club": sum(r["off_club"] for r in rows),
        "rows": rows,
    }


def _club_of(result, mi) -> str | None:
    """The club the answer's first cited fact is about."""
    known = mi.known()
    for i in result.answer.evidence:
        f = known.get(i)
        if f and f.get("team"):
            return mi.fixture.clubs[f["team"]]
        if i.count(":") >= 2 and i.split(":")[1] in mi.fixture.clubs:  # a summary: kind:team:window
            return mi.fixture.clubs[i.split(":")[1]]
    return None


def code_follow_ups(questions: list[dict]) -> dict:
    """Code's answers to each question on the stand-in match, and their suggestions' quality."""
    from ninety.intel.match_insights import MatchInsights

    mi = MatchInsights.from_dict(json.loads(STANDIN.read_text()))
    out = []
    for q in questions:
        a, b = SEEDS[str(q["seed"])]
        text = q["text"].replace(a, mi.fixture.clubs["home"]).replace(b, mi.fixture.clubs["away"])
        r = asyncio.run(
            cm.answer_match(Question("eval", None, text, 60.0 * min(q["minute"], mi.minutes) - 1), mi)
        )
        if r.answer.status == "verified":
            out.append((text, r.answer.follow_ups, (r.answer.visual or {}).get("club") or _club_of(r, mi)))
    return follow_up_quality(out, mi)


def headline_fits(question: str, answer, mi) -> bool:
    """Whether an answer's headline is the direct answer its question asks for: a player or club
    (no number) for who or which, a number with its unit for how many or how fast, a place for where
    (a number when no place was measured). Every number it shows is one the sentence says."""
    from ninety.intel.teamsheet import SHORT

    head, kind = answer.headline, cm.question_kind(question)
    if head is None:
        return kind is None
    if any(n not in re.findall(r"\d+(?:\.\d+)?", answer.text) for n in re.findall(r"\d+(?:\.\d+)?", head)):
        return False
    if kind == "who":
        sheet = {s["name"] for t in ("home", "away") for s in mi.fixture.as_dict()["sheets"][t]}
        return not re.search(r"\d", head) and (
            head in sheet or head in set(SHORT.values()) | set(mi.fixture.clubs.values()) or "'s " in head
        )
    if kind == "number":
        return head[:1].isdigit()
    if kind == "where":
        return head.startswith(tuple(cm.CHANNEL_PHRASE.values())) or head[:1].isdigit()
    return head[:1].isdigit()


def code_headlines(questions: list[dict]) -> dict:
    """Code's verified answers to each held-out question on the stand-in match: does the headline
    fit the question's kind?"""
    from ninety.intel.match_insights import MatchInsights

    mi = MatchInsights.from_dict(json.loads(STANDIN.read_text()))
    rows, by = [], Counter()
    for q in questions:
        a, b = SEEDS[str(q["seed"])]
        text = q["text"].replace(a, mi.fixture.clubs["home"]).replace(b, mi.fixture.clubs["away"])
        r = asyncio.run(
            cm.answer_match(Question("eval", None, text, 60.0 * min(q["minute"], mi.minutes) - 1), mi)
        )
        if r.answer.status != "verified":
            continue
        kind = cm.question_kind(text) or "other"
        fits = headline_fits(text, r.answer, mi)
        by[(kind, fits)] += 1
        rows.append({"question": text, "kind": kind, "headline": r.answer.headline, "fits": fits})
    kinds = sorted({k for k, _ in by})
    return {
        "answers": len(rows),
        "fit": sum(r["fits"] for r in rows),
        "by_kind": {k: f"{by[(k, True)]}/{by[(k, True)] + by[(k, False)]}" for k in kinds},
        "rows": rows,
    }


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=Path, default=Path("docs/eval/companion-tools.json"))
    ap.add_argument(
        "--live", action="store_true", help="also score the published model's plans (costs money)"
    )
    args = ap.parse_args(argv)
    body = json.loads(QUESTIONS.read_text())
    SEEDS.update(body["seeds"])
    questions = body["questions"]
    code = [(q, cm.route(q["text"])) for q in questions]
    report = {
        "questions_file": str(QUESTIONS.name),
        "code": {**score(code)},
    }
    report["code"]["chosen"] = dict(Counter(t for _, c in code for t in c))
    report["code"]["follow_ups"] = code_follow_ups(questions)
    report["code"]["headlines"] = code_headlines(questions)
    if args.live:
        report["model"] = asyncio.run(live(questions))
    args.out.write_text(json.dumps(report, indent=1) + "\n")
    c = report["code"]
    md = [
        "# Companion tool choice on held-out questions",
        "",
        "Generated by `uv run python -m ninety.eval.companion_tools`. Questions: "
        "[companion-tools-questions.json](companion-tools-questions.json), seeds 920001 and 920002, "
        "labelled before any score. "
        + (
            "The published model's plans and answers were scored too (below), at the cost it states. "
            if "model" in report
            else "Code router only: the model's plan step needs a live run (not run here; nothing was "
            "spent). "
        )
        + "The router's word lists and the questions were written by the same author, and the position "
        "words that send a who-plays question to the team sheet (lesson 237) were added after the first "
        "live run's misses on these questions were read: the lineup rows are no longer held out.",
        "",
        f"- Code router: **{c['right']}/{c['answered']}** right ({c['accuracy']}).",
        f"- Follow-up suggestions on code's verified answers (stand-in match): "
        f"{c['follow_ups']['all_good']}/{c['follow_ups']['questions']} answers offer three that the tools "
        f"can answer and none repeats; {c['follow_ups']['answerable']} suggestions answerable, "
        f"{c['follow_ups']['repeats']} with a repeat, {c['follow_ups']['off_club']} about the other club.",
        "- By tool: " + ", ".join(f"{k} {v}" for k, v in c["by_tool"].items()),
        f"- Headlines on code's verified answers (stand-in match): {c['headlines']['fit']}/"
        f"{c['headlines']['answers']} are the direct answer the question's kind asks for (a name for "
        "who, a number with its unit for how many, a place for where); by kind: "
        + ", ".join(f"{k} {v}" for k, v in c["headlines"]["by_kind"].items()),
        "",
        "Wrong:",
        "",
        *[f'- "{w["text"]}": labelled {w["label"]}, chose {w["chose"] or "none"}' for w in c["wrong"]],
    ]
    if "model" in report:
        m = report["model"]
        p = m["plans"]
        md += [
            "",
            "## The published match Companion (live)",
            "",
            f"- Tool choice: **{p['right']}/{p['answered']}** right ({p['accuracy']}); "
            f"{p['unanswered']} not answered by the service (counted apart, lesson 131).",
            "- By tool: " + ", ".join(f"{k} {v}" for k, v in p["by_tool"].items()),
            f"- Plan latency: {m['plan_latency']}; answer end to end (plan, tools, answer, check, Judge): "
            f"{m['answer_latency']}.",
            f"- How answers ended on the stand-in match: {m['answers']} (code: the model's draft was "
            "refused or failed, and code's checked answer was shown).",
            f"- The agents, as pinned: {m['agents']}.",
            f"- Cost (estimated): {m['cost']}.",
        ]
    args.out.with_suffix(".md").write_text("\n".join(md) + "\n")
    print(json.dumps({k: v for k, v in report["code"].items() if k != "wrong"}))
    for w in report["code"]["wrong"]:
        print("wrong:", w)


STANDIN = QUESTIONS.parent / "standin-insights-seed7.json"  # ninety/eval/insight_standin.py, 20 minutes


# Estimates for the Judge's calls, whose prompt the judge function builds: its instructions
# (ninety/agents/judge.py INSTRUCTIONS, 3,316 characters) and a reply of a few statements.
JUDGE_PROMPT_TOKENS = 830
JUDGE_REPLY_TOKENS = 150


async def live(questions: list[dict]) -> dict:
    """The published match Companion and Judge: their plans scored like code's, then their answers
    over the stand-in match (each question asked of its clubs' places in it), with how each ended,
    the agents' pinned definitions, and what it cost (tokens estimated, priced as committed)."""
    from ninety.agents import foundry
    from ninety.api.companion import foundry_models
    from ninety.eval import latency_cost as lc
    from ninety.intel.match_insights import MatchInsights

    models = await foundry_models()
    used = {"in": 0, "out": 0, "calls": 0}

    async def ask(prompt):
        reply = await models.match_ask(prompt)
        used["in"] += lc.tokens(prompt)
        used["out"] += lc.tokens(reply)
        used["calls"] += 1
        return reply

    async def judge(claim, evidence):
        used["in"] += lc.tokens(json.dumps({"claim": claim.text, "evidence": evidence})) + JUDGE_PROMPT_TOKENS
        used["out"] += JUDGE_REPLY_TOKENS
        used["calls"] += 1
        return await models.judge(claim, evidence)

    plans, plan_ms = await model_plans(questions, ask)
    mi = MatchInsights.from_dict(json.loads(STANDIN.read_text()))
    ends, ms, rows, ups = Counter(), [], [], []
    for q in questions:
        a, b = SEEDS[str(q["seed"])]
        text = q["text"].replace(a, mi.fixture.clubs["home"]).replace(b, mi.fixture.clubs["away"])
        question = Question("eval", None, text, 60.0 * min(q["minute"], mi.minutes) - 1)
        t0 = time.perf_counter()
        r = await cm.answer_match(question, mi, ask, judge, timeout=30.0)
        ms.append((time.perf_counter() - t0) * 1000)
        end = f"{r.source}:{r.answer.status}"
        ends[end] += 1
        if r.answer.status == "verified":
            ups.append((text, r.answer.follow_ups, (r.answer.visual or {}).get("club") or _club_of(r, mi)))
        rows.append(
            {
                "question": text,
                "end": end,
                "text": r.answer.text,
                "tools": [c["name"] for c in r.tools],
                "reasons": list(r.reasons),
            }
        )
    usd = lc.price(lc.INPUT) * used["in"] + lc.price(lc.OUTPUT) * used["out"]
    registry = foundry.load_registry()
    return {
        "plans": score(plans),
        "plan_latency": latency(plan_ms),
        "answers": dict(ends),
        "answer_latency": latency(ms),
        "follow_ups": follow_up_quality(ups, mi),
        "rows": rows,
        "agents": {name: registry.get(name) for name in ("ninety-companion-match", "ninety-judge")},
        "cost": {
            "model": lc.PRICES["model"],
            "prices_read": lc.PRICES["read"],
            "calls": used["calls"],
            "input_tokens": used["in"],
            "output_tokens": used["out"],
            "usd_estimate": str(usd.quantize(Decimal("0.0001"))),
            "how": "tokens at 4 characters a token (latency_cost.tokens); each Judge call adds its "
            "instructions and a reply at the sizes in companion_tools",
        },
    }


def latency(ms: list[float]) -> dict:
    """p50 and p95 by nearest rank, as the latency report reads them (ninety/eval/latency_cost.py)."""
    from ninety.eval.latency_cost import percentile

    if not ms:
        return {}
    return {"p50_ms": round(percentile(ms, 0.5), 1), "p95_ms": round(percentile(ms, 0.95), 1), "n": len(ms)}


if __name__ == "__main__":
    main()
