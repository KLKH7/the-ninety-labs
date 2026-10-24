"""The fixed-camera fit (ninety/vision/pitch.py, `fit_fixed`) and the image stage's fixed mode
(ninety/vision/observe.py), on frames drawn here through the renderer's camera.

A lens of the tactical camera never moves: one camera is fitted per clip from the marking pixels
that stay put, and every frame is placed through it. The pass bar is the plan's, set before any
fit was run (docs/eval/tactical-fit-plan.md): reprojection within MAX_MEDIAN_PX, and no point of
the lens's half more than 2 m wrong.
"""

from __future__ import annotations

import math
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from ninety.eval import tactical_fit as tf
from ninety.vision import observe, pitch

GROSS_M = 2.0  # the plan's bound for a camera in the wrong place (tests/test_vision_pitch.py)


@pytest.fixture
def small(monkeypatch):
    """Half-size frames and a 2 x 2 x 2 grid of positions that does not hold the true one, with the
    pan, tilt and lens steps kept over a quarter of the range, for CI's time."""
    monkeypatch.setattr(tf, "W", 960)
    monkeypatch.setattr(tf, "H", 540)
    monkeypatch.setattr(pitch, "FIXED_X", (50.5, 56.5))
    monkeypatch.setattr(pitch, "FIXED_BACK", (30.0, 37.0))
    monkeypatch.setattr(pitch, "FIXED_HEIGHT", (25.0, 31.0))
    monkeypatch.setattr(pitch, "FIXED_PAN_MAX", 0.6)
    monkeypatch.setattr(pitch, "FIXED_TILTS", tuple(np.arange(0.4, 0.6401, 0.02)))
    monkeypatch.setattr(pitch, "FIXED_HFOV_DEG", (52.0, 60.0, 68.0))
    monkeypatch.setattr(pitch, "FIXED_POINTS", 800)


def lens(side="right"):
    return tf.camera(side, 52.0, 33.5, 28.5, 61.0, 0.52, 0.47)


def truth_view(cam) -> pitch.View:
    f = np.array(cam.R)[2]
    return pitch.View(*cam.position, math.atan2(f[0], f[1]), math.asin(-f[2]), cam.focal_px, cam.width,
                      cam.height)


def test_a_fixed_lens_is_recovered_from_its_drawn_frames(small):
    # A left lens, so the grid's negative pans are the ones searched (a right lens is measured in
    # docs/eval/tactical-fit.md; one lens keeps CI's time).
    side = "left"
    cam = lens(side)
    static, points = tf.clip(side, cam, seed=11, frames=6)
    view, fits = pitch.fit_fixed(static, points, tf.W, tf.H)
    pts, _ = tf.ground_grid(side, cam)
    metres, pixels = tf.errors(cam, view, pts)
    assert all(f.ok for f in fits)
    assert np.percentile(pixels, 95) <= pitch.MAX_MEDIAN_PX
    assert metres.max() < GROSS_M


def test_the_renderers_camera_and_the_fits_are_one_model():
    cam = lens("left")
    X = np.array([[10.0, 5.0, 0.0], [40.0, 60.0, 0.0], [52.5, 34.0, 1.8]])
    uv, _ = truth_view(cam).project(X)
    assert np.allclose(uv, [cam.project(tuple(x)) for x in X], atol=1e-6)


def test_a_lens_and_its_mirror_across_halfway_do_not_tie():
    # The markings are symmetric about halfway, but the mirror lens sees the picture flipped, so the
    # fit needs no word on which half a lens shows: the true lens fits, its mirror is far off.
    v = truth_view(lens("right"))
    mirror = pitch.View(105.0 - v.cx, v.cy, v.cz, -v.pan, v.tilt, v.focal, v.width, v.height)
    pts = _marking_pixels(v)
    assert len(pts) > 1000 and np.median(pitch.distances(v, pts)) < 0.01
    assert np.median(pitch.distances(mirror, pts)) > 10 * pitch.MAX_MEDIAN_PX
    flipped = np.c_[v.width - pts[:, 0], pts[:, 1]]
    assert np.median(pitch.distances(mirror, flipped)) < 0.01  # what the mirror sees


def _marking_pixels(v: pitch.View, step_m: float = 0.25) -> np.ndarray:
    pts = []
    for pl in pitch.pitch_polylines():
        for (x0, y0), (x1, y1) in zip(pl[:-1], pl[1:], strict=True):
            n = max(1, math.ceil(math.hypot(x1 - x0, y1 - y0) / step_m))
            pts += [(x0 + (x1 - x0) * k / n, y0 + (y1 - y0) * k / n, 0.0) for k in range(n)]
    uv, depth = v.project(np.array(pts))
    keep = (depth > 0) & (uv[:, 0] >= 0) & (uv[:, 0] < v.width) & (uv[:, 1] >= 0) & (uv[:, 1] < v.height)
    return uv[keep]


