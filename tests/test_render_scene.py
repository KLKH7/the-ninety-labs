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
    ball_live,
    body_parts,
    crowded_start,
    drawn_ball,
    in_penalty_area,
    keeper_busy,
    keeper_start,
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
    g = Gait(action="run")  # the engine's pose above 4 m/s; "stand" is drawn standing
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


def test_a_strike_raises_the_labelled_foot_where_the_touch_aims_it():
    """The label's kicking leg goes where the drawn one does: the touch's aim (scene.touch_at). A
    strike pose with no touch is drawn in stride (meshpose._upper), so the touch is what lifts it."""
    g = Gait(action="strike", heading=0.0)
    g.touch = {"part": "strike", "side": "l", "at": [0.45, 0.3, 0.3], "w": 1.0}
    parts = body_parts(0, 0, LOOK, g, (1.0, 0.4))
    foot = next(p for p in parts if p["n"] == "boot_l")["a"]
    other = next(p for p in parts if p["n"] == "boot_r")["a"]
    assert foot[2] > other[2] + 0.15
    assert math.dist(foot, (0.45 - 0.08, 0.3, 0.33)) < 0.02


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
    # Hair shape is a second draw. These four fields are the looks-1 stream and must not move.
    assert [(lk.id, lk.height_m, lk.build, lk.skin, lk.hair) for lk in a] == [
        ("h1", 1.826, 1.048, "#8d5a3b", "#2b2b2b"),
        ("h2", 1.839, 1.139, "#b07850", "#2b2b2b"),
        ("h3", 1.737, 0.967, "#8d5a3b", "#6b4a2b"),
        ("h4", 1.853, 1.122, "#6b4329", "#a37a4c"),
        ("h5", 1.696, 1.008, "#f5d0b5", "#3b2516"),
        ("h6", 1.671, 1.028, "#b07850", "#3b2516"),
        ("h7", 1.781, 0.994, "#8d5a3b", "#3b2516"),
        ("h8", 1.795, 0.978, "#d19a74", "#3b2516"),
        ("h9", 1.783, 1.1, "#8d5a3b", "#6b4a2b"),
        ("h10", 1.917, 1.045, "#4a2e1d", "#6b4a2b"),
        ("h11", 1.772, 0.936, "#f5d0b5", "#a37a4c"),
        ("a1", 1.844, 1.086, "#e8b897", "#6b4a2b"),
        ("a2", 1.746, 1.052, "#8d5a3b", "#8a3b1d"),
        ("a3", 1.892, 1.106, "#d19a74", "#a37a4c"),
        ("a4", 1.808, 1.115, "#6b4329", "#1b1410"),
        ("a5", 1.701, 1.103, "#e8b897", "#d9c08c"),
        ("a6", 1.787, 1.114, "#e8b897", "#1b1410"),
        ("a7", 1.86, 1.118, "#b07850", "#3b2516"),
        ("a8", 1.806, 0.913, "#f5d0b5", "#3b2516"),
        ("a9", 1.74, 0.984, "#8d5a3b", "#d9c08c"),
        ("a10", 1.743, 1.052, "#4a2e1d", "#1b1410"),
        ("a11", 1.816, 0.958, "#d19a74", "#a37a4c"),
    ]
    assert {lk.hair_style for lk in a} == {"bald", "short", "crown"}


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


