"""The shot-flight scorer (docs/eval/highlights-plan.md): hand-computed cases, each gate at its edge,
and the answer key's flight, crossing and woodwork read from hand-made frames. Expected values are
written out, not read from the constants (lesson 190); inputs beside a threshold sit on its edge."""

import json

import pytest

from ninety.eval.shot_flight import (
    agreement,
    clip_rows,
    crossing_table,
    distance_m,
    error_table,
    flight_time_s,
    main,
    save_gate,
    score,
    true_flight,
    woodwork_hits,
    woodwork_matches,
    woodwork_table,
)
from ninety.sim.engine import FPS


def shot(id, t, x=94.0, y=34.0, kmh=80.0, outcome="on_target", source="truth"):
    e = {"id": id, "t": t, "frame": round(t * FPS), "type": "shot", "team": "home", "x": x, "y": y,
         "ball_speed_kmh": kmh, "outcome": outcome, "source": source}
    if source == "vision":
        e["confidence"] = 0.9
    return e


def still_frames(spots, seconds):
    """Frames where the ball sits at each shot's spot from its time on (a stand-in path that keeps
    the strict matcher's place check exact)."""
    out = []
    for k in range(round(seconds * FPS) + 1):
        t = k / FPS
        x, y = next(((sx, sy) for st, sx, sy in reversed(spots) if t >= st), spots[0][1:])
        out.append({"frame": k, "t": t, "ball": {"x": x, "y": y, "z": 0.0, "vx": 0.0, "vy": 0.0, "vz": 0.0},
                    "players": []})
    return out


def row(T_true, T_vision, outcome="on_target"):
    return {"truth_id": "t", "detected_id": "d", "outcome": outcome, "T_true": T_true, "T_vision": T_vision,
            "v_true": None, "v_vision": None, "d_true": None, "d_vision": None}


# Distance and flight time


def test_distance_is_to_the_centre_of_the_goal_the_shot_attacks():
    assert distance_m(94.0, 34.0) == pytest.approx(11.0)
    assert distance_m(11.0, 34.0) == pytest.approx(11.0)  # the other goal
    assert distance_m(97.0, 40.0) == pytest.approx(10.0)  # 8 along, 6 across: a 6-8-10 triangle


def test_flight_time_is_distance_over_speed_in_metres_a_second():
    assert flight_time_s(11.0, 36.0) == pytest.approx(1.1)  # 36 km/h is 10 m/s
    assert flight_time_s(25.0, 90.0) == pytest.approx(1.0)
    assert flight_time_s(11.0, None) is None
    assert flight_time_s(11.0, 0.0) is None


# Agreement and the save filter's gates


def test_a_save_on_the_dive_time_is_in_and_one_just_past_it_is_out():
    # 0.97 s exactly is in (at most); 0.98 s is out. Truth in, vision out: they disagree.
    same = agreement([row(0.97, 0.97)])
    assert (same["same_side"], same["saves"]) == (1, 1)
    split = agreement([row(0.96, 0.98)])
    assert (split["same_side"], split["saves"]) == (0, 1)
    assert split["disagreements"][0]["T_vision"] == 0.98
    # The truth on the edge (in) and vision well inside: they agree.
    assert agreement([row(0.97, 0.5)])["same_side"] == 1


def test_a_save_vision_gives_no_speed_counts_against_agreement():
    a = agreement([row(0.5, 0.5), row(0.5, None)])
    assert (a["same_side"], a["judged"], a["saves"], a["no_vision_speed"]) == (1, 1, 2, 1)
    assert a["share"] == pytest.approx(0.5)


def test_only_saves_are_judged():
    a = agreement([row(0.5, 2.0, outcome="goal"), row(0.5, 0.5)])
    assert a["saves"] == 1 and a["same_side"] == 1


def gate(n_saves, n_same, p95):
    errors = {"saves": {"all": {"T_vs_d_over_v_s": {"p95_abs": p95}}}}
    return save_gate(errors, {"saves": n_saves, "same_side": n_same,
                              "share": n_same / n_saves if n_saves else None})


def test_the_save_filter_goes_live_only_past_both_gates():
    assert gate(20, 18, 0.10)["live"]  # 90% agreement and 0.10 s: both on their edge, both pass
    assert not gate(20, 17, 0.10)["live"]  # 85%
    assert not gate(20, 18, 0.11)["live"]  # over 0.10 s
    assert not gate(20, 18, None)["live"]


