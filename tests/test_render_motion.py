"""How the mesh turns and touches the ball, measured on the skinned body's own markers.

A turn on the spot is steps, not a figurine spun on its base: a foot on the grass stays put
while the hips turn over it, and moves only lifted, one foot at a time. A touch puts the
touching part on the ball on the frame the engine says it met it; a kick gets there with a swing
of the leg. Arms hang standing and swing opposite the legs moving; a keeper holding the ball has
his hands on it.
"""

import math

import pytest

from ninety.render.camera import Camera
from ninety.render.meshpose import (
    ASSET_STATURE_M,
    HOLD_SIDE,
    _bone_index,
    _fk,
    foot_yaw,
    pose_angles,
    pose_markers,
    to_world,
)
from ninety.render.scene import (
    BALL_RADIUS,
    KICK_SWING_S,
    LEAD_AHEAD_FRAMES,
    LEAD_MAX,
    PLANT_AHEAD_MAX,
    PUMP,
    RUN_BOB,
    STEP_FRAMES,
    STEP_LIFT,
    THROW_FOLLOW_S,
    WALK_BOB,
    Gait,
    Look,
    _step_m,
    _table,
    advance_gaits,
    body_parts,
    contacts,
    hold_at,
    holds,
    mesh_pose,
    pace,
    parts_box,
    reach_sign,
    throw_at,
    throws,
    touch_at,
)

LOOK = Look("h1", "home", "CM", 1.84, 1.0, "#c68642", "#1b1410")
FPS = 25
TURN_RATE = 0.24  # rad a frame: the engine's cap, 350 degrees a second (GROUNDING P16)


def _wrap(a):
    return (a + math.pi) % (2 * math.pi) - math.pi


def _turn_on_the_spot(total: float, hold: int = 20):
    """Headings of a player standing at one spot turning `total` radians at the engine's rate."""
    n = int(abs(total) / TURN_RATE) + 1
    hs = [0.0] * 10 + [math.copysign(min(i * TURN_RATE, abs(total)), total) for i in range(1, n + 1)]
    return hs + [hs[-1]] * hold


def _drawn(headings, x=40.0, y=30.0, action="stand", speed=0.0):
    """Feet markers frame by frame, as clip.py poses the mesh (lead from the engine's later heading)."""
    g = Gait(action=action, speed=speed)
    out = []
    for i, h in enumerate(headings):
        g.heading = h
        later = headings[min(i + LEAD_AHEAD_FRAMES, len(headings) - 1)]
        g.lead = max(-LEAD_MAX, min(LEAD_MAX, _wrap(later - h)))
        body_parts(x, y, LOOK, g)
        pose = mesh_pose(g, x, y, 0.0)
        out.append((pose, pose_markers(pose, h, LOOK.height_m)))
    return out


def test_a_turn_on_the_spot_steps_instead_of_spinning_the_feet():
    """Old: both feet swung round with the body, 5 cm a frame across the grass, every frame."""
    for total in (math.pi, -math.pi / 2, 2.5):
        frames = _drawn(_turn_on_the_spot(total))
        still_frames = 0
        for (_, a), (_, b) in zip(frames, frames[1:], strict=False):
            moved = {s: math.dist(a[f"foot_{s}"][:2], b[f"foot_{s}"][:2]) for s in "lr"}
            for s in "lr":
                on_grass = a[f"foot_{s}"][2] < 0.03 and b[f"foot_{s}"][2] < 0.03
                if on_grass:
                    # A foot on the grass does not slide; it moves only lifted (a step).
                    assert moved[s] < 0.02, (total, s, moved[s])
            # One foot at a time: there is always a foot on the grass that did not move.
            assert min(moved.values()) < 0.02, (total, moved)
            still_frames += 1
        # And he does end up standing the new way: both feet point within 15 degrees of it.
        pose, _ = frames[-1]
        for s in "lr":
            assert abs(_wrap(foot_yaw(pose, pose["lead"] + total, 1.84, s) - total)) < 0.26, (total, s)
        assert still_frames > 20


def test_a_turn_lifts_the_stepping_foot_and_turns_at_most_one_foot_at_a_time():
    frames = _drawn(_turn_on_the_spot(math.pi))
    lifted = [(p["plant_l"][3] > 0.005, p["plant_r"][3] > 0.005) for p, _ in frames]
    assert any(left for left, _ in lifted) and any(right for _, right in lifted)  # both feet stepped
    assert not any(left and right for left, right in lifted)  # never both off the grass


def test_the_hips_lead_a_turn_and_the_chest_stays_on_the_engine_heading():
    """Hips (and the feet under them) turn ahead; the chest is the body the engine collides with."""
    base = {"action": "stand", "speed": 0.0, "x": 0.0, "y": 0.0}
    still = pose_markers(base, 0.0, 1.84)
    led = pose_markers({**base, "lead": 0.35}, 0.0, 1.84)
    assert math.dist(still["chest"], led["chest"]) < 0.02  # the chest stays where the engine faces
    assert math.dist(still["head"], led["head"]) < 0.02
    for s in "lr":
        assert abs(foot_yaw({**base, "lead": 0.35}, 0.0, 1.84, s) - 0.35) < 0.1


def test_a_planted_foot_keeps_pointing_the_way_it_landed_while_the_hips_turn():
    base = {"action": "stand", "speed": 0.0, "x": 0.0, "y": 0.0}
    m = pose_markers(base, 0.0, 1.84)
    plant = [m["foot_l"][0], m["foot_l"][1], 0.0, 0.0]
    for heading in (0.2, 0.4, -0.4):
        pose = {**base, "plant_l": plant}
        assert abs(foot_yaw(pose, heading, 1.84, "l")) < 0.12, heading
        foot = pose_markers(pose, heading, 1.84)["foot_l"]
        assert math.dist(foot[:2], plant[:2]) < 0.03, heading


def test_a_run_lands_its_foot_where_the_leg_reaches():
    """Old: a touchdown up to 0.58 m ahead, which the leg could not reach, so the foot slid onto it.
    A landing is a foot coming down out of its swing (scene._stride_feet); the stride's phase moves
    with the ground covered."""
    k = LOOK.height_m / ASSET_STATURE_M
    for speed in (2.5, 4.0, 6.0, 8.0):
        g = Gait(action="run", speed=speed)
        x = 0.0
        landed = 0
        for _ in range(60):  # 2.4 s: at 2.5 m/s two strides hold only four landings
            g.phase = (g.phase + 2 * math.pi * speed / FPS / (2 * _step_m(speed))) % (2 * math.pi)
            x += speed / FPS
            before = (g.down_l, g.down_r)
            body_parts(x, 0.0, LOOK, g)
            pose = mesh_pose(g, x, 0.0, 0.0)
            feet = pose_markers(pose, 0.0, LOOK.height_m)
            sides = (("l", before[0], g.down_l, g.plant_l), ("r", before[1], g.down_r, g.plant_r))
            for s, was, now, plant in sides:
                if now and not was:
                    landed += 1
                    # within the plant's rounding (0.1 mm, scene._feet)
                    assert plant[0] - x <= PLANT_AHEAD_MAX * k + 5e-5, (speed, s, plant[0] - x)
                    assert math.dist(feet[f"foot_{s}"][:2], plant[:2]) < 0.03, (speed, s)
        assert landed > 4


def _kick(ball_xy, part="strike", before=4, after=8, out=(15.0, 0.0), ball_z=0.0):
    """Engine-shaped frames: a player standing at (50, 30) facing +x; the ball still at `ball_xy`
    until the touch, then leaving at `out` m/s. A strike is its wind-up frames; a touch names its
    part from the frame it happened."""
    frames = []
    bx, by = ball_xy
    for i in range(before + after):
        struck = i >= before
        pose = ("strike" if not struck else "stand") if part == "strike" else (part if struck else "stand")
        t = (i - before + 1) / FPS if struck else 0.0
        ball = {"x": bx + out[0] * t, "y": by + out[1] * t, "z": ball_z,
                "vx": out[0] if struck else 0.0, "vy": out[1] if struck else 0.0}
        frames.append({"ball": ball, "players": [{"id": "h1", "x": 50.0, "y": 30.0, "vx": 0.0, "vy": 0.0,
                                                  "heading": 0.0, "action": pose, "dive": 0.0}]})
    return frames


def _drawn_touch(frames):
    g = Gait()
    mine = contacts(frames).get("h1", [])
    out = []
    for fi, fr in enumerate(frames):
        pl = fr["players"][0]
        g.heading, g.action, g.speed = pl["heading"], pl["action"], 0.0
        touch_at(g, mine, fi, LOOK.height_m, FPS, pl["x"], pl["y"])
        b = fr["ball"]
        ball = (b["x"], b["y"], b["z"])
        body_parts(pl["x"], pl["y"], LOOK, g, ball)
        pose = mesh_pose(g, pl["x"], pl["y"], reach_sign(pl["x"], pl["y"], g, ball))
        out.append((pose, pose_markers(pose, g.heading, LOOK.height_m), ball))
    return mine, out


def test_the_kicking_foot_meets_the_ball_on_the_contact_frame():
    """Old: the stored strike pose, wherever the ball was: its foot ended 0.3 to 0.5 m off it."""
    for ball_xy, foot in (((50.45, 29.85), "foot_r"), ((50.40, 30.18), "foot_l"), ((50.25, 29.80), "foot_r")):
        mine, drawn = _drawn_touch(_kick(ball_xy))
        assert len(mine) == 1 and mine[0]["part"] == "strike"
        c = mine[0]["frame"]
        pose, markers, ball = drawn[c]
        centre = (ball[0], ball[1], ball[2] + BALL_RADIUS)
        assert math.dist(markers[foot], centre) < BALL_RADIUS + 0.08, (ball_xy, markers[foot], centre)
        # The swing comes through the ball: the foot is drawn back over the wind-up ...
        assert math.dist(drawn[c - 3][1][foot], centre) > math.dist(markers[foot], centre) + 0.05
        # ... and follows through the way the ball went.
        assert drawn[c + 2][1][foot][0] > markers[foot][0] + 0.05


def test_a_received_ball_meets_the_foot_thigh_chest_or_head_that_the_engine_named():
    cases = [
        ("foot", (50.4, 29.9), 0.0, "foot_r", (2.0, 0.0)),
        # A thigh reaches about 0.3 m ahead of the hip at its height, standing on the other leg.
        ("thigh", (50.25, 29.95), 0.55, "thigh_top_r", (1.0, 0.0)),
        ("chest", (50.3, 30.0), 1.2, "chest", (1.0, 0.0)),
        ("head", (50.25, 30.0), 1.6, "brow", (-6.0, 0.0)),
    ]
    for part, ball_xy, z, marker, out in cases:
        mine, drawn = _drawn_touch(_kick(ball_xy, part=part, ball_z=z, out=out))
        assert len(mine) == 1 and mine[0]["part"] == part
        c = mine[0]["frame"]
        _, markers, _ = drawn[c]
        # The touch happened inside the tick before this frame, where the ball passed closest to
        # him: from where it lay the frame before (ball_xy) toward where it is now.
        centre = (ball_xy[0], ball_xy[1], z + BALL_RADIUS)
        assert math.dist(markers[marker], centre) < BALL_RADIUS + 0.1, (part, markers[marker], centre)


def test_a_header_above_his_reach_is_drawn_as_a_jump_and_lands():
    mine, drawn = _drawn_touch(_kick((50.2, 30.0), part="head", ball_z=2.0, out=(-8.0, 0.0)))
    c = mine[0]["frame"]
    pose, markers, _ = drawn[c]
    assert pose["lift"] > 0.1
    assert math.dist(markers["brow"], (50.2, 30.0, 2.0 + BALL_RADIUS)) < BALL_RADIUS + 0.1
    assert drawn[-1][0]["lift"] == 0.0


