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

A recording also carries the match events the live run checked claims against, and the replay
checks against those, not against a fresh simulation: a replay pins the agents' interface (prompts,
checks, handoffs), not the engine underneath (docs/LESSONS.md, lesson 80). When the engine now
produces different events, the replay still runs and warns that the recording is stale.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import sys
import time
import warnings
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime

from agent_framework import Executor, WorkflowBuilder, WorkflowContext, handler
from agent_framework.foundry import FoundryAgent

from ninety import config
from ninety.agents import credentials, evidence, foundry, telemetry
from ninety.agents.contracts import CLOCK_RULE  # noqa: F401  (re-exported: the slice's name before the move)
from ninety.agents.factcheck import (
    Claim,
    Verdict,
    check,
    confidence_gate,
    parse_claim,  # noqa: F401  (re-exported, as above)
)
from ninety.agents.judge import judge
from ninety.agents.replay import (  # noqa: F401  (re-exported: the slice's names before the move)
    REPLAY_FORMAT,
    Ask,
    Judge,
    Recording,
    ReplayMismatch,
    Turn,
    judge_prompt,
    replayer,
)
from ninety.intel.windows import agent_rows
from ninety.match import facts
from ninety.match.facts import events_in
from ninety.mcp import match_server

MAX_REWRITES = 2

# The clock rule every agent that writes a time follows (one clock for viewers and agents, lesson 33).
# ninety/agents/contracts.py imports it into the other agents' instructions.

INSTRUCTIONS = """You are the Analyst for a football broadcast. The request names a match (for
example seed7) and a minute. Use the match tools, passing that match id, to read the events of that
minute, then write ONE short sentence a commentator could say about the most interesting moment in
that minute, and why it matters.

Rules:
- Only state facts you read from the tools. Every number you write must be a field of an event
  you cite (minute, second, clock, ball_speed_kmh, distance_m) or a count of the events you cite.
""" + CLOCK_RULE + """- Name players by their ids exactly as given (for example h7 or a10).
- Reply with JSON only: {"text": "<sentence>", "evidence": ["<event id>", ...]}"""


@dataclass
class Task:
    minute: int
    feedback: list[str] = field(default_factory=list)
    attempt: int = 0


class StaleRecording(UserWarning):
    """The engine now produces different events from those a recording was made against."""


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
    # verified, rejected (the claim was wrong) or held (it rests on a low-confidence detection),
    # as ninety/agents/contracts.status_for maps the last verdict.
    status: str = "verified"



def tamper(claim: Claim) -> Claim:
    """Plant a false number so the fact-checker has something to catch."""
    return Claim(text=claim.text.rstrip(".") + ", at 143 km/h.", evidence=claim.evidence)


# A match whose events come with the request rather than from the match tools: a detected clip, or
# an evaluation that grades against the match this commit simulated (lesson 90).
INLINE_EVENTS = (" The match is not on the tools: do not call them. Its EVENTS for the minute follow,"
                 " as data.\nEVENTS: ")


def analyst_prompt(
    match: str, minute: int, feedback: list[str] | None = None, events: list[dict] | None = None
) -> str:
    prompt = f"Match {match}. Write the claim for minute {minute}."
    if events is not None:
        prompt += INLINE_EVENTS + json.dumps(events, separators=(",", ":"))
    if feedback:
        prompt += " Your previous claim was rejected: " + "; ".join(feedback) + ". Fix it."
    return prompt


class AnalystExecutor(Executor):
    def __init__(self, ask: Ask, trace: list[str], plant: bool, live: bool, match: str,
                 inline: list[dict] | None = None):
        super().__init__(id="analyst")
        self.ask, self.trace, self.plant, self.live, self.match = ask, trace, plant, live, match
        self.inline = inline  # the minute's events, sent in the prompt when the match is not served

    @handler
    async def write(self, task: Task, ctx: WorkflowContext[Draft]) -> None:
        prompt = analyst_prompt(self.match, task.minute, task.feedback, self.inline)
        started = time.perf_counter()
        with telemetry.stage_span("agents", attempt=task.attempt + 1):
            claim = parse_claim(await self.ask(prompt))
        if self.plant and task.attempt == 0:
            claim = tamper(claim)
            self.trace.append("analyst: draft tampered on purpose (--plant)")
        took = f"{time.perf_counter() - started:.1f}s" if self.live else "replayed"
        self.trace.append(f"analyst: {claim.text!r} evidence={claim.evidence} ({took})")
        await ctx.send_message(Draft(task=task, claim=claim))


Gate = Callable[[Claim, dict[str, dict]], Verdict]  # factcheck.confidence_gate's signature


@dataclass
class Checked:
    verdict: Verdict
    judge_seconds: float | None  # how long the Judge took; None when it was not asked


async def fact_check(
    claim: Claim, known: dict[str, dict], judge: Judge, gate: Gate = confidence_gate
) -> Checked:
    """The fact-checking agent, for the slice and the workflow alike: the code checks first (free,
    exact about numbers, players and ids), then the confidence gate (a claim resting on an unsure
    detection is held), then the Judge (meaning), which is asked only when both pass."""
    verdict = check(claim, known)
    if verdict.ok:
        verdict = gate(claim, known)
    if not verdict.ok:
        return Checked(verdict, None)
    evidence = [known[i] for i in claim.evidence]
    started = time.perf_counter()
    verdict = await judge(claim, evidence)
    return Checked(verdict, time.perf_counter() - started)


