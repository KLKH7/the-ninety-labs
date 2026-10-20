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

    uv run python -m ninety.eval.fake_box_detections runs/dataset/test/seed*
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter
from pathlib import Path

from ninety.eval.vision_score import (
    BALL_DISTANCE_PX,
    CLASSES,
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


def fake_box_detections(frames: list[dict], seed: int, per_damage: int = 2) -> tuple[list[dict], dict]:
    """Return (detections, expected): per_damage of each damage in DAMAGES for each class, and the
    counts the scorer must report, from the damage log alone (`expected_counts`)."""
    rng = fmath.Random(seed)  # the same draws as random.Random; refuses anything platform-dependent
    labels = ground_truth(frames)
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
        victims = [i for i, lab in enumerate(labels) if lab["cls"] == cls]
        rng.shuffle(victims)
        for damage in DAMAGES:
            for _ in range(per_damage):
                if damage == "add":
                    pool = [lab for lab in labels if lab["cls"] == cls]
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
                                "group": visibility_group(near["visibility"]) if near else None})
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
                            "group": visibility_group(label["visibility"])})

    out = [detections[i] for i in sorted(detections)] + added
    out.sort(key=lambda d: d["frame"])
    return out, expected_counts(labels, log)


def _metrics(tp: int, fp: int, fn: int) -> dict:
    return {"tp": tp, "fp": fp, "fn": fn,
            "precision": tp / (tp + fp) if tp + fp else None,
            "recall": tp / (tp + fn) if tp + fn else None}


def expected_counts(labels: list[dict], log: list[dict]) -> dict:
    """What the scorer must report, from the labels and the damage log alone: overall, by class,
    and by visibility group within each class."""
    tp: Counter = Counter()
    fp: Counter = Counter()
    fn: Counter = Counter()
    for label in labels:
        tp[label["cls"], visibility_group(label["visibility"])] += 1
    for entry in log:
        key = entry["cls"], entry["group"]
        if entry["damage"] in ("drop", "shift_out"):
            tp[key] -= 1
            fn[key] += 1
        if entry["damage"] in ("shift_out", "add"):
            fp[key] += 1  # an add with no label of its class in the frame has group None
    by_class = {cls: _metrics(*(sum(c[k] for k in c if k[0] == cls) for c in (tp, fp, fn)))
                for cls in CLASSES}
    return {
        "overall": _metrics(*(sum(c.values()) for c in (tp, fp, fn))),
        "by_class": by_class,
        "visibility": {cls: {g: _metrics(tp[cls, g], fp[cls, g], fn[cls, g]) for g in VISIBILITY_GROUPS}
                       for cls in CLASSES},
        "damage": log,
    }


def disagreements(expected: dict, report: dict) -> list[str]:
    """Every count or rate where the scorer's report differs from what was planted."""
    rows = [("overall", expected["overall"], report["overall"])]
    rows += [(f"by_class.{c}", expected["by_class"][c], report["by_class"][c]) for c in CLASSES]
    rows += [(f"visibility.{c}.{g}", expected["visibility"][c][g], report["visibility"][c][g])
             for c in CLASSES for g in VISIBILITY_GROUPS]
    return [f"{name}.{k}: planted {want[k]}, scored {got[k]}"
            for name, want, got in rows for k in want if want[k] != got[k]]


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
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
