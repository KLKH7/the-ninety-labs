import math

from ninety.render.camera import Camera
from ninety.render.scene import (
    BALL_RADIUS,
    KEYPOINTS,
    OCCLUDER_HEIGHT_M,
    OCCLUDER_RADIUS_M,
    Gait,
    Look,
    _stride,
    ball_hidden,
    body_parts,
    crowded_start,
    drawn_ball,
    parts_box,
    project_keypoints,
    sample_looks,
    turn_toward,
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


def test_a_press_lifts_the_foot_and_a_turn_does_not_snap():
    jog = body_parts(0, 0, LOOK, Gait(action="walk", speed=3.0, phase=3 * math.pi / 2))
    stroll = body_parts(0, 0, LOOK, Gait(action="walk", speed=1.0, phase=3 * math.pi / 2))
    ankle = lambda ps: next(p for p in ps if p["n"] == "shin_l")["b"][2]  # noqa: E731
    assert ankle(jog) > ankle(stroll) + 0.05
    turned = turn_toward(0.0, 2.0, 1 / 25)
    assert 0 < turned < 0.3


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


def test_the_ball_is_drawn_where_the_engine_has_it_even_at_a_carriers_feet():
    fr = {"ball": {"x": 50.0, "y": 30.0, "z": 0.0}, "possessor": "h1"}
    assert drawn_ball(fr) == (50.0, 30.0, 0.0)
    fr["possessor"] = None
    assert drawn_ball(fr) == (50.0, 30.0, 0.0)


def test_a_throw_lifts_both_hands_over_the_head():
    parts = body_parts(0, 0, LOOK, Gait(action="throw", heading=math.pi / 2))
    head = next(p for p in parts if p["n"] == "head")["a"][2]
    hands = [p["b"] for p in parts if p["n"].startswith("forearm")]
    assert len(hands) == 2
    assert all(h[2] > head + 0.15 for h in hands)
    assert all(h[1] > 0.15 for h in hands)  # toward the pitch


def test_a_strike_raises_the_foot_toward_the_ball():
    g = Gait(action="strike", heading=0.0)
    parts = body_parts(0, 0, LOOK, g, (1.0, 0.4))
    foot = next(p for p in parts if p["n"] == "boot_l")["b"]
    other = next(p for p in parts if p["n"] == "boot_r")["b"]
    assert foot[2] > other[2] + 0.15
    assert foot[0] > 0.3


def test_a_dive_reaches_sideways_and_keeps_the_feet_down():
    standing = body_parts(0, 0, LOOK, Gait())
    diving = body_parts(0, 0, LOOK, Gait(action="dive", dive=1.0, heading=0.0))
    head = lambda ps: next(p for p in ps if p["n"] == "head")["a"]  # noqa: E731
    assert head(diving)[1] > head(standing)[1] + 0.3
    lows = [p[k][2] - p["r"] for p in diving for k in ("a", "b") if k in p]
    assert min(lows) >= -0.01


def test_the_drawn_ball_is_the_engine_ball():
    fr = {"ball": {"x": 50.0, "y": 30.0, "z": 0.4}, "possessor": "h1"}
    assert drawn_ball(fr, 0.0) == (50.0, 30.0, 0.4)


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


GANTRY = (52.5, -35.0, 20.0)


def test_a_player_between_the_lens_and_the_ball_hides_it():
    ball = (52.5, 30.0, 0.0)
    # 2 m in front of the ball, on the line: the sight line passes him at about 1.2 m.
    assert ball_hidden(GANTRY, ball, [(52.5, 28.0)])
    # The same distance behind the ball, beside it, or past the lens: nothing hidden.
    assert not ball_hidden(GANTRY, ball, [(52.5, 32.0)])
    assert not ball_hidden(GANTRY, ball, [(52.5 + OCCLUDER_RADIUS_M + 0.05, 28.0)])
    assert not ball_hidden(GANTRY, ball, [(52.5, -40.0)])


def test_the_sight_line_passes_over_a_player_far_in_front():
    ball = (52.5, 30.0, 0.0)
    # The line rises from the ball's centre (0.11 m) to the lens 65 m away; it clears a
    # 1.81 m player who stands more than about 5.6 m in front of the ball.
    clear = 65.0 * (OCCLUDER_HEIGHT_M - 0.11) / (GANTRY[2] - 0.11)
    assert ball_hidden(GANTRY, ball, [(52.5, 30.0 - clear + 0.3)])
    assert not ball_hidden(GANTRY, ball, [(52.5, 30.0 - clear - 0.3)])


def test_a_ball_in_the_air_above_a_player_is_not_hidden_by_him():
    assert not ball_hidden(GANTRY, (52.5, 30.0, 3.0), [(52.5, 29.5)])


def _frames(windows: list[list[tuple[float, float]]], n: int) -> list[dict]:
    """n frames per window, the ball at (52.5, 30) and players fixed where each window puts them."""
    out = []
    for players in windows:
        for _ in range(n):
            out.append(
                {
                    "ball": {"x": 52.5, "y": 30.0, "z": 0.0},
                    "players": [{"x": x, "y": y} for x, y in players],
                }
            )
    return out


def test_the_crowded_window_is_the_one_where_the_ball_is_hidden():
    n = 50
    # First window: six players round the ball, all on the far side of it, so nothing is
    # hidden. Second: one player on the sight line. Counting players near the ball picks the
    # first; occlusion is the second.
    far_side = [(52.5 + dx, 31.5 + dy) for dx in (-1.0, 0.0, 1.0) for dy in (0.0, 1.0)]
    one_in_line = [(52.5, 28.5)]
    frames = _frames([far_side, one_in_line], n)
    cams = [GANTRY] * len(frames)
    assert crowded_start(frames, n, 0, n, cams, step=n) == n


def test_players_near_the_ball_break_a_tie_in_occlusion():
    n = 50
    frames = _frames([[(52.5, 34.0)], [(52.5, 31.0), (53.0, 31.0), (52.0, 31.0)]], n)
    cams = [GANTRY] * len(frames)
    assert crowded_start(frames, n, 0, n, cams, step=n) == n


def test_crowded_window_on_a_simulated_match_hides_the_ball_more_than_average():
    m = simulate(8, 3)
    n = 100
    cams = [GANTRY] * len(m.frames)
    s = crowded_start(m.frames, n, 50, len(m.frames) - n - 1, cams)

    def hidden(f):
        b = f["ball"]
        return ball_hidden(GANTRY, (b["x"], b["y"], b["z"]), [(p["x"], p["y"]) for p in f["players"]])

    window = sum(hidden(f) for f in m.frames[s : s + n]) / n
    overall = sum(hidden(f) for f in m.frames) / len(m.frames)
    assert window > overall


def test_ball_radius_is_regulation():
    assert 0.105 <= BALL_RADIUS <= 0.112


def test_a_jog_and_a_sprint_take_human_steps():
    jog = 3.0 / (_stride(3.0) / 2)
    sprint = 7.0 / (_stride(7.0) / 2)
    assert 2.4 < jog < 3.1
    assert 4.0 < sprint < 4.8


def test_the_stance_foot_stays_put_while_the_body_moves():
    g = Gait(action="run", speed=3.0, heading=0.0)
    x = 0.0
    held = []
    for _ in range(12):
        update_gait(g, 3.0 / 25, 0.0, 1 / 25, None)
        g.speed = 3.0
        g.action = "run"
        x += 3.0 / 25
        parts = body_parts(x, 0.0, LOOK, g)
        boots = {p["n"]: p["b"] for p in parts if p["n"].startswith("boot")}
        held.append(boots)
    # A foot that is down repeats its world position across frames.
    stuck = 0
    for i in range(1, len(held)):
        for name in ("boot_l", "boot_r"):
            if math.dist(held[i][name], held[i - 1][name]) < 0.03:
                stuck += 1
    assert stuck >= 3


def test_a_foot_control_reaches_toward_the_ball():
    parts = body_parts(0, 0, LOOK, Gait(action="foot", heading=0.0), (0.7, 0.3, 0.05))
    left = next(p for p in parts if p["n"] == "boot_l")["b"]
    right = next(p for p in parts if p["n"] == "boot_r")["b"]
    assert math.dist(left[:2], (0.7, 0.3)) < math.dist(right[:2], (0.7, 0.3))
    assert left[0] > 0.25


def test_a_chest_control_opens_the_body_toward_the_ball():
    standing = body_parts(0, 0, LOOK, Gait())
    parts = body_parts(0, 0, LOOK, Gait(action="chest", heading=0.0), (0.4, 0.0, 1.2))
    hands = [p["b"][2] for p in parts if p["n"].startswith("forearm")]
    base = [p["b"][2] for p in standing if p["n"].startswith("forearm")]
    assert sum(hands) > sum(base) + 0.2
    torso = next(p for p in parts if p["n"] == "torso")
    assert torso["b"][0] < 0


def test_a_header_moves_the_head_toward_the_ball():
    standing = body_parts(0, 0, LOOK, Gait(heading=0.0))
    parts = body_parts(0, 0, LOOK, Gait(action="head", heading=0.0), (0.3, 0.1, 1.5))
    head = next(p for p in parts if p["n"] == "head")["a"]
    base = next(p for p in standing if p["n"] == "head")["a"]
    ball = (0.3, 0.1, 1.5 + BALL_RADIUS)
    assert math.dist(head, ball) < math.dist(base, ball)
