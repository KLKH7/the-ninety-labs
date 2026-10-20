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
from dataclasses import dataclass, field

from ninety.render.camera import Camera
from ninety.render.meshpose import arm_points, gait_foot
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


# How a turn is drawn (design, renderer only: the engine's heading and position are unchanged).
# The hips lead: they face where the engine has him face LEAD_AHEAD_FRAMES later (0.12 s), at
# most LEAD_MAX ahead of the chest, which faces the engine's heading (what collides is what is
# drawn, P11). A foot on the grass keeps its place and the way it points; the hips turn over it
# until the hip runs out of rotation (HIP_ROT, inside the hip's 35 to 45 degree range either way),
# then it pivots on the spot. Standing, a foot that has fallen STEP_DIST behind where it would
# stand, or STEP_YAW behind the way the hips face, steps there: one foot at a time, each step
# STEP_FRAMES long and lifting STEP_LIFT, so a turn on the spot is a run of short steps.
LEAD_AHEAD_FRAMES = 3
LEAD_MAX = 0.4
HIP_ROT = 0.7
STEP_YAW = 0.45
STEP_DIST = 0.25
STEP_FRAMES = 7  # 0.28 s at 25 fps
STEP_LIFT = 0.08
STEP_PEAK_MPS = 3.0  # the fastest a stepping foot travels (design: a quick step, not a kick)
SETTLE = 0.5  # standing still, a foot that far (as a share of the step limits) squares up
# Where a standing foot sits under the hips: the asset's rest pose (foot marker, object metres
# for a 1.84 m body): lateral, forward.
FOOT_HOME = (0.219, 0.127)
ANKLE_BACK = 0.11  # the drawn ankle sits this far behind the foot marker (asset rest pose)
# The furthest ahead of the hips the mesh's leg puts a flat foot on the grass, for a 1.84 m body
# (measured from the asset: 1 cm short of a plant 0.30 m ahead, 3.6 cm at 0.35, 13.5 cm at 0.45).
# A run lands no further, or the drawn foot lands short and slides forward to its plant.
PLANT_AHEAD_MAX = 0.30
# The gait plants their feet. A touch with the foot or thigh is taken in stride: the other foot stays
# planted and the touch takes the one that meets the ball.
PLANT_ACTIONS = ("stand", "walk", "run", "chest", "head", "strike", "foot", "thigh", "hands")
# Running, each foot is planted over the part of the stride where the gait (meshpose.gait) has it
# on the grass: the stored stride swings a foot along one path and it is lowest and going back
# around these phases (measured on the asset: the left foot is forward at 1.5 pi and lifts behind
# after 2 pi). The leg takes and gives back the plant over PLANT_EASE_FRAMES.
STANCE_CENTRE = {"l": 1.75 * math.pi, "r": 0.75 * math.pi}
PLANT_EASE_FRAMES = 3
FRAME_S = 0.04  # one frame at the engine's 25 fps (ninety.sim.engine.FPS)
MESH_ARM_ACTIONS = ("strike", "foot", "thigh", "chest", "head", "hands", "shield")
HIP_PIVOT_Z = 0.99  # the mesh's spine_01 joint, where a bend over the ball starts (asset rest pose)

# How a touch is drawn (design). The engine says which part met the ball and the frame says where
# the ball was. The touching part reaches that point on the contact frame, along the way the touch
# pushed the ball (its change of velocity): drawn back over TOUCH_WIND_S, through the ball, on
# for TOUCH_FOLLOW_S. A harder touch swings further. Its weight rises over the window up to
# TOUCH_SET_S before contact and falls over TOUCH_RECOVER_S after the follow-through.
TOUCH_WIND_S = 0.2
TOUCH_FOLLOW_S = 0.2
TOUCH_SET_S = 0.04  # a touch's part is on its path this long before the contact frame
# After the follow-through the part comes back to the stride, and the hips back up out of a lunge,
# over TOUCH_RECOVER_S: a body does not snap back upright in two frames.
TOUCH_RECOVER_S = 0.28
# How a kick is drawn (design, renderer only: the engine says when the ball left and how fast). A
# strike, or a touch that sends the ball away at KICK_OUT_MIN or faster, is a swing of the leg: the
# foot goes back and up behind the hip over KICK_BACK_S (the knee folding, the thigh behind the
# body), swings through over KICK_SWING_S, speeding up, to meet the ball on the contact frame, and
# follows through the way the ball went, rising, over KICK_FOLLOW_S. A harder kick (power, 0 at
# KICK_OUT_MIN to 1 at KICK_OUT_MAX) draws further back, higher, and follows further. The shape is
# that of the instep kick (backswing, forward swing, follow-through: Lees and Nolan 1998, J Sports
# Sci 16:211-234; Kellis and Katis 2007, J Sports Sci Med 6:154-165, *verify* the timings).
KICK_BACK_S = 0.2
KICK_SWING_S = 0.12
KICK_FOLLOW_S = 0.16
KICK_OUT_MIN = 6.0
KICK_OUT_MAX = 25.0
KICK_BACK_M = (0.25, 0.45)  # foot behind the hip at the top of the backswing, soft to hard
KICK_UP_M = (0.30, 0.55)  # its height off the grass
KICK_FOLLOW_M = (0.25, 0.55)  # how far on past the ball it follows through
KICK_RISE_M = (0.15, 0.45)  # and how far it rises doing so
# A keeper holding the ball (the frame names him possessor and his pose is hands) has a hand either
# side of it (meshpose.HOLD_SIDE). A ball below HOLD_STAND_Z (centre height, a 1.84 m body) is taken
# bent over it: the trunk bends forward by up to HOLD_BEND and the hips drop by up to HOLD_DROP_M,
# deepest at a ball on the grass (design; a keeper scooping up a ground ball stoops to it). The hands
# go to the ball over HOLD_EASE_S before he has it and leave it as long after.
HOLD_STAND_Z = 1.0
HOLD_BEND = 1.5
HOLD_DROP_M = 0.33  # as low as the planted legs still reach with flat feet (measured on the asset)
HOLD_EASE_S = 0.16
TOUCH_PARTS = ("foot", "thigh", "chest", "head")
HEADER_LIFT_MAX = 0.3  # a header above the standing brow is drawn as a jump, at most this high
HEADER_AIR_S = 0.24  # half the time in the air
# A foot reaching a ball beyond a standing leg's reach lunges: the hips drop until the leg (hip to
# sole LEG_M, for a 1.84 m body, from the asset) reaches it from a hip HIP_SIDE_M to that side,
# by at most LUNGE_MAX (design). The engine's foot reaches 1 m from his centre (P14).
LEG_M = 0.9
HIP_SIDE_M = 0.1
HIP_M = 0.91
LUNGE_MAX = 0.3
# With the hips lowered (a lunge, a stoop) a foot stays down while it is within LOW_HOLD_M of where
# it would stand; a body moving on past it steps it back under him (design: inside the 0.3 to 0.45 m
# the lowered leg was measured to reach with a flat foot).
LOW_HOLD_M = 0.3
LOW_M = 0.05  # how far the hips drop before the body counts as lowered (a lunge, a stoop)


