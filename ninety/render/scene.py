"""Scene geometry shared by the labels (Python) and the pixels (three.js).

Players are labelled from capsules (thighs, shins, torso, arms) and spheres (head, hair). Python
computes every capsule in world coordinates for every frame. The page skins a mesh inside that
volume and draws the capsules for the ball. The labelled box stays the capsule box. Standing, trunk and
arms are drawn to fill the body shape the engine's contact physics uses (ninety/sim/shape.py)
between hip and shoulder height, turned the way the engine says he faces. The legs are narrower
than that shape, and running, the arms swing and the trunk leans outside it (docs/GROUNDING.md,
P11).
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass

from ninety.render.camera import Camera
from ninety.sim import shape

BALL_RADIUS = 0.11
STRIDE_M = 1.7  # fallback, used only where a caller has no speed yet


def _step_m(speed: float) -> float:
    """One step. A walk stays near two a second. A jog at 3 m/s is about 1.1 m and 2.7 a
    second. A sprint stays near 4.4 a second and lengthens the step (Debaere 2013)."""
    if speed <= 1.6:
        return max(0.55, speed / 2.0)
    if speed <= 3.0:
        return 0.80 + (speed - 1.6) * (0.30 / 1.4)
    return min(1.10 + (speed - 3.0) * 0.125, 1.80)


def _stride(speed: float) -> float:
    """Ground covered by one full cycle, which is two steps."""
    return 2.0 * _step_m(speed)


def _duty(speed: float) -> float:
    """Share of the cycle a foot is down. A walk overlaps. A sprint has a flight phase."""
    t = min(max((speed - 1.6) / 5.4, 0.0), 1.0)
    return 0.62 - 0.24 * t


def turn_toward(heading: float, target: float, dt: float, rate: float = 5.0) -> float:
    """Face `target` without snapping. A body turns; it does not swap ends in one frame."""
    diff = (target - heading + math.pi) % (2 * math.pi) - math.pi
    cap = rate * dt
    if diff > cap:
        diff = cap
    elif diff < -cap:
        diff = -cap
    return heading + diff


SKIN_TONES = ("#f5d0b5", "#e8b897", "#d19a74", "#b07850", "#8d5a3b", "#6b4329", "#4a2e1d")
HAIR_COLORS = ("#1b1410", "#3b2516", "#6b4a2b", "#a37a4c", "#d9c08c", "#2b2b2b", "#8a3b1d")


@dataclass(frozen=True)
class Look:
    """Per-player appearance, fixed for the clip and logged in clip.json."""

    id: str
    team: str
    role: str
    height_m: float
    build: float  # 0.9 slim .. 1.15 broad
    skin: str
    hair: str
    hair_style: str = "short"  # bald, short, crown. A second draw, so the fields above stay put.


def sample_looks(players: list[dict], seed: int) -> list[Look]:
    rng = random.Random(f"looks-{seed}")
    # Own stream. Drawing it on `rng` would move the next player's height and shirt colour.
    shape = random.Random(f"looks-shape-{seed}")
    looks = []
    for p in players:
        looks.append(
            Look(
                id=p["id"],
                team=p["team"],
                role=p.get("role", ""),
                height_m=round(min(max(rng.gauss(1.81, 0.07), 1.65), 1.98), 3),
                build=round(rng.uniform(0.9, 1.15), 3),
                skin=rng.choice(SKIN_TONES),
                hair=rng.choice(HAIR_COLORS),
                hair_style=shape.choice(("bald", "short", "short", "crown")),
            )
        )
    return looks


@dataclass
class Gait:
    phase: float = 0.0
    heading: float = 0.0  # radians in the pitch plane, from the engine when it has one
    speed: float = 0.0
    action: str = "stand"  # the engine's pose: run, or the part that met the ball
    dive: float = 0.0  # -1..1, keeper reaching to his left or right
    plant_l: tuple[float, float] | None = None  # world xy of a foot that is down
    plant_r: tuple[float, float] | None = None
    down_l: bool = False
    down_r: bool = False


def update_gait(g: Gait, dx: float, dy: float, dt: float, face: tuple[float, float] | None) -> None:
    d = math.hypot(dx, dy)
    speed = d / dt
    g.speed += (speed - g.speed) * 0.3
    if d > 0.01:
        target = math.atan2(dy, dx)
    elif face is not None and math.hypot(*face) > 0.1:
        target = math.atan2(face[1], face[0])
    else:
        target = g.heading
    diff = (target - g.heading + math.pi) % (2 * math.pi) - math.pi
    g.heading = turn_toward(g.heading, g.heading + diff, dt)
    g.phase = (g.phase + 2 * math.pi * d / _stride(speed)) % (2 * math.pi)


def advance_gaits(gaits: dict[str, Gait], prev_xy: dict[str, tuple[float, float]], frame: dict,
                  dt: float) -> None:
    """One frame of every player's gait: stride from how far he moved, and the way he faces, his
    speed and his pose from the engine (face), so the body is drawn turned as it collides."""
    bx, by = frame["ball"]["x"], frame["ball"]["y"]
    for pl in frame["players"]:
        px, py = prev_xy.get(pl["id"], (pl["x"], pl["y"]))
        update_gait(gaits[pl["id"]], pl["x"] - px, pl["y"] - py, dt, (bx - pl["x"], by - pl["y"]))
        prev_xy[pl["id"]] = (pl["x"], pl["y"])
        face(gaits[pl["id"]], pl)


def face(g: Gait, player: dict) -> None:
    """Turn the drawn body the way the engine says he faces, when the frame says (the engine
    already limits how fast a body turns, GROUNDING P16), so it is drawn as it collides. The
    engine's speed and pose (run, strike, dive, throw, the part that met the ball) come with it."""
    if "heading" in player:
        g.heading = player["heading"]
    if "vx" in player:
        g.speed = math.hypot(player["vx"], player.get("vy", 0.0))
    if "action" in player:
        g.action = player["action"]
        g.dive = player.get("dive", 0.0)


