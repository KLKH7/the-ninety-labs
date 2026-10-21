"""Poses for the match mesh. three.js skins these angles; the capsules stay the label box.

Object space is Y-up metres, +X the player's left, +Z the way he faces, feet on y = 0.
A positive bone X swings that limb back. Left-arm Z adducts positive, right-arm Z negative.
A bone's third angle, Y, twists it about its own length: on Root it turns the hips and legs
about the vertical, on the spine it turns the chest back, and on a thigh it turns the foot.

The pose dict is the one clip.py sends the page (scene.py decides every number in it).
render.js builds the same angles from the same pose; tests hold the two together.
"""

from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path

ASSET = Path(__file__).resolve().parents[2] / "web" / "render" / "assets" / "player.json"
# The asset's stature: the top of its skull, in the asset's own metres (the body mesh's highest
# vertex; its hair reaches 1.70). A player `height_m` tall is the asset scaled by
# height_m / ASSET_STATURE_M, so he is drawn as tall as he is. It was taken as 1.84 m, which drew
# every player at 91.5% of his height (lesson 157).
ASSET_STATURE_M = 1.684
# The forehead, where a header meets the ball: between the brows (1.59) and the top of the skull.
BROW_Y = 1.63

# Leg search. The same lists and steps run in render.js. Thigh Z is the sideways reach:
# a plant beside the hip is not on the line the thigh swings along. The grid finds the
# basin; halving steps then close on the target, so a foot that moves a little between
# frames moves a little on the screen instead of jumping from one grid point to the next.
THIGH_CAND = (-0.9, -0.55, -0.25, 0.05, 0.35, 0.6)
THIGH_Z = (-0.6, -0.4, -0.15, 0.0, 0.15, 0.4, 0.6)
CALF_CAND = (0.05, 0.35, 0.7, 1.1, 1.5)
LEG_STEP = (0.15, 0.1, 0.17, 0.15)
HEEL_CAND = (0.0, 0.35, 0.7)
# thigh X, thigh Z (sideways: the hip abducts about 45 degrees), calf (a knee does not bend
# backwards), heel lift
LEG_LIMIT = ((-1.8, 1.0), (-0.8, 0.8), (0.0, 2.2), (0.0, 0.9))
REFINE = 6
# Each refining round tries every neighbour of the best so far, diagonals included: lifting a foot
# moves the thigh and the knee together, which one angle at a time cannot find.
_MOVES3 = tuple(
    (a, b, c) for a in (-1, 0, 1) for b in (-1, 0, 1) for c in (-1, 0, 1) if (a, b, c) != (0, 0, 0)
)
_MOVES2 = tuple((a, b) for a in (-1, 0, 1) for b in (-1, 0, 1) if (a, b) != (0, 0))
PLANT_FOOT = 0.12  # the foot flat on the grass
STRIKE_FOOT = 0.4  # the instep: toes pointed, as the stored strike pose has them
PLANT_GIVE_UP = 0.45
FLOOR_SLACK = 0.02
# Between these speeds (m/s) the stand pose and the stride are blended (design): the engine's stand
# and walk meet at 0.5 m/s, and a switch there made the legs jump.
STAND_BLEND = (0.25, 0.9)
# Between these speeds (m/s) the walk's stride (walkScale) grows to the full stride (design, either
# side of the asset's fullStrideSpeed, 2.2 m/s, where the stride used to switch at once).
STRIDE_GROW = (1.6, 2.8)  # how far under the grass a blended foot may dip before it is put back on it
# The trunk's lean toward a ball on the chest or the head, shared by the lower spine and the neck.
LEAN_X = (-0.6, -0.4, -0.2, 0.0, 0.2, 0.4, 0.6)
LEAN_Z = (-0.4, -0.2, 0.0, 0.2, 0.4)
LEAN_STEP = (0.1, 0.1)
LEAN_LIMIT = ((-0.9, 0.9), (-0.6, 0.6))
LEAN_SHARE = (("spine_01", 0.35), ("spine_02", 0.35), ("neck_01", 0.3))
# The trunk's lean on top of the stride's (scene.pace), split down the spine as the stored run splits
# its own (spine_01 0.14, spine_02 0.08).
TRUNK_SHARE = (("spine_01", 0.14 / 0.22), ("spine_02", 0.08 / 0.22))
# The thigh points down, so a twist of +a about it turns the foot by -a about the vertical.
TWIST_SIGN = -1.0
# The surfaces a touch aims, not in the asset: (bone, rest point skinned wholly to it).
EXTRA = {
    "brow": ("head", (0.0, BROW_Y, 0.13)),
    "chest": ("spine_03", (0.0, 1.28, 0.14)),
    "thigh_top_l": ("thigh_l", (0.14, 0.64, 0.10)),
    "thigh_top_r": ("thigh_r", (-0.14, 0.64, 0.10)),
}

