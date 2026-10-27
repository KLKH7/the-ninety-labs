"""The agents live on the demo match: the whole graph and the Companion at chosen match moments,
every handoff, model call and MCP tool call in one trace, scored against a plan fixed beforehand.

    uv run python -m ninety.eval.agents_live --detected <detected.jsonl> --insights <insights.json> \
        --out runs/agents-live/seed8324 [--only goal-1] [--drills] [--max-calls 10]
    uv run python -m ninety.eval.agents_live --score runs/agents-live/seed8324   # score a trace again

The plan (moments, questions, expected tools, argument rules, drills) is docs/eval/agents-live-plan.md,
committed before the first live call; this file implements it and changes none of it.

For each moment:
- the graph (workflow.run_live) on the moment's minute, on the bundle's detected events, inline under
  an unserved id (lesson 90), with the published agents wrapped by an observer that times each call
  and reads the tokens the service reports;
- the Companion (companion_match.answer_match, its production 10 s budget, the Judge) asked the
  moment's question, with every insight tool executed through the real MCP server
  (ninety/mcp/match_server.py over stdio), so each tool call is an MCP call_tool.

Live calls need `az login` (DefaultAzureCredential); no key is read or written. The trace holds the
synthetic match's facts and the agents' prompts and replies, nothing else.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import inspect
import json
import logging
import os
import statistics
import sys
import tempfile
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from ninety.agents import companion_match as cm
from ninety.agents import workflow
from ninety.agents.contracts import Question, status_for
from ninety.eval import latency_cost as lc
from ninety.eval.companion_tools import right
from ninety.match import detected
from ninety.mcp import match_server

PLAN = "docs/eval/agents-live-plan.md"
COMPANION_TIMEOUT_S = cm.TIMEOUT_S  # the phone's production budget
ASK_AFTER_S = 20.0  # the fan asks 20 s after the moment
HALF_TIME_AFTER_S = 5.0
BUDGET_USD = 4.0  # the plan: stop when the run's estimate passes $4
SLOW_TACTICIAN_S = 65.0  # drill: past the workflow's 60 s budget
SLOW_COMPANION_S = 12.0  # drill: past the Companion's 10 s budget
SHAPE_DROP = ("kind", "t", "also", "visual", "club")  # MatchInsights' additions to a shape row


class OverBudget(BaseException):  # not Exception: the agents' own guards must not swallow it
    """The run reached its call cap or its spend cap: stop, report what ran."""


# ---------------------------------------------------------------------------------------------
# Moments, by the plan's rules
# ---------------------------------------------------------------------------------------------


@dataclass
class Spec:
    key: str
    kind: str
    minute: int
    t: float
    club: str | None
    other: str | None
    anchor: str | None  # the detected event the graph's Analyst must be given
    target: str | None  # the fact the Companion's tools must return
    question: str
    tool: str
    ask_t: float


def minute_of(t: float) -> int:
    return int(t // 60) + 1


def _clubs(mi, team: str | None) -> tuple[str | None, str | None]:
    if team not in ("home", "away"):
        return None, None
    other = "away" if team == "home" else "home"
    return mi.fixture.clubs[team], mi.fixture.clubs[other]


def select(events: list[dict], mi) -> list[Spec]:
    """The plan's moments, by its rules only."""
    specs: list[Spec] = []
    goals = sorted(mi.facts.get("goal", []), key=lambda f: f["t"])
    goal_minutes = {f["minute"] for f in goals}
    for n, g in enumerate(goals, 1):
        club, other = _clubs(mi, g.get("team"))
        specs.append(Spec(f"goal-{n}", "goal", g["minute"], g["t"], club, other, g.get("event"), g["id"],
                          "What led to that goal?", "goal_build_up", g["t"] + ASK_AFTER_S))

    def best(kind: str, key) -> dict | None:
        rows = [f for f in mi.facts.get(kind, []) if f.get("confident") and f["minute"] not in goal_minutes]
        return min(rows, key=key) if rows else None

    lb = best("line_break", lambda f: (-f["value"], f["t"]))
    if lb is not None:
        club, other = _clubs(mi, lb.get("team"))
        specs.append(Spec("line-break", "line_break", lb["minute"], lb["t"], club, other, lb.get("event"),
                          lb["id"], f"Which pass cut through {other}'s lines just now?", "line_breaks",
                          lb["t"] + ASK_AFTER_S))
    ov = best("overload", lambda f: (-f["value"], -f.get("duration_s", 0.0), f["t"]))
    if ov is not None:
        club, other = _clubs(mi, ov.get("team"))
        specs.append(Spec("overload", "overload", ov["minute"], ov["t"], club, other, None, ov["id"],
                          f"Where are {club} outnumbering {other}?", "overloads",
                          ov.get("t_to", ov["t"]) + ASK_AFTER_S))
    by_minute: dict[int, list[dict]] = {}
    for e in events:
        by_minute.setdefault(minute_of(e["t"]), []).append(e)
    loud = {minute_of(e["t"]) for e in events if e["type"] in ("shot", "goal")}
    quiet = [m for m, es in by_minute.items()
             if len(es) >= 3 and not any(abs(m - x) <= 2 for x in loud)]
    if quiet:
        m = min(quiet, key=lambda m: (len(by_minute[m]), m))
        last = max(e["t"] for e in by_minute[m])
        specs.append(Spec("quiet", "quiet", m, last, None, None, None, None,
                          "Has anything happened in the last few minutes?", "key_moments",
                          last + ASK_AFTER_S))
    first_half = [m for m in by_minute if m <= 45]
    if first_half:
        m = max(first_half)
        last = max(e["t"] for e in by_minute[m])
        specs.append(Spec("half-time", "half_time", m, last, None, None, None, None,
                          "Who had more of the ball in the first half?", "possession",
                          last + HALF_TIME_AFTER_S))
    return specs


