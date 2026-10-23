"""Fake pixel detections: every drawn player and ball label copied as a detection with score 1.0,
then damaged in known ways, so the recall and precision the scorer must report are known before
it runs (LESSONS 8: a check must be able to fail). The expected numbers come from the damage log
alone, never from the scorer, so a scorer bug cannot also move the answer it is checked against.

Damage, per class:
- drop: the label gets no detection, so it is a miss.
- shift_in: the copy moves a known number of pixels and stays inside the match rule: still a match.
- shift_out: the copy moves past the rule: the label is a miss and the moved box a false alarm.
- add: a false box, overlapping no label of either class.

Every damage is planted only where it cannot be confused with a neighbour, as in fake_detections.py:
a damaged player's box, and the box its copy moves to, overlap no other player label in that
frame, so no other detection can match it and its copy can match no other label; a damaged ball's
centre is far enough from every other ball that the same holds. A moved false alarm also has its
own label as the nearest one, so the scorer's group convention (an unmatched box goes to the
nearest label's visibility group) puts it in that label's group. When damage cannot be planted
cleanly it is refused, never forced.

Pitch-level damage (``fake_pitch_detections``) is planted the same way, in metres on the pitch
through each frame's saved camera (ninety/eval/vision_pitch_score.py): a copy's point (a player's foot,
the ball's centre) moves a known distance, inside the strict radius (shift_in), between the strict
and the lenient one (shift_mid: a miss and a false alarm under strict only), or past the lenient
one (shift_out); a false box lands further than the lenient radius from every label. A damaged
label, and the point its copy moves to, are further than the lenient radius from every other
label of its class in the frame, so nothing else can match them.

Both kinds also log each damage's ball height group (in the air above 0.5 m, or on the ground) and
camera blur group (a frame whose blur streak is longer than 3 px, or not), read from the clip's
`ball.z` and `blur_px` here, not by the scorer, so the per-group counts are known too. ``only``
plants every damage in one group, ``{"height": "in the air"}`` or ``{"blur": "blurred"}``; the
player has no height group, so a height restriction leaves the players' damage where it falls.

    uv run python -m ninety.eval.fake_box_detections runs/dataset/test/seed*
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter
from pathlib import Path

from ninety.eval.vision_pitch_score import (
    BALL_CENTRE_Z,
    RADIUS_M,
    RULES,
    has_cameras,
    place,
    score_pitch,
)
from ninety.eval.vision_score import (
    BALL_DISTANCE_PX,
    BLUR_GROUPS,
    BLUR_PX,
    CLASSES,
    HEIGHT_GROUPS,
    IN_AIR_Z,
    PLAYER_IOU,
    VISIBILITY_GROUPS,
    ground_truth,
    score,
    visibility_group,
)
from ninety.sim import fmath

DAMAGES = ("drop", "shift_in", "shift_out", "add")

# A player copy moves sideways by dx, keeping its size, so IoU = (w - dx) / (w + dx): it stays at or
# above PLAYER_IOU while dx <= w * PLAYER_DX_LIMIT. shift_in moves half the limit, shift_out twice it.
PLAYER_DX_LIMIT = (1 - PLAYER_IOU) / (1 + PLAYER_IOU)
PLAYER_SHIFT = {"shift_in": PLAYER_DX_LIMIT / 2, "shift_out": PLAYER_DX_LIMIT * 2}
# A ball copy moves a fixed distance in pixels: half the rule, or twice it.
BALL_SHIFT_PX = {"shift_in": BALL_DISTANCE_PX / 2, "shift_out": BALL_DISTANCE_PX * 2}
TIE_PX = 1e-6  # nearer than another label by less than this is a tie, so the group is not certain
AXES = ("height", "blur")  # the per-frame groups: the ball's height, the camera's blur
AXIS_CLASSES = {"height": ("ball",), "blur": CLASSES}


def _frame_axes(frames: list[dict]) -> dict[str, dict[int, str] | None]:
    """Each frame's height and blur group, read from the clip; an axis no frame records is None."""
    out = {}
    for axis, read, group in (("height", lambda r: (r.get("ball") or {}).get("z"), height_of),
                              ("blur", lambda r: r.get("blur_px"), blur_of)):
        values = {int(r["frame"]): read(r) for r in frames}
        out[axis] = ({f: group(v) for f, v in values.items() if v is not None}
                     if any(v is not None for v in values.values()) else None)
    return out