def _wrap(a: float) -> float:
    return (a + math.pi) % (2 * math.pi) - math.pi


def _ease(u: float) -> float:
    u = min(max(u, 0.0), 1.0)
    return u * u * (3.0 - 2.0 * u)


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
    plant_l: tuple[float, ...] | None = None  # world (x, y, yaw, lift) of a foot the mesh puts there
    plant_r: tuple[float, ...] | None = None
    down_l: bool = False
    down_r: bool = False
    lead: float = 0.0  # how far the hips are ahead of the chest in a turn (radians)
    feet: dict = field(default_factory=dict)  # side -> foot on the grass or stepping (_stance)
    ankle: dict = field(default_factory=dict)  # side -> last drawn sole (x, y, height): where a step starts
    touch: dict | None = None  # the part meeting the ball now: part, side, at (world), w
    hold: dict | None = None  # a held ball: at (world, its centre), w, bend
    lift: float = 0.0  # metres the body is raised (a header's jump) or lowered (a lunge, a stoop)


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
                  dt: float, ahead: dict | None = None) -> None:
    """One frame of every player's gait: stride from how far he moved, and the way he faces, his
    speed and his pose from the engine (face), so the body is drawn turned as it collides.
    `ahead` is the engine's frame LEAD_AHEAD_FRAMES on: the hips lead into the turn it holds."""
    bx, by = frame["ball"]["x"], frame["ball"]["y"]
    later = {pl["id"]: pl for pl in ahead["players"]} if ahead else {}
    for pl in frame["players"]:
        g = gaits[pl["id"]]
        px, py = prev_xy.get(pl["id"], (pl["x"], pl["y"]))
        update_gait(g, pl["x"] - px, pl["y"] - py, dt, (bx - pl["x"], by - pl["y"]))
        prev_xy[pl["id"]] = (pl["x"], pl["y"])
        face(g, pl)
        nxt = later.get(pl["id"])
        g.lead = 0.0
        if nxt is not None and "heading" in nxt and "heading" in pl and g.action not in ("dive", "throw"):
            g.lead = min(max(_wrap(nxt["heading"] - pl["heading"]), -LEAD_MAX), LEAD_MAX)


def contacts(frames: list[dict], events: list[dict] | None = None) -> dict[str, list[dict]]:
    """Every touch the engine drew, per player: the frame the part meets the ball, the part, which
    side of him the ball was, where the ball was, and how the touch changed its velocity.

    A touch names its part from the frame it happened (scene pose, engine TOUCH_POSE_S), so that
    frame shows the ball as it left the part. A strike is drawn over its wind-up; the ball leaves on
    the frame after the last one, so the last wind-up frame shows the ball still at his foot. A
    tackle that pokes the ball loose has no pose of its own (engine.poke): its event names the
    tackler and the frame, and his foot is drawn meeting the ball there.
    """
    found: list[tuple[str, int, str, int, int]] = []
    prev: dict[str, str] = {}
    for i, fr in enumerate(frames):
        for pl in fr["players"]:
            a, was = pl.get("action", ""), prev.get(pl["id"], "")
            prev[pl["id"]] = a
            if a in TOUCH_PARTS and a != was:
                found.append((pl["id"], i, a, max(i - 1, 0), i))
            elif was == "strike" and a != "strike" and i > 0:
                found.append((pl["id"], i - 1, "strike", i - 1, i))
    index = {fr.get("frame", i): i for i, fr in enumerate(frames)}
    seen = {(who, at) for who, at, *_ in found}
    for ev in events or ():
        i = index.get(ev.get("frame"))
        if ev.get("type") == "tackle" and ev.get("player") and i and (ev["player"], i) not in seen:
            found.append((ev["player"], i, "foot", i - 1, i))
    out: dict[str, list[dict]] = {}
    for pid, at, part, v_in, v_out in sorted(found, key=lambda f: (f[1], f[0])):
        who = next((p for p in frames[at]["players"] if p["id"] == pid), None)
        if who is None:
            continue
        bi, bo = frames[v_in]["ball"], frames[v_out]["ball"]
        b = frames[at]["ball"]
        if part != "strike":
            # The part met the ball inside the tick, where its path from the frame before
            # passed closest to him; by this frame the ball has flown on from there.
            b = _closest(bi, bo, who["x"], who["y"])
        dvx = bo.get("vx", 0.0) - bi.get("vx", 0.0)
        dvy = bo.get("vy", 0.0) - bi.get("vy", 0.0)
        h = who.get("heading", 0.0)
        hx, hy = math.cos(h), math.sin(h)
        lateral = (b["x"] - who["x"]) * -hy + (b["y"] - who["y"]) * hx
        out.setdefault(pid, []).append({
            "frame": at,
            "part": part,
            "side": "l" if lateral >= 0 else "r",
            "ball": (b["x"], b["y"], b["z"] + BALL_RADIUS),
            "dv": (dvx, dvy),
            "out": math.hypot(bo.get("vx", 0.0), bo.get("vy", 0.0)),
            "heading": h,
            "at": (who["x"], who["y"]),
        })
    return out


