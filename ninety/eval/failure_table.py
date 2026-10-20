"""Injected failures on the M1 live path, the fallback that ran, and what the viewer saw.

Each scenario runs the real live path (ninety/agents/live.run: detected events, Ledger, template
cues, the Analyst -> fact-checker workflow, the real Judge wrapper ninety/agents/judge.judge) on the
stand-in detected events of the M1 clip, with one failure injected at the model boundary: the
Analyst and the Judge are stand-ins that answer, fail, hang or reply with garbage. The Analyst
reads the match through the MCP server inside Foundry, so a tool error or an MCP timeout reaches
this code as the Analyst failing or not answering; that is where it is injected.

Timeouts are scaled down so the table regenerates in a second; the production values are printed
with it. tests/test_failure_table.py asserts every row.
"""

from __future__ import annotations

import asyncio
import inspect
import json
from collections.abc import Callable
from dataclasses import dataclass

from agent_framework.exceptions import AgentFrameworkException

from ninety.agents import live
from ninety.agents.factcheck import MIN_CONFIDENCE, Claim, Verdict
from ninety.agents.judge import RETRY_LIMIT, Judgement, Statement, judge
from ninety.agents.slice import MAX_REWRITES
from ninety.match import detected
from ninety.match.facts import compact

EVENTS_PATH = detected.FIXTURES / "detected-standin-seed900001.jsonl"
MINUTE = 2
JUDGE_TIMEOUT_PRODUCTION = inspect.signature(judge).parameters["timeout_seconds"].default
JUDGE_TIMEOUT = 0.05  # scaled down from JUDGE_TIMEOUT_PRODUCTION
AGENTS_TIMEOUT = 2.0  # scaled down from live.AGENTS_TIMEOUT_SECONDS
HANG = 60.0  # longer than any timeout here: the call never answers in time
PHANTOM_CONFIDENCE = 0.3  # the injected detection's confidence, below the gate


def events() -> list[dict]:
    return detected.load(EVENTS_PATH)


def sure_pass(evs: list[dict]) -> dict:
    """The confident completed pass in minute 2 the Analyst writes about (as tests/test_live.py)."""
    return next(e for e in evs if e["type"] == "pass" and e.get("receiver") and e["confidence"] >= 0.8
                and compact(e)["minute"] == MINUTE)


class _Reply:
    def __init__(self, value, text: str = ""):
        self.value, self.text = value, text


class JudgeModel:
    """A stand-in for the Judge's model: `ok` supports every claim, the others fail."""

    def __init__(self, mode: str):
        self.mode = mode

    async def run(self, prompt: str):
        if self.mode == "down":
            raise AgentFrameworkException("injected: Judge service unavailable")
        if self.mode == "hang":
            await asyncio.sleep(HANG)
        if self.mode == "malformed":
            return _Reply(None, "{\"statements\": \"not a list\"")
        claim = json.loads(prompt)["claim"]
        return _Reply(Judgement(statements=[
            Statement(text=claim, kind="fact", verdict="supported", reason="stand-in")
        ]))


def analyst(mode: str, event: dict) -> Callable:
    async def ask(prompt: str) -> str:
        if mode == "down":
            raise AgentFrameworkException("injected: Analyst's MCP tool call failed")
        if mode == "hang":
            await asyncio.sleep(HANG)
        if mode == "malformed":
            return "Sorry, the match tools returned nothing I can use."
        text = f"{event['player']} finds {event['receiver']}."
        return json.dumps({"text": text, "evidence": [event["id"]]})

    return ask


@dataclass
class Scenario:
    name: str
    injected: str
    analyst: str = "ok"
    judge: str = "ok"
    unsure: bool = False  # the detector reports the Analyst's event with low confidence


SCENARIOS = [
    Scenario("none", "nothing (the baseline)"),
    Scenario("judge down", "the Judge's model service fails on every call", judge="down"),
    Scenario("judge timeout", "the Judge never answers", judge="hang"),
    Scenario("judge malformed", "the Judge replies with JSON that is not its schema", judge="malformed"),
    Scenario("analyst down", "the Analyst fails: an MCP tool error or a model outage", analyst="down"),
    Scenario("mcp timeout", "the Analyst never answers: an MCP tool call that hangs", analyst="hang"),
    Scenario("analyst malformed", "the Analyst replies with prose, not claim JSON", analyst="malformed"),
    Scenario("low confidence", f"the detector reports the event the Analyst cites at confidence "
             f"{PHANTOM_CONFIDENCE}", unsure=True),
]