def test_a_ball_at_the_engines_full_reach_is_met_with_a_lunge_on_a_planted_foot():
    """The engine's foot meets a ball up to 1 m from his centre (P14); a standing leg reaches about
    0.45 m. Old: the stored pose, 0.6 m off it. Now the hips drop and the leg stretches to it,
    and the other foot stays on the grass."""
    mine, drawn = _drawn_touch(_kick((50.2, 29.05), part="foot", out=(3.0, 0.0), after=16))
    c = mine[0]["frame"]
    pose, markers, _ = drawn[c]
    assert pose["lift"] < -0.1
    contact = (50.2, 29.05, BALL_RADIUS)
    # At the deepest lunge the sole reaches about 0.76 m from his centre; the ball's centre is
    # 0.95 m out, so the boot touches it with the sole about 0.3 m from that centre.
    assert math.dist(markers["foot_r"], contact) < 0.33, markers["foot_r"]
    assert markers["foot_r"][2] > -0.005  # stretched, not through the grass
    assert markers["foot_l"][2] < 0.05  # the support foot is still on the grass
    assert drawn[-1][0]["lift"] == 0.0


def _forward(m, name, heading=0.0, x=0.0, y=0.0):
    """How far a marker is ahead of the body's centre, along the way he faces."""
    return (m[name][0] - x) * math.cos(heading) + (m[name][1] - y) * math.sin(heading)


def test_standing_arms_hang_by_his_sides():
    """Old: both forearms held out in front, the hands 0.33 m ahead of him at 0.99 m, whatever the
    action. Standing, a hand hangs below the wrist's standing height (0.485 of stature, Drillis and
    Contini 1966, so 0.89 m for 1.84 m) and close to the side of the thigh."""
    m = pose_markers({"action": "stand", "x": 0.0, "y": 0.0}, 0.0, 1.84)
    for s in "lr":
        assert m[f"hand_{s}"][2] < 0.485 * 1.84, (s, m[f"hand_{s}"])
        assert abs(_forward(m, f"hand_{s}")) < 0.15, (s, m[f"hand_{s}"])


def test_arms_swing_opposite_the_legs_walking_and_running():
    """Each hand comes forward as the other side's foot does, and goes back past the hips (old: the
    hands stayed 0.16 to 0.46 m in front all the way round a run). Walking, the elbows stay nearly
    straight, so the hands stay below the wrist's standing height (old: 1.0 m and out in front)."""
    for action, speed, swing in (("walk", 1.3, 0.15), ("run", 5.5, 0.35)):
        hands, feet = {"l": [], "r": []}, {"l": [], "r": []}
        for i in range(16):
            pose = {"action": action, "speed": speed, "phase": i * 2 * math.pi / 16, "x": 0.0, "y": 0.0}
            m = pose_markers(pose, 0.0, 1.84)
            for s in "lr":
                hands[s].append(_forward(m, f"hand_{s}"))
                feet[s].append(_forward(m, f"foot_{s}"))
                if action == "walk":
                    assert m[f"hand_{s}"][2] < 0.485 * 1.84, (action, i, s, m[f"hand_{s}"])
        for s in "lr":
            h, f = hands[s], feet[s]
            mh, mf = sum(h) / len(h), sum(f) / len(f)
            cov = sum((a - mh) * (b - mf) for a, b in zip(h, f, strict=True))
            norm = math.sqrt(sum((a - mh) ** 2 for a in h) * sum((b - mf) ** 2 for b in f))
            assert cov / norm < -0.9, (action, s, cov / norm)  # the hand moves against its own foot
            assert max(h) - min(h) > swing, (action, s, max(h) - min(h))
            assert min(h) < 0.0, (action, s, min(h))  # and goes back past the hips


def test_a_kick_swings_the_leg_back_behind_him_and_through_the_ball():
    """Old (#146): the foot was eased toward the ball from at most 0.4 m behind it, so a pass from
    the feet looked like standing still with the ball between the feet. Now the foot is drawn back
    and up behind the hips, swings through to meet the ball on the contact frame, and follows on;
    the arm on the other side goes out for balance."""
    for ball_xy, foot, out in (((50.45, 29.85), "foot_r", 12.0), ((50.40, 30.18), "foot_l", 24.0)):
        mine, drawn = _drawn_touch(_kick(ball_xy, before=12, after=14, out=(out, 0.0)))
        c = mine[0]["frame"]
        top = c - round(KICK_SWING_S * FPS)
        _, m, _ = drawn[top]
        assert m[foot][0] < 50.0 - 0.15, (out, m[foot])  # behind his hips (he stands at x = 50)
        assert m[foot][2] > 0.25, (out, m[foot])  # and up off the grass
        pose, markers, ball = drawn[c]
        centre = (ball[0], ball[1], ball[2] + BALL_RADIUS)
        assert math.dist(markers[foot], centre) < BALL_RADIUS + 0.08, (out, markers[foot], centre)
        assert drawn[c + 3][1][foot][0] > markers[foot][0] + 0.15  # it follows through
        assert drawn[c + 3][1][foot][2] > markers[foot][2] + 0.1  # rising
        far = "hand_l" if foot == "foot_r" else "hand_r"
        assert abs(markers[far][1] - 30.0) > 0.4, (out, markers[far])


def test_a_lunge_goes_down_and_comes_back_up_over_several_frames():
    """Old (#146): the hips dropped 0.24 m into the lunge in two frames and snapped back up in two
    (12 to 15 cm a frame, 3 to 3.75 m/s). Now they sink and rise over TOUCH_RECOVER_S each way: no
    frame moves them more than 7 cm (1.75 m/s)."""
    mine, drawn = _drawn_touch(_kick((50.2, 29.05), part="foot", out=(3.0, 0.0), after=16))
    lifts = [pose["lift"] for pose, _, _ in drawn]
    assert min(lifts) < -0.2
    steps = [abs(b - a) for a, b in zip(lifts, lifts[1:], strict=False)]
    assert max(steps) <= 0.07, steps
    assert lifts[-1] == 0.0


def _held(ball_z=0.0, first=6, last=11, n=18):
    """A keeper at (5, 34) facing +x with the ball 0.25 m in front of him; the frame names him its
    possessor with his pose hands on frames first..last."""
    frames = []
    for i in range(n):
        holding = first <= i <= last
        frames.append({
            "possessor": "h1" if holding else None,
            "ball": {"x": 5.25, "y": 34.0, "z": ball_z, "vx": 0.0, "vy": 0.0},
            "players": [{"id": "h1", "x": 5.0, "y": 34.0, "vx": 0.0, "vy": 0.0, "heading": 0.0,
                         "action": "hands" if holding else "stand", "dive": 0.0}],
        })
    return frames


def test_a_keeper_holding_the_ball_has_his_hands_on_it():
    """Old: the hands pose reached forward at chest height wherever the ball was, so a ball the
    engine has at his feet stayed at his feet with his hands out in front of him. Now each hand is
    beside the ball while he holds it, stooping to it on the grass, and the label's box holds him."""
    cam = Camera((52.5, -35.0, 20.0), (5.0, 34.0, 0.0), 20.0, 1280, 720)
    look = Look("h1", "home", "GK", 1.90, 1.0, "#c68642", "#1b1410")
    for z in (0.0, 1.0):
        frames = _held(ball_z=z)
        runs = holds(frames)["h1"]
        g = Gait()
        for fi, fr in enumerate(frames):
            pl, b = fr["players"][0], fr["ball"]
            g.heading, g.action, g.speed = pl["heading"], pl["action"], 0.0
            touch_at(g, [], fi, look.height_m, FPS, pl["x"], pl["y"])
            hold_at(g, runs, fi, (b["x"], b["y"], b["z"]), look.height_m, FPS)
            parts = body_parts(pl["x"], pl["y"], look, g, (b["x"], b["y"], b["z"]))
            if not runs[0][0] <= fi <= runs[0][1]:
                continue
            pose = mesh_pose(g, pl["x"], pl["y"], 0.0)
            m = pose_markers(pose, g.heading, look.height_m)
            centre = (b["x"], b["y"], b["z"] + BALL_RADIUS)
            for s in "lr":
                side = HOLD_SIDE * look.height_m / ASSET_STATURE_M
                assert math.dist(m[f"hand_{s}"], centre) < side + 0.06, (z, fi, s, m[f"hand_{s}"])
                assert m[f"foot_{s}"][2] > -0.02, (z, fi, s, m[f"foot_{s}"])  # feet on, not in, the grass
            box = parts_box(cam, parts)
            for name in ("head", "hand_l", "hand_r", "foot_l", "foot_r"):
                u, v = cam.project(m[name])
                assert box[0] - 3 <= u <= box[2] + 3 and box[1] - 3 <= v <= box[3] + 4, (z, name, (u, v), box)


def _limb_cap(v):
    """The most a marker may move relative to the body in one frame at speed v (m/s): a runner's
    swinging foot travels from behind him to ahead of him at about his running speed, so 1.6 times
    it leaves room for its peak, and 3.5 m/s more for a quick step from a standstill (design). The
    jumps this caps were 0.8 to 1.05 m in a frame, 20 to 26 m/s, which no limb does in a stride."""
    return (1.6 * v + 3.5) / FPS


def _draw(frames, events=None):
    """Every player of engine-shaped frames drawn as clip.py draws them: gait, touches (with the
    match's events), held balls, labels, then the mesh's markers."""
    looks = {pl["id"]: Look(pl["id"], "home", "CM", 1.84, 1.0, "#c68642", "#1b1410")
             for pl in frames[0]["players"]}
    gaits = {pid: Gait() for pid in looks}
    mine, held, prev = contacts(frames, events), holds(frames), {}
    out = {pid: [] for pid in looks}
    for fi, fr in enumerate(frames):
        b = fr["ball"]
        ball = (b["x"], b["y"], b["z"])
        for pl in fr["players"]:
            g = gaits[pl["id"]]
            px, py = prev.get(pl["id"], (pl["x"], pl["y"]))
            prev[pl["id"]] = (pl["x"], pl["y"])
            dist = math.hypot(pl["x"] - px, pl["y"] - py)
            stride = 2 * _step_m(math.hypot(pl["vx"], pl["vy"]))
            g.phase = (g.phase + 2 * math.pi * dist / stride) % (2 * math.pi)
            g.heading, g.action, g.speed = pl["heading"], pl["action"], math.hypot(pl["vx"], pl["vy"])
            pace(g, g.speed, 1 / FPS)
            touch_at(g, mine.get(pl["id"], []), fi, 1.84, FPS, pl["x"], pl["y"])
            hold_at(g, held.get(pl["id"], []), fi, ball, 1.84, FPS)
            body_parts(pl["x"], pl["y"], looks[pl["id"]], g, ball)
            pose = mesh_pose(g, pl["x"], pl["y"], 0.0)
            m = pose_markers(pose, g.heading, 1.84)
            rel = {k: (v[0] - pl["x"], v[1] - pl["y"], v[2]) for k, v in m.items()}
            out[pl["id"]].append((pose, m, rel, g.speed))
    return out


def _jumps(drawn):
    """Per frame, the largest move of the head, a hand or a foot relative to the body, against the cap."""
    worst = []
    for (_, _, a, va), (_, _, b, vb) in zip(drawn, drawn[1:], strict=False):
        mv = max(math.dist(a[k], b[k]) for k in ("head", "hand_l", "hand_r", "foot_l", "foot_r"))
        worst.append((mv, _limb_cap(max(va, vb))))
    return worst


def _engine_action(v):
    return "stand" if v <= 0.5 else "walk" if v <= 4.0 else "run"  # engine.pose's thresholds


