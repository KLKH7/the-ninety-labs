"""The ball from three cameras (ninety/vision/ball_fuse.py): the broadcast's ball when its camera is
trusted and it has one; the tactical views' otherwise; the two merged only within the gate."""

from __future__ import annotations

import math

from ninety.vision import track
from ninety.vision.ball_fuse import BROADCAST, Precision, broadcast_ball, fuse_ball, gate_m, tactical_only

BP, TP = Precision(p99_m=3.0, rms_m=1.0), Precision(p99_m=4.0, rms_m=2.0)  # gate 5.0 m
GATE = gate_m(BP, TP)


def ball(x, y, score=0.9, **kw):
    return {"bbox": [100, 100, 104, 104], "score": score, "x": x, "y": y, **kw}


def tac(frame=0, balls=(), ok=True):
    return {"frame": frame, "t": frame / 25, "camera": {"ok": ok},
            "players": [{"bbox": [0, 0, 10, 30], "score": 0.9, "x": 30.0, "y": 30.0, "view": "tac-l"}],
            "ball": [b | {"view": "tac-l", "views": ["tac-l"]} for b in balls]}


def bro(frame=0, balls=(), ok=True):
    return {"frame": frame, "t": frame / 25, "camera": {"ok": ok}, "players": [], "ball": list(balls)}


def one(t, b):
    return fuse_ball([t], [b] if b is not None else [], BP, TP)[0]


def test_the_gate_is_the_two_99th_percentiles_side_by_side():
    assert GATE == 5.0


def test_a_broadcast_ball_is_taken_and_a_tactical_ball_inside_the_gate_merges_into_it():
    out = one(tac(balls=[ball(50.0, 30.0, 0.6)]), bro(balls=[ball(54.0, 30.0)]))
    assert len(out["ball"]) == 1 and out["camera"]["ball_from"] == BROADCAST
    b = out["ball"][0]
    # Weights 1/1 and 1/4: four fifths of the way to the broadcast's place.
    assert b["source"] == BROADCAST and b["view"] == BROADCAST and math.isclose(b["x"], 53.2)
    assert b["merged"] == ["tac-l"] and b["score"] == 0.9


def test_a_tactical_ball_just_outside_the_gate_is_dropped_not_merged():
    out = one(tac(balls=[ball(50.0, 30.0)]), bro(balls=[ball(50.0 + GATE + 0.01, 30.0)]))
    assert [(b["source"], b["x"], "merged" in b) for b in out["ball"]] == [(BROADCAST, 55.01, False)]


def test_a_tactical_ball_just_inside_the_gate_merges():
    out = one(tac(balls=[ball(50.0, 30.0)]), bro(balls=[ball(50.0 + GATE - 0.01, 30.0)]))
    assert "merged" in out["ball"][0]


def test_when_the_broadcast_camera_is_not_trusted_the_tactical_ball_stands():
    out = one(tac(balls=[ball(50.0, 30.0)]), bro(balls=[ball(54.0, 30.0)], ok=False))
    assert [b["source"] for b in out["ball"]] == ["tactical"] and out["ball"][0]["x"] == 50.0
    assert out["camera"]["ball_from"] == "tactical" and not out["camera"]["broadcast_ok"]


def test_when_the_broadcast_has_no_confident_ball_the_tactical_ball_stands():
    out = one(tac(balls=[ball(50.0, 30.0)]), bro(balls=[ball(54.0, 30.0, score=0.4)]))
    assert [b["source"] for b in out["ball"]] == ["tactical"]
    out = one(tac(balls=[ball(50.0, 30.0)]), bro(balls=[ball(None, None)]))  # not placed
    assert [b["source"] for b in out["ball"]] == ["tactical"]


def test_a_frame_the_broadcast_did_not_run_is_left_to_the_tactical_views():
    out = one(tac(balls=[ball(50.0, 30.0)]), None)
    assert out["ball"][0]["source"] == "tactical"


def test_players_always_come_from_the_tactical_views():
    out = one(tac(balls=[]), bro(balls=[ball(54.0, 30.0)]) | {"players": [{"x": 1.0}]})
    assert out["players"] == tac()["players"]


def test_a_broadcast_ball_on_a_frame_whose_tactical_fit_failed_is_still_used_for_the_ball():
    out = one(tac(balls=[], ok=False), bro(balls=[ball(54.0, 30.0)]))
    assert out["camera"]["ok"] and out["ball"][0]["source"] == BROADCAST
    path = track.ball_path([out])
    assert [(p.x, p.y) for p in path] == [(54.0, 30.0)]


def test_two_tactical_balls_merge_one_to_one_with_the_nearest_broadcast_ball():
    out = one(tac(balls=[ball(50.0, 30.0), ball(52.0, 30.0)]), bro(balls=[ball(53.0, 30.0)]))
    assert len(out["ball"]) == 1 and math.isclose(out["ball"][0]["x"], (53.0 * 1 + 52.0 * 0.25) / 1.25)


def test_the_single_source_variants_take_only_their_own_ball():
    t, b = [tac(balls=[ball(50.0, 30.0)])], [bro(balls=[ball(54.0, 30.0)])]
    assert [x["source"] for x in tactical_only(t)[0]["ball"]] == ["tactical"]
    assert [(x["source"], x["x"]) for x in broadcast_ball(t, b)[0]["ball"]] == [(BROADCAST, 54.0)]
    assert broadcast_ball(t, [bro(balls=[ball(54.0, 30.0)], ok=False)])[0]["ball"] == []


def test_the_ball_on_a_tactical_player_check_never_compares_a_broadcast_box_with_a_tactical_one():
    # The broadcast ball's pixels fall inside a tactical player's box, in a different picture.
    t = tac(balls=[])
    t["players"][0]["bbox"] = [90, 90, 120, 130]
    out = one(t, bro(balls=[ball(54.0, 30.0)]))
    assert not track.ball_path([out])[0].on_player
