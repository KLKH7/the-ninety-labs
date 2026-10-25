"""The event scoring harness: hand-computed cases, one planted defect at a time, and a full run on
simulator events damaged in known ways (docs/EVALUATION.md, Vision scoring; LESSONS 8 and 11)."""

import json
import math

import pytest

from ninety.eval.event_score import LENIENT_M, STRICT_M, WINDOW_S, main, match, reference_point, score
from ninety.eval.fake_detections import DAMAGES, expected_counts, fake_detections
from ninety.sim.engine import CONTROL_M, FPS, simulate


def ev(id, t, kind="pass", team="home", x=50.0, y=34.0, source="truth"):
    return {"id": id, "t": t, "type": kind, "team": team, "x": x, "y": y, "source": source}


def det(id, t, kind="pass", team="home", x=50.0, y=34.0):
    return {**ev(id, t, kind, team, x, y, source="vision"), "confidence": 0.9}


def counts(report, kind="pass", rule="time_only"):
    row = report[rule]["per_type"][kind]
    return row["tp"], row["fp"], row["fn"]


def ball_x(t):
    """The ball in the hand-made frames: along y = 34 at 10 m/s from x = 10, about a pass's speed."""
    return 10.0 + 10.0 * t


def frames(seconds=5.0):
    """Hand-made truth frames: the moving ball, h1 standing at (30, 20), a1 standing at (60, 50)."""
    out = []
    for k in range(round(seconds * FPS) + 1):
        t = k / FPS
        out.append({"frame": k, "t": t,
                    "ball": {"x": ball_x(t), "y": 34.0, "z": 0.0, "vx": 10.0, "vy": 0.0, "vz": 0.0},
                    "players": [{"id": "h1", "team": "home", "x": 30.0, "y": 20.0, "vx": 0.0, "vy": 0.0},
                                {"id": "a1", "team": "away", "x": 60.0, "y": 50.0, "vx": 0.0, "vy": 0.0}]})
    return out


# Hand-computed cases: time


def test_three_passes_worked_by_hand():
    # Truth at 10, 20, 30 s; detections at 10.4, 25.0, 30.9 s. 10.4 and 30.9 are within 1 s of a
    # true pass; 25.0 is 5 s from the nearest. So 2 correct, 1 false alarm, 1 miss: P = R = F1 = 2/3.
    truth = [ev("t1", 10.0), ev("t2", 20.0), ev("t3", 30.0)]
    detected = [det("d1", 10.4), det("d2", 25.0), det("d3", 30.9)]
    report = score(truth, detected)
    assert counts(report) == (2, 1, 1)
    row = report["time_only"]["per_type"]["pass"]
    assert row["precision"] == pytest.approx(2 / 3)
    assert row["recall"] == pytest.approx(2 / 3)
    assert row["f1"] == pytest.approx(2 / 3)


def test_a_perfect_copy_scores_exactly_one():
    truth = [ev("t1", 1.0), ev("t2", 3.0, team="away"), ev("t3", 5.0, kind="shot"),
             ev("t4", 7.0, kind="tackle")]
    detected = [det("d" + e["id"], e["t"], e["type"], e["team"]) for e in truth]
    for row in score(truth, detected)["time_only"]["per_type"].values():
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
    row = score([ev("t1", 10.0), ev("t2", 20.0)], [det("d1", 10.0)])["time_only"]["per_type"]["pass"]
    assert (row["tp"], row["fp"], row["fn"]) == (1, 0, 1)
    assert (row["precision"], row["recall"]) == (1.0, 0.5)


def test_an_invented_event_is_a_false_alarm():
    row = score([ev("t1", 10.0)], [det("d1", 10.0), det("d2", 40.0)])["time_only"]["per_type"]["pass"]
    assert (row["tp"], row["fp"], row["fn"]) == (1, 1, 0)
    assert (row["precision"], row["recall"]) == (0.5, 1.0)


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
    row = score([ev("t1", 10.0, kind="shot")], [])["time_only"]["per_type"]["shot"]
    assert (row["tp"], row["fp"], row["fn"]) == (0, 0, 1)
    assert (row["precision"], row["recall"], row["f1"]) == (None, 0.0, None)


def test_no_true_events_of_a_type_leaves_recall_undefined():
    row = score([], [det("d1", 10.0, kind="shot")])["time_only"]["per_type"]["shot"]
    assert (row["precision"], row["recall"], row["f1"]) == (0.0, None, None)


def test_all_wrong_gives_f1_zero_not_undefined():
    row = score([ev("t1", 10.0)], [det("d1", 30.0)])["time_only"]["per_type"]["pass"]
    assert (row["precision"], row["recall"], row["f1"]) == (0.0, 0.0, 0.0)


# Place: the detected spot against where the reference object really was at the detected time


