"""Thin slice through the whole stack: Foundry model, Agent Framework workflow, MCP tools,
a fact-checking step that can reject, and speech.

    uv run ninety-slice --minute 2                # one verified claim about minute 2
    uv run ninety-slice --minute 2 --plant        # tamper with the first draft to show a rejection
    uv run ninety-slice --minute 2 --speak a.mp3  # also speak the verified claim

The Analyst reads the match only through the MCP server. The Fact-checker is code
(ninety/agents/factcheck.py): it sends a rejected claim back with its reasons, at most twice.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import time
from dataclasses import dataclass, field

from agent_framework import Agent, Executor, MCPStdioTool, WorkflowBuilder, WorkflowContext, handler
from agent_framework.foundry import FoundryChatClient
from azure.identity import DefaultAzureCredential

from ninety import config
from ninety.agents.factcheck import Claim, check
from ninety.match.facts import events_in

MAX_REWRITES = 2

INSTRUCTIONS = """You are the Analyst for a football broadcast. Use the match tools to read the
events of the requested minute, then write ONE short sentence a commentator could say about the
most interesting moment in that minute, and why it matters.

Rules:
- Only state facts you read from the tools. Every number you write must be a field of an event
  you cite (minute, second, ball_speed_kmh, distance_m) or a count of the events you cite.
- Name players by their ids exactly as given (for example h7 or a10).
- Reply with JSON only: {"text": "<sentence>", "evidence": ["<event id>", ...]}"""


@dataclass
class Task:
    minute: int
    feedback: list[str] = field(default_factory=list)
    attempt: int = 0


@dataclass
class Draft:
    task: Task
    claim: Claim


@dataclass
class Outcome:
    accepted: bool
    claim: Claim
    attempts: int
    trace: list[str]


def parse_claim(text: str) -> Claim:
    body = re.search(r"\{.*\}", text, re.S)
    data = json.loads(body.group() if body else text)
    return Claim(text=str(data.get("text", "")), evidence=[str(i) for i in data.get("evidence", [])])


def tamper(claim: Claim) -> Claim:
    """Plant a false number so the fact-checker has something to catch."""
    return Claim(text=claim.text.rstrip(".") + ", at 143 km/h.", evidence=claim.evidence)


class AnalystExecutor(Executor):
    def __init__(self, agent: Agent, trace: list[str], plant: bool):
        super().__init__(id="analyst")
        self.agent, self.trace, self.plant = agent, trace, plant

    @handler
    async def write(self, task: Task, ctx: WorkflowContext[Draft]) -> None:
        prompt = f"Write the claim for minute {task.minute}."
        if task.feedback:
            prompt += " Your previous claim was rejected: " + "; ".join(task.feedback) + ". Fix it."
        started = time.perf_counter()
        response = await self.agent.run(prompt)
        claim = parse_claim(response.text)
        if self.plant and task.attempt == 0:
            claim = tamper(claim)
            self.trace.append("analyst: draft tampered on purpose (--plant)")
        seconds = time.perf_counter() - started
        self.trace.append(f"analyst: {claim.text!r} evidence={claim.evidence} ({seconds:.1f}s)")
        await ctx.send_message(Draft(task=task, claim=claim))


class FactCheckExecutor(Executor):
    def __init__(self, known: dict[str, dict], trace: list[str]):
        super().__init__(id="fact_checker")
        self.known, self.trace = known, trace

    @handler
    async def review(self, draft: Draft, ctx: WorkflowContext[Task, Outcome]) -> None:
        verdict = check(draft.claim, self.known)
        if verdict.ok:
            self.trace.append("fact_checker: accepted")
            await ctx.yield_output(Outcome(True, draft.claim, draft.task.attempt + 1, self.trace))
        elif draft.task.attempt < MAX_REWRITES:
            self.trace.append("fact_checker: rejected: " + "; ".join(verdict.reasons))
            await ctx.send_message(Task(draft.task.minute, verdict.reasons, draft.task.attempt + 1))
        else:
            self.trace.append("fact_checker: rejected, out of rewrites: " + "; ".join(verdict.reasons))
            await ctx.yield_output(Outcome(False, draft.claim, draft.task.attempt + 1, self.trace))


async def run_slice(minute: int, plant: bool, seed: int, minutes: float) -> Outcome:
    known = {e["id"]: e for e in events_in(seed, minutes, 1, int(minutes) + 1)}
    trace: list[str] = []
    tools = MCPStdioTool(
        name="match",
        command=sys.executable,
        args=["-m", "ninety.mcp.match_server"],
        env={"NINETY_SEED": str(seed), "NINETY_MINUTES": str(minutes)},
    )
    client = FoundryChatClient(
        project_endpoint=config.FOUNDRY_PROJECT, model=config.MODEL, credential=DefaultAzureCredential()
    )
    async with tools:
        agent = Agent(client=client, name="analyst", instructions=INSTRUCTIONS, tools=tools)
        analyst = AnalystExecutor(agent, trace, plant)
        checker = FactCheckExecutor(known, trace)
        # A rejected claim goes back to the analyst with the reasons, at most MAX_REWRITES times.
        builder = WorkflowBuilder(start_executor=analyst)
        workflow = builder.add_edge(analyst, checker).add_edge(checker, analyst).build()
        result = await workflow.run(Task(minute=minute))
    return result.get_outputs()[0]


def main() -> None:
    ap = argparse.ArgumentParser(description="Thin slice: Analyst -> Fact-checker over MCP, on Foundry.")
    ap.add_argument("--minute", type=int, default=2)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--minutes", type=float, default=5)
    ap.add_argument("--plant", action="store_true", help="tamper with the first draft to show a rejection")
    ap.add_argument("--speak", metavar="MP3", help="speak the verified claim to this file")
    args = ap.parse_args()

    started = time.perf_counter()
    outcome = asyncio.run(run_slice(args.minute, args.plant, args.seed, args.minutes))
    for line in outcome.trace:
        print(line)
    verdict = "ACCEPTED" if outcome.accepted else "REJECTED"
    print(f"{verdict} after {outcome.attempts} draft(s), {time.perf_counter() - started:.1f}s")
    if outcome.accepted and args.speak:
        from ninety.speech.tts import synthesize

        audio, seconds = synthesize(outcome.claim.text)
        with open(args.speak, "wb") as f:
            f.write(audio)
        print(f"spoken to {args.speak} in {seconds:.2f}s")