def args_right(spec: Spec, call: dict | None) -> bool:
    """The plan's argument rule for the expected tool's call, as the model wrote it."""
    if call is None:
        return False
    club = call.get("club")
    club_ok = club is None or (
        spec.club is not None and isinstance(club, str) and club.lower() == spec.club.lower())
    lo, hi = call.get("minute_from"), call.get("minute_to")
    asked = minute_of(spec.ask_t)
    if spec.kind == "goal":
        return isinstance(hi, int) and hi >= spec.minute and club_ok
    if spec.kind == "half_time":
        return isinstance(lo, int) and isinstance(hi, int) and lo <= 2 and hi >= asked - 1
    window = isinstance(lo, int) and isinstance(hi, int) and lo <= spec.minute <= hi
    return window and (club_ok if spec.kind in ("line_break", "overload") else True)


# ---------------------------------------------------------------------------------------------
# The trace
# ---------------------------------------------------------------------------------------------


@dataclass
class Trace:
    path: Path
    max_calls: int
    budget_usd: float = BUDGET_USD
    calls: int = 0
    usd: float = 0.0
    scope: dict = field(default_factory=dict)  # moment key and run (graph, companion, drill) now
    started: float = field(default_factory=time.perf_counter)

    def write(self, kind: str, **body) -> None:
        row = {"kind": kind, "at_s": round(time.perf_counter() - self.started, 3), **self.scope, **body}
        with self.path.open("a") as f:
            f.write(json.dumps(row, separators=(",", ":"), default=str) + "\n")

    def spend(self, tokens_in: int, tokens_out: int) -> float:
        usd = float(lc.price(lc.INPUT) * tokens_in + lc.price(lc.OUTPUT) * tokens_out)
        self.usd += usd
        return usd

    def admit(self) -> None:
        if self.calls >= self.max_calls:
            raise OverBudget(f"call cap {self.max_calls} reached")
        if self.usd >= self.budget_usd:
            raise OverBudget(f"spend cap ${self.budget_usd} reached (${self.usd:.3f})")
        self.calls += 1


class Observed:
    """A published agent as a role calls it: each call timed, its tokens as the service reports
    them (else estimated, and marked so), its hosted tool calls, and the prompt and reply. `fault`
    is a drill: an awaitable run before the real call, which may raise or sleep."""

    def __init__(self, trace: Trace, role: str, name: str, version: str, agent, fault=None):
        self.trace, self.role, self.name, self.version, self.agent, self.fault = (
            trace, role, name, version, agent, fault)

    async def run(self, prompt, **kwargs):
        self.trace.admit()
        t0, reply, error = time.perf_counter(), None, None
        try:
            if self.fault is not None:
                await self.fault()
            reply = await self.agent.run(prompt, **kwargs)
            return reply
        except BaseException as e:  # noqa: BLE001  (recorded, then raised as it was)
            error = ("cancelled (caller's timeout)" if isinstance(e, asyncio.CancelledError)
                     else f"{type(e).__name__}: {e}")
            raise
        finally:
            from ninety.agents import foundry

            text = prompt if isinstance(prompt, str) else str(prompt)
            reply_text = getattr(reply, "text", None) if reply is not None else None
            usage = getattr(reply, "usage_details", None) if reply is not None else None
            usage = usage if isinstance(usage, dict) else vars(usage) if usage is not None else {}
            t_in, t_out = usage.get("input_token_count"), usage.get("output_token_count")
            reported = t_in is not None and t_out is not None
            if not reported:
                t_in, t_out = lc.tokens(text), lc.tokens(reply_text or "")
            usd = self.trace.spend(t_in, t_out) if reply is not None else 0.0
            self.trace.write(
                "model_call", role=self.role, agent=f"{self.name}:{self.version}",
                ms=round((time.perf_counter() - t0) * 1000, 1), tokens_in=t_in, tokens_out=t_out,
                tokens_reported=reported, usd=round(usd, 6),
                hosted_tool_calls=foundry.tool_calls(reply) if reply is not None else [],
                prompt=text, reply=reply_text, error=error,
            )


