"""The image stage of event detection: images + detections -> observations on the pitch.

    uv run --group vision python -m ninety.vision.observe <clip> \\
        --detections <detections.jsonl> --out <observations.jsonl>

Reads the clip's `images/` and the detections file (ninety/vision/detections.py), nothing else: not
frames.jsonl, events.jsonl, clip.json or meta.json, which hold the answer key and the render
settings. Images are paired with detection lines in order (both are one per frame, in frame order;
the counts must agree). For each frame it writes one line:

    {"frame", "t",
     "camera": {"ok", "median_px", "points", "P"},       # estimated from the markings (pitch.py)
     "players": [{"bbox", "score", "x", "y", "rgb"}],     # foot point on the pitch, kit colour
     "ball": [{"bbox", "score", "x", "y"}]}               # centre, on the ground

Positions are null on a frame whose camera fit is not ok. A player's place is the bottom centre
of his box (where his feet meet the ground); the ball's is its box centre taken to be on the
ground, so a ball in the air is placed too far from the camera (planned: height from its path).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from ninety.vision import pitch
from ninety.vision.detections import read_detections
from ninety.vision.track import SCORE_MIN

BALL_CENTRE_Z = 0.11  # a ball on the ground has its centre one radius up (Law 2: about 0.11 m)


def kit_rgb(rgb: np.ndarray, bbox) -> list[float] | None:
    """Median colour of the shirt: the box's upper-middle part (20 to 50% down, the middle 60%
    across), without grass-coloured pixels. None when nothing is left."""
    x0, y0, x1, y1 = bbox
    w, h = x1 - x0, y1 - y0
    H, W = rgb.shape[:2]
    xa, xb = int(max(0, x0 + 0.2 * w)), int(min(W, x1 - 0.2 * w))
    ya, yb = int(max(0, y0 + 0.2 * h)), int(min(H, y0 + 0.5 * h))
    patch = rgb[ya:yb, xa:xb].reshape(-1, 3).astype(np.float32)
    if not len(patch):
        return None
    r, g, b = patch[:, 0], patch[:, 1], patch[:, 2]
    patch = patch[~((g > r + 10) & (g > b + 10))]
    if not len(patch):
        return None
    return [round(float(v), 1) for v in np.median(patch, axis=0)]


def observe(images: list[Path], dets: list, load) -> list[dict]:
    """`load(path) -> (H, W, 3) uint8` reads an image; passed in so tests need no image files."""
    if len(images) != len(dets):
        raise ValueError(f"{len(images)} images but {len(dets)} detection lines: they pair one to one")
    rgbs, points = [], []
    for img, fd in zip(images, dets, strict=True):
        rgb = load(img)
        boxes = [d.bbox for d in fd.detections if d.score >= SCORE_MIN]
        rgbs.append(rgb)
        points.append(pitch.line_points(rgb, boxes))
    H, W = rgbs[0].shape[:2]
    gantry, fits = pitch.fit_clip(points, W, H)
    rows = []
    for rgb, fd, fit in zip(rgbs, dets, fits, strict=True):
        view = fit.view if fit.ok else None
        players, balls = [], []
        for d in fd.detections:
            x0, y0, x1, y1 = d.bbox
            if d.cls == "player":
                foot = np.array([[(x0 + x1) / 2, y1]])
                xy = view.to_ground(foot)[0] if view else (None, None)
                players.append({"bbox": list(d.bbox), "score": d.score, "x": _r(xy[0]), "y": _r(xy[1]),
                                "rgb": kit_rgb(rgb, d.bbox) if d.score >= SCORE_MIN else None})
            else:
                c = np.array([[(x0 + x1) / 2, (y0 + y1) / 2]])
                xy = view.to_ground(c, z=BALL_CENTRE_Z)[0] if view else (None, None)
                balls.append({"bbox": list(d.bbox), "score": d.score, "x": _r(xy[0]), "y": _r(xy[1])})
        rows.append({
            "frame": fd.frame, "t": fd.t,
            "camera": {"ok": fit.ok, "median_px": fit.median_px, "points": fit.points,
                       "P": ([[round(float(v), 6) for v in row] for row in fit.view.P()]
                             if fit.view else None)},
            "players": players, "ball": balls,
        })
    rows[0]["gantry"] = [round(v, 3) for v in gantry]
    return rows


def _r(v) -> float | None:
    return None if v is None or not np.isfinite(v) else round(float(v), 3)


def main(argv: list[str] | None = None) -> None:
    from PIL import Image

    ap = argparse.ArgumentParser(description="Place a clip's detections on the pitch from its images.")
    ap.add_argument("clip", type=Path)
    ap.add_argument("--detections", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args(argv)
    images = sorted((a.clip / "images").glob("*.jpg"))
    dets = read_detections(a.detections)
    rows = observe(images, dets, lambda p: np.asarray(Image.open(p).convert("RGB")))
    with open(a.out, "w", encoding="utf-8", newline="\n") as f:
        for r in rows:
            f.write(json.dumps(r, separators=(",", ":")) + "\n")
    ok = sum(r["camera"]["ok"] for r in rows)
    print(json.dumps({"out": str(a.out), "frames": len(rows), "camera_ok": ok, "gantry": rows[0]["gantry"]}))


if __name__ == "__main__":
    main()
