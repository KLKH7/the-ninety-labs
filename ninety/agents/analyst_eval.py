"""Measure the Analyst: how often its first draft would air, and how Foundry's agent evaluators
rate the same responses.

    uv run python -m ninety.agents.analyst_eval              # writes docs/eval/analyst.md
    uv run python -m ninety.agents.analyst_eval --foundry    # also records both in Foundry

The published Analyst (the version pinned in foundry_agents.json) writes one claim per match
minute, reading the match only through the MCP server, which Foundry calls. Our fact-checker (code
checks, then the published Judge) decides whether that first draft would reach the screen: the
number that matters on air, decided in code and by the Judge, not by an evaluator model.
Foundry's built-in evaluators (task adherence, intent resolution, tool call accuracy) then score
the stored responses by id; they are model-graded opinions, reported beside our verdicts, never in
place of them.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import datetime
import subprocess
from pathlib import Path

from agent_framework.foundry import FoundryAgent

from ninety import config
from ninety.agents import credentials, evidence, foundry, foundry_evals
from ninety.agents.factcheck import check
from ninety.agents.judge import judge
from ninety.agents.slice import analyst_prompt, parse_claim
from ninety.match.facts import events_in
from ninety.mcp import match_server

ROOT = Path(__file__).resolve().parents[2]
FOUNDRY_EVAL = "ninety-analyst-first-draft"
EVALUATORS = ["task_adherence", "intent_resolution", "tool_call_accuracy"]
MINUTES = match_server.MINUTES  # one claim per minute of a served match


async def drafts(seeds: list[int]) -> tuple[list[dict], str, dict]:
    """One first draft per minute per seed, each with its response id and the fact-checker's
    verdict. Returns the rows, which agent versions ran, and their definitions
    (ninety/agents/evidence.py)."""
    async with credentials.new_credential() as credential:
        # Signed in before the simulations, which can outlast agents-live's sign-in (credentials.py).
        await credentials.sign_in(credential)
        known_by_seed = {s: {e["id"]: e for e in events_in(s, MINUTES, 1, MINUTES + 1)} for s in seeds}
        return await _drafts(credential, seeds, known_by_seed)


async def _drafts(
    credential, seeds: list[int], known_by_seed: dict[int, dict]
) -> tuple[list[dict], str, dict]:
    rows, ran, defs = [], "", {}
    for seed in seeds:
        known = known_by_seed[seed]
        async with contextlib.AsyncExitStack() as stack:
            agents, labels = [], []
            locals_ = foundry.slice_agents(foundry.chat_client(credential))
            defs = evidence.record(locals_)
            for local in locals_:
                name, version = foundry.pinned(local)
                labels.append(f"{name}:{version}")
                published = FoundryAgent(
                    project_endpoint=config.FOUNDRY_PROJECT,
                    agent_name=name,
                    agent_version=version,
                    credential=credential,
                )
                agents.append(await stack.enter_async_context(published))
            analyst, judge_agent = agents
            ran = ", ".join(labels)
            for minute in range(1, MINUTES + 1):
                response = await analyst.run(analyst_prompt(match_server.match_id(seed), minute))
                row = {
                    "seed": seed,
                    "minute": minute,
                    "response_id": response.response_id,
                    "text": response.text,
                }
                try:
                    claim = parse_claim(response.text)
                except (ValueError, AttributeError) as e:  # not the JSON the instructions ask for
                    rows.append(
                        {**row, "claim": "", "verdict": "reject", "reasons": [f"unparseable reply: {e}"]}
                    )
                    continue
                verdict = check(claim, known)
                if verdict.ok:
                    verdict = await judge(judge_agent, claim, [known[i] for i in claim.evidence])
                rows.append(
                    {
                        **row,
                        "claim": claim.text,
                        "verdict": "accept" if verdict.ok else "reject",
                        "reasons": verdict.reasons,
                        "category": verdict.category,
                    }
                )
    return rows, ran, defs


async def foundry_scores(response_ids: list[str]) -> dict:
    from agent_framework.foundry import evaluate_traces

    async with credentials.new_credential() as credential:
        await credentials.sign_in(credential)
        results = await evaluate_traces(
            response_ids=response_ids,
            evaluators=EVALUATORS,
            client=foundry.chat_client(credential),
            model=config.MODEL,
            eval_name="ninety-analyst-agent-evaluators",
            timeout=900,
        )
    return {
        "status": results.status,
        "report_url": results.report_url,
        "per_evaluator": results.per_evaluator,
    }


def report(
    rows: list[dict], seeds: str, ran: str, recorded: dict | None, scored: dict | None, *, defs: dict,
) -> str:
    sha = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True
    ).stdout.strip()
    aired = sum(r["verdict"] == "accept" for r in rows)
    lines = [
        "# Analyst evaluation",
        "",
        f"Generated by `uv run python -m ninety.agents.analyst_eval` on {datetime.date.today()} at commit "
        f"`{sha}`, simulator seeds {seeds}, minutes 1 to {MINUTES}, agents {ran} on `{config.MODEL}`. The "
        "Analyst writes one claim per minute; the fact-checker (code checks, then the Judge) decides "
        "whether that first draft would air.",
        "",
        evidence.md_line(defs),
        "",
        f"**First drafts that would air:** {aired}/{len(rows)}.",
        "",
    ]
    if recorded:
        lines += [f"In Foundry: [our verdicts]({recorded['report_url']}) (`{FOUNDRY_EVAL}`).", ""]
    if scored:
        lines += [
            f"**Foundry agent evaluators** ([run]({scored['report_url']}), model-graded, status "
            f"{scored['status']}):",
            "",
            "| Evaluator | Passed | Failed | Errored |",
            "|---|---|---|---|",
        ]
        for name, counts in sorted((scored.get("per_evaluator") or {}).items()):
            cells = [str(counts.get(k, 0)) for k in ("passed", "failed", "errored")]
            lines.append(f"| {name} | " + " | ".join(cells) + " |")
        lines.append("")
    lines += [
        "## Every draft",
        "",
        "| Seed | Minute | Verdict | Claim | Why rejected |",
        "|---|---|---|---|---|",
    ]
    for r in rows:
        claim = r["claim"].replace("|", "/")
        why = "; ".join(r["reasons"]).replace("|", "/")
        lines.append(f"| {r['seed']} | {r['minute']} | {r['verdict']} | {claim} | {why} |")
    return "\n".join(lines) + "\n"


def refuse_outage(rows: list[dict]) -> None:
    """NothingMeasured when too many minutes got no answer: an empty Analyst reply, or a Judge
    service error or timeout on its draft. That run measured an outage, not the Analyst (lesson 131)."""
    unanswered = sum(not r["text"] or r.get("category") in {"service", "timeout"} for r in rows)
    evidence.refuse_outage(unanswered, len(rows), "minutes")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--seeds", default="21,33", help="comma-separated simulator seeds (held out)")
    ap.add_argument("--out", type=Path, default=ROOT / "docs/eval/analyst.md")
    ap.add_argument("--foundry", action="store_true", help="record in Foundry and run its agent evaluators")
    args = ap.parse_args()
    rows, ran, defs = asyncio.run(drafts([int(s) for s in args.seeds.split(",")]))
    refuse_outage(rows)  # before anything is recorded in Foundry or written
    recorded = scored = None
    if args.foundry:
        recorded = foundry_evals.record(
            FOUNDRY_EVAL,
            f"seeds {args.seeds}, {ran}",
            [
                {
                    "seed": str(r["seed"]),
                    "minute": str(r["minute"]),
                    "claim": r["claim"],
                    "verdict": r["verdict"],
                    "expected": "accept",
                    "reasons": "; ".join(r["reasons"]),
                }
                for r in rows
            ],
            [foundry_evals.equals("first draft would air", "verdict", "expected")],
        )
        scored = asyncio.run(foundry_scores([r["response_id"] for r in rows if r["response_id"]]))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(report(rows, args.seeds, ran, recorded, scored, defs=defs))
    print(args.out.read_text())


if __name__ == "__main__":
    main()
