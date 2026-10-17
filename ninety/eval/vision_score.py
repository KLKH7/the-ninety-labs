"""Deterministic pixel-level scoring for player and ball detections.

Ground-truth rows are read from ``frames.jsonl``.  A detection is a mapping with
``frame``, ``cls`` (``player`` or ``ball``), ``bbox`` and ``score``.
"""

from __future__ import annotations

import argparse
import json
import math
from collections.abc import Iterable, Mapping
from pathlib import Path

CLASSES = ("player", "ball")
PLAYER_IOU = 0.50
BALL_DISTANCE_PX = 5.0
DEFAULT_THRESHOLD = 0.5
VISIBILITY_GROUPS = ("visible", "partly hidden", "mostly hidden")


def load_jsonl(path: str | Path) -> list[dict]:
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


def _box(box: Iterable[float]) -> tuple[float, float, float, float]:
    values = tuple(float(v) for v in box)
    if len(values) != 4 or values[2] < values[0] or values[3] < values[1]:
        raise ValueError(f"invalid bbox: {box!r}")
    return values  # type: ignore[return-value]


def iou(a: Iterable[float], b: Iterable[float]) -> float:
    ax0, ay0, ax1, ay1 = _box(a)
    bx0, by0, bx1, by1 = _box(b)
    area_a = max(0.0, ax1 - ax0) * max(0.0, ay1 - ay0)
    area_b = max(0.0, bx1 - bx0) * max(0.0, by1 - by0)
    overlap = max(0.0, min(ax1, bx1) - max(ax0, bx0)) * max(0.0, min(ay1, by1) - max(ay0, by0))
    union = area_a + area_b - overlap
    return overlap / union if union else 0.0


def center_distance(a: Iterable[float], b: Iterable[float]) -> float:
    ax0, ay0, ax1, ay1 = _box(a)
    bx0, by0, bx1, by1 = _box(b)
    return math.hypot((ax0 + ax1 - bx0 - bx1) / 2, (ay0 + ay1 - by0 - by1) / 2)


def visibility_group(visibility: float) -> str | None:
    if visibility >= 0.9:
        return "visible"
    if visibility >= 0.5:
        return "partly hidden"
    if visibility > 0:
        return "mostly hidden"
    return None


def ground_truth(frames: Iterable[Mapping]) -> list[dict]:
    """Flatten drawn labels from frame rows into scorer labels."""
    labels = []
    for row in frames:
        frame = int(row["frame"])
        for label in row.get("boxes", []):
            if label.get("bbox") is not None and label.get("cls") in CLASSES:
                labels.append({
                    "frame": frame, "cls": label["cls"], "bbox": label["bbox"],
                    "visibility": float(label.get("visibility", 1.0)),
                })
        if row.get("boxes"):
            continue
        for player in row.get("players", []):
            if player.get("bbox") is not None:
                labels.append({
                    "frame": frame, "cls": "player", "bbox": player["bbox"],
                    "visibility": float(player.get("visibility", 1.0)),
                })
        ball = row.get("ball", {})
        if ball.get("bbox") is not None:
            labels.append({
                "frame": frame, "cls": "ball", "bbox": ball["bbox"],
                "visibility": float(ball.get("visibility", 1.0)),
            })
    return labels


def _candidate(true: dict, detected: dict) -> tuple[float, float] | None:
    if true["cls"] == "player":
        value = iou(true["bbox"], detected["bbox"])
        return (value, center_distance(true["bbox"], detected["bbox"])) if value >= PLAYER_IOU else None
    distance = center_distance(true["bbox"], detected["bbox"])
    return (distance, 0.0) if distance <= BALL_DISTANCE_PX else None


