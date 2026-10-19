"""Traces of every agent run, sent to the Application Insights resource connected to the Foundry
project (infra/main.bicep), where Foundry's tracing view shows them.

Agent Framework already records a span for each agent call, model call and tool call. We add two of
our own, so a run reads as football: `ninety.claim` around one claim's whole life (drafts,
checks, rewrites), and `ninety.fact_check` for each verdict, with the reasons a draft was rejected.

Prompt and reply text is recorded only with `content=True` (`--trace-content`): today it is
synthetic match data, but once viewers type into the app their words must not reach the logs.
"""

from __future__ import annotations

from contextlib import contextmanager

from opentelemetry import trace

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


@contextmanager
def claim_span(minute: int, seed: int, planted: bool, live: bool):
    with tracer().start_as_current_span("ninety.claim") as span:
        span.set_attributes(
            {"ninety.minute": minute, "ninety.seed": seed, "ninety.planted": planted, "ninety.live": live}
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


def record_description(event_id: str, source: str, aired: bool, ms_to_speech: float | None,
                       problems: list[str]) -> None:
    """One audio-description line: who wrote it, whether it aired and was spoken, and how long from
    the event reaching the Describer to audio in hand (ninety/agents/describer.py)."""
    with tracer().start_as_current_span("ninety.describe") as span:
        span.set_attributes(
            {
                "ninety.event": event_id,
                "ninety.source": source,
                "ninety.aired": aired,
                "ninety.spoken": ms_to_speech is not None,
                "ninety.ms_to_speech": -1.0 if ms_to_speech is None else ms_to_speech,
                "ninety.problems": problems,
            }
        )
