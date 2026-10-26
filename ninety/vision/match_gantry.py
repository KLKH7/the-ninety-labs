"""One broadcast gantry for a match, from frames of all its clips.

    uv run --group vision python -m ninety.vision.match_gantry \\
        --clip <clip> --detections <detections.jsonl> [--clip ... --detections ...] --out <gantry.json>

A match has one main camera on one gantry, and a clip that shows only one end of the pitch cannot
pin it (docs/eval/match-gantry-plan.md). This fits the gantry once from every clip's anchors (its
frames at every 25th index, players and ball masked out, as observe reads them) pooled
(pitch.fit_match_gantry), and writes it for `observe --match-gantry` and `live_job --match-gantry`.

Reads each clip's `images/` and detections file, nothing else: not frames.jsonl, events.jsonl,
clip.json or meta.json. Which clips are one match is the caller's statement (the clips passed
together are one feed); nothing here infers it. The gantry is written unrounded, so a match of one
clip gives exactly the gantry that clip's own fit finds.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from ninety.vision import pitch
from ninety.vision.detections import read_detections
from ninety.vision.track import SCORE_MIN

ANCHOR_EVERY = 25  # as pitch.fit_clip takes a clip's anchors


def anchors(images: list[Path], dets: list, load) -> tuple[list[np.ndarray], int, int]:
    """One clip's anchors (marking pixels of every ANCHOR_EVERY-th frame), and the image size."""
    if len(images) != len(dets):
        raise ValueError(f"{len(images)} images but {len(dets)} detection lines: they pair one to one")
    out, size = [], None
    for img, fd in list(zip(images, dets, strict=True))[::ANCHOR_EVERY]:
        rgb = load(img)
        size = rgb.shape[1], rgb.shape[0]
        out.append(pitch.line_points(rgb, [d.bbox for d in fd.detections if d.score >= SCORE_MIN]))
    return out, *size


def fit(clips: list[tuple[list[Path], list]], load) -> dict:
    """The match gantry from (images, detections) per clip."""
    by_clip, sizes = [], set()
    for images, dets in clips:
        a, w, h = anchors(images, dets, load)
        by_clip.append(a)
        sizes.add((w, h))
    if len(sizes) != 1:
        raise ValueError(f"the clips are not one feed: image sizes {sorted(sizes)}")
    (w, h), = sizes
    g = pitch.fit_match_gantry(by_clip, w, h)
    return {"gantry": list(g), "clips": len(by_clip), "anchors": sum(map(len, by_clip))}


def read(path: Path) -> tuple[float, float, float]:
    g = json.loads(Path(path).read_text())["gantry"]
    if len(g) != 3:
        raise ValueError(f"{path}: a gantry is three numbers, not {g}")
    return tuple(float(v) for v in g)


def main(argv: list[str] | None = None) -> None:
    from PIL import Image

    ap = argparse.ArgumentParser(description="Fit one broadcast gantry from all of a match's clips.")
    ap.add_argument("--clip", type=Path, action="append", required=True, help="a clip's folder (images/)")
    ap.add_argument("--detections", type=Path, action="append", required=True,
                    help="its detections, in the same order as --clip")
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args(argv)
    if len(a.clip) != len(a.detections):
        ap.error("one --detections per --clip")
    clips = [(sorted((c / "images").glob("*.jpg")), read_detections(d))
             for c, d in zip(a.clip, a.detections, strict=True)]
    body = fit(clips, lambda p: np.asarray(Image.open(p).convert("RGB")))
    a.out.write_text(json.dumps(body) + "\n", encoding="utf-8")
    print(json.dumps({"out": str(a.out), **body}))


if __name__ == "__main__":
    main()