# A throw-in is drawn from the standing pose: its hands are on the ball wherever the engine has it
# (scene.throw_at, a hold), so the stored throw pose, arms over the head, is not used.
_CONTACT = {"strike", "foot", "thigh", "chest", "head", "hands", "dive", "shield"}
_FEET = ("strike", "foot", "thigh")  # touches taken in stride: the stored pose gives only the arms
# Holding the ball: the trunk bends over it (scene.py decides how far; this splits it down the
# spine, the neck taking some back so the eyes stay on the ball) and a hand goes either side of it,
# HOLD_SIDE from its centre: a ball's radius and a palm's thickness (design).
HOLD_BEND = (("spine_01", 0.45), ("spine_02", 0.4), ("spine_03", 0.15), ("neck_01", -0.3))
HOLD_SIDE = 0.14
# Arm search (the same lists in render.js): upper arm X (back +) and Z (toward the body), lower arm
# X and Z, Z given for the left arm and mirrored for the right. The elbow does not bend backwards:
# the limits keep the lower arm on the side of its rest pose that folds forward.
ARM_UX = (-2.2, -1.4, -0.7, 0.0)
ARM_UZ = (-0.4, 0.2, 0.6, 1.0)
ARM_LX = (-1.0, -0.4, 0.2)
ARM_LZ = (-0.3, 0.2, 0.6)
ARM_STEP = (0.3, 0.2, 0.25, 0.2)
ARM_LIMIT = ((-2.8, 1.0), (-0.8, 1.3), (-1.6, 0.6), (-0.6, 1.0))
ARM_PULL = 0.004
_MOVES4 = tuple(
    (a, b, c, d) for a in (-1, 0, 1) for b in (-1, 0, 1) for c in (-1, 0, 1) for d in (-1, 0, 1)
    if (a, b, c, d) != (0, 0, 0, 0)
)


@lru_cache(maxsize=1)
def asset() -> dict:
    return json.loads(ASSET.read_text())


@lru_cache(maxsize=1)
def _bone_index() -> dict[str, int]:
    return {b["name"]: i for i, b in enumerate(asset()["bones"])}


def _xzy(spec) -> tuple[float, float, float]:
    if isinstance(spec, (list, tuple)):
        return float(spec[0]), float(spec[1]), float(spec[2]) if len(spec) > 2 else 0.0
    return float(spec), 0.0, 0.0


def _xz(spec) -> tuple[float, float]:
    x, z, _ = _xzy(spec)
    return x, z


def _rot_x(angle: float) -> tuple:
    c, s = math.cos(angle), math.sin(angle)
    return ((1.0, 0.0, 0.0), (0.0, c, s), (0.0, -s, c))


def _rot_y(angle: float) -> tuple:
    c, s = math.cos(angle), math.sin(angle)
    return ((c, 0.0, -s), (0.0, 1.0, 0.0), (s, 0.0, c))


def _rot_z(angle: float) -> tuple:
    c, s = math.cos(angle), math.sin(angle)
    return ((c, s, 0.0), (-s, c, 0.0), (0.0, 0.0, 1.0))


def _matvec(cols, v):
    return (
        cols[0][0] * v[0] + cols[1][0] * v[1] + cols[2][0] * v[2],
        cols[0][1] * v[0] + cols[1][1] * v[1] + cols[2][1] * v[2],
        cols[0][2] * v[0] + cols[1][2] * v[1] + cols[2][2] * v[2],
    )


def _matmul(a, b):
    return tuple(_matvec(a, column) for column in b)