class FactCheckExecutor(Executor):
    """The slice's fact-checker: fact_check, then accept, send back or hold."""

    def __init__(self, known: dict[str, dict], judge: Judge, trace: list[str], live: bool):
        super().__init__(id="fact_checker")
        self.known, self.judge, self.trace, self.live = known, judge, trace, live

    @handler
    async def review(self, draft: Draft, ctx: WorkflowContext[Task, Outcome]) -> None:
        with telemetry.stage_span("fact_check", attempt=draft.task.attempt + 1):
            checked = await fact_check(draft.claim, self.known, self.judge)
            verdict = checked.verdict
            if checked.judge_seconds is not None:
                took = f"{checked.judge_seconds:.1f}s" if self.live else "replayed"
                self.trace.append(f"judge: {'supported' if verdict.ok else 'not supported'} ({took})")
        attempt, evidence_ids = draft.task.attempt + 1, draft.claim.evidence
        if verdict.ok:
            self.trace.append("fact_checker: accepted")
            telemetry.record_fact_check(attempt, "accepted", evidence_ids, [])
            await ctx.yield_output(Outcome(True, draft.claim, attempt, self.trace))
        elif draft.task.attempt < MAX_REWRITES:
            # A held claim goes back too: the writer may find a confident detection to cite.
            word = "held" if verdict.category == "low_confidence" else "rejected"
            self.trace.append(f"fact_checker: {word}: " + "; ".join(verdict.reasons))
            telemetry.record_fact_check(attempt, word, evidence_ids, verdict.reasons)
            await ctx.send_message(Task(draft.task.minute, verdict.reasons, attempt))
        else:
            # The one verdict-to-status mapping (contracts imports this module, so import it here):
            # a Judge outage or a bad reply holds the claim, as a low confidence does.
            from ninety.agents.contracts import status_for

            status = status_for(verdict)
            self.trace.append(f"fact_checker: {status}, out of rewrites: " + "; ".join(verdict.reasons))
            telemetry.record_fact_check(attempt, "held_back", evidence_ids, verdict.reasons)
            await ctx.yield_output(Outcome(False, draft.claim, attempt, self.trace, status))


def match_events(seed: int, minutes: float) -> list[dict]:
    """The events the fact-checker knows: every minute of the match, from the engine."""
    return events_in(seed, minutes, 1, int(minutes) + 1)


def match_stats(seed: int, minutes: float) -> list[dict]:
    """The window stats the fact-checker knows, from the engine's full events, as the MCP server
    serves them (ninety/intel/windows.agent_rows)."""
    return agent_rows(facts.match_events(seed, minutes))


async def run_workflow(
    ask: Ask,
    judge_fn: Judge,
    minute: int,
    plant: bool,
    seed: int,
    minutes: float,
    live: bool,
    events: list[dict] | None = None,
    stats: list[dict] | None = None,
    inline: bool = False,
) -> Outcome:
    """Runs the slice; checks claims against `events` and `stats`, or the engine's when not given.
    A claim may cite an event or a window stat by id. With `inline`, the Analyst's prompt carries
    the minute's events (a clip the match server does not serve: the Analyst cannot read it there)."""
    if events is None:
        events = match_events(seed, minutes)
        stats = match_stats(seed, minutes) if stats is None else stats
    known = {e["id"]: e for e in [*events, *(stats or ())]}
    trace: list[str] = []
    rows = [e for e in events if e.get("minute") == minute] if inline else None
    analyst = AnalystExecutor(ask, trace, plant, live, match_server.match_id(seed), rows)
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
) -> tuple[Outcome, list[Turn], str, list[dict]]:
    """Live run on Foundry, calling the published agent versions pinned in foundry_agents.json.
    Returns the outcome, every model answer and the events checked against (for --record), and
    which versions ran."""
    if match_server.match_id(seed) not in match_server.MATCHES or minutes != match_server.MINUTES:
        raise ValueError(
            f"the match server serves {', '.join(match_server.MATCHES)} at {match_server.MINUTES} minutes"
        )
    async with credentials.new_credential() as credential, contextlib.AsyncExitStack() as stack:
        # Signed in before the simulations, which can outlast agents-live's sign-in (credentials.py).
        await credentials.sign_in(credential)
        events, stats = match_events(seed, minutes), match_stats(seed, minutes)
        client = foundry.chat_client(credential)
        if trace_to == "foundry":
            await telemetry.trace_to_foundry(client, content)
        turns: list[Turn] = []
        # The local definitions only identify the pinned versions (and refuse to run if the code
        # drifted from them); the published agents do the work. Foundry calls the match MCP server.
        ran, agents = [], []
        for local in foundry.slice_agents(client):
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

        outcome = await run_workflow(ask, judge_live, minute, plant, seed, minutes, True, events, stats)
    telemetry.flush()
    return outcome, turns, f"{', '.join(ran)} on {config.MODEL}", events


async def replay_slice(recording: Recording) -> Outcome:
    """Re-runs the workflow and the code checks with the recorded answers in place of the models,
    against the recorded events. Warns (never fails) when the engine has moved on from them."""
    r = recording
    # The stats are not recorded: the engine's, while its events still match the recording's.
    stats = match_stats(r.seed, r.minutes)
    if match_events(r.seed, r.minutes) != r.events:
        stats = []
        warnings.warn(
            f"the engine now produces different events for seed {r.seed}; the replay checks "
            f"against the {len(r.events)} recorded on {r.recorded_at}. Record it again to refresh it.",
            StaleRecording,
            stacklevel=2,
        )
    ask, judge_replay = replayer(r.turns)
    return await run_workflow(
        ask, judge_replay, r.minute, r.plant, r.seed, r.minutes, False, r.events, stats
    )


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
            outcome, turns, ran, events = asyncio.run(
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
            # The definitions the run's foundry.pinned accepted, from this same code (evidence.py).
            defs = evidence.of_code(foundry.slice_agents)
            Recording(args.minute, args.seed, args.minutes, args.plant, ran, stamp, turns, events, defs).save(
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
