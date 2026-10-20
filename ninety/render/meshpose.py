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
# The trunk's lean toward a ball on the chest or the head, shared by the lower spine and the neck.
LEAN_X = (-0.6, -0.4, -0.2, 0.0, 0.2, 0.4, 0.6)
LEAN_Z = (-0.4, -0.2, 0.0, 0.2, 0.4)
LEAN_STEP = (0.1, 0.1)
LEAN_LIMIT = ((-0.9, 0.9), (-0.6, 0.6))
LEAN_SHARE = (("spine_01", 0.35), ("spine_02", 0.35), ("neck_01", 0.3))
# The thigh points down, so a twist of +a about it turns the foot by -a about the vertical.
TWIST_SIGN = -1.0
# The surfaces a touch aims, not in the asset: (bone, rest point skinned wholly to it).
EXTRA = {
    "brow": ("head", (0.0, 1.70, 0.13)),
    "chest": ("spine_03", (0.0, 1.28, 0.14)),
    "thigh_top_l": ("thigh_l", (0.14, 0.64, 0.10)),
    "thigh_top_r": ("thigh_r", (-0.14, 0.64, 0.10)),
}

_CONTACT = {"strike", "foot", "thigh", "chest", "head", "hands", "throw", "dive", "shield"}


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


def gait(s: float, run: dict) -> dict:
    """s = sin(phase). +1 is the stored run (right foot forward). -1 is its mirror."""
    left, right = (s + 1.0) / 2.0, (1.0 - s) / 2.0
    out = {}
    for base in ("thigh", "calf", "foot"):
        lv, rv = float(run[f"{base}_l"]), float(run[f"{base}_r"])
        out[f"{base}_l"] = lv * left + rv * right
        out[f"{base}_r"] = rv * left + lv * right
    for base in ("upperarm", "lowerarm"):
        lx, lz = _xz(run[f"{base}_l"])
        rx, rz = _xz(run[f"{base}_r"])
        out[f"{base}_l"] = (lx * left + rx * right, lz)
        out[f"{base}_r"] = (rx * left + lx * right, rz)
    for bone in ("spine_01", "spine_02"):
        if bone in run:
            out[bone] = float(run[bone])
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
    k = height_m / 1.84
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


def pose_angles(pose: dict, heading: float, height_m: float) -> dict:
    """The bone angles for one frame's pose. The same steps as anglesFor in render.js."""
    data = asset()
    poses = data["poses"]
    action = pose.get("action") or "stand"
    speed = pose.get("speed") or 0.0
    reach = pose.get("reach") or 0.0
    x, y = pose.get("x", 0.0), pose.get("y", 0.0)
    lead = pose.get("lead") or 0.0
    lift = pose.get("lift") or 0.0
    if action in ("strike", "foot", "thigh") and action in poses:
        angles = mirror(poses[action]) if reach > 0 else dict_angles(poses[action])
    elif action in poses and action in _CONTACT:
        base = dict_angles(poses[action])
        if action == "dive":
            dive = pose.get("dive") or 0.0
            mag = min(1.0, abs(dive))
            base = mirror(base) if dive < 0 else base
            angles = scale(base, mag if mag > 0.35 else 0.35)
        else:
            angles = base
    elif action == "stand" or speed < data["standSpeed"]:
        angles = dict_angles(poses["stand"])
    else:
        angles = gait(math.sin(pose.get("phase") or 0.0), poses["run"])
        if action != "run" and speed < data["fullStrideSpeed"]:
            angles = scale(angles, data["walkScale"], keep_z=True)
    if lead:
        # The hips lead a turn and the chest follows: Root turns the hips and legs, the lower
        # spine turns the chest back to where the engine has it face.
        _add(angles, "Root", dz=lead)
        _add(angles, "spine_01", dy=-lead * 0.5)
        _add(angles, "spine_02", dy=-lead * 0.5)
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
        if err <= PLANT_GIVE_UP:
            angles = planted
    touch = pose.get("touch")
    if touch and touch.get("w", 0.0) > 0.0:
        part, side, at = touch["part"], touch.get("side", "r"), touch["at"]
        target = _to_object(x, y, heading, height_m, at[0], at[1], at[2], lift)
        if part in ("foot", "strike"):
            foot = STRIKE_FOOT if part == "strike" else PLANT_FOOT
            floor = -lift / (height_m / 1.84)
            reached, _ = _leg(angles, side, target, foot, 0.0, f"foot_{side}", False, floor=floor)
        elif part == "thigh":
            reached, _ = _leg(angles, side, target, 0.25, 0.0, f"thigh_top_{side}", False, calf_fixed=1.5)
        else:
            reached = _lean(angles, target, "brow" if part == "head" else "chest")
        angles = _blend(angles, reached, float(touch["w"]))
    return angles


def dict_angles(raw: dict) -> dict:
    out = {}
    for key, spec in raw.items():
        if isinstance(spec, list):
            out[key] = tuple(float(v) for v in spec)
        else:
            out[key] = float(spec)
    return out


def to_world(x, y, heading, height_m, point, lift: float = 0.0) -> tuple[float, float, float]:
    k = height_m / 1.84
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
