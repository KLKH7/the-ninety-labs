"""The agent ablation: one agent with every tool, with and without the fact-checker, against the
full multi-agent graph.

    uv run python -m ninety.eval.agent_ablation --live --seeds 940001,940002 --name ablation-third-arm

    uv run python -m ninety.eval.agent_ablation --live --out runs/eval    # agents-live task=ablation

On the given seeds (21 and 33 by default, the committed two-arm run; 940001 and 940002 for the
three-arm run docs/eval/ablation-third-arm-plan.md fixed before it ran), every minute of the served
match runs through three arms:

- **one agent**: the slice's Analyst (`ninety-analyst`), one published agent, writes the minute's
  claim, and it airs as written: no Tactician, no Challenger, no fact-checking agent. This is what
  a single agent would put on screen.
- **one agent + fact-checker**: the same Analyst, then the slice's fact-checker (ninety/agents/slice.py:
  the code checks, the confidence gate and the Judge, with up to two rewrites). This separates what
  the fact-checker buys from what the graph's other agents buy.
- **graph**: the multi-agent workflow (ninety/agents/workflow.py): the moment Analyst, the
  Tactician, the Challenger, the fact-checking agent (code checks, confidence gate, the Judge with
  rewrites) and the Producer. Only verified claims air.

Every arm gets the minute's events inline, from the match this commit simulated, under a match id no
server serves (a call to the match tools fails the call), and every aired claim of every arm is
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
from ninety.agents import slice as single
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

# docs/eval/latency-cost.md's prices for gpt-4.1-mini, at the plan's ~3,000 tokens in and 150 out a call
# (docs/eval/ablation-third-arm-plan.md): tokens were not metered, so cost is estimated from calls.
USD_PER_CALL = 3000 * 0.0004 / 1000 + 150 * 0.0016 / 1000
BUDGET_USD = 0.50  # the plan's cost stop, approved by Kian

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
    """The minute's events as every arm reads them: inline, from the match this commit simulated and
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


async def checked_agent_minute(
    ask: Ask, judge: Judge, seed: int, match: str, minute: int, known: dict[str, dict],
    checker: dict | None = None,
) -> tuple[list[Claim], int, str]:
    """The same single agent, then the same fact-checker as the graph (ninety/agents/slice.py: the code
    checks, the confidence gate and the Judge; a rejected claim goes back with its reasons, at most
    slice.MAX_REWRITES times). Only a verified claim airs. Returns the aired claims, the model calls
    (the agent's and the Judge's), and why nothing aired, if nothing did; `checker` gathers what the
    fact-checker held, rejected, or let air after a rewrite."""
    calls = 0
    checked = {} if checker is None else checker
    for k in ("drafts", "held", "rejected", "rewritten"):
        checked.setdefault(k, 0)

    async def counted_ask(prompt: str) -> str:
        nonlocal calls
        calls += 1
        return await ask(prompt)

    async def counted_judge(claim: Claim, evidence: list[dict]) -> Verdict:
        nonlocal calls
        calls += 1
        return await judge(claim, evidence)

    try:
        outcome = await single.run_workflow(counted_ask, counted_judge, minute, False, seed, MINUTES, True,
                                            events=list(known.values()), stats=[], inline=True,
                                            match=match)
    except Exception as e:  # a failed call airs nothing, as for the other arms
        return [], calls, f"{type(e).__name__}"
    checked["drafts"] += outcome.attempts
    checked["rewritten"] += outcome.accepted and outcome.attempts > 1
    if outcome.accepted:
        return [outcome.claim], calls, ""
    checked[outcome.status if outcome.status == "held" else "rejected"] += 1
    return [], calls, f"{outcome.status} after {outcome.attempts} draft(s)"


