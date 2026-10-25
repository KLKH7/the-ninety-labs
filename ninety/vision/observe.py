"""The image stage of event detection: images + detections -> observations on the pitch.

    uv run --group vision python -m ninety.vision.observe <clip> \\
        --detections <detections.jsonl> --out <observations.jsonl> [--fixed]

Reads the clip's `images/` and the detections file (ninety/vision/detections.py), nothing else: not
frames.jsonl, events.jsonl, clip.json or meta.json, which hold the answer key and the render
settings. Images are paired with detection lines in order (both are one per frame, in frame order;
the counts must agree). For each frame it writes one line:

    {"frame", "t",
     "camera": {"ok", "median_px", "points", "P"},       # estimated from the markings (pitch.py)
     "players": [{"bbox", "score", "x", "y", "rgb"}],     # foot point on the pitch, kit colour
     "ball": [{"bbox", "score", "x", "y"}]}               # centre, on the ground

The broadcast camera pans and zooms, so its camera is fitted frame by frame (pitch.fit_clip). It
also cuts between cameras. With `--cuts`, a cut is found where the picture changes at once
(pitch.shot_starts) and each shot is fitted on its own (pitch.fit_shots), its index written as
`camera.shot`. It is off by default: on validation it trusted a tight lens's frames 1 to 1.3 m
wrong, and on the test set a reverse angle 44 m wrong, the mirror of the main camera through the
centre spot, which the markings cannot tell apart (docs/eval/camera-cuts-plan.md, lesson 244). A
lens of the tactical camera (`--fixed`) never moves: its camera is fitted once, from the marking
pixels that stay put across the clip's frames (pitch.fit_fixed), and every frame is placed
through that one camera.

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
# (docs/eval/detector-plan.md, step B). Re-derived by that rule for the current renders (lesson 230),
# on the clips docs/eval/ball-three-cams/PLAN.md fixed for it: tactical1's 23 validation clips
# (renderer 0.5.15, the test clips' look), broadcast, the camera fit with the grain blur (lesson
# 215), 4,563 good frames of 5,500 (docs/eval/band-broadcast.json, ninety/eval/band_derive.py; the
# same rule on dataset v2's validation clips, renderer 0.5.9, gives 0.987 to 1.099,
# docs/eval/band-broadcast-v2.json). The band of renderer 0.3 (0.901 to 1.002,
# docs/eval/detector-derive.json) rejected every right camera there: the ratio on right cameras sits
# about 5 to 8% higher now (cause not established). It replaced the marking test
# (half the marking pixels within 1.5 px), which trusted 198 badly wrong frames on validation and
# kept 89% of the good ones, where this keeps 98%. The marking fit's own verdict is kept as
# `markings_ok` and guides the fit from frame to frame (pitch.fit_clip). On the broadcast it is
# required again as well as the heights (gate B3; lesson 230), chosen on validation before any test
# score: on tactical1's 23 validation clips the heights alone trusted 654 badly wrong frames, the
# worst 51.7 m (one clip's camera 28 m wrong in every frame, which no frame-to-frame check sees),
# and both together 360, the worst 14.1 m, keeping 97.8% of good frames against 98.1%
# (docs/eval/band-broadcast.json, `candidates`). A fixed lens is judged by its heights only: its
# markings test was measured only before the grain fix (lesson 215), where it failed most good frames.
# A frame the heights trust must also agree with its neighbours (`agree`): a broadcast camera pans
# continuously, under 0.02 rad a frame (pitch.STEP_SD), so the ground point at the image centre
# moves little from frame to frame. A frame is kept only if that point lies within NEIGHBOUR_M of
# the nearest other height-trusted frame's within NEIGHBOUR_FRAMES (design, set before measuring;
# docs/eval/camera-bound-plan.md). On validation that cut the worst trusted frame from 55 m wrong
# to 8.2 m (observed, under the plan's 8.5 m) and kept every good frame the heights kept. It sees an
# isolated wrong frame only: frames wrong the same way agree and pass together. A tie between two
# neighbours goes to the earlier (fixed with the plan's values, not tuned).
# A neighbour is looked for within the frame's own shot (`camera.shot`, pitch.shot_starts): the
# premise is a camera that pans continuously, and across a cut it is another camera
# (docs/eval/camera-cuts-plan.md). Without a cut every frame is in shot 0, as before.
# Known limit (lesson 159): frames whose wrong cameras agree with each other still pass, since no
# check of one frame against another can see them: a whole clip offset the same way (validation
# seed 108, about 2 to 8 m), and a run of 4 frames on test clip 900003, about 46 m wrong.
NEIGHBOUR_FRAMES = 5
NEIGHBOUR_M = 2.0
PLAYER_HEIGHT_M = 1.80
HEIGHT_BAND = (0.966, 1.121)
# The same test for a fixed lens (the tactical camera): its own band, from its own frames, because
# the ratio depends on the camera's height and distance and on how players are drawn. Measured by
# the same rule (step B: the 1st to 99th percentile on frames whose ground mapping is within 1.0 m)
# on tactical1's 23 validation clips, both lenses, renderer 0.5.15, ours-freeze tiled: 11,250 good
# frames of 11,500 (docs/eval/ball-three-cams/band-fixed.json, session D; reproduced exactly in
# docs/eval/band-broadcast.json). It keeps 98% of them; of the 250 bad frames (one lens of seed
# 2042 fitted 69 m wrong) it trusts one, which `agree` then has no trusted neighbour for.
FIXED_HEIGHT_BAND = (1.002, 1.151)


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
    tie) in the same shot; a frame with no such neighbour is not trusted. Untrusted frames lose
    their positions."""
    centre, shot = {}, {}
    for r in rows:
        cam = r["camera"]
        shot[r["frame"]] = cam.get("shot", 0)
        if cam.get("heights_ok") and cam.get("P") is not None:
            centre[r["frame"]] = principal_ground(np.array(cam["P"]))
    for r in rows:
        f, c = r["frame"], centre.get(r["frame"])
        near = sorted((abs(g - f), g) for g in centre
                      if g != f and abs(g - f) <= NEIGHBOUR_FRAMES and shot[g] == shot[f])
        other = centre[near[0][1]] if near else None
        r["camera"]["ok"] = bool(c is not None and other is not None
                                 and math.dist(c, other) <= NEIGHBOUR_M)
        if not r["camera"]["ok"]:
            for d in r["players"] + r["ball"]:
                d["x"], d["y"] = None, None
    return rows


