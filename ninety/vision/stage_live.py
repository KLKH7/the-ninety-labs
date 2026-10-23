"""Stage the live detection job's inputs: a time window of a rendered clip, and a checkpoint.

    uv run python -m ninety.vision.stage_live <rendered clip> --from 100 --to 160 \\
        --checkpoint <folder with checkpoint_best_total.pth and train-manifest.json> \\
        --out runs/live-input

Runs on a maintainer's machine, before the image is built (infra/live-job.sh stage). It is not on
the live path: it reads the clip's frame file for each frame's time and image, as
ninety.vision.frame_index does, and writes what the job may read and nothing else:

    <out>/clip/index.jsonl          clip id, frame, time and image path of each frame in the window
    <out>/clip/images/*.jpg         those frames' images
    <out>/checkpoint/               the weights and their training record, copied

The window is [from, to] seconds on the clip's own clock; frames keep their numbers and times, so
detected events line up with the clip. The demo clip is an argument, never a constant here.
"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from ninety.vision.frame_index import FIELDS, INDEX

WEIGHTS = "checkpoint_best_total.pth"
RECORD = "train-manifest.json"


def stage_clip(clip_dir: Path, t0: float, t1: float, out: Path) -> int:
    """Copy the frames with t0 <= t <= t1 and write their labels-free index; returns how many."""
    if t1 <= t0:
        raise SystemExit(f"--to {t1} must be after --from {t0}")
    if out.exists():
        raise SystemExit(f"{out} exists: stage into a fresh folder")
    clip_id = json.loads((clip_dir / "clip.json").read_text())["clip_id"]
    (out / "images").mkdir(parents=True)
    rows = []
    with open(clip_dir / "frames.jsonl") as src:
        for line in src:
            fr = json.loads(line)
            if t0 <= fr["t"] <= t1:
                image = Path(fr["image"])
                shutil.copy2(clip_dir / image, out / "images" / image.name)
                row = {"clip": clip_id, "frame": fr["frame"], "t": fr["t"], "image": f"images/{image.name}"}
                rows.append({k: row[k] for k in FIELDS})
    if not rows:
        raise SystemExit(f"{clip_dir}: no frame between {t0} and {t1} s")
    (out / INDEX).write_text("".join(json.dumps(r) + "\n" for r in rows))
    return len(rows)


def stage_checkpoint(src: Path, out: Path) -> None:
    out.mkdir(parents=True)
    for name in (WEIGHTS, RECORD):
        if not (src / name).is_file():
            raise SystemExit(f"{src / name} is missing: the job needs the weights and their record")
        shutil.copy2(src / name, out / name)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Stage a clip window and a checkpoint for the live job.")
    ap.add_argument("clip", type=Path, help="a rendered clip folder")
    ap.add_argument("--from", dest="t0", type=float, required=True, help="seconds, on the clip's clock")
    ap.add_argument("--to", dest="t1", type=float, required=True)
    ap.add_argument("--checkpoint", type=Path, required=True, help=f"folder with {WEIGHTS} and {RECORD}")
    ap.add_argument("--out", type=Path, default=Path("runs/live-input"))
    a = ap.parse_args(argv)
    n = stage_clip(a.clip, a.t0, a.t1, a.out / "clip")
    stage_checkpoint(a.checkpoint, a.out / "checkpoint")
    print(json.dumps({"out": str(a.out), "frames": n, "from": a.t0, "to": a.t1}))


if __name__ == "__main__":
    main()