def _tag(labels: list[dict], axes: dict) -> None:
    """Give each label its height group (the ball only) and its frame's blur group, or None."""
    for lab in labels:
        for axis in AXES:
            groups = axes[axis]
            lab[axis] = (groups.get(lab["frame"]) if groups is not None and lab["cls"] in AXIS_CLASSES[axis]
                         else None)


def _wanted(label: dict, only: dict | None) -> bool:
    """The label is in the group `only` names on each axis its class has."""
    for axis, group in (only or {}).items():
        if axis not in AXES:
            raise ValueError(f"no such axis {axis!r}: damage can be planted by {', '.join(AXES)}")
        if label["cls"] in AXIS_CLASSES[axis] and label[axis] != group:
            return False
    return True


def _centre(box) -> tuple[float, float]:
    return (box[0] + box[2]) / 2, (box[1] + box[3]) / 2


def _distance(a, b) -> float:
    (ax, ay), (bx, by) = _centre(a), _centre(b)
    return math.hypot(ax - bx, ay - by)


def _overlap(a, b) -> bool:
    """Positive shared area; boxes that only touch along an edge do not overlap."""
    return min(a[2], b[2]) > max(a[0], b[0]) and min(a[3], b[3]) > max(a[1], b[1])


def _span(a, b) -> list[float]:
    return [min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3])]


def _in_image(box, camera) -> bool:
    return 0 <= box[0] <= box[2] <= camera["width"] and 0 <= box[1] <= box[3] <= camera["height"]


def _moved(label: dict, damage: str, rng) -> tuple[list[float], float]:
    """The copy's new box and how far it moved, in pixels."""
    x0, y0, x1, y1 = label["bbox"]
    if label["cls"] == "player":
        dx = (x1 - x0) * PLAYER_SHIFT[damage] * rng.choice((-1, 1))
        return [x0 + dx, y0, x1 + dx, y1], abs(dx)
    a = rng.uniform(0, 2 * math.pi)
    d = BALL_SHIFT_PX[damage]
    dx, dy = d * fmath.cos(a), d * fmath.sin(a)
    return [x0 + dx, y0 + dy, x1 + dx, y1 + dy], d


def _clear(label: dict, box, others: list[dict], reach_px: float) -> bool:
    """No other label of its class could match the label or the box: for players no overlap with
    either; for the ball every other centre more than reach_px + 2 x the rule away."""
    if label["cls"] == "player":
        area = _span(label["bbox"], box)
        return not any(_overlap(area, o["bbox"]) for o in others)
    return all(_distance(label["bbox"], o["bbox"]) > reach_px + 2 * BALL_DISTANCE_PX for o in others)


def _nearest(box, same: list[dict]) -> dict | None:
    """The label the scorer gives an unmatched box to, or None when two are too close to call."""
    ranked = sorted(same, key=lambda o: _distance(box, o["bbox"]))
    if not ranked:
        return None
    if len(ranked) > 1 and _distance(box, ranked[1]["bbox"]) - _distance(box, ranked[0]["bbox"]) < TIE_PX:
        return None
    return ranked[0]


def _false_box(source: dict, labels: list[dict], camera, rng) -> list[float] | None:
    """A box the size of `source`, in the image, overlapping no label of either class in its frame,
    a ball centre more than 2 x the rule from every ball, and one nearest label of its class (if it
    has any) to give it a group; None when no try finds room."""
    x0, y0, x1, y1 = source["bbox"]
    w, h = x1 - x0, y1 - y0
    here = [o for o in labels if o["frame"] == source["frame"]]
    same = [o for o in here if o["cls"] == source["cls"]]
    for _ in range(200):
        x, y = rng.uniform(0, camera["width"] - w), rng.uniform(0, camera["height"] - h)
        box = [x, y, x + w, y + h]
        if any(_overlap(box, o["bbox"]) for o in here):
            continue
        if source["cls"] == "ball" and any(
            _distance(box, o["bbox"]) <= 2 * BALL_DISTANCE_PX for o in same
        ):
            continue
        if same and _nearest(box, same) is None:
            continue
        return box
    return None