async def graph_minute(
    models: Models, events: list[dict], match: str, minute: int, checker: dict | None = None
) -> tuple[list[Claim], int, str]:
    """The workflow's verified claims for the minute, and its model calls; `checker` gathers what the
    fact-checking agent held, rejected, or let air after a rewrite."""
    result = await workflow.run_workflow(models, events, minute, match, inline_events=True)
    aired = [r.aired for r in result.reviews if r.aired is not None]
    held = sum(r.status == "held" for r in result.reviews)
    rejected = sum(r.status == "rejected" for r in result.reviews)
    failed = [s.detail for s in result.trace if s.role == "analyst" and s.action == "fail"]
    if checker is not None:
        rewrites = {s.moment for s in result.trace if s.action == "rewrite"}
        checker.update(held=held, rejected=rejected,
                       rewritten=sum(r.aired is not None and r.moment_id in rewrites for r in result.reviews))
    why = "" if aired else "; ".join([f"{len(result.reviews)} moment(s): {held} held, {rejected} rejected",
                                       *(f"analyst: {d}" for d in failed)])
    return aired, result.model_calls, why


async def run(
    graph_models: Models, one_agent: Ask, grader: Judge, events_by_seed: dict[int, list[dict]],
    minutes: int = MINUTES, budget_usd: float = BUDGET_USD,
) -> dict:
    """Every arm over every minute of every seed, each aired claim graded. Starts no further minute
    once the estimated spend (every model call, the grader's too) reaches `budget_usd`."""
    arms: dict[str, list[dict]] = {"one agent": [], "one agent + fact-checker": [], "graph": []}
    graded_calls = 0

    async def counted_grader(claim: Claim, evidence: list[dict]) -> Verdict:
        nonlocal graded_calls
        graded_calls += 1
        return await grader(claim, evidence)

    def spent() -> float:
        return (graded_calls + sum(m["model_calls"] for ms in arms.values() for m in ms)) * USD_PER_CALL

    stopped = ""
    for seed, events in events_by_seed.items():
        # The inline events under a match id no server serves (lesson 90): a tool call errors.
        match = match_server.unserved(match_server.match_id(seed))
        known = {e["id"]: compact(e) for e in workflow.agent_events(events)}
        for minute in range(1, minutes + 1):
            if not stopped and spent() >= budget_usd:
                stopped = f"cost stop: ${spent():.2f} estimated before seed {seed} minute {minute}"
            if stopped:
                break
            for arm in arms:
                started = time.perf_counter()
                checker: dict = {}
                if arm == "one agent":
                    aired, calls, why = await one_agent_minute(one_agent, match, minute, known)
                elif arm == "one agent + fact-checker":
                    aired, calls, why = await checked_agent_minute(
                        one_agent, grader, seed, match, minute, known, checker
                    )
                else:
                    aired, calls, why = await graph_minute(graph_models, events, match, minute, checker)
                seconds = time.perf_counter() - started
                graded = [await grade(c, known, counted_grader) for c in aired]
                arms[arm].append({"seed": seed, "minute": minute, "aired": graded, "model_calls": calls,
                                  "seconds": round(seconds, 2), "why_none": why, "checker": checker})
    return {"seeds": list(events_by_seed), "minutes": minutes,
            "arms": {a: summary(m) for a, m in arms.items()}, "minutes_by_arm": arms,
            "grader_calls": graded_calls, "estimated_usd": round(spent(), 4), "stopped": stopped}


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
        **{k: sum(m.get("checker", {}).get(k, 0) for m in minutes)
           for k in ("held", "rejected", "rewritten")},
    }


def results(body: dict) -> str:
    # Strict JSON: another program reads it (lesson 43).
    return json.dumps(body, indent=1, allow_nan=False) + "\n"


def pct(n: int, d: int) -> str:
    return f"{n}/{d} ({100 * n / d:.0f}%)" if d else f"{n}/0"


ARM_WORDS = {
    "one agent": "the slice's Analyst, one published agent, writes the minute's claim, and it airs as "
    "written.",
    "one agent + fact-checker": "the same Analyst, then the same fact-checker as the graph (the code checks, "
    "the confidence gate and the Judge; a rejected claim goes back with its reasons, at most twice); only "
    "a verified claim airs.",
    "graph": "the workflow (moment Analyst, Tactician, Challenger, fact-checking agent with the confidence "
    "gate and the Judge, Producer); only verified claims air.",
}