def test_fewer_than_twenty_saves_are_not_judged():
    g = gate(19, 19, 0.0)
    assert not g["live"] and "not judged" in g["reason"]


# The ball's own flight in the answer key


def flying(x0=85.0, vx=20.0, y=34.0, z=1.0, seconds=2.0):
    """The ball from x0 toward the right goal line at vx m/s, at a fixed height z (its lowest point)."""
    return [{"frame": k, "t": k / FPS, "ball": {"x": x0 + vx * k / FPS, "y": y, "z": z,
                                                 "vx": vx, "vy": 0.0, "vz": 0.0}, "players": []}
            for k in range(round(seconds * FPS) + 1)]


def test_the_true_flight_ends_at_the_goal_line_with_the_ball_centre_there():
    # 20 m from x = 85 to the line at 20 m/s: 1.0 s. The frames give the ball's lowest point at
    # 1.0 m, so its centre crossed at 1.11 m.
    f = true_flight(shot("s", 0.0, x=85.0), flying(), [])
    assert f["t_s"] == pytest.approx(1.0)
    assert f["crossing"]["y"] == pytest.approx(34.0)
    assert f["crossing"]["z"] == pytest.approx(1.11)
    assert f["lifted"] is True


def touch_at(t, x):
    return {"id": "e", "t": t, "type": "deflection", "team": "away", "x": x, "y": 34.0, "source": "truth"}


def test_a_touch_before_the_line_ends_the_flight_and_there_is_no_crossing():
    f = true_flight(shot("s", 0.0, x=85.0), flying(), [touch_at(0.5, 95.0)])
    assert f["t_s"] == pytest.approx(0.5)
    assert f["crossing"] is None


def test_a_touch_just_before_the_line_ends_the_flight_inside_the_last_frame():
    # The line is reached at 1.0 s, between the frames at 0.96 and 1.0 s; a touch at 0.99 s comes first.
    f = true_flight(shot("s", 0.0, x=85.0), flying(), [touch_at(0.99, 104.8)])
    assert f["t_s"] == pytest.approx(0.99)
    assert f["crossing"] is None


def test_a_ball_at_knee_height_is_not_lifted_and_one_above_it_is():
    assert true_flight(shot("s", 0.0, x=85.0), flying(z=0.5), [])["lifted"] is False  # at 0.5 m: ground
    assert true_flight(shot("s", 0.0, x=85.0), flying(z=0.51), [])["lifted"] is True


# The woodwork in the answer key


def bounce(y, z, x=104.8, vx=20.0, back=-12.0):
    """Two frames: the ball heading at the right goal line at vx, then coming back at `back` after
    the engine's bounce, which leaves it 0.15 m in front of the line (engine.woodwork)."""
    return [{"frame": 100, "t": 4.0, "ball": {"x": x, "y": y, "z": z, "vx": vx, "vy": 0.0, "vz": 0.0}},
            {"frame": 101, "t": 4.04,
             "ball": {"x": 104.85, "y": y, "z": z, "vx": back, "vy": 0.0, "vz": 0.0}}]


def test_a_ball_coming_back_off_a_post_is_a_woodwork_hit():
    hits = woodwork_hits(bounce(y=34.0 + 3.66, z=0.3))
    assert [(h["frame"], h["what"]) for h in hits] == [(100, "post")]


def test_a_ball_coming_back_off_the_bar_is_a_woodwork_hit():
    hits = woodwork_hits(bounce(y=34.0, z=2.44 - 0.11))  # its centre on the bar
    assert [h["what"] for h in hits] == ["bar"]


def test_a_ball_turned_back_in_the_middle_of_the_goal_is_not_the_woodwork():
    assert woodwork_hits(bounce(y=34.0, z=0.3)) == []  # a keeper's save on the line


def test_a_ball_turned_back_short_of_the_line_is_not_the_woodwork():
    assert woodwork_hits(bounce(y=34.0 + 3.66, z=0.3, x=100.0)) == []  # 5 m out: a touch


def test_a_post_hit_is_found_on_the_edge_of_contact_and_not_past_it():
    # Contact is within a ball's radius plus a post's (0.11 + 0.06) of the post's centre line.
    assert woodwork_hits(bounce(y=34.0 + 3.66 + 0.17, z=0.3))
    assert woodwork_hits(bounce(y=34.0 + 3.66 + 0.18, z=0.3)) == []


