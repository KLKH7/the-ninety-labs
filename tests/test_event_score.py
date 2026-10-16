"""The event scoring harness: hand-computed cases, one planted defect at a time, and a full run on
simulator events damaged in known ways (docs/EVALUATION.md, Vision scoring; LESSONS 8 and 11)."""

import json

import pytest

from ninety.eval.event_score import WINDOW_S, main, match, score
from ninety.eval.fake_detections import DAMAGES, expected_counts, fake_detections
from ninety.match.facts import match_events


def ev(id, t, kind="pass", team="home", x=50.0, y=34.0, source="truth"):
    return {"id": id, "t": t, "type": kind, "team": team, "x": x, "y": y, "source": source}


def det(id, t, kind="pass", team="home", x=50.0, y=34.0):
    return {**ev(id, t, kind, team, x, y, source="vision"), "confidence": 0.9}


def counts(report, kind="pass"):
    row = report["per_type"][kind]
    return row["tp"], row["fp"], row["fn"]


# Hand-computed cases


def test_three_passes_worked_by_hand():
    # Truth at 10, 20, 30 s; detections at 10.4, 25.0, 30.9 s. 10.4 and 30.9 are within 1 s of a
    # true pass; 25.0 is 5 s from the nearest. So 2 correct, 1 false alarm, 1 miss: P = R = F1 = 2/3.
    truth = [ev("t1", 10.0), ev("t2", 20.0), ev("t3", 30.0)]
    detected = [det("d1", 10.4), det("d2", 25.0), det("d3", 30.9)]
    report = score(truth, detected)
    assert counts(report) == (2, 1, 1)
    row = report["per_type"]["pass"]
    assert row["precision"] == pytest.approx(2 / 3)
    assert row["recall"] == pytest.approx(2 / 3)
    assert row["f1"] == pytest.approx(2 / 3)
    assert report["headline"]["pass_f1"] == pytest.approx(2 / 3)


def test_a_perfect_copy_scores_exactly_one():
    truth = [ev("t1", 1.0), ev("t2", 3.0, team="away"), ev("t3", 5.0, kind="shot"),
             ev("t4", 7.0, kind="tackle")]
    detected = [det("d" + e["id"], e["t"], e["type"], e["team"]) for e in truth]
    report = score(truth, detected)
    for row in report["per_type"].values():
        assert (row["precision"], row["recall"], row["f1"]) == (1.0, 1.0, 1.0)
        assert row["fp"] == row["fn"] == 0


def test_exactly_one_second_counts_and_just_over_does_not():
    assert WINDOW_S == 1.0
    assert counts(score([ev("t1", 10.0)], [det("d1", 11.0)])) == (1, 0, 0)
    assert counts(score([ev("t1", 10.0)], [det("d1", 9.0)])) == (1, 0, 0)
    assert counts(score([ev("t1", 10.0)], [det("d1", 11.01)])) == (0, 1, 1)


# One planted defect at a time: each must move the counts by exactly what it should


def test_a_small_time_shift_still_counts():
    assert counts(score([ev("t1", 10.0)], [det("d1", 10.5)])) == (1, 0, 0)


def test_a_large_time_shift_is_a_miss_and_a_false_alarm():
    assert counts(score([ev("t1", 10.0)], [det("d1", 12.0)])) == (0, 1, 1)


def test_a_deleted_event_is_a_miss():
    report = score([ev("t1", 10.0), ev("t2", 20.0)], [det("d1", 10.0)])
    assert counts(report) == (1, 0, 1)
    assert report["per_type"]["pass"]["precision"] == 1.0
    assert report["per_type"]["pass"]["recall"] == 0.5


def test_an_invented_event_is_a_false_alarm():
    report = score([ev("t1", 10.0)], [det("d1", 10.0), det("d2", 40.0)])
    assert counts(report) == (1, 1, 0)
    assert report["per_type"]["pass"]["precision"] == 0.5
    assert report["per_type"]["pass"]["recall"] == 1.0


def test_reporting_one_event_twice_counts_it_once():
    # One to one: a true event can be matched only once, so repeating a detection cannot pay.
    assert counts(score([ev("t1", 10.0)], [det("d1", 10.0), det("d2", 10.1)])) == (1, 1, 0)


def test_the_wrong_team_is_a_miss_and_a_false_alarm():
    assert counts(score([ev("t1", 10.0)], [det("d1", 10.0, team="away")])) == (0, 1, 1)


def test_the_wrong_type_is_a_miss_of_one_and_a_false_alarm_of_the_other():
    report = score([ev("t1", 10.0)], [det("d1", 10.0, kind="shot")])
    assert counts(report, "pass") == (0, 0, 1)
    assert counts(report, "shot") == (0, 1, 0)


