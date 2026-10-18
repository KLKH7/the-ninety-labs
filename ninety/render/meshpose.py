"""Poses for the match mesh. three.js skins these angles; the capsules stay the label box.

Object space is Y-up metres, +X the player's left, +Z the way he faces, feet on y = 0.
A positive bone X swings that limb back. Left-arm Z adducts positive, right-arm Z negative.
"""

from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path

ASSET = Path(__file__).resolve().parents[2] / "web" / "render" / "assets" / "player.json"

# Stance-foot search. The same lists run in render.js. Thigh Z is the sideways reach:
# a plant beside the hip is not on the line the thigh swings along.
THIGH_CAND = (-0.9, -0.55, -0.25, 0.05, 0.35, 0.6)
THIGH_Z = (-0.4, -0.15, 0.0, 0.15, 0.4)
CALF_CAND = (0.05, 0.35, 0.7, 1.1, 1.5)
PLANT_FOOT = 0.12
PLANT_GIVE_UP = 0.45

_CONTACT = {"strike", "foot", "thigh", "chest", "head", "hands", "throw", "dive", "shield"}


@lru_cache(maxsize=1)
def asset() -> dict:
    return json.loads(ASSET.read_text())


def _xz(spec) -> tuple[float, float]:
    if isinstance(spec, (list, tuple)):
        return float(spec[0]), float(spec[1])
    return float(spec), 0.0


def _rot_x(angle: float) -> tuple:
    c, s = math.cos(angle), math.sin(angle)
    return ((1.0, 0.0, 0.0), (0.0, c, s), (0.0, -s, c))


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
    x, z = _xz(spec)
    return _matmul(_rot_z(z), _rot_x(x))


def _cols(flat) -> tuple:
    return (
        (flat[0], flat[1], flat[2]),
        (flat[3], flat[4], flat[5]),
        (flat[6], flat[7], flat[8]),
    )


def mirror(angles: dict) -> dict:
    """Swap left and right. Z flips because the right arm adducts the other way."""
    out = {}
    for key, spec in angles.items():
        if key.endswith("_l"):
            name = key[:-2] + "_r"
        elif key.endswith("_r"):
            name = key[:-2] + "_l"
        else:
            name = key
        x, z = _xz(spec)
        out[name] = (x, -z) if isinstance(spec, (list, tuple)) else x
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


def _fk(angles: dict):
    data = asset()
    bones = data["bones"]
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
        swing = _matmul(posed_r[parent], _transpose(_cols(bones[parent]["R"])))
        offset = (
            head[0] - bones[parent]["head"][0],
            head[1] - bones[parent]["head"][1],
            head[2] - bones[parent]["head"][2],
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


def _markers(angles: dict) -> dict[str, tuple[float, float, float]]:
    posed_head, posed_r = _fk(angles)
    data = asset()
    return {
        name: _skin_one(m["pos"], m["skin"], posed_head, posed_r)
        for name, m in data["markers"].items()
    }


def _to_object(x, y, heading, height_m, wx, wy) -> tuple[float, float, float]:
    k = height_m / 1.84
    hx, hy = math.cos(heading), math.sin(heading)
    dx, dy = (wx - x) / k, (wy - y) / k
    return (-hy * dx + hx * dy, 0.0, hx * dx + hy * dy)


def _plant(angles: dict, side: str, target) -> dict:
    best = None
    for thigh in THIGH_CAND:
        for tz in THIGH_Z:
            for calf in CALF_CAND:
                trial = dict(angles)
                trial[f"thigh_{side}"] = (thigh, tz)
                trial[f"calf_{side}"] = calf
                trial[f"foot_{side}"] = PLANT_FOOT
                foot = _markers(trial)[f"foot_{side}"]
                err = math.dist(foot, target) + 3.0 * max(0.0, foot[1] - 0.04)
                if best is None or err < best[0]:
                    best = (err, trial)
    if best[0] > PLANT_GIVE_UP:
        return angles
    return best[1]


def angles_for(
    action: str,
    phase: float,
    speed: float,
    reach: float,
    dive: float,
    plant_l,
    plant_r,
    x: float,
    y: float,
    heading: float,
    height_m: float,
) -> dict:
    data = asset()
    poses = data["poses"]
    if action == "strike" and "strike" in poses:
        angles = mirror(poses["strike"]) if reach > 0 else dict_angles(poses["strike"])
    elif action == "foot" and "foot" in poses:
        angles = mirror(poses["foot"]) if reach > 0 else dict_angles(poses["foot"])
    elif action == "thigh" and "thigh" in poses:
        angles = mirror(poses["thigh"]) if reach > 0 else dict_angles(poses["thigh"])
    elif action in poses and action in _CONTACT:
        base = dict_angles(poses[action])
        if action == "dive":
            mag = min(1.0, abs(dive))
            base = mirror(base) if dive < 0 else base
            angles = scale(base, mag if mag > 0.35 else 0.35)
        else:
            angles = base
    elif action == "stand" or speed < data["standSpeed"]:
        angles = dict_angles(poses["stand"])
    else:
        angles = gait(math.sin(phase), poses["run"])
        if action != "run" and speed < data["fullStrideSpeed"]:
            angles = scale(angles, data["walkScale"], keep_z=True)
        if action not in _CONTACT:
            if plant_l:
                angles = _plant(angles, "l", _to_object(x, y, heading, height_m, plant_l[0], plant_l[1]))
            if plant_r:
                angles = _plant(angles, "r", _to_object(x, y, heading, height_m, plant_r[0], plant_r[1]))
    return angles


def dict_angles(raw: dict) -> dict:
    out = {}
    for key, spec in raw.items():
        if isinstance(spec, list):
            out[key] = (float(spec[0]), float(spec[1]))
        else:
            out[key] = float(spec)
    return out


def to_world(x, y, heading, height_m, point) -> tuple[float, float, float]:
    k = height_m / 1.84
    hx, hy = math.cos(heading), math.sin(heading)
    ox, oy, oz = point
    return (
        x + k * (-hy * ox + hx * oz),
        y + k * (hx * ox + hy * oz),
        k * oy,
    )


def world_markers(
    x, y, heading, height_m, action, phase, speed, reach, dive, plant_l, plant_r,
) -> dict[str, tuple[float, float, float]]:
    angles = angles_for(
        action, phase, speed, reach, dive, plant_l, plant_r, x, y, heading, height_m,
    )
    return {name: to_world(x, y, heading, height_m, p) for name, p in _markers(angles).items()}