def reading(arms: dict) -> str:
    """The plan's reading rule, fixed before any run was scored (docs/eval/ablation-third-arm-plan.md):
    exactly one of four outcomes, checked in order."""
    g, c = arms["graph"], arms["one agent + fact-checker"]

    def rate(arm: dict) -> float:
        return arm["false_aired"] / arm["aired"] if arm["aired"] else 0.0

    def beats(a: dict, b: dict) -> bool:
        return (a["true_aired"] >= b["true_aired"] and a["false_aired"] < b["false_aired"]) or (
            a["true_aired"] > b["true_aired"] and rate(a) <= rate(b)
        )

    if abs(g["true_aired"] - c["true_aired"]) <= 1 and abs(g["false_aired"] - c["false_aired"]) <= 1:
        return ("**Outcome 1, the single agent with the fact-checker matches the graph** by the plan's rule "
                "(within one true and one false claim): the fact-checker does the work, and the graph's "
                "extra agents buy only coverage, at their cost.")
    if beats(g, c):
        return ("**Outcome 2, the graph wins** by the plan's rule: at least as many true claims with fewer "
                "false ones on air, or more true claims at a false rate no higher.")
    if beats(c, g):
        return ("**Outcome 3, the single agent with the fact-checker wins** by the plan's rule: at least as "
                "many true claims with fewer false ones on air, or more true claims at a false rate no "
                "higher.")
    return "**Outcome 4, mixed** by the plan's rule: neither arm beats the other; no winner is drawn."


def checked(name: str, arm: dict) -> str:
    if name == "one agent" or "held" not in arm:  # no fact-checker, or a run from before the third arm
        return "n/a"
    return f"{arm['held']} / {arm['rejected']} / {arm['rewritten']}"