# Nearest first


def test_the_nearer_detection_wins():
    pairs = match([ev("t1", 10.0)], [det("far", 10.8), det("near", 10.2)])
    assert [(p["truth_id"], p["detected_id"]) for p in pairs] == [("t1", "near")]


def test_nearest_first_can_pair_fewer_than_the_best_possible():
    # Written down so the behaviour is known, not hidden. Truth at 0.0 and 1.4 s; detections at
    # 0.9 and 2.3 s. The closest pair is 0.9 with 1.4 (0.5 s), taken first; that leaves 0.0 and 2.3
    # 2.3 s apart. The best possible pairing (0.9 with 0.0, 2.3 with 1.4) would match both.
    report = score([ev("t1", 0.0), ev("t2", 1.4)], [det("d1", 0.9), det("d2", 2.3)])
    assert counts(report) == (1, 1, 1)


# Undefined is not zero


def test_no_detections_of_a_type_leaves_precision_undefined():
    report = score([ev("t1", 10.0, kind="shot")], [])
    row = report["per_type"]["shot"]
    assert (row["tp"], row["fp"], row["fn"]) == (0, 0, 1)
    assert row["precision"] is None
    assert row["recall"] == 0.0
    assert row["f1"] is None


def test_no_true_events_of_a_type_leaves_recall_undefined():
    row = score([], [det("d1", 10.0, kind="shot")])["per_type"]["shot"]
    assert row["precision"] == 0.0
    assert row["recall"] is None
    assert row["f1"] is None


def test_all_wrong_gives_f1_zero_not_undefined():
    row = score([ev("t1", 10.0)], [det("d1", 30.0)])["per_type"]["pass"]
    assert (row["precision"], row["recall"], row["f1"]) == (0.0, 0.0, 0.0)


# What the report records besides the counts


def test_matched_pairs_report_time_and_distance():
    pairs = match([ev("t1", 10.0, x=50.0, y=30.0)], [det("d1", 10.3, x=53.0, y=34.0)])
    assert pairs == [{"truth_id": "t1", "detected_id": "d1", "type": "pass", "team": "home",
                      "dt_s": pytest.approx(0.3), "distance_m": pytest.approx(5.0)}]


def test_the_command_writes_a_report_with_its_inputs(tmp_path):
    truth, detected = tmp_path / "truth.jsonl", tmp_path / "detected.jsonl"
    truth.write_text("".join(json.dumps(e) + "\n" for e in [ev("t1", 10.0), ev("t2", 20.0)]))
    detected.write_text(json.dumps(det("d1", 10.2)) + "\n")
    out = tmp_path / "report.json"
    main(["--truth", str(truth), "--detected", str(detected), "--report", str(out)])
    report = json.loads(out.read_text())
    assert report["rules"]["time_window_s"] == 1.0
    assert set(report["inputs"]) >= {"truth", "detected", "git_commit", "date"}
    assert counts(report) == (1, 0, 1)
    assert report["pairs"][0]["detected_id"] == "d1"


def test_the_command_refuses_events_from_the_wrong_side(tmp_path):
    # Truth must be truth and detections must be vision, so the two files cannot be swapped.
    path = tmp_path / "events.jsonl"
    path.write_text(json.dumps(ev("t1", 10.0)) + "\n")
    with pytest.raises(ValueError, match="source"):
        main(["--truth", str(path), "--detected", str(path), "--report", str(tmp_path / "r.json")])


# Fake detections from the simulator: damage planted in known amounts must be scored exactly


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_simulator_events_damaged_in_known_ways_score_as_predicted(seed):
    truth = list(match_events(7, 5))
    detected, log = fake_detections(truth, seed=seed, per_damage=2)
    assert {entry["damage"] for entry in log} == set(DAMAGES)
    report = score(truth, detected)
    for kind, (tp, fp, fn) in expected_counts(truth, log).items():
        assert counts(report, kind) == (tp, fp, fn), kind


def test_undamaged_simulator_events_score_exactly_one():
    truth = list(match_events(7, 5))
    detected, log = fake_detections(truth, seed=1, per_damage=0)
    assert log == []
    for row in score(truth, detected)["per_type"].values():
        assert (row["precision"], row["recall"], row["f1"]) == (1.0, 1.0, 1.0)


def test_fake_detections_refuse_damage_they_cannot_plant_cleanly():
    # Three passes 0.5 s apart: no damage can be planted without landing within 1 s of another
    # true pass, where it could be matched to the wrong one and the predicted score would lie.
    crowded = [ev("t1", 10.0), ev("t2", 10.5), ev("t3", 11.0)]
    with pytest.raises(ValueError, match="isolated"):
        fake_detections(crowded, seed=1, per_damage=1)
