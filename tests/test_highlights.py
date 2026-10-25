"""The highlights reel (ninety/highlights.py, docs/eval/highlights-plan.md): which goals and saves
make it and the label each gets, on hand-made detected events. Expected values are written out, not
read from the constants (lesson 190); inputs beside a threshold sit a centimetre or a tenth of a unit
either side of its margin, never exactly on it, where float rounding decides."""

from __future__ import annotations

import json

import pytest

from ninety import condensed, highlights
from ninety.highlights import (
    Verdict,
    distance_m,
    flight_time_s,
    label,
    origin,
    record,
    reel,
    verdict_from_report,
)
from ninety.match.timeline import Timeline

# A measured verdict: the filter live, small errors (1 km/h, 0.5 m, 0.2 m along and across, 0.02 s).
MEASURED = Verdict(save_filter=True, margins={"v_kmh": 1.0, "d_m": 0.5, "x_m": 0.2, "y_m": 0.2, "T_s": 0.02})


def shot(eid, t, outcome, x=94.0, y=34.0, kmh=80.0, team="home", confidence=0.9):
    return {"id": eid, "t": t, "frame": round(t * 25), "type": "shot", "team": team, "x": x, "y": y,
            "player": None, "outcome": outcome, "ball_speed_kmh": kmh, "source": "vision",
            "confidence": confidence}


def moments(events, verdict=MEASURED):
    return {m["event"]: m for m in reel(events, verdict)["moments"]}


# Which moments are in


def test_every_goal_is_in_and_misses_and_blocks_are_not():
    events = [shot("g", 10.0, "goal", x=70.0, kmh=40.0),  # a slow goal from 35 m: still in
              shot("m", 20.0, "off_target"), shot("b", 30.0, "blocked")]
    assert list(moments(events)) == ["g"]


def test_a_save_on_the_dive_time_is_in_and_one_just_slower_is_left_out():
    # From 11 m, 0.97 s is 40.82 km/h: at 40.9 km/h it takes 0.968 s, at 40.7 km/h 0.973 s.
    r = reel([shot("in", 10.0, "on_target", kmh=40.9), shot("out", 20.0, "on_target", kmh=40.7)], MEASURED)
    assert [m["event"] for m in r["moments"]] == ["in"]
    assert r["moments"][0]["why"] == "beat_the_dive"
    assert r["saves_left_out"] == 1


def test_a_save_with_no_speed_is_left_out_by_the_filter():
    r = reel([shot("s", 10.0, "on_target", kmh=None)], MEASURED)
    assert r["moments"] == [] and r["saves_left_out"] == 1


def test_until_the_filter_passes_every_save_is_in_and_listed_fastest_first():
    events = [shot("slow", 10.0, "on_target", kmh=30.0), shot("fast", 20.0, "on_target", kmh=110.0),
              shot("none", 30.0, "on_target", kmh=None), shot("g", 40.0, "goal")]
    r = reel(events)  # no verdict: nothing measured
    assert [m["event"] for m in r["moments"]] == ["slow", "fast", "none", "g"]  # in match time
    assert {m["why"] for m in r["moments"] if m["kind"] == "save"} == {"filter_off"}
    assert r["saves_by_pace"] == ["fast", "slow", "none"]
    assert (r["save_filter"], r["labels"], r["saves_left_out"]) == (False, False, 0)


def test_each_moment_carries_its_numbers_and_its_clip():
    # 8 m along and 6 across: 10 m. 36 km/h is 10 m/s, so 1.0 s.
    g = moments([shot("g", 10.0, "goal", x=97.0, y=40.0, kmh=36.0)])["g"]
    assert (g["d_m"], g["v_kmh"], g["T_s"]) == (10.0, 36.0, 1.0)
    assert g["clip"] == [2.0, 13.0]  # 8 s before, 3 s after
    assert moments([shot("e", 5.0, "goal")])["e"]["clip"] == [0.0, 8.0]  # not before kick-off


# Labels


