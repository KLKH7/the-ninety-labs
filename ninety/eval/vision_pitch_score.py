"""Pitch-level scoring for player and ball detections: boxes matched by where they put the object
on the pitch, not by how their pixels overlap (docs/EVALUATION.md, Vision scoring).

Every true and every detected box goes to the pitch through that frame's saved camera matrix
(``camera.P`` in ``frames.jsonl``), the way event detection places it (ninety/vision/observe.py):
a player at the bottom middle of the box, where the feet meet the ground; the ball at the box
centre, taken to be on the ground with its centre one radius up. Within each frame and class,
eligible detections (the pixel scorer's score threshold) are paired one to one with true boxes,
nearest first, within the strict radius (1.0 m for both) or the lenient one (1.5 m for players,
2.0 m for the ball). Truth and detection are placed the same way, so the score measures the
detector's boxes, not the camera fit or a ball's height; the in-air ball (EVALUATION.md's
difficulty group, height above 0.5 m) is reported as its own group, never left out.

Only frames the detector ran on are scored, as in the pixel scorer (``vision_score``). A box whose
point is not on the ground in front of the camera (above the horizon) has no place: a label is
then a miss and a detection a false alarm, and both are counted under ``unplaced``.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping

from ninety.eval.event_score import LENIENT_M, STRICT_M
from ninety.eval.pitch_score import GROUND_Z
from ninety.eval.vision_score import (
    CLASSES,
    DEFAULT_THRESHOLD,
    VISIBILITY_GROUPS,
    _metrics,
    center_distance,
    ground_truth,
    visibility_group,
)

# The ball's centre on the ground is one radius up (Law 2: about 0.11 m), as in
# ninety.vision.observe.BALL_CENTRE_Z; copied, not imported, because observe needs numpy, which
# the scorer's environment does not have. tests/test_vision_pitch_score.py checks they agree.
BALL_CENTRE_Z = 0.11
# The lenient player radius of docs/EVALUATION.md's pitch-level table (design, GROUNDING.md
# Vision scoring S4; strict is S3); the strict radius and the
# ball's lenient radius are the event scorer's own (STRICT_M, LENIENT_M), so they cannot drift.
PLAYER_LENIENT_M = 1.5
RADIUS_M = {
    "strict": {"player": STRICT_M, "ball": STRICT_M},
    "lenient": {"player": PLAYER_LENIENT_M, "ball": LENIENT_M},
}
RULES = tuple(RADIUS_M)
# EVALUATION.md's "in the air" group: a ball whose height is above 0.5 m (the same cut-off the
# position scorer uses, pitch_score.GROUND_Z; never a new one).
IN_AIR_Z = GROUND_Z
HEIGHT_GROUPS = ("on the ground", "in the air")


def to_ground(P: list[list[float]], u: float, v: float, z: float) -> tuple[float, float] | None:
    """The pitch point (x, y) at height z that the saved 3x4 matrix P projects to pixel (u, v),
    or None when there is none in front of the camera (a pixel above the horizon)."""
    a11, a12 = P[0][0] - u * P[2][0], P[0][1] - u * P[2][1]
    a21, a22 = P[1][0] - v * P[2][0], P[1][1] - v * P[2][1]
    b1 = -((P[0][2] - u * P[2][2]) * z + P[0][3] - u * P[2][3])
    b2 = -((P[1][2] - v * P[2][2]) * z + P[1][3] - v * P[2][3])
    det = a11 * a22 - a12 * a21
    if det == 0 or not math.isfinite(det):
        return None
    x, y = (b1 * a22 - a12 * b2) / det, (a11 * b2 - b1 * a21) / det
    depth = P[2][0] * x + P[2][1] * y + P[2][2] * z + P[2][3]
    if not depth > 1e-9:  # the same test as ninety.render.camera.project_with
        return None
    return x, y


def place(cls: str, box: Iterable[float], P: list[list[float]]) -> tuple[float, float] | None:
    """Where a box puts its object on the pitch: a player's foot point, the ball's centre."""
    x0, y0, x1, y1 = (float(v) for v in box)
    if cls == "player":
        return to_ground(P, (x0 + x1) / 2, y1, 0.0)
    return to_ground(P, (x0 + x1) / 2, (y0 + y1) / 2, BALL_CENTRE_Z)


def height_group(z: float) -> str:
    return "in the air" if z > IN_AIR_Z else "on the ground"


def _ball_heights(frames: Iterable[Mapping]) -> dict[int, float]:
    heights = {}
    for row in frames:
        z = row.get("ball", {}).get("z")
        if z is not None:
            heights[int(row["frame"])] = float(z)
    return heights


def has_cameras(frames: Iterable[Mapping]) -> bool:
    """True when every frame has a saved camera matrix, False when none has; a mix is refused."""
    flags = {bool(row.get("camera", {}).get("P")) for row in frames}
    if len(flags) > 1:
        raise ValueError("some frames have a saved camera matrix and some do not")
    return flags == {True}


def _match(labels: list[dict], detections: list[dict],
           radius: Mapping[str, float]) -> list[tuple[int, int, float]]:
    """One to one within each frame and class, nearest first; (label, detection, metres)."""
    candidates = []
    for ti, true in enumerate(labels):
        if true["xy"] is None:
            continue
        for di, found in enumerate(detections):
            if found["xy"] is None or (true["frame"], true["cls"]) != (found["frame"], found["cls"]):
                continue
            distance = math.dist(true["xy"], found["xy"])
            if distance <= radius[true["cls"]]:
                candidates.append((distance, ti, di))
    candidates.sort()
    used_true: set[int] = set()
    used_found: set[int] = set()
    pairs = []
    for distance, ti, di in candidates:
        if ti in used_true or di in used_found:
            continue
        used_true.add(ti)
        used_found.add(di)
        pairs.append((ti, di, distance))
    return pairs


def _groups(labels, detections, pairs, cls, axis, names) -> dict:
    """Counts for each group of one axis, with the pixel scorer's convention: a match takes its
    label's group, an unmatched detection the group of the nearest label (box centre distance) in
    its frame and class, and a false alarm with no such label is in no group."""
    matched_true = {ti for ti, _, _ in pairs}
    matched_found = {di for _, di, _ in pairs}
    out = {}
    for group in names:
        truth = {i for i, label in enumerate(labels) if label["cls"] == cls and label[axis] == group}
        tp = sum(1 for ti, _, _ in pairs if ti in truth)
        fp = 0
        for di, found in enumerate(detections):
            if di in matched_found or found["cls"] != cls:
                continue
            nearby = [(center_distance(label["bbox"], found["bbox"]), i) for i, label in enumerate(labels)
                      if label["frame"] == found["frame"] and label["cls"] == cls]
            if nearby and labels[min(nearby)[1]][axis] == group:
                fp += 1
        out[group] = _metrics(tp, fp, len(truth - matched_true))
    return out


def score_pitch(
    frames: Iterable[Mapping],
    detections: Iterable[Mapping],
    threshold: float = DEFAULT_THRESHOLD,
    run: Iterable[int] | None = None,
) -> dict:
    """Strict and lenient pitch-level metrics: overall, by class, by visibility group within each
    class, and the ball by height. ``run`` is as in ``vision_score.score``."""
    frames = list(frames)
    known = {int(row["frame"]) for row in frames}
    run = known if run is None else {int(f) for f in run}
    if unknown := sorted(run - known):
        raise ValueError(f"detections name frames not in frames.jsonl: {unknown[:5]}")
    cameras = {int(row["frame"]): row.get("camera", {}).get("P") for row in frames}
    if missing := sorted(f for f in run if not cameras[f]):
        raise ValueError(f"pitch-level matching needs each frame's saved camera matrix: {missing[:5]}")
    heights = _ball_heights(frames)
    labels = []
    for label in ground_truth(frames):
        if label["frame"] not in run:
            continue
        frame, cls = label["frame"], label["cls"]
        if cls == "ball" and frame not in heights:
            raise ValueError(f"frame {frame}: a ball label with no height, so its height group is unknown")
        labels.append({**label, "xy": place(cls, label["bbox"], cameras[frame]),
                       "visibility_group": visibility_group(label["visibility"]),
                       "height_group": height_group(heights[frame]) if cls == "ball" else None})
    eligible = []
    for d in detections:
        if float(d.get("score", 0.0)) < threshold:
            continue
        frame = int(d["frame"])
        if frame not in run:
            raise ValueError(f"a detection on frame {frame}, which the run does not list")
        eligible.append({**d, "frame": frame, "xy": place(d["cls"], d["bbox"], cameras[frame])})

    report = {
        "rules": {
            "score_threshold": threshold,
            "radius_m": RADIUS_M,
            "player_point": "bottom middle of the box, on the ground",
            "ball_point": f"centre of the box, {BALL_CENTRE_Z} m up (on the ground)",
            "in_the_air_above_m": IN_AIR_Z,
            "match": "same frame/class, one-to-one, nearest on the pitch first",
        },
        "frames": {"scored": len(run)},
        "unplaced": {"labels": sum(label["xy"] is None for label in labels),
                     "detections": sum(d["xy"] is None for d in eligible)},
    }
    for rule in RULES:
        pairs = _match(labels, eligible, RADIUS_M[rule])
        by_class = {}
        for cls in CLASSES:
            tp = sum(1 for ti, _, _ in pairs if labels[ti]["cls"] == cls)
            by_class[cls] = _metrics(tp, sum(d["cls"] == cls for d in eligible) - tp,
                                     sum(label["cls"] == cls for label in labels) - tp)
        report[rule] = {
            "overall": _metrics(len(pairs), len(eligible) - len(pairs), len(labels) - len(pairs)),
            "by_class": by_class,
            "visibility": {cls: _groups(labels, eligible, pairs, cls, "visibility_group", VISIBILITY_GROUPS)
                           for cls in CLASSES},
            "height": {"ball": _groups(labels, eligible, pairs, "ball", "height_group", HEIGHT_GROUPS)},
            "distance_m": _distances([d for _, _, d in pairs]),
        }
    return report


def _distances(values: list[float]) -> dict:
    if not values:
        return {"mean": None, "max": None}
    return {"mean": round(sum(values) / len(values), 4), "max": round(max(values), 4)}
