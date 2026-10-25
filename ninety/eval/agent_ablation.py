"""The agent ablation: one agent with every tool, against the full multi-agent graph.

    uv run python -m ninety.eval.agent_ablation --live --out runs/eval    # agents-live task=ablation

On the held-out seeds (21 and 33), every minute of the served match runs through two arms:

- **one agent**: the slice's Analyst (`ninety-analyst`), one published agent, writes the minute's
  claim, and it airs as written: no Tactician, no Challenger, no fact-checking agent. This is what
  a single agent would put on screen.
- **graph**: the multi-agent workflow (ninety/agents/workflow.py): the moment Analyst, the
  Tactician, the Challenger, the fact-checking agent (code checks, confidence gate, the Judge with
  rewrites) and the Producer. Only verified claims air.

Both arms get the minute's events inline, from the match this commit simulated, under a match id no
server serves (a call to the match tools fails the call), and every aired claim of both arms is
then graded the same way, against that match's own
events (grading is the answer key's allowed use): the code checks (numbers, players, cited ids)
and the published Judge (meaning). The graph cannot air a claim its own fact-checker failed, so a
false claim it airs is one the grader's second Judge call disagrees with; the one-agent arm airs
whatever it writes. The report counts, per arm, what aired, how much of it was false, and what it
cost in model calls.

Without --live the arms take the models a caller passes (tests/test_agent_ablation.py scripts
them); only a live run is committed (docs/eval/ablation-agents.{md,json}, unedited).
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import functools
import json
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import replace
from pathlib import Path

from ninety.agents import evidence, workflow
from ninety.agents.contracts import Models
from ninety.agents.factcheck import Claim, Verdict, check
from ninety.agents.judge import judge as judge_call
from ninety.agents.slice import analyst_prompt, parse_claim
from ninety.match.facts import compact
from ninety.mcp import match_server

ROOT = Path(__file__).resolve().parents[2]
COMMAND = "uv run python -m ninety.eval.agent_ablation --live"
SEEDS = (21, 33)  # the held-out seeds (docs/EVALUATION.md)
MINUTES = match_server.MINUTES  # every served match is this long

Ask = Callable[[str], Awaitable[str]]
Judge = Callable[[Claim, list[dict]], Awaitable[Verdict]]


async def grade(claim: Claim, known: dict[str, dict], judge: Judge) -> dict:
    """The same grade for every aired claim: the code checks, then (if they pass) the Judge."""
    code = check(claim, known)
    verdict = await judge(claim, [known[i] for i in claim.evidence]) if code.ok else None
    true = code.ok and verdict is not None and verdict.ok
    return {
        "text": claim.text,
        "evidence": list(claim.evidence),
        "code_ok": code.ok,
        "judge_ok": None if verdict is None else verdict.ok,
        "true": true,
        "reasons": list(code.reasons if not code.ok else (verdict.reasons if verdict else [])),
    }


def window(known: dict[str, dict], minute: int) -> list[dict]:
    """The minute's events as both arms read them: inline, from the match this commit simulated and
    the grader grades against. The deployed match tools serve the matches the deployed image
    simulated, with its own engine: a one-agent run once aired a goal at 03:03 on seed 33, which had
    no shot here (lesson 90)."""
    return [e for e in known.values() if e["minute"] == minute]


async def one_agent_minute(
    ask: Ask, match: str, minute: int, known: dict[str, dict]
) -> tuple[list[Claim], int, str]:
    """The single agent's claim for the minute, aired unchecked. Returns the aired claims, the model
    calls, and why nothing aired, if nothing did."""
    try:
        reply = await ask(analyst_prompt(match, minute, events=window(known, minute)))
    except Exception as e:  # a failed call airs nothing
        return [], 1, f"{type(e).__name__}"
    try:
        claim = parse_claim(reply)
    except (ValueError, AttributeError) as e:
        return [], 1, f"unparseable reply ({type(e).__name__})"
    return ([claim], 1, "") if claim.text.strip() else ([], 1, "empty claim")


async def graph_minute(
    models: Models, events: list[dict], match: str, minute: int
) -> tuple[list[Claim], int, str]:
    """The workflow's verified claims for the minute, and its model calls."""
    result = await workflow.run_workflow(models, events, minute, match, inline_events=True)
    aired = [r.aired for r in result.reviews if r.aired is not None]
    held = sum(r.status == "held" for r in result.reviews)
    rejected = sum(r.status == "rejected" for r in result.reviews)
    failed = [s.detail for s in result.trace if s.role == "analyst" and s.action == "fail"]
    why = "" if aired else "; ".join([f"{len(result.reviews)} moment(s): {held} held, {rejected} rejected",
                                       *(f"analyst: {d}" for d in failed)])
    return aired, result.model_calls, why