def _closest(a: dict, b: dict, x: float, y: float) -> dict:
    """The point of the ball's straight path from `a` to `b` nearest (x, y), in the pitch plane."""
    dx, dy = b["x"] - a["x"], b["y"] - a["y"]
    n = dx * dx + dy * dy
    t = 0.0 if n < 1e-12 else min(max(((x - a["x"]) * dx + (y - a["y"]) * dy) / n, 0.0), 1.0)
    return {"x": a["x"] + dx * t, "y": a["y"] + dy * t, "z": a["z"] + (b["z"] - a["z"]) * t}


def _kick(c: dict) -> bool:
    return c["part"] == "strike" or (c["part"] == "foot" and c["out"] >= KICK_OUT_MIN)


def _touch_window(c: dict) -> tuple[float, float]:
    """Seconds before and after the contact frame that the touch is drawn. A lunge starts going
    down as long before the touch as it takes to come back up after it."""
    if _kick(c):
        return -(KICK_BACK_S + KICK_SWING_S), KICK_FOLLOW_S + TOUCH_RECOVER_S
    return -max(TOUCH_WIND_S, TOUCH_RECOVER_S), TOUCH_FOLLOW_S + TOUCH_RECOVER_S


def _touch_weight(c: dict, u: float) -> float:
    lo, hi = _touch_window(c)
    if _kick(c):
        rise = _ease((u + KICK_BACK_S + KICK_SWING_S) / KICK_BACK_S)
    else:
        # The part sets off for the ball from the start of the window, so a foot that was far from
        # it (a poke from mid-stride) is not flung there in a few frames.
        rise = _ease((u - lo) / (-lo - TOUCH_SET_S))
    return min(rise, _ease((hi - u) / TOUCH_RECOVER_S))


def touch_at(g: Gait, mine: list[dict], fi: int, height_m: float, fps: int,
             x: float | None = None, y: float | None = None) -> None:
    """Set the part meeting the ball at frame `fi` (g.touch) and any jump to a header (g.lift).
    (x, y) is where he is now; a kick's backswing is drawn behind his hips there."""
    g.touch, g.lift = None, 0.0
    best = None
    for c in mine:
        u = (fi - c["frame"]) / fps
        lo, hi = _touch_window(c)
        if lo < u < hi:
            w = _touch_weight(c, u)
            if w <= 0.0 and c["part"] not in ("foot", "strike"):
                continue
            # Two touches close together: the one further into its swing is drawn.
            if best is None or w > best[2] or (w == best[2] and abs(u) < abs(best[1])):
                best = (c, u, w)
    if best is None:
        return
    c, u, w = best
    k = height_m / 1.84
    part = c["part"]
    dvx, dvy = c["dv"]
    n = math.hypot(dvx, dvy)
    dx, dy = (dvx / n, dvy / n) if n > 0.5 else (math.cos(c["heading"]), math.sin(c["heading"]))
    bx, by, bz = c["ball"]
    gap = {"foot": 0.02, "strike": 0.02, "thigh": 0.05}.get(part, 0.02)
    px, py = bx - dx * (BALL_RADIUS + gap), by - dy * (BALL_RADIUS + gap)
    pz = max(bz - 0.07, 0.03) if part in ("foot", "strike") else bz - 0.05 if part == "thigh" else bz
    if _kick(c):
        at = _kick_path(c, u, (px, py, pz), (dx, dy), g.heading,
                        c["at"] if x is None or y is None else (x, y), k)
    else:
        if part == "foot":
            back = min(max(0.12 + 0.012 * c["out"], 0.12), 0.4) * k
            follow = min(max(0.08 + 0.01 * c["out"], 0.08), 0.35) * k
            rise = 0.6
        else:
            back, follow, rise = 0.08 * k, 0.05 * k, 0.0
        if u < 0:
            s = min(u / TOUCH_WIND_S, 1.0) ** 2 if u > -TOUCH_WIND_S else 1.0
            off, up = -back * s, back * rise * s
        else:
            # Past the follow-through it stays there while it eases back to the stride.
            q = math.sin(0.5 * math.pi * min(u / TOUCH_FOLLOW_S, 1.0))
            off, up = follow * q, follow * rise * 0.5 * q
        at = (px + dx * off, py + dy * off, pz + up)
    if u > 0 and x is not None and y is not None:
        # After the ball has gone the follow-through goes on with him: a part left reaching for a
        # spot on the grass he has run past drags the leg out behind him.
        at = (at[0] + x - c["at"][0], at[1] + y - c["at"][1], at[2])
    g.touch = {
        "part": part,
        "side": c["side"],
        "at": [round(at[0], 4), round(at[1], 4), round(max(at[2], 0.02), 4)],
        "w": round(w, 4),
    }
    if part in ("foot", "strike"):
        far = math.hypot(px - c["at"][0], py - c["at"][1]) / k - HIP_SIDE_M
        if far > 0:
            hip = math.sqrt(max(LEG_M * LEG_M - far * far, 0.0))
            drop = min(max(HIP_M - hip, 0.0), LUNGE_MAX) * k
            # The hips go down over the whole wind-up and start back up as soon as the ball has
            # gone, over TOUCH_RECOVER_S: he does not run on crouched in the follow-through.
            lo, _ = _touch_window(c)
            sink = min(_ease((u - lo) / -lo), _ease((TOUCH_RECOVER_S - u) / TOUCH_RECOVER_S))
            g.lift = -round(drop * sink, 4)
    if part == "head":
        rise_m = min(pz - 1.70 * k, HEADER_LIFT_MAX)
        if rise_m > 0.02:
            g.lift = round(rise_m * max(0.0, 1.0 - (u / HEADER_AIR_S) ** 2), 4)


