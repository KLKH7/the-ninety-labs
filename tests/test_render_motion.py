"""How the mesh turns and touches the ball, measured on the skinned body's own markers.

A turn on the spot is steps, not a figurine spun on its base: a foot on the grass stays put
while the hips turn over it, and moves only lifted, one foot at a time. A touch puts the
touching part on the ball on the frame the engine says it met it.
"""

import math

from ninety.render.meshpose import foot_yaw, pose_markers
from ninety.render.scene import (
    BALL_RADIUS,
    LEAD_AHEAD_FRAMES,
    LEAD_MAX,
    PLANT_AHEAD_MAX,
    Gait,
    Look,
    body_parts,
    contacts,
    mesh_pose,
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
        touch_at(g, mine, fi, LOOK.height_m, FPS)
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
    mine, drawn = _drawn_touch(_kick((50.2, 29.05), part="foot", out=(3.0, 0.0)))
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