# ---------------------------------------------------------------------------------------------
# The Companion's insight tools, through the real MCP server
# ---------------------------------------------------------------------------------------------


class MCPClient:
    """One stdio session to ninety.mcp.match_server, on its own thread and event loop, so the
    Companion's synchronous `run_tools` can call it. The server reads the match's precomputed
    insights from NINETY_MATCH_DIR/insights/<match>.json."""

    def __init__(self, match_dir: Path):
        self.loop = asyncio.new_event_loop()
        self.ready, self.session, self.error = threading.Event(), None, None
        self.thread = threading.Thread(target=self.loop.run_forever, daemon=True)
        self.thread.start()
        self.stop = None
        self.task = asyncio.run_coroutine_threadsafe(self._serve(match_dir), self.loop)
        if not self.ready.wait(120):
            raise RuntimeError("the MCP server did not start in 120 s")
        if self.error:
            raise RuntimeError(f"the MCP server did not start: {self.error}")

    async def _serve(self, match_dir: Path) -> None:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        self.stop = asyncio.Event()
        params = StdioServerParameters(
            command=sys.executable, args=["-m", "ninety.mcp.match_server"],
            env={**os.environ, "NINETY_MATCH_DIR": str(match_dir)},
        )
        try:
            async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
                await session.initialize()
                self.tools = [t.name for t in (await session.list_tools()).tools]
                self.session = session
                self.ready.set()
                await self.stop.wait()
        except Exception as e:  # noqa: BLE001
            self.error = f"{type(e).__name__}: {e}"
            self.ready.set()

    def call(self, name: str, args: dict) -> dict:
        result = asyncio.run_coroutine_threadsafe(self.session.call_tool(name, args), self.loop).result(60)
        if result.isError:
            raise RuntimeError(f"MCP {name} failed: {result.content[0].text if result.content else ''}")
        if result.structuredContent is not None:
            body = result.structuredContent
            return body["result"] if set(body) == {"result"} else body
        return json.loads(result.content[0].text)

    def close(self) -> None:
        if self.stop is not None:
            self.loop.call_soon_threadsafe(self.stop.set)
        with contextlib.suppress(Exception):
            self.task.result(30)
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.thread.join(10)


class MCPInsights:
    """The match's MatchInsights for everything but its tools: each insight tool the Companion (or
    code's fallback answer) calls goes to the MCP server as call_tool(name, {match, ...}), and the
    answer used is the server's. Each call is traced, with whether it equals the in-process result."""

    def __init__(self, mi, match: str, mcp: MCPClient, trace: Trace):
        self._mi, self._match, self._mcp, self._trace = mi, match, mcp, trace

    def __getattr__(self, name):
        value = getattr(self._mi, name)
        if name not in match_server.INSIGHT_TOOLS or not callable(value):
            return value
        ours = inspect.signature(value)  # the in-process method's parameters
        theirs = inspect.signature(getattr(match_server, name)).parameters

        def tool(*args, **kwargs):
            bound = ours.bind(*args, **kwargs)
            bound.apply_defaults()
            sent = {"match": self._match, **{k: v for k, v in bound.arguments.items() if k in theirs}}
            t0 = time.perf_counter()
            got = self._mcp.call(name, sent)
            ms = round((time.perf_counter() - t0) * 1000, 1)
            direct = json.loads(json.dumps(value(*args, **kwargs), default=str))
            mine = {k: v for k, v in got.items() if k not in ("match", "tracked", "clubs")}
            size = len(json.dumps(got, separators=(",", ":")))
            self._trace.write("mcp_call", tool=name, args=sent, ms=ms, result_bytes=size,
                              facts=len(got.get("facts", [])), summary=len(got.get("summary", [])),
                              fact_ids=[f["id"] for f in got.get("facts", [])][:40],
                              same_as_in_process=mine == direct)
            return mine

        return tool


# ---------------------------------------------------------------------------------------------
# Runs
# ---------------------------------------------------------------------------------------------


def shape_rows(mi) -> list[dict]:
    return [{k: v for k, v in r.items() if k not in SHAPE_DROP} for r in mi.facts.get("shape", [])]


def wrapper(trace: Trace, faults: dict | None = None):
    faults = faults or {}

    def wrap(role, name, version, agent):
        return Observed(trace, role, name, version, agent, faults.get(role))

    return wrap