def tag(kind, x=94.0, y=34.0, kmh=80.0, verdict=MEASURED):
    d = distance_m(x, y)
    T = d / (kmh / 3.6) if kmh else None
    out = label(kind, x, y, d, kmh, T, verdict)
    return out[0] if out else None


def test_no_label_until_the_errors_are_measured():
    assert tag("goal", x=70.0, kmh=130.0, verdict=Verdict()) is None
    assert reel([shot("g", 1.0, "goal", x=70.0, kmh=130.0)])["moments"][0]["label"] == "GOAL"


def test_a_rocket_clears_100_kmh_by_more_than_the_speed_error():
    assert tag("save", kmh=101.1) == "ROCKET"  # past 100 + 1 km/h
    assert tag("save", kmh=101.0) is None  # on the margin: not sure
    assert tag("goal", kmh=101.1) == "ROCKET"


def test_a_screamer_is_a_goal_outside_the_area_from_25_m():
    assert tag("goal", x=105 - 25.6) == "SCREAMER"  # past 25 + 0.5 m, straight on
    assert tag("goal", x=105 - 25.49) is None  # within the distance margin
    assert tag("goal", x=105 - 24.4) == "LONG-RANGE"  # outside the area, under 25 - 0.5 m
    assert tag("goal", x=105 - 24.51) is None  # within the margin the other side
    assert tag("save", x=105 - 30.0) is None  # a save is never a screamer


def test_long_range_needs_the_shot_surely_outside_the_area():
    assert tag("goal", x=105 - 16.8) == "LONG-RANGE"  # past 16.5 + 0.2 m deep
    assert tag("goal", x=105 - 16.69) is None  # within the position margin of the edge
    # 10 m out but wide of the area: 20.16 + 0.2 m from the centre line is its edge and margin.
    assert tag("goal", x=95.0, y=34.0 + 20.46) == "LONG-RANGE"
    assert tag("goal", x=95.0, y=34.0 + 20.35) is None


def test_a_thunderbolt_is_a_screamer_that_is_also_a_rocket():
    assert tag("goal", x=105 - 26.0, kmh=101.1) == "THUNDERBOLT"
    assert tag("goal", x=105 - 26.0, kmh=101.0) == "SCREAMER"


def test_a_reflex_save_beats_a_footballers_reaction():
    # From 6 m, under 0.41 - 0.02 s needs more than 55.38 km/h: 56 km/h takes 0.386 s, 55 km/h 0.393 s.
    assert tag("save", x=105 - 6.0, kmh=56.0) == "REFLEX SAVE"
    assert tag("save", x=105 - 6.0, kmh=55.0) is None
    assert tag("goal", x=105 - 6.0, kmh=56.0) is None  # only a save


def test_a_tap_in_is_a_goal_from_inside_the_six_yard_box():
    assert tag("goal", x=105 - 5.2) == "TAP-IN"  # under 5.5 - 0.2 m deep
    assert tag("goal", x=105 - 5.31) is None
    assert tag("goal", x=105 - 3.0, y=34.0 + 8.9) == "TAP-IN"  # under 9.16 - 0.2 m across
    assert tag("goal", x=105 - 3.0, y=34.0 + 8.97) is None
    assert tag("save", x=105 - 5.2, kmh=None) is None  # only a goal (no speed, so no reflex save)


def test_the_first_label_that_applies_wins():
    assert tag("goal", x=105 - 5.0, kmh=101.1) == "ROCKET"  # a rocket from inside the six-yard box
    assert tag("save", x=105 - 6.0, kmh=101.1) == "ROCKET"  # also a reflex save; rocket comes first


def test_the_left_goal_is_judged_the_same_way():
    assert tag("goal", x=25.6) == "SCREAMER"
    assert tag("goal", x=5.2) == "TAP-IN"


def test_a_label_keeps_the_number_that_earned_it():
    m = moments([shot("r", 10.0, "goal", kmh=112.4)])["r"]
    assert (m["label"], m["label_detail"]) == ("ROCKET", "112 km/h")


