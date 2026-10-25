"""The audio-description report (docs/eval/describe.md) is current, and its counts mean what they say."""

import json

import pytest

from ninety.eval import describe_eval


def test_the_committed_report_is_current():
    assert describe_eval.REPORT.read_text() == describe_eval.report()


def test_coverage_counts_only_confident_graphic_events_and_never_exceeds_them():
    for path in describe_eval.CLIPS.values():
        m = describe_eval.measure(path)
        assert 0 <= m["covered"] <= m["confident"] <= m["events"]
        assert m["lines"] == sum(m["sources"].values())
        assert all(lag <= describe_eval.describe.MAX_LAG_S for lag in m["lags"])  # never said late
        assert m["spoken_s"] <= m["span_s"]


def test_an_unsure_event_is_not_counted_as_one_to_cover(tmp_path):
    import json

    rows = [json.loads(line) for line in describe_eval.CLIPS["seed900001 (hand-written stand-in, whole file)"]
            .read_text().splitlines()]
    path = tmp_path / "detected-standin-seed900001.jsonl"
    path.write_text("".join(json.dumps({**r, "confidence": 0.1}) + "\n" for r in rows))
    m = describe_eval.measure(path)
    assert m["confident"] == 0 and m["covered"] == 0


def test_on_the_pixel_clip_a_verified_insight_covers_its_event_and_false_detections_are_told_apart():
    m = describe_eval.measure(describe_eval.CLIPS["seed900001 (detected from the pixels)"])
    real = describe_eval.real_detections()
    # Events by what they are, not by id (lesson 243): the event report's matches on 900001 are
    # three passes and the possession change; the insight's event is the shot read as a pass, at
    # 71.52 s (frame 1788), a false detection.
    rows = describe_eval.detected.load(describe_eval.CLIPS["seed900001 (detected from the pixels)"])
    kinds = sorted(e["type"] for e in rows if e["id"] in real)
    assert kinds == ["pass", "pass", "pass", "possession_change"]
    shot_read_as_pass = next(e["id"] for e in rows if e["type"] == "pass" and e["frame"] == 1788)
    assert shot_read_as_pass in m["covered_ids"]  # said inside the verified claim
    assert shot_read_as_pass not in real


def _report_with(tmp_path, pair: dict):
    report = json.loads(describe_eval.EVENT_REPORT.read_text())
    clip = next(c for c in report["clips"] if c["seed"] == 900001)
    clip["events"]["time_only"]["pairs"] = [pair]
    path = tmp_path / "event-report.json"
    path.write_text(json.dumps(report))
    return path



@pytest.mark.parametrize("pair", [
    {"truth_id": "e1", "detected_id": "v99999", "type": "pass"},  # no such detected event
    {"truth_id": "e1", "detected_id": "v00006", "type": "shot"},  # the id now names another event
])
def test_a_report_pair_that_no_longer_names_its_event_is_refused(tmp_path, monkeypatch, pair):
    # Review of #268: the report grades detected events by id; an id that left the fixture, or now
    # names an event of another type, would grade another event's match.
    monkeypatch.setattr(describe_eval, "EVENT_REPORT", _report_with(tmp_path, pair))
    with pytest.raises(ValueError, match="is not the event it matched"):
        describe_eval.real_detections()


def test_a_report_pair_that_still_names_its_event_is_graded(tmp_path, monkeypatch):
    pair = {"truth_id": "e1", "detected_id": "v00006", "type": "pass"}
    monkeypatch.setattr(describe_eval, "EVENT_REPORT", _report_with(tmp_path, pair))
    # v00006 is the report's sixth event of the kinds it knew; kinds added since (pressure) do not
    # move it, and the fixture's own id for that event is returned.
    rows = describe_eval.detected.load(describe_eval.detected.FIXTURES / "detected-seed900001.jsonl")
    sixth = [e for e in rows if e["type"] in describe_eval.REPORT_KINDS][5]
    assert any(e["type"] not in describe_eval.REPORT_KINDS for e in rows)  # the premise: one was added
    assert describe_eval.real_detections() == {sixth["id"]} and sixth["type"] == "pass"