def reach_sign(x: float, y: float, g: Gait, ball: tuple[float, ...] | None) -> float:
    """Which foot the ball is on: 1 is his left, -1 his right. 0 if the pose does not pick a side."""
    if ball is None or g.action not in ("strike", "foot", "thigh"):
        return 0.0
    hx, hy = math.cos(g.heading), math.sin(g.heading)
    lateral = (ball[0] - x) * -hy + (ball[1] - y) * hx
    return 1.0 if lateral >= 0 else -1.0


def body_parts(
    x: float, y: float, look: Look, g: Gait, ball: tuple[float, ...] | None = None
) -> list[dict]:
    """Capsules (a, b, r) and spheres (a only) in world metres, tagged with a colour slot.

    The heading, speed and action come from the engine. The stride phase is how far these
    feet have already travelled, so a run cycles instead of sliding.
    """
    k = look.height_m / 1.84
    w = look.build
    hx, hy = math.cos(g.heading), math.sin(g.heading)  # forward
    lx, ly = -hy, hx  # left
    speed_n = min(g.speed / 7.0, 1.0)
    # Under 4 m/s the engine calls it a walk. On the pitch that speed is a press, and it has to look like one.
    pressing = g.action == "run" or (g.action not in ("strike", "dive", "throw") and g.speed >= 2.2)
    step = _step_m(g.speed)
    if g.action == "strike":
        amp = 0.08 * k
    elif g.action == "throw":
        amp = 0.0
    elif g.action == "dive":
        amp = speed_n * 0.16 * k
    elif g.speed > 0.45:
        amp = min(step * 0.50, 0.62) * k
    else:
        amp = 0.0
    s = math.sin(g.phase)
    dive = g.dive if g.action == "dive" else 0.0
    lean = (0.16 if pressing else 0.05) * min(g.speed / 5.0, 1.0) * k
    if g.action == "strike":
        lean = 0.04 * k
    elif g.action == "chest":
        lean = -0.14 * k  # the chest opens onto a ball he is under
    elif g.action == "head":
        lean = 0.12 * k
    reach = None
    if ball is not None and g.action in ("strike", "foot", "thigh"):
        lateral = (ball[0] - x) * lx + (ball[1] - y) * ly
        reach = 1.0 if lateral >= 0 else -1.0
    if g.action in ("strike", "dive", "throw"):
        g.plant_l = g.plant_r = None
        g.down_l = g.down_r = False

    def at(f: float, side: float, z: float) -> list[float]:
        # A dive reaches sideways and folds the body down. The feet stay on the grass.
        if dive and z > 0.35:
            side += dive * (0.25 + 0.7 * min(z / 1.5, 1.0)) * k
            z -= abs(dive) * 0.42 * k * min((z - 0.35) / 1.2, 1.0)
        return [round(x + hx * f + lx * side, 4), round(y + hy * f + ly * side, 4), round(max(z, 0.02), 4)]

    def toward(of: float, os: float, oz: float, max_m: float) -> tuple[float, float, float]:
        """Body-frame point pulled toward the ball, and no further than the joint can reach."""
        if ball is None:
            return of, os, oz
        bz = ball[2] + BALL_RADIUS if len(ball) > 2 else 0.22
        tf = (ball[0] - x) * hx + (ball[1] - y) * hy
        ts = (ball[0] - x) * lx + (ball[1] - y) * ly
        vf, vs, vz = tf - of, ts - os, bz - oz
        dist = math.sqrt(vf * vf + vs * vs + vz * vz) or 1.0
        scale = min(1.0, max_m / dist)
        return of + vf * scale, os + vs * scale, max(oz + vz * scale, 0.02)

    sleeve_r = 0.06 * k
    arm_r = 0.048 * k
    # The outer edge of the sleeves is the shoulder breadth over the deltoids (shape.py, P11).
    shoulder_y = shape.SHOULDER_BREADTH_M / 2 - sleeve_r
    parts = []
    for side, sign in (("l", 1.0), ("r", -1.0)):
        swing = amp * s * sign
        kicking = g.action == "strike" and sign == reach
        receiving = g.action in ("foot", "thigh") and sign == reach
        hip = at(0.0, 0.10 * k * sign, 0.92 * k)
        plant = None
        if g.action not in ("strike", "dive", "throw") and g.speed >= 0.45 and not receiving:
            ph = g.phase % (2 * math.pi)
            window = _duty(g.speed) * 2 * math.pi
            on = ph < window if sign > 0 else ((ph - math.pi) % (2 * math.pi)) < window
            was = g.down_l if sign > 0 else g.down_r
            held = g.plant_l if sign > 0 else g.plant_r
            if on and not was:
                ahead = min(_duty(g.speed) * step, 0.58)
                held = (round(x + hx * ahead, 4), round(y + hy * ahead, 4))
            if not on:
                held = None
            if held is not None and math.hypot(held[0] - x, held[1] - y) > 0.72:
                held = None
                on = False
            if sign > 0:
                g.down_l, g.plant_l = on, held
            else:
                g.down_r, g.plant_r = on, held
            plant = held
        if kicking:
            knee = at(0.28 * k, 0.12 * k * sign, 0.72 * k)
            ankle = at(0.48 * k, 0.10 * k * sign, 0.38 * k)
            toe = at(0.62 * k, 0.10 * k * sign, 0.32 * k)
        elif g.action == "foot" and receiving:
            ff, fs, fz = toward(0.0, 0.10 * k * sign, 0.92 * k, 0.78 * k)
            knee = at(ff * 0.45, 0.11 * k * sign + fs * 0.2, max(fz, 0.32 * k))
            ankle = at(ff, fs, max(fz, 0.06 * k))
            toe = at(ff + 0.10 * k, fs, max(fz - 0.04 * k, 0.05 * k))
        elif g.action == "thigh" and receiving:
            ff, fs, fz = toward(0.0, 0.10 * k * sign, 0.92 * k, 0.46 * k)
            knee = at(ff, fs, max(fz, 0.55 * k))
            ankle = at(ff * 0.25, 0.11 * k * sign, 0.28 * k)
            toe = at(ff * 0.25 + 0.08 * k, 0.11 * k * sign, 0.12 * k)
        elif plant is not None:
            # The support foot stays where it landed. The body moves over it.
            az = 0.08 * k
            knee = [
                round((hip[0] + plant[0]) / 2, 4),
                round((hip[1] + plant[1]) / 2, 4),
                round((hip[2] + az) / 2 + 0.05 * k, 4),
            ]
            ankle = [round(plant[0], 4), round(plant[1], 4), round(az, 4)]
            toe = [round(plant[0] + hx * 0.13 * k, 4), round(plant[1] + hy * 0.13 * k, 4), round(0.05 * k, 4)]
        else:
            # The trailing foot recovers. The knee folds up over it, then the leg reaches out to land.
            recover = max(0.0, -swing) / amp if amp > 1e-4 else 0.0
            knee_lift = recover * (0.26 * k if pressing else 0.08 * k)
            foot_lift = recover * (0.16 * k if pressing else 0.035 * k)
            knee = at(swing * 0.40 + 0.05 * k, 0.11 * k * sign, 0.48 * k + knee_lift)
            ankle = at(swing, 0.11 * k * sign, 0.08 * k + foot_lift)
            toe = at(swing + 0.13 * k, 0.11 * k * sign, 0.05 * k + foot_lift * 0.85)
        parts.append({"n": f"thigh_{side}", "a": hip, "b": knee, "r": round(0.085 * k * w, 4), "c": "shorts"})
        parts.append({"n": f"shin_{side}", "a": knee, "b": ankle, "r": round(0.058 * k * w, 4), "c": "socks"})
        parts.append({"n": f"boot_{side}", "a": ankle, "b": toe, "r": round(0.042 * k, 4), "c": "boots"})
        # Opposite arm, elbow kept bent so a run pumps instead of hanging straight. Standing, the
        # sleeve hangs inside the deltoid and the hand inside the shoulder breadth (shape.py, P11).
        pump = -swing * (1.35 if pressing else 0.65)
        shoulder = at(lean, shoulder_y * sign, 1.40 * k)
        if kicking:
            elbow = at(lean + 0.08 * k, 0.24 * k * w * sign, 1.22 * k)
            hand = at(lean + 0.16 * k, 0.16 * k * w * sign, 1.05 * k)
        elif g.action == "dive":
            elbow = at(lean, 0.32 * k * w * sign, 1.20 * k)
            hand = at(lean + dive * 0.10 * k, 0.42 * k * w * sign, 1.15 * k)
        elif g.action == "throw":
            # Both hands meet over the head, on the ball. A throw-in is not a kick.
            elbow = at(0.08, 0.18 * k * sign, 1.72)
            hand = at(0.28, 0.08 * sign, 1.96)
        elif g.action == "chest":
            elbow = at(0.10 * k, 0.24 * k * sign, 1.28 * k)
            hand = at(0.22 * k, 0.10 * k * sign, 1.16 * k)
        elif g.action == "head":
            elbow = at(0.04 * k, 0.22 * k * sign, 1.34 * k)
            hand = at(-0.02 * k, 0.16 * k * sign, 1.12 * k)
        elif g.action == "hands":
            hf, hs, hz = toward(lean, 0.18 * k * sign, 1.40 * k, 0.55 * k)
            elbow = at(hf * 0.55, hs * 0.45 + 0.08 * k * sign, max(hz, 1.15 * k))
            hand = at(hf, hs, hz)
        elif g.action == "thigh" and receiving:
            elbow = at(lean, 0.28 * k * sign, 1.22 * k)
            hand = at(lean + 0.04 * k, 0.16 * k * sign, 1.02 * k)
        else:
            elbow = at(pump * 0.55 + lean, shoulder_y * sign, 1.16 * k)
            hand = at(pump * 0.12 + lean, (shoulder_y + sleeve_r - arm_r) * sign, 0.93 * k)
        parts.append({"n": f"arm_{side}", "a": shoulder, "b": elbow, "r": round(sleeve_r, 4), "c": "shirt"})
        parts.append({"n": f"forearm_{side}", "a": elbow, "b": hand, "r": round(arm_r, 4), "c": "skin"})
    # The trunk: three capsules side by side, each as thick as the chest is deep, filling the width
    # up to the inside of the hanging arms, so at chest height, trunk and arms span the engine's
    # body (shape.py) across and front to back.
    half = shape.CHEST_DEPTH_M / 2
    arm_inner = shoulder_y + sleeve_r - 2 * arm_r
    trunk_y = max(0.0, arm_inner - half)
    for side, sign in (("l", 1.0), ("", 0.0), ("r", -1.0)):
        parts.append(
            {
                "n": f"torso_{side}" if side else "torso",
                "a": at(lean * 0.4, trunk_y * sign, 0.98 * k),
                "b": at(lean, trunk_y * sign, 1.36 * k),
                "r": round(half, 4),
                "c": "shirt",
            }
        )
    parts.append(
        {
            "n": "neck",
            "a": at(lean, 0.0, 1.44 * k),
            "b": at(lean * 1.1, 0.0, 1.52 * k),
            "r": round(0.048 * k, 4),
            "c": "skin",
        }
    )
    if g.action == "head":
        hf, hs, hz = toward(lean, 0.0, 1.64 * k, 0.18 * k)
        head = at(hf, hs, hz)
    else:
        head = at(lean * 1.15, dive * 0.05 * k, 1.64 * k)
    parts.append({"n": "head", "a": head, "r": round(0.105 * k, 4), "c": "skin"})
    parts.append(
        {
            "n": "hair",
            "a": [head[0] - hx * 0.02, head[1] - hy * 0.02, round(head[2] + 0.05 * k, 4)],
            "r": round(0.09 * k, 4),
            "c": "hair",
        }
    )
    return parts