def place(row: dict, band: tuple[float, float] = HEIGHT_BAND, markings: bool = True) -> dict:
    """Judge the frame's camera by its players' heights (their median ratio inside `band`) and,
    with `markings` (the broadcast), its marking fit's own verdict too; when it is trusted, place
    every detection on the pitch through it (players at the foot point, the ball one radius up)."""
    cam = row["camera"]
    P = np.array(cam["P"]) if cam.get("P") is not None else None
    ratio = height_ratio(row["players"], P) if P is not None else None
    cam["markings_ok"] = cam.get("markings_ok", cam["ok"])
    # With no player to measure, the heights cannot judge the camera, and the markings' verdict
    # stands (one frame of 3,250 on validation, untrusted either way).
    if ratio is not None:
        ok = band[0] <= ratio <= band[1] and (cam["markings_ok"] or not markings)
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


def observe(images: list[Path], dets: list, load, fixed: bool = False, cuts: bool = False) -> list[dict]:
    """`load(path) -> (H, W, 3) uint8` reads an image; passed in so tests need no image files.
    `fixed` for a lens that never moves (the tactical camera), else the broadcast camera; `cuts`
    to fit the broadcast shot by shot at the cuts the images show (off by default, above)."""
    if len(images) != len(dets):
        raise ValueError(f"{len(images)} images but {len(dets)} detection lines: they pair one to one")
    rgbs, points, thumbs = [], [], []
    counts = None
    for img, fd in zip(images, dets, strict=True):
        rgb = load(img)
        boxes = [d.bbox for d in fd.detections if d.score >= SCORE_MIN]
        rgbs.append(rgb)
        if not fixed:
            points.append(pitch.line_points(rgb, boxes))
            if cuts:
                thumbs.append(pitch.thumbnail(rgb))
            continue
        mask = pitch.line_mask(rgb, boxes)
        counts = mask.astype(np.uint32) if counts is None else counts + mask
        points.append(pitch.mask_points(mask))
    H, W = rgbs[0].shape[:2]
    if not fixed:
        starts = pitch.shot_starts(thumbs) if cuts else [0]
        gantries, fits = pitch.fit_shots(points, W, H, starts)
    else:
        view, fits = pitch.fit_fixed(pitch.static_points(counts, len(points)), points, W, H)
        starts, gantries = [0], [(view.cx, view.cy, view.cz)]
    shot_of = np.searchsorted(starts, np.arange(len(fits)), side="right") - 1
    rows = []
    for k, (rgb, fd, fit) in enumerate(zip(rgbs, dets, fits, strict=True)):
        players, balls = [], []
        for d in fd.detections:
            if d.cls == "player":
                players.append({"bbox": list(d.bbox), "score": d.score, "x": None, "y": None,
                                "rgb": kit_rgb(rgb, d.bbox) if d.score >= SCORE_MIN else None})
            else:
                balls.append({"bbox": list(d.bbox), "score": d.score, "x": None, "y": None})
        rows.append(place({
            "frame": fd.frame, "t": fd.t,
            "camera": {"ok": fit.ok, "median_px": fit.median_px, "points": fit.points,
                       "shot": int(shot_of[k]),
                       "P": ([[round(float(v), 6) for v in row] for row in fit.view.P()]
                             if fit.view else None)},
            "players": players, "ball": balls,
        }, FIXED_HEIGHT_BAND if fixed else HEIGHT_BAND, markings=not fixed))
    rows = agree(rows)
    rows[0]["gantry"] = None if gantries[0] is None else [round(v, 3) for v in gantries[0]]
    if len(starts) > 1:
        rows[0]["shots"] = [{"frame": rows[s]["frame"],
                             "gantry": None if g is None else [round(v, 3) for v in g]}
                            for s, g in zip(starts, gantries, strict=True)]
    if fixed:
        rows[0]["fixed"] = True
    return rows


