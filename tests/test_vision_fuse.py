"""Merging the tactical camera's two views (ninety/vision/fuse.py).

Detections are planted through a stand-in rig of the two lenses (tests/tactical_rig.py), placed on
the pitch as observe places them. Each case that must merge has a near miss that must not: the
gate is what the two measurements can miss by, and no wider.
"""

from __future__ import annotations

import numpy as np
import pytest

from ninety.vision import fuse, track
from ninety.vision.fuse import PRECISION, ellipse, fuse_frame, same_place
from tests.tactical_rig import LEFT, RIGHT, ball_box, player_box

VIEWS = {"tac-l": LEFT, "tac-r": RIGHT}


def player(view: str, x: float, y: float, score: float = 0.9, rgb=(200.0, 20.0, 20.0)) -> dict:
    """A player detection in `view` of someone standing at (x, y), placed where observe would
    place it: the box is drawn from (x, y), and the place is (x, y)."""
    return {"bbox": player_box(VIEWS[view], x, y), "score": score, "x": x, "y": y, "rgb": list(rgb)}


def ball(view: str, x: float, y: float, score: float = 0.8) -> dict:
    return {"bbox": ball_box(VIEWS[view], x, y), "score": score, "x": x, "y": y}


def frame(left=(), right=(), left_ball=(), right_ball=(), frame=0, ok=(True, True), residual=0.0):
    def row(view, players, balls, good):
        return {"frame": frame, "t": frame / 25,
                "camera": {"ok": good, "median_px": residual, "P": VIEWS[view].tolist() if good else None},
                "players": list(players), "ball": list(balls)}
    return {"tac-l": row("tac-l", left, left_ball, ok[0]), "tac-r": row("tac-r", right, right_ball, ok[1])}


def places(out, key="players"):
    return sorted((round(d["x"], 2), round(d["y"], 2), tuple(d["views"])) for d in out[key])


def test_one_player_on_halfway_seen_by_both_lenses_is_one_player_from_both():
    out = fuse_frame(frame([player("tac-l", 52.5, 34.0, 0.8)], [player("tac-r", 52.6, 34.1, 0.9)]))
    assert len(out["players"]) == 1
    p = out["players"][0]
    assert p["views"] == ["tac-l", "tac-r"] and p["score"] == 0.9 and p["view"] == "tac-r"
    assert 52.5 <= p["x"] <= 52.6 and 34.0 <= p["y"] <= 34.1  # between the two
    assert out["camera"]["ok"] and set(out["camera"]["views"]) == {"tac-l", "tac-r"}


def test_near_the_camera_a_15_cm_disagreement_merges_but_two_players_60_cm_apart_do_not():
    assert len(fuse_frame(frame([player("tac-l", 52.5, 6.0)], [player("tac-r", 52.65, 6.0)]))["players"]) == 1
    out = fuse_frame(frame([player("tac-l", 52.2, 6.0)], [player("tac-r", 52.8, 6.0)]))
    assert places(out) == [(52.2, 6.0, ("tac-l",)), (52.8, 6.0, ("tac-r",))]


def test_far_from_the_camera_depth_is_uncertain_so_40_cm_in_depth_merges_and_1_2_m_does_not():
    near = fuse_frame(frame([player("tac-l", 52.5, 65.8)], [player("tac-r", 52.5, 66.2)]))
    assert len(near["players"]) == 1
    out = fuse_frame(frame([player("tac-l", 52.5, 65.4)], [player("tac-r", 52.5, 66.6)]))
    assert len(out["players"]) == 2


def test_far_from_the_camera_depth_is_long_and_width_is_not():
    # The same 0.6 m: along the line of sight it is within what the views can miss by, across
    # it is not.
    a = player("tac-l", 52.5, 66.0)
    S = {v: ellipse("player", player(v, 52.5, 66.0), VIEWS[v], 0.0) for v in VIEWS}
    deep = same_place(a, S["tac-l"], player("tac-r", 52.5, 66.6), S["tac-r"])
    wide = same_place(a, S["tac-l"], player("tac-r", 53.1, 66.0), S["tac-r"])
    assert deep < 1.0 < wide


def test_two_players_close_together_in_one_view_are_never_merged():
    out = fuse_frame(frame([player("tac-l", 52.5, 34.0), player("tac-l", 52.55, 34.05)], []))
    assert len(out["players"]) == 2