async def graph(trace: Trace, credential, events, minute: int, match: str, shape, faults=None) -> dict:
    t0 = time.perf_counter()
    try:
        result, _turns, pins, failed, used = await workflow.run_live(
            lambda: events, minute, match_server.unserved(match), True, False, trace_to="none",
            credential=credential, shape=shape, wrap=wrapper(trace, faults),
        )
    except OverBudget:
        raise
    except Exception as e:  # noqa: BLE001  (a lost minute is a finding, recorded)
        trace.write("graph_error", minute=minute, error=f"{type(e).__name__}: {e}")
        return {"error": str(e)}
    for s in result.trace:
        trace.write("step", role=s.role, moment=s.moment, action=s.action, ms=s.ms, detail=s.detail,
                    fallback=s.fallback)
    for m in result.moments:
        trace.write("moment_picked", moment=m.id, main_event=m.main_event, evidence=list(m.evidence))
    for r in result.reviews:
        trace.write("review", moment=r.moment_id, status=r.status, author=r.author,
                    primary=asdict(r.primary), alternative=asdict(r.alternative) if r.alternative else None,
                    attempts=[list(a) for a in r.attempts],
                    drafted=asdict(r.drafted) if r.drafted else None,
                    aired=asdict(r.aired) if r.aired else None)
    templates = sum(1 for c in result.cues if c.get("kind") != "insight")
    insights = [c for c in result.cues if c.get("kind") == "insight"]
    trace.write("graph_done", minute=minute, ms=round((time.perf_counter() - t0) * 1000, 1),
                pins=pins, model_failed=failed, model_calls=result.model_calls,
                templates=templates, insights=[{"text": c.get("text"), "evidence": c.get("evidence")}
                                               for c in insights],
                minute_event_ids=[e["id"] for e in used if minute_of(e["t"]) == minute])
    return {"ok": True}


@contextlib.asynccontextmanager
async def companion_models(trace: Trace, credential, faults=None):
    from agent_framework.foundry import FoundryAgent

    from ninety import config
    from ninety.agents import foundry
    from ninety.agents.judge import judge as run_judge
    from ninety.agents.judge import judge_agent

    faults = faults or {}
    client = foundry.chat_client(credential)
    async with contextlib.AsyncExitStack() as stack:
        agents = {}
        for role, local in (("companion", cm.companion_match_agent(client)), ("judge", judge_agent(client))):
            name, version = foundry.pinned(local)
            published = await stack.enter_async_context(FoundryAgent(
                project_endpoint=config.FOUNDRY_PROJECT, agent_name=name, agent_version=version,
                credential=credential))
            agents[role] = Observed(trace, role, name, version, published, faults.get(role))

        async def ask(prompt: str) -> str:
            return (await agents["companion"].run(prompt)).text

        async def judge(claim, evidence):
            return await run_judge(agents["judge"], claim, evidence)

        yield ask, judge


async def companion(trace: Trace, credential, mi, insights, spec: Spec, faults=None) -> None:
    question = Question("agents-live", None, spec.question, spec.ask_t)
    t0 = time.perf_counter()
    async with companion_models(trace, credential, faults) as (ask, judge):
        r = await cm.answer_match(question, insights, ask, judge, timeout=COMPANION_TIMEOUT_S)
    a = r.answer
    trace.write("companion_done", question=spec.question, ask_t=spec.ask_t,
                ms=round((time.perf_counter() - t0) * 1000, 1), source=r.source, status=a.status,
                text=a.text, evidence=list(a.evidence), reasons=list(r.reasons),
                tools_used=[dict(c) for c in r.tools])


def dropout(events: list[dict], t: float, width: float = 60.0) -> tuple[list[dict], list[str]]:
    kept = [e for e in events if not (t - width / 2 <= e["t"] <= t + width / 2)]
    return kept, [e["id"] for e in events if e not in kept]


