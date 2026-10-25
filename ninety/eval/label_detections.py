"""A clip's drawn labels copied as detections, score 1: the detector's stand-in where no checkpoint is.

    uv run python -m ninety.eval.label_detections <clip> --out <detections.jsonl>

Reads the answer key (frames.jsonl), so it is evaluation, never the live path. Every player and the
ball with a box on screen (visibility above 0) becomes a detection with score 1.0, one line per
frame in the detections contract (ninety/vision/detections.py), so `observe` can fit the camera
from the pixels and place them as it would a detector's. Numbers made from it measure the camera
fit and what comes after it, and are an upper bound on what a detector would give (its boxes are
exact; docs/eval/camera-cuts-plan.md did the same).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ninety.vision.detections import Detection, FrameDetections, Model, write_detections

MODEL = Model(name="labels", size="small", version="drawn-labels", checkpoint="labels")


def label_detections(clip: Path) -> list[FrameDetections]:
    clip_id = json.loads((clip / "clip.json").read_text())["clip_id"]
    out = []
    for line in (clip / "frames.jsonl").read_text().splitlines():
        if not line.strip():
            continue
        f = json.loads(line)
        dets = [Detection("player", tuple(float(v) for v in p["bbox"]), 1.0)
                for p in f["players"] if p.get("bbox") and p.get("visibility", 0) > 0]
        b = f.get("ball") or {}
        if b.get("bbox") and b.get("visibility", 0) > 0:
            dets.append(Detection("ball", tuple(float(v) for v in b["bbox"]), 1.0))
        out.append(FrameDetections(clip_id, f["frame"], f["t"], MODEL, tuple(dets)))
    return out


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="A clip's drawn labels as detections, score 1.")
    ap.add_argument("clip", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args(argv)
    rows = label_detections(a.clip)
    write_detections(a.out, rows)
    print(json.dumps({"out": str(a.out), "frames": len(rows),
                      "detections": sum(len(r.detections) for r in rows)}))


if __name__ == "__main__":
    main()