def parts_box(cam: Camera, parts: list[dict]) -> tuple[float, float, float, float] | None:
    """Analytic image box of a set of capsules and spheres, unclipped. None if behind the camera."""
    xs, ys = [], []
    f = cam.focal_px
    for p in parts:
        for key in ("a", "b"):
            if key not in p:
                continue
            c = tuple(p[key])
            uv = cam.project(c)
            if uv is None:
                return None
            rpx = f * p["r"] / cam.depth(c)
            xs += [uv[0] - rpx, uv[0] + rpx]
            ys += [uv[1] - rpx, uv[1] + rpx]
    return (min(xs), min(ys), max(xs), max(ys))


def ball_parts(x: float, y: float, z: float, spin: tuple[float, float, float] | None = None) -> list[dict]:
    part = {
        "n": "ball",
        "a": [round(x, 4), round(y, 4), round(z + BALL_RADIUS, 4)],
        "r": BALL_RADIUS,
        "c": "ball",
    }
    if spin is not None:
        part["spin"] = [round(spin[0], 4), round(spin[1], 4), round(spin[2], 4)]
    return [part]


def drawn_ball(frame: dict, carrier_heading: float | None = None) -> tuple[float, float, float]:
    """Where the ball is drawn: where the engine has it. A carrier's ball is already against his
    body on the side he faces (engine.py, tick_carrier), so it is drawn there, not moved."""
    b = frame["ball"]
    return (b["x"], b["y"], b["z"])


