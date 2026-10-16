"""Scene geometry shared by the labels (Python) and the pixels (three.js).

Players are built from capsules (thighs, shins, torso, arms) and spheres (head, hair). Python
computes every capsule in world coordinates for every frame and sends them to the page, so the
geometry that is drawn and the geometry that is labelled are the same numbers. Standing, trunk and
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
STRIDE_M = 1.7  # ground covered per full running cycle

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


def sample_looks(players: list[dict], seed: int) -> list[Look]:
    rng = random.Random(f"looks-{seed}")
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
            )
        )
    return looks


@dataclass
class Gait:
    phase: float = 0.0
    heading: float = 0.0  # radians in the pitch plane
    speed: float = 0.0


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
    g.heading += diff * 0.25
    g.phase = (g.phase + 2 * math.pi * d / STRIDE_M) % (2 * math.pi)


def advance_gaits(gaits: dict[str, Gait], prev_xy: dict[str, tuple[float, float]], frame: dict,
                  dt: float) -> None:
    """One frame of every player's gait: stride from how far he moved, and the way he faces from
    the engine (face), so the body is drawn turned as it collides."""
    bx, by = frame["ball"]["x"], frame["ball"]["y"]
    for pl in frame["players"]:
        px, py = prev_xy.get(pl["id"], (pl["x"], pl["y"]))
        update_gait(gaits[pl["id"]], pl["x"] - px, pl["y"] - py, dt, (bx - pl["x"], by - pl["y"]))
        prev_xy[pl["id"]] = (pl["x"], pl["y"])
        face(gaits[pl["id"]], pl)


def face(g: Gait, player: dict) -> None:
    """Turn the drawn body the way the engine says he faces, when the frame says (the engine
    already limits how fast a body turns, GROUNDING P16), so it is drawn as it collides."""
    if "heading" in player:
        g.heading = player["heading"]


def body_parts(x: float, y: float, look: Look, g: Gait) -> list[dict]:
    """Capsules (a, b, r) and spheres (a only) in world metres, tagged with a colour slot."""
    k = look.height_m / 1.84
    w = look.build
    hx, hy = math.cos(g.heading), math.sin(g.heading)  # forward
    lx, ly = -hy, hx  # left
    amp = min(g.speed / 7.0, 1.0) * 0.38 * k
    s = math.sin(g.phase)

    def at(f: float, side: float, z: float) -> list[float]:
        return [round(x + hx * f + lx * side, 4), round(y + hy * f + ly * side, 4), round(z, 4)]

    sleeve_r = 0.06 * k
    # The outer edge of the sleeves is the shoulder breadth over the deltoids (shape.py, P11).
    shoulder_y = shape.SHOULDER_BREADTH_M / 2 - sleeve_r
    parts = []
    for side, sign in (("l", 1.0), ("r", -1.0)):
        swing = amp * s * sign
        hip = at(0.0, 0.10 * k * sign, 0.92 * k)
        knee = at(swing * 0.55 + 0.04 * k, 0.11 * k * sign, 0.50 * k + abs(swing) * 0.08)
        lift = 0.12 * k * (-swing / amp) if swing < 0 else 0.0  # the trailing foot comes off the grass
        ankle = at(swing, 0.11 * k * sign, 0.09 * k + lift)
        parts.append({"n": f"thigh_{side}", "a": hip, "b": knee, "r": round(0.085 * k * w, 4), "c": "shorts"})
        parts.append({"n": f"shin_{side}", "a": knee, "b": ankle, "r": round(0.062 * k * w, 4), "c": "socks"})
        arm_swing = -swing * 0.7
        shoulder = at(0.0, shoulder_y * sign, 1.40 * k)
        arm_r = 0.048 * k
        hand = at(arm_swing, (shoulder_y + sleeve_r - arm_r) * sign, 0.93 * k)  # hangs inside the deltoid
        parts.append({"n": f"arm_{side}", "a": shoulder, "b": hand, "r": round(arm_r, 4), "c": "skin"})
        parts.append(
            {
                "n": f"sleeve_{side}",
                "a": shoulder,
                "b": [round((shoulder[i] * 0.6 + hand[i] * 0.4), 4) for i in range(3)],
                "r": round(sleeve_r, 4),
                "c": "shirt",
            }
        )
    lean = min(g.speed / 7.0, 1.0) * 0.08 * k
    # The trunk: three capsules side by side, each as thick as the chest is deep, filling the width
    # up to the inside of the hanging arms, so at chest height, trunk and arms span the engine's
    # body (shape.py) across and front to back.
    half = shape.CHEST_DEPTH_M / 2
    arm_inner = shoulder_y + sleeve_r - 2 * 0.048 * k
    trunk_y = max(0.0, arm_inner - half)
    for side, sign in (("l", 1.0), ("", 0.0), ("r", -1.0)):
        parts.append(
            {
                "n": f"torso_{side}" if side else "torso",
                "a": at(0.0, trunk_y * sign, 0.98 * k),
                "b": at(lean, trunk_y * sign, 1.36 * k),
                "r": round(half, 4),
                "c": "shirt",
            }
        )
    parts.append(
        {
            "n": "neck",
            "a": at(lean, 0.0, 1.45 * k),
            "b": at(lean, 0.0, 1.52 * k),
            "r": round(0.05 * k, 4),
            "c": "skin",
        }
    )
    parts.append({"n": "head", "a": at(lean * 1.2, 0.0, 1.64 * k), "r": round(0.105 * k, 4), "c": "skin"})
    parts.append(
        {"n": "hair", "a": at(lean * 1.2 - 0.02, 0.0, 1.69 * k), "r": round(0.098 * k, 4), "c": "hair"}
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


def ball_parts(x: float, y: float, z: float) -> list[dict]:
    return [
        {
            "n": "ball",
            "a": [round(x, 4), round(y, 4), round(z + BALL_RADIUS, 4)],
            "r": BALL_RADIUS,
            "c": "ball",
        }
    ]


def drawn_ball(frame: dict) -> tuple[float, float, float]:
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


def crowded_start(frames: list[dict], n: int, earliest: int, latest: int, step: int = 25) -> int:
    """Start frame of the n-frame window with the most players near the ball."""
    best, best_score = earliest, -1.0
    for s in range(earliest, max(earliest, latest) + 1, step):
        window = frames[s : s + n : 5]
        if len(window) * 5 < n - 5:
            break
        score = sum(crowding(f) for f in window) / len(window)
        if score > best_score:
            best, best_score = s, score
    return best
