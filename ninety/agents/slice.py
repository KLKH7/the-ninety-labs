"""Thin slice through the whole stack: Foundry model, Agent Framework workflow, MCP tools,
a fact-checking step that can reject, and speech.

    uv run ninety-slice --minute 2                # one verified claim about minute 2
    uv run ninety-slice --minute 2 --plant        # tamper with the first draft to show a rejection
    uv run ninety-slice --minute 2 --speak a.mp3  # also speak the verified claim
    uv run ninety-slice --minute 2 --plant --record replays/slice.json   # save the model's replies
    uv run ninety-slice --replay replays/slice.json                      # no Azure needed

The Analyst reads the match only through the MCP server. The Fact-checker runs the code checks
(ninety/agents/factcheck.py) and then the Judge (ninety/agents/judge.py), and sends a rejected
claim back with its reasons, at most twice.

--replay swaps only the two Foundry models for what they answered when recorded: the Analyst's
replies and the Judge's verdicts. The workflow, the handoffs and the code checks all run for real,
so anyone can run the slice without access to our Azure resources. If a prompt no longer matches
the recording (the code checks changed, say), the replay stops instead of pairing an old answer
with a new question.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import time
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from agent_framework import Agent, Executor, MCPStdioTool, WorkflowBuilder, WorkflowContext, handler
from agent_framework.foundry import FoundryChatClient
from azure.identity import DefaultAzureCredential

from ninety import config
from ninety.agents.factcheck import Claim, Verdict, check
from ninety.agents.judge import judge, judge_agent
from ninety.match.facts import events_in

MAX_REWRITES = 2
REPLAY_FORMAT = 2

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
class Turn:
    """One model answer: the Analyst's raw reply, or the Judge's verdict as JSON."""

    role: str
    prompt: str
    response: str


@dataclass
class Recording:
    """The models' answers from one live run, enough to replay it without Azure."""

    minute: int
    seed: int
    minutes: float
    plant: bool
    model: str
    recorded_at: str
    turns: list[Turn]

    def save(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"format": REPLAY_FORMAT, **asdict(self)}, indent=2) + "\n")

    @classmethod
    def load(cls, path: str | Path) -> Recording:
        data = json.loads(Path(path).read_text())
        if data.pop("format", None) != REPLAY_FORMAT:
            raise ValueError(f"{path}: not a format {REPLAY_FORMAT} slice recording")
        data["turns"] = [Turn(**t) for t in data["turns"]]
        return cls(**data)


class ReplayMismatch(RuntimeError):
    pass


Ask = Callable[[str], Awaitable[str]]
Judge = Callable[[Claim, list[dict]], Awaitable[Verdict]]


def judge_prompt(claim: Claim) -> str:
    """What identifies a Judge call in a recording: the claim and the ids it cites."""
    return json.dumps({"text": claim.text, "evidence": claim.evidence})


def replayer(turns: list[Turn]) -> tuple[Ask, Judge]:
    """Answers each call with the recorded answer, in order, and refuses a call it never saw."""
    queue = list(turns)

    def next_answer(role: str, prompt: str) -> str:
        if not queue:
            raise ReplayMismatch(f"the recording has no {role} answer for: {prompt!r}")
        turn = queue.pop(0)
        if (turn.role, turn.prompt) != (role, prompt):
            raise ReplayMismatch(
                f"call changed since recording: {turn.role} {turn.prompt!r} -> {role} {prompt!r}"
            )
        return turn.response

    async def ask(prompt: str) -> str:
        return next_answer("analyst", prompt)

    async def judge_replay(claim: Claim, evidence: list[dict]) -> Verdict:
        return Verdict(**json.loads(next_answer("judge", judge_prompt(claim))))

    return ask, judge_replay


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
    def __init__(self, ask: Ask, trace: list[str], plant: bool, live: bool):
        super().__init__(id="analyst")
        self.ask, self.trace, self.plant, self.live = ask, trace, plant, live

    @handler
    async def write(self, task: Task, ctx: WorkflowContext[Draft]) -> None:
        prompt = f"Write the claim for minute {task.minute}."
        if task.feedback:
            prompt += " Your previous claim was rejected: " + "; ".join(task.feedback) + ". Fix it."
        started = time.perf_counter()
        claim = parse_claim(await self.ask(prompt))
        if self.plant and task.attempt == 0:
            claim = tamper(claim)
            self.trace.append("analyst: draft tampered on purpose (--plant)")
        took = f"{time.perf_counter() - started:.1f}s" if self.live else "replayed"
        self.trace.append(f"analyst: {claim.text!r} evidence={claim.evidence} ({took})")
        await ctx.send_message(Draft(task=task, claim=claim))