# ---- pitch keypoints ----------------------------------------------------------------------


def _keypoints() -> list[tuple[str, float, float]]:
    L, W, cy = 105.0, 68.0, 34.0
    pts = [
        ("corner_nl", 0, 0),
        ("corner_fl", 0, W),
        ("corner_nr", L, 0),
        ("corner_fr", L, W),
        ("half_near", L / 2, 0),
        ("half_far", L / 2, W),
        ("centre", L / 2, cy),
        ("circle_near", L / 2, cy - 9.15),
        ("circle_far", L / 2, cy + 9.15),
        ("circle_left", L / 2 - 9.15, cy),
        ("circle_right", L / 2 + 9.15, cy),
    ]
    for side, gx, s in (("l", 0.0, 1), ("r", L, -1)):
        pts += [
            (f"box_{side}_goal_near", gx, cy - 20.16),
            (f"box_{side}_goal_far", gx, cy + 20.16),
            (f"box_{side}_edge_near", gx + s * 16.5, cy - 20.16),
            (f"box_{side}_edge_far", gx + s * 16.5, cy + 20.16),
            (f"six_{side}_goal_near", gx, cy - 9.16),
            (f"six_{side}_goal_far", gx, cy + 9.16),
            (f"six_{side}_edge_near", gx + s * 5.5, cy - 9.16),
            (f"six_{side}_edge_far", gx + s * 5.5, cy + 9.16),
            (f"spot_{side}", gx + s * 11.0, cy),
            (f"post_{side}_near", gx, cy - 3.66),
            (f"post_{side}_far", gx, cy + 3.66),
        ]
        # where the penalty arc meets the box edge
        dy = math.sqrt(9.15**2 - 5.5**2)
        pts += [(f"arc_{side}_near", gx + s * 16.5, cy - dy), (f"arc_{side}_far", gx + s * 16.5, cy + dy)]
    return pts