async def run(args) -> None:
    from ninety.agents import credentials
    from ninety.intel.match_insights import MatchInsights

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    events = workflow.agent_events(detected.load(Path(args.detected)))
    mi = MatchInsights.from_dict(json.loads(Path(args.insights).read_text()))
    match = mi.clip
    specs = select(events, mi)
    (out / "moments.json").write_text(json.dumps([asdict(s) for s in specs], indent=1) + "\n")
    if args.only:
        specs = [s for s in specs if s.key in args.only.split(",")]
    trace = Trace(out / "trace.jsonl", args.max_calls)
    trace.write("run_start", match=match, plan=PLAN, commit=workflow._commit(),
                at=datetime.now(UTC).isoformat(timespec="seconds"), detected=str(args.detected),
                insights=str(args.insights), moments=[s.key for s in specs], drills=args.drills)
    shape = shape_rows(mi)
    tmp = tempfile.TemporaryDirectory()
    (Path(tmp.name) / match_server.INSIGHTS_DIR).mkdir()
    (Path(tmp.name) / match_server.INSIGHTS_DIR / f"{match}.json").write_text(Path(args.insights).read_text())
    mcp = MCPClient(Path(tmp.name))
    trace.write("mcp_ready", tools=mcp.tools)
    insights = MCPInsights(mi, match, mcp, trace)
    done: set[int] = set()
    try:
        async with credentials.new_credential() as credential:
            await credentials.sign_in(credential)
            for spec in specs:
                trace.scope = {"key": spec.key, "run": "graph"}
                if spec.minute not in done and not args.skip_graph:
                    trace.write("moment_start", spec=asdict(spec))
                    await graph(trace, credential, events, spec.minute, match, shape)
                    done.add(spec.minute)
                elif spec.minute in done:
                    trace.write("moment_start", spec=asdict(spec), shares_graph_minute=spec.minute)
                if not args.skip_companion:
                    trace.scope = {"key": spec.key, "run": "companion"}
                    await companion(trace, credential, mi, insights, spec)
            if args.drills:
                await drills(trace, credential, events, mi, insights, match, shape, specs)
    except OverBudget as e:
        trace.scope = {}
        trace.write("stopped", reason=str(e))
        print(f"stopped: {e}", file=sys.stderr)
    finally:
        mcp.close()
        tmp.cleanup()
        trace.scope = {}
        trace.write("run_end", calls=trace.calls, usd=round(trace.usd, 4))
    print(f"{trace.calls} model call(s), ${trace.usd:.4f}; trace {trace.path}")


async def drills(trace, credential, events, mi, insights, match, shape, specs) -> None:
    from azure.core.exceptions import ServiceRequestError

    by = {s.key: s for s in specs}

    async def judge_down():
        raise ServiceRequestError("drill: the Judge's endpoint cannot be reached")

    async def slow(seconds):
        async def wait():
            await asyncio.sleep(seconds)
        return wait

    if (g := by.get("goal-1")) is not None:
        trace.scope = {"key": g.key, "run": "drill:judge-down"}
        trace.write("drill_start", injected="every Judge call raises ServiceRequestError")
        await graph(trace, credential, events, g.minute, match, shape, {"judge": judge_down})
        trace.scope = {"key": g.key, "run": "drill:judge-down-companion"}
        await companion(trace, credential, mi, insights, g, {"judge": judge_down})
    if (g := by.get("goal-2")) is not None:
        kept, dropped = dropout(events, g.t)
        trace.scope = {"key": g.key, "run": "drill:vision-dropout"}
        trace.write("drill_start", injected="no detected events in the 60 s around the goal",
                    dropped=dropped, window=[g.t - 30, g.t + 30])
        await graph(trace, credential, kept, g.minute, match, shape)
    if (s := by.get("line-break")) is not None:
        trace.scope = {"key": s.key, "run": "drill:slow-tactician"}
        trace.write("drill_start", injected=f"the Tactician answers after {SLOW_TACTICIAN_S} s (budget "
                    f"{workflow.MODEL_TIMEOUT_SECONDS} s)")
        await graph(trace, credential, events, s.minute, match, shape,
                    {"tactician": await slow(SLOW_TACTICIAN_S)})
    if (s := by.get("overload")) is not None:
        trace.scope = {"key": s.key, "run": "drill:slow-companion"}
        trace.write("drill_start", injected=f"the Companion answers after {SLOW_COMPANION_S} s (budget "
                    f"{COMPANION_TIMEOUT_S} s)")
        await companion(trace, credential, mi, insights, s, {"companion": await slow(SLOW_COMPANION_S)})


# ---------------------------------------------------------------------------------------------
# Scores, from the trace and the plan only
# ---------------------------------------------------------------------------------------------


def _rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _pct(xs: list[float]) -> dict:
    if not xs:
        return {"n": 0}
    return {"n": len(xs), "p50_ms": round(statistics.median(xs)), "max_ms": round(max(xs))}


def plan_of(reply: str | None) -> list[dict] | None:
    if reply is None:
        return None
    try:
        plan = cm.first_object(reply)
    except Exception:  # noqa: BLE001
        return []
    tools = plan.get("tools") if isinstance(plan, dict) else None
    return [c for c in tools if isinstance(c, dict)] if isinstance(tools, list) else []