def fake_box_detections(frames: list[dict], seed: int, per_damage: int = 2,
                        only: dict | None = None) -> tuple[list[dict], dict]:
    """Return (detections, expected): per_damage of each damage in DAMAGES for each class (on labels
    in the group `only` names, if given), and the counts the scorer must report, from the damage
    log alone (`expected_counts`)."""
    rng = fmath.Random(seed)  # the same draws as random.Random; refuses anything platform-dependent
    labels = ground_truth(frames)
    axes = _frame_axes(frames)
    _tag(labels, axes)
    cameras = {int(row["frame"]): row["camera"] for row in frames}
    by_frame_cls: dict[tuple[int, str], list[int]] = {}
    for i, label in enumerate(labels):
        by_frame_cls.setdefault((label["frame"], label["cls"]), []).append(i)
    detections = {i: {"frame": lab["frame"], "cls": lab["cls"], "bbox": list(lab["bbox"]), "score": 1.0}
                  for i, lab in enumerate(labels)}
    damaged: set[int] = set()
    added: list[dict] = []
    log: list[dict] = []

    for cls in CLASSES:
        victims = [i for i, lab in enumerate(labels) if lab["cls"] == cls and _wanted(lab, only)]
        rng.shuffle(victims)
        for damage in DAMAGES:
            for _ in range(per_damage):
                if damage == "add":
                    pool = [lab for lab in labels if lab["cls"] == cls and _wanted(lab, only)]
                    if not pool:
                        raise ValueError(f"no {cls} label to size a false box on")
                    source = rng.choice(pool)
                    box = _false_box(source, labels, cameras[source["frame"]], rng)
                    if box is None:
                        raise ValueError(f"no room for a false {cls} box in frame {source['frame']}")
                    same = [labels[j] for j in by_frame_cls[(source["frame"], cls)]]
                    near = _nearest(box, same)
                    added.append({"frame": source["frame"], "cls": cls, "bbox": box, "score": 1.0})
                    log.append({"damage": damage, "cls": cls, "frame": source["frame"], "shift_px": None,
                                "group": visibility_group(near["visibility"]) if near else None,
                                **{axis: near[axis] if near else None for axis in AXES}})
                    continue
                for i in victims:
                    if i in damaged:
                        continue
                    label = labels[i]
                    others = [labels[j] for j in by_frame_cls[(label["frame"], cls)] if j != i]
                    if damage == "drop":
                        box, moved = label["bbox"], 0.0
                    else:
                        box, moved = _moved(label, damage, rng)
                        if not _in_image(box, cameras[label["frame"]]):
                            continue
                    if not _clear(label, box, others, moved):
                        continue
                    if damage == "shift_out" and _nearest(box, [label, *others]) is not label:
                        continue
                    break
                else:
                    raise ValueError(f"not enough isolated {cls} labels to plant {damage} cleanly")
                damaged.add(i)
                if damage == "drop":
                    del detections[i]
                else:
                    detections[i]["bbox"] = box
                log.append({"damage": damage, "cls": cls, "frame": label["frame"],
                            "shift_px": moved if damage != "drop" else None,
                            "group": visibility_group(label["visibility"]),
                            **{axis: label[axis] for axis in AXES}})

    out = [detections[i] for i in sorted(detections)] + added
    out.sort(key=lambda d: d["frame"])
    return out, expected_counts(labels, log, measured={a for a in AXES if axes[a] is not None})


def _metrics(tp: int, fp: int, fn: int) -> dict:
    return {"tp": tp, "fp": fp, "fn": fn,
            "precision": tp / (tp + fp) if tp + fp else None,
            "recall": tp / (tp + fn) if tp + fn else None}


# What each pixel damage does to its label's counts: (tp, fp, fn) changes.
EFFECT = {"drop": (-1, 0, 1), "shift_in": (0, 0, 0), "shift_out": (-1, 1, 1), "add": (0, 1, 0)}
GROUPS = {"height": HEIGHT_GROUPS, "blur": BLUR_GROUPS}