KEYPOINTS = _keypoints()


def project_keypoints(cam: Camera) -> list[dict]:
    """Keypoints that fall inside the image, with exact pixel positions (visibility set later)."""
    out = []
    for name, x, y in KEYPOINTS:
        uv = cam.project((x, y, 0.0))
        if uv is None or not (0 <= uv[0] < cam.width and 0 <= uv[1] < cam.height):
            continue
        out.append({"name": name, "px": round(uv[0], 3), "py": round(uv[1], 3)})
    return out


# ---- clip window --------------------------------------------------------------------------


def crowding(frame: dict, radius: float = 4.0) -> int:
    bx, by = frame["ball"]["x"], frame["ball"]["y"]
    return sum(1 for p in frame["players"] if math.hypot(p["x"] - bx, p["y"] - by) <= radius)


# A player stands in for his drawn body: the torso capsule body_parts draws (radius 0.23 m at an
# average build) up to the mean height sample_looks draws (1.81 m). Only the window choice uses
# these; the labels still come from the drawn capsules and the pixels.
OCCLUDER_RADIUS_M = 0.23
OCCLUDER_HEIGHT_M = 1.81


def ball_hidden(cam_pos: tuple[float, float, float], ball: tuple[float, float, float], players) -> bool:
    """True if a player stands on the camera's line of sight to the ball's centre.

    The sight line is a segment from the lens to the ball. A player blocks it when he stands
    between the two in the pitch plane, within OCCLUDER_RADIUS_M of it, and the line passes
    him below OCCLUDER_HEIGHT_M. A player beside or behind the ball, or under a ball in the
    air, does not hide it, however close he is.
    """
    cx, cy, cz = cam_pos
    bx, by, bz = ball[0], ball[1], ball[2] + BALL_RADIUS
    dx, dy = bx - cx, by - cy
    reach2 = dx * dx + dy * dy
    if reach2 == 0:
        return False
    reach = math.sqrt(reach2)
    for px, py in players:
        ox, oy = px - cx, py - cy
        along = (ox * dx + oy * dy) / reach2  # 0 at the lens, 1 at the ball
        if not 0 < along < 1:
            continue
        if abs(ox * dy - oy * dx) / reach > OCCLUDER_RADIUS_M:
            continue
        if cz + along * (bz - cz) <= OCCLUDER_HEIGHT_M:
            return True
    return False