def score(out: Path) -> dict:
    rows = _rows(out / "trace.jsonl")
    specs = {s["key"]: s for s in json.loads((out / "moments.json").read_text())}
    main = [r for r in rows if r.get("run") in ("graph", "companion")]
    per: dict[str, dict] = {}
    for key, spec in specs.items():
        mine = [r for r in main if r.get("key") == key]
        if not mine:
            continue
        g = [r for r in mine if r["run"] == "graph"]
        c = [r for r in mine if r["run"] == "companion"]
        shared = next((r["shares_graph_minute"] for r in g if r.get("shares_graph_minute")), None)
        if shared is not None:  # the graph ran under the moment that first had this minute
            first = next(k for k, s in specs.items() if s["minute"] == shared)
            g = [r for r in main if r.get("key") == first and r["run"] == "graph"]
        per[key] = moment_score(Spec(**spec), g, c)
    drill_rows = [r for r in rows if str(r.get("run", "")).startswith("drill:")]
    calls = [r for r in rows if r["kind"] == "model_call"]
    by_role: dict[str, list[float]] = {}
    for r in calls:
        if r["error"] is None:
            by_role.setdefault(r["role"], []).append(r["ms"])
    end = next((r for r in rows if r["kind"] == "run_end"), {})
    return {
        "moments": per,
        "totals": totals(per),
        "drills": drill_scores(drill_rows, specs),
        "latency": {
            **{f"model:{k}": _pct(v) for k, v in sorted(by_role.items())},
            "mcp_call": _pct([r["ms"] for r in rows if r["kind"] == "mcp_call"]),
            "graph_minute": _pct([r["ms"] for r in main if r["kind"] == "graph_done"]),
            "companion_answer": _pct([r["ms"] for r in main if r["kind"] == "companion_done"]),
        },
        "cost": {"calls": len(calls), "usd": round(sum(r["usd"] for r in calls), 4),
                 "tokens_in": sum(r["tokens_in"] for r in calls),
                 "tokens_out": sum(r["tokens_out"] for r in calls),
                 "tokens_reported": all(r["tokens_reported"] for r in calls if r["error"] is None),
                 "prices": lc.PRICES["read"]},
        "mcp": {"calls": sum(r["kind"] == "mcp_call" for r in rows),
                "same_as_in_process": all(r["same_as_in_process"] for r in rows if r["kind"] == "mcp_call")},
        "stopped": next((r["reason"] for r in rows if r["kind"] == "stopped"), None),
        "run": {k: end.get(k) for k in ("calls", "usd")},
    }


def moment_score(spec: Spec, g: list[dict], c: list[dict]) -> dict:
    s: dict = {"minute": spec.minute, "question": spec.question, "expected_tool": spec.tool}
    done = next((r for r in g if r["kind"] == "graph_done"), None)
    if done is not None:
        analyst = [r for r in g if r["kind"] == "model_call" and r["role"] == "analyst"]
        picked = [r for r in g if r["kind"] == "moment_picked"]
        reviews = [r for r in g if r["kind"] == "review"]
        given = set(done["minute_event_ids"]) | {i for r in picked for i in r["evidence"]}
        s["graph"] = {
            "anchor_given": None if spec.anchor is None else spec.anchor in done["minute_event_ids"],
            "analyst_picked_anchor": (None if spec.anchor is None
                                      else any(spec.anchor in r["evidence"] for r in picked)),
            "analyst_tool_calls": sum(len(r["hosted_tool_calls"]) for r in analyst),
            "tactician_context": all(
                all(i in r["prompt"] for i in p["evidence"])
                for p in picked for r in g
                if r["kind"] == "model_call" and r["role"] == "tactician"
                and f'"id":"{p["moment"]}"' in r["prompt"]),
            "moments": len(picked),
            "verdicts": verdict_counts(g),
            "ends": {st: sum(r["status"] == st for r in reviews) for st in ("verified", "rejected", "held")},
            "aired": [r["aired"] for r in reviews if r["aired"]],
            "grounded": all(r["aired"]["evidence"] and set(r["aired"]["evidence"]) <= given
                            for r in reviews if r["aired"]),
            "templates": done["templates"],
            "ms": done["ms"],
            "model_calls": done["model_calls"],
        }
    elif any(r["kind"] == "graph_error" for r in g):
        s["graph"] = {"error": next(r["error"] for r in g if r["kind"] == "graph_error")}
    cdone = next((r for r in c if r["kind"] == "companion_done"), None)
    if cdone is not None:
        asks = [r for r in c if r["kind"] == "model_call" and r["role"] == "companion"]
        plan_call = asks[0] if asks else None
        answer_call = asks[1] if len(asks) > 1 else None
        returned = plan_call is not None and plan_call["error"] is None
        plan = plan_of(plan_call["reply"]) if returned else None
        chosen = [p.get("name") for p in plan] if plan is not None else None
        expected = next((p for p in plan or [] if p.get("name") == spec.tool), None)
        # What the model was given to answer from: the facts in its answer prompt (the tools' results).
        given = _ids_in(answer_call["prompt"]) if answer_call is not None else set()
        every = {i for r in c if r["kind"] == "mcp_call" for i in r["fact_ids"]}
        cited = set(cdone["evidence"])
        s["companion"] = {
            "plan": plan,
            "tool_right": right(chosen, spec.tool) if plan is not None else None,
            "args_right": args_right(spec, expected) if plan is not None else None,
            "target_given": None if spec.target is None or plan is None else spec.target in given,
            "source": cdone["source"], "status": cdone["status"], "text": cdone["text"],
            "evidence": cdone["evidence"], "reasons": cdone["reasons"],
            # A model answer may cite only what its tools gave it; code's fallback only what MCP returned.
            "grounded": bool(cited) and cited <= (given if cdone["source"] == "model" else every | given),
            "mcp_calls": sum(r["kind"] == "mcp_call" for r in c), "ms": cdone["ms"],
        }
    return s