def _kick_path(c: dict, u: float, contact: tuple, d: tuple, heading: float, xy: tuple,
               k: float) -> tuple[float, float, float]:
    """Where the kicking foot is aimed `u` seconds from contact: back behind the hip, through the
    ball, on after it (KICK_*)."""
    power = min(max((c["out"] - KICK_OUT_MIN) / (KICK_OUT_MAX - KICK_OUT_MIN), 0.0), 1.0)

    def mix(span: tuple[float, float]) -> float:
        return (span[0] + (span[1] - span[0]) * power) * k

    hx, hy = math.cos(heading), math.sin(heading)
    sign = 1.0 if c["side"] == "l" else -1.0
    side = HIP_SIDE_M * k * sign
    back = mix(KICK_BACK_M)
    top = (xy[0] - hy * side - hx * back, xy[1] + hx * side - hy * back, mix(KICK_UP_M))
    if u <= -KICK_SWING_S:
        return top
    if u <= 0:
        t = 1.0 + u / KICK_SWING_S
        e = t * t  # the foot speeds up into the ball
        return tuple(top[i] + (contact[i] - top[i]) * e for i in range(3))
    q = math.sin(0.5 * math.pi * min(u / KICK_FOLLOW_S, 1.0))
    on, up = mix(KICK_FOLLOW_M) * q, mix(KICK_RISE_M) * q
    return (contact[0] + d[0] * on, contact[1] + d[1] * on, contact[2] + up)


def holds(frames: list[dict]) -> dict[str, list[tuple[int, int]]]:
    """Per keeper, the runs of frames (first, last) in which he holds the ball: the frame names him
    its possessor and his pose is hands."""
    out: dict[str, list[tuple[int, int]]] = {}
    for i, fr in enumerate(frames):
        who = fr.get("possessor")
        if not who:
            continue
        pl = next((p for p in fr["players"] if p["id"] == who), None)
        if pl is None or pl.get("action") != "hands":
            continue
        runs = out.setdefault(who, [])
        if runs and runs[-1][1] == i - 1:
            runs[-1] = (runs[-1][0], i)
        else:
            runs.append((i, i))
    return out


def hold_at(g: Gait, runs: list[tuple[int, int]], fi: int, ball: tuple[float, float, float],
            height_m: float, fps: int) -> None:
    """Set the hands on a held ball (g.hold), bending over it and dropping the hips if it is low."""
    g.hold = None
    ease = HOLD_EASE_S * fps
    w = 0.0
    for first, last in runs:
        if first - ease < fi < last + ease:
            w = max(w, min(_ease((fi - (first - ease)) / ease), _ease((last + ease - fi) / ease)))
    if w <= 0.0:
        return
    k = height_m / 1.84
    z = ball[2] + BALL_RADIUS
    depth = min(max((HOLD_STAND_Z * k - z) / ((HOLD_STAND_Z - BALL_RADIUS) * k), 0.0), 1.0)
    g.hold = {
        "at": [round(ball[0], 4), round(ball[1], 4), round(z, 4)],
        "w": round(w, 4),
        "bend": round(HOLD_BEND * depth, 4),
    }
    g.lift = min(g.lift, -round(HOLD_DROP_M * depth * k * w, 4))


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
    if g.action not in ("strike", "foot", "thigh"):
        return 0.0
    if g.touch is not None and g.touch["part"] in ("strike", "foot", "thigh"):
        return 1.0 if g.touch["side"] == "l" else -1.0
    if ball is None:
        return 0.0
    hx, hy = math.cos(g.heading), math.sin(g.heading)
    lateral = (ball[0] - x) * -hy + (ball[1] - y) * hx
    return 1.0 if lateral >= 0 else -1.0


def _step_frames(dist: float) -> int:
    """How many frames a step of `dist` metres takes: STEP_FRAMES, or longer for a long step, so
    the foot is never faster than STEP_PEAK_MPS (it covers its way in the middle 70% of the step,
    smoothstep, whose peak is 1.5 times its mean)."""
    return max(STEP_FRAMES, math.ceil(1.5 * dist / (0.7 * STEP_PEAK_MPS * FRAME_S)))


def _gait_pose(g: Gait, x: float, y: float) -> dict:
    return {"action": g.action, "speed": g.speed, "phase": g.phase, "lead": g.lead, "x": x, "y": y}