def _tally(labels: list[dict], log: list[dict], effect: dict) -> dict:
    """tp, fp and fn keyed by (class, visibility group, height group, blur group): every label starts
    as a match, and each damage changes its label's counts by `effect`. An add with no label of its
    class in the frame has no groups (None), so it counts only overall and by class."""
    counts = {k: Counter() for k in ("tp", "fp", "fn")}
    for label in labels:
        counts["tp"][label["cls"], visibility_group(label["visibility"]), label["height"], label["blur"]] += 1
    for entry in log:
        key = entry["cls"], entry["group"], entry["height"], entry["blur"]
        for name, change in zip(("tp", "fp", "fn"), effect[entry["damage"]], strict=True):
            counts[name][key] += change
    return counts


def _rows(counts: dict, measured: set[str]) -> dict:
    """Overall, by class, by visibility group, and by height and blur group where measured."""
    fields = ("cls", "group", "height", "blur")

    def row(**where):
        return _metrics(*(sum(n for key, n in counts[name].items()
                              if all(key[fields.index(f)] == v for f, v in where.items()))
                          for name in ("tp", "fp", "fn")))

    return {
        "overall": row(),
        "by_class": {cls: row(cls=cls) for cls in CLASSES},
        "visibility": {cls: {g: row(cls=cls, group=g) for g in VISIBILITY_GROUPS} for cls in CLASSES},
        **{axis: {cls: {g: row(cls=cls, **{axis: g}) for g in GROUPS[axis]} for cls in AXIS_CLASSES[axis]}
           if axis in measured else None for axis in AXES},
    }


def expected_counts(labels: list[dict], log: list[dict], measured: set[str] = frozenset()) -> dict:
    """What the scorer must report, from the labels and the damage log alone: overall, by class,
    by visibility group within each class, and by the height and blur groups the clip records
    (`measured`; None for an axis it does not)."""
    return {**_rows(_tally(labels, log, EFFECT), measured), "damage": log}


def _compare(rows: list[tuple[str, dict | None, dict | None]]) -> list[str]:
    out = []
    for name, want, got in rows:
        if want is None or got is None:
            if want is not got:
                out.append(f"{name}: planted {want}, scored {got}")
            continue
        out += [f"{name}.{k}: planted {want[k]}, scored {got[k]}" for k in want if want[k] != got[k]]
    return out


def _group_rows(prefix: str, expected: dict, report: dict) -> list[tuple]:
    rows = [(f"{prefix}visibility.{c}.{g}", expected["visibility"][c][g], report["visibility"][c][g])
            for c in CLASSES for g in VISIBILITY_GROUPS]
    for axis in AXES:
        want, got = expected[axis], report[axis]
        if want is None or got is None:
            rows.append((f"{prefix}{axis}", want, got))
            continue
        rows += [(f"{prefix}{axis}.{c}.{g}", want[c][g], got[c][g])
                 for c in AXIS_CLASSES[axis] for g in GROUPS[axis]]
    return rows


def disagreements(expected: dict, report: dict) -> list[str]:
    """Every count or rate where the scorer's report differs from what was planted."""
    rows = [("overall", expected["overall"], report["overall"])]
    rows += [(f"by_class.{c}", expected["by_class"][c], report["by_class"][c]) for c in CLASSES]
    return _compare(rows + _group_rows("", expected, report))


PITCH_DAMAGES = ("drop", "shift_in", "shift_mid", "shift_out", "add")


def pitch_shift_m(cls: str) -> dict[str, float]:
    """How far each shift moves a copy's point on the pitch, from the radii alone: half the strict
    radius; halfway between strict and lenient; twice the lenient radius."""
    strict, lenient = RADIUS_M["strict"][cls], RADIUS_M["lenient"][cls]
    return {"shift_in": strict / 2, "shift_mid": (strict + lenient) / 2, "shift_out": 2 * lenient}


# What each damage does to a label's counts under each rule: (tp, fp, fn) changes.
PITCH_EFFECT = {
    "drop": {"strict": (-1, 0, 1), "lenient": (-1, 0, 1)},
    "shift_in": {"strict": (0, 0, 0), "lenient": (0, 0, 0)},
    "shift_mid": {"strict": (-1, 1, 1), "lenient": (0, 0, 0)},
    "shift_out": {"strict": (-1, 1, 1), "lenient": (-1, 1, 1)},
    "add": {"strict": (0, 1, 0), "lenient": (0, 1, 0)},
}


def _project(P, x: float, y: float, z: float) -> tuple[float, float] | None:
    """The pixel the saved matrix puts a pitch point at, as ninety.render.camera.project_with."""
    h = [P[i][0] * x + P[i][1] * y + P[i][2] * z + P[i][3] for i in range(3)]
    return None if h[2] <= 1e-9 else (h[0] / h[2], h[1] / h[2])