async def _run(s: Scenario) -> tuple[live.LiveResult, dict]:
    evs = events()
    event = sure_pass(evs)
    if s.unsure:
        evs = [{**e, "confidence": PHANTOM_CONFIDENCE} if e["id"] == event["id"] else e for e in evs]
    model = JudgeModel(s.judge)

    async def judge_fn(claim: Claim, evidence: list[dict]) -> Verdict:
        return await judge(model, claim, evidence, timeout_seconds=JUDGE_TIMEOUT)

    result = await live.run(evs, ask=analyst(s.analyst, event), judge=judge_fn, minute=MINUTE,
                            timeout_seconds=AGENTS_TIMEOUT)
    return result, event


def run(s: Scenario) -> dict:
    """One scenario's outcome, in the terms of the table."""
    result, event = asyncio.run(_run(s))
    templates = [c for c in result.cues if c["kind"] != "insight"]
    insight = [c for c in result.cues if c["kind"] == "insight"]
    if result.outcome is not None:
        last = result.outcome.trace[-1]
        fallback = last.removeprefix("fact_checker: ")
        status = result.outcome.status
        drafts = result.outcome.attempts
    else:
        fallback, status, drafts = f"workflow stopped ({result.agents_error})", "none", 0
    return {
        "status": status,
        "drafts": drafts,
        "fallback": fallback,
        "insight": [c["text"] for c in insight],
        "template_ids": [c["id"] for c in templates],
        "held_detections": result.held_detections,
        "event": event["id"],
    }


def _viewer(row: dict, base: dict) -> str:
    lost = sorted(set(base["template_ids"]) - set(row["template_ids"]))
    if not lost and row["template_ids"] == base["template_ids"]:
        graphics = f"all {len(row['template_ids'])} template cues, as without the failure"
    else:
        graphics = (f"{len(row['template_ids'])} template cues: the {len(lost)} on the unsure detection "
                    "are not drawn")
    insight = f"the verified insight \"{row['insight'][0]}\"" if row["insight"] else "no insight"
    return f"{graphics}; {insight}"


def report(command: str) -> str:
    rows = {s.name: run(s) for s in SCENARIOS}
    base = rows["none"]
    lines = [
        "# Failure table: injected failures on the live path",
        "",
        f"Generated by `{command}`. Each row runs the real live path "
        "(`ninety/agents/live.run`: detected events, Ledger, template cues, the Analyst to "
        "fact-checker workflow and the real Judge wrapper) on the M1 clip's stand-in detected "
        f"events, with the Analyst writing about the confident pass `{base['event']}` in minute "
        f"{MINUTE} and one failure injected at the model boundary. The Analyst reads the match over "
        "MCP inside Foundry, so a tool error or MCP timeout reaches our code as the Analyst failing "
        "or not answering: that is where those are injected. Every row is asserted by "
        "`tests/test_failure_table.py`.",
        "",
        "| Injected failure | Fallback that ran | Claim status | What the viewer saw | Test |",
        "|---|---|---|---|---|",
    ]
    for s in SCENARIOS:
        row = rows[s.name]
        drafts = f", after {row['drafts']} draft(s)" if row["drafts"] else ""
        lines.append(
            f"| {s.injected} | {row['fallback']} | {row['status']}{drafts} | {_viewer(row, base)} "
            f"| `test_failure_row[{s.name}]` |"
        )
    recovered = sum(
        not rows[s.name]["insight"] and set(rows[s.name]["template_ids"]) <= set(base["template_ids"])
        for s in SCENARIOS[1:]
    )
    lines += [
        "",
        f"**Recovered:** {recovered} of {len(SCENARIOS) - 1} injected failures: nothing unverified "
        "reached the screen and the template graphics stayed up.",
        "",
        "## Budgets",
        "",
        f"- The Judge: {JUDGE_TIMEOUT_PRODUCTION:g} s per call in production, tried "
        f"{RETRY_LIMIT + 1} times, on each of up to {MAX_REWRITES + 1} drafts; then the claim is "
        f"held (fail closed). Here {JUDGE_TIMEOUT:g} s.",
        f"- The whole Analyst to fact-checker workflow: {live.AGENTS_TIMEOUT_SECONDS:g} s in "
        f"production (`live.AGENTS_TIMEOUT_SECONDS`, a design value); then no insight airs and the "
        f"template cues stand. Here {AGENTS_TIMEOUT:g} s.",
        f"- The confidence gate: a claim citing a detection below {MIN_CONFIDENCE:.2f} is held, and a "
        "template cue is drawn only for a detection at or above it.",
        "",
        "Latencies are not measured here: every model is a stand-in, so a time would describe the "
        "stand-in. The live latencies belong to the deployed demo's traces.",
        "",
    ]
    return "\n".join(lines)