def _home(x: float, y: float, yaw: float, k: float, sign: float) -> tuple[float, float]:
    hx, hy = math.cos(yaw), math.sin(yaw)
    f, side = FOOT_HOME[1] * k, FOOT_HOME[0] * k * sign
    return (x + hx * f - hy * side, y + hy * f + hx * side)


def _feet(g: Gait, x: float, y: float, k: float) -> None:
    """Which feet are on the grass this frame, where, and pointing which way (g.feet, g.plant_*).

    Running, a foot lands a little ahead on its part of the stride and stays put until the stride
    lifts it. Standing or shuffling, the feet stay put and step when the body has turned or moved
    off them (STEP_*). Either way a foot on the grass keeps the way it pointed when it landed,
    pivoting only when the hip can turn no further (HIP_ROT).
    """
    pel = g.heading + g.lead
    busy = None
    if g.touch is not None and g.touch["w"] > 0 and g.touch["part"] in ("foot", "strike", "thigh"):
        busy = g.touch["side"]
    lunge = g.lift < -LOW_M * k  # the support foot stays down under a lunge, whatever the pose
    if (g.action not in PLANT_ACTIONS and not lunge) or g.lift > 0.02:
        g.feet = {}
    elif g.action != "stand" and g.speed >= 0.45 and not lunge:
        half = _duty(g.speed) * math.pi
        per_frame = 2 * math.pi * g.speed * FRAME_S / _stride(g.speed)
        ph = g.phase % (2 * math.pi)
        hx, hy = math.cos(g.heading), math.sin(g.heading)
        for side, sign in (("l", 1.0), ("r", -1.0)):
            off = _wrap(ph - STANCE_CENTRE[side])
            on = abs(off) < half
            foot = g.feet.get(side)
            if foot is not None and foot["swing"] is not None:
                foot = None
            if on and foot is None and not (g.down_l if sign > 0 else g.down_r):
                # Put down where the stride has the foot now, once that is within the leg's reach.
                gx, gy = gait_foot(_gait_pose(g, x, y), g.heading, k * 1.84, side)
                if (gx - x) * hx + (gy - y) * hy <= PLANT_AHEAD_MAX * k:
                    foot = {"x": gx, "y": gy, "yaw": pel, "z": 0.0, "swing": None}
            if foot is not None and math.hypot(foot["x"] - x, foot["y"] - y) > 0.72:
                foot = None
            if foot is not None:
                # The leg takes the plant over the first frames on the grass and gives it back to the
                # stride over the last, instead of jumping onto it and off it; a foot still planted
                # from standing lets go at the same pace.
                ease = PLANT_EASE_FRAMES * per_frame
                want = _ease((half - abs(off)) / ease) if on and ease > 0 else (1.0 if on else 0.0)
                foot["w"] = max(want, foot.get("w", want) - 1.0 / PLANT_EASE_FRAMES)
                if foot["w"] <= 0.0:
                    foot = None
            if foot is None:
                g.feet.pop(side, None)
            else:
                g.feet[side] = foot
    else:
        for side, sign in (("l", 1.0), ("r", -1.0)):
            hx_, hy_ = _home(x, y, pel, k, sign)
            foot = g.feet.get(side)
            if foot is None:
                # A foot coming out of a stride or a touch starts where it was drawn last: on the
                # grass it stays there, and in the air it comes down as a step to where it stands.
                # Either way the leg takes the plant over PLANT_EASE_FRAMES.
                fx, fy, fz = g.ankle.get(side, (hx_, hy_, 0.0))
                foot = {"x": fx, "y": fy, "yaw": pel, "z": fz, "swing": None, "w": 0.0}
                if fz > 0.02:
                    frames = _step_frames(math.hypot(fx - hx_, fy - hy_))
                    foot["swing"], foot["over"] = (fx, fy, pel, 0, frames, fz), False
            foot["w"] = min(1.0, foot.get("w", 1.0) + 1.0 / PLANT_EASE_FRAMES)
            if foot["swing"] is not None:
                sx, sy, syaw, age, steps, *rest = foot["swing"]
                z0 = rest[0] if rest else 0.0
                age += 1
                # It travels while it is off the grass, and once over its spot comes straight down
                # there, however the hips go on turning.
                e = _ease((age / steps - 0.15) / 0.7)
                if not foot.get("over"):
                    foot["x"], foot["y"] = sx + (hx_ - sx) * e, sy + (hy_ - sy) * e
                    foot["yaw"] = syaw + _wrap(pel - syaw) * e
                    foot["over"] = e >= 1.0
                done = min(age / steps, 1.0)
                foot["z"] = z0 * (1.0 - done) + STEP_LIFT * k * math.sin(math.pi * done)
                foot["swing"] = None if age >= steps else (sx, sy, syaw, age, steps, z0)
                if foot["swing"] is None:
                    foot["z"], foot["over"] = 0.0, False
            g.feet[side] = foot
        stepping = any(f["swing"] is not None for f in g.feet.values())
        if not stepping:
            # Once the body has stopped turning he squares up: a foot half as far off steps too.
            settle = SETTLE if abs(g.lead) < 0.05 else 1.0
            worst = None
            for side, sign in (("l", 1.0), ("r", -1.0)):
                foot = g.feet[side]
                hx_, hy_ = _home(x, y, pel, k, sign)
                off = math.hypot(foot["x"] - hx_, foot["y"] - hy_)
                if side == busy:
                    continue  # the touching foot is the touch's (its plant is where its swing starts)
                if lunge and off < LOW_HOLD_M * k:
                    continue  # lowered, he keeps a foot down while the leg still reaches it
                err = max(
                    off / (STEP_DIST * k * settle),
                    abs(_wrap(foot["yaw"] - pel)) / (STEP_YAW * settle),
                )
                if err >= 1.0 and (worst is None or err > worst[0]):
                    worst = (err, side)
            if worst is not None:
                foot = g.feet[worst[1]]
                hx_, hy_ = _home(x, y, pel, k, 1.0 if worst[1] == "l" else -1.0)
                frames = _step_frames(math.hypot(foot["x"] - hx_, foot["y"] - hy_))
                foot["swing"], foot["over"] = (foot["x"], foot["y"], foot["yaw"], 0, frames), False
    for foot in g.feet.values():
        if foot["swing"] is None:
            # The hips turn over a planted foot until the hip will turn no further; then it pivots.
            rel = _wrap(foot["yaw"] - pel)
            if abs(rel) > HIP_ROT:
                foot["yaw"] = pel + math.copysign(HIP_ROT, rel)
    for side in ("l", "r"):
        foot = g.feet.get(side)
        plant = None
        if foot is not None:
            plant = (round(foot["x"], 4), round(foot["y"], 4), round(foot["yaw"], 4), round(foot["z"], 4),
                     round(foot.get("w", 1.0), 4))
        down = foot is not None and foot["swing"] is None
        if side == "l":
            g.plant_l, g.down_l = plant, down
        else:
            g.plant_r, g.down_r = plant, down


