"""The image stage's trust test (ninety/vision/observe.py, `place`): a camera is trusted when its
players are as tall as they should be, and only then are detections placed on the pitch."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from ninety.vision import observe, pitch

ROOT = Path(__file__).resolve().parents[1]
VIEW = pitch.View(52.5, -40.0, 18.0, pan=0.0, tilt=0.3, focal=2000.0, width=1280, height=720)
SPOTS = [(40.0, 30.0), (60.0, 20.0), (52.0, 40.0), (70.0, 28.0)]


def project(P, x, y, z):
    h = P @ np.array([x, y, z, 1.0])
    return h[0] / h[2], h[1] / h[2]


def row(scale=1.0, players=SPOTS, markings_ok=True):
    """A frame through VIEW whose player boxes are `scale` times an upright 1.80 m player's height."""
    P = VIEW.P()
    dets = []
    for x, y in players:
        u, v_foot = project(P, x, y, 0.0)
        _, v_head = project(P, x, y, observe.PLAYER_HEIGHT_M)
        top = v_foot - scale * (v_foot - v_head)
        dets.append({"bbox": [u - 8, top, u + 8, v_foot], "score": 0.9, "x": None, "y": None, "rgb": None})
    u, v = project(P, 50.0, 31.0, observe.BALL_CENTRE_Z)
    ball = [{"bbox": [u - 4, v - 4, u + 4, v + 4], "score": 0.9}]
    return {"frame": 0, "t": 0.0, "players": dets, "ball": ball,
            "camera": {"ok": markings_ok, "median_px": 1.0, "points": 200, "P": P.tolist()}}


def test_players_of_the_right_height_are_trusted_and_placed_where_they_stand():
    r = observe.place(row())
    assert r["camera"]["ok"] and abs(r["camera"]["height_ratio"] - 1.0) < 1e-6
    for (x, y), d in zip(SPOTS, r["players"], strict=True):
        assert abs(d["x"] - x) < 0.01 and abs(d["y"] - y) < 0.01
    assert abs(r["ball"][0]["x"] - 50.0) < 0.01 and abs(r["ball"][0]["y"] - 31.0) < 0.01


def test_players_a_camera_makes_too_tall_or_too_short_are_not_trusted_and_not_placed():
    for scale in (1.3, 0.8):
        r = observe.place(row(scale))
        assert not r["camera"]["ok"], scale
        assert all(d["x"] is None for d in r["players"]) and r["ball"][0]["x"] is None


def test_the_band_holds_its_ends_and_the_markings_no_longer_decide():
    lo, hi = observe.HEIGHT_BAND
    assert observe.place(row(lo + 0.002, markings_ok=False))["camera"]["ok"]  # heights decide now
    assert observe.place(row(hi - 0.002))["camera"]["ok"]
    assert not observe.place(row(lo - 0.01))["camera"]["ok"]
    assert not observe.place(row(hi + 0.01))["camera"]["ok"]
    assert observe.place(row(markings_ok=False))["camera"]["markings_ok"] is False  # kept, for the record


def test_with_no_player_to_measure_the_markings_verdict_stands():
    assert observe.place(row(players=[]))["camera"]["ok"] is True
    assert observe.place(row(players=[], markings_ok=False))["camera"]["ok"] is False


def test_the_band_is_the_committed_validation_measurement():
    body = json.loads((ROOT / "docs/eval/detector-derive.json").read_text())
    assert list(observe.HEIGHT_BAND) == body["gates"]["band"]


def view_at(dx: float) -> pitch.View:
    return pitch.View(VIEW.cx + dx, VIEW.cy, VIEW.cz, VIEW.pan, VIEW.tilt, VIEW.focal,
                      VIEW.width, VIEW.height)


def wrong_place_row(dx: float = 10.0, frame: int = 0):
    """The scene through VIEW, but the frame's camera dx metres along the touchline from where it
    is: players come out the right height (the same camera, moved), placed dx metres wrong."""
    r = row()
    r["frame"] = frame
    r["camera"]["P"] = view_at(dx).P().tolist()
    return r


def clip(offsets: dict[int, float], frames: int = 11) -> list[dict]:
    """A clip of frames through VIEW, each frame's camera moved by offsets.get(frame, 0) metres."""
    return [observe.place(wrong_place_row(offsets.get(f, 0.0), f)) for f in range(frames)]


def test_a_camera_in_the_wrong_place_still_makes_players_the_right_height():
    # Why the height test alone cannot see it (lesson 149).
    r = observe.place(wrong_place_row())
    assert abs(r["camera"]["height_ratio"] - 1.0) < 1e-6
    assert abs(r["players"][0]["x"] - (SPOTS[0][0] + 10.0)) < 0.01


def test_a_frame_whose_camera_disagrees_with_its_neighbours_is_not_trusted():
    # One frame 10 m wrong among right ones (more than the plan's 8.5 m bound): the heights pass
    # it, its neighbours do not. Frames away from it stay trusted.
    rows = observe.agree(clip({5: 10.0}))
    ok = {r["frame"]: r["camera"]["ok"] for r in rows}
    assert ok[5] is False and all(d["x"] is None for d in rows[5]["players"])
    assert all(ok[f] for f in (0, 1, 2, 3, 7, 8, 9, 10))
    assert rows[5]["camera"]["heights_ok"] is True  # the heights' verdict, kept for the record


def test_a_trusted_frame_with_no_trusted_neighbour_near_it_is_not_trusted():
    far = observe.place(wrong_place_row(0.0, observe.NEIGHBOUR_FRAMES + 1))
    rows = observe.agree(clip({}, frames=1) + [far])
    assert [r["camera"]["ok"] for r in rows] == [False, False]
    together = observe.agree(clip({}, frames=2))
    assert [r["camera"]["ok"] for r in together] == [True, True]


@pytest.mark.xfail(strict=True, reason="no check of one frame against another can see a whole clip offset "
                   "the same way (validation seed 108); within the plan's bound, by design")
def test_a_whole_clip_in_the_wrong_place_is_not_trusted():
    rows = observe.agree(clip({f: 5.0 for f in range(11)}))
    assert not any(r["camera"]["ok"] for r in rows)


def test_regate_judges_each_frame_against_its_neighbours(tmp_path):
    src, out = tmp_path / "in.jsonl", tmp_path / "out.jsonl"
    src.write_text("".join(json.dumps(r) + "\n" for r in clip({5: 10.0})))
    observe.main(["--regate", str(src), "--out", str(out)])
    ok = [json.loads(x)["camera"]["ok"] for x in out.read_text().splitlines()]
    assert ok[5] is False and ok[0] and ok[10]