def test_the_verdict_is_read_from_the_scorers_report():
    p95 = {"v_kmh": 3.0, "d_m": 1.0, "x_m": 0.5, "y_m": 0.4, "T_vs_d_over_v_s": 0.05}
    report = {"save_filter": {"live": True},
              "errors": {"all": {"all": {k: {"p95_abs": v} for k, v in p95.items()}}}}
    v = verdict_from_report(report)
    assert v.save_filter is True
    assert v.margins == {"v_kmh": 3.0, "d_m": 1.0, "x_m": 0.5, "y_m": 0.4, "T_s": 0.05}
    report["save_filter"]["live"] = False  # a failed gate keeps the filter off
    assert verdict_from_report(report).save_filter is False
    report["errors"]["all"]["all"]["v_kmh"] = None  # not measured: no speed label
    assert verdict_from_report(report).margin("v_kmh") is None


# In match.json


def test_match_json_carries_the_reel_of_confident_events_only():
    meta = {"fps": 25, "t_start": 0.0, "frames": 1500, "segments": [{"index": 0, "frame": 0, "frames": 1500}]}
    events = [shot("g", 10.0, "goal"), shot("unsure", 20.0, "goal", confidence=0.3)]
    body = condensed.build(meta, events)
    assert [m["event"] for m in body["highlights"]["moments"]] == ["g"]
    assert body["highlights"]["save_filter"] is False


def test_only_a_goal_is_a_thunderbolt_a_screamer_or_long_range():
    # The same strike from 26 m outside the area at 101.1 km/h, saved: a rocket, and no goal word.
    assert tag("save", x=105 - 26.0, kmh=101.1) == "ROCKET"
    assert tag("save", x=105 - 26.0, kmh=80.0) is None
    assert tag("save", x=105 - 20.0, kmh=80.0) is None  # long-range is a goal's word


def test_a_flight_time_needs_a_positive_speed():
    assert flight_time_s(10.0, 36.0) == 1.0  # 10 m at 10 m/s
    assert flight_time_s(10.0, 0.0) is None
    assert flight_time_s(10.0, -36.0) is None
    assert flight_time_s(10.0, None) is None


# Recording each moment from the footage (highlights.record)


def images_in(folder, n):
    """n clip images, each its own bytes, so a still can be told apart."""
    folder.mkdir(parents=True)
    paths = []
    for i in range(n):
        p = folder / f"{i:05d}.jpg"
        p.write_bytes(f"image {i}".encode())
        paths.append(p)
    return paths


def moment(eid, t, clip):
    return {"event": eid, "t": t, "clip": clip}


# 50 images: match 60.0 to 61.56 s (images 0 to 39), a cut, then 62.0 to 62.36 s (images 40 to 49).
CUT = Timeline([{"index": 0, "frame": 1500, "frames": 40}, {"index": 40, "frame": 1550, "frames": 10}], 25)


def test_a_moment_is_recorded_as_a_still_at_the_strike_and_its_images(tmp_path):
    images = images_in(tmp_path / "images", 50)
    reel = {"moments": [moment("v2", 61.0, [60.4, 61.4])]}
    record(reel, CUT, images, tmp_path / "out", encode=False)
    rec = reel["moments"][0]["recording"]
    # 60.4 s is image 10, 61.4 s image 35 (end exclusive), the strike at 61.0 s image 25.
    assert rec == {"images": [10, 35], "video_t": [0.4, 1.4], "shot_image": 25,
                   "poster": "highlights/v2.jpg", "clip": None}
    assert (tmp_path / "out" / "highlights" / "v2.jpg").read_bytes() == b"image 25"


def test_a_window_across_a_cut_runs_on_into_the_next_segment(tmp_path):
    images = images_in(tmp_path / "images", 50)
    reel = {"moments": [moment("v5", 62.2, [61.0, 62.3])]}
    record(reel, CUT, images, tmp_path / "out", encode=False)
    rec = reel["moments"][0]["recording"]
    assert rec["images"] == [25, 48]  # 62.3 s is image 40 + 7.5: up to 48, exclusive
    assert rec["shot_image"] == 45


