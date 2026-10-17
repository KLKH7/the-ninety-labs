"""Deterministic fake pixel detections for scoring tests and smoke reports."""

from __future__ import annotations

import random
from collections.abc import Mapping

from ninety.eval.vision_score import BALL_DISTANCE_PX, PLAYER_IOU, ground_truth, iou, score


def _shift(box, dx, dy):
    x0, y0, x1, y1 = box
    return [x0 + dx, y0 + dy, x1 + dx, y1 + dy]


def _frame_dimensions(frame):
    camera = frame.get("camera", {})
    width = camera.get("width", frame.get("width"))
    height = camera.get("height", frame.get("height"))
    if width is None or height is None:
        raise ValueError(f"frame {frame.get('frame', '?')} has no image dimensions")
    return float(width), float(height)


def _in_frame(box, width, height):
    x0, y0, x1, y1 = box
    return 0 <= x0 <= x1 <= width and 0 <= y0 <= y1 <= height


def _away_from_truth(box, cls, frame, labels):
    same_class = [
        label for label in labels
        if label["frame"] == frame and label["cls"] == cls
    ]
    if cls == "player":
        return all(iou(box, label["bbox"]) < PLAYER_IOU for label in same_class)
    x0, y0, x1, y1 = box
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    return all(
        ((cx - (label["bbox"][0] + label["bbox"][2]) / 2) ** 2
         + (cy - (label["bbox"][1] + label["bbox"][3]) / 2) ** 2) ** 0.5
        > BALL_DISTANCE_PX
        for label in same_class
    )


def _false_box(source, frame, labels, width, height):
    x0, y0, x1, y1 = source["bbox"]
    box_width, box_height = x1 - x0, y1 - y0
    max_x = width - box_width
    max_y = height - box_height
    if max_x < 0 or max_y < 0:
        raise ValueError("no in-frame placement exists for false box")
    for y in range(int(max_y) + 1):
        for x in range(int(max_x) + 1):
            candidate = [float(x), float(y), float(x) + box_width, float(y) + box_height]
            if _away_from_truth(candidate, source["cls"], frame, labels):
                return candidate
    raise ValueError("no in-frame placement exists for false box")


def fake_detections(
    frames,
    *,
    seed: int = 0,
    drop: int = 0,
    shift: int = 0,
    add: int = 0,
    shift_px: float = 20.0,
    score_value: float = 1.0,
    damages: Mapping[str, int] | None = None,
    damage: Mapping[str, int] | None = None,
):
    """Copy boxes and apply deterministic damage counts.

    ``drop``, ``shift`` and ``add`` are counts.  A shifted box must be outside
    its class's matching rule and not land ambiguously near another label.
    """
    if damages and damage:
        raise ValueError("pass only one of damages or damage")
    if damage:
        damages = damage
    if damages:
        drop = damages.get("drop", drop)
        shift = damages.get("shift", shift)
        add = damages.get("add", add)
    labels = ground_truth(frames)
    frames_by_number = {int(frame["frame"]): frame for frame in frames}
    rng = random.Random(seed)
    if drop + shift > len(labels):
        raise ValueError("damage exceeds the number of drawn boxes")
    chosen = list(range(len(labels)))
    rng.shuffle(chosen)
    drop_ids = set(chosen[:drop])
    shift_ids = set(chosen[drop:drop + shift])
    detections = []
    for index, label in enumerate(labels):
        if index in drop_ids:
            continue
        box = list(label["bbox"])
        if index in shift_ids:
            dx = shift_px
            shifted = _shift(box, dx, 0)
            width, height = _frame_dimensions(frames_by_number[label["frame"]])
            if not _in_frame(shifted, width, height):
                raise ValueError("shift damage has no in-frame placement")
            if not _away_from_truth(shifted, label["cls"], label["frame"], labels):
                raise ValueError("shift damage is not outside the matching rule")
            box = shifted
        detections.append({"frame": label["frame"], "cls": label["cls"], "bbox": box, "score": score_value})
    for _ in range(add):
        if not labels:
            raise ValueError("cannot add a detection without frame labels")
        source = rng.choice(labels)
        width, height = _frame_dimensions(frames_by_number[source["frame"]])
        box = _false_box(source, source["frame"], labels, width, height)
        detections.append({"frame": source["frame"], "cls": source["cls"], "bbox": box, "score": score_value})
    expected = score(frames, detections)
    return detections, expected


def expected_metrics(frames, detections, threshold=0.5):
    """Convenience name for callers that already have damaged detections."""
    return score(frames, detections, threshold)


make_fake_detections = fake_detections
fake_box_detections = fake_detections
