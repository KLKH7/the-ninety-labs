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
import math
from pathlib import Path

import numpy as np

from ninety.vision import pitch
from ninety.vision.detections import read_detections
from ninety.vision.track import SCORE_MIN

BALL_CENTRE_Z = 0.11  # a ball on the ground has its centre one radius up (Law 2: about 0.11 m)
# Whether a frame's camera is trusted: its players are as tall as they should be. Through a right
# camera a player's box is about as tall as an upright PLAYER_HEIGHT_M segment at his feet projects
# (design: about the renderer's mean player, which it draws from N(1.81 m, 0.07 m),
# ninety/render/scene.py; the band absorbs the spread); a camera at the wrong distance or zoom
# scales every player the same wrong way. The frame's median ratio must lie in HEIGHT_BAND: the
# 1st to 99th percentile of that ratio on validation frames whose ground mapping is within 1.0 m
# (docs/eval/detector-plan.md, step B; docs/eval/detector-derive.json). It replaced the marking test
# (half the marking pixels within 1.5 px), which trusted 198 badly wrong frames on validation and
# kept 89% of the good ones, where this keeps 98%. The marking fit's own verdict is still kept as
# `markings_ok`, and still guides the fit from frame to frame (pitch.fit_clip).
# A frame the heights trust must also agree with its neighbours (`agree`): a broadcast camera pans
# continuously, under 0.02 rad a frame (pitch.STEP_SD), so the ground point at the image centre
# moves little from frame to frame. A frame is kept only if that point lies within NEIGHBOUR_M of
# the nearest other height-trusted frame's within NEIGHBOUR_FRAMES (design, set before measuring;
# docs/eval/camera-bound-plan.md). On validation that cut the worst trusted frame from 55 m wrong
# to 8.2 m (observed, under the plan's 8.5 m) and kept every good frame the heights kept. It sees an
# isolated wrong frame only: frames wrong the same way agree and pass together. A tie between two
# neighbours goes to the earlier (fixed with the plan's values, not tuned).
# Known limit (lesson 159): frames whose wrong cameras agree with each other still pass, since no
# check of one frame against another can see them: a whole clip offset the same way (validation
# seed 108, about 2 to 8 m), and a run of 4 frames on test clip 900003, about 46 m wrong.
NEIGHBOUR_FRAMES = 5
NEIGHBOUR_M = 2.0
PLAYER_HEIGHT_M = 1.80
HEIGHT_BAND = (0.901, 1.002)


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


def _ground(P: np.ndarray, uv: tuple[float, float], z: float = 0.0) -> tuple[float, float] | None:
    """The pixel back on the horizontal plane at height z through camera P."""
    H = np.c_[P[:, 0], P[:, 1], P[:, 2] * z + P[:, 3]]
    g = np.linalg.solve(H, np.array([uv[0], uv[1], 1.0]))
    return (float(g[0] / g[2]), float(g[1] / g[2])) if g[2] != 0 else None


def height_ratio(players: list[dict], P: np.ndarray) -> float | None:
    """The median, over the frame's player detections, of box height over the projected height of an
    upright PLAYER_HEIGHT_M at the box's foot point; None without players in front of the camera."""
    ratios = []
    for d in players:
        if d["score"] < SCORE_MIN:
            continue
        x0, _, x1, y1 = d["bbox"]
        g = _ground(P, ((x0 + x1) / 2, y1))
        if g is None:
            continue
        foot = P @ np.array([g[0], g[1], 0.0, 1.0])
        head = P @ np.array([g[0], g[1], PLAYER_HEIGHT_M, 1.0])
        if foot[2] <= 0 or head[2] <= 0:
            continue
        px = abs(foot[1] / foot[2] - head[1] / head[2])
        if px > 0:
            ratios.append((y1 - d["bbox"][1]) / px)
    return float(np.median(ratios)) if ratios else None


def principal_ground(P: np.ndarray) -> tuple[float, float] | None:
    """Where the camera's principal point (the image centre) meets the ground: x0 = M m3, M the
    camera matrix's left 3x3 and m3 its third row (Hartley and Zisserman), then back to z = 0."""
    x0 = P[:, :3] @ P[2, :3]
    return _ground(P, (x0[0] / x0[2], x0[1] / x0[2])) if x0[2] != 0 else None


def agree(rows: list[dict]) -> list[dict]:
    """Keep trusted only the frames the heights trusted whose image centre lands within NEIGHBOUR_M of
    where the nearest other height-trusted frame's does, within NEIGHBOUR_FRAMES (the earlier on a
    tie); a frame with no such neighbour is not trusted. Untrusted frames lose their positions."""
    centre = {}
    for r in rows:
        cam = r["camera"]
        if cam.get("heights_ok") and cam.get("P") is not None:
            centre[r["frame"]] = principal_ground(np.array(cam["P"]))
    for r in rows:
        f, c = r["frame"], centre.get(r["frame"])
        near = sorted((abs(g - f), g) for g in centre if g != f and abs(g - f) <= NEIGHBOUR_FRAMES)
        other = centre[near[0][1]] if near else None
        r["camera"]["ok"] = bool(c is not None and other is not None
                                 and math.dist(c, other) <= NEIGHBOUR_M)
        if not r["camera"]["ok"]:
            for d in r["players"] + r["ball"]:
                d["x"], d["y"] = None, None
    return rows