def test_a_window_past_the_footage_is_cut_to_it_and_one_outside_it_is_not_recorded(tmp_path):
    images = images_in(tmp_path / "images", 50)
    reel = {"moments": [moment("a", 61.0, [53.0, 64.0]), moment("b", 70.0, [62.5, 73.0])]}
    record(reel, CUT, images, tmp_path / "out", encode=False)
    assert reel["moments"][0]["recording"]["images"] == [0, 50]
    assert reel["moments"][1]["recording"] is None  # it starts after the last image
    assert not (tmp_path / "out" / "highlights" / "b.jpg").exists()


def test_a_file_name_keeps_letters_digits_dashes_and_underscores_only(tmp_path):
    images = images_in(tmp_path / "images", 50)
    reel = {"moments": [moment("../e 7", 61.0, [60.4, 61.4])]}
    record(reel, CUT, images, tmp_path / "out", encode=False)
    assert reel["moments"][0]["recording"]["poster"] == "highlights/___e_7.jpg"


def test_with_ffmpeg_the_window_is_encoded_as_vp9(tmp_path, monkeypatch):
    images = images_in(tmp_path / "images", 50)
    calls = []
    monkeypatch.setattr(highlights.shutil, "which", lambda name: "/usr/bin/ffmpeg")
    monkeypatch.setattr(highlights.subprocess, "run", lambda cmd, check: calls.append(cmd))
    reel = {"moments": [moment("v2", 61.0, [60.4, 61.4])]}
    record(reel, CUT, images, tmp_path / "out", encode=True)
    assert reel["moments"][0]["recording"]["clip"] == "highlights/v2.webm"
    (cmd,) = calls
    assert cmd[cmd.index("-start_number") + 1] == "10" and cmd[cmd.index("-frames:v") + 1] == "25"
    assert cmd[cmd.index("-framerate") + 1] == "25"
    assert cmd[cmd.index("-c:v") + 1] == "libvpx-vp9" and "libx264" not in cmd
    assert cmd[-1] == str(tmp_path / "out" / "highlights" / "v2.webm")


def test_without_ffmpeg_or_when_shipping_frames_no_clip_is_encoded(tmp_path, monkeypatch):
    images = images_in(tmp_path / "images", 50)
    monkeypatch.setattr(highlights.subprocess, "run", lambda *a, **k: pytest.fail("encoded"))
    monkeypatch.setattr(highlights.shutil, "which", lambda name: None)
    reel = {"moments": [moment("v2", 61.0, [60.4, 61.4])]}
    record(reel, CUT, images, tmp_path / "out", encode=True)
    assert reel["moments"][0]["recording"]["clip"] is None


def test_the_bundle_records_every_highlight_and_matches_the_schema(tmp_path):
    from ninety import e2e
    from ninety.agents.contracts import schema_validator
    from tests.e2e_clip import write_clip

    clip, detections, events = write_clip(tmp_path)
    e2e.main([str(clip), "--out", str(tmp_path / "bundle"), "--detections", str(detections), "--frames",
              "--events-file", str(events), "--match"])
    reel = json.loads((tmp_path / "bundle" / "match.json").read_text())["highlights"]
    schema_validator("highlight_reel").validate(reel)
    (save,) = reel["moments"]  # e2_clip.py's one shot, a save at 61.2 s, while the filter is off
    assert save["recording"]["images"] == [0, 75]  # its 11 s window is wider than the 3 s clip
    assert (tmp_path / "bundle" / save["recording"]["poster"]).exists()
    assert save["recording"]["clip"] is None  # --frames: the bundle ships frames, so no clip


def test_shipping_frames_encodes_no_clip_even_with_ffmpeg(tmp_path, monkeypatch):
    images = images_in(tmp_path / "images", 50)
    monkeypatch.setattr(highlights.shutil, "which", lambda name: "/usr/bin/ffmpeg")
    monkeypatch.setattr(highlights.subprocess, "run", lambda *a, **k: pytest.fail("encoded"))
    reel = {"moments": [moment("v2", 61.0, [60.4, 61.4])]}
    record(reel, CUT, images, tmp_path / "out", encode=False)
    assert reel["moments"][0]["recording"]["clip"] is None