def test_the_radii_are_the_ones_in_the_evaluation_rules():
    assert (STRICT_M, LENIENT_M) == (1.0, 2.0)


def test_without_frames_there_is_no_place_rule_and_no_headline():
    report = score([ev("t1", 1.0)], [det("d1", 1.0)])
    assert "strict" not in report and "lenient" not in report
    assert report["headline"]["pass_f1"] is None


def test_exactly_one_metre_is_strict_and_just_over_is_only_lenient():
    truth = [ev("t1", 2.0, x=ball_x(2.0))]
    at_edge = score(truth, [det("d1", 2.0, x=ball_x(2.0), y=35.0)], frames())
    assert counts(at_edge, rule="strict") == (1, 0, 0)
    over = score(truth, [det("d1", 2.0, x=ball_x(2.0), y=35.01)], frames())
    assert counts(over, rule="strict") == (0, 1, 1)
    assert counts(over, rule="lenient") == (1, 0, 0)


def test_exactly_two_metres_is_lenient_and_just_over_is_neither():
    truth = [ev("t1", 2.0, x=ball_x(2.0))]
    at_edge = score(truth, [det("d1", 2.0, x=ball_x(2.0), y=36.0)], frames())
    assert counts(at_edge, rule="lenient") == (1, 0, 0)
    over = score(truth, [det("d1", 2.0, x=ball_x(2.0), y=36.01)], frames())
    assert counts(over, rule="lenient") == (0, 1, 1)
    assert counts(over, rule="time_only") == (1, 0, 0)


def test_a_late_detection_is_judged_where_the_ball_was_when_it_says():
    # The heart of the rule. The pass is at 2.0 s; vision says 2.6 s. By then the ball is 6 m on.
    # Reporting where the ball really was at 2.6 s is right; reporting the kick spot is not, because
    # at 2.6 s nothing was there. Timing is graded by the time rule alone.
    truth = [ev("t1", 2.0, x=ball_x(2.0))]
    where_it_was = score(truth, [det("d1", 2.6, x=ball_x(2.6))], frames())
    assert counts(where_it_was, rule="strict") == (1, 0, 0)
    kick_spot = score(truth, [det("d1", 2.6, x=ball_x(2.0))], frames())
    assert counts(kick_spot, rule="strict") == (0, 1, 1)
    assert counts(kick_spot, rule="lenient") == (0, 1, 1)
    assert counts(kick_spot, rule="time_only") == (1, 0, 0)


def test_pressure_is_placed_at_the_nearest_player_of_its_team():
    truth = [ev("t1", 1.0, kind="pressure", x=30.0, y=20.0)]
    near_h1 = score(truth, [det("d1", 1.0, kind="pressure", x=30.5, y=20.0)], frames())
    assert counts(near_h1, "pressure", rule="strict") == (1, 0, 0)
    # At a1, who is on the other team: no home player is near, so the place is wrong.
    at_a1 = score(truth, [det("d1", 1.0, kind="pressure", x=60.0, y=50.0)], frames())
    assert counts(at_a1, "pressure", rule="lenient") == (0, 1, 1)


def test_a_window_cut_from_a_match_is_graded_by_frame_number():
    # The test clips are windows that keep the match's frame numbers (DATA_CONTRACT.md); their
    # first frame is not 0. The old scorer indexed by position and refused them.
    window = [f for f in frames(5.0) if f["frame"] >= 50]
    truth = [ev("t1", 3.0, x=ball_x(3.0))]
    assert counts(score(truth, [det("d1", 3.0, x=ball_x(3.0))], window), rule="strict") == (1, 0, 0)
    assert counts(score(truth, [det("d1", 3.0, x=ball_x(2.0))], window), rule="strict") == (0, 1, 1)
    # Before the window there is nothing to be right about, as after the last frame.
    early = score([ev("t2", 1.8, x=ball_x(1.8))], [det("d2", 1.9, x=ball_x(1.9))], window)
    assert counts(early, rule="time_only") == (1, 0, 0) and counts(early, rule="lenient") == (0, 1, 1)


def test_a_window_with_a_missing_frame_is_refused():
    window = [f for f in frames(5.0) if f["frame"] >= 50 and f["frame"] != 60]
    with pytest.raises(ValueError, match="consecutive"):
        score([ev("t1", 3.0, x=ball_x(3.0))], [det("d1", 3.0, x=ball_x(3.0))], window)


def test_a_time_outside_the_clip_has_nowhere_to_be_right():
    truth = [ev("t1", 4.8, x=ball_x(4.8))]
    report = score(truth, [det("d1", 5.5, x=ball_x(5.5))], frames(5.0))
    assert counts(report, rule="time_only") == (1, 0, 0)
    assert counts(report, rule="lenient") == (0, 1, 1)


