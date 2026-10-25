"""The image stage's trust test (ninety/vision/observe.py, `place`): a camera is trusted when its
players are as tall as they should be, and only then are detections placed on the pitch."""

from __future__ import annotations

import json
import math
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


def test_the_band_holds_its_ends_and_on_the_broadcast_the_markings_must_agree():
    lo, hi = observe.HEIGHT_BAND
    assert observe.place(row(lo + 0.002))["camera"]["ok"]
    assert observe.place(row(hi - 0.002))["camera"]["ok"]
    assert not observe.place(row(lo - 0.01))["camera"]["ok"]
    assert not observe.place(row(hi + 0.01))["camera"]["ok"]
    # Gate B3 (lesson 230): heights in the band and markings that do not fit is not a camera.
    assert not observe.place(row(markings_ok=False))["camera"]["ok"]
    assert observe.place(row(markings_ok=False))["camera"]["heights_ok"] is False
    # A fixed lens is judged by its heights alone.
    assert observe.place(row(markings_ok=False), markings=False)["camera"]["ok"]


def test_a_whole_clip_through_a_wrong_camera_whose_markings_do_not_fit_is_never_trusted():
    # Validation seed 2042's failure: every frame's camera 28 m wrong the same way, players the
    # right height through it (the same camera, moved), the marking fit failing. The neighbours
    # agree with each other, so only the markings can stop it.
    rows = []
    for f in range(11):
        r = wrong_place_row(28.0, f)
        r["camera"]["ok"] = False  # the marking fit's own verdict
        rows.append(observe.place(r))
    rows = observe.agree(rows)
    assert not any(r["camera"]["ok"] for r in rows)
    assert all(r["players"][0]["x"] is None for r in rows)


def test_with_no_player_to_measure_the_markings_verdict_stands():
    assert observe.place(row(players=[]))["camera"]["ok"] is True
    assert observe.place(row(players=[], markings_ok=False))["camera"]["ok"] is False


def test_the_band_is_the_committed_validation_measurement():
    body = json.loads((ROOT / "docs/eval/band-broadcast.json").read_text())
    assert list(observe.HEIGHT_BAND) == body["broadcast"]["band"] == [0.966, 1.121]
    assert not any(s >= 900000 for s in body["seeds"])  # validation clips only


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
    # One frame 10 m wrong among right ones: the heights pass it, its neighbours do not. A tie goes
    # to the earlier neighbour (fixed in the plan, not tuned), so frame 4 is judged against 3 and
    # kept, and frame 6 against 5 and lost with it: one wrong frame costs one good one after it.
    rows = observe.agree(clip({5: 10.0}))
    assert [r["camera"]["ok"] for r in rows] == [True] * 5 + [False, False] + [True] * 4
    assert all(d["x"] is None for d in rows[5]["players"]) and rows[5]["ball"][0]["x"] is None
    assert rows[5]["camera"]["heights_ok"] is True  # the heights' verdict, kept for the record


def test_neighbours_agree_within_two_metres_and_not_beyond():
    assert all(r["camera"]["ok"] for r in observe.agree(clip({5: observe.NEIGHBOUR_M - 0.1})))
    assert not observe.agree(clip({5: observe.NEIGHBOUR_M + 0.1}))[5]["camera"]["ok"]


def test_a_neighbour_exactly_the_window_away_still_counts():
    far = observe.place(wrong_place_row(0.0, observe.NEIGHBOUR_FRAMES))
    assert [r["camera"]["ok"] for r in observe.agree(clip({}, frames=1) + [far])] == [True, True]


def test_a_frame_too_tall_for_its_camera_stays_untrusted_however_well_it_agrees():
    # Its camera is the same as its neighbours', so it agrees; the heights still reject it.
    rows = [observe.place(dict(row(1.3 if f == 5 else 1.0), frame=f)) for f in range(11)]
    rows = observe.agree(rows)
    assert rows[5]["camera"]["heights_ok"] is False and rows[5]["camera"]["ok"] is False
    assert rows[4]["camera"]["ok"] and rows[6]["camera"]["ok"]


def test_the_principal_point_is_the_image_centre_on_a_panned_and_tilted_camera():
    v = pitch.View(40.0, -35.0, 16.0, pan=0.35, tilt=0.22, focal=1800.0, width=1280, height=720)
    P = v.P()
    g = observe.principal_ground(P)
    want = observe._ground(P, (640.0, 360.0))
    assert abs(g[0] - want[0]) < 1e-6 and abs(g[1] - want[1]) < 1e-6
    assert abs(g[0] - observe._ground(P, (0.0, 0.0))[0]) > 1.0  # not just any pixel


def test_observe_judges_each_frame_against_its_neighbours(monkeypatch):
    # The whole image stage with the camera fit stubbed: frame 5's camera is 10 m wrong.
    from types import SimpleNamespace
    P = VIEW.P()
    dets = []
    for f in range(11):
        boxes = [SimpleNamespace(cls="player", bbox=tuple(d["bbox"]), score=0.9) for d in row()["players"]]
        dets.append(SimpleNamespace(frame=f, t=f / 25, detections=tuple(boxes)))
    fits = [pitch.FrameFit(view_at(10.0 if f == 5 else 0.0), 1.0, 200, True) for f in range(11)]
    monkeypatch.setattr(pitch, "line_points", lambda rgb, boxes: np.zeros((0, 2)))
    monkeypatch.setattr(pitch, "fit_clip", lambda points, w, h, **k: ((VIEW.cx, VIEW.cy, VIEW.cz), fits))
    rows = observe.observe([Path(f"{f}.jpg") for f in range(11)], dets,
                           lambda path: np.zeros((720, 1280, 3), np.uint8))
    assert P is not None and [r["camera"]["ok"] for r in rows][4:7] == [True, False, False]