def test_setting_off_running_and_pulling_up_moves_no_limb_in_a_jump():
    """Old: the stride planted each foot a quarter of a cycle away from where the gait has it on the
    grass, switched the stand pose and the walk's short stride on and off at fixed speeds, and
    dropped plants whole, so a foot jumped up to a metre in one frame at every landing and lift
    off. Now each marker moves at most _limb_cap in a frame, from a standstill up to a sprint and
    back down."""
    profile = [0.0] * 15 + [min(7.0, 0.1 * i) for i in range(1, 71)] + [7.0] * 25
    profile += [max(0.0, 7.0 - 0.1 * i) for i in range(1, 71)] + [0.0] * 15
    x, frames = 20.0, []
    for v in profile:
        x += v / FPS
        frames.append({"ball": {"x": 80.0, "y": 50.0, "z": 0.0, "vx": 0.0, "vy": 0.0}, "possessor": None,
                       "players": [{"id": "h1", "x": x, "y": 30.0, "vx": v, "vy": 0.0, "heading": 0.0,
                                    "action": _engine_action(v), "dive": 0.0}]})
    jumps = _jumps(_draw(frames)["h1"])
    over = [(i, round(mv, 3), round(cap, 3)) for i, (mv, cap) in enumerate(jumps) if mv > cap]
    assert not over, over


def test_a_tackle_puts_the_tacklers_foot_on_the_ball_and_neither_body_jumps():
    """The engine's tackle pokes the ball loose with no pose of its own (engine.poke); old, the
    tackler ran in with no leg near the ball and the tackled carrier jumped into a stored pose and
    out of it. Now the tackle event's frame has the tackler's foot on the ball, reached with a
    lunge, and neither body moves a limb in a jump."""
    frames, poke = [], 30
    tx, cx, bx0 = 44.0, 52.0, 0.0
    for i in range(55):
        tv = 4.2 if i < poke else max(2.5, 4.2 - 0.1 * (i - poke))
        cv = 2.0 if i < poke - 6 else max(0.3, 2.0 - 0.25 * (i - poke + 6))
        tx += tv / FPS
        cx -= cv / FPS
        if i < poke:
            ball = {"x": cx - 0.4, "y": 30.25, "z": 0.0, "vx": -cv, "vy": 0.0}
        else:
            t = (i - poke + 1) / FPS
            ball = {"x": bx0 - 1.5 * t, "y": 30.25 - 4.7 * t, "z": 0.0, "vx": -1.5, "vy": -4.7}
        if i == poke - 1:
            bx0 = ball["x"]
        frames.append({"frame": 1000 + i, "ball": ball, "possessor": "a1" if i < poke else None, "players": [
            {"id": "h1", "x": tx, "y": 30.0, "vx": tv, "vy": 0.0, "heading": 0.0,
             "action": _engine_action(tv), "dive": 0.0},
            {"id": "a1", "x": cx, "y": 30.3, "vx": -cv, "vy": 0.0, "heading": math.pi,
             "action": _engine_action(cv), "dive": 0.0},
        ]})
    events = [{"type": "tackle", "frame": 1000 + poke, "player": "h1", "receiver": "a1"}]
    drawn = _draw(frames, events)
    _, m, _, _ = drawn["h1"][poke]
    a = frames[poke - 1]["ball"]
    centre = (a["x"], a["y"], BALL_RADIUS)  # the poke met the ball where it lay as the tick began
    reach = min(math.dist(m[f], centre) for f in ("foot_l", "foot_r"))
    assert reach < BALL_RADIUS + 0.15, (reach, m["foot_l"], m["foot_r"])
    for who in ("h1", "a1"):
        jumps = enumerate(_jumps(drawn[who]))
        over = [(i, round(mv, 3), round(cap, 3)) for i, (mv, cap) in jumps if mv > cap]
        assert not over, (who, over)


def _run_frames(profile, turn_rate=0.0):
    """One player running the speed `profile` (m/s a frame), turning at `turn_rate` rad/s."""
    x, y, h, frames = 20.0, 30.0, 0.0, []
    for v in profile:
        h += turn_rate / FPS
        x, y = x + math.cos(h) * v / FPS, y + math.sin(h) * v / FPS
        frames.append({"ball": {"x": 80.0, "y": 50.0, "z": 0.0, "vx": 0.0, "vy": 0.0}, "possessor": None,
                       "players": [{"id": "h1", "x": x, "y": y, "vx": v * math.cos(h), "vy": v * math.sin(h),
                                    "heading": h, "action": _engine_action(v), "dive": 0.0}]})
    return frames


def _slides(drawn):
    """How far each foot moves along the grass between two frames it is on the grass in: drawn
    within 2 cm of it in both, and not coming down onto it from a swing (a walking swing's last frame
    can be 1 cm up with 2 cm still to go; with the hips' bob the leg now reaches that low)."""
    out = []
    for (pa, a, _, _), (_, b, _, _) in zip(drawn, drawn[1:], strict=False):
        for s in "lr":
            landing = pa[f"plant_{s}"] is not None and pa[f"plant_{s}"][3] > 0.0
            if a[f"foot_{s}"][2] < 0.02 and b[f"foot_{s}"][2] < 0.02 and not landing:
                out.append(math.dist(a[f"foot_{s}"][:2], b[f"foot_{s}"][:2]))
    return out


def test_a_foot_on_the_grass_does_not_slide_from_a_standstill_to_a_sprint_and_back():
    """Old: the stride swung each foot back and forth along one path between two stored poses, so a
    walking foot skimmed along the grass and a landing foot blended onto its plant: a quarter of the
    frames a foot was on the grass it slid more than 2 cm, up to 23 cm (lesson 157). Now a foot on
    the grass stays where it landed (within the leg search's precision, 2 cm) and a swinging foot
    is lifted, from a standstill to 7 m/s and back, and running a bend."""
    profile = [0.0] * 15 + [min(7.0, 0.1 * i) for i in range(1, 71)] + [7.0] * 25
    profile += [max(0.0, 7.0 - 0.1 * i) for i in range(1, 71)] + [0.0] * 15
    for frames in (_run_frames(profile), _run_frames([5.0] * 120, turn_rate=0.5)):
        slides = _slides(_draw(frames)["h1"])
        assert len(slides) > 30
        assert max(slides) <= 0.02, sorted(slides)[-5:]


def test_the_stride_lengthens_and_the_swing_lifts_with_speed():
    """The same foot lands a stride (two steps, scene._step_m: Debaere 2013) further on each time,
    and is carried higher through its swing the faster he runs."""
    lifts = []
    for speed in (1.5, 3.0, 5.0, 7.0):
        drawn = _draw(_run_frames([speed] * 150))["h1"]
        landings, top = [], 0.0
        for (pa, _, _, _), (pb, mb, _, _) in zip(drawn, drawn[1:], strict=False):
            was, now = pa["plant_l"], pb["plant_l"]
            if now and now[3] == 0.0 and was and was[3] > 0.0:
                landings.append(now[0])
            top = max(top, mb["foot_l"][2])
        strides = [b - a for a, b in zip(landings[1:], landings[2:], strict=False)]
        assert strides, speed
        for s in strides:
            assert abs(s / (2 * _step_m(speed)) - 1.0) < 0.1, (speed, s, 2 * _step_m(speed))
        lifts.append(top)
    assert lifts == sorted(lifts) and lifts[0] > 0.05 and lifts[-1] > 0.3, lifts


# A low step after the body (scene.STEP_LIFT) with 4 cm for the foot marker above its sole, both
# lengths of the body: for the 1.84 m player these tests draw, scaled as the scene scales every
# length, by height / ASSET_STATURE_M.
LOW_STEP_M = (STEP_LIFT + 0.04) * 1.84 / ASSET_STATURE_M


def test_a_kick_straight_after_a_touch_stands_on_its_other_foot():
    """Old (0.4.2): a touch then a strike while walking left the other foot to the stride, which
    lifted it as the kick swung: both feet in the air, the drawn body above the label's foot line
    (render-check player_feet_in_boxes, seeds 7 and 11). While a foot plays the ball the other one
    stands, and steps after the body; no foot goes through the grass."""
    frames, touch_at_frame, kick_at = [], 12, 22
    x, bx0 = 40.0, 0.0
    for i in range(40):
        v = 2.2
        x += v / FPS
        if i < touch_at_frame:
            ball = {"x": x + 2.0, "y": 30.3, "z": 0.0, "vx": 0.0, "vy": 0.0}
        elif i <= kick_at:
            ball = {"x": x + 0.45, "y": 30.25, "z": 0.0, "vx": v, "vy": 0.0}
        else:
            t = (i - kick_at) / FPS
            ball = {"x": bx0 + 15.0 * t, "y": 30.25, "z": 0.0, "vx": 15.0, "vy": 0.0}
        if i == kick_at:
            bx0 = ball["x"]
        if touch_at_frame <= i < touch_at_frame + 4:
            action = "foot"
        else:
            action = "strike" if 18 <= i <= kick_at else "walk"
        frames.append({"ball": ball, "possessor": "h1" if touch_at_frame <= i <= kick_at else None,
                       "players": [{"id": "h1", "x": x, "y": 30.0, "vx": v, "vy": 0.0, "heading": 0.0,
                                    "action": action, "dive": 0.0}]})
    drawn = _draw(frames)["h1"]
    for i, (pose, m, _, _) in enumerate(drawn):
        assert min(m["foot_l"][2], m["foot_r"][2]) > -0.03, (i, m["foot_l"], m["foot_r"])
        touch = pose["touch"]
        if touch and touch["part"] in ("foot", "strike") and touch["w"] >= 0.9:  # the touch, the kick
            other = "foot_r" if touch["side"] == "l" else "foot_l"
            # It stands, or takes a low step after the body (STEP_LIFT, 8 cm): it is not swung up.
            assert m[other][2] < LOW_STEP_M, (i, touch["part"], m[other])


@pytest.mark.parametrize("gap", [0, 5])
def test_a_first_touch_then_a_strike_on_the_move_keeps_a_foot_on_the_grass(gap):
    """Old (0.4.3): a pass cushioned with the left foot while walking at 3.1 m/s, then struck with
    the right, left the left foot's plant where it stood before the touch. By the strike the body
    was 2 m on, beyond the leg's reach, so the mesh hung that foot 0.3 to 0.6 m up while the right
    foot swung: the whole body in the air for half a second (render-check player_feet_in_boxes,
    seed 7, h3 at 23.5 s). 0.4.4 brought the foot back from where the touch drew it, which was
    still the old plant once the touch had faded before the strike (`gap`, seed 7's h10 at
    33.4 s). Now a touch keeps its foot's plant within the leg's reach, and lets the foot go
    from where it is drawn."""
    frames, x, v = [], 30.0, 3.1
    touch, strike = 20, (31 + gap, 33 + gap)  # the first frame of the cushion; the strike's wind-up
    for i in range(48 + gap):
        v = 3.1 if i <= strike[0] else max(0.0, v - 0.26)
        x += v / FPS
        if i < touch:
            # The pass comes at him at 11.7 m/s (seed 7, h3), to his left foot.
            ball = {"x": x + 0.2 + 11.7 * (touch - i) / FPS, "y": 30.05, "z": 0.0, "vx": -11.7, "vy": 0.0}
        elif i <= strike[1]:
            # Cushioned, then carried 0.2 m ahead of him; it rolls across to his right to be struck.
            y = 30.05 if i < strike[0] - 2 else 29.95
            ball = {"x": x + 0.2, "y": y, "z": 0.0, "vx": v, "vy": 0.0}
        else:
            t = (i - strike[1]) / FPS
            ball = {"x": frames[strike[1]]["ball"]["x"] + 6.5 * t, "y": 29.95 + 19.5 * t, "z": 0.0,
                    "vx": 6.5, "vy": 19.5}
        action = ("foot" if touch <= i < touch + 8 else "strike" if strike[0] <= i <= strike[1]
                  else _engine_action(v))
        frames.append({"ball": ball, "possessor": "h1" if touch <= i <= strike[1] else None,
                       "players": [{"id": "h1", "x": x, "y": 30.0, "vx": v, "vy": 0.0, "heading": 0.0,
                                    "action": action, "dive": 0.0}]})
    drawn = _draw(frames)["h1"]
    assert any(p["touch"] and p["touch"]["part"] == "foot" and p["touch"]["side"] == "l" for p, *_ in drawn)
    assert any(p["touch"] and p["touch"]["part"] == "strike" and p["touch"]["side"] == "r" for p, *_ in drawn)
    for i, (pose, m, _, _) in enumerate(drawn):
        # While a touch is drawn, a foot is on the grass or on a low step after the body (STEP_LIFT).
        # Between touches the stride's own flight phase is a run's (3.1 m/s, _duty).
        low = min(m["foot_l"][2], m["foot_r"][2])
        assert low > -0.03, (i, m["foot_l"], m["foot_r"])
        if pose["touch"]:
            assert low < LOW_STEP_M, (i, pose["touch"], m["foot_l"], m["foot_r"])