def _ids_in(text: str) -> set[str]:
    import re

    return set(re.findall(r'"id":\s*"([^"]+)"', text))


def verdict_counts(rows: list[dict]) -> dict:
    out = {"verified": 0, "rejected": 0, "held": 0, "rewrites": 0}
    for r in rows:
        if r["kind"] == "review":
            for v in (r["primary"], r["alternative"]):
                if v is not None:
                    from ninety.agents.factcheck import Verdict

                    out[status_for(Verdict(**v))] += 1
            out["rewrites"] += sum(max(0, n - 1) for _, n in r["attempts"])
    return out


def totals(per: dict) -> dict:
    gs = [m["graph"] for m in per.values() if "graph" in m and "error" not in m["graph"]]
    cs = [m["companion"] for m in per.values() if "companion" in m]
    answered = [c for c in cs if c["tool_right"] is not None]

    def frac(xs):
        xs = [x for x in xs if x is not None]
        return f"{sum(xs)}/{len(xs)}" if xs else "0/0"

    return {
        "tool_choice": frac([c["tool_right"] for c in answered]),
        "args": frac([c["args_right"] for c in answered]),
        "plans_not_returned": sum(c["tool_right"] is None for c in cs),
        "companion_target_given": frac([c["target_given"] for c in cs]),
        "companion_model_verified": sum(c["source"] == "model" and c["status"] == "verified" for c in cs),
        "companion_grounded": frac([c["grounded"] for c in cs if c["status"] == "verified"]),
        "anchor_given": frac([g["anchor_given"] for g in gs]),
        "analyst_picked_anchor": frac([g["analyst_picked_anchor"] for g in gs]),
        "analyst_tool_calls": sum(g["analyst_tool_calls"] for g in gs),
        "tactician_context": frac([g["tactician_context"] for g in gs]),
        "graph_aired": sum(len(g["aired"]) for g in gs),
        "graph_grounded": frac([g["grounded"] for g in gs if g["aired"]]),
        "graph_ends": {k: sum(g["ends"][k] for g in gs) for k in ("verified", "rejected", "held")},
        "graph_verdicts": {k: sum(g["verdicts"][k] for g in gs)
                           for k in ("verified", "rejected", "held", "rewrites")},
        "graph_errors": sum("error" in m.get("graph", {}) for m in per.values()),
    }


# The role whose call each drill fails: the drill is exercised only if the trace shows that call failing.
DRILL_ROLE = {"drill:judge-down": "judge", "drill:judge-down-companion": "judge",
              "drill:slow-tactician": "tactician", "drill:slow-companion": "companion"}


def drill_scores(rows: list[dict], specs: dict) -> dict:
    out = {}
    for run in dict.fromkeys(r["run"] for r in rows):
        mine = [r for r in rows if r["run"] == run]
        start = next((r for r in mine if r["kind"] == "drill_start"), {})
        reviews = [r for r in mine if r["kind"] == "review"]
        aired = [r["aired"] for r in reviews if r["aired"]]
        calls = [r for r in mine if r["kind"] == "model_call"]
        d = {
            "injected": start.get("injected"),
            "model_calls": len(calls),
            "failed_calls": [f'{r["role"]}: {r["error"]}' for r in calls if r["error"]],
            "ends": {st: sum(r["status"] == st for r in reviews) for st in ("verified", "rejected", "held")},
            "aired": aired,
            "steps": [f'{r["role"]} {r["action"]} {r["moment"]}: {r["detail"]}'
                      for r in mine if r["kind"] == "step"],
        }
        done = next((r for r in mine if r["kind"] in ("graph_done", "companion_done")), None)
        if done is not None:
            d["ms"] = done["ms"]
        if (c := next((r for r in mine if r["kind"] == "companion_done"), None)) is not None:
            d["companion"] = {k: c[k] for k in ("source", "status", "text", "reasons")}
        if err := next((r for r in mine if r["kind"] == "graph_error"), None):
            d["graph_error"] = err["error"]
        role = DRILL_ROLE.get(run)
        d["exercised"] = (bool(start.get("dropped")) if role is None
                          else any(r["role"] == role and r["error"] for r in calls))
        if run == "drill:vision-dropout":
            dropped = set(start.get("dropped", []))
            d["dropped"] = len(dropped)
            d["aired_cites_dropped"] = any(set(a["evidence"]) & dropped for a in aired)
            d["aired_says_goal"] = any("goal" in a["text"].lower() for a in aired)
        out[run] = d
    return out