def test_woodwork_hits_pair_within_three_frames_one_to_one():
    true = [{"frame": 100}, {"frame": 200}]
    assert woodwork_matches(true, [{"frame": 103}, {"frame": 204}]) == 1  # 3 frames in, 4 out
    assert woodwork_matches(true, [{"frame": 100}, {"frame": 101}]) == 1  # one true hit, used once


def test_the_woodwork_goes_live_only_with_ten_true_hits_and_ninety_percent_precision():
    assert woodwork_table(10, 10, 9)["live"]  # 90%, ten hits: both on their edge
    assert not woodwork_table(10, 10, 8)["live"]
    assert not woodwork_table(9, 9, 9)["live"]


# Goal-mouth crossings


def crossing_row(det_id, y, z):
    return {"detected_id": det_id, "crossing": {"y": y, "z": z, "t": 1.0}}


def test_crossings_within_two_metres_of_the_frame_are_measured_and_further_out_are_not():
    rows = [crossing_row("a", 34.0 + 3.66 + 2.0, 1.0), crossing_row("b", 34.0 + 3.66 + 2.01, 1.0),
            crossing_row("c", 34.0, 2.44 + 2.01)]
    vision = {"a": {"y": 39.0, "z": 1.2}, "b": {"y": 40.0, "z": 1.0}, "c": {"y": 34.0, "z": 4.0}}
    t = crossing_table(rows, vision)
    assert (t["true_crossings"], t["with_vision_crossing"]) == (1, 1)
    assert t["y_m"]["median_signed"] == pytest.approx(39.0 - 39.66)
    assert t["z_m"]["median_signed"] == pytest.approx(0.2)
    assert t["placement_labels"] is False  # 1 crossing, fewer than 20


# Whole clips


def test_a_clip_matches_shots_and_reports_each_error():
    # A true save from 11 m at 40 km/h; vision finds it at the same spot at 44 km/h and one false shot.
    truth = [shot("t1", 1.0, kmh=40.0)]
    detected = [shot("d1", 1.0, kmh=44.0, source="vision"), shot("d2", 3.0, x=80.0, source="vision")]
    frames = still_frames([(1.0, 94.0, 34.0), (3.0, 80.0, 34.0)], 4.0)
    rows, counts = clip_rows(truth, frames, detected)
    assert counts == {"true_shots": 1, "detected_shots": 2, "matched": 1, "missed": 0, "false": 1}
    r = rows[0]
    assert r["T_true"] == pytest.approx(0.99)  # 11 m at 11.11 m/s
    assert r["T_vision"] == pytest.approx(0.9)  # 11 m at 12.22 m/s
    errors = error_table(rows)
    assert errors["saves"]["all"]["v_kmh"]["median_signed"] == pytest.approx(4.0)
    # The true save is out (0.99 s) and vision puts it in (0.90 s): they disagree.
    assert agreement(rows)["same_side"] == 0


def test_a_shot_vision_places_more_than_a_metre_off_is_not_matched():
    truth = [shot("t1", 1.0)]
    detected = [shot("d1", 1.0, x=95.5, source="vision")]  # the ball is at 94: 1.5 m off
    _, counts = clip_rows(truth, still_frames([(0.0, 94.0, 34.0)], 2.0), detected)
    assert (counts["matched"], counts["missed"], counts["false"]) == (0, 1, 1)


def test_score_reports_no_crossings_or_woodwork_unless_given():
    clip = {"truth": [shot("t1", 1.0)], "frames": still_frames([(0.0, 94.0, 34.0)], 2.0),
            "detected": [shot("d1", 1.0, source="vision")]}
    report = score([clip])
    assert report["crossings"] is None and report["woodwork"] is None
    assert report["save_filter"]["live"] is False  # one save: not judged


def test_the_command_writes_a_strict_json_report(tmp_path):
    root = tmp_path / "seed1"
    root.mkdir()
    (root / "events.jsonl").write_text(json.dumps(shot("t1", 1.0)) + "\n")
    lines = (json.dumps(f) + "\n" for f in still_frames([(0.0, 94.0, 34.0)], 2.0))
    (root / "frames.jsonl").write_text("".join(lines))
    det = tmp_path / "detected.jsonl"
    det.write_text(json.dumps(shot("d1", 1.0, source="vision")) + "\n")
    main(["--clip", str(root), "--detected", str(det), "--out", str(tmp_path / "report")])
    report = json.loads((tmp_path / "report.json").read_text())
    assert report["counts"][0]["matched"] == 1
    assert report["agreement"]["saves"] == 1