def _reach_leg(hip, knee, ankle, toe, touch: dict, fwd: tuple[float, float], k: float):
    """The touching leg's capsules, eased from the stride toward the ball by the touch's weight.

    A foot reaches with its sole (the mesh's foot marker) and its knee folds forward, both thigh
    and shin 0.42 m for a 1.84 m body; a thigh reaches with its knee and the shin hangs from it.
    """
    w = touch["w"]
    tx, ty, tz = touch["at"]
    seg = 0.42 * k
    if touch["part"] == "thigh":
        k2 = [tx, ty, max(tz, 0.3 * k)]
        a2 = [tx - fwd[0] * 0.05 * k, ty - fwd[1] * 0.05 * k, max(k2[2] - 0.40 * k, 0.06 * k)]
        t2 = [a2[0] + fwd[0] * 0.10 * k, a2[1] + fwd[1] * 0.10 * k, max(a2[2] - 0.04 * k, 0.04 * k)]
    else:
        a2 = [tx - fwd[0] * 0.08 * k, ty - fwd[1] * 0.08 * k, max(tz + 0.03 * k, 0.06 * k)]
        vx, vy, vz = a2[0] - hip[0], a2[1] - hip[1], a2[2] - hip[2]
        d = math.sqrt(vx * vx + vy * vy + vz * vz) or 1.0
        if d > 2 * seg:  # out of reach: the leg straight toward it
            a2 = [hip[0] + vx * 2 * seg / d, hip[1] + vy * 2 * seg / d, hip[2] + vz * 2 * seg / d]
            vx, vy, vz, d = a2[0] - hip[0], a2[1] - hip[1], a2[2] - hip[2], 2 * seg
        ux, uy, uz = vx / d, vy / d, vz / d
        dot = fwd[0] * ux + fwd[1] * uy
        nx, ny, nz = fwd[0] - dot * ux, fwd[1] - dot * uy, -dot * uz
        nn = math.sqrt(nx * nx + ny * ny + nz * nz)
        if nn < 1e-6:
            nx, ny, nz, nn = 0.0, 0.0, 1.0, 1.0
        bend = math.sqrt(max(seg * seg - (d / 2) ** 2, 0.0))
        k2 = [
            hip[0] + vx / 2 + nx / nn * bend,
            hip[1] + vy / 2 + ny / nn * bend,
            hip[2] + vz / 2 + nz / nn * bend,
        ]
        t2 = [a2[0] + fwd[0] * 0.13 * k, a2[1] + fwd[1] * 0.13 * k, max(a2[2] - 0.03 * k, 0.04 * k)]

    def mix(p, q):
        return [round(p[i] + (q[i] - p[i]) * w, 4) for i in range(3)]

    return mix(knee, k2), mix(ankle, a2), mix(toe, t2)


