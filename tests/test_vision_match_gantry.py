"""One gantry per match, and "camera unsure" per shot (pitch.fit_match_gantry, pitch.fit_match_shots,
observe's `gantry`), on scenes built here (docs/eval/match-gantry-plan.md).

A goal-end clip is fitted through the gantry its match pins; a match of one clip is today's fit; a
reverse angle (the main camera's mirror through the centre spot, lesson 244) is marked unsure when
its own gantry is beyond the tolerance and explains more of its frames; a shot without markings
cannot disagree.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from ninety.vision import observe, pitch
from tests.test_vision_pitch import (
    DOWNSTREAM_BUDGET_M,
    GANTRY,
    GANTRY_GROSS_M,
    H,
    W,
    marking_pixels,
    pitch_error,
    small_grid,  # noqa: F401  (a fixture)
    view,
)


def open_play():
    """Frames that pan widely across the pitch: they pin the gantry."""
    return [view(pan=p, tilt=t) for p, t in ((0.29, 0.14), (0.05, 0.16), (-0.25, 0.15))]


def goal_end():
    """A tight shot on the right-hand goal that barely moves: from it alone, distance along the
    line of sight trades against zoom."""
    return [view(pan=0.5 + 0.004 * k, tilt=0.16, focal=4200.0) for k in range(3)]


def test_one_clip_pools_exactly_the_anchors_and_scoring_frames_its_own_fit_uses():
    rng = np.random.default_rng(1)
    clip = [rng.random((n, 2)) for n in (90, 300, 10, 120, 400, 61, 200, 75)]
    pooled, score = pitch.match_anchors([clip])
    kept = [a for a in clip if len(a) >= pitch.MIN_POINTS]
    assert len(pooled) == len(kept) and all(a is b for a, b in zip(pooled, kept, strict=True))
    by_markings = sorted(kept, key=len, reverse=True)
    assert all(a is b for a, b in zip(score, by_markings, strict=True))


def test_scoring_frames_go_round_robin_across_clips_and_a_long_match_is_thinned(monkeypatch):
    def frames(*sizes):
        return [np.zeros((n, 2)) for n in sizes]

    a, b = frames(100, 400, 200), frames(300, 90)
    pooled, score = pitch.match_anchors([a, b])
    assert [len(x) for x in score] == [400, 300, 200, 90, 100]
    assert len(pooled) == 5
    monkeypatch.setattr(pitch, "MATCH_ANCHORS", 5)
    long = frames(*range(100, 110))
    pooled, _ = pitch.match_anchors([long, b])
    # each clip thinned evenly to its share, ceil(5 / 2) = 3
    assert [len(x) for x in pooled] == [100, 104, 109, 300, 90]
    pooled, _ = pitch.match_anchors([long])  # one clip is never thinned: it is today's fit
    assert len(pooled) == len(long)


@pytest.mark.usefixtures("small_grid")
def test_a_goal_end_clip_is_fitted_through_the_gantry_its_match_pins():
    first, goal = open_play(), goal_end()
    g = pitch.fit_match_gantry([[marking_pixels(v) for v in first], [marking_pixels(v) for v in goal]],
                               W, H)
    assert math.dist(g, GANTRY) < GANTRY_GROSS_M, g
    pts = [marking_pixels(v) for v in goal]
    checks, fits = pitch.fit_match_shots(pts, W, H, [0], g, anchor_every=1)
    assert not checks[0].unsure and checks[0].ok_match == len(goal)
    for f, v in zip(fits, goal, strict=True):
        assert f.ok and f.view.vector()[:3] == pytest.approx(g)
        assert pitch_error(f.view, v) < DOWNSTREAM_BUDGET_M


def test_a_match_of_one_clip_finds_its_gantry_from_what_its_own_fit_uses(monkeypatch):
    seen = []
    monkeypatch.setattr(pitch, "find_gantry", lambda a, w, h, score=None: seen.append((a, score)) or GANTRY)
    rng = np.random.default_rng(2)
    clip = [rng.random((n, 2)) for n in (90, 300, 10, 120, 400, 61, 200)]
    assert pitch.fit_match_gantry([clip], W, H) == GANTRY
    anchors, score = seen[0]
    # find_gantry keeps the anchors with MIN_POINTS and scores on its GANTRY_SCORE_FRAMES with most
    # markings; the pooled lists give it exactly those.
    kept = sorted((a for a in clip if len(a) >= pitch.MIN_POINTS), key=len, reverse=True)
    assert [id(a) for a in sorted(anchors, key=len, reverse=True)] == [id(a) for a in kept]
    n = pitch.GANTRY_SCORE_FRAMES
    assert [id(a) for a in score[:n]] == [id(a) for a in kept[:n]]


def test_a_shot_whose_own_gantry_is_the_match_gantry_keeps_its_own_fit(monkeypatch):
    calls = []
    own_fits = [pitch.FrameFit(view(), 0.5, 100, True), pitch.FrameFit(view(), 2.0, 100, False)]

    def fit_clip(points, w, h, anchor_every=25, gantry=None):
        calls.append(gantry)
        return GANTRY, own_fits

    monkeypatch.setattr(pitch, "fit_clip", fit_clip)
    checks, fits = pitch.fit_match_shots([np.zeros((100, 2))] * 2, W, H, [0], GANTRY)
    assert calls == [None] and fits == own_fits  # not fitted twice: the same fit
    assert checks == [pitch.ShotCheck(GANTRY, 0.0, 1, 1, False)]


def reverse_angle(twin_x: float) -> list[pitch.View]:
    """A camera in the far stand whose mirror through the centre spot is a near gantry at
    (twin_x, GANTRY's y and height): its frames draw what that twin, turned, draws."""
    far = (pitch.PITCH_X - twin_x, pitch.PITCH_Y - GANTRY[1], GANTRY[2])
    return [pitch.View(*far, p + math.pi, t, 3600.0, W, H)
            for p, t in ((0.3, 0.14), (0.0, 0.16), (-0.3, 0.15))]


@pytest.mark.usefixtures("small_grid")
def test_a_reverse_angle_beyond_the_tolerance_is_camera_unsure_and_not_ok(monkeypatch):
    # The twin stands 8 m from the match gantry along the stand. The measured tolerance is wider
    # than that (next test); here it is set under it, to test the rule itself.
    monkeypatch.setattr(pitch, "SHOT_GANTRY_M", 4.0)
    pts = [marking_pixels(v) for v in reverse_angle(GANTRY[0] - 8.0)]
    checks, fits = pitch.fit_match_shots(pts, W, H, [0], GANTRY, anchor_every=1)
    c = checks[0]
    assert c.distance_m > 4.0 and c.ok_match < c.ok_own and c.unsure
    assert not any(f.ok for f in fits)


@pytest.mark.usefixtures("small_grid")
def test_at_the_measured_tolerance_a_reverse_angle_near_halfway_is_a_known_limit():
    # Lesson 244: at the measured SHOT_GANTRY_M the same reverse angle is not marked; its frames,
    # fitted through the match gantry, are judged frame by frame as any others.
    pts = [marking_pixels(v) for v in reverse_angle(GANTRY[0] - 8.0)]
    checks, _ = pitch.fit_match_shots(pts, W, H, [0], GANTRY, anchor_every=1)
    assert checks[0].distance_m < pitch.SHOT_GANTRY_M and not checks[0].unsure


@pytest.mark.usefixtures("small_grid")
def test_a_shot_without_markings_cannot_disagree_and_its_frames_are_not_ok():
    good = [marking_pixels(v) for v in open_play()]
    none = [np.zeros((0, 2)) for _ in range(2)]
    checks, fits = pitch.fit_match_shots(good + none, W, H, [0, 3], GANTRY, anchor_every=1)
    assert checks[1] == pitch.ShotCheck(None, None, 0, 0, False)
    assert [f.ok for f in fits[3:]] == [False, False] and fits[3].view is None


class Det:
    def __init__(self, cls, bbox):
        self.cls, self.bbox, self.score = cls, bbox, 1.0


class FD:
    def __init__(self, k):
        self.frame, self.t = k, k / 25
        self.detections = (Det("player", (600.0, 300.0, 620.0, 360.0)),)


def fake_fits(monkeypatch, unsure: bool):
    fit = pitch.FrameFit(view(), 0.5, 100, True)

    def fit_shots(points, w, h, starts):
        return [GANTRY], [fit] * len(points)

    def fit_match_shots(points, w, h, starts, gantry):
        ok = not unsure
        return ([pitch.ShotCheck(GANTRY, 0.0, len(points), len(points) if ok else 0, unsure)],
                [pitch.FrameFit(fit.view, 0.5, 100, ok)] * len(points))

    monkeypatch.setattr(pitch, "fit_shots", fit_shots)
    monkeypatch.setattr(pitch, "fit_match_shots", fit_match_shots)
    monkeypatch.setattr(pitch, "line_points", lambda rgb, boxes: np.zeros((100, 2)))


def run(gantry):
    imgs = [f"{k}.jpg" for k in range(4)]
    return observe.observe(imgs, [FD(k) for k in range(4)], lambda p: np.zeros((H, W, 3), np.uint8),
                           gantry=gantry)


HEADER = ("gantry", "match_gantry", "shots")


def test_observe_through_a_one_clip_match_gantry_writes_the_same_frames(monkeypatch):
    fake_fits(monkeypatch, unsure=False)
    before, after = run(None), run(GANTRY)
    assert after[0]["match_gantry"] is True and after[0]["shots"][0]["unsure"] is False
    strip = [{k: v for k, v in r.items() if k not in HEADER} for r in after]
    assert strip == [{k: v for k, v in r.items() if k not in HEADER} for r in before]


def test_observe_holds_every_frame_of_an_unsure_shot(monkeypatch):
    fake_fits(monkeypatch, unsure=True)
    rows = run(GANTRY)
    assert all(r["camera"]["unsure"] and not r["camera"]["ok"] for r in rows)
    assert all(p["x"] is None for r in rows for p in r["players"])
    assert rows[0]["shots"][0]["unsure"] is True


@pytest.mark.parametrize("over, ok_match, unsure", [
    (0.0, 0, False),  # at the tolerance is within it
    (0.01, 0, True),  # beyond it, and the match gantry explains fewer frames
    (0.01, 2, False),  # beyond it, but a tie goes to the match gantry
])
def test_unsure_is_beyond_the_tolerance_and_explained_worse_by_the_match_gantry(monkeypatch, over,
                                                                              ok_match, unsure):
    own = (GANTRY[0] + pitch.SHOT_GANTRY_M + over, GANTRY[1], GANTRY[2])

    def fit_clip(points, w, h, anchor_every=25, gantry=None):
        n_ok = 2 if gantry is None else ok_match
        return own, [pitch.FrameFit(view(), 0.5, 100, k < n_ok) for k in range(len(points))]

    monkeypatch.setattr(pitch, "fit_clip", fit_clip)
    checks, fits = pitch.fit_match_shots([np.zeros((100, 2))] * 3, W, H, [0], GANTRY)
    assert checks[0].unsure is unsure and checks[0].ok_own == 2 and checks[0].ok_match == ok_match
    assert [f.ok for f in fits] == ([False] * 3 if unsure else [k < ok_match for k in range(3)])


def test_the_finalist_gantries_are_scored_on_the_given_frames(monkeypatch):
    # Each anchor here "prefers" a gantry by its size; the top anchors by markings prefer x = 37.5,
    # the given scoring frames x = 67.5. The winner must be the scoring frames' choice.
    monkeypatch.setattr(pitch, "GANTRY_X", (37.5, 67.5))
    monkeypatch.setattr(pitch, "GANTRY_BACK", (30.0,))
    monkeypatch.setattr(pitch, "GANTRY_DOWN_DEG", (22.0,))
    monkeypatch.setattr(pitch, "search", lambda a, w, h, gantry=None, keep=1: [view(gantry=gantry)])
    monkeypatch.setattr(pitch, "cost", lambda v, a: abs(v.cx - (67.5 if len(a) < 100 else 37.5)))
    monkeypatch.setattr(pitch, "_median", lambda v, a: math.inf)  # no joint refine: the winner itself
    top = [np.zeros((n, 2)) for n in (300, 250, 200, 150, 120)]
    given = [np.zeros((n, 2)) for n in (90, 80)]
    assert pitch.find_gantry(top + given, W, H)[0] == 37.5
    assert pitch.find_gantry(top + given, W, H, score=given)[0] == 67.5