def test_a_time_outside_the_clip_still_gives_strict_json():
    # The agents (R4) read the report, and JavaScript's JSON.parse rejects Infinity and NaN. The
    # time-only pair is kept, its place marked unmeasurable rather than infinitely wrong.
    truth = [ev("t1", 4.8, x=ball_x(4.8))]
    report = score(truth, [det("d1", 5.5, x=ball_x(5.5))], frames(5.0))
    json.dumps(report, allow_nan=False)
    [pair] = report["time_only"]["pairs"]
    assert (pair["place_error_m"], pair["outside_frames"]) == (None, True)
    inside = score(truth, [det("d1", 4.4, x=ball_x(4.4))], frames(5.0))["time_only"]["pairs"][0]
    assert (inside["place_error_m"], inside["outside_frames"]) == (0.0, False)


def test_a_substitution_is_graded_on_time_only():
    truth = [ev("t1", 1.0, kind="substitution", x=52.5, y=0.0)]
    report = score(truth, [det("d1", 1.0, kind="substitution", x=90.0, y=60.0)], frames())
    assert counts(report, "substitution", rule="strict") == (1, 0, 0)


def test_pairs_report_time_place_and_distance_to_the_true_event():
    truth = [ev("t1", 2.0, x=ball_x(2.0))]
    pairs = score(truth, [det("d1", 2.2, x=ball_x(2.2), y=34.5)], frames())["strict"]["pairs"]
    assert pairs == [{"truth_id": "t1", "detected_id": "d1", "type": "pass", "team": "home",
                      "dt_s": pytest.approx(0.2), "place_error_m": pytest.approx(0.5),
                      "outside_frames": False,
                      "distance_m": pytest.approx(math.hypot(2.0, 0.5))}]


# The command


def write_jsonl(path, rows):
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))
    return str(path)


def test_the_command_writes_a_report_with_its_inputs(tmp_path):
    true_events = [ev("t1", 2.0, x=ball_x(2.0)), ev("t2", 4.0, x=ball_x(4.0))]
    truth = write_jsonl(tmp_path / "truth.jsonl", true_events)
    detected = write_jsonl(tmp_path / "detected.jsonl", [det("d1", 2.2, x=ball_x(2.2))])
    frames_path = write_jsonl(tmp_path / "frames.jsonl", frames())
    out = tmp_path / "report.json"
    main(["--truth", truth, "--detected", detected, "--frames", frames_path, "--report", str(out)])
    report = json.loads(out.read_text())
    assert report["rules"]["time_window_s"] == 1.0
    assert (report["rules"]["strict_m"], report["rules"]["lenient_m"]) == (1.0, 2.0)
    assert set(report["inputs"]) >= {"truth", "detected", "frames", "git_commit", "date"}
    assert counts(report, rule="strict") == (1, 0, 1)
    assert report["headline"]["pass_f1"] == pytest.approx(2 / 3)


def test_the_command_needs_the_truth_frames(tmp_path):
    path = write_jsonl(tmp_path / "e.jsonl", [ev("t1", 1.0)])
    with pytest.raises(SystemExit):
        main(["--truth", path, "--detected", path, "--report", str(tmp_path / "r.json")])


def test_the_command_refuses_events_from_the_wrong_side(tmp_path):
    # Truth must be truth and detections must be vision, so the two files cannot be swapped.
    path = write_jsonl(tmp_path / "events.jsonl", [ev("t1", 1.0)])
    frames_path = write_jsonl(tmp_path / "frames.jsonl", frames())
    with pytest.raises(ValueError, match="source"):
        main(["--truth", path, "--detected", path, "--frames", frames_path,
              "--report", str(tmp_path / "r.json")])


# Simulator truth


@pytest.fixture(scope="module")
def seed7():
    return simulate(7, 5)


@pytest.mark.parametrize("seed", [7, 11])
def test_each_event_spot_is_at_its_reference_object(seed):
    # Guards what an event's x, y means. The engine records the point of contact, which a foot
    # reaches up to CONTROL_M from the body; the frame can then hold the object up to one frame of
    # travel further on. So the spot must be within CONTROL_M plus one frame of the reference's
    # speed. A wrong reference (a player for a ball event, or the reverse) is metres off.
    m = simulate(seed, 5)
    checked = 0
    for e in m.events:
        point = reference_point(e["type"], e["team"], e["t"], m.frames, (e["x"], e["y"]))
        if point is None:
            continue
        x, y, vx, vy = point
        limit = CONTROL_M + math.hypot(vx, vy) / FPS
        assert math.hypot(x - e["x"], y - e["y"]) <= limit, e
        checked += 1
    assert checked > 50


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_simulator_events_damaged_in_known_ways_score_as_predicted(seed7, seed):
    truth = seed7.events
    detected, log = fake_detections(truth, seed7.frames, seed=seed, per_damage=2)
    assert {entry["damage"] for entry in log} == set(DAMAGES)
    report = score(truth, detected, seed7.frames)
    for rule, per_kind in expected_counts(truth, log).items():
        for kind, expected in per_kind.items():
            assert counts(report, kind, rule) == expected, (rule, kind)


