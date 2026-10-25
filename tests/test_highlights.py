"""The highlights reel (ninety/highlights.py, docs/eval/highlights-plan.md): which goals and saves
make it and the label each gets, on hand-made detected events. Expected values are written out, not
read from the constants (lesson 190); inputs beside a threshold sit a centimetre or a tenth of a unit
either side of its margin, never exactly on it, where float rounding decides."""

from __future__ import annotations

from ninety import condensed
from ninety.highlights import Verdict, distance_m, flight_time_s, label, reel, verdict_from_report

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