def mesh_pose(g: Gait, x: float, y: float, reach: float) -> dict:
    """What the page needs to pose the mesh this frame (render.js anglesFor, meshpose.pose_angles)."""
    return {
        "action": g.action,
        "phase": round(g.phase, 4),
        "speed": round(g.speed, 3),
        "reach": reach,
        "dive": round(g.dive, 3),
        "plant_l": [round(v, 4) for v in g.plant_l] if g.plant_l else None,
        "plant_r": [round(v, 4) for v in g.plant_r] if g.plant_r else None,
        "lead": round(g.lead, 4),
        "lift": round(g.lift, 4),
        "touch": g.touch,
        "hold": g.hold,
        "x": round(x, 4),
        "y": round(y, 4),
    }


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
    pressing = g.action == "run" or (g.action not in ("dive", "throw") and g.speed >= 2.2)
    step = _step_m(g.speed)
    if g.action == "throw":
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
    if g.action == "chest":
        lean = -0.14 * k  # the chest opens onto a ball he is under
    elif g.action == "head":
        lean = 0.12 * k
    _feet(g, x, y, k)
    touch = g.touch if g.touch is not None and g.touch["w"] > 0 else None
    hold = g.hold if g.hold is not None and g.hold["w"] > 0 else None
    lift = g.lift
    # Away from the gait the arms are labelled where the mesh draws them: balancing a kick, spread
    # for a chest control, reaching for a held ball (meshpose.arm_points). The gait's own capsule
    # arms stay: standing they fill the engine's body outline (P11).
    mesh_arms = None
    if hold is not None or touch is not None or g.action in MESH_ARM_ACTIONS:
        mesh_arms = arm_points(mesh_pose(g, x, y, 0.0), g.heading, look.height_m)

    def at(f: float, side: float, z: float) -> list[float]:
        # A dive reaches sideways and folds the body down. The feet stay on the grass.
        if dive and z > 0.35:
            side += dive * (0.25 + 0.7 * min(z / 1.5, 1.0)) * k
            z -= abs(dive) * 0.42 * k * min((z - 0.35) / 1.2, 1.0)
        return [
            round(x + hx * f + lx * side, 4), round(y + hy * f + ly * side, 4), round(max(z + lift, 0.02), 4)
        ]

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

    strided = {side: gait_foot(_gait_pose(g, x, y), g.heading, look.height_m, side, with_height=True)
               for side in ("l", "r")}
    sleeve_r = 0.06 * k
    arm_r = 0.048 * k
    # The outer edge of the sleeves is the shoulder breadth over the deltoids (shape.py, P11).
    shoulder_y = shape.SHOULDER_BREADTH_M / 2 - sleeve_r
    parts = []
    for side, sign in (("l", 1.0), ("r", -1.0)):
        # The same stride as the mesh's (meshpose.gait): at sin(phase) = 1 the right foot is forward.
        swing = -amp * s * sign
        # The hips lead the chest in a turn (g.lead), so the hip joints sit turned by it.
        hip = at(-0.10 * k * sign * math.sin(g.lead), 0.10 * k * sign * math.cos(g.lead), 0.92 * k)
        plant = g.plant_l if sign > 0 else g.plant_r
        # Off the grass the leg is where the mesh's stride has it (meshpose.gait_foot): the knee
        # ahead of the line from hip to ankle, as a knee bends.
        gx, gy, gz = strided[side]
        ankle = [round(gx - hx * ANKLE_BACK * k, 4), round(gy - hy * ANKLE_BACK * k, 4),
                 round(0.08 * k + gz, 4)]
        toe = [round(gx + hx * 0.02 * k, 4), round(gy + hy * 0.02 * k, 4), round(0.05 * k + gz, 4)]
        knee = [
            round((hip[0] + ankle[0]) / 2 + hx * 0.10 * k, 4),
            round((hip[1] + ankle[1]) / 2 + hy * 0.10 * k, 4),
            round((hip[2] + ankle[2]) / 2 + 0.03 * k, 4),
        ]
        if plant is not None:
            # A foot on the grass stays where it landed, pointing the way it landed; the body moves
            # and turns over it. A stepping foot is lifted off the grass on its way. A stride's
            # plant is taken and given back over a few frames (its weight).
            fx, fy = math.cos(plant[2]), math.sin(plant[2])
            az = 0.08 * k + plant[3]
            ax, ay = plant[0] - fx * ANKLE_BACK * k, plant[1] - fy * ANKLE_BACK * k
            pk = [
                round((hip[0] + ax) / 2 + hx * 0.04 * k, 4),
                round((hip[1] + ay) / 2 + hy * 0.04 * k, 4),
                round((hip[2] + az) / 2 + 0.05 * k, 4),
            ]
            pa = [round(ax, 4), round(ay, 4), round(az, 4)]
            pt = [round(ax + fx * 0.13 * k, 4), round(ay + fy * 0.13 * k, 4), round(0.05 * k + plant[3], 4)]
            pw = plant[4] if len(plant) > 4 else 1.0
            knee, ankle, toe = ([round(a[i] + (b[i] - a[i]) * pw, 4) for i in range(3)]
                                for a, b in ((knee, pk), (ankle, pa), (toe, pt)))
        if touch is not None and touch["part"] in ("foot", "strike", "thigh") and touch["side"] == side:
            knee, ankle, toe = _reach_leg(hip, knee, ankle, toe, touch, (hx, hy), k)
        parts.append({"n": f"thigh_{side}", "a": hip, "b": knee, "r": round(0.085 * k * w, 4), "c": "shorts"})
        parts.append({"n": f"shin_{side}", "a": knee, "b": ankle, "r": round(0.058 * k * w, 4), "c": "socks"})
        parts.append({"n": f"boot_{side}", "a": ankle, "b": toe, "r": round(0.042 * k, 4), "c": "boots"})
        # Opposite arm, elbow kept bent so a run pumps instead of hanging straight. Standing, the
        # sleeve hangs inside the deltoid and the hand inside the shoulder breadth (shape.py, P11).
        pump = -swing * (1.35 if pressing else 0.65)
        shoulder = at(lean, shoulder_y * sign, 1.40 * k)
        if mesh_arms is not None:
            shoulder, elbow, hand = (mesh_arms[f"{j}_{side}"] for j in ("shoulder", "elbow", "hand"))
        elif g.action == "dive":
            elbow = at(lean, 0.32 * k * w * sign, 1.20 * k)
            hand = at(lean + dive * 0.10 * k, 0.42 * k * w * sign, 1.15 * k)
        elif g.action == "throw":
            # Both hands meet over the head, on the ball. A throw-in is not a kick.
            elbow = at(0.08, 0.18 * k * sign, 1.72)
            hand = at(0.28, 0.08 * sign, 1.96)
        else:
            elbow = at(pump * 0.55 + lean, shoulder_y * sign, 1.16 * k)
            hand = at(pump * 0.12 + lean, (shoulder_y + sleeve_r - arm_r) * sign, 0.93 * k)
        parts.append({"n": f"arm_{side}", "a": shoulder, "b": elbow, "r": round(sleeve_r, 4), "c": "shirt"})
        parts.append({"n": f"forearm_{side}", "a": elbow, "b": hand, "r": round(arm_r, 4), "c": "skin"})
    # Where each foot is drawn now, for a step that starts from it (_feet): on its plant, or where
    # the mesh's stride has it. The capsules' own stride is the label's, not the picture's.
    for side in ("l", "r"):
        plant = g.plant_l if side == "l" else g.plant_r
        if plant is not None and (len(plant) < 5 or plant[4] >= 0.5):
            g.ankle[side] = (plant[0], plant[1], plant[3])
        else:
            g.ankle[side] = strided[side]
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
    if touch is not None and touch["part"] in ("chest", "head"):
        _lean_to(parts, touch, head, (hx, hy), k, at(lean, 0.0, 1.28 * k))
    if hold is not None and hold["bend"] > 0:
        _bend_over(parts, hold["bend"] * hold["w"], at(0.0, 0.0, HIP_PIVOT_Z * k), (hx, hy))
    return parts


