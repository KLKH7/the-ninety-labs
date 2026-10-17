"""Thin slice through the whole stack: Foundry agents, Agent Framework workflow, MCP tools,
a fact-checking step that can reject, traces in Foundry, and speech.

    uv run ninety-slice --minute 2                # one verified claim about minute 2
    uv run ninety-slice --minute 2 --plant        # tamper with the first draft to show a rejection
    uv run ninety-slice --minute 2 --speak a.mp3  # also speak the verified claim
    uv run ninety-slice --minute 2 --plant --record replays/slice.json   # save the model's replies
    uv run ninety-slice --replay replays/slice.json                      # no Azure needed

Live runs call the Analyst and the Judge as published Foundry prompt agents, at the versions
pinned in foundry_agents.json (ninety/agents/foundry.py), and send their traces to Foundry
(ninety/agents/telemetry.py; --no-trace to skip, --trace-content to include prompts and replies).
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
import contextlib
import json
import re
import sys
import time
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from agent_framework import Executor, WorkflowBuilder, WorkflowContext, handler
from agent_framework.foundry import FoundryAgent
from azure.identity import DefaultAzureCredential

from ninety import config
from ninety.agents import foundry, telemetry
from ninety.agents.factcheck import Claim, Verdict, check
from ninety.agents.judge import judge
from ninety.match.facts import events_in
from ninety.mcp import match_server

MAX_REWRITES = 2
REPLAY_FORMAT = 2

INSTRUCTIONS = """You are the Analyst for a football broadcast. The request names a match (for
example seed7) and a minute. Use the match tools, passing that match id, to read the events of that
minute, then write ONE short sentence a commentator could say about the most interesting moment in
that minute, and why it matters.

Rules:
- Only state facts you read from the tools. Every number you write must be a field of an event
  you cite (minute, second, clock, ball_speed_kmh, distance_m) or a count of the events you cite.
- For a time, use the event's clock exactly as given (01:28), or its minute as an ordinal (in
  minute 2); never combine minute and second into a clock.
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


def analyst_prompt(match: str, minute: int, feedback: list[str] | None = None) -> str:
    prompt = f"Match {match}. Write the claim for minute {minute}."
    if feedback:
        prompt += " Your previous claim was rejected: " + "; ".join(feedback) + ". Fix it."
    return prompt


class AnalystExecutor(Executor):
    def __init__(self, ask: Ask, trace: list[str], plant: bool, live: bool, match: str):
        super().__init__(id="analyst")
        self.ask, self.trace, self.plant, self.live, self.match = ask, trace, plant, live, match

    @handler
    async def write(self, task: Task, ctx: WorkflowContext[Draft]) -> None:
        prompt = analyst_prompt(self.match, task.minute, task.feedback)
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
        attempt, evidence_ids = draft.task.attempt + 1, draft.claim.evidence
        if verdict.ok:
            self.trace.append("fact_checker: accepted")
            telemetry.record_fact_check(attempt, "accepted", evidence_ids, [])
            await ctx.yield_output(Outcome(True, draft.claim, attempt, self.trace))
        elif draft.task.attempt < MAX_REWRITES:
            self.trace.append("fact_checker: rejected: " + "; ".join(verdict.reasons))
            telemetry.record_fact_check(attempt, "rejected", evidence_ids, verdict.reasons)
            await ctx.send_message(Task(draft.task.minute, verdict.reasons, attempt))
        else:
            self.trace.append("fact_checker: rejected, out of rewrites: " + "; ".join(verdict.reasons))
            telemetry.record_fact_check(attempt, "held_back", evidence_ids, verdict.reasons)
            await ctx.yield_output(Outcome(False, draft.claim, attempt, self.trace))


async def run_workflow(
    ask: Ask, judge_fn: Judge, minute: int, plant: bool, seed: int, minutes: float, live: bool
) -> Outcome:
    known = {e["id"]: e for e in events_in(seed, minutes, 1, int(minutes) + 1)}
    trace: list[str] = []
    analyst = AnalystExecutor(ask, trace, plant, live, match_server.match_id(seed))
    checker = FactCheckExecutor(known, judge_fn, trace, live)
    # A rejected claim goes back to the analyst with the reasons, at most MAX_REWRITES times.
    builder = WorkflowBuilder(start_executor=analyst)
    workflow = builder.add_edge(analyst, checker).add_edge(checker, analyst).build()
    with telemetry.claim_span(minute, seed, plant, live) as span:
        outcome = (await workflow.run(Task(minute=minute))).get_outputs()[0]
        span.set_attributes({"ninety.accepted": outcome.accepted, "ninety.drafts": outcome.attempts})
    return outcome


async def run_slice(
    minute: int, plant: bool, seed: int, minutes: float, trace_to: str = "foundry", content: bool = False
) -> tuple[Outcome, list[Turn], str]:
    """Live run on Foundry, calling the published agent versions pinned in foundry_agents.json.
    Returns the outcome, every model answer (for --record) and which versions ran."""
    if match_server.match_id(seed) not in match_server.MATCHES or minutes != match_server.MINUTES:
        raise ValueError(
            f"the match server serves {', '.join(match_server.MATCHES)} at {match_server.MINUTES} minutes"
        )
    credential = DefaultAzureCredential()
    client = foundry.chat_client(credential)
    if trace_to == "foundry":
        await telemetry.trace_to_foundry(client, content)
    turns: list[Turn] = []
    async with contextlib.AsyncExitStack() as stack:
        # The local definitions only identify the pinned versions (and refuse to run if the code
        # drifted from them); the published agents do the work. Foundry calls the match MCP server.
        ran, agents = [], []
        for local in foundry.build_agents(client):
            name, version = foundry.pinned(local)
            ran.append(f"{name}:{version}")
            published = FoundryAgent(
                project_endpoint=config.FOUNDRY_PROJECT,
                agent_name=name,
                agent_version=version,
                credential=credential,
            )
            agents.append(await stack.enter_async_context(published))
        agent, judge_ag = agents

        async def ask(prompt: str) -> str:
            response = (await agent.run(prompt)).text
            turns.append(Turn("analyst", prompt, response))
            return response

        async def judge_live(claim: Claim, evidence: list[dict]) -> Verdict:
            verdict = await judge(judge_ag, claim, evidence)
            turns.append(Turn("judge", judge_prompt(claim), json.dumps(asdict(verdict))))
            return verdict

        outcome = await run_workflow(ask, judge_live, minute, plant, seed, minutes, live=True)
    telemetry.flush()
    return outcome, turns, f"{', '.join(ran)} on {config.MODEL}"


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
    ap.add_argument("--no-trace", action="store_true", help="do not send traces to Foundry")
    ap.add_argument("--trace-content", action="store_true", help="include prompts and replies in the traces")
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
        try:
            outcome, turns, ran = asyncio.run(
                run_slice(
                    args.minute,
                    args.plant,
                    args.seed,
                    args.minutes,
                    trace_to="none" if args.no_trace else "foundry",
                    content=args.trace_content,
                )
            )
        except foundry.RegistryDrift as e:
            sys.exit(f"not run: {e}")
        print(f"ran {ran}")
        if args.record:
            stamp = datetime.now(UTC).isoformat(timespec="seconds")
            Recording(args.minute, args.seed, args.minutes, args.plant, ran, stamp, turns).save(args.record)
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