def _transpose(cols):
    return (
        (cols[0][0], cols[1][0], cols[2][0]),
        (cols[0][1], cols[1][1], cols[2][1]),
        (cols[0][2], cols[1][2], cols[2][2]),
    )


def _local_rot(spec) -> tuple:
    x, z, y = _xzy(spec)
    rot = _matmul(_rot_z(z), _rot_x(x))
    return _matmul(rot, _rot_y(y)) if y else rot


def _cols(flat) -> tuple:
    return (
        (flat[0], flat[1], flat[2]),
        (flat[3], flat[4], flat[5]),
        (flat[6], flat[7], flat[8]),
    )


def mirror(angles: dict) -> dict:
    """Swap left and right. Z and the twist flip: the right arm adducts the other way."""
    out = {}
    for key, spec in angles.items():
        if key.endswith("_l"):
            name = key[:-2] + "_r"
        elif key.endswith("_r"):
            name = key[:-2] + "_l"
        else:
            name = key
        x, z, y = _xzy(spec)
        if isinstance(spec, (list, tuple)):
            out[name] = (x, -z, -y) if len(spec) > 2 else (x, -z)
        else:
            out[name] = x
    return out


def scale(angles: dict, factor: float, keep_z: bool = False) -> dict:
    out = {}
    for key, spec in angles.items():
        x, z = _xz(spec)
        if isinstance(spec, (list, tuple)):
            out[key] = (x * factor, z if keep_z else z * factor)
        else:
            out[key] = x * factor
    return out


def gait(s: float, run: dict, walk: dict | None = None, arm_t: float = 1.0, pump: float = 1.0) -> dict:
    """s = sin(phase). +1 is the stored run (right foot forward). -1 is its mirror.

    The arms swing opposite the legs. Walking they swing from the shoulder with the elbows
    nearly straight (the stored walk); running the elbows bend to about a right angle, more in
    front than behind (the stored run). `arm_t` goes from the one to the other, and `pump` widens
    the upper arms' swing about its middle (scene.PUMP).
    """
    left, right = (s + 1.0) / 2.0, (1.0 - s) / 2.0
    out = {}
    for base in ("thigh", "calf", "foot"):
        lv, rv = float(run[f"{base}_l"]), float(run[f"{base}_r"])
        out[f"{base}_l"] = lv * left + rv * right
        out[f"{base}_r"] = rv * left + lv * right
    arms = run if walk is None else _blend_xz(walk, run, arm_t)
    for base in ("upperarm", "lowerarm"):
        lx, lz = _xz(arms[f"{base}_l"])
        rx, rz = _xz(arms[f"{base}_r"])
        if base == "upperarm" and pump != 1.0:
            mid = (lx + rx) / 2.0
            lx, rx = mid + (lx - mid) * pump, mid + (rx - mid) * pump
        # The right arm's Z is the mirror of the left's: an arm in the other's place takes its Z negated.
        out[f"{base}_l"] = (lx * left + rx * right, lz * left - rz * right)
        out[f"{base}_r"] = (rx * left + lx * right, rz * left - lz * right)
    for bone in ("spine_01", "spine_02"):
        if bone in run:
            out[bone] = float(run[bone])
    return out


_ARMS = ("upperarm_l", "lowerarm_l", "upperarm_r", "lowerarm_r")


def _blend_xz(a: dict, b: dict, t: float) -> dict:
    out = {}
    for key in _ARMS:
        ax, az = _xz(a[key])
        bx, bz = _xz(b[key])
        out[key] = (ax + (bx - ax) * t, az + (bz - az) * t)
    return out


def _add(angles: dict, bone: str, dx: float = 0.0, dz: float = 0.0, dy: float = 0.0) -> None:
    x, z, y = _xzy(angles.get(bone, 0.0))
    angles[bone] = (x + dx, z + dz, y + dy)


