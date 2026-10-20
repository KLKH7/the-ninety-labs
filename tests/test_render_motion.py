"""How the mesh turns and touches the ball, measured on the skinned body's own markers.

A turn on the spot is steps, not a figurine spun on its base: a foot on the grass stays put
while the hips turn over it, and moves only lifted, one foot at a time. A touch puts the
touching part on the ball on the frame the engine says it met it; a kick gets there with a swing
of the leg. Arms hang standing and swing opposite the legs moving; a keeper holding the ball has
his hands on it.
"""

import math

from ninety.render.camera import Camera
from ninety.render.meshpose import HOLD_SIDE, foot_yaw, pose_markers
from ninety.render.scene import (
    BALL_RADIUS,
    KICK_SWING_S,
    LEAD_AHEAD_FRAMES,
    LEAD_MAX,
    PLANT_AHEAD_MAX,
    STEP_LIFT,
    Gait,
    Look,
    _step_m,
    body_parts,
    contacts,
    hold_at,
    holds,
    mesh_pose,
    parts_box,
    reach_sign,
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
    """Old: a touchdown up to 0.58 m ahead, which the leg could not reach, so the foot slid onto it."""
    for speed in (2.5, 4.0, 6.0, 8.0):
        g = Gait(action="run", speed=speed)
        x = 0.0
        landed = 0
        for i in range(40):
            g.phase = (i * 0.5) % (2 * math.pi)
            x += speed / FPS
            before = (g.plant_l, g.plant_r)
            body_parts(x, 0.0, LOOK, g)
            pose = mesh_pose(g, x, 0.0, 0.0)
            feet = pose_markers(pose, 0.0, 1.84)
            for s, was, now in (("l", before[0], g.plant_l), ("r", before[1], g.plant_r)):
                if now and not was:
                    landed += 1
                    assert now[0] - x <= PLANT_AHEAD_MAX + 1e-9
                    assert math.dist(feet[f"foot_{s}"][:2], now[:2]) < 0.03, (speed, s)
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
                assert math.dist(m[f"hand_{s}"], centre) < HOLD_SIDE * look.height_m / 1.84 + 0.06, (
                    z, fi, s, m[f"hand_{s}"])
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
            assert m[other][2] < STEP_LIFT + 0.04, (i, touch["part"], m[other])


def test_a_first_touch_then_a_strike_on_the_move_keeps_a_foot_on_the_grass():
    """Old (0.4.3): a pass cushioned with the left foot while walking at 3.1 m/s, then struck with
    the right, left the left foot's plant where it stood before the touch. By the strike the body
    was 2 m on, beyond the leg's reach, so the mesh hung that foot 0.3 to 0.6 m up while the right
    foot swung: the whole body in the air for half a second (render-check player_feet_in_boxes,
    seed 7, h3 at 23.5 s and h10 at 33.4 s). A foot that has played the ball comes back to the
    grass from where the touch drew it."""
    frames, x, v = [], 30.0, 3.1
    touch, strike = 20, (31, 33)  # the first frame of the cushion; the strike's wind-up frames
    for i in range(48):
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
        # Walking, a foot is always on the grass, or on a low step after the body (STEP_LIFT).
        low = min(m["foot_l"][2], m["foot_r"][2])
        assert -0.03 < low < STEP_LIFT + 0.04, (i, pose["touch"], m["foot_l"], m["foot_r"])


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