def report(body: dict, ran: str) -> str:
    arms = body["arms"]
    seeds = ", ".join(map(str, body["seeds"]))
    lines = [
        "# Ablation: one agent with every tool, with and without the fact-checker, against the multi-agent "
        "graph",
        "",
        f"Generated by `{COMMAND}`, on seeds {seeds}, every minute of",
        f"the served match ({body['minutes']} each), with {ran}, at commit `{body.get('commit', 'unknown')}`",
        "(the engine that simulated the seeds). Committed as the run wrote it; live models vary from run",
        f"to run. Data: `docs/eval/{body.get('name', 'ablation-agents')}.json`.",
        "",
        evidence.md_line(body[evidence.KEY]),
        "",
        *(f"- **{name}**: {ARM_WORDS[name]}" for name in arms),
        "",
        "Every arm gets the minute's events inline, from the match this commit simulated, under a match",
        "id no server serves; an agent that calls the deployed match tools anyway (the deployed image's",
        "match, simulated with its own engine) fails that call. Every aired claim of every arm is graded",
        "the same way, against those events: the code checks (numbers, players, cited ids), then the",
        "published Judge. A claim is *false* if either fails it.",
        "",
        "| Arm | Claims aired | True on air | False on air | of which: code checks | of which: Judge "
        "| Minutes with an insight | Minutes lost to a tool call | Held / rejected / aired after a rewrite "
        "| Model calls | Cost (est.) | Seconds a minute |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for name, arm in arms.items():
        lines.append(
            f"| {name} | {arm['aired']} | {arm['true_aired']} | {pct(arm['false_aired'], arm['aired'])} "
            f"| {arm['false_by_code']} | {arm['false_by_judge']} "
            f"| {pct(arm['minutes_with_an_insight'], arm['minutes'])} "
            f"| {arm['minutes_read_the_tools']} of {arm['minutes']} "
            f"| {checked(name, arm)} | {arm['model_calls']} "
            f"| ${arm['model_calls'] * USD_PER_CALL:.2f} | {arm['seconds'] / max(arm['minutes'], 1):.1f} |"
        )
    if "estimated_usd" in body:
        lines += ["", f"Estimated cost of the run: ${body['estimated_usd']:.2f}, from {body['grader_calls']} "
                  "grader calls and every arm's model calls (tokens not metered)."]
    if body.get("stopped"):
        lines += ["", f"**The run stopped early ({body['stopped']}).** The rule below is read on the "
                  "minutes run."]
    if "one agent + fact-checker" in arms:
        lines += ["", reading(arms)]
    lines += ["", "## False claims on air", ""]
    for name in arms:
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
        "- The checked arms' aired claims already passed the same code checks and a Judge call, so a",
        "  false claim on their rows is one where the grader's second Judge call disagreed with the first.",
        "- The arms do not get the same budget: the one agent has one call a minute and no retry, the",
        "  checked agent up to three drafts and their Judge calls, the graph several agents and rewrites.",
        "  This compares what each puts on screen at its own cost (the table gives both), not designs at",
        "  a matched number of calls.",
        "- Cost is estimated, as the plan fixes it: model calls times the price of ~3,000 tokens in and",
        "  150 out (gpt-4.1-mini global rates, docs/eval/latency-cost.md); tokens are not metered. A Judge",
        "  call retried after a timeout or service error counts once, so calls and cost are a floor.",
        "- *Held / rejected / aired after a rewrite* are each claim's final outcome, not how many drafts",
        "  were sent back. The two checked arms count *held* differently: the graph holds a moment whose",
        "  writer's call failed, while the checked agent's failed call loses its minute (a minute with",
        "  nothing aired, and the reason, in the data); the checked agent also rewrites a held claim,",
        "  as the live slice does, and the graph does not.",
        "- One run of live models: a second run would differ. The table claims nothing past this sample.",
        "- The grader's Judge is the same published Judge the checked agent's and the graph's",
        "  fact-checker asked, so the grade is correlated with their own filter, which favours both",
        "  over the unchecked agent. The code checks are independent of it, and the table splits false",
        "  claims by which check caught them.",
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
                ANSWERED["calls"] += 1  # the model answered, whatever the answer is worth
                return foundry.inline_only(reply)

            return answer

        judge = functools.partial(judge_call, agents["judge"])
        models = replace(
            Models.scripted({}), analyst=ask("analyst"), tactician=ask("tactician"),
            challenger=ask("challenger"), judge=judge,
        )
        defs = evidence.record(locals_.values())
        yield models, ask("one agent"), judge, f"{', '.join(sorted(set(ran)))} on {config.MODEL}", defs


ANSWERED = {"calls": 0}  # writer calls that returned in this process (the Judge's are not counted)


async def live(seeds: tuple[int, ...]) -> tuple[dict, str, dict]:
    async with live_arms() as (models, one_agent, judge, ran, defs):
        events = {s: workflow.simulated_events(s, MINUTES) for s in seeds}  # after the sign-in
        body = await run(models, one_agent, judge, events)
    if not ANSWERED["calls"]:
        # The plan's void run: no model answered at all, so nothing was measured and no report is
        # written (docs/eval/ablation-third-arm-plan.md, exclusions).
        raise SystemExit("no model answered: a void run, and no report written")
    return body, ran, defs


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--live", action="store_true", help="the published agents (Azure): the committed run")
    ap.add_argument("--seeds", default=",".join(map(str, SEEDS)))
    ap.add_argument("--out", type=Path, default=ROOT / "runs" / "eval")
    ap.add_argument("--name", default="ablation-agents",
                    help="the output files' name: ablation-third-arm for the plan's run (its own files)")
    args = ap.parse_args()
    if not args.live:
        ap.error("the ablation is measured live (--live); tests/test_agent_ablation.py runs it on scripts")
    logging.getLogger("agent_framework").setLevel(logging.WARNING)
    body, ran, defs = asyncio.run(live(tuple(int(s) for s in args.seeds.split(","))))
    body["ran"] = ran
    body[evidence.KEY] = defs  # each agent's version and definition fingerprint (ninety/agents/evidence.py)
    body["commit"] = workflow._commit()  # the engine the seeds were simulated with, and everything else
    body["name"] = args.name
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / f"{args.name}.json").write_text(results(body))
    (args.out / f"{args.name}.md").write_text(report(body, ran))
    for name, arm in body["arms"].items():
        print(f"{name}: {arm['aired']} aired, {arm['false_aired']} false, {arm['model_calls']} model calls")


if __name__ == "__main__":
    main()