def _fk(angles: dict, upto: int | None = None):
    """Posed bone heads and rotations, for the bones up to `upto` (the asset lists parents first)."""
    bones = asset()["bones"]
    if upto is not None:
        bones = bones[: upto + 1]
    posed_r, posed_head = [], []
    for bone in bones:
        parent = bone["parent"]
        local = _local_rot(angles.get(bone["name"], 0.0))
        rest_r = _cols(bone["R"])
        head = tuple(bone["head"])
        if parent < 0:
            posed_r.append(_matmul(rest_r, local))
            posed_head.append(head)
            continue
        all_bones = asset()["bones"]
        swing = _matmul(posed_r[parent], _transpose(_cols(all_bones[parent]["R"])))
        offset = (
            head[0] - all_bones[parent]["head"][0],
            head[1] - all_bones[parent]["head"][1],
            head[2] - all_bones[parent]["head"][2],
        )
        swung = _matvec(swing, offset)
        posed_head.append((
            posed_head[parent][0] + swung[0],
            posed_head[parent][1] + swung[1],
            posed_head[parent][2] + swung[2],
        ))
        posed_r.append(_matmul(swing, _matmul(rest_r, local)))
    return posed_head, posed_r


def _skin_one(pos, skin, posed_head, posed_r) -> tuple[float, float, float]:
    acc = (0.0, 0.0, 0.0)
    weight_sum = 0.0
    bones = asset()["bones"]
    for i in range(0, 8, 2):
        bone, weight = int(skin[i]), float(skin[i + 1])
        if bone < 0 or weight == 0.0:
            continue
        rest_head = bones[bone]["head"]
        local = _matvec(_transpose(_cols(bones[bone]["R"])), (
            pos[0] - rest_head[0], pos[1] - rest_head[1], pos[2] - rest_head[2],
        ))
        world = _matvec(posed_r[bone], local)
        head = posed_head[bone]
        acc = (
            acc[0] + (world[0] + head[0]) * weight,
            acc[1] + (world[1] + head[1]) * weight,
            acc[2] + (world[2] + head[2]) * weight,
        )
        weight_sum += weight
    if weight_sum == 0.0:
        return tuple(pos)
    return acc


def _marker(name: str) -> tuple[list, list]:
    """(rest position, skin) of an asset marker or one of the touch surfaces."""
    if name in EXTRA:
        bone, pos = EXTRA[name]
        return list(pos), [_bone_index()[bone], 1.0, -1, 0.0, -1, 0.0, -1, 0.0]
    m = asset()["markers"][name]
    return m["pos"], m["skin"]


def _marker_bone(name: str) -> int:
    _, skin = _marker(name)
    return max(int(skin[i]) for i in range(0, 8, 2))


def _point(angles: dict, name: str) -> tuple[float, float, float]:
    pos, skin = _marker(name)
    posed_head, posed_r = _fk(angles, _marker_bone(name))
    return _skin_one(pos, skin, posed_head, posed_r)


def _markers(angles: dict) -> dict[str, tuple[float, float, float]]:
    posed_head, posed_r = _fk(angles)
    names = [*asset()["markers"], *EXTRA]
    out = {}
    for name in names:
        pos, skin = _marker(name)
        out[name] = _skin_one(pos, skin, posed_head, posed_r)
    return out


def _to_object(x, y, heading, height_m, wx, wy, wz=0.0, lift=0.0) -> tuple[float, float, float]:
    k = height_m / ASSET_STATURE_M
    hx, hy = math.cos(heading), math.sin(heading)
    dx, dy = (wx - x) / k, (wy - y) / k
    return (-hy * dx + hx * dy, (wz - lift) / k, hx * dx + hy * dy)


def _clamp(v: float, lo: float, hi: float) -> float:
    return lo if v < lo else hi if v > hi else v


