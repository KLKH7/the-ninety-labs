"""Two views of one moment -> one observation per frame: the fixed tactical camera's lenses, merged
on the pitch.

    uv run python -m ninety.vision.fuse --view tac-l=<observations.jsonl> \\
        --view tac-r=<observations.jsonl> --out <observations.jsonl>

The tactical camera is two fixed lenses, each covering half the pitch, sharing about 5 m around
halfway. A player or the ball in that band is seen by both, so each view's observations
(ninety.vision.observe, one line per frame) hold it once each; the events stage must see it once.

For each frame, each pair of detections of one class from different views is a candidate when
their pitch positions agree within what the two measurements can miss by (`same_place`):

- each detection's ground point is wrong in the image by up to `PRECISION` of its box (the 99th
  percentile of the detector's error against the renderer's foot points, across and down, measured
  on 24 validation clips with the demo detector: docs/eval/fuse-gate.md), plus the camera fit's own
  residual on that frame (`camera.median_px`), plus LABEL_PX (the labels it was measured against
  are whole pixels);
- that pixel ellipse is carried to the pitch through the view's own camera (the ground mapping's
  Jacobian at that point), so a far player, whose pixel spans metres of pitch in depth, has a long
  ellipse, and a near one a small round one;
- the two are the same object when their difference lies inside the sum of the two ellipses
  (d' (Sa + Sb)^-1 d <= 1). With normal errors at the 99th percentile per axis this keeps about
  96% of true pairs (chi-square, 2 degrees of freedom, at 2.576^2 = 6.63).

On the tactical renders the detector's ground point is also off in a set direction: a standing body
leans away from the image centre in perspective, so the box's bottom centre sits outward of the
feet, more the nearer the edge. In the shared band each lens sees the player near its own edge, in
opposite directions, so one player's two places lie about 0.3 m apart and the pair stayed split.
With `USE_LENS_BIAS`, for a named lens (`BIAS`), each ground pixel is first moved back by its
measured bias (a line in the pixel's column, as a share of its box) and placed again through the
view's camera, and the gate uses the precision left after that (`VIEW_PRECISION`):
docs/eval/fuse-gate.md, the tactical re-measurement, on 15 validation clips. Scored once on 8
others, it failed its pre-registered rule (side accuracy), so it is off: every view keeps
`PRECISION` and its pixel as drawn.

Candidates are taken one to one, closest first (in that measure), so a detection is merged at most
once, and two detections from one view are never merged: the detector already told them apart.
A merged detection takes the place both ellipses agree on most (each weighted by the inverse of
its ellipse), the higher score, and the box, colour and view of the higher-scoring one; `views`
lists both. Each fused line keeps observe's shape, so tracking and events read it unchanged; its
camera is ok when any view's is, with each view's verdict under `camera.views`.

Reads only the views' observations: this is the live path. Pure numpy, so CI runs it.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from ninety.vision.observe import BALL_CENTRE_Z
from ninety.vision.track import SCORE_MIN

# The 99th percentile of |detected - true| ground point, across and down, as a share of the
# label's height (players) or width (ball): ninety.eval.foot_precision on the 24 validation clips
# of dataset v2 at the look freeze, ours-freeze, score 0.5 (docs/eval/fuse-gate/foot-precision.json:
# 13,641 players, 1,073 balls). Measured on the broadcast camera, where players are 30 to 120 px
# tall; re-measured on the tactical renders by the same command once they exist.
PRECISION = {"player": (0.1549, 0.0821), "ball": (0.4028, 0.2559)}
# The labels the precision was measured against are whole pixels (frames.jsonl's bbox), so no
# measurement here is finer than a pixel: added in quadrature, it dominates only the smallest boxes.
LABEL_PX = 1.0

# Per tactical lens and class, the detector's signed ground-pixel error as a share of the box (height
# for players, width for the ball), fitted as a + b*c across and down, c the pixel's column from the
# image centre as a share of half the width; and the 99th percentile of what that line leaves.
# ninety.eval.foot_precision --view on the 15 derive clips of dataset tactical's validation set,
# ours-tactical, score 0.5 (docs/eval/fuse-gate/foot-precision-tac-{l,r}.json: 9,024 and 10,295
# players, 268 and 445 balls). The form was fixed before measuring (docs/eval/fuse-gate.md).
BIAS = {
    "tac-l": {"player": ((0.026, 0.0621), (0.051, -0.0281)), "ball": ((0.0267, 0.0153), (-0.0249, 0.0559))},
    "tac-r": {"player": ((-0.015, 0.0795), (0.0392, 0.0139)), "ball": ((0.0112, 0.0089), (-0.0267, -0.0419))},
}
VIEW_PRECISION = {
    "tac-l": {"player": (0.1723, 0.13), "ball": (0.3551, 0.2678)},
    "tac-r": {"player": (0.1819, 0.1287), "ball": (0.345, 0.229)},
}
# Off: the correction failed its pre-registered adoption rule on validation (docs/eval/fuse-gate.md).
USE_LENS_BIAS = False
# The tactical lens's picture width in pixels: the renderer's TACTICAL_SIZE (ninety/render/camera.py;
# the live path may not import the renderer, so a test holds the two equal).
VIEW_WIDTH_PX = 1920


def _ground(P: np.ndarray, uv, z: float) -> np.ndarray | None:
    """The pixel back on the horizontal plane at height z (as observe places detections)."""
    H = np.c_[P[:, 0], P[:, 1], P[:, 2] * z + P[:, 3]]
    try:
        g = np.linalg.solve(H, np.array([uv[0], uv[1], 1.0]))
    except np.linalg.LinAlgError:
        return None
    return g[:2] / g[2] if g[2] != 0 else None


def _point(cls: str, bbox, view: str | None = None) -> tuple[tuple[float, float], float, float]:
    """The pixel observe places on the pitch, its height, and the size its error is measured by;
    for a lens in BIAS, the pixel less its measured bias."""
    x0, y0, x1, y1 = bbox
    if cls == "player":
        uv, z, size = ((x0 + x1) / 2, y1), 0.0, y1 - y0
    else:
        uv, z, size = ((x0 + x1) / 2, (y0 + y1) / 2), BALL_CENTRE_Z, x1 - x0
    if USE_LENS_BIAS and view in BIAS:
        (au, bu), (av, bv) = BIAS[view][cls]
        c = (uv[0] - VIEW_WIDTH_PX / 2) / (VIEW_WIDTH_PX / 2)
        uv = (uv[0] - size * (au + bu * c), uv[1] - size * (av + bv * c))
    return uv, z, size


def corrected(cls: str, d: dict, P: np.ndarray) -> dict:
    """The detection placed again from its bias-corrected pixel, for a lens in BIAS; else as it is."""
    if not USE_LENS_BIAS or d.get("view") not in BIAS:
        return d
    uv, z, _ = _point(cls, d["bbox"], d["view"])
    g = _ground(P, uv, z)
    return d if g is None else d | {"x": round(float(g[0]), 3), "y": round(float(g[1]), 3)}


def ellipse(cls: str, d: dict, P: np.ndarray, residual_px: float) -> np.ndarray | None:
    """The 2 x 2 pitch covariance (metres^2, in 99th-percentile units) of a detection's place:
    its pixel error (PRECISION of its size, the fit's residual and LABEL_PX, in quadrature)
    through the Jacobian of the ground mapping at its pixel. None if it cannot be mapped."""
    uv, z, size = _point(cls, d["bbox"], d.get("view"))
    lens = USE_LENS_BIAS and d.get("view") in VIEW_PRECISION
    across, down = VIEW_PRECISION[d["view"]][cls] if lens else PRECISION[cls]
    su = np.sqrt((across * size) ** 2 + residual_px ** 2 + LABEL_PX ** 2)
    sv = np.sqrt((down * size) ** 2 + residual_px ** 2 + LABEL_PX ** 2)
    g0 = _ground(P, uv, z)
    gu = _ground(P, (uv[0] + 1.0, uv[1]), z)
    gv = _ground(P, (uv[0], uv[1] + 1.0), z)
    if g0 is None or gu is None or gv is None:
        return None
    J = np.c_[gu - g0, gv - g0]  # metres per pixel
    return J @ np.diag([su ** 2, sv ** 2]) @ J.T


def same_place(a: dict, Sa: np.ndarray, b: dict, Sb: np.ndarray) -> float | None:
    """d' (Sa + Sb)^-1 d for the two places; at most 1 is the same object (module docstring)."""
    d = np.array([a["x"] - b["x"], a["y"] - b["y"]])
    try:
        return float(d @ np.linalg.solve(Sa + Sb, d))
    except np.linalg.LinAlgError:
        return None


def _merged(a: dict, Sa: np.ndarray, b: dict, Sb: np.ndarray) -> dict:
    Ia, Ib = np.linalg.inv(Sa), np.linalg.inv(Sb)
    xy = np.linalg.solve(Ia + Ib, Ia @ [a["x"], a["y"]] + Ib @ [b["x"], b["y"]])
    best = a if a["score"] >= b["score"] else b
    return best | {"x": round(float(xy[0]), 3), "y": round(float(xy[1]), 3),
                   "views": sorted({a["view"], b["view"]})}


def fuse_frame(rows: dict[str, dict]) -> dict:
    """One frame seen by each view (name -> observe's line for it) -> one fused line."""
    names = sorted(rows)
    first = rows[names[0]]
    out = {"frame": first["frame"], "t": first["t"],
           "camera": {"ok": any(rows[n]["camera"]["ok"] for n in names),
                      "views": {n: {"ok": rows[n]["camera"]["ok"],
                                    "median_px": rows[n]["camera"].get("median_px")} for n in names}}}
    for cls, key in (("player", "players"), ("ball", "ball")):
        cands, rest = [], []
        for n in names:
            cam = rows[n]["camera"]
            P = np.array(cam["P"]) if cam["ok"] and cam.get("P") is not None else None
            residual = float(cam.get("median_px") or 0.0)
            for d in rows[n][key]:
                d = d | {"view": n}
                S = None
                if P is not None and d["score"] >= SCORE_MIN and d.get("x") is not None:
                    d = corrected(cls, d, P)
                    S = ellipse(cls, d, P, residual)
                (cands if S is not None else rest).append((d, S))
        pairs = []
        for i, (a, Sa) in enumerate(cands):
            for j in range(i + 1, len(cands)):
                b, Sb = cands[j]
                if a["view"] != b["view"]:
                    m = same_place(a, Sa, b, Sb)
                    if m is not None and m <= 1.0:
                        pairs.append((m, i, j))
        used, fused = set(), []
        for _, i, j in sorted(pairs):
            if i in used or j in used:
                continue
            used |= {i, j}
            fused.append(_merged(*cands[i], *cands[j]))
        fused += [d | {"views": [d["view"]]} for k, (d, _) in enumerate(cands) if k not in used]
        fused += [d | {"views": [d["view"]]} for d, _ in rest]
        out[key] = sorted(fused, key=lambda d: -d["score"])
    return out


def fuse(views: dict[str, list[dict]]) -> list[dict]:
    """Each view's observations (name -> observe's lines) -> fused lines, frame by frame. The
    views must hold the same frames: they are one camera rig, shooting together."""
    if len(views) < 2:
        raise ValueError(f"fusing needs two views or more, got {sorted(views)}")
    frames = {n: [r["frame"] for r in rows] for n, rows in views.items()}
    ref = next(iter(frames.values()))
    if any(f != ref for f in frames.values()):
        raise ValueError("the views do not hold the same frames: " +
                         ", ".join(f"{n}: {len(f)} frames" for n, f in sorted(frames.items())))
    return [fuse_frame({n: views[n][k] for n in views}) for k in range(len(ref))]


def main(argv: list[str] | None = None) -> None:
    from ninety.vision.track import read_observations

    ap = argparse.ArgumentParser(description="Merge the tactical camera's views on the pitch.")
    ap.add_argument("--view", action="append", required=True, metavar="NAME=OBSERVATIONS",
                    help="a view's name and its observations file; give two or more")
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args(argv)
    views = {}
    for v in a.view:
        name, _, path = v.partition("=")
        if not name or not path or name in views:
            ap.error(f"--view {v!r}: give NAME=PATH, each name once")
        views[name] = read_observations(path)
    rows = fuse(views)
    with open(a.out, "w", encoding="utf-8", newline="\n") as f:
        for r in rows:
            f.write(json.dumps(r, separators=(",", ":")) + "\n")
    merged = sum(len(d["views"]) > 1 for r in rows for d in r["players"] + r["ball"])
    print(json.dumps({"out": str(a.out), "frames": len(rows), "merged": merged}))


if __name__ == "__main__":
    main()
