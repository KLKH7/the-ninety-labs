"""Traces of every agent run, sent to the Application Insights resource connected to the Foundry
project (infra/main.bicep), where Foundry's tracing view shows them.

Agent Framework already records a span for each agent call, model call and tool call. We add two of
our own, so a run reads as football: `ninety.claim` around one claim's whole life (drafts,
checks, rewrites) in the slice, `ninety.minute` around one minute of the workflow, and
`ninety.fact_check` for each verdict, with the reasons a draft was rejected.

`ninety.stage` spans time the live chain stage by stage (STAGES), so latency from an event to its
graphic is read off the same traces in Application Insights, or in memory for
docs/eval/latency-cost.md (ninety/eval/latency_cost.py).

Prompt and reply text is recorded only with `content=True` (`--trace-content`): today it is
synthetic match data, but once viewers type into the app their words must not reach the logs.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from pathlib import Path

from opentelemetry import trace

log = logging.getLogger(__name__)

# Tests swap in an in-memory provider; None means the global one that Azure Monitor configures.
TRACER_PROVIDER: trace.TracerProvider | None = None


def tracer() -> trace.Tracer:
    return trace.get_tracer("ninety.agents", tracer_provider=TRACER_PROVIDER)


async def trace_to_foundry(client, content: bool = False) -> None:
    """Send this process's traces to the Foundry project's Application Insights."""
    await client.configure_azure_monitor(enable_sensitive_data=content)


def flush() -> None:
    """Export buffered spans before a short-lived process exits."""
    provider = TRACER_PROVIDER or trace.get_tracer_provider()
    force_flush = getattr(provider, "force_flush", None)
    if force_flush:
        force_flush()


# The live chain in order: frames to detections, detections to events, events to stats, the Analyst,
# the fact-checker (code checks and the Judge), and the cues the graphics draw.
STAGES = ("detect", "events", "stats", "agents", "fact_check", "cue")


@contextmanager
def stage_span(stage: str, **attributes):
    """One stage's work, timed: a `ninety.stage` span named by its `ninety.stage` attribute."""
    if stage not in STAGES:
        raise ValueError(f"unknown stage {stage!r}; stages: {', '.join(STAGES)}")
    with tracer().start_as_current_span("ninety.stage") as span:
        span.set_attributes({"ninety.stage": stage, **{f"ninety.{k}": v for k, v in attributes.items()}})
        yield span


@contextmanager
def claim_span(minute: int, seed: int, planted: bool, live: bool):
    with tracer().start_as_current_span("ninety.claim") as span:
        span.set_attributes(
            {"ninety.minute": minute, "ninety.seed": seed, "ninety.planted": planted, "ninety.live": live}
        )
        yield span


@contextmanager
def minute_span(minute: int, match: str, planted: bool, live: bool):
    """The workflow's span: one minute's moments, claims, checks and graphics."""
    with tracer().start_as_current_span("ninety.minute") as span:
        span.set_attributes(
            {"ninety.minute": minute, "ninety.match": match, "ninety.planted": planted, "ninety.live": live}
        )
        yield span


def record_fact_check(attempt: int, verdict: str, evidence: list[str], reasons: list[str]) -> None:
    """One fact-checking decision: accepted, rejected (sent back) or held back (out of rewrites)."""
    with tracer().start_as_current_span("ninety.fact_check") as span:
        span.set_attributes(
            {
                "ninety.attempt": attempt,
                "ninety.verdict": verdict,
                "ninety.evidence": evidence,
                "ninety.reasons": reasons,
            }
        )


# --- the phone's Ask ---------------------------------------------------------------------------
# One record per question (ninety/api/companion.py): who answered (code or model), why a model draft
# was dropped, the tools, each model step's latency, tokens and cost. The viewer's words never reach
# it: only their length and a hash. With Azure Monitor configured (APPLICATIONINSIGHTS_CONNECTION_STRING)
# it is a `ninety.ask` span there; otherwise one JSON line appended to NINETY_ASK_TRACE (default
# runs/ask-trace.jsonl) and written to this module's log, which the container's console log keeps.