def test_the_video_times_are_the_whole_images_recorded(tmp_path):
    images = images_in(tmp_path / "images", 50)
    reel = {"moments": [moment("v2", 61.0, [60.41, 61.41])]}  # starts a quarter into image 10
    record(reel, CUT, images, tmp_path / "out", encode=False)
    rec = reel["moments"][0]["recording"]
    assert rec["images"] == [10, 36] and rec["video_t"] == [0.4, 1.44]


# How the attack started (highlights.origin, the plan's Amendment 2)


def ev(eid, t, kind, team="home", x=80.0, y=34.0, outcome=None):
    return {"id": eid, "t": t, "type": kind, "team": team, "x": x, "y": y, "outcome": outcome,
            "source": "vision", "confidence": 0.9}


SHOT = ev("s", 20.0, "shot", x=94.0, outcome="goal")  # home attacks the goal line at x = 105


def started(*before, shot=SHOT, cut=None):
    return origin(shot, [*before, shot], cut or (lambda t0, t1: False))


def test_the_ball_won_back_from_an_opponents_failed_pass_is_open_play():
    assert started(ev("p", 10.0, "pass", "away", outcome="fail"),
                   ev("q", 15.0, "pass", outcome="success")) == "open_play"


def test_a_ball_out_over_a_touchline_is_a_throw_in_for_the_side_that_did_not_touch_it_last():
    assert started(ev("o", 10.0, "out_of_play", "away", x=60.0, y=-0.3)) == "throw_in"
    assert started(ev("o", 10.0, "out_of_play", "away", x=60.0, y=68.3)) == "throw_in"
    assert started(ev("o", 10.0, "out_of_play", "home", x=60.0, y=-0.3)) is None  # away's throw


def test_over_the_line_attacked_off_a_defender_is_a_corner_and_off_an_attacker_a_goal_kick():
    assert started(ev("o", 10.0, "out_of_play", "away", x=105.3, y=20.0)) == "corner"
    assert started(ev("o", 10.0, "out_of_play", "home", x=105.3, y=20.0)) is None  # away's goal kick
    assert started(ev("o", 10.0, "out_of_play", "away", x=-0.3, y=20.0)) == "goal_kick"  # home's own line
    assert started(ev("o", 10.0, "out_of_play", "home", x=-0.3, y=20.0)) is None  # away's corner


def test_at_a_corner_flag_the_line_it_is_further_over_decides():
    assert started(ev("o", 10.0, "out_of_play", "away", x=105.2, y=-0.5)) == "throw_in"
    assert started(ev("o", 10.0, "out_of_play", "away", x=105.5, y=-0.2)) == "corner"
    assert started(ev("o", 10.0, "out_of_play", "away", x=105.25, y=-0.25)) == "throw_in"  # level: touchline


def test_a_side_attacking_the_other_way_takes_its_corner_at_the_other_end():
    shot = ev("s", 20.0, "shot", x=11.0, outcome="on_target")  # attacks x = 0
    assert started(ev("o", 10.0, "out_of_play", "away", x=-0.3, y=20.0), shot=shot) == "corner"
    assert started(ev("o", 10.0, "out_of_play", "away", x=105.3, y=20.0), shot=shot) == "goal_kick"


def test_a_goal_by_the_other_side_gives_the_kick_off():
    assert started(ev("g", 5.0, "shot", "away", x=10.0, outcome="goal"),
                   ev("p", 15.0, "pass", outcome="success")) == "kick_off"
    assert started(ev("g", 5.0, "goal", "away", x=10.0)) == "kick_off"
    assert started(ev("g", 5.0, "shot", "home", x=94.0, outcome="goal")) is None  # its own: away kicks off


def test_a_ball_out_straight_after_a_goal_is_that_goal():
    assert started(ev("g", 5.0, "shot", "away", x=10.0, outcome="goal"),
                   ev("o", 5.5, "out_of_play", "away", x=-0.3, y=34.0)) == "kick_off"