def test_a_thigh_touch_on_the_move_keeps_a_foot_on_the_grass():
    """Old (0.4.4): walking at 3 m/s into a ball at thigh height, the touch caught the other foot
    in the stride's swing, half a metre up, and brought it down as a step across the whole way to
    where it stands, over 0.6 s: with the thigh raised, both feet were off the grass (seed 7, a6
    at 35.6 s). A foot caught in the air lands within LAND_FRAMES."""
    frames, x, v = [], 60.0, 3.0
    touch = 22  # the frame the thigh meets the ball
    for i in range(46):
        x += v / FPS
        bz = 0.9 if i <= touch else max(0.0, 0.9 - 0.3 * (i - touch))
        ball = {"x": x + (0.25 if i >= touch else 0.25 + 9.0 * (touch - i) / FPS), "y": 30.1, "z": bz,
                "vx": v if i >= touch else -9.0, "vy": 0.0}
        action = "thigh" if touch <= i < touch + 6 else _engine_action(v)
        frames.append({"ball": ball, "possessor": "h1" if i >= touch else None,
                       "players": [{"id": "h1", "x": x, "y": 30.0, "vx": v, "vy": 0.0, "heading": 0.0,
                                    "action": action, "dive": 0.0}]})
    drawn = _draw(frames)["h1"]
    assert any(p["touch"] and p["touch"]["part"] == "thigh" for p, *_ in drawn)
    for i, (pose, m, _, _) in enumerate(drawn):
        # While the touch is drawn; between touches a 3 m/s stride has a run's flight phase (_duty).
        low = min(m["foot_l"][2], m["foot_r"][2])
        assert low > -0.03, (i, m["foot_l"], m["foot_r"])
        if pose["touch"]:
            assert low < LOW_STEP_M, (i, pose["touch"], m["foot_l"], m["foot_r"])


@pytest.mark.parametrize("wind_up", range(20, 34, 2))
def test_a_strike_on_the_run_keeps_a_foot_on_the_grass(wind_up):
    """Old (0.5.3 before the fix): running at 4.2 m/s into a strike, the support foot could be just
    lifting off behind him when the strike began; it came down where it was, a metre back, and
    stepped after him at standing pace (STEP_PEAK_MPS), never catching him up: the leg hung toward
    it, both feet 0.3 to 0.4 m up through the strike (seed 7, h6 at 9.9 s). A stepping foot now
    outpaces the body (STEP_CATCH_UP). Across the stride's phases at the strike (`wind_up`)."""
    frames, x, v = [], 50.0, 4.2
    for i in range(wind_up + 16):
        x += v / FPS
        striking = wind_up <= i < wind_up + 3
        ball = {"x": x + 0.4, "y": 29.85, "z": 0.0, "vx": v, "vy": 0.0}
        if i >= wind_up + 3:
            t = (i - wind_up - 2) / FPS
            struck = frames[wind_up + 2]["ball"]["x"]
            ball = {"x": struck + 18.0 * t, "y": 29.85, "z": 0.0, "vx": 18.0, "vy": 0.0}
        frames.append({"ball": ball, "possessor": "h1" if i < wind_up + 3 else None,
                       "players": [{"id": "h1", "x": x, "y": 30.0, "vx": v, "vy": 0.0, "heading": 0.0,
                                    "action": "strike" if striking else _engine_action(v), "dive": 0.0}]})
    drawn = _draw(frames)["h1"]
    for i, (pose, m, _, _) in enumerate(drawn):
        touch = pose["touch"]
        if touch and touch["part"] == "strike" and touch["w"] >= 0.5:
            low = min(m["foot_l"][2], m["foot_r"][2])
            assert -0.03 < low < LOW_STEP_M + 0.05, (wind_up, i, m["foot_l"], m["foot_r"])


def test_a_keeper_stooping_on_the_run_keeps_his_feet_on_the_grass():
    """Old (0.4.2): a keeper gathering a ground ball at 3 m/s dropped his hips while a foot stayed
    planted behind him beyond the leg's reach; the leg gave up and the foot was drawn 0.34 m
    through the grass. Now a foot left beyond reach steps at once, he stoops less on the move,
    and a lowered leg that cannot reach its plant reaches toward it above the grass."""
    frames, x = [], 20.0
    for i in range(36):
        v = 3.0 if i < 30 else 1.0
        x += v / FPS
        holding = 16 <= i <= 24
        frames.append({"possessor": "h1" if holding else None,
                       "ball": {"x": x + 0.3, "y": 34.0, "z": 0.0, "vx": v, "vy": 0.0},
                       "players": [{"id": "h1", "x": x, "y": 34.0, "vx": v, "vy": 0.0, "heading": 0.0,
                                    "action": "hands" if holding else "run", "dive": 0.0}]})
    drawn = _draw(frames)["h1"]
    for i, (pose, m, _, _) in enumerate(drawn):
        assert min(m["foot_l"][2], m["foot_r"][2]) > -0.03, (i, pose["lift"], m["foot_l"], m["foot_r"])


def _throw_in(wait=30, hold=5, after=30, way=(-15.6, 5.5, 10.0)):
    """Engine-shaped frames of a throw-in (engine.throw_hands, tick_carrier): the taker stands behind
    the touchline facing the pitch with the ball on the grass 0.28 m in front of him; on the frame he
    is named thrower it is still there, then rises 0.48 m a frame (P6's 12 m/s) to 1.85 m, stays for
    `hold` frames, and leaves on the first frame after, at `way` m/s; he then walks off."""
    frames, x, y = [], 50.0, -0.55
    bx, by = 50.0, -0.27
    n = wait + 1 + 4 + hold + after
    rel = wait + 1 + 4 + hold
    for i in range(n):
        if i <= wait:
            action, z = "stand", 0.0
        elif i < rel:
            action, z = "throw", min(1.85, 0.48 * (i - wait))
        else:
            action = "stand" if i < rel + 3 else "walk"
        if i < rel:
            ball = {"x": bx, "y": by, "z": z if i > wait else 0.0, "vx": 0.0, "vy": 0.0}
        else:
            t = (i - rel) / FPS
            ball = {"x": bx + way[0] * t, "y": by + way[1] * t, "z": 1.85 + way[2] * t - 4.9 * t * t,
                    "vx": way[0], "vy": way[1]}
        v = 0.0 if i < rel + 3 else min(1.5, 0.1 * (i - rel - 2))
        y += v / FPS
        frames.append({"frame": 2000 + i, "ball": ball, "possessor": "h1" if wait <= i < rel else None,
                       "players": [{"id": "h1", "x": x, "y": y, "vx": 0.0, "vy": v, "heading": math.pi / 2,
                                    "action": action, "dive": 0.0}]})
    return frames, wait, rel


def _draw_throw(frames, height=1.84):
    look = Look("h1", "home", "FB", height, 1.0, "#c68642", "#1b1410")
    thrown = throws(frames, FPS)
    g, out = Gait(), []
    for fi, fr in enumerate(frames):
        pl, b = fr["players"][0], fr["ball"]
        g.heading, g.action, g.speed = pl["heading"], pl["action"], math.hypot(pl["vx"], pl["vy"])
        g.phase = (g.phase + 2 * math.pi * g.speed / FPS / (2 * _step_m(g.speed))) % (2 * math.pi)
        touch_at(g, [], fi, height, FPS, pl["x"], pl["y"])
        hold_at(g, [], fi, (b["x"], b["y"], b["z"]), height, FPS)
        throw_at(g, thrown.get("h1", []), fi, height, FPS, pl["x"], pl["y"])
        body_parts(pl["x"], pl["y"], look, g, None)
        pose = mesh_pose(g, pl["x"], pl["y"], 0.0)
        m = pose_markers(pose, g.heading, height)
        rel = {k: (v[0] - pl["x"], v[1] - pl["y"], v[2]) for k, v in m.items()}
        out.append((pose, m, rel, g.speed))
    return out


def test_a_throw_in_keeps_both_hands_on_the_ball_from_the_grass_to_the_throw():
    """Old: on the frame the engine named him thrower the arms snapped over his head with the ball
    still at his feet, the ball rose into the hands by itself, and on the throw the arms dropped to
    his sides in one frame (seed 21, a6 at 6:09). Now he bends to the ball beforehand, a hand either
    side of it (HOLD_SIDE) from the frame it starts to rise until it leaves, and follows through."""
    frames, start, rel = _throw_in()
    drawn = _draw_throw(frames)
    side = HOLD_SIDE * 1.84 / ASSET_STATURE_M
    for i in range(start, rel + 1):
        b = frames[i]["ball"]
        centre = (b["x"], b["y"], b["z"] + BALL_RADIUS)
        for s in "lr":
            assert math.dist(drawn[i][1][f"hand_{s}"], centre) < side + 0.04, (i, s, drawn[i][1][f"hand_{s}"])
    # Bent to it on the grass: the head is below the hips' standing height when the lift starts.
    assert drawn[start][1]["head"][2] < 1.0, drawn[start][1]["head"]
    # The follow-through goes the way the ball went (forward along the throw), not straight down.
    way = (-15.6 / math.hypot(15.6, 5.5), 5.5 / math.hypot(15.6, 5.5))
    mid = lambda m: [(m["hand_l"][j] + m["hand_r"][j]) / 2 for j in range(3)]  # noqa: E731
    a, b = mid(drawn[rel][1]), mid(drawn[rel + 4][1])
    assert (b[0] - a[0]) * way[0] + (b[1] - a[1]) * way[1] > 0.25, (a, b)
    assert b[2] < a[2] - 0.3, (a, b)


def test_a_throw_in_moves_no_limb_in_a_jump():
    """Old: the arms jumped about a metre on the frame he was named thrower and again on the throw.
    Now no marker moves relative to the body faster than the limb cap, with two stated exceptions.
    While the engine lifts the ball at 12 m/s (0.48 m a frame) the hands hold it, so the head moves
    no further in a frame than the ball and each hand no further than the ball plus the 4 cm either
    side of its hold at both ends and a frame's turn of the wrist about it (0.15 m). In the
    follow-through the hands swing on from a ball that left them at about 20 m/s: up to 0.3 m a frame
    (7.5 m/s, design), still a third of the release."""
    frames, start, rel = _throw_in()
    drawn = _draw_throw(frames)
    for i in range(1, len(drawn)):
        cap = _limb_cap(max(drawn[i - 1][3], drawn[i][3]))
        for k in ("head", "hand_l", "hand_r", "foot_l", "foot_r"):
            limit = cap
            if start < i <= rel:
                a, b = frames[i - 1]["ball"], frames[i]["ball"]
                step = math.dist((a["x"], a["y"], a["z"]), (b["x"], b["y"], b["z"]))
                limit = max(cap, step + (0.15 if k.startswith("hand") else 0.0))
            elif rel < i <= rel + round(THROW_FOLLOW_S * FPS) and k.startswith("hand"):
                limit = 0.3
            mv = math.dist(drawn[i - 1][2][k], drawn[i][2][k])
            assert mv <= limit, (i, k, round(mv, 3), round(limit, 3))