def _box_at(label: dict, uv: tuple[float, float]) -> list[float]:
    """The label's box translated so its point (bottom middle, or centre for the ball) is at uv."""
    x0, y0, x1, y1 = label["bbox"]
    du = uv[0] - (x0 + x1) / 2
    dv = uv[1] - (y1 if label["cls"] == "player" else (y0 + y1) / 2)
    return [x0 + du, y0 + dv, x1 + du, y1 + dv]


def _far(point, others: list, reach: float) -> bool:
    return all(o is None or math.dist(point, o) > reach + TIE_PX for o in others)


def fake_pitch_detections(frames: list[dict], seed: int, per_damage: int = 2,
                          only: dict | None = None) -> tuple[list[dict], dict]:
    """Return (detections, expected): per_damage of each of PITCH_DAMAGES for each class (on labels
    in the group `only` names, if given), moved in metres on the pitch, and what the pitch-level
    scorer must report under each rule, from the damage log alone (`expected_pitch_counts`)."""
    rng = fmath.Random(seed)
    labels = ground_truth(frames)
    cameras = {int(row["frame"]): row["camera"] for row in frames}
    points = [place(lab["cls"], lab["bbox"], cameras[lab["frame"]]["P"]) for lab in labels]
    axes = _frame_axes(frames)
    if axes["height"] is None and any(lab["cls"] == "ball" for lab in labels):
        raise ValueError("the pitch-level scorer needs the ball's height (ball.z) on every frame")
    _tag(labels, axes)
    by_frame_cls: dict[tuple[int, str], list[int]] = {}
    for i, label in enumerate(labels):
        by_frame_cls.setdefault((label["frame"], label["cls"]), []).append(i)
    detections = {i: {"frame": lab["frame"], "cls": lab["cls"], "bbox": list(lab["bbox"]), "score": 1.0}
                  for i, lab in enumerate(labels)}
    damaged: set[int] = set()
    added: list[dict] = []
    log: list[dict] = []

    for cls in CLASSES:
        reach = RADIUS_M["lenient"][cls]
        z = 0.0 if cls == "player" else BALL_CENTRE_Z
        victims = [i for i, lab in enumerate(labels)
                   if lab["cls"] == cls and points[i] is not None and _wanted(lab, only)]
        rng.shuffle(victims)
        for damage in PITCH_DAMAGES:
            for _ in range(per_damage):
                if damage == "add":
                    pool = [lab for lab in labels if lab["cls"] == cls and _wanted(lab, only)]
                    if not pool:
                        raise ValueError(f"no {cls} label to size a false box on")
                    source = rng.choice(pool)
                    camera = cameras[source["frame"]]
                    same = [labels[j] for j in by_frame_cls[(source["frame"], cls)]]
                    near_points = [points[j] for j in by_frame_cls[(source["frame"], cls)]]
                    w, h = source["bbox"][2] - source["bbox"][0], source["bbox"][3] - source["bbox"][1]
                    for _ in range(200):
                        x, y = rng.uniform(0, camera["width"] - w), rng.uniform(0, camera["height"] - h)
                        box = [x, y, x + w, y + h]
                        spot = place(cls, box, camera["P"])
                        if spot is not None and _far(spot, near_points, reach) and (
                                not same or _nearest(box, same) is not None):
                            break
                    else:
                        raise ValueError(f"no room for a false {cls} box in frame {source['frame']}")
                    near = _nearest(box, same)
                    added.append({"frame": source["frame"], "cls": cls, "bbox": box, "score": 1.0})
                    log.append({"damage": damage, "cls": cls, "frame": source["frame"], "shift_m": None,
                                "bbox": box, "group": visibility_group(near["visibility"]) if near else None,
                                **{axis: near[axis] if near else None for axis in AXES}})
                    continue
                for i in victims:
                    if i in damaged:
                        continue
                    label, here = labels[i], points[i]
                    camera = cameras[label["frame"]]
                    others = [points[j] for j in by_frame_cls[(label["frame"], cls)] if j != i]
                    if not _far(here, others, reach):
                        continue
                    if damage == "drop":
                        box, moved = label["bbox"], None
                        break
                    moved = pitch_shift_m(cls)[damage]
                    a = rng.uniform(0, 2 * math.pi)
                    spot = (here[0] + moved * fmath.cos(a), here[1] + moved * fmath.sin(a))
                    uv = _project(camera["P"], *spot, z)
                    if uv is None:
                        continue
                    box = _box_at(label, uv)
                    if not _in_image(box, camera) or not _far(spot, others, reach):
                        continue
                    if damage != "shift_in" and _nearest(
                            box, [labels[j] for j in by_frame_cls[(label["frame"], cls)]]) is not label:
                        continue
                    break
                else:
                    raise ValueError(f"not enough isolated {cls} labels to plant {damage} cleanly")
                damaged.add(i)
                if damage == "drop":
                    del detections[i]
                else:
                    detections[i]["bbox"] = box
                log.append({"damage": damage, "cls": cls, "frame": label["frame"], "shift_m": moved,
                            "group": visibility_group(label["visibility"]),
                            **{axis: label[axis] for axis in AXES}})

    out = [detections[i] for i in sorted(detections)] + added
    out.sort(key=lambda d: d["frame"])
    return out, expected_pitch_counts(labels, log, blur=axes["blur"] is not None)