def test_a_start_not_seen_gives_no_origin():
    assert started() is None  # nothing before it
    assert started(ev("p", 10.0, "pass", "away", outcome="success")) is None  # theirs, then ours unseen
    assert started(ev("p", 10.0, "pass", outcome="fail")) is None  # we lost it: how we won it is unseen
    assert started(ev("o", 5.0, "out_of_play", "away", x=105.3, y=20.0),
                   ev("p", 10.0, "pass", outcome="fail")) is None  # the corner's possession ended there
    assert started(ev("x", 10.0, "shot", "away", x=10.0, outcome="on_target")) is None


def test_the_possession_runs_on_through_passes_and_a_rebound():
    assert started(ev("o", 5.0, "out_of_play", "away", x=105.3, y=20.0),
                   ev("p", 8.0, "pass", outcome="success"),
                   ev("r", 12.0, "shot", x=96.0, outcome="on_target")) == "corner"


def test_nothing_before_a_cut_is_read_but_a_restart_after_it_is():
    cut_at_9 = lambda t0, t1: t0 < 9.0 <= t1  # noqa: E731
    assert started(ev("p", 5.0, "pass", "away", outcome="fail"), ev("q", 12.0, "pass", outcome="success"),
                   cut=cut_at_9) is None
    out = ev("o", 5.0, "out_of_play", "away", x=105.3, y=20.0)
    # A ball out before the cut says nothing: a condensed match's cut can skip a foul and minutes.
    assert started(out, ev("q", 12.0, "pass", outcome="success"), cut=cut_at_9) is None
    # The restart the detector saw after the cut is read.
    assert started(out, restart_ev("r", 10.0, "corner"), ev("q", 12.0, "pass", outcome="success"),
                   cut=cut_at_9) == "corner"

def test_the_reel_gives_each_moment_its_origin_and_match_json_knows_the_cuts():
    meta = {"fps": 25, "t_start": 0.0, "frames": 750,
            "segments": [{"index": 0, "frame": 0, "frames": 250},
                         {"index": 250, "frame": 500, "frames": 500}]}
    events = [ev("p", 5.0, "pass", "away", outcome="fail"), ev("s", 21.0, "shot", x=94.0, outcome="goal")]
    body = condensed.build(meta, events)  # a cut from 10 s to 20 s, between the pass and the shot
    assert body["highlights"]["moments"][0]["origin"] is None
    assert reel(events)["moments"][0]["origin"] == "open_play"  # the same with no cut
    cut = condensed.cut_between(Timeline.of_clip(meta))
    assert cut(5.0, 21.0) and not cut(1.0, 9.0) and not cut(20.0, 29.0)


# Restarts the detector saw (ninety/vision/restarts.py: kickoff, and set_piece with its `restart`)


def restart_ev(eid, t, kind, team="home"):
    if kind == "kick_off":
        return ev(eid, t, "kickoff", team, x=52.5, y=34.0)
    return {**ev(eid, t, "set_piece", team), "restart": kind}


@pytest.mark.parametrize("kind", ["corner", "throw_in", "goal_kick", "free_kick", "penalty_kick"])
def test_a_detected_restart_the_side_took_is_the_origin(kind):
    assert started(restart_ev("r", 10.0, kind), ev("p", 12.0, "pass", outcome="success")) == kind
    assert started(restart_ev("r", 10.0, kind, team="away")) is None  # theirs: our start unseen


def test_a_detected_kick_off_starts_a_half_or_follows_a_goal():
    assert started(restart_ev("k", 0.0, "kick_off"), ev("p", 4.0, "pass", outcome="success")) == "kick_off"
    assert started(restart_ev("k", 0.0, "kick_off", team="away")) is None


def test_a_restart_struck_as_the_shot_is_found_within_a_frame():
    # A direct free kick or a penalty: the restart and the shot are one strike, timed a frame apart.
    assert started(restart_ev("r", 20.04, "penalty_kick")) == "penalty_kick"
    assert started(restart_ev("r", 20.0, "free_kick")) == "free_kick"
    assert started(restart_ev("r", 20.08, "free_kick")) is None  # two frames later: after the shot