class FactCheckExecutor(Executor):
    """Code checks first (free, exact about numbers, players and ids), then the Judge (meaning)."""

    def __init__(self, known: dict[str, dict], judge: Judge, trace: list[str], live: bool):
        super().__init__(id="fact_checker")
        self.known, self.judge, self.trace, self.live = known, judge, trace, live

    @handler
    async def review(self, draft: Draft, ctx: WorkflowContext[Task, Outcome]) -> None:
        verdict = check(draft.claim, self.known)
        if verdict.ok:
            evidence = [self.known[i] for i in draft.claim.evidence]
            started = time.perf_counter()
            verdict = await self.judge(draft.claim, evidence)
            took = f"{time.perf_counter() - started:.1f}s" if self.live else "replayed"
            self.trace.append(f"judge: {'supported' if verdict.ok else 'not supported'} ({took})")
        if verdict.ok:
            self.trace.append("fact_checker: accepted")
            await ctx.yield_output(Outcome(True, draft.claim, draft.task.attempt + 1, self.trace))
        elif draft.task.attempt < MAX_REWRITES:
            self.trace.append("fact_checker: rejected: " + "; ".join(verdict.reasons))
            await ctx.send_message(Task(draft.task.minute, verdict.reasons, draft.task.attempt + 1))
        else:
            self.trace.append("fact_checker: rejected, out of rewrites: " + "; ".join(verdict.reasons))
            await ctx.yield_output(Outcome(False, draft.claim, draft.task.attempt + 1, self.trace))


async def run_workflow(
    ask: Ask, judge_fn: Judge, minute: int, plant: bool, seed: int, minutes: float, live: bool
) -> Outcome:
    known = {e["id"]: e for e in events_in(seed, minutes, 1, int(minutes) + 1)}
    trace: list[str] = []
    analyst = AnalystExecutor(ask, trace, plant, live)
    checker = FactCheckExecutor(known, judge_fn, trace, live)
    # A rejected claim goes back to the analyst with the reasons, at most MAX_REWRITES times.
    builder = WorkflowBuilder(start_executor=analyst)
    workflow = builder.add_edge(analyst, checker).add_edge(checker, analyst).build()
    result = await workflow.run(Task(minute=minute))
    return result.get_outputs()[0]


async def run_slice(minute: int, plant: bool, seed: int, minutes: float) -> tuple[Outcome, list[Turn]]:
    """Live run on Foundry. Returns the outcome and every model answer, for --record."""
    tools = MCPStdioTool(
        name="match",
        command=sys.executable,
        args=["-m", "ninety.mcp.match_server"],
        env={"NINETY_SEED": str(seed), "NINETY_MINUTES": str(minutes)},
    )
    client = FoundryChatClient(
        project_endpoint=config.FOUNDRY_PROJECT, model=config.MODEL, credential=DefaultAzureCredential()
    )
    turns: list[Turn] = []
    async with tools:
        agent = Agent(client=client, name="analyst", instructions=INSTRUCTIONS, tools=tools)

        judge_ag = judge_agent(client)

        async def ask(prompt: str) -> str:
            response = (await agent.run(prompt)).text
            turns.append(Turn("analyst", prompt, response))
            return response

        async def judge_live(claim: Claim, evidence: list[dict]) -> Verdict:
            verdict = await judge(judge_ag, claim, evidence)
            turns.append(Turn("judge", judge_prompt(claim), json.dumps(asdict(verdict))))
            return verdict

        outcome = await run_workflow(ask, judge_live, minute, plant, seed, minutes, live=True)
    return outcome, turns


async def replay_slice(recording: Recording) -> Outcome:
    """Re-runs the workflow and the code checks with the recorded answers in place of the models."""
    r = recording
    ask, judge_replay = replayer(r.turns)
    return await run_workflow(ask, judge_replay, r.minute, r.plant, r.seed, r.minutes, live=False)


def main() -> None:
    ap = argparse.ArgumentParser(description="Thin slice: Analyst -> Fact-checker over MCP, on Foundry.")
    ap.add_argument("--minute", type=int, default=2)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--minutes", type=float, default=5)
    ap.add_argument("--plant", action="store_true", help="tamper with the first draft to show a rejection")
    ap.add_argument("--speak", metavar="MP3", help="speak the verified claim to this file")
    ap.add_argument("--record", metavar="JSON", help="save the models' answers to this file")
    ap.add_argument(
        "--replay", metavar="JSON", help="replay a recording instead of calling Foundry (no Azure needed)"
    )
    args = ap.parse_args()
    if args.replay and (args.record or args.speak):
        ap.error("--replay cannot be combined with --record or --speak (speech needs Azure)")

    started = time.perf_counter()
    if args.replay:
        recording = Recording.load(args.replay)
        print(
            f"replaying {args.replay}: minute {recording.minute}, seed {recording.seed}, "
            f"{'planted, ' if recording.plant else ''}{recording.model} recorded {recording.recorded_at}"
        )
        try:
            outcome = asyncio.run(replay_slice(recording))
        except ReplayMismatch as e:
            sys.exit(f"replay stopped: {e}. Record it again with --record.")
    else:
        outcome, turns = asyncio.run(run_slice(args.minute, args.plant, args.seed, args.minutes))
        if args.record:
            stamp = datetime.now(UTC).isoformat(timespec="seconds")
            Recording(args.minute, args.seed, args.minutes, args.plant, config.MODEL, stamp, turns).save(
                args.record
            )
    for line in outcome.trace:
        print(line)
    verdict = "ACCEPTED" if outcome.accepted else "REJECTED"
    print(f"{verdict} after {outcome.attempts} draft(s), {time.perf_counter() - started:.1f}s")
    if args.record and not args.replay:
        print(f"recorded {len(turns)} model answer(s) to {args.record}")
    if outcome.accepted and args.speak:
        from ninety.speech.tts import synthesize

        audio, seconds = synthesize(outcome.claim.text)
        with open(args.speak, "wb") as f:
            f.write(audio)
        print(f"spoken to {args.speak} in {seconds:.2f}s")