def _frames(windows: list[list[tuple[float, float]]], n: int, possessor: str | None = "h9") -> list[dict]:
    """n frames per window, the ball at (52.5, 30) held by `possessor` (None: a still, dead ball),
    and players fixed where each window puts them."""
    out = []
    for players in windows:
        for _ in range(n):
            out.append(
                {
                    "ball": {"x": 52.5, "y": 30.0, "z": 0.0},
                    "possessor": possessor,
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


def test_a_player_beside_a_dead_ball_is_not_a_crowded_window():
    n = 50
    # First window: a free-kick wait, a player on the sight line beside a still ball nobody has.
    # Second: the ball in play, hidden for fewer frames. The live window wins.
    dead = _frames([[(52.5, 28.5)]], n, possessor=None)
    live = _frames([[(52.5, 28.5)]], n // 5) + _frames([[(60.0, 40.0)]], n - n // 5)
    cams = [GANTRY] * (2 * n)
    assert crowded_start(dead + live, n, 0, n, cams, step=n) == n


def test_a_ball_is_live_when_held_or_moving_and_on_the_pitch():
    still = {"ball": {"x": 52.5, "y": 30.0, "z": 0.0}, "possessor": None}
    held = {**still, "possessor": "h9"}
    rolled = {"ball": {"x": 52.6, "y": 30.0, "z": 0.0}, "possessor": None}
    off = {"ball": {"x": 106.0, "y": 30.0, "z": 0.0}, "possessor": "h9"}
    assert not ball_live(still, still)
    assert ball_live(still, held)
    assert ball_live(still, rolled)
    assert not ball_live(held, off)
    assert not ball_live(held, {"ball": {"x": 52.5, "y": -0.1, "z": 0.0}, "possessor": "h9"})


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


def _keeper_frames(windows: list[tuple[str, tuple[float, float]]], n: int) -> list[dict]:
    """n frames per window: the home keeper's action and where the ball is."""
    return [
        {"ball": {"x": bx, "y": by, "z": 0.0},
         "players": [{"id": "h1", "role": "GK", "x": 2.0, "y": 34.0, "action": action},
                     {"id": "h5", "role": "LB", "x": 20.0, "y": 50.0, "action": "foot"}]}
        for action, (bx, by) in windows
        for _ in range(n)
    ]


def test_the_keeper_window_is_the_one_where_a_keeper_handles_or_dives():
    n = 50
    # First window: the ball in the box but the keeper only stands. Second: he dives.
    frames = _keeper_frames([("stand", (8.0, 34.0)), ("dive", (60.0, 34.0))], n)
    assert keeper_start(frames, n, 0, n, step=n) == n
    # An outfield player's touch is not a keeper's.
    frames = _keeper_frames([("stand", (60.0, 34.0)), ("stand", (8.0, 34.0))], n)
    frames[10]["players"][1]["action"] = "hands"
    assert keeper_start(frames, n, 0, n, step=n) == n


def test_with_no_keeper_action_the_ball_in_a_penalty_area_decides():
    n = 50
    frames = _keeper_frames([("stand", (52.5, 34.0)), ("stand", (95.0, 40.0))], n)
    assert keeper_start(frames, n, 0, n, step=n) == n


def test_the_penalty_area_is_law_one_size():
    assert in_penalty_area({"x": 16.5, "y": 34.0 + 20.16})
    assert not in_penalty_area({"x": 16.6, "y": 34.0})
    assert not in_penalty_area({"x": 5.0, "y": 34.0 + 20.2})
    assert in_penalty_area({"x": 105.0 - 16.5, "y": 34.0 - 20.16})


def test_keeper_window_on_a_simulated_match_is_busier_than_average():
    m = simulate(8, 3)
    n = 100
    s = keeper_start(m.frames, n, 50, len(m.frames) - n - 1)
    window = sum(keeper_busy(f) for f in m.frames[s : s + n]) / n
    overall = sum(keeper_busy(f) for f in m.frames) / len(m.frames)
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
    g = Gait(action="foot", heading=0.0)
    g.touch = {"part": "foot", "side": "l", "at": [0.6, 0.3, 0.05], "w": 1.0}
    parts = body_parts(0, 0, LOOK, g, (0.7, 0.3, 0.05))
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


def test_occlusion_keeper_chooses_the_keeper_window():
    from ninety.render.clip import WARMUP, choose_start
    from ninety.render.params import sample_params

    m = simulate(8, 5)
    p = sample_params(8, occlusion="keeper")
    n = 250
    start = choose_start(m.frames, p, n, 8, 10.0, 240.0)
    assert start == keeper_start(m.frames, n, max(250, WARMUP), 240 * 25)