def test_the_grid_pans_both_ways_and_straight_ahead():
    pans = np.unique(pitch.fixed_grid(1920)[:, 3])
    assert pans.min() == pytest.approx(-0.78) and pans.max() == pytest.approx(0.78)
    assert np.isclose(pans, 0.0).any() and np.allclose(np.diff(pans), 0.03)


def test_a_pixel_is_static_from_half_the_frames_and_not_one_frame_fewer():
    counts = np.zeros((4, 6), dtype=np.uint32)
    counts[1, :] = 10  # a line in every frame
    counts[2, 0] = 5  # exactly half of 10 frames
    counts[2, 1] = 4  # one frame fewer
    counts[3, 2] = 1  # a white kit the detector missed, in one frame
    pts = pitch.static_points(counts, 10)
    got = {(int(x), int(y)) for x, y in pts}
    assert got == {(x, 1) for x in range(6)} | {(0, 2)}


def test_too_few_static_markings_is_no_camera():
    with pytest.raises(ValueError):
        pitch.fit_fixed(np.zeros((pitch.MIN_POINTS - 1, 2)), [], 1920, 1080)


def test_a_fixed_clip_places_every_frame_through_one_camera(monkeypatch):
    # The image stage in fixed mode, with the fit stubbed: one camera, every frame (no jitter),
    # the static vote is what the fit reads, and the heights still judge each frame (lesson 148).
    view = truth_view(lens("right"))
    seen = {}

    def fit_fixed(static, points, w, h):
        seen.update(static=static, frames=len(points))
        return view, [pitch.FrameFit(view, 1.0, 200, True) for _ in points]

    monkeypatch.setattr(pitch, "fit_fixed", fit_fixed)
    monkeypatch.setattr(pitch, "fit_clip", lambda *a: pytest.fail("a fixed lens is fitted once"))
    P = view.P()
    frames = []
    for f in range(4):
        boxes = []
        for x, y in [(70.0, 30.0), (80.0, 20.0), (90.0, 50.0)]:
            u, vf = _px(P, x + f, y, 0.0)
            _, vh = _px(P, x + f, y, observe.PLAYER_HEIGHT_M * (1.3 if f == 2 else 1.0))
            boxes.append(SimpleNamespace(cls="player", bbox=(u - 5, vh, u + 5, vf), score=0.9))
        frames.append(SimpleNamespace(frame=f, t=f / 25, detections=tuple(boxes)))
    img = np.zeros((view.height, view.width, 3), np.uint8)
    img[...] = (60, 120, 10)
    img[500, 100:400] = (240, 240, 235)  # a marking in every frame
    rows = observe.observe([Path(f"{f}.jpg") for f in range(4)], frames, lambda p: img.copy(), fixed=True)
    assert seen["frames"] == 4
    assert {(int(x), int(y)) for x, y in seen["static"]} >= {(x, 500) for x in range(110, 390)}
    assert len({str(r["camera"]["P"]) for r in rows}) == 1
    assert rows[0]["fixed"] is True
    assert [r["camera"]["heights_ok"] for r in rows] == [True, True, False, True]
    assert rows[0]["players"][0]["x"] == pytest.approx(70.0, abs=0.01)


def _px(P, x, y, z):
    h = P @ np.array([x, y, z, 1.0])
    return h[0] / h[2], h[1] / h[2]



# A drawn scene where the six-parameter step stalls: the static marking pixels of
# `tactical_fit.sample_cameras(1, 7)[0]` (clip seed 7000, thinned to 500), and the view the free
# step stopped at, about a metre from the camera (3.1 px at p95 on the lens's half).
STALLED = (53.0052, -36.3211, 29.6475, -0.523, 0.4942, 1739.1743)


def test_the_compass_search_walks_on_where_the_free_step_stalls():
    side, cam = tf.sample_cameras(1, 7)[0]
    static = np.load(Path(__file__).parent / "fixtures" / "tactical-static-seed7.npy")
    stalled = pitch.View(*STALLED, tf.W, tf.H)
    pts, _ = tf.ground_grid(side, cam)

    def p95(v):
        return np.percentile(tf.errors(cam, v, pts)[1], 95)

    assert p95(pitch.refine(stalled, static, free=range(6), iters=50)) > 2 * pitch.MAX_MEDIAN_PX
    assert p95(pitch.settle(stalled, static)) <= pitch.MAX_MEDIAN_PX