def test_each_detection_merges_once_with_its_closest_partner():
    out = fuse_frame(frame([player("tac-l", 52.5, 34.0)],
                           [player("tac-r", 52.55, 34.0), player("tac-r", 52.5, 34.4)]))
    got = sorted((d["views"], round(d["x"], 1), round(d["y"], 1)) for d in out["players"])
    assert got == [(["tac-l", "tac-r"], 52.5, 34.0), (["tac-r"], 52.5, 34.4)]


def test_the_ball_in_the_overlap_is_one_ball_and_a_second_ball_far_off_is_kept():
    out = fuse_frame(frame(left_ball=[ball("tac-l", 52.0, 40.0, 0.7)],
                           right_ball=[ball("tac-r", 52.05, 40.05, 0.9), ball("tac-r", 70.0, 20.0, 0.6)]))
    assert [len(b["views"]) for b in out["ball"]] == [2, 1] and out["ball"][0]["score"] == 0.9


def test_a_player_and_the_ball_at_his_feet_are_never_merged():
    out = fuse_frame(frame([player("tac-l", 52.5, 34.0)], right_ball=[ball("tac-r", 52.5, 34.0)]))
    assert len(out["players"]) == 1 and len(out["ball"]) == 1


def test_a_view_whose_camera_is_not_trusted_merges_nothing_and_its_detections_pass_unplaced():
    right = player("tac-r", 52.5, 34.0) | {"x": None, "y": None}
    out = fuse_frame(frame([player("tac-l", 52.5, 34.0)], [right], ok=(True, False)))
    assert out["camera"]["ok"] and len(out["players"]) == 2
    assert sorted(p["x"] is None for p in out["players"]) == [False, True]


def test_a_detection_below_the_scorer_s_threshold_is_passed_through_not_merged():
    out = fuse_frame(frame([player("tac-l", 52.5, 34.0, 0.3)], [player("tac-r", 52.5, 34.0)]))
    assert len(out["players"]) == 2


def test_a_poor_camera_fit_widens_the_gate():
    # 1 m apart at the far touchline does not merge on a clean fit; on a fit 5 px off, it does.
    pair = ([player("tac-l", 52.5, 65.5)], [player("tac-r", 52.5, 66.5)])
    assert len(fuse_frame(frame(*pair))["players"]) == 2
    assert len(fuse_frame(frame(*pair, residual=5.0))["players"]) == 1


def test_views_with_different_frames_are_refused():
    a = [frame(frame=0)["tac-l"], frame(frame=1)["tac-l"]]
    b = [frame(frame=0)["tac-r"]]
    with pytest.raises(ValueError, match="same frames"):
        fuse.fuse({"tac-l": a, "tac-r": b})
    with pytest.raises(ValueError, match="two views"):
        fuse.fuse({"tac-l": a})


def test_fused_lines_track_as_observe_s_lines_do():
    rows = []
    for k in range(30):
        x = 50.0 + 0.2 * k  # one player running right across halfway, seen by one view then both
        left = [player("tac-l", x, 34.0)] if x <= 55.0 else []
        right = [player("tac-r", x + 0.05, 34.0)] if x >= 50.0 else []
        rows.append(frame(left, right, frame=k))
    fused = fuse.fuse({v: [r[v] for r in rows] for v in VIEWS})
    assert sum(len(f["players"]) for f in fused) == 30  # once a frame, never twice
    tracks = track.track_players(fused)
    assert len(tracks) == 1 and len(tracks[0].frames) == 30


def test_the_precision_is_the_measured_one():
    import json
    from pathlib import Path

    m = json.loads((Path(__file__).parents[1] / "docs/eval/fuse-gate/foot-precision.json").read_text())
    assert PRECISION == {c: (m[c]["p99_across"], m[c]["p99_down"]) for c in ("player", "ball")}
    assert np.isfinite(list(PRECISION["ball"])).all()


def test_the_ball_is_on_a_player_only_when_both_boxes_are_in_one_picture():
    # The ball in the right lens at pixels a left-lens player's box happens to cover.
    p = player("tac-l", 30.0, 30.0)
    b = {"bbox": p["bbox"][:2] + [p["bbox"][0] + 4, p["bbox"][1] + 4], "score": 0.9,
         "x": 70.0, "y": 30.0, "view": "tac-r", "views": ["tac-r"]}
    row = {"frame": 0, "t": 0.0, "camera": {"ok": True},
           "players": [p | {"view": "tac-l", "views": ["tac-l"]}], "ball": [b]}
    assert not track.ball_path([row])[0].on_player
    row["players"][0]["view"] = "tac-r"
    assert track.ball_path([row])[0].on_player
