"""The audio-description report (docs/eval/describe.md) is current, and its counts mean what they say."""

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


def test_an_unsure_event_is_not_counted_as_one_to_cover(tmp_path, monkeypatch):
    import json

    from ninety.match import detected

    rows = [json.loads(line) for line in describe_eval.CLIPS["seed900001 (hand-written stand-in)"]
            .read_text().splitlines()]
    path = tmp_path / "detected-standin-seed900001.jsonl"
    path.write_text("".join(json.dumps({**r, "confidence": 0.1}) + "\n" for r in rows))
    monkeypatch.setattr(detected, "FIXTURES", tmp_path)
    m = describe_eval.measure(path)
    assert m["confident"] == 0 and m["covered"] == 0