async def run(
    graph_models: Models, one_agent: Ask, grader: Judge, events_by_seed: dict[int, list[dict]],
    minutes: int = MINUTES,
) -> dict:
    """Both arms over every minute of every seed, each aired claim graded."""
    arms: dict[str, list[dict]] = {"one agent": [], "graph": []}
    for seed, events in events_by_seed.items():
        # The inline events under a match id no server serves (lesson 90): a tool call errors.
        match = match_server.unserved(match_server.match_id(seed))
        known = {e["id"]: compact(e) for e in workflow.agent_events(events)}
        for minute in range(1, minutes + 1):
            for arm in arms:
                started = time.perf_counter()
                if arm == "one agent":
                    aired, calls, why = await one_agent_minute(one_agent, match, minute, known)
                else:
                    aired, calls, why = await graph_minute(graph_models, events, match, minute)
                seconds = time.perf_counter() - started
                graded = [await grade(c, known, grader) for c in aired]
                arms[arm].append({"seed": seed, "minute": minute, "aired": graded, "model_calls": calls,
                                  "seconds": round(seconds, 2), "why_none": why})
    return {"seeds": list(events_by_seed), "minutes": minutes,
            "arms": {a: summary(m) for a, m in arms.items()}, "minutes_by_arm": arms}


def summary(minutes: list[dict]) -> dict:
    aired = [c for m in minutes for c in m["aired"]]
    false = [c for c in aired if not c["true"]]
    calls = sum(m["model_calls"] for m in minutes)
    return {
        "minutes": len(minutes),
        "aired": len(aired),
        "false_aired": len(false),
        "false_by_code": sum(not c["code_ok"] for c in aired),
        "false_by_judge": sum(c["code_ok"] and c["judge_ok"] is False for c in aired),
        "true_aired": len(aired) - len(false),
        "minutes_with_an_insight": sum(bool(m["aired"]) for m in minutes),
        # Minutes lost because an agent called the match tools with the events inline (lesson 90).
        "minutes_read_the_tools": sum("ReadTheTools" in m["why_none"] for m in minutes),
        "model_calls": calls,
        "seconds": round(sum(m["seconds"] for m in minutes), 1),
    }


def results(body: dict) -> str:
    # Strict JSON: another program reads it (lesson 43).
    return json.dumps(body, indent=1, allow_nan=False) + "\n"


def pct(n: int, d: int) -> str:
    return f"{n}/{d} ({100 * n / d:.0f}%)" if d else f"{n}/0"


