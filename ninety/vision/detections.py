"""The detections contract: what the detector writes and the vision scorer reads.

One JSON line per frame, in `detections.jsonl` next to the clip:

    {"clip": "seed900001", "frame": 1200, "t": 48.0,
     "model": {"name": "rf-detr", "size": "small", "version": "<pinned>", "checkpoint": "coco"},
     "detections": [{"cls": "player", "bbox": [x0, y0, x1, y1], "score": 0.91}]}

- `clip`, `frame` and `t` are copied from the frame's row in `frames.jsonl`, so `frame` is the
  match frame index (the schema's meaning), not the image's position in the clip.
- `cls` is "player" or "ball". `bbox` is [x0, y0, x1, y1] in pixels, the same key, order and
  pixel convention as the labels in `frames.jsonl`.
- Every frame the detector ran on gets a line, with an empty list when nothing was found, so a
  frame with no detections is never mistaken for a frame that was not run.
- The detector keeps everything down to a score of `SCORE_FLOOR`. Nothing here applies a
  threshold: choosing one is the scorer's job, and it needs the low scores to draw a curve.
"""

from __future__ import annotations

import json
import math
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

CLASSES = ("player", "ball")
# RF-DETR sizes released under Apache-2.0 (AGENTS.md); the others carry a different license.
SIZES = ("nano", "small", "medium", "large")
SCORE_FLOOR = 0.05  # the detector keeps detections at or above this score


@dataclass(frozen=True)
class Model:
    name: str
    size: str
    version: str
    checkpoint: str

    def __post_init__(self) -> None:
        for key in ("name", "version", "checkpoint"):
            if not isinstance(getattr(self, key), str) or not getattr(self, key):
                raise ValueError(f"model {key} must be a non-empty string")
        if self.size not in SIZES:
            raise ValueError(f"model size {self.size!r} is not one of {SIZES}")


@dataclass(frozen=True)
class Detection:
    cls: str
    bbox: tuple[float, float, float, float]
    score: float

    def __post_init__(self) -> None:
        if self.cls not in CLASSES:
            raise ValueError(f"cls {self.cls!r} is not one of {CLASSES}")
        if len(self.bbox) != 4 or not all(_number(v) for v in self.bbox):
            raise ValueError(f"bbox {self.bbox!r} is not four finite numbers")
        x0, y0, x1, y1 = self.bbox
        if x1 < x0 or y1 < y0:
            raise ValueError(f"bbox {self.bbox!r} is not [x0, y0, x1, y1] with x0 <= x1 and y0 <= y1")
        if not _number(self.score) or not 0.0 <= self.score <= 1.0:
            raise ValueError(f"score {self.score!r} is not a number from 0 to 1")


@dataclass(frozen=True)
class FrameDetections:
    clip: str
    frame: int
    t: float
    model: Model
    detections: tuple[Detection, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.clip, str) or not self.clip:
            raise ValueError("clip must be a non-empty string")
        if isinstance(self.frame, bool) or not isinstance(self.frame, int) or self.frame < 0:
            raise ValueError(f"frame {self.frame!r} is not a non-negative integer")
        if not _number(self.t) or self.t < 0:
            raise ValueError(f"t {self.t!r} is not a non-negative number")

    def to_dict(self) -> dict:
        return {
            "clip": self.clip,
            "frame": self.frame,
            "t": self.t,
            "model": {
                "name": self.model.name,
                "size": self.model.size,
                "version": self.model.version,
                "checkpoint": self.model.checkpoint,
            },
            "detections": [
                {"cls": d.cls, "bbox": list(d.bbox), "score": d.score} for d in self.detections
            ],
        }

    @classmethod
    def from_dict(cls, row: dict) -> FrameDetections:
        _keys(row, {"clip", "frame", "t", "model", "detections"}, "row")
        _keys(row["model"], {"name", "size", "version", "checkpoint"}, "model")
        if not isinstance(row["detections"], list):
            raise ValueError("detections must be a list")
        dets = []
        for d in row["detections"]:
            _keys(d, {"cls", "bbox", "score"}, "detection")
            if not isinstance(d["bbox"], list):
                raise ValueError(f"bbox {d['bbox']!r} is not a list")
            dets.append(Detection(cls=d["cls"], bbox=tuple(d["bbox"]), score=d["score"]))
        return cls(
            clip=row["clip"],
            frame=row["frame"],
            t=row["t"],
            model=Model(**row["model"]),
            detections=tuple(dets),
        )


def write_detections(path: Path | str, frames: Iterable[FrameDetections]) -> None:
    """Write one line per frame, in the order given."""
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        for fd in frames:
            f.write(json.dumps(fd.to_dict(), separators=(",", ":")) + "\n")


def read_detections(path: Path | str) -> list[FrameDetections]:
    """Read every line; refuse the file on the first line that breaks the contract."""
    out: list[FrameDetections] = []
    seen: set[tuple[str, int]] = set()
    with open(path, encoding="utf-8") as f:
        for n, line in enumerate(f, start=1):
            if not line.strip():
                continue
            try:
                fd = FrameDetections.from_dict(json.loads(line))
            except (ValueError, TypeError) as e:
                raise ValueError(f"{path}:{n}: {e}") from e
            if (fd.clip, fd.frame) in seen:
                raise ValueError(f"{path}:{n}: frame {fd.frame} of {fd.clip} appears twice")
            seen.add((fd.clip, fd.frame))
            out.append(fd)
    return out


def _number(v: object) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _keys(obj: object, want: set[str], what: str) -> None:
    if not isinstance(obj, dict):
        raise ValueError(f"{what} is not a JSON object")
    if set(obj) != want:
        raise ValueError(f"{what} keys {sorted(obj)} are not {sorted(want)}")