# gpt-4.1-mini, USD per token: the Azure Retail Prices read on 2026-10-19 (docs/eval/latency-cost.md).
PRICE_IN, PRICE_OUT = 0.0004 / 1000, 0.0016 / 1000
ASK_TRACE_ENV, ASK_TRACE_DEFAULT = "NINETY_ASK_TRACE", "runs/ask-trace.jsonl"
_ASK: ContextVar[dict | None] = ContextVar("ninety_ask", default=None)
_monitor = {"configured": False}


def text_digest(text: str) -> dict:
    """What a record may keep of viewer text: its length and a hash, never the words."""
    return {"len": len(text), "sha256": hashlib.sha256(text.encode()).hexdigest()[:16]}


@contextmanager
def ask_trace(**fields):
    """The record of one question, open while it is answered, so each model step can add itself."""
    record = {"steps": [], **fields}
    token = _ASK.set(record)
    t0 = time.perf_counter()
    try:
        yield record
    finally:
        _ASK.reset(token)
        record["ms"] = round((time.perf_counter() - t0) * 1000, 1)


@contextmanager
def ask_step(step: str):
    """One model step of the open Ask record, timed. Outside an Ask (an eval, a test) it records nothing."""
    record = _ASK.get()
    entry = {"step": step, "outcome": "ok", "tokens_in": None, "tokens_out": None}
    if record is not None:
        record["steps"].append(entry)
    t0 = time.perf_counter()
    try:
        yield entry
    except BaseException as exc:
        if entry["outcome"] == "ok":
            entry["outcome"] = type(exc).__name__
        raise
    finally:
        entry["ms"] = round((time.perf_counter() - t0) * 1000, 1)


def note_usage(reply) -> None:
    """Add a model reply's reported tokens to the open step of the open Ask record."""
    record = _ASK.get()
    if record is None or not record["steps"]:
        return
    usage = getattr(reply, "usage_details", None)
    usage = usage if isinstance(usage, dict) else vars(usage) if usage is not None else {}
    entry = record["steps"][-1]
    for ours, theirs in (("tokens_in", "input_token_count"), ("tokens_out", "output_token_count")):
        if usage.get(theirs) is not None:
            entry[ours] = (entry[ours] or 0) + int(usage[theirs])


def finish_ask(record: dict) -> dict:
    """Totals for the record, then send it: a span with Azure Monitor, else a JSON line."""
    tokens_in = sum(s["tokens_in"] or 0 for s in record["steps"])
    tokens_out = sum(s["tokens_out"] or 0 for s in record["steps"])
    record.update(
        at=datetime.now(UTC).isoformat(timespec="seconds"),
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        usd=round(tokens_in * PRICE_IN + tokens_out * PRICE_OUT, 6),
    )
    if os.environ.get("APPLICATIONINSIGHTS_CONNECTION_STRING"):
        _to_monitor(record)
    else:
        _to_file(record)
    return record


def _to_monitor(record: dict) -> None:
    if not _monitor["configured"]:
        from azure.monitor.opentelemetry import configure_azure_monitor

        configure_azure_monitor()
        _monitor["configured"] = True
    with tracer().start_as_current_span("ninety.ask") as span:
        span.set_attributes({f"ninety.ask.{k}": v if isinstance(v, (str, int, float, bool)) else json.dumps(v)
                             for k, v in record.items() if v is not None})


def _to_file(record: dict) -> None:
    line = json.dumps(record, separators=(",", ":"), default=str)
    log.info("ninety.ask %s", line)
    path = Path(os.environ.get(ASK_TRACE_ENV) or ASK_TRACE_DEFAULT)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a") as f:
            f.write(line + "\n")
    except OSError as exc:  # a read-only image: the log line above still carries it
        log.warning("could not append the Ask trace to %s: %s", path, type(exc).__name__)
