"""The camera from the pitch markings (ninety/vision/pitch.py), on scenes built here.

A known camera projects Law 1's markings; the fit must recover it from those pixels alone. Each
guard has a case only it catches: a stripe edge is not a marking, a white kit inside a player's
box is not a marking, too few markings is not a fit (docs/LESSONS.md, lessons 8 and 73).
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from ninety.eval.event_score import STRICT_M
from ninety.vision import pitch

W, H = 1280, 720
GANTRY = (58.0, -37.0, 16.0)


def view(pan=0.29, tilt=0.14, focal=3600.0, gantry=GANTRY):
    return pitch.View(*gantry, pan, tilt, focal, W, H)


def marking_pixels(v: pitch.View, step_m: float = 0.1) -> np.ndarray:
    """Pixels on the markings `v` sees: every marking sampled every step_m, projected, kept in shot."""
    pts = []
    for pl in pitch.pitch_polylines():
        for (x0, y0), (x1, y1) in zip(pl[:-1], pl[1:], strict=True):
            n = max(1, math.ceil(math.hypot(x1 - x0, y1 - y0) / step_m))
            for k in range(n):
                pts.append((x0 + (x1 - x0) * k / n, y0 + (y1 - y0) * k / n, 0.0))
    uv, depth = v.project(np.array(pts))
    keep = (depth > 0) & (uv[:, 0] >= 0) & (uv[:, 0] < W) & (uv[:, 1] >= 0) & (uv[:, 1] < H)
    return uv[keep]


def test_the_pitch_model_is_law_1():
    xs = pitch.SEGMENTS[:, :, 0]
    ys = pitch.SEGMENTS[:, :, 1]
    assert xs.min() == pytest.approx(0, abs=1e-9) and xs.max() == pytest.approx(pitch.PITCH_X)
    assert ys.min() == pytest.approx(0, abs=1e-9) and ys.max() == pytest.approx(pitch.PITCH_Y)
    assert (pitch.SEGMENTS[:, :, 2] == 0).all()
    circle = [p for p in pitch.pitch_polylines()[2]]
    assert all(abs(math.hypot(x - 52.5, y - 34) - pitch.CIRCLE_R) < 1e-9 for x, y in circle)


def test_projection_and_ground_back_projection_invert_each_other():
    v = view()
    X = np.array([[70.0, 30.0, 0.0], [90.0, 50.0, 0.0], [60.0, 5.0, 0.0]])
    uv, _ = v.project(X)
    assert np.allclose(v.to_ground(uv), X[:, :2], atol=1e-6)


def test_a_known_camera_is_recovered_from_its_markings_with_the_gantry_known(small_grid):
    truth = view()
    pts = marking_pixels(truth)
    fit = pitch.refine(pitch.search(pts, W, H, gantry=GANTRY, keep=1)[0], pts)
    assert abs(fit.pan - truth.pan) < 1e-3 and abs(fit.tilt - truth.tilt) < 1e-3
    assert abs(fit.focal / truth.focal - 1) < 0.01
    assert pitch._median(fit, pts) < 0.1


@pytest.fixture
def small_grid(monkeypatch):
    """A 2 x 2 x 2 gantry grid that does not contain the true gantry, so the joint refine has to
    carry the best grid point the last metres; the full grid is too slow for CI."""
    monkeypatch.setattr(pitch, "GANTRY_X", (52.5, 62.5))
    monkeypatch.setattr(pitch, "GANTRY_BACK", (34.0, 40.0))
    monkeypatch.setattr(pitch, "GANTRY_DOWN_DEG", (20.0, 26.0))
    monkeypatch.setattr(pitch, "GANTRY_FINALISTS", 3)
    # The scenes here pan between -0.25 and 0.31 and tilt between 0.14 and 0.17: the grid keeps
    # its steps and covers that with a margin, a quarter of the full range, for CI's time.
    monkeypatch.setattr(pitch, "PANS", tuple(np.arange(-0.45, 0.4501, 0.015)))
    monkeypatch.setattr(pitch, "TILTS", tuple(np.arange(0.06, 0.2501, 0.01)))


# The fit's precision, set before any result: half its marking pixels within MAX_MEDIAN_PX of a
# projected marking (pitch.py). That is what these tests hold it to.
#
# Away from the markings the gantry's weak position along the line of sight (with a narrow lens,
# distance trades against zoom) still moves the ground by up to 3.4 to 4.0 px on these perfect
# scenes, measured after the fit (0.13 m at worst); on seed 900001, a median 2.6 px, 90% within
# 14.7 px. That limit is reported in docs/EVALUATION.md, not asserted here.
#
# A downstream budget, not a precision: calibration may use up a quarter of the strict 1 m radius
# events are graded by. Set after measuring 0.13 m at worst on these scenes, and said so.
DOWNSTREAM_BUDGET_M = STRICT_M / 4
# With a narrow lens the gantry's distance trades against zoom (perfect markings leave it within
# tens of centimetres, the clip about 2 m): a bound that catches a gantry in the wrong place.
GANTRY_GROSS_M = 2.0


def pitch_error(fitted: pitch.View, truth: pitch.View) -> float:
    """The largest distance between where `fitted` and `truth` put a pixel on the pitch, over a
    grid of pixels the truth shows on the pitch."""
    uv = np.array([(u, v) for u in range(0, W, 64) for v in range(0, H, 36)], dtype=float)
    g = truth.to_ground(uv)
    on = np.isfinite(g).all(1) & (g[:, 0] >= 0) & (g[:, 0] <= 105) & (g[:, 1] >= 0) & (g[:, 1] <= 68)
    return float(np.max(np.linalg.norm(fitted.to_ground(uv[on]) - g[on], axis=1)))


def test_the_gantry_is_recovered_from_frames_that_pan_across_the_pitch(small_grid):
    truths = [view(pan=p, tilt=t) for p, t in ((0.29, 0.14), (0.05, 0.16), (-0.25, 0.15))]
    anchors = [marking_pixels(v) for v in truths]
    g = pitch.find_gantry(anchors, W, H)
    assert math.dist(g, GANTRY) < GANTRY_GROSS_M, g
    for v, a in zip(truths, anchors, strict=True):
        fit = pitch.refine(pitch.search(a, W, H, gantry=g, keep=1)[0], a)
        assert pitch._median(fit, a) <= pitch.MAX_MEDIAN_PX
        assert pitch_error(fit, v) < DOWNSTREAM_BUDGET_M


def test_a_frame_with_too_few_markings_is_not_ok():
    truth = view()
    pts = marking_pixels(truth)[: pitch.MIN_POINTS - 1]
    assert not pitch._judge(truth, pts).ok
    assert pitch._judge(truth, marking_pixels(truth)).ok


def grass(h=60, w=80):
    img = np.zeros((h, w, 3), dtype=np.uint8)
    img[...] = (60, 120, 10)
    return img


def test_a_white_line_on_grass_is_a_marking():
    img = grass()
    img[30, :] = (240, 240, 235)
    m = pitch.line_mask(img)
    # The blur spreads a 1 px line over the rows either side, centred on it: no pixel elsewhere.
    assert m[30, 10:70].all() and m.sum() == m[29:32].sum()
    assert m[29].sum() == m[31].sum()


def test_sensor_grain_is_not_a_marking_and_a_far_line_with_a_gap_still_is():
    # Grain at the renderer's strongest noise (params.noise up to 0.02 of full scale: 5.1 levels),
    # drawn independently per pixel and channel.
    rng = np.random.default_rng(0)

    def grainy(img):
        return np.clip(img + rng.normal(0, 0.02 * 255, img.shape), 0, 255).astype(np.uint8)

    assert pitch.line_mask(grainy(grass(80, 120))).sum() == 0
    line = grass(80, 120)
    line[40, :] = (240, 240, 235)
    line[40, 60] = line[39, 60]  # a gap of one pixel in a 1 px line
    m = pitch.line_mask(grainy(line))
    assert m[40, 10:110].sum() >= 98 and m.sum() == m[39:42].sum()


def test_the_edge_between_two_mowing_stripes_is_not_a_marking():
    img = grass()
    img[:, 40:] = (90, 160, 40)  # a lighter stripe: brighter on one side only
    assert not pitch.line_mask(img).any()


def test_a_white_kit_inside_a_player_box_is_not_a_marking():
    img = grass()
    img[20:24, 30:34] = (245, 245, 245)  # small white shorts: brighter than grass on both sides
    assert pitch.line_mask(img).any()
    assert not pitch.line_mask(img, boxes=[(28, 15, 36, 30)]).any()


@pytest.mark.parametrize("pan", [0.29, -0.2])
def test_a_clip_is_tracked_frame_to_frame_and_every_frame_is_ok(pan, small_grid):
    truths = [view(pan=pan + 0.004 * k, tilt=0.14 + 0.001 * k) for k in range(6)]
    pts = [marking_pixels(v) for v in truths]
    # Two anchors a few hundredths of a radian apart cannot place the gantry along the line of
    # sight (the test above pans widely for that); tracking is judged by where pixels land.
    _, fits = pitch.fit_clip(pts, W, H, anchor_every=3)
    assert all(f.ok for f in fits)
    for f, v, a in zip(fits, truths, pts, strict=True):
        assert pitch._median(f.view, a) <= pitch.MAX_MEDIAN_PX
        assert pitch_error(f.view, v) < DOWNSTREAM_BUDGET_M


# Camera cuts (pitch.shot_starts, pitch.fit_shots; docs/eval/camera-cuts-plan.md).


def test_the_cut_distance_is_the_share_of_pixels_whose_colour_cell_changed():
    a = grass()
    b = grass()
    b[:30] = (240, 240, 240)  # half the picture turns white: half its pixels change cell
    ha, hb = pitch.colour_histogram(a), pitch.colour_histogram(b)
    assert pitch.cut_distance(ha, ha) == 0.0
    assert pitch.cut_distance(ha, hb) == pytest.approx(0.5)
    white = np.full_like(a, 240)
    assert pitch.cut_distance(ha, pitch.colour_histogram(white)) == pytest.approx(1.0)


def test_a_shot_starts_at_every_frame_at_least_the_threshold_from_the_last():
    h0 = pitch.colour_histogram(grass())
    half = grass()
    half[:30] = (240, 240, 240)
    h1 = pitch.colour_histogram(half)  # 0.5 from h0
    hists = [h0, h0, h1, h1, h0]
    assert pitch.shot_starts(hists, threshold=0.5) == [0, 2, 4]  # at the threshold is a cut
    assert pitch.shot_starts(hists, threshold=0.51) == [0]
    assert pitch.shot_starts([h0, h1]) == [0, 1]  # the adopted threshold sees half the picture change


OTHER_GANTRY = (50.0, -38.0, 15.0)  # another camera on the same stand, 8 m along it


def two_shots():
    first = [view(pan=0.29 - 0.27 * k, tilt=0.14 + 0.01 * k) for k in range(3)]
    second = [view(pan=0.42 - 0.3 * k, tilt=0.15, focal=3000.0, gantry=OTHER_GANTRY) for k in range(3)]
    return first + second


def test_after_a_cut_each_shot_gets_its_own_gantry_and_every_frame_fits(small_grid):
    truths = two_shots()
    pts = [marking_pixels(v) for v in truths]
    gantries, fits = pitch.fit_shots(pts, W, H, [0, 3], anchor_every=1)
    assert math.dist(gantries[0], GANTRY) < GANTRY_GROSS_M
    assert math.dist(gantries[1], OTHER_GANTRY) < GANTRY_GROSS_M
    assert all(f.ok for f in fits)
    for f, v in zip(fits, truths, strict=True):
        assert pitch_error(f.view, v) < DOWNSTREAM_BUDGET_M
    # One gantry for both shots, as before the change, cannot fit them all.
    _, joint = pitch.fit_clip(pts, W, H, anchor_every=1)
    assert not all(f.ok and pitch_error(f.view, v) < DOWNSTREAM_BUDGET_M
                   for f, v in zip(joint, truths, strict=True))


def test_a_shot_without_markings_gets_no_camera_and_the_others_are_still_fitted(monkeypatch):
    calls = []

    def fit_clip(points, w, h, anchor_every=25):
        calls.append(len(points))
        if not any(len(p) for p in points):
            raise ValueError("no frame shows enough pitch markings to place the camera")
        return GANTRY, [pitch.FrameFit(view(), 0.5, len(p), True) for p in points]

    monkeypatch.setattr(pitch, "fit_clip", fit_clip)
    some, none = np.zeros((100, 2)), np.zeros((0, 2))
    gantries, fits = pitch.fit_shots([some, some, none, none, some], W, H, [0, 2, 4])
    assert calls == [2, 2, 1] and gantries == [GANTRY, None, GANTRY]
    assert [f.ok for f in fits] == [True, True, False, False, True] and fits[2].view is None
    with pytest.raises(ValueError):  # a clip of one shot with no markings is still an error
        pitch.fit_shots([none, none], W, H, [0])


def test_a_clip_without_a_cut_is_fitted_exactly_as_before(monkeypatch):
    seen = []
    def fit_clip(points, w, h, anchor_every=25):
        seen.append((points, anchor_every))
        return GANTRY, ["fits"]

    monkeypatch.setattr(pitch, "fit_clip", fit_clip)
    pts = [np.zeros((100, 2)) for _ in range(4)]
    assert pitch.fit_shots(pts, W, H, [0]) == ([GANTRY], ["fits"])
    assert len(seen) == 1 and seen[0][1] == 25
    assert len(seen[0][0]) == len(pts) and all(a is b for a, b in zip(seen[0][0], pts, strict=True))