def _leg(angles: dict, side: str, target, foot: float, twist: float, point: str,
         ground: bool, calf_fixed: float | None = None, floor: float | None = None) -> tuple[dict, float]:
    """Thigh and calf angles that put `point` on `target` (object space). Grid, then halving steps.

    On the grass (`ground`) the sole stays level however the knee bends: thigh, calf and foot all
    turn about the same sideways axis, so the foot takes back what the thigh and knee turned. A
    foot left behind the hips rolls onto its toes instead (HEEL_CAND): the heel lifts and the ball
    of the foot, where the marker is, stays put.
    """

    def trial(params):
        t = dict(angles)
        t[f"thigh_{side}"] = (params[0], params[1], twist)
        t[f"calf_{side}"] = params[2]
        t[f"foot_{side}"] = foot - (params[0] + params[2]) + params[3] if ground else foot
        p = _point(t, point)
        err = math.dist(p, target)
        if ground:
            err += 3.0 * max(0.0, p[1] - (target[1] + 0.04))
        if floor is not None:  # a reaching foot stays above the grass
            err += 3.0 * max(0.0, floor - p[1])
        return err, t

    best = None
    calves = (calf_fixed,) if calf_fixed is not None else CALF_CAND
    heels = HEEL_CAND if ground else (0.0,)
    for thigh in THIGH_CAND:
        for tz in THIGH_Z:
            for calf in calves:
                for heel in heels:
                    err, t = trial((thigh, tz, calf, heel))
                    if best is None or err < best[0]:
                        best = (err, t, [thigh, tz, calf, heel])
    steps = list(LEG_STEP)
    moves = list(_MOVES2 if calf_fixed is not None else _MOVES3)
    if ground:
        moves += [(0, 0, 0, 1), (0, 0, 0, -1)]
    for _ in range(REFINE):
        centre = best[2]
        for move in moves:
            params = list(centre)
            for i, m in enumerate(move):
                params[i] = _clamp(centre[i] + m * steps[i], *LEG_LIMIT[i])
            err, t = trial(params)
            if err < best[0]:
                best = (err, t, params)
        steps = [s / 2 for s in steps]
    return best[1], best[0]


def _lean(angles: dict, target, point: str) -> dict:
    """Lean the spine and neck so `point` (the chest or the brow) meets `target`."""

    def trial(bx, bz):
        t = dict(angles)
        for bone, share in LEAN_SHARE:
            _add(t, bone, bx * share, bz * share)
        return math.dist(_point(t, point), target), t

    best = None
    for bx in LEAN_X:
        for bz in LEAN_Z:
            err, t = trial(bx, bz)
            if best is None or err < best[0]:
                best = (err, t, [bx, bz])
    steps = list(LEAN_STEP)
    for _ in range(REFINE):
        centre = best[2]
        for move in _MOVES2:
            params = [_clamp(centre[i] + move[i] * steps[i], *LEAN_LIMIT[i]) for i in range(2)]
            err, t = trial(*params)
            if err < best[0]:
                best = (err, t, params)
        steps = [s / 2 for s in steps]
    return best[1]


def _blend(base: dict, touch: dict, w: float) -> dict:
    if w >= 1.0:
        return touch
    out = dict(base)
    for key in set(base) | set(touch):
        a, b = _xzy(base.get(key, 0.0)), _xzy(touch.get(key, 0.0))
        if a == b:
            continue
        out[key] = tuple(a[i] + (b[i] - a[i]) * w for i in range(3))
    return out


def _wrap(a: float) -> float:
    return (a + math.pi) % (2 * math.pi) - math.pi