def height_of(z: float) -> str:
    """EVALUATION.md's height groups, read here from the clip's ball height."""
    return HEIGHT_GROUPS[1] if z > IN_AIR_Z else HEIGHT_GROUPS[0]


def blur_of(blur_px) -> str:
    """EVALUATION.md's blur groups, read here from the frame's camera blur streak (its length)."""
    return BLUR_GROUPS[1] if math.hypot(*blur_px) > BLUR_PX else BLUR_GROUPS[0]


def expected_pitch_counts(labels: list[dict], log: list[dict], blur: bool = False) -> dict:
    """What the pitch-level scorer must report under each rule, from the labels and the damage
    log alone: overall, by class, by visibility group within each class, the ball by height (the
    pitch-level scorer always has it), and each class by blur when the clip records it (`blur`)."""
    measured = {"height", "blur"} if blur else {"height"}
    out = {rule: _rows(_tally(labels, log, {d: e[rule] for d, e in PITCH_EFFECT.items()}), measured)
           for rule in RULES}
    out["damage"] = log
    return out


def pitch_disagreements(expected: dict, report: dict) -> list[str]:
    """Every count or rate where the pitch-level report differs from what was planted."""
    rows = []
    for rule in RULES:
        want, got = expected[rule], report[rule]
        rows.append((f"{rule}.overall", want["overall"], got["overall"]))
        rows += [(f"{rule}.by_class.{c}", want["by_class"][c], got["by_class"][c]) for c in CLASSES]
        rows += _group_rows(f"{rule}.", want, got)
    return _compare(rows)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Plant known damage in copied labels and check the "
                                     "vision scorer reports exactly what was planted.")
    parser.add_argument("clips", nargs="+", type=Path)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--per-damage", type=int, default=2)
    args = parser.parse_args(argv)
    failed = False
    for clip in args.clips:
        frames = [json.loads(line) for line in (clip / "frames.jsonl").read_text().splitlines() if line]
        detections, expected = fake_box_detections(frames, args.seed, args.per_damage)
        report = score(frames, detections)
        problems = disagreements(expected, report)
        failed |= bool(problems)
        row = {"clip": clip.name, "labels": len(ground_truth(frames)), "detections": len(detections),
               "damages": dict(Counter(f"{e['cls']}.{e['damage']}" for e in expected["damage"])),
               "by_class": {c: {k: report["by_class"][c][k] for k in expected["by_class"][c]}
                            for c in CLASSES},
               "agrees": not problems, "problems": problems}
        print(json.dumps(row))
        if not has_cameras(frames):  # frames built without saved cameras have no pitch to check
            continue
        detections, expected = fake_pitch_detections(frames, args.seed, args.per_damage)
        problems = pitch_disagreements(expected, score_pitch(frames, detections))
        failed |= bool(problems)
        print(json.dumps({"clip": clip.name, "pitch": True, "detections": len(detections),
                          "damages": dict(Counter(f"{e['cls']}.{e['damage']}" for e in expected["damage"])),
                          "agrees": not problems, "problems": problems}))
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