@pytest.mark.parametrize("speed", [2.5, 3.5, 4.5, 6.0])
def test_a_running_foot_is_highest_early_in_its_swing(speed):
    """Old (0.5.3): a running foot was carried highest halfway through its swing, under the hips, as
    if walking: a high-knee march at 3 to 4 m/s. Running, it is highest about a third of the way
    through (Fukuchi et al. 2017, Fig. 3: the knee most folded at 69% of the stride, the swing from
    about 54%), behind him, and comes through low to land: in most swings no later than a third and
    one frame (a swing is 10 to 13 frames here)."""
    drawn = _draw(_run_frames([speed] * 120))["h1"][30:]
    shares = []
    for s in "lr":
        swing = []
        for pose, m, _, _ in drawn:
            plant = pose[f"plant_{s}"]
            if plant and plant[3] > 0.0:
                swing.append(m[f"foot_{s}"][2])
            elif swing:
                shares.append((swing.index(max(swing)) + 1) / (len(swing) + 1))
                swing = []
    shares = sorted(shares[1:])
    assert len(shares) > 4
    assert shares[len(shares) // 2] < 1 / 3 + 1 / 11, (speed, shares)


def test_a_run_has_a_flight_phase_and_a_walk_does_not():
    """Above the walk-to-run switch (1.96 m/s, Neptune and Sasaki 2005) both feet leave the grass
    between steps; below it there are frames with both feet down. Old (0.5.3): at 3 to 4 m/s the
    stride dragged a foot on its toes behind him while the other landed."""
    for speed, flight in ((1.3, False), (3.5, True), (6.0, True)):
        drawn = _draw(_run_frames([speed] * 100))["h1"][40:]
        both_up = sum(1 for _, m, _, _ in drawn if min(m["foot_l"][2], m["foot_r"][2]) > 0.03)
        both_down = sum(1 for _, m, _, _ in drawn if max(m["foot_l"][2], m["foot_r"][2]) < 0.03)
        assert (both_up > 0) == flight and (both_down > 0) != flight, (speed, both_up, both_down)


def test_a_change_of_pace_in_mid_swing_moves_no_foot_in_a_jump():
    """Old (0.5.3): the swing's progress was read straight off the stride's phase, so when braking
    from a run changed the stance's share mid-swing the swinging foot jumped, from knee-up to planted
    far ahead in one frame (seed 21, h2 at 5:43.8). Braking at 7 m/s (the engine's) from 5 m/s
    through the walk-run switch and speeding up again, no foot moves relative to the body faster
    than the limb cap."""
    profile = [5.0] * 30 + [max(1.0, 5.0 - 0.28 * i) for i in range(1, 16)] + [1.0] * 10
    profile += [min(5.0, 1.0 + 0.25 * i) for i in range(1, 17)] + [5.0] * 20
    for start in range(0, 12, 3):  # different phases of the stride at the change
        drawn = _draw(_run_frames([5.0] * start + profile))["h1"]
        over = [(i, round(mv, 3), round(cap, 3)) for i, (mv, cap) in enumerate(_jumps(drawn)) if mv > cap]
        assert not over, (start, over)


def test_the_push_off_toe_does_not_slide_before_it_lifts():
    """Old (0.5.3): a foot was kept on the grass behind him further back than the leg reaches
    (STANCE_BEHIND_MAX 0.45, measured 0.30), so in its last frames before lifting the leg dragged
    it along on its toes at the same height, up to 17 cm a frame (seed 21, h9 at 5:55). Now in the
    frame after a foot was planted it either stays within 3 cm or has left the grass (risen 2 cm,
    the slide test's height for on the grass), at every pace from a walk to a sprint."""
    for speed in (1.5, 2.5, 3.5, 5.0, 7.0):
        drawn = _draw(_run_frames([speed] * 80))["h1"][20:]
        for (pa, a, _, _), (_, b, _, _) in zip(drawn, drawn[1:], strict=False):
            for s in "lr":
                planted = pa[f"plant_{s}"] is not None and pa[f"plant_{s}"][3] == 0.0
                if planted:
                    mv = math.dist(a[f"foot_{s}"][:2], b[f"foot_{s}"][:2])
                    rise = b[f"foot_{s}"][2] - a[f"foot_{s}"][2]
                    assert mv <= 0.03 or rise >= 0.02, (speed, s, round(mv, 3), round(rise, 3))


# Seed 21, h2 from 5:49.6 (engine frames 8740-8829): he slows from a jog, turns on the spot and the
# engine's pose flickers between walk and stand: (x, y, vx, vy, heading, action).
H2_STOP = [
    (45.943, 3.851, 4.057, -5.313, -0.919, "run"), (46.106, 3.638, 4.092, -5.343, -0.917, "run"),
    (46.268, 3.426, 4.046, -5.282, -0.917, "run"), (46.425, 3.222, 3.907, -5.101, -0.917, "run"),
    (46.576, 3.026, 3.786, -4.915, -0.914, "run"), (46.722, 2.836, 3.647, -4.734, -0.914, "run"),
    (46.862, 2.654, 3.508, -4.553, -0.914, "run"), (46.997, 2.479, 3.368, -4.372, -0.914, "run"),
    (47.125, 2.313, 3.199, -4.149, -0.914, "run"), (47.246, 2.156, 3.03, -3.926, -0.913, "run"),
    (47.361, 2.008, 2.861, -3.703, -0.913, "run"), (47.468, 1.869, 2.691, -3.48, -0.913, "run"),
    (47.569, 1.739, 2.521, -3.257, -0.912, "run"), (47.663, 1.617, 2.352, -3.034, -0.911, "walk"),
    (47.75, 1.505, 2.182, -2.811, -0.911, "walk"), (47.831, 1.402, 2.014, -2.588, -0.91, "walk"),
    (47.905, 1.307, 1.845, -2.364, -0.908, "walk"), (47.972, 1.221, 1.677, -2.141, -0.906, "walk"),
    (48.032, 1.145, 1.509, -1.916, -0.904, "walk"), (48.086, 1.077, 1.342, -1.692, -0.9, "walk"),
    (48.134, 1.019, 1.203, -1.448, -0.877, "walk"), (48.177, 0.971, 1.069, -1.203, -0.845, "walk"),
    (48.214, 0.933, 0.937, -0.956, -0.795, "walk"), (48.247, 0.904, 0.81, -0.706, -0.717, "walk"),
    (48.274, 0.886, 0.688, -0.454, -0.584, "walk"), (48.297, 0.878, 0.57, -0.2, -0.34, "walk"),
    (48.315, 0.88, 0.457, 0.056, -0.584, "stand"), (48.329, 0.893, 0.348, 0.314, -0.828, "stand"),
    (48.339, 0.916, 0.245, 0.574, -0.584, "walk"), (48.344, 0.947, 0.135, 0.771, -0.34, "walk"),
    (48.346, 0.984, 0.039, 0.938, -0.095, "walk"), (48.344, 1.028, -0.043, 1.091, 0.149, "walk"),
    (48.34, 1.077, -0.112, 1.236, 0.393, "walk"), (48.333, 1.133, -0.173, 1.378, 0.638, "walk"),
    (48.324, 1.193, -0.226, 1.516, 0.882, "walk"), (48.313, 1.259, -0.274, 1.652, 1.127, "walk"),
    (48.3, 1.331, -0.317, 1.785, 1.371, "walk"), (48.286, 1.407, -0.357, 1.917, 1.615, "walk"),
    (48.27, 1.489, -0.394, 2.046, 1.761, "walk"), (48.253, 1.576, -0.429, 2.173, 1.766, "walk"),
    (48.234, 1.668, -0.462, 2.298, 1.769, "walk"), (48.215, 1.765, -0.493, 2.421, 1.772, "walk"),
    (48.194, 1.867, -0.524, 2.541, 1.774, "walk"), (48.173, 1.968, -0.522, 2.526, 1.774, "walk"),
    (48.154, 2.059, -0.474, 2.296, 1.774, "walk"), (48.137, 2.142, -0.427, 2.065, 1.774, "walk"),
    (48.122, 2.215, -0.379, 1.833, 1.774, "walk"), (48.108, 2.279, -0.33, 1.599, 1.774, "walk"),
    (48.097, 2.334, -0.281, 1.362, 1.774, "walk"), (48.088, 2.379, -0.232, 1.121, 1.774, "walk"),
    (48.081, 2.414, -0.181, 0.875, 1.774, "walk"), (48.075, 2.438, -0.128, 0.617, 1.774, "walk"),
    (48.073, 2.452, -0.071, 0.343, 2.019, "stand"), (48.06, 2.46, -0.309, 0.196, 2.263, "stand"),
    (48.039, 2.462, -0.528, 0.047, 2.507, "walk"), (48.012, 2.458, -0.684, -0.092, 2.752, "walk"),
    (47.979, 2.449, -0.82, -0.215, 2.996, "walk"), (47.941, 2.436, -0.947, -0.328, -3.043, "walk"),
    (47.898, 2.419, -1.068, -0.436, -2.798, "walk"), (47.851, 2.397, -1.184, -0.542, -2.712, "walk"),
    (47.799, 2.371, -1.296, -0.647, -2.678, "walk"), (47.757, 2.352, -1.065, -0.489, -2.711, "walk"),
    (47.723, 2.339, -0.847, -0.313, -2.788, "walk"), (47.697, 2.334, -0.631, -0.134, -2.932, "walk"),
    (47.682, 2.335, -0.398, 0.02, -2.688, "stand"), (47.66, 2.329, -0.543, -0.143, -2.884, "walk"),
    (47.633, 2.318, -0.663, -0.283, -2.738, "walk"), (47.602, 2.301, -0.775, -0.411, -2.654, "walk"),
    (47.581, 2.29, -0.534, -0.269, -2.674, "walk"), (47.568, 2.287, -0.317, -0.092, -2.43, "stand"),
    (47.551, 2.278, -0.438, -0.229, -2.186, "stand"), (47.542, 2.276, -0.224, -0.049, -1.941, "stand"),
    (47.528, 2.268, -0.348, -0.187, -1.697, "stand"), (47.523, 2.267, -0.116, -0.03, -1.452, "stand"),
    (47.514, 2.261, -0.241, -0.157, -1.358, "stand"), (47.511, 2.263, -0.065, 0.061, -1.358, "stand"),
    (47.502, 2.259, -0.235, -0.107, -1.356, "stand"), (47.487, 2.249, -0.354, -0.233, -1.354, "stand"),
    (47.469, 2.235, -0.469, -0.351, -1.598, "walk"), (47.456, 2.231, -0.31, -0.121, -1.354, "stand"),
    (47.451, 2.234, -0.131, 0.095, -1.348, "stand"), (47.438, 2.231, -0.315, -0.095, -1.346, "stand"),
    (47.421, 2.221, -0.429, -0.243, -1.343, "stand"), (47.4, 2.206, -0.537, -0.374, -1.587, "walk"),
    (47.374, 2.186, -0.641, -0.499, -1.831, "walk"), (47.355, 2.175, -0.468, -0.279, -2.076, "walk"),
    (47.343, 2.173, -0.3, -0.055, -1.831, "stand"), (47.341, 2.175, -0.048, 0.067, -1.587, "stand"),
    (47.333, 2.17, -0.221, -0.121, -1.343, "stand"), (47.319, 2.16, -0.33, -0.256, -1.325, "stand"),
]


def test_a_player_stopping_does_not_stand_with_his_legs_crossed():
    """Old (0.5.3): slowing and turning on the spot while the engine's pose flickered between walk and
    stand, h2's left foot ended up to the right of his right foot and stayed there for 7 frames
    (seed 21 at 5:51), as each flicker restarted the step that would have uncrossed them. Now feet
    crossed for the way he faces step apart at once, and a foot stepping across passes the other
    within half a step (STEP_FRAMES // 2). Drawn as clip.py draws him, from the engine's frames
    (H2_STOP), the gait starting fresh on the first."""
    frames = [{"ball": {"x": 80.0, "y": 50.0, "z": 0.0, "vx": 0.0, "vy": 0.0}, "possessor": None,
               "players": [{"id": "h1", "x": x, "y": y, "vx": vx, "vy": vy, "heading": h, "action": a,
                            "dive": 0.0}]} for x, y, vx, vy, h, a in H2_STOP]
    frames += [frames[-1]] * 20  # then he stands
    h2 = Look("h1", "home", "RB", 1.81, 1.11, "#4a2e1d", "#3b2516")  # as seed 21 draws h2
    g, prev, run, worst = Gait(), {}, 0, 0
    for i, fr in enumerate(frames):
        advance_gaits({"h1": g}, prev, fr, 1 / FPS, frames[min(i + LEAD_AHEAD_FRAMES, len(frames) - 1)])
        pl = fr["players"][0]
        body_parts(pl["x"], pl["y"], h2, g)
        pose = mesh_pose(g, pl["x"], pl["y"], 0.0)
        m = pose_markers(pose, g.heading, h2.height_m)
        lx, ly = -math.sin(pl["heading"]), math.cos(pl["heading"])  # his left
        left = (m["foot_l"][0] - pl["x"]) * lx + (m["foot_l"][1] - pl["y"]) * ly
        right = (m["foot_r"][0] - pl["x"]) * lx + (m["foot_r"][1] - pl["y"]) * ly
        # Stopping: slower than a walk's stride (1.25 m/s, Swinnen et al. 2026's slowest; design). A
        # stride turning fast crosses over, as a turning walker's does; that is not a stance.
        run = run + 1 if left < right and math.hypot(pl["vx"], pl["vy"]) < 1.0 else 0
        worst = max(worst, run)
    assert worst <= STEP_FRAMES // 2, worst


def _both_up_runs(drawn, height=0.14):
    """Longest run of frames with both feet above `height` (a blind critic's measure: 14 cm)."""
    run = worst = 0
    for _, m, _, _ in drawn:
        run = run + 1 if min(m["foot_l"][2], m["foot_r"][2]) > height else 0
        worst = max(worst, run)
    return worst


def test_a_player_drifting_while_the_pose_flickers_keeps_his_feet_down():
    """Found by the blind critic of this change's first draft: drifting at 0.4 to 0.6 m/s, the engine's
    pose flickers between walk and stand every frame (seed 21, a8 at 6:08), and a stride restarted
    each frame never landed: both feet hovered 10 to 20 cm up for 40 frames, a crouched shuffle.
    Below STRIDE_FROM_MPS  the feet step after the body as when standing."""
    frames, x = [], 30.0
    for i in range(60):
        v, action = (0.55, "walk") if i % 3 else (0.4, "stand")
        x += v / FPS
        frames.append({"ball": {"x": 80.0, "y": 50.0, "z": 0.0, "vx": 0.0, "vy": 0.0}, "possessor": None,
                       "players": [{"id": "h1", "x": x, "y": 30.0, "vx": v, "vy": 0.0, "heading": 0.0,
                                    "action": action, "dive": 0.0}]})
    assert _both_up_runs(_draw(frames)["h1"], 0.05) <= STEP_FRAMES // 2


def test_setting_off_from_standing_lifts_one_foot_at_a_time():
    """Found by the same critic: setting off, both standing feet were behind the leg's reach at once
    and lifted together, a tuck-jump (seed 21, a5 and h9). One foot lifts early at a time; a run's
    flight with both feet high lasts no more than a frame."""
    profile = [0.0] * 20 + [min(3.2, 0.15 * i) for i in range(1, 30)] + [3.2] * 20
    for start in range(0, 8, 2):  # different stance phases at the start
        drawn = _draw(_run_frames([0.0] * start + profile))["h1"]
        assert _both_up_runs(drawn) <= 1, start


# Seed 7, h10 from 1:33 (engine frames 2324-2599, where the clip"s picture comes back after a cut):
# standing, then setting off to 3.5 m/s at the end.
H10_SET_OFF = [
    (78.115, 41.025, -0.79, 0.329, 2.746, "walk"), (78.084, 41.038, -0.79, 0.329, 2.746, "walk"),
    (78.052, 41.052, -0.79, 0.329, 2.746, "walk"), (78.021, 41.065, -0.79, 0.329, 2.746, "walk"),
    (77.989, 41.078, -0.79, 0.329, 2.746, "walk"), (77.957, 41.091, -0.79, 0.329, 2.746, "walk"),
    (77.926, 41.104, -0.79, 0.329, 2.746, "walk"), (77.894, 41.117, -0.79, 0.329, 2.746, "walk"),
    (77.863, 41.131, -0.79, 0.329, 2.746, "walk"), (77.831, 41.144, -0.79, 0.329, 2.746, "walk"),
    (77.799, 41.157, -0.79, 0.329, 2.746, "walk"), (77.768, 41.17, -0.79, 0.329, 2.746, "walk"),
    (77.736, 41.183, -0.79, 0.329, 2.746, "walk"), (77.705, 41.196, -0.79, 0.329, 2.746, "walk"),
    (77.673, 41.21, -0.79, 0.329, 2.746, "walk"), (77.642, 41.223, -0.79, 0.329, 2.746, "walk"),
    (77.61, 41.236, -0.79, 0.329, 2.746, "walk"), (77.578, 41.249, -0.79, 0.329, 2.746, "walk"),
    (77.547, 41.262, -0.79, 0.329, 2.746, "walk"), (77.515, 41.276, -0.79, 0.329, 2.746, "walk"),
    (77.484, 41.289, -0.79, 0.329, 2.746, "walk"), (77.452, 41.302, -0.79, 0.329, 2.746, "walk"),
    (77.42, 41.315, -0.79, 0.33, 2.746, "walk"), (77.389, 41.328, -0.789, 0.33, 2.746, "walk"),
    (77.357, 41.342, -0.788, 0.333, 2.742, "walk"), (77.326, 41.355, -0.787, 0.335, 2.74, "walk"),
    (77.294, 41.368, -0.786, 0.337, 2.737, "walk"), (77.263, 41.382, -0.785, 0.34, 2.733, "walk"),
    (77.232, 41.396, -0.784, 0.342, 2.73, "walk"), (77.2, 41.41, -0.783, 0.345, 2.727, "walk"),
    (77.169, 41.423, -0.782, 0.347, 2.724, "walk"), (77.138, 41.437, -0.781, 0.349, 2.721, "walk"),
    (77.107, 41.451, -0.78, 0.351, 2.719, "walk"), (77.075, 41.465, -0.78, 0.351, 2.719, "walk"),
    (77.044, 41.48, -0.78, 0.352, 2.718, "walk"), (77.013, 41.494, -0.78, 0.352, 2.718, "walk"),
    (76.982, 41.508, -0.781, 0.35, 2.72, "walk"), (76.95, 41.522, -0.781, 0.349, 2.721, "walk"),
    (76.919, 41.536, -0.782, 0.348, 2.723, "walk"), (76.888, 41.549, -0.783, 0.346, 2.725, "walk"),
    (76.857, 41.563, -0.783, 0.344, 2.728, "walk"), (76.825, 41.577, -0.784, 0.342, 2.731, "walk"),
    (76.794, 41.59, -0.787, 0.336, 2.738, "walk"), (76.762, 41.604, -0.788, 0.334, 2.74, "walk"),
    (76.731, 41.617, -0.788, 0.332, 2.743, "walk"), (76.699, 41.63, -0.789, 0.331, 2.745, "walk"),
    (76.668, 41.643, -0.79, 0.329, 2.747, "walk"), (76.636, 41.656, -0.79, 0.328, 2.748, "walk"),
    (76.604, 41.67, -0.79, 0.328, 2.748, "walk"), (76.573, 41.683, -0.79, 0.328, 2.748, "walk"),
    (76.541, 41.696, -0.79, 0.328, 2.748, "walk"), (76.51, 41.709, -0.79, 0.328, 2.748, "walk"),
    (76.478, 41.722, -0.79, 0.328, 2.748, "walk"), (76.446, 41.735, -0.79, 0.328, 2.748, "walk"),
    (76.415, 41.748, -0.79, 0.328, 2.748, "walk"), (76.383, 41.761, -0.79, 0.328, 2.748, "walk"),
    (76.351, 41.775, -0.79, 0.328, 2.748, "walk"), (76.32, 41.788, -0.79, 0.328, 2.748, "walk"),
    (76.288, 41.801, -0.79, 0.328, 2.748, "walk"), (76.257, 41.814, -0.79, 0.328, 2.748, "walk"),
    (76.225, 41.827, -0.79, 0.328, 2.748, "walk"), (76.193, 41.84, -0.79, 0.328, 2.748, "walk"),
    (76.162, 41.853, -0.79, 0.328, 2.748, "walk"), (76.13, 41.866, -0.79, 0.328, 2.748, "walk"),
    (76.099, 41.879, -0.79, 0.328, 2.748, "walk"), (76.067, 41.893, -0.79, 0.328, 2.748, "walk"),
    (76.035, 41.906, -0.79, 0.328, 2.748, "walk"), (76.004, 41.919, -0.79, 0.328, 2.748, "walk"),
    (75.972, 41.932, -0.79, 0.328, 2.748, "walk"), (75.941, 41.945, -0.79, 0.328, 2.748, "walk"),
    (75.909, 41.958, -0.79, 0.328, 2.748, "walk"), (75.877, 41.971, -0.79, 0.328, 2.748, "walk"),
    (75.846, 41.984, -0.79, 0.328, 2.748, "walk"), (75.814, 41.998, -0.79, 0.328, 2.748, "walk"),
    (75.783, 42.011, -0.79, 0.328, 2.748, "walk"), (75.751, 42.024, -0.79, 0.328, 2.748, "walk"),
    (75.719, 42.037, -0.79, 0.328, 2.748, "walk"), (75.688, 42.05, -0.79, 0.328, 2.748, "walk"),
    (75.656, 42.063, -0.79, 0.328, 2.748, "walk"), (75.624, 42.076, -0.79, 0.328, 2.748, "walk"),
    (75.593, 42.089, -0.79, 0.328, 2.748, "walk"), (75.561, 42.102, -0.79, 0.328, 2.748, "walk"),
    (75.53, 42.116, -0.79, 0.328, 2.748, "walk"), (75.498, 42.129, -0.79, 0.328, 2.748, "walk"),
    (75.466, 42.142, -0.79, 0.328, 2.748, "walk"), (75.435, 42.155, -0.79, 0.328, 2.748, "walk"),
    (75.403, 42.168, -0.79, 0.328, 2.748, "walk"), (75.372, 42.181, -0.79, 0.328, 2.748, "walk"),
    (75.34, 42.194, -0.79, 0.328, 2.748, "walk"), (75.308, 42.207, -0.79, 0.328, 2.748, "walk"),
    (75.277, 42.221, -0.79, 0.328, 2.748, "walk"), (75.245, 42.234, -0.79, 0.328, 2.748, "walk"),
    (75.214, 42.247, -0.79, 0.328, 2.748, "walk"), (75.182, 42.26, -0.79, 0.328, 2.748, "walk"),
    (75.15, 42.273, -0.79, 0.328, 2.748, "walk"), (75.119, 42.286, -0.79, 0.328, 2.748, "walk"),
    (75.087, 42.299, -0.79, 0.328, 2.748, "walk"), (75.056, 42.312, -0.79, 0.328, 2.748, "walk"),
    (75.024, 42.325, -0.79, 0.328, 2.748, "walk"), (74.992, 42.339, -0.79, 0.328, 2.748, "walk"),
    (74.961, 42.352, -0.79, 0.328, 2.748, "walk"), (74.929, 42.365, -0.79, 0.328, 2.748, "walk"),
    (74.897, 42.378, -0.79, 0.328, 2.748, "walk"), (74.866, 42.391, -0.79, 0.328, 2.748, "walk"),
    (74.834, 42.404, -0.79, 0.328, 2.748, "walk"), (74.803, 42.417, -0.79, 0.328, 2.748, "walk"),
    (74.771, 42.43, -0.79, 0.328, 2.748, "walk"), (74.739, 42.444, -0.79, 0.328, 2.748, "walk"),
    (74.708, 42.457, -0.79, 0.328, 2.748, "walk"), (74.676, 42.47, -0.79, 0.328, 2.748, "walk"),
    (74.645, 42.483, -0.79, 0.328, 2.748, "walk"), (74.613, 42.496, -0.79, 0.328, 2.748, "walk"),
    (74.581, 42.509, -0.79, 0.328, 2.748, "walk"), (74.55, 42.522, -0.79, 0.328, 2.748, "walk"),
    (74.518, 42.535, -0.79, 0.328, 2.748, "walk"), (74.487, 42.549, -0.79, 0.328, 2.748, "walk"),
    (74.455, 42.562, -0.79, 0.328, 2.748, "walk"), (74.423, 42.575, -0.79, 0.328, 2.748, "walk"),
    (74.392, 42.588, -0.79, 0.328, 2.748, "walk"), (74.36, 42.601, -0.79, 0.328, 2.748, "walk"),
    (74.329, 42.614, -0.79, 0.328, 2.748, "walk"), (74.297, 42.627, -0.79, 0.328, 2.748, "walk"),
    (74.265, 42.64, -0.79, 0.328, 2.748, "walk"), (74.234, 42.653, -0.79, 0.328, 2.748, "walk"),
    (74.202, 42.667, -0.79, 0.328, 2.748, "walk"), (74.171, 42.68, -0.79, 0.328, 2.748, "walk"),
    (74.139, 42.693, -0.79, 0.328, 2.748, "walk"), (74.107, 42.706, -0.79, 0.328, 2.748, "walk"),
    (74.076, 42.719, -0.79, 0.328, 2.748, "walk"), (74.044, 42.732, -0.79, 0.328, 2.748, "walk"),
    (74.013, 42.745, -0.79, 0.328, 2.748, "walk"), (73.981, 42.758, -0.79, 0.328, 2.748, "walk"),
    (73.949, 42.772, -0.79, 0.328, 2.748, "walk"), (73.918, 42.785, -0.79, 0.328, 2.748, "walk"),
    (73.886, 42.798, -0.79, 0.328, 2.748, "walk"), (73.854, 42.811, -0.79, 0.328, 2.748, "walk"),
    (73.823, 42.824, -0.79, 0.328, 2.748, "walk"), (73.791, 42.837, -0.79, 0.328, 2.748, "walk"),
    (73.76, 42.85, -0.79, 0.328, 2.748, "walk"), (73.728, 42.863, -0.79, 0.328, 2.748, "walk"),
    (73.696, 42.876, -0.79, 0.328, 2.748, "walk"), (73.665, 42.89, -0.79, 0.328, 2.748, "walk"),
    (73.633, 42.903, -0.79, 0.328, 2.748, "walk"), (73.602, 42.916, -0.79, 0.328, 2.748, "walk"),
    (73.57, 42.929, -0.79, 0.328, 2.748, "walk"), (73.538, 42.942, -0.79, 0.328, 2.748, "walk"),
    (73.507, 42.955, -0.79, 0.328, 2.748, "walk"), (73.475, 42.968, -0.79, 0.328, 2.748, "walk"),
    (73.444, 42.981, -0.79, 0.328, 2.748, "walk"), (73.412, 42.995, -0.79, 0.328, 2.748, "walk"),
    (73.38, 43.008, -0.79, 0.328, 2.748, "walk"), (73.349, 43.021, -0.79, 0.328, 2.748, "walk"),
    (73.317, 43.034, -0.79, 0.328, 2.748, "walk"), (73.286, 43.047, -0.79, 0.328, 2.748, "walk"),
    (73.254, 43.06, -0.79, 0.328, 2.748, "walk"), (73.222, 43.073, -0.79, 0.328, 2.748, "walk"),
    (73.191, 43.086, -0.79, 0.328, 2.748, "walk"), (73.159, 43.099, -0.79, 0.328, 2.748, "walk"),
    (73.128, 43.113, -0.79, 0.328, 2.748, "walk"), (73.096, 43.126, -0.79, 0.328, 2.748, "walk"),
    (73.064, 43.139, -0.79, 0.328, 2.748, "walk"), (73.033, 43.152, -0.79, 0.328, 2.748, "walk"),
    (73.001, 43.165, -0.79, 0.328, 2.748, "walk"), (72.97, 43.178, -0.79, 0.328, 2.748, "walk"),
    (72.938, 43.191, -0.79, 0.328, 2.748, "walk"), (72.906, 43.204, -0.79, 0.328, 2.748, "walk"),
    (72.875, 43.218, -0.79, 0.328, 2.748, "walk"), (72.843, 43.231, -0.79, 0.328, 2.748, "walk"),
    (72.812, 43.244, -0.79, 0.328, 2.748, "walk"), (72.78, 43.257, -0.79, 0.328, 2.748, "walk"),
    (72.748, 43.27, -0.79, 0.328, 2.748, "walk"), (72.717, 43.283, -0.79, 0.328, 2.748, "walk"),
    (72.685, 43.296, -0.79, 0.328, 2.748, "walk"), (72.654, 43.309, -0.79, 0.328, 2.748, "walk"),
    (72.622, 43.322, -0.79, 0.328, 2.748, "walk"), (72.59, 43.336, -0.79, 0.328, 2.748, "walk"),
    (72.559, 43.349, -0.79, 0.328, 2.748, "walk"), (72.527, 43.362, -0.79, 0.328, 2.748, "walk"),
    (72.495, 43.375, -0.79, 0.328, 2.748, "walk"), (72.464, 43.388, -0.79, 0.328, 2.748, "walk"),
    (72.432, 43.401, -0.79, 0.328, 2.748, "walk"), (72.401, 43.414, -0.79, 0.328, 2.748, "walk"),
    (72.369, 43.427, -0.79, 0.328, 2.748, "walk"), (72.337, 43.441, -0.79, 0.328, 2.748, "walk"),
    (72.306, 43.454, -0.79, 0.328, 2.748, "walk"), (72.274, 43.467, -0.79, 0.328, 2.748, "walk"),
    (72.243, 43.48, -0.79, 0.328, 2.748, "walk"), (72.211, 43.493, -0.79, 0.328, 2.748, "walk"),
    (72.179, 43.506, -0.79, 0.328, 2.748, "walk"), (72.148, 43.519, -0.79, 0.328, 2.748, "walk"),
    (72.116, 43.532, -0.79, 0.328, 2.748, "walk"), (72.085, 43.546, -0.79, 0.328, 2.748, "walk"),
    (72.053, 43.559, -0.79, 0.328, 2.748, "walk"), (72.021, 43.572, -0.79, 0.328, 2.748, "walk"),
    (71.99, 43.585, -0.79, 0.328, 2.748, "walk"), (71.958, 43.598, -0.79, 0.328, 2.748, "walk"),
    (71.927, 43.611, -0.79, 0.328, 2.748, "walk"), (71.895, 43.624, -0.79, 0.328, 2.748, "walk"),
    (71.863, 43.637, -0.79, 0.328, 2.748, "walk"), (71.832, 43.65, -0.79, 0.328, 2.748, "walk"),
    (71.807, 43.661, -0.618, 0.257, 2.748, "walk"), (71.782, 43.671, -0.618, 0.257, 2.748, "walk"),
    (71.758, 43.681, -0.618, 0.257, 2.748, "walk"), (71.733, 43.692, -0.618, 0.257, 2.748, "walk"),
    (71.708, 43.702, -0.618, 0.257, 2.748, "walk"), (71.683, 43.712, -0.618, 0.257, 2.748, "walk"),
    (71.659, 43.722, -0.618, 0.257, 2.748, "walk"), (71.634, 43.733, -0.618, 0.257, 2.748, "walk"),
    (71.609, 43.743, -0.621, 0.257, 2.75, "walk"), (71.584, 43.753, -0.621, 0.257, 2.75, "walk"),
    (71.56, 43.763, -0.621, 0.257, 2.75, "walk"), (71.543, 43.77, -0.414, 0.171, 2.505, "stand"),
    (71.526, 43.777, -0.412, 0.17, 2.261, "stand"), (71.51, 43.784, -0.411, 0.17, 2.017, "stand"),
    (71.494, 43.791, -0.409, 0.169, 1.772, "stand"), (71.477, 43.797, -0.407, 0.168, 1.656, "stand"),
    (71.461, 43.804, -0.406, 0.168, 1.668, "stand"), (71.445, 43.811, -0.404, 0.167, 1.68, "stand"),
    (71.429, 43.817, -0.402, 0.166, 1.692, "stand"), (71.413, 43.824, -0.401, 0.166, 1.705, "stand"),
    (71.397, 43.831, -0.401, 0.165, 1.718, "stand"), (71.381, 43.837, -0.4, 0.165, 1.731, "stand"),
    (71.365, 43.844, -0.398, 0.164, 1.745, "stand"), (71.349, 43.85, -0.397, 0.164, 1.76, "stand"),
    (71.333, 43.857, -0.396, 0.163, 1.775, "stand"), (71.317, 43.863, -0.395, 0.163, 1.79, "stand"),
    (71.302, 43.87, -0.394, 0.162, 1.806, "stand"), (71.286, 43.876, -0.392, 0.162, 1.823, "stand"),
    (71.27, 43.883, -0.391, 0.161, 1.84, "stand"), (71.255, 43.889, -0.39, 0.161, 1.857, "stand"),
    (71.239, 43.896, -0.389, 0.16, 1.876, "stand"), (71.224, 43.902, -0.388, 0.16, 1.895, "stand"),
    (71.208, 43.908, -0.386, 0.16, 1.914, "stand"), (71.193, 43.915, -0.385, 0.159, 1.934, "stand"),
    (71.177, 43.921, -0.384, 0.159, 1.955, "stand"), (71.162, 43.927, -0.383, 0.158, 1.977, "stand"),
    (71.147, 43.934, -0.382, 0.158, 1.999, "stand"), (71.132, 43.94, -0.381, 0.158, 2.022, "stand"),
    (71.116, 43.946, -0.38, 0.157, 2.046, "stand"), (71.101, 43.953, -0.379, 0.157, 2.07, "stand"),
    (71.086, 43.959, -0.379, 0.157, 2.096, "stand"), (71.071, 43.965, -0.378, 0.156, 2.122, "stand"),
    (71.056, 43.971, -0.377, 0.156, 2.148, "stand"), (71.041, 43.978, -0.375, 0.155, 2.176, "stand"),
    (71.026, 43.984, -0.374, 0.155, 2.204, "stand"), (71.011, 43.99, -0.372, 0.154, 2.233, "stand"),
    (70.996, 43.996, -0.37, 0.153, 2.262, "stand"), (70.982, 44.002, -0.366, 0.152, 2.292, "stand"),
    (70.967, 44.008, -0.36, 0.149, 2.323, "stand"), (70.953, 44.014, -0.351, 0.145, 2.354, "stand"),
    (70.939, 44.008, -0.345, -0.135, 2.386, "stand"), (70.926, 43.992, -0.337, -0.415, 2.63, "walk"),
    (70.914, 43.966, -0.307, -0.652, 2.874, "walk"), (70.903, 43.931, -0.276, -0.861, 3.119, "walk"),
    (70.892, 43.889, -0.253, -1.052, -2.92, "walk"), (70.883, 43.84, -0.234, -1.234, -2.676, "walk"),
    (70.863, 43.787, -0.5, -1.322, -2.431, "walk"), (70.833, 43.732, -0.755, -1.387, -2.187, "walk"),
    (70.793, 43.674, -0.993, -1.431, -2.177, "walk"), (70.745, 43.616, -1.215, -1.462, -2.264, "walk"),
    (70.688, 43.556, -1.421, -1.485, -2.334, "walk"), (70.623, 43.496, -1.616, -1.503, -2.392, "walk"),
    (70.551, 43.436, -1.799, -1.518, -2.441, "walk"), (70.472, 43.374, -1.972, -1.533, -2.481, "walk"),
    (70.387, 43.312, -2.138, -1.547, -2.515, "walk"), (70.295, 43.25, -2.296, -1.56, -2.545, "walk"),
    (70.197, 43.187, -2.447, -1.574, -2.57, "walk"), (70.093, 43.123, -2.592, -1.589, -2.592, "walk"),
    (69.984, 43.06, -2.741, -1.588, -2.616, "walk"), (69.868, 42.996, -2.884, -1.589, -2.638, "walk"),
    (69.747, 42.933, -3.02, -1.593, -2.656, "walk"), (69.621, 42.869, -3.15, -1.599, -2.672, "walk"),
    (69.49, 42.804, -3.276, -1.606, -2.686, "walk"), (69.354, 42.74, -3.398, -1.614, -2.698, "walk"),
    (69.214, 42.675, -3.516, -1.623, -2.709, "walk"), (69.069, 42.61, -3.631, -1.63, -2.72, "walk"),
]


def test_setting_off_the_feet_do_not_leave_the_grass_together():
    """Found by the blind critic of this change's second draft: h10 setting off from standing (seed 7 at
    1:43) lifted his right foot, which hovered low while his pace grew, then his left on its phase:
    both rose together, a hop. A foot whose stance is over waits for the other to be past the middle
    of its swing (unless the leg can no longer reach it). Both feet are high for less than a whole
    flight: at 3.3 m/s a flight lasts about 3 frames (half of a 0.72 s stride less a 0.233 s stance,
    Swinnen et al. 2026); without the rule, 3; with it, 1 (the bound, 2, was set after measuring an
    earlier draft). Drawn as clip.py draws him."""
    from ninety.render.scene import advance_gaits as advance

    frames = [{"ball": {"x": 80.0, "y": 50.0, "z": 0.0, "vx": 0.0, "vy": 0.0}, "possessor": None,
               "players": [{"id": "h1", "x": x, "y": y, "vx": vx, "vy": vy, "heading": h, "action": a,
                            "dive": 0.0}]} for x, y, vx, vy, h, a in H10_SET_OFF]
    h10 = Look("h1", "home", "ST", 1.732, 1.085, "#8d5a3b", "#d9c08c")  # as seed 7 draws him
    g, prev, drawn = Gait(), {}, []
    for i, fr in enumerate(frames):
        advance({"h1": g}, prev, fr, 1 / FPS, frames[min(i + LEAD_AHEAD_FRAMES, len(frames) - 1)])
        pl = fr["players"][0]
        body_parts(pl["x"], pl["y"], h10, g)
        pose = mesh_pose(g, pl["x"], pl["y"], 0.0)
        drawn.append((pose, pose_markers(pose, g.heading, h10.height_m), None, g.speed))
    assert _both_up_runs(drawn) <= 2, _both_up_runs(drawn)
    # Off the grass, the leg reaches where the stride carries the foot (within 10 cm): a foot left
    # further behind than the leg reaches as he sped away had the knee fold it up toward the seat,
    # 26 to 38 cm above its path for three frames.
    for i, (pose, m, _, _) in enumerate(drawn):
        for s in "lr":
            plant = pose[f"plant_{s}"]
            if plant and plant[3] > 0.05:
                assert m[f"foot_{s}"][2] - plant[3] < 0.10, (i, s, m[f"foot_{s}"][2], plant[3])


# The runner's bob, knee fold, lean and arms (lesson 180). Measured on the drawn mesh: the pelvis
# joint, the knee and the trunk from the posed bones, the feet from the skinned markers.
def _joint(pose, bone, height=1.84):
    """World position of a posed bone's joint for one frame's pose (heading 0, as _run_frames runs)."""
    head, _ = _fk(pose_angles(pose, 0.0, height))
    return to_world(pose["x"], pose["y"], 0.0, height, head[_bone_index()[bone]], pose.get("lift") or 0.0)


def _knee_fold(pose, side):
    """Degrees the knee is bent: between the thigh and the shin."""
    hip, knee, ankle = (_joint(pose, f"{b}_{side}") for b in ("thigh", "calf", "foot"))
    u, v = [knee[i] - hip[i] for i in range(3)], [ankle[i] - knee[i] for i in range(3)]
    c = sum(a * b for a, b in zip(u, v, strict=True)) / (math.dist(hip, knee) * math.dist(knee, ankle))
    return math.degrees(math.acos(max(-1.0, min(1.0, c))))


def _trunk(pose):
    """Degrees the trunk leans forward of upright: pelvis to neck, along the way he runs."""
    p, n = _joint(pose, "pelvis"), _joint(pose, "neck_01")
    return math.degrees(math.atan2(n[0] - p[0], n[2] - p[2]))


@pytest.mark.parametrize("speed", [3.0, 4.5, 6.0])
def test_a_runners_hips_are_lowest_on_the_grass_and_rise_in_the_air(speed):
    """Old (0.5.9): the hips were drawn level, a jog at 3 to 4 m/s gliding like a power-walk. Running,
    the centre of mass rises and falls 7.5 to 8.7 cm a step (scene.RUN_BOB: Fadillioglu 2022, Hanley
    2022, Gullstrand 2009), lowest at mid-stance (Lee and Farley 1998) and in free fall in the air.
    The drawn hips bob within 30% of it (set after measuring: the drawn stance is shortened to the
    leg's reach, which lengthens the drawn flight), and are higher with both feet in the air than
    with a foot on the grass under them, by at least half of it."""
    drawn = _draw(_run_frames([speed] * 110))["h1"][40:]
    hips = [_joint(p, "pelvis")[2] for p, _, _, _ in drawn]
    bob = _table(RUN_BOB, speed)
    assert 0.7 * bob <= max(hips) - min(hips) <= 1.3 * bob, (speed, max(hips) - min(hips), bob)
    air = [z for z, (_, m, _, _) in zip(hips, drawn, strict=True)
           if min(m["foot_l"][2], m["foot_r"][2]) > 0.03]
    under = [z for z, (_, m, r, _) in zip(hips, drawn, strict=True)
             if any(m[f"foot_{s}"][2] < 0.02 and abs(r[f"foot_{s}"][0]) < 0.15 for s in "lr")]
    assert air and under, (speed, len(air), len(under))
    assert sum(air) / len(air) - sum(under) / len(under) >= 0.5 * bob, (speed, air, under)


@pytest.mark.parametrize("speed", [1.0, 1.6])
def test_a_walkers_hips_are_highest_over_the_standing_leg(speed):
    """Old (0.5.9): level hips at a walk. Walking, the body vaults over the standing leg: highest at
    mid-stance and lowest as the weight passes from one foot to the other, 3.6 cm at 1.0 m/s and
    4.8 at 1.6 (Orendurff et al. 2004). The drawn hips within 30% (set after measuring), and higher,
    by at least half of it, with a foot on the grass under them (within 10 cm) than without."""
    drawn = _draw(_run_frames([speed] * 110))["h1"][40:]
    hips = [_joint(p, "pelvis")[2] for p, _, _, _ in drawn]
    bob = _table(WALK_BOB, speed)
    assert 0.7 * bob <= max(hips) - min(hips) <= 1.3 * bob, (speed, max(hips) - min(hips), bob)
    over, other = [], []
    for z, (_, m, r, _) in zip(hips, drawn, strict=True):
        under = any(m[f"foot_{s}"][2] < 0.02 and abs(r[f"foot_{s}"][0]) < 0.10 for s in "lr")
        (over if under else other).append(z)
    assert over and other, (speed, len(over), len(other))
    assert sum(over) / len(over) - sum(other) / len(other) >= 0.5 * bob, (speed, over, other)


@pytest.mark.parametrize("speed,peak", [(2.5, 93.5), (3.5, 108.7)])
def test_a_running_knee_folds_as_far_as_a_runners(speed, peak):
    """Old (0.5.9): a swinging knee folded to 77 degrees at 2.5 m/s and 90 at 3.5, the foot carried at
    a walk's height. Runners fold it to 93.5 and 108.7 degrees (Fukuchi et al. 2017, Table 4): the
    drawn peak within 5 degrees."""
    drawn = _draw(_run_frames([speed] * 90))["h1"][40:]
    top = max(_knee_fold(p, s) for p, _, _, _ in drawn for s in "lr")
    assert abs(top - peak) <= 5.0, (speed, top, peak)


def test_the_trunk_leans_into_a_sprint_start_and_comes_up_braking():
    """Old (0.5.9): the trunk kept the stride's lean whatever the pace did. Speeding up at a m/s^2 the
    body leans atan(a / g) so the ground's push passes through it (Kugler and Janshen 2010); slowing,
    the trunk comes back up to upright and no further. Setting off at 4 m/s^2, as he passes 3, 4 and
    5 m/s the drawn trunk leans at least 0.7 of atan(4 / g) beyond its lean at that speed held (it
    eases in over a few frames); braking at 6 m/s^2 it is upright, within 1 degree behind and 3 ahead
    of his standing trunk."""
    up = [0.0] * 10 + [min(6.0, 0.16 * i) for i in range(1, 40)] + [6.0] * 30
    down = [max(1.0, 6.0 - 0.24 * i) for i in range(1, 22)]
    drawn = _draw(_run_frames(up + down))["h1"]
    want = 0.7 * math.degrees(math.atan(4.0 / 9.81))
    for i in (19, 25, 31):  # 3.04, 4.0 and 4.96 m/s
        v = drawn[i][3]
        held = _trunk(_draw(_run_frames([v] * 50))["h1"][-1][0])
        assert _trunk(drawn[i][0]) - held >= want, (v, _trunk(drawn[i][0]), held, want)
    stand = _trunk(drawn[5][0])
    for p, _, _, v in drawn[-15:]:  # braking, from 4.6 m/s
        assert stand - 1.0 <= _trunk(p) <= stand + 3.0, (v, _trunk(p), stand)


def test_the_arms_swing_wider_toward_a_sprint():
    """Old (0.5.9): from 4 m/s up the arms kept the stored run's swing, the shoulder through 83
    degrees, so a sprinting arm moved no more than a jogging one. A sprinter's shoulder swings
    through 118 to 135 degrees at top speed (Mann and Herman 1985); the drawn swing widens toward it
    (scene.PUMP): at 7 m/s within 10% of 83 times the pump, and wider than at 4.5 m/s."""
    def swing(speed):
        drawn = _draw(_run_frames([speed] * 70))["h1"][40:]
        angles = []
        for p, _, _, _ in drawn:
            sh, el = _joint(p, "upperarm_l"), _joint(p, "lowerarm_l")
            angles.append(math.degrees(math.atan2(el[0] - sh[0], sh[2] - el[2])))
        return max(angles) - min(angles)

    jog, sprint = swing(4.5), swing(7.0)
    assert abs(sprint / (83.0 * _table(PUMP, 7.0)) - 1.0) <= 0.1, (sprint, 83.0 * _table(PUMP, 7.0))
    assert sprint > jog * 1.1, (jog, sprint)


@pytest.mark.parametrize("speed", [5.0, 7.0, 8.5])
def test_a_sprints_flight_is_seen_over_two_frames_or_more(speed):
    """Old (0.5.9): sprinting, a foot was drawn on the grass for the frame it lifted, by then 40 to 56
    cm behind the hips, beyond the leg's reach; the leg hung toward it and both feet were seen off
    the grass together (5 cm up) for one frame a step, a flicker. A sprinter's flight is 0.12 s or
    so, 3 frames at 25 fps; drawn, both feet are up for at least 2 frames every step."""
    drawn = _draw(_run_frames([speed] * 100))["h1"][40:]
    runs, run = [], 0
    for _, m, _, _ in drawn:
        if min(m["foot_l"][2], m["foot_r"][2]) > 0.05:
            run += 1
        elif run:
            runs.append(run)
            run = 0
    assert len(runs) >= 6 and min(runs) >= 2, (speed, runs)