def _upper(pose: dict, heading: float, height_m: float) -> dict:
    """The angles before the feet are placed: the action, the turn, the arms and a held ball.

    Nothing after this moves a bone above the hips except a chest or head touch (_lean), so the
    arms here are the arms drawn (arm_points)."""
    data = asset()
    poses = data["poses"]
    action = pose.get("action") or "stand"
    speed = pose.get("speed") or 0.0
    lead = pose.get("lead") or 0.0
    if action in poses and action in _CONTACT and action not in _FEET:
        base = dict_angles(poses[action])
        if action == "dive":
            dive = pose.get("dive") or 0.0
            mag = min(1.0, abs(dive))
            base = mirror(base) if dive < 0 else base
            angles = scale(base, mag if mag > 0.35 else 0.35)
        else:
            angles = base
    elif speed < STAND_BLEND[0] or (action == "stand" and speed < data["standSpeed"]):
        angles = dict_angles(poses["stand"])
    else:
        # A strike or a touch with the foot or thigh is taken in stride: the legs keep the gait
        # and the touch (below) takes the one that meets the ball.
        full = data["fullStrideSpeed"]
        arm_t = 1.0 if action == "run" else _clamp((speed - full) / (data["armRunSpeed"] - full), 0.0, 1.0)
        pump = pose.get("pump") or 1.0
        angles = gait(math.sin(pose.get("phase") or 0.0), poses["run"], poses["walk"], arm_t, pump)
        if action != "run" and speed < STRIDE_GROW[1]:
            # A walk's short stride grows into the full one through a jog (STRIDE_GROW), not at once.
            t = _clamp((speed - STRIDE_GROW[0]) / (STRIDE_GROW[1] - STRIDE_GROW[0]), 0.0, 1.0)
            factor = data["walkScale"] + (1.0 - data["walkScale"]) * t
            legs = scale({k: v for k, v in angles.items() if k not in _ARMS}, factor, keep_z=True)
            angles.update(legs)
        if action != "run" and speed < STAND_BLEND[1]:
            # Setting off and pulling up, the stride grows out of the stance and back into it.
            t = (speed - STAND_BLEND[0]) / (STAND_BLEND[1] - STAND_BLEND[0])
            angles = _blend(dict_angles(poses["stand"]), angles, t)
    lean = pose.get("lean") or 0.0
    if lean and not (action in poses and action in _CONTACT and action not in _FEET):
        # Speeding up the trunk leans into it, slowing it comes up (scene.pace).
        for bone, share in TRUNK_SHARE:
            _add(angles, bone, lean * share)
    if lead:
        # The hips lead a turn and the chest follows: Root turns the hips and legs, the lower
        # spine turns the chest back to where the engine has it face.
        _add(angles, "Root", dz=lead)
        _add(angles, "spine_01", dy=-lead * 0.5)
        _add(angles, "spine_02", dy=-lead * 0.5)
    touch = pose.get("touch")
    if touch and touch.get("w", 0.0) > 0.0 and touch["part"] in _FEET:
        # The arms balance the kick or the touch: the far arm out and forward, the near one back
        # (the stored poses are a right-footed touch).
        arms = dict_angles(poses[touch["part"]])
        arms = mirror(arms) if touch.get("side", "r") == "l" else arms
        angles = _blend(angles, {**angles, **{k: arms[k] for k in _ARMS}}, float(touch["w"]))
    hold = pose.get("hold")
    if hold and hold.get("w", 0.0) > 0.0:
        angles = _blend(angles, _hold(angles, pose, hold, heading, height_m), float(hold["w"]))
    return angles


def pose_angles(pose: dict, heading: float, height_m: float) -> dict:
    """The bone angles for one frame's pose. The same steps as anglesFor in render.js."""
    x, y = pose.get("x", 0.0), pose.get("y", 0.0)
    lead = pose.get("lead") or 0.0
    lift = pose.get("lift") or 0.0
    angles = _upper(pose, heading, height_m)
    # scene.py plants a foot only when the pose stands on it.
    for side in ("l", "r"):
        plant = pose.get(f"plant_{side}")
        if not plant:
            continue
        twist = 0.0
        if len(plant) > 2 and plant[2] is not None:
            twist = TWIST_SIGN * _wrap(plant[2] - heading - lead)
        pz = plant[3] if len(plant) > 3 else 0.0
        target = _to_object(x, y, heading, height_m, plant[0], plant[1], pz, lift)
        planted, err = _leg(angles, side, target, PLANT_FOOT, twist, f"foot_{side}", True)
        if err > PLANT_GIVE_UP and lift < 0.0:
            # Lowered, a foot the leg cannot reach is not left to the pose, which would put it through
            # the grass: the leg reaches toward its plant and stays above the grass.
            floor = -lift / (height_m / ASSET_STATURE_M)
            planted, err = _leg(angles, side, target, PLANT_FOOT, twist, f"foot_{side}", False, floor=floor)
            err = 0.0
        if err <= PLANT_GIVE_UP:
            # A stride's plant comes and goes with a weight (scene.PLANT_EASE_FRAMES).
            w = float(plant[4]) if len(plant) > 4 and plant[4] is not None else 1.0
            angles = _blend(angles, planted, w)
    touch = pose.get("touch")
    if touch and touch.get("w", 0.0) > 0.0:
        part, side, at = touch["part"], touch.get("side", "r"), touch["at"]
        target = _to_object(x, y, heading, height_m, at[0], at[1], at[2], lift)
        if part in ("foot", "strike"):
            foot = STRIKE_FOOT if part == "strike" else PLANT_FOOT
            floor = -lift / (height_m / ASSET_STATURE_M)
            reached, _ = _leg(angles, side, target, foot, 0.0, f"foot_{side}", False, floor=floor)
            angles = _blend(angles, reached, float(touch["w"]))
            # Halfway between a planted leg and a swing the knee can pass under the grass when the
            # hips are low; then the foot is put on the grass where the blend had it.
            p = _point(angles, f"foot_{side}")
            if p[1] < floor - FLOOR_SLACK:
                on_grass = (p[0], floor, p[2])
                angles, _ = _leg(angles, side, on_grass, foot, 0.0, f"foot_{side}", False, floor=floor)
            return angles
        elif part == "thigh":
            reached, _ = _leg(angles, side, target, 0.25, 0.0, f"thigh_top_{side}", False, calf_fixed=1.5)
        else:
            reached = _lean(angles, target, "brow" if part == "head" else "chest")
        angles = _blend(angles, reached, float(touch["w"]))
    return angles


