"""How well the fixed-camera fit (ninety/vision/pitch.py, `fit_fixed`) places the pitch, on scenes
drawn here through the renderer's camera model, before the tactical renders exist.

    uv run python -m ninety.eval.tactical_fit --cameras 20 --out docs/eval/tactical-fit.json

Each scene is one lens of the tactical rig, drawn from the rig's ranges (TACTICAL_*): a
ninety/render/camera.py `Camera` looks at its half of the pitch. Frames are drawn pixel by pixel
from that camera: mown grass, the Law 1 markings 12 cm wide (anti-aliased), players standing on
them and hiding them (one team in white, the hardest kit for the line detector), image noise and
JPEG. The live path's own steps then run on the pixels alone: the line detector with the players'
boxes (some missed, as a detector misses), the static vote, `fit_fixed`. The fit never sees the
camera; this module grades it against the camera afterwards.

The error is measured on a 1 m grid of ground points the lens shows on its half of the pitch:
where the true camera draws the point, taken back to the ground through the fitted one. Zones are
the lens's own: near (y < 17 m), centre, far (y >= 51 m), and the near and far corners (the 15 m
next to the goal line in the near and far bands). The pass bar is in
docs/eval/tactical-fit-plan.md, set before any fit was run.
"""

from __future__ import annotations

import argparse
import io
import json
import math
from pathlib import Path

import numpy as np

from ninety.render.camera import Camera
from ninety.sim import fmath
from ninety.vision import pitch

W, H = 1920, 1080
# The rig (the Coordinator's tactical-camera plan): lenses near (52.5, -32, 28) m, 24 to 32 m up,
# 28 to 38 m back, within 3 m of halfway, about 60 degrees across, tilted about 0.52 rad down and
# panned about 0.47 rad to their half. Pan, tilt and lens are drawn around those (design).
TACTICAL_X = (49.5, 55.5)
TACTICAL_BACK = (28.0, 38.0)
TACTICAL_HEIGHT = (24.0, 32.0)
TACTICAL_HFOV_DEG = (55.0, 65.0)
TACTICAL_TILT = (0.46, 0.58)
TACTICAL_PAN = (0.40, 0.54)

LINE_HALF_M = 0.06  # Law 1: lines no wider than 12 cm, and the renderer draws them 12 cm
SUPERSAMPLE = 2  # 2 x 2 rays per pixel: a far line under a pixel wide is drawn by its coverage
GRASS = ((52, 118, 30), (62, 134, 38))  # two mowing shades
STRIPE_M = 5.25  # 20 stripes across the length
PAINT = (236, 238, 232)
KITS = ((238, 238, 238), (196, 34, 44), (20, 20, 24))  # white, red, the referee's black
PLAYER_H_M, PLAYER_W_M = 1.80, 0.5
NOISE_SD = 3.0
JPEG_QUALITY = 85
MISSED = 0.1  # share of players the detector misses, so their kit can reach the line detector
FRAMES = 12
STEP_M = 3.0  # how far a player moves between the sampled frames (about half a second apart)
NEAR_Y, FAR_Y, CORNER_M = 17.0, 51.0, 15.0
ZONES = ("near", "centre", "far", "near_corner", "far_corner")
SIDES = ("left", "right")


def camera(side: str, x: float, back: float, height: float, hfov_deg: float, tilt: float,
           pan: float) -> Camera:
    """The renderer's camera for one lens: at (x, -back, height), aimed `pan` toward its half and
    `tilt` below the horizon, `hfov_deg` across a W x H picture."""
    s = 1.0 if side == "right" else -1.0
    fwd = (s * fmath.sin(pan) * fmath.cos(tilt), fmath.cos(pan) * fmath.cos(tilt), -fmath.sin(tilt))
    pos = (x, -back, height)
    half = math.radians(hfov_deg) / 2
    fov_v = 2 * math.degrees(fmath.atan2(fmath.sin(half) * H, fmath.cos(half) * W))
    return Camera(pos, tuple(p + 10 * f for p, f in zip(pos, fwd, strict=True)), fov_v, W, H)


