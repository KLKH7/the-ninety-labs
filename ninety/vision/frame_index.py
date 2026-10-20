"""Write a clip's labels-free frame index, so detection can run where the answer key must not go.

    uv run python -m ninety.vision.frame_index runs/test-frozen-<commit>/test/seed* --stride 1

`index.jsonl` holds, per frame, only what detection reads: clip id, frame number, time and image
path (ninety.vision.detect.frame_rows). With it beside the images, a rented GPU gets the images and
the index, never frames.jsonl, events.jsonl, meta.json or clip.json (which carries label counts).
Its detections come back and are scored locally against the truth (docs/eval/round2/PLAN.md).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

INDEX = "index.jsonl"
FIELDS = ("clip", "frame", "t", "image")


def write_index(clip_dir: Path, stride: int = 1) -> Path:
    """Each strided frame's clip id (from clip.json, as detect reads it), frame, t and image, and
    nothing else."""
    clip_id = json.loads((clip_dir / "clip.json").read_text())["clip_id"]
    out = clip_dir / INDEX
    with open(clip_dir / "frames.jsonl") as src, open(out, "w") as dst:
        for i, line in enumerate(src):
            if i % stride:
                continue
            row = {**json.loads(line), "clip": clip_id}
            dst.write(json.dumps({k: row[k] for k in FIELDS}) + "\n")
    return out


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Write labels-free frame indexes for detection elsewhere.")
    ap.add_argument("clips", nargs="+", type=Path)
    ap.add_argument("--stride", type=int, default=1, help="every Nth frame, as detection will run")
    a = ap.parse_args(argv)
    for clip in a.clips:
        print(write_index(clip, a.stride))


if __name__ == "__main__":
    main()