def _hold(angles: dict, pose: dict, hold: dict, heading: float, height_m: float) -> dict:
    """Bend over a held ball (scene.py decides how far) and put a hand either side of it."""
    out = dict(angles)
    bend = float(hold.get("bend") or 0.0)
    for bone, share in HOLD_BEND:
        _add(out, bone, bend * share)
    x, y, lift = pose.get("x", 0.0), pose.get("y", 0.0), pose.get("lift") or 0.0
    bx, by, bz = hold["at"]
    centre = _to_object(x, y, heading, height_m, bx, by, bz, lift)
    k = height_m / ASSET_STATURE_M
    head, rot = _fk(out, max(_bone_index()["clavicle_l"], _bone_index()["clavicle_r"]))
    for side, sign in (("l", 1.0), ("r", -1.0)):
        target = (centre[0] + sign * HOLD_SIDE / k, centre[1], centre[2])
        out = _arm(out, side, sign, target, head, rot)
    return out


def _arm_hand(angles: dict, side: str, head: list, rot: list) -> tuple[float, float, float]:
    """The hand marker for these arm angles, from the posed shoulder girdle (head, rot)."""
    i = _bone_index()
    bones = asset()["bones"]
    heads, rots = dict(enumerate(head)), dict(enumerate(rot))
    for name in (f"upperarm_{side}", f"lowerarm_{side}", f"hand_{side}"):
        b = i[name]
        bone = bones[b]
        parent = bone["parent"]
        swing = _matmul(rots[parent], _transpose(_cols(bones[parent]["R"])))
        offset = tuple(bone["head"][j] - bones[parent]["head"][j] for j in range(3))
        swung = _matvec(swing, offset)
        heads[b] = tuple(heads[parent][j] + swung[j] for j in range(3))
        rots[b] = _matmul(swing, _matmul(_cols(bone["R"]), _local_rot(angles.get(name, 0.0))))
    pos, skin = _marker(f"hand_{side}")
    b = i[f"hand_{side}"]
    rest = bones[b]["head"]
    local = _matvec(_transpose(_cols(bones[b]["R"])), tuple(pos[j] - rest[j] for j in range(3)))
    world = _matvec(rots[b], local)
    return tuple(world[j] + heads[b][j] for j in range(3))


def _arm(angles: dict, side: str, sign: float, target, head: list, rot: list) -> dict:
    """Upper and lower arm angles that put the hand on `target`. Grid, then halving steps. A small
    pull toward the hanging arm keeps the elbow bending the way an elbow bends."""
    stand = asset()["poses"]["stand"]
    rest = [*_xz(stand["upperarm_l"]), *_xz(stand["lowerarm_l"])]

    def trial(params):
        t = dict(angles)
        t[f"upperarm_{side}"] = (params[0], params[1] * sign)
        t[f"lowerarm_{side}"] = (params[2], params[3] * sign)
        err = math.dist(_arm_hand(t, side, head, rot), target)
        err += ARM_PULL * sum(abs(params[j] - rest[j]) for j in range(4))
        return err, t

    best = None
    for ux in ARM_UX:
        for uz in ARM_UZ:
            for lx in ARM_LX:
                for lz in ARM_LZ:
                    err, t = trial((ux, uz, lx, lz))
                    if best is None or err < best[0]:
                        best = (err, t, [ux, uz, lx, lz])
    steps = list(ARM_STEP)
    for _ in range(REFINE):
        centre = best[2]
        for move in _MOVES4:
            params = [_clamp(centre[j] + move[j] * steps[j], *ARM_LIMIT[j]) for j in range(4)]
            err, t = trial(params)
            if err < best[0]:
                best = (err, t, params)
        steps = [v / 2 for v in steps]
    return best[1]


