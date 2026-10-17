"""Every claim leaves a trace: one `ninety.claim` span holding a `ninety.fact_check` span per
verdict, with the reasons a draft was rejected. Runs the committed planted replay, no Azure."""

import asyncio
from pathlib import Path

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from ninety.agents import telemetry
from ninety.agents.slice import Recording, replay_slice

PLANTED = Path(__file__).parents[1] / "replays" / "slice-minute2-plant.json"


@pytest.fixture
def spans(monkeypatch):
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(telemetry, "TRACER_PROVIDER", provider)
    return exporter


def test_a_planted_claim_traces_its_rejection_and_its_rewrite(spans):
    outcome = asyncio.run(replay_slice(Recording.load(PLANTED)))
    finished = spans.get_finished_spans()
    claims = [s for s in finished if s.name == "ninety.claim"]
    checks = [s for s in finished if s.name == "ninety.fact_check"]

    assert len(claims) == 1 and len(checks) == outcome.attempts == 2
    claim = claims[0]
    assert claim.attributes["ninety.accepted"] is True and claim.attributes["ninety.drafts"] == 2
    assert claim.attributes["ninety.planted"] is True and claim.attributes["ninety.live"] is False

    rejected, accepted = sorted(checks, key=lambda s: s.attributes["ninety.attempt"])
    assert rejected.attributes["ninety.verdict"] == "rejected"
    assert any("143" in r for r in rejected.attributes["ninety.reasons"])
    assert accepted.attributes["ninety.verdict"] == "accepted" and accepted.attributes["ninety.reasons"] == ()
    # One trace per claim, so Foundry's tracing view shows the whole story together.
    assert {s.context.trace_id for s in checks} == {claim.context.trace_id}
    assert all(s.parent.span_id == claim.context.span_id for s in checks)
