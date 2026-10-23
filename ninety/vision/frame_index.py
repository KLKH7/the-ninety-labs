"""Write a clip's labels-free frame index, so detection can run where the answer key must not go.

    uv run python -m ninety.vision.frame_index runs/test-frozen-<commit>/test/seed* --stride 1

`index.jsonl` holds, per frame, only what detection reads: clip id, frame number, time and image
path (ninety.vision.detect.frame_rows). With it beside the images, a rented GPU gets the images and
the index, never frames.jsonl, events.jsonl, meta.json or clip.json (which carries label counts).
Its detections come back and are scored locally against the truth (docs/eval/round2/PLAN.md).

A clip of the fixed tactical camera holds one folder per lens, `views/<name>/`, each with its own
frame file and images; each view gets its own index there, and the clip id is the clip's.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

INDEX = "index.jsonl"
FIELDS = ("clip", "frame", "t", "image")
VIEWS = "views"


def views(clip_dir: Path) -> dict[str, Path]:
    """The clip's frame folders by view name: {"": the clip} for one camera, or each folder under
    `views/` for the tactical camera's lenses."""
    root = clip_dir / VIEWS
    if not root.is_dir():
        return {"": clip_dir}
    found = {p.name: p for p in sorted(root.iterdir()) if p.is_dir()}
    if not found:
        raise SystemExit(f"{root} holds no view")
    return found


def clip_id(folder: Path) -> str:
    """The clip id from clip.json: the folder's own, or, for a view, its clip's."""
    for d in (folder, folder.parent.parent):
        if (d / "clip.json").is_file() and (d is folder or folder.parent.name == VIEWS):
            return json.loads((d / "clip.json").read_text())["clip_id"]
    raise SystemExit(f"{folder}: no clip.json in it or, for a view, in its clip")


def write_indexes(clip_dir: Path, stride: int = 1) -> list[Path]:
    """An index for the clip, or one for each of its views."""
    return [write_index(d, stride) for d in views(clip_dir).values()]


def write_index(clip_dir: Path, stride: int = 1) -> Path:
    """Each strided frame's clip id (from clip.json, as detect reads it), frame, t and image, and
    nothing else."""
    clip_id_ = clip_id(clip_dir)
    out = clip_dir / INDEX
    with open(clip_dir / "frames.jsonl") as src, open(out, "w") as dst:
        for i, line in enumerate(src):
            if i % stride:
                continue
            row = {**json.loads(line), "clip": clip_id_}
            dst.write(json.dumps({k: row[k] for k in FIELDS}) + "\n")
    return out


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Write labels-free frame indexes for detection elsewhere.")
    ap.add_argument("clips", nargs="+", type=Path)
    ap.add_argument("--stride", type=int, default=1, help="every Nth frame, as detection will run")
    a = ap.parse_args(argv)
    for clip in a.clips:
        for index in write_indexes(clip, a.stride):
            print(index)


if __name__ == "__main__":
    main()