def crowded_start(
    frames: list[dict],
    n: int,
    earliest: int,
    latest: int,
    cam_positions: list[tuple[float, float, float]],
    step: int = 25,
) -> int:
    """Start frame of the n-frame window where the ball is most often behind a player.

    cam_positions[i] is where the broadcast lens stood at frame i. Occlusion is a matter of
    where players stand on the line from that lens to the ball, not of how many are near it:
    a crowd on the far side of the ball hides nothing. Players near the ball break ties.
    """
    hidden = [0] * (len(frames) + 1)  # prefix sums of hidden frames
    for i, f in enumerate(frames[: len(cam_positions)]):
        b = f["ball"]
        players = [(p["x"], p["y"]) for p in f["players"]]
        blocked = ball_hidden(cam_positions[i], (b["x"], b["y"], b["z"]), players)
        hidden[i + 1] = hidden[i] + blocked
    best, best_score = earliest, (-1, -1.0)
    for s in range(earliest, max(earliest, latest) + 1, step):
        if s + n > len(cam_positions):
            break
        window = frames[s : s + n : 5]
        score = (hidden[s + n] - hidden[s], sum(crowding(f) for f in window) / len(window))
        if score > best_score:
            best, best_score = s, score
    return best


# A goalkeeper's own touches and his dive: the actions the engine names when he handles the ball
# or throws himself at it (ninety/sim). Arms over the ball are what hides it from the lens.
KEEPER_ACTIONS = ("hands", "dive", "throw")
# The penalty area, 16.5 m from the goal line and 40.32 m wide (Law 1): where a keeper handles.
PENALTY_DEPTH_M = 16.5
PENALTY_HALF_WIDTH_M = 20.16


def keeper_busy(frame: dict) -> bool:
    return any(p.get("role") == "GK" and p.get("action") in KEEPER_ACTIONS for p in frame["players"])


def in_penalty_area(ball: dict, pitch_x: float = 105.0, pitch_y: float = 68.0) -> bool:
    near_goal = ball["x"] <= PENALTY_DEPTH_M or ball["x"] >= pitch_x - PENALTY_DEPTH_M
    return near_goal and abs(ball["y"] - pitch_y / 2) <= PENALTY_HALF_WIDTH_M


def keeper_start(frames: list[dict], n: int, earliest: int, latest: int, step: int = 25) -> int:
    """Start frame of the n-frame window where a goalkeeper most often handles or dives.

    A keeper's catch, parry or dive puts his arms and body over the ball, the situation `crowded`
    does not aim at: it ranks windows by outfield players on the sight line. Frames with the
    ball in a penalty area break ties, so a match with no keeper action still gets a goalmouth.
    """
    busy = [0] * (len(frames) + 1)
    box = [0] * (len(frames) + 1)
    for i, f in enumerate(frames):
        busy[i + 1] = busy[i] + keeper_busy(f)
        box[i + 1] = box[i] + in_penalty_area(f["ball"])
    best, best_score = earliest, (-1, -1)
    for s in range(earliest, max(earliest, latest) + 1, step):
        if s + n > len(frames):
            break
        score = (busy[s + n] - busy[s], box[s + n] - box[s])
        if score > best_score:
            best, best_score = s, score
    return best
