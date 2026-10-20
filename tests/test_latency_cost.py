"""docs/eval/latency-cost.md: rebuilt byte for byte from its data, stage spans from the live chain,
and the cost arithmetic. No Azure: the e2e run is offline and the agents run from the recording."""

import asyncio
import json

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from ninety import e2e
from ninety.agents import telemetry
from ninety.agents.slice import Recording, replay_slice
from ninety.eval import latency_cost as lc
from tests.e2e_clip import write_clip


@pytest.fixture
def spans(monkeypatch):
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(telemetry, "TRACER_PROVIDER", provider)
    return exporter


def stages(exporter) -> list[str]:
    return [s.attributes["ninety.stage"] for s in exporter.get_finished_spans() if s.name == "ninety.stage"]


def test_the_report_rebuilds_byte_for_byte_from_its_data():
    assert lc.render(json.loads(lc.DATA.read_text())) == lc.REPORT.read_text()


def test_check_fails_when_the_report_is_stale(tmp_path, monkeypatch):
    stale = tmp_path / "latency-cost.md"
    stale.write_text(lc.REPORT.read_text().replace("Latency and cost", "Latency", 1))
    monkeypatch.setattr(lc, "REPORT", stale)
    with pytest.raises(SystemExit):
        lc.main(["--check"])


def test_every_stage_of_the_e2e_chain_is_a_span(tmp_path, spans):
    clip, detections, events = write_clip(tmp_path)
    args = e2e.parser().parse_args([str(clip), "--out", str(tmp_path / "bundle"), "--detections",
                                    str(detections), "--events-file", str(events), "--frames"])
    asyncio.run(e2e.run(args))
    assert set(stages(spans)) == set(telemetry.STAGES)


def test_each_draft_and_each_verdict_is_timed_in_replay(spans):
    outcome = asyncio.run(replay_slice(Recording.load(lc.RECORDING)))
    found = stages(spans)
    assert found.count("agents") == outcome.attempts
    assert found.count("fact_check") == outcome.attempts


def test_an_unknown_stage_is_refused():
    with pytest.raises(ValueError):
        with telemetry.stage_span("render"):
            pass


def test_percentile_is_nearest_rank():
    values = list(range(1, 21))  # 1..20
    assert lc.percentile(values, 0.5) == 10
    assert lc.percentile(values, 0.95) == 19
    assert lc.percentile([7.0], 0.95) == 7.0


def test_tokens_round_up_at_four_characters():
    assert lc.tokens("") == 0
    assert lc.tokens("abcd") == 1
    assert lc.tokens("abcde") == 2


def test_cost_uses_the_quoted_meters():
    call = {"turn": 1, "role": "judge", "call": "verdict", "input": 1000, "output": 1000}
    assert lc.cost([call]) == pytest.approx(0.0004 + 0.0016)
    assert lc.cost([call], lc.INPUT_DZ, lc.OUTPUT_DZ) == pytest.approx(0.00044 + 0.00176)
    assert lc.price(lc.SPEECH) == pytest.approx(15 / 1_000_000)


def test_an_analyst_turn_is_two_calls_and_a_judge_turn_one():
    recording = Recording.load(lc.RECORDING)
    calls = lc.model_calls(recording)
    roles = [t.role for t in recording.turns]
    assert len(calls) == 2 * roles.count("analyst") + roles.count("judge")
    for call in calls:
        assert call["input"] > 0 and call["output"] > 0
    # The answer is sent everything the tool request was, plus the tool's result.
    for request, answer in zip(calls, calls[1:], strict=False):
        if request["call"] == "tool request":
            assert answer["call"] == "answer" and answer["input"] > request["input"]


def test_a_clean_claim_is_one_analyst_turn_and_one_judge_call():
    calls = lc.model_calls(Recording.load(lc.RECORDING))
    clean = lc.clean_claim(calls)
    assert [c["role"] for c in clean].count("judge") == 1
    assert len({c["turn"] for c in clean if c["role"] == "analyst"}) == 1
    assert lc.cost(clean) < lc.cost(calls)


def test_the_published_data_matches_the_recording():
    """The committed token counts are what the recording gives today; re-measure when this fails."""
    data = json.loads(lc.DATA.read_text())
    assert data["calls"] == lc.model_calls(Recording.load(lc.RECORDING))
    assert data["graphics_text"] == lc.graphics_text()


def test_a_recount_rebuilds_the_tokens_and_keeps_the_timings():
    data = json.loads(lc.DATA.read_text())
    stale = {**data, "calls": [], "graphics_text": {}}
    fresh = lc.recount(stale)
    assert fresh["calls"] == lc.model_calls(Recording.load(lc.RECORDING))
    assert fresh["graphics_text"] == lc.graphics_text()
    assert {k: fresh[k] for k in ("latency", "commit", "measured", "machine")} == {
        k: data[k] for k in ("latency", "commit", "measured", "machine")
    }
    assert set(fresh["recounted"]) == {"commit", "date"}
    assert "Tokens re-counted" in lc.render(fresh)