def place(row: dict) -> dict:
    """Judge the frame's camera by its players' heights and, when it is trusted, place every
    detection on the pitch through it (players at the foot point, the ball one radius up)."""
    cam = row["camera"]
    P = np.array(cam["P"]) if cam.get("P") is not None else None
    ratio = height_ratio(row["players"], P) if P is not None else None
    cam["markings_ok"] = cam.get("markings_ok", cam["ok"])
    # With no player to measure, the heights cannot judge the camera, and the markings' verdict
    # stands (one frame of 3,250 on validation, untrusted either way).
    if ratio is not None:
        ok = HEIGHT_BAND[0] <= ratio <= HEIGHT_BAND[1]
    else:
        ok = bool(P is not None and cam["markings_ok"])
    cam["height_ratio"] = None if ratio is None else round(ratio, 4)
    cam["heights_ok"] = ok
    cam["ok"] = ok  # until `agree` judges the frame against its neighbours
    for d in row["players"]:
        x0, _, x1, y1 = d["bbox"]
        xy = _ground(P, ((x0 + x1) / 2, y1)) if ok else None
        d["x"], d["y"] = (_r(xy[0]), _r(xy[1])) if xy else (None, None)
    for b in row["ball"]:
        x0, y0, x1, y1 = b["bbox"]
        xy = _ground(P, ((x0 + x1) / 2, (y0 + y1) / 2), BALL_CENTRE_Z) if ok else None
        b["x"], b["y"] = (_r(xy[0]), _r(xy[1])) if xy else (None, None)
    return row


def observe(images: list[Path], dets: list, load) -> list[dict]:
    """`load(path) -> (H, W, 3) uint8` reads an image; passed in so tests need no image files."""
    if len(images) != len(dets):
        raise ValueError(f"{len(images)} images but {len(dets)} detection lines: they pair one to one")
    # One pass over the images keeps only what the second needs (the markings' points and each
    # player's kit colour), never the frames: a clip's decoded frames do not fit in memory (2.8 MB
    # each at 1280 x 720, so 4 GB a minute at 25 fps).
    kits, points, size = [], [], None
    for img, fd in zip(images, dets, strict=True):
        rgb = load(img)
        size = size or rgb.shape[:2]
        boxes = [d.bbox for d in fd.detections if d.score >= SCORE_MIN]
        points.append(pitch.line_points(rgb, boxes))
        kits.append([kit_rgb(rgb, d.bbox) if d.cls == "player" and d.score >= SCORE_MIN else None
                     for d in fd.detections])
    H, W = size
    gantry, fits = pitch.fit_clip(points, W, H)
    rows = []
    for kit, fd, fit in zip(kits, dets, fits, strict=True):
        players, balls = [], []
        for d, colour in zip(fd.detections, kit, strict=True):
            if d.cls == "player":
                players.append({"bbox": list(d.bbox), "score": d.score, "x": None, "y": None,
                                "rgb": colour})
            else:
                balls.append({"bbox": list(d.bbox), "score": d.score, "x": None, "y": None})
        rows.append(place({
            "frame": fd.frame, "t": fd.t,
            "camera": {"ok": fit.ok, "median_px": fit.median_px, "points": fit.points,
                       "P": ([[round(float(v), 6) for v in row] for row in fit.view.P()]
                             if fit.view else None)},
            "players": players, "ball": balls,
        }))
    rows = agree(rows)
    rows[0]["gantry"] = [round(v, 3) for v in gantry]
    return rows


def _r(v) -> float | None:
    return None if v is None or not np.isfinite(v) else round(float(v), 3)


def main(argv: list[str] | None = None) -> None:
    from PIL import Image

    ap = argparse.ArgumentParser(description="Place a clip's detections on the pitch from its images.")
    ap.add_argument("clip", type=Path, nargs="?", help="the clip's folder (images/)")
    ap.add_argument("--detections", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--regate", type=Path, default=None,
                    help="an observations file to judge again with today's trust test and placing, "
                         "without the camera fit (its cameras are kept)")
    a = ap.parse_args(argv)
    if a.regate is not None:
        rows = []
        for x in a.regate.read_text().splitlines():
            if x.strip():
                rows.append(place(json.loads(x)))
        rows = agree(rows)
    else:
        if a.clip is None or a.detections is None:
            ap.error("a clip and --detections, or --regate")
        images = sorted((a.clip / "images").glob("*.jpg"))
        dets = read_detections(a.detections)
        rows = observe(images, dets, lambda p: np.asarray(Image.open(p).convert("RGB")))
    with open(a.out, "w", encoding="utf-8", newline="\n") as f:
        for r in rows:
            f.write(json.dumps(r, separators=(",", ":")) + "\n")
    ok = sum(r["camera"]["ok"] for r in rows)
    print(json.dumps({"out": str(a.out), "frames": len(rows), "camera_ok": ok,
                      "gantry": rows[0].get("gantry")}))


if __name__ == "__main__":
    main()