def test_a_trusted_frame_with_no_trusted_neighbour_near_it_is_not_trusted():
    far = observe.place(wrong_place_row(0.0, observe.NEIGHBOUR_FRAMES + 1))
    rows = observe.agree(clip({}, frames=1) + [far])
    assert [r["camera"]["ok"] for r in rows] == [False, False]
    together = observe.agree(clip({}, frames=2))
    assert [r["camera"]["ok"] for r in together] == [True, True]


def in_shots(rows: list[dict], starts: list[int]) -> list[dict]:
    """Label each row with its shot, the shots beginning at the given frames."""
    for r in rows:
        r["camera"]["shot"] = sum(r["frame"] >= s for s in starts) - 1
    return rows


def test_after_a_cut_frames_are_judged_against_their_own_shot():
    # Frames 6 to 10 are another camera, 30 m from the first: each shot agrees within itself. Judged
    # across the cut, frame 6 would meet frame 5 first (the tie goes to the earlier) and be lost.
    rows = observe.agree(in_shots(clip({f: 30.0 for f in range(6, 11)}), [0, 6]))
    assert all(r["camera"]["ok"] for r in rows)
    across = observe.agree(clip({f: 30.0 for f in range(6, 11)}))
    assert [r["camera"]["ok"] for r in across] == [True] * 6 + [False] + [True] * 4


def test_a_shot_of_one_frame_has_no_neighbour_and_is_not_trusted():
    # Frame 5 alone between two cuts: its camera agrees with the frames either side, but they are
    # other shots, so nothing vouches for it.
    rows = observe.agree(in_shots(clip({}), [0, 5, 6]))
    assert [r["camera"]["ok"] for r in rows] == [True] * 5 + [False] + [True] * 5


def test_observe_fits_each_shot_on_its_own_and_labels_it(monkeypatch):
    # The images change colour at frame 6 (a cut); the fit is stubbed and must be called once per
    # shot, with that shot's frames only.
    from types import SimpleNamespace
    dets = [SimpleNamespace(frame=f, t=f / 25, detections=tuple(
        SimpleNamespace(cls="player", bbox=tuple(d["bbox"]), score=0.9) for d in row()["players"]))
        for f in range(11)]
    calls = []

    def fit_clip(points, w, h, **k):
        calls.append(len(points))
        return (VIEW.cx, VIEW.cy, VIEW.cz), [pitch.FrameFit(VIEW, 1.0, 200, True) for _ in points]

    monkeypatch.setattr(pitch, "line_points", lambda rgb, boxes: np.zeros((0, 2)))
    monkeypatch.setattr(pitch, "fit_clip", fit_clip)
    grass, stands = np.zeros((72, 128, 3), np.uint8), np.zeros((72, 128, 3), np.uint8)
    grass[...] = (60, 120, 10)
    stands[...] = (120, 120, 140)
    load = lambda path: stands if int(path.stem) >= 6 else grass  # noqa: E731
    rows = observe.observe([Path(f"{f}.jpg") for f in range(11)], dets, load, cuts=True)
    assert calls == [6, 5]
    assert [r["camera"]["shot"] for r in rows] == [0] * 6 + [1] * 5
    assert [s["frame"] for s in rows[0]["shots"]] == [0, 6]
    assert all(r["camera"]["ok"] for r in rows)
    # Off by default (docs/eval/camera-cuts-plan.md, Outcome): the same images are one shot.
    calls.clear()
    rows = observe.observe([Path(f"{f}.jpg") for f in range(11)], dets, load)
    assert calls == [11] and {r["camera"]["shot"] for r in rows} == {0} and "shots" not in rows[0]


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


def test_the_trust_bound_is_the_committed_measurement():
    from ninety.eval import detector_derive as dd
    body = json.loads((ROOT / "docs/eval/detector-derive.json").read_text())["bound"]
    worst = body["candidates"]["height"]["worst_by_seed"][str(dd.BOUND_SEED)]
    assert dd.MAX_TRUSTED_M == math.ceil(worst * 2) / 2 == body["max_trusted_m"]
    assert dd.KEEP_GOOD == body["keep_good"] == 0.95
    assert body["adopted"] == "C2"


def test_observe_keeps_no_more_than_one_decoded_frame_at_a_time(monkeypatch):
    """A clip's frames do not fit in memory (a minute is about 4 GB), so each decoded image must be
    let go before the next is read; the kit colours are taken on the way. Same output either way."""
    import weakref

    from ninety.vision.detections import Detection, FrameDetections
    from ninety.vision.model import model

    monkeypatch.setattr(pitch, "find_gantry", lambda anchors, w, h: (58.0, -37.0, 16.0))
    shirt = Detection(cls="player", bbox=(100.0, 100.0, 120.0, 150.0), score=0.9)
    dets = [FrameDetections(clip="c", frame=k, t=k / 25, model=model("ours-v4"), detections=(shirt,))
            for k in range(6)]
    alive, most = [], []

    def load(_):
        most.append(sum(r() is not None for r in alive))
        img = np.full((360, 640, 3), (200, 30, 30), dtype=np.uint8)  # a red shirt, no grass
        alive.append(weakref.ref(img))
        return img

    rows = observe.observe([Path(f"{k}.jpg") for k in range(6)], dets, load)
    assert max(most) <= 1, most  # only the frame still in hand when the next is read
    assert [r["players"][0]["rgb"] for r in rows] == [[200.0, 30.0, 30.0]] * 6