def test_undamaged_simulator_events_score_exactly_one(seed7):
    detected, log = fake_detections(seed7.events, seed7.frames, seed=1, per_damage=0)
    assert log == []
    report = score(seed7.events, detected, seed7.frames)
    for rule in ("strict", "lenient", "time_only"):
        for row in report[rule]["per_type"].values():
            assert (row["precision"], row["recall"], row["f1"]) == (1.0, 1.0, 1.0), rule


def test_fake_detections_refuse_damage_they_cannot_plant_cleanly():
    # Three passes 0.5 s apart: no damage can be planted without landing within 1 s of another
    # true pass, where it could be matched to the wrong one and the predicted score would lie.
    crowded = [ev("t1", 1.0), ev("t2", 1.5), ev("t3", 2.0)]
    with pytest.raises(ValueError, match="isolated"):
        fake_detections(crowded, frames(), seed=1, per_damage=1)


def test_a_foul_is_placed_at_the_fouled_player_not_the_one_who_fouled():
    # engine.foul: the event's team is the offender's, its spot is where the fouled player was.
    frame = {"frame": 0, "t": 0.0, "ball": {"x": 30.0, "y": 30.0, "z": 0.0},
             "players": [{"id": "h4", "team": "home", "x": 10.0, "y": 10.0},
                         {"id": "a6", "team": "away", "x": 10.5, "y": 11.4}]}
    assert reference_point("foul", "home", 0.0, [frame], (10.5, 11.4))[:2] == (10.5, 11.4)


def test_the_wilson_interval_matches_known_values():
    from ninety.eval.event_score import wilson
    assert wilson(7, 13) == [0.29, 0.77]
    assert wilson(7, 7) == [0.65, 1.0]
    assert wilson(0, 5) == [0.0, 0.43]
    assert wilson(0, 0) is None


def test_a_clip_the_broadcast_cut_is_graded_across_its_recorded_cut():
    """A rendered clip leaves out a dead ball (meta.json cuts, ninety/render/edit.py). It is graded
    on the frames it shows; a detection timed inside the cut has nowhere to be right, and a gap the
    clip does not record is still refused (lesson 99)."""
    cut = {"first_frame": 60, "last_frame": 69}
    clip = [f for f in frames(5.0) if f["frame"] >= 50 and not 60 <= f["frame"] <= 69]
    truth = [ev("t1", 3.0, x=ball_x(3.0))]
    assert counts(score(truth, [det("d1", 3.0, x=ball_x(3.0))], clip, cuts=[cut]), rule="strict") == (1, 0, 0)
    inside = score([ev("t2", 2.6, x=ball_x(2.6))], [det("d2", 2.6, x=ball_x(2.6))], clip, cuts=[cut])
    assert counts(inside, rule="time_only") == (1, 0, 0) and counts(inside, rule="lenient") == (0, 1, 1)
    with pytest.raises(ValueError, match="consecutive"):
        score(truth, [det("d1", 3.0, x=ball_x(3.0))], clip, cuts=[{"first_frame": 60, "last_frame": 68}])
    with pytest.raises(ValueError, match="consecutive"):
        score(truth, [det("d1", 3.0, x=ball_x(3.0))], clip)


def test_possession_changes_are_split_into_open_play_and_at_a_restart():
    truth = [ev("e1", 1.0, "set_piece", "away"), ev("e2", 1.0, "possession_change", "away"),
             ev("e3", 2.0, "possession_change", "home"),
             ev("e4", 3.0, "set_piece", "home"), ev("e5", 3.0, "possession_change", "away")]
    detected = [det("v1", 2.1, "possession_change", "home"), det("v2", 1.1, "possession_change", "away")]
    phase = score(truth, detected)["time_only"]["per_type"]["possession_change"]["by_phase"]
    # e5 shares a moment with a set piece of the other side: won in play, not given at a restart.
    assert phase["open_play"] == {"true": 2, "tp": 1, "fn": 1, "recall": 0.5}
    assert phase["at_restart"] == {"true": 1, "tp": 1, "fn": 0, "recall": 1.0}
    assert "by_phase" not in score(truth, detected)["time_only"]["per_type"]["set_piece"]


def test_the_engine_gives_possession_changes_at_restarts_and_in_play(seed7):
    # The split's premise on a real match (lesson 41): both kinds occur in seed 7's five minutes,
    # and every restart one shares its moment with a restart of its own side.
    phase = score(seed7.events, [])["time_only"]["per_type"]["possession_change"]["by_phase"]
    assert phase["open_play"]["true"] > 0 and phase["at_restart"]["true"] > 0
