import math

from ninety.render.camera import Camera
from ninety.render.scene import (
    BALL_RADIUS,
    KEYPOINTS,
    Gait,
    Look,
    body_parts,
    crowded_start,
    crowding,
    drawn_ball,
    parts_box,
    project_keypoints,
    sample_looks,
    update_gait,
)
from ninety.sim.engine import simulate

LOOK = Look("h1", "home", "CM", 1.84, 1.0, "#d19a74", "#1b1410")


def test_body_stands_on_the_pitch_and_is_as_tall_as_the_player():
    parts = body_parts(30.0, 20.0, LOOK, Gait())
    lows = [p[k][2] - p["r"] for p in parts for k in ("a", "b") if k in p]
    highs = [p[k][2] + p["r"] for p in parts for k in ("a", "b") if k in p]
    assert min(lows) >= -0.01
    assert abs(max(highs) - 1.84) < 0.08
    assert all(abs(p["a"][0] - 30) < 0.6 and abs(p["a"][1] - 20) < 0.6 for p in parts)


def test_running_swings_the_legs():
    g = Gait()
    for _ in range(10):
        update_gait(g, 0.28, 0.0, 0.04, None)  # 7 m/s along +x
    g.phase = math.pi / 2
    a = body_parts(0, 0, LOOK, g)
    g.phase = 3 * math.pi / 2
    b = body_parts(0, 0, LOOK, g)
    shin = lambda ps: next(p for p in ps if p["n"] == "shin_l")["b"]  # noqa: E731
    assert math.dist(shin(a), shin(b)) > 0.4  # the foot goes from front to back
    assert abs(g.heading) < 0.05


def test_parts_box_contains_the_projected_feet_and_head():
    cam = Camera((52.5, -35.0, 20.0), (40.0, 30.0, 0.0), 20.0, 1280, 720)
    parts = body_parts(40.0, 30.0, LOOK, Gait())
    x0, y0, x1, y1 = parts_box(cam, parts)
    u, v = cam.project((40.0, 30.0, 0.0))
    assert x0 <= u <= x1 and abs(v - y1) < 4
    assert 40 < y1 - y0 < 130


def test_dribbled_ball_is_drawn_ahead_of_the_feet():
    fr = {"ball": {"x": 50.0, "y": 30.0, "z": 0.0}, "possessor": "h1"}
    x, y, z = drawn_ball(fr, 0.0)
    assert x > 50.0 and y == 30.0
    fr["possessor"] = None
    assert drawn_ball(fr, 0.0) == (50.0, 30.0, 0.0)


def test_keypoints_cover_the_markings_and_project_exactly():
    names = {n for n, _, _ in KEYPOINTS}
    assert {"centre", "spot_l", "spot_r", "corner_fr", "box_l_edge_far"} <= names
    assert len(names) == len(KEYPOINTS)
    cam = Camera((52.5, -35.0, 20.0), (52.5, 34.0, 0.0), 28.0, 1280, 720)
    kps = project_keypoints(cam)
    assert any(k["name"] == "centre" for k in kps)
    for k in kps:
        assert 0 <= k["px"] < 1280 and 0 <= k["py"] < 720


def test_looks_are_seeded_and_varied():
    m = simulate(1, 0.05)
    a, b = sample_looks(m.frames[0]["players"], 1), sample_looks(m.frames[0]["players"], 1)
    assert a == b
    assert len({lk.skin for lk in a}) > 2 and len({lk.height_m for lk in a}) > 10
    assert all(1.65 <= lk.height_m <= 1.98 for lk in a)


def test_crowded_window_has_more_players_near_the_ball():
    m = simulate(8, 3)
    n = 100
    s = crowded_start(m.frames, n, 50, len(m.frames) - n - 1)
    mean = lambda a: sum(crowding(f) for f in m.frames[a : a + n]) / n  # noqa: E731
    overall = sum(crowding(f) for f in m.frames) / len(m.frames)
    assert mean(s) >= overall


def test_ball_radius_is_regulation():
    assert 0.105 <= BALL_RADIUS <= 0.112