def gait_foot(pose: dict, heading: float, height_m: float, side: str,
              with_height: bool = False) -> tuple[float, ...]:
    """Where the stride alone puts a foot on the pitch, (x, y) or (x, y, height of the sole): where
    scene.py plants it, and where a step from the stride starts."""
    p = _point(_upper(pose, heading, height_m), f"foot_{side}")
    w = to_world(pose.get("x", 0.0), pose.get("y", 0.0), heading, height_m, p)
    return (w[0], w[1], max(0.0, w[2])) if with_height else (w[0], w[1])


def arm_points(pose: dict, heading: float, height_m: float) -> dict[str, list[float]]:
    """World shoulder, elbow and hand of each arm as the mesh draws them (scene.py labels them)."""
    angles = _upper(pose, heading, height_m)
    head, _ = _fk(angles, max(_bone_index()["hand_l"], _bone_index()["hand_r"]))
    markers = {}
    i = _bone_index()
    for side in ("l", "r"):
        markers[f"shoulder_{side}"] = head[i[f"upperarm_{side}"]]
        markers[f"elbow_{side}"] = head[i[f"lowerarm_{side}"]]
        markers[f"hand_{side}"] = _point(angles, f"hand_{side}")
    x, y, lift = pose.get("x", 0.0), pose.get("y", 0.0), pose.get("lift") or 0.0
    return {name: list(to_world(x, y, heading, height_m, p, lift)) for name, p in markers.items()}


def dict_angles(raw: dict) -> dict:
    out = {}
    for key, spec in raw.items():
        if isinstance(spec, list):
            out[key] = tuple(float(v) for v in spec)
        else:
            out[key] = float(spec)
    return out


def to_world(x, y, heading, height_m, point, lift: float = 0.0) -> tuple[float, float, float]:
    k = height_m / ASSET_STATURE_M
    hx, hy = math.cos(heading), math.sin(heading)
    ox, oy, oz = point
    return (
        x + k * (-hy * ox + hx * oz),
        y + k * (hx * ox + hy * oz),
        k * oy + lift,
    )


def pose_markers(pose: dict, heading: float, height_m: float) -> dict[str, tuple[float, float, float]]:
    """World position of every marker (and touch surface) for one frame's pose."""
    angles = pose_angles(pose, heading, height_m)
    x, y, lift = pose.get("x", 0.0), pose.get("y", 0.0), pose.get("lift") or 0.0
    return {name: to_world(x, y, heading, height_m, p, lift) for name, p in _markers(angles).items()}


def foot_yaw(pose: dict, heading: float, height_m: float, side: str) -> float:
    """Which way a foot points on the grass, in pitch radians: from its heel to its toes."""
    angles = pose_angles(pose, heading, height_m)
    posed_head, _ = _fk(angles)
    i = _bone_index()
    heel, toe = posed_head[i[f"foot_{side}"]], posed_head[i[f"ball_{side}"]]
    hx, hy = math.cos(heading), math.sin(heading)
    dx, dz = toe[0] - heel[0], toe[2] - heel[2]
    return math.atan2(hx * dx + hy * dz, -hy * dx + hx * dz)


def world_markers(
    x, y, heading, height_m, action, phase, speed, reach, dive, plant_l, plant_r,
) -> dict[str, tuple[float, float, float]]:
    pose = {
        "action": action, "phase": phase, "speed": speed, "reach": reach, "dive": dive,
        "plant_l": plant_l, "plant_r": plant_r, "x": x, "y": y,
    }
    return pose_markers(pose, heading, height_m)