def _yes(x) -> str:
    return "–" if x is None else ("yes" if x else "**no**")


def tables(result: dict) -> str:
    """The report's tables, rendered from score.json only."""
    lines = ["| moment | min | graph: anchor given / picked | graph: drafts v/r/h | graph aired | "
             "companion tool / args | target given | answer (source, status) |",
             "|---|---|---|---|---|---|---|---|"]
    for key, m in result["moments"].items():
        g, c = m.get("graph", {}), m.get("companion", {})
        if "error" in g:
            graph_cells = ["error", g["error"][:60], "–"]
        elif g:
            v = g["verdicts"]
            graph_cells = [f'{_yes(g["anchor_given"])} / {_yes(g["analyst_picked_anchor"])}',
                           f'{v["verified"]}/{v["rejected"]}/{v["held"]} ({v["rewrites"]} rewrites)',
                           "; ".join(f'"{a["text"]}"' for a in g["aired"]) or "template stays"]
        else:
            graph_cells = ["(shares a minute)", "", ""]
        comp = (f'{_yes(c.get("tool_right"))} / {_yes(c.get("args_right"))}' if c else "–")
        answer = f'"{c["text"]}" ({c["source"]}, {c["status"]})' if c else "–"
        lines.append(f'| {key} | {m["minute"]} | ' + " | ".join(graph_cells)
                     + f' | {comp} | {_yes(c.get("target_given")) if c else "–"} | {answer} |')
    lines += ["", "| stage | calls | p50 | max |", "|---|---|---|---|"]
    for stage, p in result["latency"].items():
        if p["n"]:
            lines.append(f'| {stage} | {p["n"]} | {p["p50_ms"] / 1000:.1f} s | {p["max_ms"] / 1000:.1f} s |')
    lines += ["", "| drill | injected | fault hit | ends (v/r/h) | aired | what happened |",
              "|---|---|---|---|---|---|"]
    for run, d in result["drills"].items():
        e = d["ends"]
        c = d.get("companion")
        what = c and f'Companion: {c["source"]} answer, {c["reasons"]}'
        what = what or d.get("graph_error") or "; ".join(d["steps"][-3:])[:300]
        if run == "drill:vision-dropout":
            what = (f'{d["dropped"]} events dropped; aired cites a dropped id: '
                    f'{_yes(d["aired_cites_dropped"])}; aired says goal: '
                    f'{_yes(d["aired_says_goal"])}. ' + what)
        aired = "; ".join(f'"{a["text"]}"' for a in d["aired"]) or "nothing"
        lines.append(f'| {run} | {d["injected"]} | {_yes(d["exercised"])} | '
                     f'{e["verified"]}/{e["rejected"]}/{e["held"]} | {aired} | '
                     f'{what.replace("|", "/")} |')
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> None:
    logging.getLogger("agent_framework").setLevel(logging.WARNING)
    ap = argparse.ArgumentParser(description="The agents live on the demo match, traced and scored.")
    ap.add_argument("--detected", type=Path)
    ap.add_argument("--insights", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--only", help="comma-separated moment keys")
    ap.add_argument("--drills", action="store_true")
    ap.add_argument("--max-calls", type=int, default=400)
    ap.add_argument("--skip-graph", action="store_true")
    ap.add_argument("--skip-companion", action="store_true")
    ap.add_argument("--list", action="store_true",
                    help="print the moments the plan's rules select; no live call")
    ap.add_argument("--score", action="store_true", help="score the trace in --out; no live call")
    args = ap.parse_args(argv)
    if args.score:
        result = score(args.out)
        (args.out / "score.json").write_text(json.dumps(result, indent=1) + "\n")
        (args.out / "tables.md").write_text(tables(result))
        print(json.dumps(result["totals"], indent=1))
        return
    if args.list:
        from ninety.intel.match_insights import MatchInsights

        events = workflow.agent_events(detected.load(args.detected))
        mi = MatchInsights.from_dict(json.loads(args.insights.read_text()))
        for s in select(events, mi):
            print(json.dumps(asdict(s)))
        return
    asyncio.run(run(args))
    result = score(args.out)
    (args.out / "score.json").write_text(json.dumps(result, indent=1) + "\n")
    (args.out / "tables.md").write_text(tables(result))
    print(json.dumps(result["totals"], indent=1))


if __name__ == "__main__":
    main()
