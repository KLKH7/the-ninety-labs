"""Detected events are the live path's only input (ninety/match/detected.py)."""

import json

import pytest

from ninety.match import detected
from ninety.match.facts import compact
from ninety.mcp import match_server

STANDIN = detected.FIXTURES / "detected-standin-seed900001.jsonl"


def rows(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def test_the_standin_is_marked_as_one_and_loads():
    events = detected.load(STANDIN)
    assert detected.is_standin(STANDIN)
    assert events and all(e["id"].startswith("standin-") for e in events)
    assert {e["source"] for e in events} == {"vision"}
    assert all(0 <= e["confidence"] <= 1 for e in events)


def test_r3s_detected_events_replace_the_standin_when_they_land(tmp_path, monkeypatch):
    monkeypatch.setattr(detected, "FIXTURES", tmp_path)
    assert detected.is_standin(detected.m1_path())
    (tmp_path / "detected-seed900001.jsonl").write_text(STANDIN.read_text())
    assert detected.m1_path() == tmp_path / "detected-seed900001.jsonl"
    assert not detected.is_standin(detected.m1_path())


def test_a_ground_truth_event_is_refused():
    event = {**rows(STANDIN)[0], "source": "truth", "confidence": None}
    with pytest.raises(ValueError, match="never ground truth"):
        detected.check([event])


def test_a_detection_without_confidence_is_refused():
    event = {**rows(STANDIN)[0], "confidence": None}
    with pytest.raises(ValueError, match="needs a confidence"):
        detected.check([event])


def test_an_event_outside_the_schema_is_refused():
    with pytest.raises(ValueError, match="not a match_event"):
        detected.check([{**rows(STANDIN)[0], "x": 140.0}])


def test_a_duplicate_id_is_refused():
    event = rows(STANDIN)[0]
    with pytest.raises(ValueError, match="duplicate"):
        detected.check([event, dict(event)])


@pytest.mark.parametrize("name", ["events.jsonl", "frames.jsonl"])
def test_the_answer_keys_files_are_refused_by_name(tmp_path, name):
    path = tmp_path / name
    path.write_text(STANDIN.read_text())  # valid detected events, wrong file: refused all the same
    with pytest.raises(ValueError, match="answer key"):
        detected.load(path)


def test_compact_carries_a_detections_confidence_and_tolerates_missing_fields():
    event = rows(STANDIN)[0]
    assert compact(event)["confidence"] == event["confidence"]
    bare = {k: event[k] for k in ("id", "t", "type", "team", "x", "y", "source", "confidence")}
    assert compact(bare)["player"] is None and "outcome" not in compact(bare)


def test_compact_adds_nothing_to_a_ground_truth_event():
    truth = {**rows(STANDIN)[1], "source": "truth", "confidence": None}
    assert "confidence" not in compact(truth)


def test_the_mcp_server_serves_the_m1_clip_from_detected_events():
    match_server.events_of.cache_clear()
    served = match_server.list_events(detected.M1_CLIP, 1, 2, None)
    assert served and all(e["id"].startswith("standin-") and "confidence" in e for e in served)
    assert {e["minute"] for e in match_server.list_events(detected.M1_CLIP, 2, 2, None)} == {2}
    assert match_server.match_info(detected.M1_CLIP)["minutes"] == 2