def test_the_detected_restart_wins_over_the_inference_from_the_ball_out():
    out = ev("o", 5.0, "out_of_play", "away", x=105.3, y=20.0)  # inferred: a corner
    assert started(out, restart_ev("r", 9.0, "goal_kick")) == "goal_kick"  # but the video saw a goal kick
    assert started(out) == "corner"  # no restart seen: the inference


def test_a_set_piece_with_no_kind_gives_no_origin():
    assert started({**ev("r", 10.0, "set_piece"), "restart": None}) is None
    assert started(ev("r", 10.0, "set_piece")) is None  # the answer key's set_piece carries no kind
    assert started({**ev("r", 10.0, "set_piece"), "restart": "drop_ball"}) is None  # not a kind we know


def test_a_shot_straight_from_the_kick_off_is_found_at_the_same_instant():
    assert started(restart_ev("z", 20.0, "kick_off")) == "kick_off"  # timed with the strike itself



# The rest of the answer key's events (and main's possession changes on the live path)


def test_presses_and_touches_change_nobodys_possession():
    assert started(ev("p", 5.0, "pass", "away", outcome="fail"), ev("x", 6.0, "pressure", "away"),
                   ev("d", 7.0, "deflection", "away")) == "open_play"


def test_a_change_of_possession_to_the_side_is_open_play_unless_a_stoppage_came_just_before():
    assert started(ev("c", 10.0, "possession_change")) == "open_play"
    assert started(ev("c", 10.0, "possession_change", "away")) is None
    out = ev("o", 5.0, "out_of_play", "away", x=60.0, y=-0.3)  # then home's throw-in
    assert started(out, ev("c", 10.0, "possession_change")) == "throw_in"


def test_the_side_winning_the_ball_is_open_play():
    assert started(ev("i", 10.0, "interception")) == "open_play"
    assert started(ev("k", 10.0, "tackle", outcome="success")) == "open_play"
    assert started(ev("k", 10.0, "tackle", outcome="fail")) is None
    assert started(ev("i", 10.0, "interception", "away")) is None


def test_a_set_piece_of_no_kind_is_read_from_the_stoppage_before_it():
    sp = ev("s1", 12.0, "set_piece")  # the answer key's: no kind
    assert started(ev("f", 8.0, "foul", "away", x=70.0, y=34.0), sp) == "free_kick"
    assert started(ev("f", 8.0, "foul", "away", x=95.0, y=34.0), sp) == "penalty_kick"  # in the area
    assert started(ev("f", 8.0, "foul", "away", x=88.4, y=34.0), sp) == "free_kick"  # 16.6 m: outside
    assert started(ev("f", 8.0, "offside", "away", x=95.0, y=34.0), sp) == "free_kick"  # indirect
    assert started(ev("f", 8.0, "foul", x=70.0, y=34.0), sp) is None  # its own foul: theirs
    assert started(ev("o", 5.0, "out_of_play", "away", x=105.3, y=20.0), sp) == "corner"
    assert started(sp) is None  # nothing seen stopped play
    assert started(ev("f", 8.0, "foul", "away", x=70.0, y=34.0), {**sp, "team": "away"}) is None


def test_a_foul_with_no_free_kick_after_it_was_play_on():
    assert started(ev("f", 8.0, "foul", "away", x=70.0, y=34.0),
                   ev("p", 9.0, "pass", outcome="success")) is None


def test_a_set_piece_of_no_kind_needs_the_stoppage_right_before_it():
    foul = ev("f", 8.0, "foul", "away", x=70.0, y=34.0)
    sp = ev("s1", 12.0, "set_piece")
    assert started(foul, ev("p", 10.0, "pass", outcome="success"), sp) is None  # play went on between
    assert started(foul, ev("s0", 10.0, "set_piece"), sp) is None  # two set pieces: which, unseen
    assert started(ev("f", 8.0, "foul", "away", x=95.0, y=34.0 + 21.0), sp) == "free_kick"  # wide of the area