def match(labels: list[dict], detections: list[dict], threshold: float = DEFAULT_THRESHOLD) -> list[dict]:
    """Match eligible boxes one-to-one, best-first within each frame and class."""
    detections = [d for d in detections if float(d.get("score", 0.0)) >= threshold]
    candidates = []
    for ti, true in enumerate(labels):
        for di, detected in enumerate(detections):
            if (true["frame"], true["cls"]) != (detected["frame"], detected["cls"]):
                continue
            quality = _candidate(true, detected)
            if quality is not None:
                candidates.append((true["cls"], quality[0], quality[1], ti, di))
    candidates.sort(
        key=lambda item: (
            0 if item[0] == "player" else 1,
            -item[1] if item[0] == "player" else item[1],
            item[2],
            item[3],
        ),
    )
    used_true: set[int] = set()
    used_detected: set[int] = set()
    pairs = []
    for _cls, _primary, _secondary, ti, di in candidates:
        if ti in used_true or di in used_detected:
            continue
        used_true.add(ti)
        used_detected.add(di)
        true, detected = labels[ti], detections[di]
        pairs.append({"truth": ti, "detection": di, "frame": true["frame"], "cls": true["cls"],
                      "visibility": true["visibility"],
                      "group": visibility_group(true["visibility"])})
    return pairs


def _metrics(tp: int, fp: int, fn: int) -> dict:
    precision = tp / (tp + fp) if tp + fp else None
    recall = tp / (tp + fn) if tp + fn else None
    f1 = (
        2 * precision * recall / (precision + recall)
        if precision is not None and recall is not None and precision + recall
        else None
    )
    return {"tp": tp, "fp": fp, "fn": fn, "precision": precision, "recall": recall, "f1": f1}


def score(
    frames: Iterable[Mapping],
    detections: Iterable[Mapping],
    threshold: float = DEFAULT_THRESHOLD,
) -> dict:
    """Return overall and visibility-group pixel metrics."""
    frames = list(frames)
    labels = ground_truth(frames)
    detections = [dict(d) for d in detections]
    eligible = [d for d in detections if float(d.get("score", 0.0)) >= threshold]
    pairs = match(labels, eligible, threshold=threshold)
    matched_truth = {p["truth"] for p in pairs}
    matched_detection = {p["detection"] for p in pairs}
    overall = _metrics(len(pairs), len(eligible) - len(pairs), len(labels) - len(pairs))
    groups = {}
    for cls in CLASSES:
        groups[cls] = {}
        for group in VISIBILITY_GROUPS:
            group_truth = {
                i for i, label in enumerate(labels)
                if label["cls"] == cls and visibility_group(label["visibility"]) == group
            }
            group_pairs = [p for p in pairs if p["truth"] in group_truth]
            # A false positive has no visibility of its own. Attribute it to
            # the nearest drawn label only when it is in the same frame/class;
            # isolated false positives remain in overall metrics.
            group_fp = 0
            for di, detected in enumerate(eligible):
                if di in matched_detection or detected["cls"] != cls:
                    continue
                nearby = [
                    (center_distance(label["bbox"], detected["bbox"]), i)
                    for i, label in enumerate(labels)
                    if label["frame"] == detected["frame"] and label["cls"] == cls
                ]
                if nearby and visibility_group(labels[min(nearby)[1]]["visibility"]) == group:
                    group_fp += 1
            groups[cls][group] = _metrics(
                len(group_pairs),
                group_fp,
                len(group_truth - matched_truth),
            )
    by_class = {}
    for cls in CLASSES:
        truth_cls = [i for i, label in enumerate(labels) if label["cls"] == cls]
        detected_cls = [i for i, d in enumerate(eligible) if d["cls"] == cls]
        tp = sum(1 for p in pairs if p["cls"] == cls)
        by_class[cls] = _metrics(tp, len(detected_cls) - tp, len(truth_cls) - tp)
    return {
        "rules": {
            "score_threshold": threshold,
            "player_iou": PLAYER_IOU,
            "ball_center_distance_px": BALL_DISTANCE_PX,
            "match": "same frame/class, one-to-one, best-first",
        },
        "overall": overall, "by_class": by_class, "visibility": groups,
        "pairs": pairs,
    }


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Score pixel detections against frames.jsonl labels.")
    parser.add_argument("--frames", type=Path, required=True)
    parser.add_argument("--detected", type=Path, required=True)
    parser.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)
    report = score(load_jsonl(args.frames), load_jsonl(args.detected), args.threshold)
    text = json.dumps(report, indent=2) + "\n"
    if args.report:
        args.report.write_text(text)
    print(text, end="")


if __name__ == "__main__":
    main()