def sample_cameras(n: int, seed: int) -> list[tuple[str, Camera]]:
    rng = np.random.default_rng(seed)
    out = []
    for k in range(n):
        side = SIDES[k % 2]
        args = [rng.uniform(*r) for r in (TACTICAL_X, TACTICAL_BACK, TACTICAL_HEIGHT, TACTICAL_HFOV_DEG,
                                           TACTICAL_TILT, TACTICAL_PAN)]
        out.append((side, camera(side, *args)))
    return out


def _rays(cam: Camera, u: np.ndarray, v: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Where the rays through pixel coordinates (u, v) meet the ground; NaN above the horizon."""
    R = np.array(cam.R)
    f = cam.focal_px
    d = np.stack([(u - W / 2) / f, (v - H / 2) / f, np.ones_like(u)], -1) @ R
    s = -cam.position[2] / d[..., 2]
    s = np.where(s > 0, s, np.nan)
    return cam.position[0] + s * d[..., 0], cam.position[1] + s * d[..., 1]


def _segment_dist(x, y, a, b):
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    t = np.clip(((x - ax) * dx + (y - ay) * dy) / (dx * dx + dy * dy), 0.0, 1.0)
    return np.hypot(x - ax - t * dx, y - ay - t * dy)


def marking_distance(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Metres from each ground point to the nearest Law 1 marking: the straight lines exactly and
    the circles and arcs as circles, each over its own angle."""
    d = np.full(x.shape, np.inf, dtype=np.float64)
    for pl in pitch.pitch_polylines():
        if len(pl) > 5:  # an arc: drawn as its circle below
            continue
        for a, b in zip(pl[:-1], pl[1:], strict=True):
            d = np.minimum(d, _segment_dist(x, y, a, b))
    d = np.minimum(d, np.abs(np.hypot(x - 52.5, y - 34) - pitch.CIRCLE_R))
    for mx, outside in ((11.0, x > 16.5), (94.0, x < 88.5)):  # the penalty arcs, outside the area
        d = np.where(outside, np.minimum(d, np.abs(np.hypot(x - mx, y - 34) - pitch.CIRCLE_R)), d)
    for cx, cy in ((0, 0), (105, 0), (105, 68), (0, 68)):  # corner arcs, inside the pitch
        inside = ((x - cx) * (1 if cx == 0 else -1) >= 0) & ((y - cy) * (1 if cy == 0 else -1) >= 0)
        d = np.where(inside, np.minimum(d, np.abs(np.hypot(x - cx, y - cy) - 1.0)), d)
    return d


def background(cam: Camera) -> np.ndarray:
    """(H, W, 3) float: grass with mowing stripes and the markings, anti-aliased by coverage;
    above the pitch's surroundings a flat grey stand."""
    paint = np.zeros((H, W))
    stripe = np.zeros((H, W))
    ground = np.zeros((H, W))
    vv, uu = np.mgrid[0:H, 0:W].astype(np.float64)
    n = SUPERSAMPLE
    for i in range(n):
        for j in range(n):
            gx, gy = _rays(cam, uu + (i + 0.5) / n, vv + (j + 0.5) / n)
            ok = np.isfinite(gx) & (gx > -8) & (gx < 113) & (gy > -6) & (gy < 74)
            gx, gy = np.where(ok, gx, -100.0), np.where(ok, gy, -100.0)
            on = ok & (gx > -2) & (gx < 107) & (gy > -2) & (gy < 70)
            paint += np.where(on, marking_distance(gx, gy) <= LINE_HALF_M, False)
            stripe += np.where(ok, (np.floor(gx / STRIPE_M) % 2), 0.0)
            ground += ok
    paint, stripe, ground = paint / (n * n), stripe / (n * n), ground / (n * n)
    g0, g1 = np.array(GRASS[0], float), np.array(GRASS[1], float)
    grass = g0 + (g1 - g0) * (stripe / np.maximum(ground, 1e-9))[..., None]
    img = grass * (1 - paint[..., None]) + np.array(PAINT, float) * paint[..., None]
    stand = np.array((90.0, 90.0, 96.0))
    return img * ground[..., None] + stand * (1 - ground[..., None])


def players(side: str, rng: np.random.Generator) -> np.ndarray:
    """(23, 3) x, y, kit: 11 a side and the referee, most of them in the lens's half."""
    xs = rng.uniform(30, 105, 23) if side == "right" else rng.uniform(0, 75, 23)
    return np.stack([xs, rng.uniform(2, 66, 23), np.array([0] * 11 + [1] * 11 + [2])], 1)


def draw(base: np.ndarray, cam: Camera, people: np.ndarray, rng: np.random.Generator):
    """One frame (uint8, through JPEG) and the boxes a detector reports (some players missed)."""
    img = base.copy()
    P = np.array(cam.P)
    boxes = []
    order = np.argsort(-np.array([cam.depth((x, y, 0.0)) for x, y, _ in people]))
    for k in order:  # far to near, so a near player hides a far one
        x, y, kit = people[k]
        if cam.depth((x, y, 0.0)) <= 0:
            continue
        foot = P @ [x, y, 0.0, 1.0]
        head = P @ [x, y, PLAYER_H_M, 1.0]
        side = P @ [x + PLAYER_W_M, y, 0.0, 1.0]
        u, vf, vh = foot[0] / foot[2], foot[1] / foot[2], head[1] / head[2]
        hw = max(abs(side[0] / side[2] - u) / 2, 1.0)
        x0, x1, y0, y1 = u - hw, u + hw, vh, vf
        if x1 < 0 or x0 >= W or y1 < 0 or y0 >= H:
            continue
        xa, xb = max(int(round(x0)), 0), min(int(round(x1)) + 1, W)
        ya, yb = max(int(round(y0)), 0), min(int(round(y1)) + 1, H)
        img[ya:yb, xa:xb] = KITS[int(kit)]
        img[max(yb - 2, 0):yb, xa:xb] = (30, 30, 30)  # boots
        if rng.random() >= MISSED:
            boxes.append([x0 + rng.normal(0, 1), y0 + rng.normal(0, 1), x1 + rng.normal(0, 1),
                          y1 + rng.normal(0, 1)])
    img = img + rng.normal(0, NOISE_SD, img.shape)
    return _jpeg(np.clip(img, 0, 255).astype(np.uint8)), boxes


def _jpeg(img: np.ndarray) -> np.ndarray:
    from PIL import Image

    buf = io.BytesIO()
    Image.fromarray(img).save(buf, format="JPEG", quality=JPEG_QUALITY)
    return np.asarray(Image.open(io.BytesIO(buf.getvalue())).convert("RGB"))


def clip(side: str, cam: Camera, seed: int, frames: int = FRAMES) -> tuple[np.ndarray, list[np.ndarray]]:
    """The live path's inputs for one scene: the static marking pixels and each frame's own."""
    rng = np.random.default_rng(seed)
    base = background(cam)
    people = players(side, rng)
    counts = np.zeros((H, W), dtype=np.uint16)
    points = []
    for _ in range(frames):
        img, boxes = draw(base, cam, people, rng)
        mask = pitch.line_mask(img, boxes)
        counts += mask
        points.append(pitch.mask_points(mask))
        people[:, :2] += rng.normal(0, STEP_M / math.sqrt(2), (len(people), 2))
    return pitch.static_points(counts, frames), points


def ground_grid(side: str, cam: Camera) -> tuple[np.ndarray, np.ndarray]:
    """(N, 2) ground points every 1 m on the lens's half that it shows, and (N,) their zone."""
    xs = np.arange(52.5, 105.01, 1.0) if side == "right" else np.arange(0.0, 52.51, 1.0)
    pts = np.array([(x, y) for x in xs for y in np.arange(0.0, 68.01, 1.0)])
    keep = []
    for x, y in pts:
        uv = cam.project((x, y, 0.0))
        keep.append(uv is not None and 0 <= uv[0] < W and 0 <= uv[1] < H)
    pts = pts[np.array(keep)]
    end = np.abs(pts[:, 0] - 52.5) >= 52.5 - CORNER_M
    zone = np.where(pts[:, 1] < NEAR_Y, "near", np.where(pts[:, 1] >= FAR_Y, "far", "centre"))
    zone = np.where(end & (pts[:, 1] < NEAR_Y), "near_corner", zone)
    zone = np.where(end & (pts[:, 1] >= FAR_Y), "far_corner", zone)
    return pts, zone


def footprint(cam: Camera, pts: np.ndarray, h: float = 0.01) -> np.ndarray:
    """(N,) metres of ground per pixel at each point, the worst direction: 1 over the smallest
    singular value of the ground-to-pixel Jacobian. Geometry of the true camera only."""
    out = []
    for x, y in pts:
        p0 = np.array(cam.project((x, y, 0.0)))
        J = np.stack([np.array(cam.project((x + h, y, 0.0))) - p0,
                      np.array(cam.project((x, y + h, 0.0))) - p0], 1) / h
        out.append(1.0 / np.linalg.svd(J, compute_uv=False).min())
    return np.array(out)


def errors(cam: Camera, fitted: pitch.View, pts: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """(N,) metres and (N,) pixels between the truth and the fit at each ground point."""
    uv = np.array([cam.project((x, y, 0.0)) for x, y in pts])
    metres = np.linalg.norm(fitted.to_ground(uv) - pts, axis=1)
    back, _ = fitted.project(np.c_[pts, np.zeros(len(pts))])
    return metres, np.linalg.norm(back - uv, axis=1)


def _stats(a: np.ndarray) -> dict:
    return {"n": int(len(a)), "median": round(float(np.median(a)), 4),
            "p95": round(float(np.percentile(a, 95)), 4), "max": round(float(a.max()), 4)}


def measure(n: int, seed: int, fit: bool = True) -> dict:
    """Every scene's zones: footprint (geometry, known before any fit) and, with `fit`, the fit's
    ground and pixel error."""
    by_zone = {z: {"footprint": [], "metres": [], "pixels": []} for z in ZONES}
    scenes = []
    for k, (side, cam) in enumerate(sample_cameras(n, seed)):
        pts, zone = ground_grid(side, cam)
        fp = footprint(cam, pts)
        row = {"side": side, "position": [round(v, 3) for v in cam.position],
               "fov_v_deg": round(cam.fov_v_deg, 3)}
        if fit:
            static, points = clip(side, cam, seed * 1000 + k)
            view, fits = pitch.fit_fixed(static, points, W, H)
            m, px = errors(cam, view, pts)
            row.update({"static_points": int(len(static)), "frames_ok": sum(f.ok for f in fits),
                        "median_px": round(pitch._median(view, static), 3),
                        "fitted_position": [round(v, 3) for v in view.vector()[:3]],
                        "position_error_m": round(math.dist(view.vector()[:3], cam.position), 3),
                        "max_m": round(float(m.max()), 4), "p95_px": round(float(np.percentile(px, 95)), 4)})
        for z in ZONES:
            sel = zone == z
            by_zone[z]["footprint"].append(fp[sel])
            if fit:
                by_zone[z]["metres"].append(m[sel])
                by_zone[z]["pixels"].append(px[sel])
        scenes.append(row)
        print(json.dumps(row), flush=True)
    zones = {}
    for z, d in by_zone.items():
        zones[z] = {"footprint_m_per_px": _stats(np.concatenate(d["footprint"]))}
        if fit:
            zones[z]["error_m"] = _stats(np.concatenate(d["metres"]))
            zones[z]["error_px"] = _stats(np.concatenate(d["pixels"]))
    return {"cameras": n, "seed": seed, "frames": FRAMES, "zones": zones, "scenes": scenes}


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--cameras", type=int, default=20)
    ap.add_argument("--seed", type=int, default=193)
    ap.add_argument("--geometry-only", action="store_true", help="footprints only, no fit (for the plan)")
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args(argv)
    result = measure(a.cameras, a.seed, fit=not a.geometry_only)
    a.out.write_text(json.dumps(result, indent=1) + "\n")
    print(json.dumps(result["zones"], indent=1))


if __name__ == "__main__":
    main()