def report(body: dict, ran: str) -> str:
    one, graph = body["arms"]["one agent"], body["arms"]["graph"]
    seeds = ", ".join(map(str, body["seeds"]))
    lines = [
        "# Ablation: one agent with every tool, against the multi-agent graph",
        "",
        f"Generated by `{COMMAND}` in agents-live, on held-out seeds {seeds}, every minute of",
        f"the served match ({body['minutes']} each), with {ran}, at commit `{body.get('commit', 'unknown')}`",
        "(the engine that simulated the seeds). Committed as the run wrote it; live models vary from run",
        "to run. Data: `docs/eval/ablation-agents.json`.",
        "",
        evidence.md_line(body[evidence.KEY]),
        "",
        "- **one agent**: the slice's Analyst, one published agent, writes the minute's claim, and it airs",
        "  as written.",
        "- **graph**: the workflow (moment Analyst, Tactician, Challenger, fact-checking agent with the",
        "  confidence gate and the Judge, Producer); only verified claims air.",
        "",
        "Both arms get the minute's events inline, from the match this commit simulated, under a match",
        "id no server serves; an agent that calls the deployed match tools anyway (the deployed image's",
        "match, simulated with its own engine) fails that call. Every aired claim of both arms is graded",
        "the same way, against those events: the code checks (numbers, players, cited ids), then the",
        "published Judge. A claim is *false* if either fails it.",
        "",
        "| Arm | Claims aired | False on air | of which: code checks | of which: Judge "
        "| Minutes with an insight | Minutes lost to a tool call | Model calls |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for name, arm in (("one agent", one), ("graph", graph)):
        lines.append(
            f"| {name} | {arm['aired']} | {pct(arm['false_aired'], arm['aired'])} | {arm['false_by_code']} "
            f"| {arm['false_by_judge']} | {pct(arm['minutes_with_an_insight'], arm['minutes'])} "
            f"| {arm['minutes_read_the_tools']} of {arm['minutes']} | {arm['model_calls']} |"
        )
    lines += ["", "## False claims on air", ""]
    for name in ("one agent", "graph"):
        false = [(m, c) for m in body["minutes_by_arm"][name] for c in m["aired"] if not c["true"]]
        lines.append(f"### {name}: {len(false)}")
        lines.append("")
        for m, c in false:
            why = "; ".join(c["reasons"]) or "Judge: not supported"
            lines.append(f"- seed {m['seed']}, minute {m['minute']}: \"{c['text']}\" ({why})")
        if not false:
            lines.append("- none")
        lines.append("")
    lines += [
        "## Reading it",
        "",
        "- The graph's aired claims already passed the same code checks and a Judge call, so a false",
        "  claim on its row is one where the grader's second Judge call disagreed with the first.",
        "- The arms do not get the same budget: the one agent has one call a minute and no retry, the",
        "  graph several agents and rewrites. This compares what each puts on screen at its own cost",
        "  (the table gives both), not two designs at a matched number of calls.",
        "- The grader's Judge is the same published Judge the graph's fact-checker asked, so the",
        "  grade is correlated with the graph's own filter, which favours the graph. The code checks",
        "  are independent of it, and the table splits false claims by which check caught them.",
        "- An agent that calls the match tools while given its events inline fails that call",
        "  (`foundry.ReadTheTools`), so a minute's claims never come from the deployed image's match.",
        "  Such a minute airs nothing for that arm, and the table counts them: the one agent's",
        "  instructions say to use the tools, so it is the arm more likely to lose minutes this way.",
        "",
    ]
    return "\n".join(lines)


# --- live: the published agents, one signed-in credential -------------------------------------


@contextlib.asynccontextmanager
async def live_arms():
    """The graph's Models, the single agent and the grading Judge, all published versions."""
    from agent_framework.foundry import FoundryAgent

    from ninety import config
    from ninety.agents import credentials, foundry

    async with credentials.new_credential() as credential, contextlib.AsyncExitStack() as stack:
        await credentials.sign_in(credential)
        client = foundry.chat_client(credential)
        ran, agents = [], {}
        locals_ = {**foundry.workflow_agents(client), "one agent": foundry.slice_agents(client)[0]}
        for role, local in locals_.items():
            name, version = foundry.pinned(local)
            ran.append(f"{name}:{version}")
            agents[role] = await stack.enter_async_context(FoundryAgent(
                project_endpoint=config.FOUNDRY_PROJECT, agent_name=name, agent_version=version,
                credential=credential,
            ))

        def ask(role: str) -> Ask:
            async def answer(prompt: str) -> str:
                # Every arm gets its events inline: a call to the match tools fails the call.
                reply = await asyncio.wait_for(agents[role].run(prompt), workflow.MODEL_TIMEOUT_SECONDS)
                return foundry.inline_only(reply)

            return answer

        judge = functools.partial(judge_call, agents["judge"])
        models = replace(
            Models.scripted({}), analyst=ask("analyst"), tactician=ask("tactician"),
            challenger=ask("challenger"), judge=judge,
        )
        defs = evidence.record(locals_.values())
        yield models, ask("one agent"), judge, f"{', '.join(sorted(set(ran)))} on {config.MODEL}", defs


async def live(seeds: tuple[int, ...]) -> tuple[dict, str, dict]:
    async with live_arms() as (models, one_agent, judge, ran, defs):
        events = {s: workflow.simulated_events(s, MINUTES) for s in seeds}  # after the sign-in
        return await run(models, one_agent, judge, events), ran, defs


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--live", action="store_true", help="the published agents (Azure): the committed run")
    ap.add_argument("--seeds", default=",".join(map(str, SEEDS)))
    ap.add_argument("--out", type=Path, default=ROOT / "runs" / "eval")
    args = ap.parse_args()
    if not args.live:
        ap.error("the ablation is measured live (--live); tests/test_agent_ablation.py runs it on scripts")
    logging.getLogger("agent_framework").setLevel(logging.WARNING)
    body, ran, defs = asyncio.run(live(tuple(int(s) for s in args.seeds.split(","))))
    body["ran"] = ran
    body[evidence.KEY] = defs  # each agent's version and definition fingerprint (ninety/agents/evidence.py)
    body["commit"] = workflow._commit()  # the engine the seeds were simulated with, and everything else
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "ablation-agents.json").write_text(results(body))
    (args.out / "ablation-agents.md").write_text(report(body, ran))
    for name, arm in body["arms"].items():
        print(f"{name}: {arm['aired']} aired, {arm['false_aired']} false, {arm['model_calls']} model calls")


if __name__ == "__main__":
    main()
