"""The shot-flight scorer (docs/eval/highlights-plan.md): hand-computed cases, each gate at its edge,
and the answer key's flight, crossing and woodwork read from hand-made frames. Expected values are
written out, not read from the constants (lesson 190); inputs beside a threshold sit on its edge."""

import json

import pytest

import ninety.eval.shot_flight as shot_flight
from ninety.eval.shot_flight import (
    agreement,
    clip_rows,
    crossing_table,
    distance_m,
    error_table,
    flight_time_s,
    main,
    percentile,
    save_gate,
    score,
    summary,
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


def crossing_row(det_id, y, z, clip="A"):
    return {"clip": clip, "detected_id": det_id, "crossing": {"y": y, "z": z, "t": 1.0}}


def test_crossings_within_two_metres_of_the_frame_are_measured_and_further_out_are_not():
    rows = [crossing_row("a", 34.0 + 3.66 + 2.0, 1.0), crossing_row("b", 34.0 + 3.66 + 2.01, 1.0),
            crossing_row("c", 34.0, 2.44 + 2.01)]
    vision = {("A", "a"): {"y": 39.0, "z": 1.2}, ("A", "b"): {"y": 40.0, "z": 1.0},
              ("A", "c"): {"y": 34.0, "z": 4.0}}
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


def test_the_same_detected_id_in_two_clips_is_two_shots():
    # Detected ids count from v1 in every clip: clip B's v1 is not clip A's.
    rows = [crossing_row("v1", 34.0, 1.0, clip="A"), crossing_row("v1", 36.0, 1.5, clip="B")]
    vision = {("A", "v1"): {"y": 34.5, "z": 1.0}, ("B", "v1"): {"y": 36.2, "z": 1.4}}
    t = crossing_table(rows, vision)
    assert t["with_vision_crossing"] == 2
    assert t["y_m"]["median_signed"] == pytest.approx(0.35)  # errors 0.5 and 0.2, not 2.5 and 1.8
    assert t["z_m"]["p95_abs"] == pytest.approx(0.0 + (0.1 - 0.0) * 0.95)  # errors 0.0 and -0.1
    # A clip with no crossing for its v1 is not given another clip's.
    t = crossing_table(rows, {("A", "v1"): {"y": 34.5, "z": 1.0}})
    assert t["with_vision_crossing"] == 1


def test_rows_name_their_clip_through_score():
    clips = [{"name": n, "truth": [shot("t1", 1.0)], "frames": still_frames([(0.0, 94.0, 34.0)], 2.0),
              "detected": [shot("v1", 1.0, source="vision")]} for n in ("A", "B")]
    report = score(clips)
    assert [r["clip"] for r in report["rows"]] == ["A", "B"]  # both detected ids are v1


# The statistic the save gate stands on


def test_a_percentile_is_interpolated_between_the_ranks():
    assert percentile([1.0, 2.0, 3.0, 4.0, 5.0], 0.95) == pytest.approx(4.8)
    assert percentile([5.0, 1.0, 3.0], 0.5) == pytest.approx(3.0)
    assert percentile([], 0.5) is None
    assert percentile([2.0], 0.95) == pytest.approx(2.0)


def test_the_summary_of_five_errors_has_the_exact_p95_median_and_bias():
    s = summary([0.01, -0.02, 0.05, -0.08, 0.11])
    assert s["n"] == 5
    assert s["median_abs"] == pytest.approx(0.05)
    assert s["p95_abs"] == pytest.approx(0.08 + (0.11 - 0.08) * 0.8)  # rank 3.8 of the sorted |errors|
    assert s["median_signed"] == pytest.approx(0.01)


def full_row(**over):
    base = {"clip": "A", "truth_id": "t", "detected_id": "d", "outcome": "on_target",
            "v_true": 80.0, "v_vision": 80.0, "d_true": 11.0, "d_vision": 11.0,
            "x_error": 0.0, "y_error": 0.0, "T_true": 0.5, "T_vision": 0.5, "T_flown": 0.5,
            "lifted": False, "crossing": None}
    return {**base, **over}


def test_the_save_gate_reads_the_p95_of_the_flight_time_errors_of_saves():
    # Twenty saves, every one on the same side of the dive time; the errors are 0.00 for nineteen
    # and 0.20 for one: rank 18.05 of 19 puts the p95 at 0.01, under the gate; two at 0.20 put it at 0.2.
    ok = [full_row(T_true=0.5, T_vision=0.5) for _ in range(19)] + [full_row(T_true=0.5, T_vision=0.7)]
    gate = save_gate(error_table(ok), agreement(ok))
    assert gate["p95_T_s"] == pytest.approx(0.2 * 0.05)
    assert gate["live"] is True
    bad = [full_row(T_true=0.5, T_vision=0.5) for _ in range(18)] + [full_row(T_true=0.5, T_vision=0.7)] * 2
    gate = save_gate(error_table(bad), agreement(bad))
    assert gate["p95_T_s"] == pytest.approx(0.2)
    assert gate["live"] is False


def test_each_error_is_read_from_its_own_field_and_ground_and_lifted_are_apart():
    rows = [full_row(x_error=1.0, y_error=0.25, lifted=False, v_vision=90.0),
            full_row(x_error=1.0, y_error=0.25, lifted=True, v_vision=70.0)]
    errors = error_table(rows)
    assert errors["all"]["all"]["x_m"]["median_signed"] == pytest.approx(1.0)
    assert errors["all"]["all"]["y_m"]["median_signed"] == pytest.approx(0.25)
    assert errors["saves"]["ground"]["v_kmh"]["median_signed"] == pytest.approx(10.0)
    assert errors["saves"]["lifted"]["v_kmh"]["median_signed"] == pytest.approx(-10.0)


def test_a_high_ball_past_a_post_is_not_a_hit_on_it():
    # Over the bar's height beside the post: neither the post (under the bar) nor the bar (between the posts).
    assert woodwork_hits(bounce(y=34.0 + 3.66 + 0.1, z=3.0)) == []


# Test seeds are scored once


def make_clip(tmp_path, name, seed=None):
    root = tmp_path / name
    root.mkdir()
    (root / "events.jsonl").write_text(json.dumps(shot("t1", 1.0)) + "\n")
    lines = (json.dumps(f) + "\n" for f in still_frames([(0.0, 94.0, 34.0)], 2.0))
    (root / "frames.jsonl").write_text("".join(lines))
    if seed is not None:
        (root / "meta.json").write_text(json.dumps({"seed": seed}))
    det = tmp_path / f"{name}.detected.jsonl"
    det.write_text(json.dumps(shot("v1", 1.0, source="vision")) + "\n")
    return root, det


@pytest.mark.parametrize("name,seed", [("seed900001", None), ("seed900030", None), ("seed910009", None),
                                       ("seed910016", None), ("clip", 900015), ("clip", 910012)])
def test_a_test_seed_is_refused_unless_it_is_the_final_look(tmp_path, name, seed):
    root, det = make_clip(tmp_path, name, seed)
    with pytest.raises(SystemExit, match="test seed"):
        main(["--clip", str(root), "--detected", str(det), "--out", str(tmp_path / "r")])
    assert not (tmp_path / "r.json").exists()
    main(["--clip", str(root), "--detected", str(det), "--out", str(tmp_path / "r"), "--final-test"])
    assert (tmp_path / "r.json").exists()


@pytest.mark.parametrize("name,seed", [("seed910001", None), ("seed910008", None), ("seed12", None),
                                       ("clip", 910004), ("seed900031", None)])
def test_a_validation_or_training_seed_is_scored_without_the_flag(tmp_path, name, seed):
    root, det = make_clip(tmp_path, name, seed)
    main(["--clip", str(root), "--detected", str(det), "--out", str(tmp_path / "r")])
    assert (tmp_path / "r.json").exists()


def test_a_clip_whose_seed_cannot_be_told_is_refused(tmp_path):
    root, det = make_clip(tmp_path, "clip")
    with pytest.raises(SystemExit, match="unknown"):
        main(["--clip", str(root), "--detected", str(det), "--out", str(tmp_path / "r")])


def test_crossings_name_their_clip_and_each_clip_reads_only_its_own(tmp_path):
    a, da = make_clip(tmp_path, "seed1")
    b, db = make_clip(tmp_path, "seed2")
    cross = tmp_path / "crossings.jsonl"
    cross.write_text(json.dumps({"shot": "v1", "y": 34.0, "z": 1.0}) + "\n")
    with pytest.raises(SystemExit, match="names its clip"):
        main(["--clip", str(a), "--detected", str(da), "--clip", str(b), "--detected", str(db),
              "--crossings", str(cross), "--out", str(tmp_path / "r")])
    cross.write_text(json.dumps({"clip": "seed1", "shot": "v1", "y": 34.0, "z": 1.0}) + "\n")
    main(["--clip", str(a), "--detected", str(da), "--clip", str(b), "--detected", str(db),
          "--crossings", str(cross), "--out", str(tmp_path / "r")])


@pytest.mark.parametrize("name,seed", [("seed910001", 900001), ("seed910001", "900001"),
                                       ("seed910001", 900001.0), ("seed12", 910012)])
def test_meta_jsons_seed_beats_the_folders_name(tmp_path, name, seed):
    root, det = make_clip(tmp_path, name, seed)
    with pytest.raises(SystemExit, match="test seed"):
        main(["--clip", str(root), "--detected", str(det), "--out", str(tmp_path / "r")])


def test_a_folder_named_for_a_test_seed_is_scored_when_meta_jsons_seed_is_a_validation_one(tmp_path):
    root, det = make_clip(tmp_path, "seed900001", 910001)
    main(["--clip", str(root), "--detected", str(det), "--out", str(tmp_path / "r")])
    assert (tmp_path / "r.json").exists()


@pytest.mark.parametrize("seed", [None, "n/a", True, 12.5])
def test_a_seed_meta_json_cannot_give_is_unknown_not_the_names(tmp_path, seed):
    root, det = make_clip(tmp_path, "seed910001", seed)
    (root / "meta.json").write_text(json.dumps({"seed": seed}))
    with pytest.raises(SystemExit, match="unknown"):
        main(["--clip", str(root), "--detected", str(det), "--out", str(tmp_path / "r")])


def test_each_clip_is_given_only_its_own_crossings(tmp_path, monkeypatch):
    a, da = make_clip(tmp_path, "seed1")
    b, db = make_clip(tmp_path, "seed2")
    cross = tmp_path / "crossings.jsonl"
    cross.write_text(json.dumps({"clip": "seed1", "shot": "v1", "y": 34.0, "z": 1.0}) + "\n"
                     + json.dumps({"clip": "seed2", "shot": "v1", "y": 36.0, "z": 1.5}) + "\n"
                     + json.dumps({"clip": "seed2", "shot": "v2", "y": 35.0, "z": 0.5}) + "\n")
    seen = {}

    def spy(clips):
        seen.update({c["name"]: c["crossings"] for c in clips})
        return {"counts": [], "agreement": {"saves": 0, "same_side": 0, "share": None}, "save_filter": None}

    monkeypatch.setattr(shot_flight, "score", spy)
    main(["--clip", str(a), "--detected", str(da), "--clip", str(b), "--detected", str(db),
          "--crossings", str(cross), "--out", str(tmp_path / "r")])
    assert seen == {"seed1": {"v1": {"clip": "seed1", "shot": "v1", "y": 34.0, "z": 1.0}},
                    "seed2": {"v1": {"clip": "seed2", "shot": "v1", "y": 36.0, "z": 1.5},
                              "v2": {"clip": "seed2", "shot": "v2", "y": 35.0, "z": 0.5}}}


@pytest.mark.parametrize("body", [[], [{"seed": 900001}], "seed", 5, None])
def test_a_meta_json_that_is_not_an_object_leaves_the_seed_unknown(tmp_path, body):
    root, det = make_clip(tmp_path, "seed910001")
    (root / "meta.json").write_text(json.dumps(body))
    with pytest.raises(SystemExit, match="unknown"):
        main(["--clip", str(root), "--detected", str(det), "--out", str(tmp_path / "r")])