def _r(v) -> float | None:
    return None if v is None or not np.isfinite(v) else round(float(v), 3)


def main(argv: list[str] | None = None) -> None:
    from PIL import Image

    ap = argparse.ArgumentParser(description="Place a clip's detections on the pitch from its images.")
    ap.add_argument("clip", type=Path, nargs="?", help="the clip's folder (images/)")
    ap.add_argument("--detections", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--fixed", action="store_true",
                    help="a fixed lens (the tactical camera): one camera for the whole clip")
    ap.add_argument("--cuts", action="store_true",
                    help="the broadcast: fit each shot on its own at the cuts the images show "
                         "(off by default)")
    ap.add_argument("--regate", type=Path, default=None,
                    help="an observations file to judge again with today's trust test and placing, "
                         "without the camera fit (its cameras are kept)")
    a = ap.parse_args(argv)
    if a.regate is not None:
        rows = []
        lines = [json.loads(x) for x in a.regate.read_text().splitlines() if x.strip()]
        fixed = bool(lines and lines[0].get("fixed"))
        band = FIXED_HEIGHT_BAND if fixed else HEIGHT_BAND
        for x in lines:
            rows.append(place(x, band, markings=not fixed))
        rows = agree(rows)
    else:
        if a.clip is None or a.detections is None:
            ap.error("a clip and --detections, or --regate")
        images = sorted((a.clip / "images").glob("*.jpg"))
        dets = read_detections(a.detections)
        rows = observe(images, dets, lambda p: np.asarray(Image.open(p).convert("RGB")),
                       fixed=a.fixed, cuts=a.cuts)
    with open(a.out, "w", encoding="utf-8", newline="\n") as f:
        for r in rows:
            f.write(json.dumps(r, separators=(",", ":")) + "\n")
    ok = sum(r["camera"]["ok"] for r in rows)
    print(json.dumps({"out": str(a.out), "frames": len(rows), "camera_ok": ok,
                      "gantry": rows[0].get("gantry"), "shots": len(rows[0].get("shots", [0]))}))


if __name__ == "__main__":
    main()