def _bend_over(parts: list[dict], angle: float, pivot: list[float], fwd: tuple[float, float]) -> None:
    """Turn the trunk, neck and head forward about the hips, as the mesh's spine bends over a held
    ball (meshpose.HOLD_BEND); the arms are the mesh's already."""
    c, s = math.cos(angle), math.sin(angle)

    def turn(p: list[float]) -> list[float]:
        f = (p[0] - pivot[0]) * fwd[0] + (p[1] - pivot[1]) * fwd[1]
        z = p[2] - pivot[2]
        f2, z2 = f * c + z * s, z * c - f * s
        return [round(p[0] + fwd[0] * (f2 - f), 4), round(p[1] + fwd[1] * (f2 - f), 4),
                round(max(pivot[2] + z2, 0.02), 4)]

    for part in parts:
        if part["n"] in ("torso", "torso_l", "torso_r", "neck", "head", "hair"):
            part["a"] = turn(part["a"])
            if "b" in part:
                part["b"] = turn(part["b"])


def _lean_to(parts: list[dict], touch: dict, head: list[float], fwd: tuple[float, float], k: float,
             chest: list[float]) -> None:
    """Lean the upper body so the chest or the brow meets the ball, eased by the touch's weight."""
    if touch["part"] == "head":
        point = [head[0] + fwd[0] * 0.12 * k, head[1] + fwd[1] * 0.12 * k, head[2] + 0.06 * k]
        moved = {"head": (1.0, 1.0), "hair": (1.0, 1.0), "neck": (0.5, 1.0)}
    else:
        point = [chest[0] + fwd[0] * 0.14 * k, chest[1] + fwd[1] * 0.14 * k, chest[2]]
        moved = {"head": (1.0, 1.0), "hair": (1.0, 1.0), "neck": (1.0, 1.0),
                 "torso": (0.0, 1.0), "torso_l": (0.0, 1.0), "torso_r": (0.0, 1.0),
                 "arm_l": (1.0, 1.0), "arm_r": (1.0, 1.0), "forearm_l": (1.0, 1.0), "forearm_r": (1.0, 1.0)}
    d = [(touch["at"][i] - point[i]) * touch["w"] for i in range(3)]
    n = math.sqrt(sum(v * v for v in d))
    cap = 0.35 * k
    if n > cap:
        d = [v * cap / n for v in d]
    for part in parts:
        if part["n"] not in moved:
            continue
        sa, sb = moved[part["n"]]
        part["a"] = [round(part["a"][i] + d[i] * sa, 4) for i in range(3)]
        if "b" in part:
            part["b"] = [round(part["b"][i] + d[i] * sb, 4) for i in range(3)]


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


def ball_live(prev: dict | None, frame: dict, pitch_x: float = 105.0, pitch_y: float = 68.0) -> bool:
    """The ball is on the pitch and in play: someone has it, or it moved since the last frame.

    A still ball nobody has is a dead ball waiting for a restart (Law 9: out of play after it
    crosses a line or the referee stops play), and a ball off the pitch is not in play either.
    A player standing beside a dead ball for the whole restart wait is not footage of a player
    hiding the ball in play: on seed 7004 that wait filled a crowded window (250 frames counted
    hidden, none hidden in the render).
    """
    b = frame["ball"]
    if not (0.0 <= b["x"] <= pitch_x and 0.0 <= b["y"] <= pitch_y):
        return False
    if frame.get("possessor") is not None or prev is None:
        return True
    a = prev["ball"]
    return (a["x"], a["y"], a["z"]) != (b["x"], b["y"], b["z"])


def crowded_start(
    frames: list[dict],
    n: int,
    earliest: int,
    latest: int,
    cam_positions: list[tuple[float, float, float]],
    step: int = 25,
) -> int:
    """Start frame of the n-frame window where the ball, in play, is most often behind a player.

    cam_positions[i] is where the broadcast lens stood at frame i. Occlusion is a matter of
    where players stand on the line from that lens to the ball, not of how many are near it:
    a crowd on the far side of the ball hides nothing. Players near the ball break ties.
    """
    hidden = [0] * (len(frames) + 1)  # prefix sums of hidden frames
    for i, f in enumerate(frames[: len(cam_positions)]):
        b = f["ball"]
        players = [(p["x"], p["y"]) for p in f["players"]]
        live = ball_live(frames[i - 1] if i else None, f)
        blocked = live and ball_hidden(cam_positions[i], (b["x"], b["y"], b["z"]), players)
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
