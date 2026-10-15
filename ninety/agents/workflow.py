"""Workflow v1: cited match facts become a verified (or safely held) cue.

The orchestration is built with Agent Framework executors so the scripted adapters used by the
tests can be replaced by model clients without changing the hand-offs.  The default adapters are
deterministic and never contact Azure.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agent_framework import Executor, WorkflowBuilder, WorkflowContext, handler
from jsonschema import validate

from ninety.agents.cues import DISPLAY_SECONDS, template_cues, write_fixture
from ninety.agents.factcheck import Claim, Verdict, check
from ninety.agents.judge import judge as live_judge
from ninety.agents.judge import judge_agent
from ninety.agents.ledger import InMemoryLedger, Ledger, Record, load_match
from ninety.agents.slice import MAX_REWRITES
from ninety.match.facts import match_events

WORKFLOW_REPLAY_FORMAT = 2
REPLAY_FORMAT = WORKFLOW_REPLAY_FORMAT
ROOT = Path(__file__).resolve().parents[2]
OVERLAY_SCHEMA = json.loads((ROOT / "schemas" / "overlay_cue.schema.json").read_text())
Ask = Callable[[str], Awaitable[str | Mapping]]


@dataclass(frozen=True)
class Proposal:
    text: str
    evidence: tuple[str, ...]

    def claim(self) -> Claim:
        return Claim(self.text, list(self.evidence))


@dataclass(frozen=True)
class Decision:
    category: str
    reasons: tuple[str, ...] = ()
    alternative: Proposal | None = None


DecisionAsk = Callable[[str], Awaitable[str | Mapping | Decision]]


@dataclass
class Models:
    """Injected model adapters; absent adapters use deterministic scripted fakes."""

    analyst: Ask | None = None
    tactician: Ask | None = None
    challenger: DecisionAsk | None = None
    judge: DecisionAsk | None = None
    judge_timeout_seconds: float = 15.0


@dataclass
class Request:
    events: tuple[dict, ...]
    known: dict[str, dict]
    times: dict[str, float]
    window: tuple[float, float] | None
    plant: bool
    ledger: Ledger


@dataclass
class Draft:
    request: Request
    proposal: Proposal
    attempt: int = 0
    history: list[dict] = field(default_factory=list)
    feedback: tuple[str, ...] = ()
    author: str = "analyst"


@dataclass
class Review:
    draft: Draft
    challenger: Decision
    judge: Decision


@dataclass(frozen=True)
class WorkflowResult:
    category: str
    cue: dict | None
    proposal: Proposal | None
    attempts: int
    claim_history: tuple[dict, ...]
    trace: tuple[str, ...]
    moments: tuple[str, ...] = ()
    model_calls: int = 0

    @property
    def accepted(self) -> bool:
        return self.category == "verified"

    @property
    def call_count(self) -> int:
        return self.model_calls


@dataclass
class Turn:
    role: str
    prompt: str
    response: str


@dataclass
class Recording:
    format: int
    seed: int
    minutes: float
    model: str
    recorded_at: str
    turns: list[Turn]
    window: str | None = None
    plant: bool = False

    def save(self, path: str | Path) -> None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(asdict(self), indent=2) + "\n")

    @classmethod
    def load(cls, path: str | Path) -> Recording:
        data = json.loads(Path(path).read_text())
        if data.pop("format", None) != WORKFLOW_REPLAY_FORMAT:
            raise ValueError(f"{path}: not a format {WORKFLOW_REPLAY_FORMAT} workflow recording")
        data["format"] = WORKFLOW_REPLAY_FORMAT
        data["turns"] = [Turn(**turn) for turn in data["turns"]]
        return cls(**data)


class ReplayMismatch(RuntimeError):
    pass


async def _run_live_workflow(**kwargs: Any) -> WorkflowResult:
    """Wire the production Foundry/MCP adapters without importing Azure on scripted runs."""
    import sys

    from agent_framework import Agent, MCPStdioTool
    from agent_framework.foundry import FoundryChatClient
    from azure.identity import DefaultAzureCredential

    from ninety import config

    tools = MCPStdioTool(
        name="match",
        command=sys.executable,
        args=["-m", "ninety.mcp.match_server"],
        env={"NINETY_SEED": str(kwargs["seed"]), "NINETY_MINUTES": str(kwargs["minutes"])},
    )
    client = FoundryChatClient(
        project_endpoint=config.FOUNDRY_PROJECT,
        model=config.MODEL,
        credential=DefaultAzureCredential(),
    )
    async with tools:
        analyst_agent = Agent(
            client=client,
            name="analyst",
            instructions="Write JSON with text and evidence for the supplied football events.",
            tools=tools,
        )
        tactician_agent = Agent(
            client=client,
            name="tactician",
            instructions="Improve the supplied football commentary while preserving cited facts.",
        )
        challenger_agent = Agent(
            client=client,
            name="challenger",
            instructions='Return JSON: {"category":"agree|raise|alternative","reasons":[]}.',
        )
        judge_model = judge_agent(client)

        async def ask(agent: Agent, prompt: str) -> str:
            return (await agent.run(prompt)).text

        async def judge_call(prompt: str) -> Decision:
            data = _json(prompt)["input"]
            proposal = _proposal(data["claim"])
            verdict = await live_judge(
                judge_model,
                proposal.claim(),
                list(data["evidence"]),
                timeout_seconds=kwargs["judge_timeout_seconds"],
            )
            return Decision(
                "verified" if verdict.ok else "rejected",
                tuple(verdict.reasons),
            )

        models = Models(
            analyst=lambda prompt: ask(analyst_agent, prompt),
            tactician=lambda prompt: ask(tactician_agent, prompt),
            challenger=lambda prompt: ask(challenger_agent, prompt),
            judge=judge_call,
            judge_timeout_seconds=kwargs["judge_timeout_seconds"],
        )
        return await run_workflow(**kwargs, models=models, live_models=False)


def _json(response: str | Mapping) -> dict:
    if isinstance(response, Mapping):
        return dict(response)
    body = re.search(r"\{.*\}", response, re.S)
    return json.loads(body.group() if body else response)


def _proposal(response: str | Mapping) -> Proposal:
    data = _json(response)
    return Proposal(str(data.get("text", "")), tuple(str(item) for item in data.get("evidence", [])))


def _decision(response: str | Mapping | Decision | Verdict) -> Decision:
    if isinstance(response, Decision):
        return response
    if isinstance(response, Verdict):
        return Decision(response.category, tuple(response.reasons))
    data = _json(response)
    alternative = data.get("alternative")
    return Decision(
        str(data.get("category", "held")),
        tuple(str(reason) for reason in data.get("reasons", [])),
        _proposal(alternative) if alternative else None,
    )


def _prompt(role: str, payload: object) -> str:
    return json.dumps({"role": role, "input": payload}, separators=(",", ":"), sort_keys=True)


def _window(value: str | None) -> tuple[float, float] | None:
    if not value:
        return None
    match = re.fullmatch(r"(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)", value)
    if not match or float(match.group(2)) <= float(match.group(1)):
        raise ValueError("--window must be START-END seconds")
    return float(match.group(1)), float(match.group(2))


def _scripted(events: Sequence[Mapping]) -> Proposal:
    event = next(
        event for event in events if event.get("type") in {"goal", "shot", "interception", "pass"}
    )
    player = event["player"]
    if event["type"] == "pass" and event.get("receiver"):
        return Proposal(
            f"{player} finds {event['receiver']} with a {event.get('distance_m', 0)} m pass.",
            (str(event["id"]),),
        )
    if event["type"] == "goal":
        return Proposal(f"{player} scores.", (str(event["id"]),))
    return Proposal(f"{player} creates a {event['type']} moment.", (str(event["id"]),))


def _tamper(proposal: Proposal) -> Proposal:
    return Proposal(proposal.text.rstrip(".") + " at 999 km/h.", proposal.evidence)


async def _scripted_ask(role: str, prompt: str) -> dict:
    data = _json(prompt)["input"]
    if role == "analyst":
        proposal = _scripted(data["events"])
        if data.get("feedback"):
            proposal = _scripted(data["events"])
        return {"text": proposal.text, "evidence": list(proposal.evidence)}
    if role == "tactician" and data.get("feedback"):
        return {"text": _scripted(data["events"]).text, "evidence": list(_scripted(data["events"]).evidence)}
    return data["proposal"]


def _replay(turns: list[Turn]) -> dict[str, Ask]:
    queue = turns

    def adapter(role: str) -> Ask:
        async def ask(prompt: str) -> str:
            if not queue:
                raise ReplayMismatch(f"recording has no {role} answer for {prompt!r}")
            turn = queue.pop(0)
            if turn.role != role or turn.prompt != prompt:
                raise ReplayMismatch(
                    f"role-aware replay mismatch: {turn.role} {turn.prompt!r} -> {role} {prompt!r}"
                )
            return turn.response

        return ask

    return {role: adapter(role) for role in ("analyst", "tactician", "challenger", "judge")}


class AnalystExecutor(Executor):
    def __init__(self, ask: Ask, trace: list[str], turns: list[Turn] | None, plant: bool):
        super().__init__(id="analyst")
        self.ask, self.trace, self.turns, self.plant = ask, trace, turns, plant

    @handler
    async def write(self, input_data: Request | Draft, ctx: WorkflowContext[Draft]) -> None:
        request = input_data.request if isinstance(input_data, Draft) else input_data
        previous = input_data if isinstance(input_data, Draft) else None
        payload = {"events": list(request.events)}
        if request.window:
            payload["window"] = request.window
        if previous is not None:
            payload["previous"] = asdict(previous.proposal)
            payload["feedback"] = list(previous.feedback)
        claim_id = f"claim-workflow-{request.events[0]['id']}"
        try:
            response = await self.ask(_prompt("analyst", payload))
            proposal = _proposal(response)
        except (ValueError, TypeError, json.JSONDecodeError):
            self.trace.append("analyst: invalid_response")
            await ctx.yield_output(
                WorkflowResult(
                    "held",
                    None,
                    None,
                    previous.attempt if previous else 0,
                    tuple(previous.history if previous else ()),
                    tuple(self.trace),
                    model_calls=1,
                )
            )
            return
        if self.plant and previous is None:
            proposal = _tamper(proposal)
        if self.turns is not None:
            self.turns.append(Turn("analyst", _prompt("analyst", payload), json.dumps(asdict(proposal))))
        self.trace.append("analyst: draft")
        known = set(request.known)
        await self._append_claim(
            request,
            claim_id,
            proposal,
            "draft",
            tuple(item for item in proposal.evidence if item in known),
            previous.attempt + 1 if previous else 1,
        )
        await ctx.send_message(
            Draft(
                request,
                proposal,
                previous.attempt if previous else 0,
                [*(previous.history if previous else []), {"status": "draft", "text": proposal.text}],
                author="analyst",
            )
        )

    async def _append_claim(
        self, request: Request, claim_id: str, proposal: Proposal, status: str,
        evidence: tuple[str, ...], attempt: int,
    ) -> None:
        await request.ledger.append(
            Record(
                claim_id,
                1,
                "claim",
                request.times[str(request.events[0]["id"])],
                "workflow",
                None,
                evidence,
                {
                    "status": status,
                    "text": proposal.text,
                    "attempt": attempt,
                    "evidence": list(proposal.evidence),
                },
            )
        )


class TacticianExecutor(Executor):
    def __init__(self, ask: Ask, trace: list[str], turns: list[Turn] | None):
        super().__init__(id="tactician")
        self.ask, self.trace, self.turns = ask, trace, turns

    @handler
    async def explain(self, draft: Draft, ctx: WorkflowContext[Draft]) -> None:
        payload = {
            "proposal": asdict(draft.proposal),
            "events": list(draft.request.events),
            "feedback": list(draft.feedback),
        }
        prompt = _prompt("tactician", payload)
        response = await self.ask(prompt)
        proposal = _proposal(response)
        if self.turns is not None:
            self.turns.append(Turn("tactician", prompt, json.dumps(asdict(proposal))))
        self.trace.append("tactician: draft")
        await ctx.send_message(
            Draft(draft.request, proposal, draft.attempt, draft.history, author="tactician")
        )


class ChallengerExecutor(Executor):
    def __init__(self, trace: list[str], ask: DecisionAsk | None = None, turns: list[Turn] | None = None):
        super().__init__(id="challenger")
        self.trace, self.ask, self.turns = trace, ask, turns

    @handler
    async def challenge(self, draft: Draft, ctx: WorkflowContext[Review]) -> None:
        evidence = [
            draft.request.known[item]
            for item in draft.proposal.evidence
            if item in draft.request.known
        ]
        deterministic: Decision | None = None
        if not draft.proposal.text.strip():
            deterministic = Decision("raise", ("empty claim text",))
        elif not draft.proposal.evidence:
            deterministic = Decision("raise", ("claim has no evidence",))
        elif len(evidence) != len(draft.proposal.evidence):
            deterministic = Decision("raise", ("unknown evidence id",))
        if deterministic is not None:
            decision = deterministic
        elif self.ask is not None:
            prompt = _prompt(
                "challenger",
                {"proposal": asdict(draft.proposal), "evidence": evidence},
            )
            try:
                raw = await self.ask(prompt)
                decision = _decision(raw)
            except Exception as exc:
                decision = Decision("raise", (f"challenger service error: {exc}",))
            if self.turns is not None:
                self.turns.append(Turn("challenger", prompt, json.dumps(asdict(decision))))
        else:
            decision = Decision("agree")
        self.trace.append(f"challenger: {decision.category}")
        await ctx.send_message(Review(draft, decision, Decision("held")), target_id="judge")


class JudgeExecutor(Executor):
    def __init__(
        self,
        trace: list[str],
        ask: DecisionAsk | None = None,
        turns: list[Turn] | None = None,
        timeout_seconds: float = 1.0,
    ):
        super().__init__(id="judge")
        self.trace, self.ask, self.turns, self.timeout_seconds = trace, ask, turns, timeout_seconds

    @handler
    async def judge(self, review: Review, ctx: WorkflowContext[Any]) -> None:
        if review.challenger.category == "raise":
            self.trace.append("challenger: skipped; tactician continues")
            review = Review(review.draft, Decision("agree"), review.judge)
        elif review.challenger.category == "alternative" and review.challenger.alternative:
            review = Review(
                Draft(
                    review.draft.request,
                    review.challenger.alternative,
                    review.draft.attempt,
                    review.draft.history,
                    review.draft.feedback,
                ),
                Decision("agree"),
                review.judge,
            )
        elif review.challenger.category not in {"agree", "verified"}:
            await ctx.send_message(review, target_id="producer")
            return
        draft = review.draft
        if not draft.proposal.text.strip():
            code_verdict = Verdict(False, ["empty claim text"])
        elif not draft.proposal.evidence:
            code_verdict = Verdict(False, ["claim has no evidence"])
        else:
            code_verdict = check(draft.proposal.claim(), draft.request.known)
        if not code_verdict.ok:
            decision = Decision("rejected", tuple(code_verdict.reasons))
            self.trace.append("judge: rejected")
            self.trace.append("fact_checker: rejected: " + "; ".join(decision.reasons))
            if draft.attempt < MAX_REWRITES:
                await ctx.send_message(
                    replace(
                        draft,
                        attempt=draft.attempt + 1,
                        feedback=decision.reasons,
                    ),
                    target_id=draft.author,
                )
            else:
                await ctx.send_message(
                    Review(draft, review.challenger, decision),
                    target_id="producer",
                )
            return
        if self.ask is None:
            decision = Decision("verified")
        else:
            prompt = _prompt(
                "judge",
                {
                    "claim": asdict(draft.proposal),
                    "evidence": [
                        draft.request.known[item]
                        for item in draft.proposal.evidence
                        if item in draft.request.known
                    ],
                },
            )
            try:
                raw = await asyncio.wait_for(self.ask(prompt), timeout=self.timeout_seconds)
                decision = _decision(raw)
            except TimeoutError:
                decision = Decision("held", ("judge timeout; claim held back",))
            except (ValueError, TypeError, json.JSONDecodeError):
                decision = Decision("held", ("judge returned invalid response; claim held back",))
            except Exception:
                decision = Decision("held", ("judge service error; claim held back",))
            if self.turns is not None:
                self.turns.append(Turn("judge", prompt, json.dumps(asdict(decision))))
        category = (
            "rejected"
            if decision.category in {"input", "unsupported_claim"}
            else "held"
            if decision.category in {"timeout", "service", "invalid_response"}
            else decision.category
        )
        if category != decision.category:
            decision = Decision(category, decision.reasons)
        self.trace.append(f"judge: {category}")
        self.trace.append(
            "fact_checker: accepted"
            if category == "verified"
            else "fact_checker: rejected: " + "; ".join(decision.reasons)
        )
        if category == "rejected" and draft.attempt < MAX_REWRITES:
            await ctx.send_message(
                replace(
                    draft,
                    attempt=draft.attempt + 1,
                    feedback=decision.reasons,
                ),
                target_id=draft.author,
            )
        else:
            await ctx.send_message(
                Review(draft, review.challenger, decision),
                target_id="producer",
            )


class ProducerExecutor(Executor):
    def __init__(self, ledger: Ledger, trace: list[str]):
        super().__init__(id="producer")
        self.ledger, self.trace = ledger, trace

    @handler
    async def produce(self, review: Review, ctx: WorkflowContext[WorkflowResult]) -> None:
        draft = review.draft
        category = review.judge.category
        if review.challenger.category == "raise":
            category = "rejected"
        elif review.challenger.category not in {"agree", "verified"}:
            category = "held"
        status = category if category in {"verified", "rejected", "held"} else "held"
        claim_id = f"claim-workflow-{draft.request.events[0]['id']}"
        known_evidence = tuple(item for item in draft.proposal.evidence if item in draft.request.known)
        reasons = review.judge.reasons or review.challenger.reasons
        await self.ledger.append(
            Record(
                claim_id,
                1,
                "claim",
                draft.request.times[str(draft.request.events[0]["id"])],
                "workflow",
                None,
                known_evidence,
                {
                    "status": status,
                    "text": draft.proposal.text,
                    "attempt": draft.attempt + 1,
                    "reasons": list(reasons),
                    "evidence": list(draft.proposal.evidence),
                },
            )
        )
        history = [
            *draft.history,
            {
                "status": status,
                "text": draft.proposal.text,
                "reasons": list(reasons),
            },
        ]
        if status != "verified":
            self.trace.append(f"producer: {status}; template remains on air")
            await ctx.yield_output(
                WorkflowResult(
                    status,
                    None,
                    draft.proposal,
                    draft.attempt + 1,
                    tuple(history),
                    tuple(self.trace),
                )
            )
            return
        event_id = draft.proposal.evidence[0]
        t = draft.request.times[event_id]
        cue = {
            "id": f"cue-workflow-{event_id}-analyst",
            "t_in": t,
            "t_out": round(t + DISPLAY_SECONDS, 2),
            "kind": "insight",
            "slot": "lower_third",
            "anchor": None,
            "persona": "analyst",
            "lang": "en",
            "text": draft.proposal.text,
            "verified": True,
            "replaces": f"cue-{event_id}-analyst",
            "evidence": list(draft.proposal.evidence),
        }
        validate(cue, OVERLAY_SCHEMA)
        await self.ledger.append(
            Record(cue["id"], 1, "cue", t, "producer", None, tuple(cue["evidence"]), cue)
        )
        self.trace.append("producer: verified alternative replaces template")
        await ctx.yield_output(
            WorkflowResult(
                "verified",
                cue,
                draft.proposal,
                draft.attempt + 1,
                tuple(history),
                tuple(self.trace),
            )
        )


async def run_workflow(
    *,
    seed: int = 7,
    minutes: float = 5,
    window: tuple[float, float] | None = None,
    plant: bool = False,
    ledger: Ledger | None = None,
    asks: Mapping[str, Ask] | None = None,
    analyst: Ask | None = None,
    tactician: Ask | None = None,
    challenger: DecisionAsk | None = None,
    judge: DecisionAsk | None = None,
    judge_timeout_seconds: float = 1.0,
    models: Models | None = None,
    live_models: bool = False,
) -> WorkflowResult:
    if live_models:
        if models is not None:
            raise ValueError("live_models cannot be combined with injected models")
        return await _run_live_workflow(
            seed=seed,
            minutes=minutes,
            window=window,
            plant=plant,
            ledger=ledger,
            judge_timeout_seconds=judge_timeout_seconds,
        )
    store = ledger or InMemoryLedger()
    events = list(match_events(seed, minutes))
    await load_match(store, events, ())
    template = await template_cues(store)
    for cue in template:
        if window is not None and not window[0] <= cue["t_in"] <= window[1]:
            continue
        await store.append(
            Record(
                cue["id"],
                1,
                "cue",
                cue["t_in"],
                "template",
                None,
                tuple(cue["evidence"]),
                cue,
            )
        )
    records = await store.query(kind="event")
    selected = tuple(
        record.payload for record in records
        if window is None or window[0] <= record.t <= window[1]
    )
    if not selected:
        raise ValueError("window contains no events")
    known = {record.id: record.payload for record in records}
    times = {record.id: record.t for record in records}
    trace: list[str] = ["template cues: aired before model calls"]
    turns: list[Turn] = []
    adapters = dict(asks or {})
    if analyst is not None:
        adapters["analyst"] = analyst
    if tactician is not None:
        adapters["tactician"] = tactician
    if models is not None:
        if models.analyst is not None:
            adapters["analyst"] = models.analyst
        if models.tactician is not None:
            adapters["tactician"] = models.tactician
        challenger = models.challenger or challenger
        judge = models.judge or judge
        judge_timeout_seconds = models.judge_timeout_seconds
    analyst_executor = AnalystExecutor(
        adapters.get("analyst", lambda p: _scripted_ask("analyst", p)),
        trace,
        turns,
        plant,
    )
    tactician_executor = TacticianExecutor(
        adapters.get("tactician", lambda p: _scripted_ask("tactician", p)),
        trace,
        turns,
    )
    challenger_executor = ChallengerExecutor(trace, challenger, turns)
    judge_executor = JudgeExecutor(trace, judge, turns, judge_timeout_seconds)
    producer = ProducerExecutor(store, trace)
    request = Request(selected, known, times, window, plant, store)
    workflow = (
        WorkflowBuilder(start_executor=analyst_executor)
        .add_edge(analyst_executor, tactician_executor)
        .add_edge(tactician_executor, challenger_executor)
        .add_edge(challenger_executor, judge_executor)
        .add_edge(judge_executor, analyst_executor)
        .add_edge(judge_executor, tactician_executor)
        .add_edge(judge_executor, producer)
        .build()
    )
    result = await workflow.run(request)
    outcome = result.get_outputs()[0]
    outcome = WorkflowResult(
        outcome.category,
        outcome.cue,
        outcome.proposal,
        outcome.attempts,
        outcome.claim_history,
        tuple(trace),
        tuple(str(event["id"]) for event in selected),
        len(turns),
    )
    return outcome


async def replay(recording: Recording) -> WorkflowResult:
    queue = list(recording.turns)
    asks = _replay(queue)
    result = await run_workflow(
        seed=recording.seed,
        minutes=recording.minutes,
        window=_window(recording.window),
        plant=recording.plant,
        asks=asks,
    )
    if queue:
        raise ReplayMismatch(f"recording has {len(queue)} unused role turn(s)")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Run or replay workflow v1 without Azure.")
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--minutes", type=float, default=5)
    parser.add_argument("--window", help="event window in START-END seconds")
    parser.add_argument("--plant", action="store_true", help="plant a false first claim")
    parser.add_argument("--record", type=Path)
    parser.add_argument("--replay", type=Path)
    parser.add_argument("--cues-out", type=Path, help="write every aired cue for the selected window")
    parser.add_argument("--live-models", action="store_true", help="use Foundry and MCP adapters")
    args = parser.parse_args()
    if args.record and args.replay:
        parser.error("--record and --replay cannot be combined")
    selected_window = _window(args.window)
    if args.replay:
        result = asyncio.run(replay(Recording.load(args.replay)))
    else:
        turns: list[Turn] = []
        asks = None
        cli_ledger = InMemoryLedger()
        if args.record:
            adapters = _recording_adapters(turns)
            asks = adapters
        result = asyncio.run(
            run_workflow(
                seed=args.seed,
                minutes=args.minutes,
                window=selected_window,
                plant=args.plant,
                asks=asks,
                ledger=cli_ledger,
                live_models=args.live_models,
            )
        )
        if args.cues_out:
            cues = asyncio.run(_aired_cues(cli_ledger, selected_window))
            write_fixture(cues, args.cues_out)
        if args.record:
            Recording(
                WORKFLOW_REPLAY_FORMAT,
                args.seed,
                args.minutes,
                "scripted",
                datetime.now(UTC).isoformat(timespec="seconds"),
                turns,
                args.window,
                args.plant,
            ).save(args.record)
    for line in result.trace:
        print(line)
    print(result.category.upper())
    if result.category == "held":
        print("template cue remains on air")


def _recording_adapters(turns: list[Turn]) -> dict[str, Ask]:
    async def adapter(role: str, prompt: str) -> dict:
        response = await _scripted_ask(role, prompt)
        turns.append(Turn(role, prompt, json.dumps(response)))
        return response

    async def challenger(prompt: str) -> dict:
        response = {"category": "agree", "reasons": []}
        turns.append(Turn("challenger", prompt, json.dumps(response)))
        return response

    async def judge(prompt: str) -> dict:
        response = {"category": "verified", "reasons": []}
        turns.append(Turn("judge", prompt, json.dumps(response)))
        return response

    return {
        **{
            role: (lambda prompt, role=role: adapter(role, prompt))
            for role in ("analyst", "tactician")
        },
        "challenger": challenger,
        "judge": judge,
    }


async def _template_only(
    seed: int, minutes: float, window: tuple[float, float] | None = None
) -> list[dict]:
    ledger = InMemoryLedger()
    await load_match(ledger, list(match_events(seed, minutes)), ())
    cues = await template_cues(ledger)
    if window is None:
        return cues
    return [cue for cue in cues if window[0] <= cue["t_in"] <= window[1]]


async def _aired_cues(ledger: Ledger, window: tuple[float, float] | None) -> list[dict]:
    records = await ledger.query(kind="cue")
    cues = [record.payload for record in records]
    if window is None:
        return cues
    return [cue for cue in cues if window[0] <= cue["t_in"] <= window[1]]


if __name__ == "__main__":
    main()
