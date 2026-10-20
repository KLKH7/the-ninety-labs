"""Where the camera is, from the pitch markings in the image: image pixels to pitch metres.

The live path may not read the camera the renderer saved (frames.jsonl is the answer key), so the
camera is estimated from what a broadcast picture shows: the white markings, whose layout is fixed
by Law 1 (docs/GROUNDING.md, L1). The model is the broadcast main camera: a fixed gantry that pans,
tilts and zooms, with no roll, square pixels and the principal point at the image centre (the
pinhole the renderer draws, ninety/render/camera.py). So a clip has 3 unknowns (where the gantry
is) and each frame 3 more (pan, tilt, focal length).

    line_points(rgb, boxes)        white-marking pixels, with players and the ball masked out
    fit_clip(points_by_frame, ...) the gantry and every frame's pan, tilt and focal length

Each frame is fitted by Gauss-Newton on the pixel distance from every marking pixel to the nearest
projected marking, with a Cauchy loss so stray pixels (a white boot, a shadow edge) count little.
A frame whose markings do not pin the camera (too few marking pixels, or a residual that says the
fit is wrong, as at a camera cut) is marked `ok: false`, and nothing downstream reads its
positions.

numpy only; the image is passed in as an array, so this runs without an image library.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

# Law 1 (GROUNDING L1): a 105 x 68 m pitch, centre circle 9.15 m, penalty area 16.5 m deep and
# 40.32 m wide, goal area 5.5 m by 18.32 m, penalty mark 11 m out, arc 9.15 m from the mark,
# corner arcs 1 m. x 0..105 toward the right goal, y 0..68 from the near touchline.
PITCH_X, PITCH_Y = 105.0, 68.0
CIRCLE_R = 9.15
ARC_STEP_M = 1.0  # arcs become chords this long: a 9.15 m circle then sags under 1.5 cm


def _arc(cx: float, cy: float, r: float, a0: float, a1: float) -> list[tuple[float, float]]:
    n = max(2, math.ceil(abs(a1 - a0) * r / ARC_STEP_M))
    return [(cx + r * math.cos(a0 + (a1 - a0) * i / n), cy + r * math.sin(a0 + (a1 - a0) * i / n))
            for i in range(n + 1)]


def pitch_polylines() -> list[list[tuple[float, float]]]:
    """Every marking as a polyline on the ground, in pitch metres."""
    lines = [
        [(0, 0), (PITCH_X, 0), (PITCH_X, PITCH_Y), (0, PITCH_Y), (0, 0)],
        [(52.5, 0), (52.5, PITCH_Y)],
        _arc(52.5, 34, CIRCLE_R, 0, 2 * math.pi),
    ]
    a = math.acos(5.5 / CIRCLE_R)  # the arc is the part of the mark's circle outside the area
    for gx, s in ((0.0, 1.0), (PITCH_X, -1.0)):
        lines.append([(gx, 13.84), (gx + s * 16.5, 13.84), (gx + s * 16.5, 54.16), (gx, 54.16)])
        lines.append([(gx, 24.84), (gx + s * 5.5, 24.84), (gx + s * 5.5, 43.16), (gx, 43.16)])
        lines.append(_arc(11, 34, CIRCLE_R, -a, a) if s > 0
                     else _arc(94, 34, CIRCLE_R, math.pi - a, math.pi + a))
    corners = ((0, 0, 0), (PITCH_X, 0, math.pi / 2), (PITCH_X, PITCH_Y, math.pi), (0, PITCH_Y, 1.5 * math.pi))
    for cx, cy, a0 in corners:
        lines.append(_arc(cx, cy, 1.0, a0, a0 + math.pi / 2))
    return lines


def pitch_segments() -> np.ndarray:
    """(M, 2, 3): every marking as ground segments (z = 0)."""
    segs = []
    for pl in pitch_polylines():
        for p, q in zip(pl[:-1], pl[1:], strict=True):
            segs.append([[p[0], p[1], 0.0], [q[0], q[1], 0.0]])
    return np.asarray(segs, dtype=float)


SEGMENTS = pitch_segments()


@dataclass(frozen=True)
class View:
    """One frame's camera: gantry position (pitch metres), pan, tilt (radians) and focal (px).

    pan 0 looks straight up the pitch (+y), positive turns toward +x; tilt is the angle below the
    horizon. Image size gives the principal point."""

    cx: float
    cy: float
    cz: float
    pan: float
    tilt: float
    focal: float
    width: int
    height: int

    def vector(self) -> np.ndarray:
        return np.array([self.cx, self.cy, self.cz, self.pan, self.tilt, self.focal])

    @classmethod
    def from_vector(cls, v, width: int, height: int) -> View:
        return cls(*(float(x) for x in v), width=width, height=height)

    def rotation(self) -> np.ndarray:
        """World-to-camera rows: right, down, forward (OpenCV axes, as the renderer)."""
        cp, sp, ct, st = math.cos(self.pan), math.sin(self.pan), math.cos(self.tilt), math.sin(self.tilt)
        fwd = np.array([sp * ct, cp * ct, -st])
        right = np.array([cp, -sp, 0.0])  # fwd x z, normalised
        down = np.cross(fwd, right)
        return np.stack([right, down, fwd])

    def P(self) -> np.ndarray:
        R = self.rotation()
        t = -R @ np.array([self.cx, self.cy, self.cz])
        K = np.array([[self.focal, 0, self.width / 2], [0, self.focal, self.height / 2], [0, 0, 1.0]])
        return K @ np.hstack([R, t[:, None]])

    def project(self, X: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """(N, 3) world points -> (N, 2) pixels and depth (N,)."""
        h = np.hstack([X, np.ones((len(X), 1))]) @ self.P().T
        return h[:, :2] / h[:, 2:3], h[:, 2]

    def to_ground(self, uv: np.ndarray, z: float = 0.0) -> np.ndarray:
        """(N, 2) pixels -> (N, 2) pitch metres where each ray meets the plane at height z;
        NaN for a ray at or above the horizon."""
        R = self.rotation()
        K_inv = np.array([[1 / self.focal, 0, -self.width / (2 * self.focal)],
                          [0, 1 / self.focal, -self.height / (2 * self.focal)], [0, 0, 1.0]])
        rays = (np.hstack([uv, np.ones((len(uv), 1))]) @ K_inv.T) @ R  # camera ray in world axes
        s = (z - self.cz) / rays[:, 2]
        out = np.stack([self.cx + s * rays[:, 0], self.cy + s * rays[:, 1]], axis=1)
        out[~(s > 0)] = np.nan
        return out


# ---------------------------------------------------------------------------------------------
# Marking pixels

# A marking pixel is brighter and bluer than the grass on both sides of it across the line. Grass
# is green with little blue; paint is near white, so the blue channel separates them best, and
# requiring the step on both sides rejects the edge between two mowing stripes, which is bright
# on one side only. Lines 12 cm wide are 1 to 7 px across at broadcast range, so both sides are
# tested 2, 3 and 4 px out. The thresholds are design, set on frames of a training clip.
SIDE_PX = (2, 3, 4)
MIN_LUMA_STEP = 10.0
MIN_BLUE_STEP = 15.0
BOX_PAD_PX = 4  # around each detected player and ball, so a white kit or boot is not a marking


def _shift(a: np.ndarray, dy: int, dx: int, fill) -> np.ndarray:
    H, W = a.shape
    out = np.full_like(a, fill)
    out[max(dy, 0):H + min(dy, 0), max(dx, 0):W + min(dx, 0)] = \
        a[max(-dy, 0):H + min(-dy, 0), max(-dx, 0):W + min(-dx, 0)]
    return out


def line_mask(rgb: np.ndarray, boxes=()) -> np.ndarray:
    """(H, W) bool: pixels on a white marking, with the given [x0, y0, x1, y1] boxes cleared."""
    img = rgb.astype(np.float32)
    r, g, b = img[..., 0], img[..., 1], img[..., 2]
    luma = img.mean(-1)
    grass = (g > r + 10) & (g > b + 10)
    mask = np.zeros(luma.shape, dtype=bool)
    for k in SIDE_PX:
        for dy, dx in ((k, 0), (0, k)):
            l1, l2 = _shift(luma, dy, dx, 0.0), _shift(luma, -dy, -dx, 0.0)
            b1, b2 = _shift(b, dy, dx, 0.0), _shift(b, -dy, -dx, 0.0)
            g1, g2 = _shift(grass, dy, dx, False), _shift(grass, -dy, -dx, False)
            mask |= ((luma - np.maximum(l1, l2) > MIN_LUMA_STEP) & (b - np.maximum(b1, b2) > MIN_BLUE_STEP)
                     & g1 & g2)
    H, W = mask.shape
    for x0, y0, x1, y1 in boxes:
        p = BOX_PAD_PX
        ya, yb = max(int(y0) - p, 0), min(int(math.ceil(y1)) + p, H)
        xa, xb = max(int(x0) - p, 0), min(int(math.ceil(x1)) + p, W)
        mask[ya:yb, xa:xb] = False
    return mask


def line_points(rgb: np.ndarray, boxes=(), max_points: int = 800) -> np.ndarray:
    """(N, 2) pixel centres of marking pixels, thinned evenly to at most max_points."""
    ys, xs = np.nonzero(line_mask(rgb, boxes))
    pts = np.stack([xs + 0.5, ys + 0.5], axis=1)
    if len(pts) > max_points:
        pts = pts[np.linspace(0, len(pts) - 1, max_points).astype(int)]
    return pts


# ---------------------------------------------------------------------------------------------
# Fitting

CAUCHY_PX = 3.0  # the loss's scale: a pixel this far from a marking already counts half
FD_STEP = np.array([0.05, 0.05, 0.05, 1e-4, 1e-4, 0.5])  # finite-difference steps per parameter


# Distances are capped: a pixel this far from every marking is an outlier whatever the exact
# figure (the Cauchy loss is nearly flat out here), so markings that project this far outside the
# picture can be dropped before measuring without changing any result (design).
MAX_DIST_PX = 100.0


def distances(view: View, pts: np.ndarray, segments: np.ndarray = SEGMENTS) -> np.ndarray:
    """Pixel distance from each point to the nearest projected marking, capped at MAX_DIST_PX."""
    a, da = view.project(segments[:, 0])
    b, db = view.project(segments[:, 1])
    m = MAX_DIST_PX
    keep = ((da > 0) & (db > 0)
            & (np.maximum(a[:, 0], b[:, 0]) > -m) & (np.minimum(a[:, 0], b[:, 0]) < view.width + m)
            & (np.maximum(a[:, 1], b[:, 1]) > -m) & (np.minimum(a[:, 1], b[:, 1]) < view.height + m))
    a, b = a[keep], b[keep]
    if not len(a):
        return np.full(len(pts), m)
    ab = b - a
    L2 = np.maximum((ab ** 2).sum(1), 1e-12)
    ap = pts[:, None, :] - a[None]
    t = np.clip((ap * ab[None]).sum(-1) / L2[None], 0.0, 1.0)
    d = np.linalg.norm(ap - t[..., None] * ab[None], axis=-1)
    return np.minimum(d.min(1), m)


def _P_many(V: np.ndarray, width: int, height: int) -> np.ndarray:
    """(B, 6) parameter rows -> (B, 3, 4) projection matrices, as View.P does one at a time."""
    cp, sp, ct, st = np.cos(V[:, 3]), np.sin(V[:, 3]), np.cos(V[:, 4]), np.sin(V[:, 4])
    fwd = np.stack([sp * ct, cp * ct, -st], axis=1)
    right = np.stack([cp, -sp, np.zeros_like(cp)], axis=1)
    down = np.cross(fwd, right)
    R = np.stack([right, down, fwd], axis=1)
    t = -np.einsum("bij,bj->bi", R, V[:, :3])
    K = np.zeros((len(V), 3, 3))
    K[:, 0, 0] = K[:, 1, 1] = V[:, 5]
    K[:, 0, 2], K[:, 1, 2], K[:, 2, 2] = width / 2, height / 2, 1.0
    return K @ np.concatenate([R, t[:, :, None]], axis=2)


def costs_many(V: np.ndarray, pts: np.ndarray, width: int, height: int, chunk: int = 256,
               scale: float = CAUCHY_PX) -> np.ndarray:
    """cost() for many parameter rows at once: the same capped distances and Cauchy loss."""
    out = np.empty(len(V))
    A = np.hstack([SEGMENTS[:, 0], np.ones((len(SEGMENTS), 1))])
    B = np.hstack([SEGMENTS[:, 1], np.ones((len(SEGMENTS), 1))])
    m = MAX_DIST_PX
    for i in range(0, len(V), chunk):
        P = _P_many(V[i:i + chunk], width, height)
        ha, hb = np.einsum("bij,mj->bmi", P, A), np.einsum("bij,mj->bmi", P, B)
        front = (ha[..., 2] > 0) & (hb[..., 2] > 0)
        a = ha[..., :2] / np.where(front, ha[..., 2], 1.0)[..., None]
        b = hb[..., :2] / np.where(front, hb[..., 2], 1.0)[..., None]
        ab = b - a
        L2 = np.maximum((ab ** 2).sum(-1), 1e-12)
        ap = pts[None, :, None, :] - a[:, None]
        t = np.clip((ap * ab[:, None]).sum(-1) / L2[:, None], 0.0, 1.0)
        d = np.linalg.norm(ap - t[..., None] * ab[:, None], axis=-1)
        d = np.where(front[:, None], d, m).min(-1)
        d = np.minimum(d, m)
        out[i:i + chunk] = np.mean(scale ** 2 * np.log1p((d / scale) ** 2), axis=1)
    return out


def _cauchy_weights(r: np.ndarray, scale: float = CAUCHY_PX) -> np.ndarray:
    return 1.0 / (1.0 + (r / scale) ** 2)


def cost(view: View, pts: np.ndarray) -> float:
    """Mean Cauchy loss in px^2: about the squared pixel error when the fit is right."""
    r = distances(view, pts)
    return float(np.mean(CAUCHY_PX ** 2 * np.log1p((r / CAUCHY_PX) ** 2)))


def _objective(v: np.ndarray, view: View, pts: np.ndarray, prior, prior_sd,
               scale: float = CAUCHY_PX) -> float:
    """What refine minimises: the summed Cauchy loss plus, with a prior, its squared z-scores."""
    r = distances(View.from_vector(v, view.width, view.height), pts)
    total = float(np.sum(scale ** 2 * np.log1p((r / scale) ** 2)))
    if prior is not None:
        total += float(np.sum(((v - prior) / prior_sd) ** 2))
    return total


def refine(view: View, pts: np.ndarray, free=(3, 4, 5), iters: int = 15, prior: np.ndarray | None = None,
           prior_sd: np.ndarray | None = None, scale: float = CAUCHY_PX) -> View:
    """Levenberg-Marquardt with Cauchy weights (IRLS) on the chosen parameters. An optional prior
    (a full vector and per-parameter SDs) keeps a frame with few markings near its neighbour."""
    v = view.vector()
    free = list(free)
    if prior is not None:
        prior = np.asarray(prior, dtype=float).copy()
        prior_sd = np.asarray(prior_sd, dtype=float)
        fixed = [k for k in range(6) if k not in free]
        prior[fixed] = v[fixed]  # a parameter held fixed is not pulled anywhere
    lam = 1e-3
    for _ in range(iters):
        r = distances(View.from_vector(v, view.width, view.height), pts)
        w2 = _cauchy_weights(r, scale)
        J = np.zeros((len(pts), len(free)))
        for j, k in enumerate(free):
            vp = v.copy()
            vp[k] += FD_STEP[k]
            J[:, j] = (distances(View.from_vector(vp, view.width, view.height), pts) - r) / FD_STEP[k]
        A = (J * w2[:, None]).T @ J
        g = (J * w2[:, None]).T @ r
        if prior is not None:
            Pd = 1.0 / prior_sd[free] ** 2
            A = A + np.diag(Pd)
            g = g + Pd * (v[free] - prior[free])
        before = _objective(v, view, pts, prior, prior_sd, scale)
        while True:
            step = np.linalg.solve(A + lam * np.diag(np.diag(A) + 1e-9), -g)
            trial = v.copy()
            trial[free] += step
            if _objective(trial, view, pts, prior, prior_sd, scale) <= before:
                v, lam = trial, max(lam / 3, 1e-6)
                break
            lam *= 4
            if lam > 1e6:
                return View.from_vector(v, view.width, view.height)
        if np.all(np.abs(step) < FD_STEP[free] * 0.1):
            break
    return View.from_vector(v, view.width, view.height)


# The search for a first view. A main broadcast camera sits on a gantry beside the halfway line,
# behind the near touchline, looking down at it. These ranges are a wide prior on that (design):
# along the touchline within 15 m of halfway, 20 to 55 m back, looking down at the near touchline
# at 15 to 30 degrees, a lens whose shot is 20 to 70 m wide at the aim point.
GANTRY_X = (37.5, 52.5, 67.5)
GANTRY_BACK = (20.0, 30.0, 40.0, 55.0)
GANTRY_DOWN_DEG = (15.0, 22.0, 30.0)
# Every view a gantry can take: pan across the whole pitch, tilt from just under the horizon to
# steeply down, lenses from 8 to 45 degrees across (design). The steps move the picture by about
# 54 px (pan) and 36 px (tilt) at a long lens, inside COARSE_PX's reach, so some grid view is
# always near enough to the right one for the refine to find it.
PANS = tuple(np.arange(-0.9, 0.9001, 0.015))
TILTS = tuple(np.arange(0.04, 0.4001, 0.01))
HFOV_DEG = (8.0, 10.5, 14.0, 18.5, 24.0, 32.0, 45.0)
SEARCH_COARSE_POINTS = 100  # marking pixels a coarse grid view is scored on
GANTRY_FINALISTS = 8  # grid gantries kept after the anchor with most markings
GANTRY_SCORE_FRAMES = 5  # anchors the finalists are scored on
JOINT_SCALES_PX = (12.0, 6.0, CAUCHY_PX, 12.0, 6.0, CAUCHY_PX)  # the joint fit's schedule (design)
JOINT_MAX_MEDIAN_PX = 5.0  # an anchor this far off at the best grid gantry stays out of the joint fit


# The coarse ranking: each grid view's markings, sampled every MODEL_STEP_M, are looked up in a
# map of the distance to the nearest marking pixel, built once per frame on a DT_CELL_PX grid.
# Thousands of views cost what one exact cost does; it only has to put the right basin among the
# best COARSE_KEEP, which the exact cost then ranks (design).
MODEL_STEP_M = 1.0
DT_CELL_PX = 4
COARSE_KEEP = 64
COARSE_PX = 20.0  # the loss's scale while ranking grid views (design)
REFINE_SCALES_PX = (12.0, CAUCHY_PX)  # a search's refine, coarse to fine (design)
MIN_IN_SHOT = 20  # sampled marking points in shot, fewer and the view says too little (design)


def _model_samples(step: float = MODEL_STEP_M) -> np.ndarray:
    pts = []
    for pl in pitch_polylines():
        for (x0, y0), (x1, y1) in zip(pl[:-1], pl[1:], strict=True):
            n = max(1, math.ceil(math.hypot(x1 - x0, y1 - y0) / step))
            pts += [(x0 + (x1 - x0) * k / n, y0 + (y1 - y0) * k / n, 0.0, 1.0) for k in range(n)]
    return np.array(pts)


MODEL_SAMPLES = _model_samples()
MODEL_SAMPLES_T = MODEL_SAMPLES.T.astype(np.float32).copy()


def distance_map(pts: np.ndarray, width: int, height: int, cell: int = DT_CELL_PX) -> np.ndarray:
    """(rows, cols): pixel distance from each cell to the nearest cell holding a point, capped at
    MAX_DIST_PX. Grown outward one cell at a time with the 3-4 chamfer weights (Borgefors 1986),
    within 8% of the true distance: enough to rank coarse views."""
    cols, rows = math.ceil(width / cell), math.ceil(height / cell)
    d = np.full((rows, cols), np.inf, dtype=np.float32)
    if len(pts):
        c = np.clip((pts // cell).astype(int), 0, [cols - 1, rows - 1])
        d[c[:, 1], c[:, 0]] = 0.0
    step = [(dy, dx, cell * (4.0 if dy and dx else 3.0) / 3.0) for dy in (-1, 0, 1) for dx in (-1, 0, 1)
            if dy or dx]
    for _ in range(math.ceil(MAX_DIST_PX / cell) + 1):
        grown = d.copy()
        for dy, dx, w in step:
            grown = np.minimum(grown, _shift(d, dy, dx, np.inf) + w)
        if np.array_equal(grown, d):
            break
        d = grown
    return np.minimum(d, MAX_DIST_PX)


def chamfer_many(V: np.ndarray, dmap: np.ndarray, width: int, height: int, chunk: int = 512,
                 scale: float = CAUCHY_PX) -> np.ndarray:
    """Mean Cauchy loss of each view's sampled markings in shot, looked up in the distance map;
    infinite for a view with fewer than MIN_IN_SHOT samples in shot."""
    out = np.empty(len(V))
    rows, cols = dmap.shape
    for i in range(0, len(V), chunk):
        h = _P_many(V[i:i + chunk], width, height).astype(np.float32) @ MODEL_SAMPLES_T  # (b, 3, m)
        z = h[:, 2]
        u = h[:, 0] / np.where(z > 0, z, 1.0)
        v = h[:, 1] / np.where(z > 0, z, 1.0)
        shot = (z > 0) & (u >= 0) & (u < width) & (v >= 0) & (v < height)
        u, v = np.where(shot, u, 0.0), np.where(shot, v, 0.0)
        cu = np.clip((u // DT_CELL_PX).astype(int), 0, cols - 1)
        cv = np.clip((v // DT_CELL_PX).astype(int), 0, rows - 1)
        d = dmap[cv, cu]
        loss = np.where(shot, scale ** 2 * np.log1p((d / scale) ** 2), 0.0)
        n = shot.sum(1)
        out[i:i + chunk] = np.where(n >= MIN_IN_SHOT, loss.sum(1) / np.maximum(n, 1), np.inf)
    return out


def search(pts: np.ndarray, width: int, height: int, gantry: tuple[float, float, float] | None = None,
           keep: int = 6, iters: int = 15) -> list[View]:
    """Coarse grid of aim points and lenses (and gantries, unless given), best `keep` by cost,
    each refined. A coarse view is scored on a subsample to keep the grid affordable."""
    sample = _sample(pts, SEARCH_POINTS)
    sub = _sample(pts, SEARCH_COARSE_POINTS)
    gantries = [gantry] if gantry else [
        (x, -back, back * math.tan(math.radians(dn))) for x in GANTRY_X for back in GANTRY_BACK
        for dn in GANTRY_DOWN_DEG]
    focals = [width / 2 / math.tan(math.radians(h) / 2) for h in HFOV_DEG]
    V = np.array([(cx, cy, cz, pan, tilt, f) for cx, cy, cz in gantries
                  for pan in PANS for tilt in TILTS for f in focals])
    # Rank the whole grid by the cheap chamfer, then the best COARSE_KEEP by the exact cost, both
    # at COARSE_PX: a grid view is tens of pixels from the truth, where the fine loss is flat.
    dmap = distance_map(pts, width, height)
    order = np.argsort(chamfer_many(V, dmap, width, height, scale=COARSE_PX), kind="stable")[:COARSE_KEEP]
    exact = costs_many(V[order], sub, width, height, scale=COARSE_PX)
    best = np.argsort(exact, kind="stable")[:keep * 4]
    starts = [View.from_vector(V[order[k]], width, height) for k in best]
    # Aim and lens first with the gantry where the grid put it (freeing all six at once from a
    # coarse start lets the gantry slide into a wrong basin), coarse to fine (graduated loss).
    aimed = []
    for v in starts:
        for sc in REFINE_SCALES_PX:
            v = refine(v, sample, free=(3, 4, 5), iters=iters, scale=sc)
        aimed.append(v)
    aimed.sort(key=lambda v: cost(v, sample))
    if gantry:
        return aimed[:keep]
    out = [refine(v, sample, free=(0, 1, 2, 3, 4, 5)) for v in aimed[:keep]]
    return sorted(out, key=lambda v: cost(v, sample))


# ---------------------------------------------------------------------------------------------
# A whole clip: one gantry, every frame's aim and lens

# A frame's fit is trusted when half its marking pixels lie within MAX_MEDIAN_PX of a projected
# marking and it has at least MIN_POINTS of them. A line is found to about its blur width (1 to
# 2 px at broadcast range), so 1.5 px is the precision of a right fit, not a tuned threshold
# (design); 60 pixels is two short line pieces, the least that pins three angles (design).
MAX_MEDIAN_PX = 1.5
MIN_POINTS = 60
SEARCH_POINTS = 300  # marking pixels per frame while searching; the final fit uses all of them
# How far one frame's aim and lens may move from the last one before the data must say so: the
# prior keeps a frame with one visible line from sliding along it. A broadcast pan is under about
# 30 degrees a second (0.02 rad a frame at 25 fps) and a zoom under 10% a second (design).
STEP_SD = np.array([1.0, 1.0, 1.0, 0.02, 0.01, 0.004])


@dataclass(frozen=True)
class FrameFit:
    view: View | None
    median_px: float | None
    points: int
    ok: bool


def _sample(pts: np.ndarray, n: int) -> np.ndarray:
    return pts if len(pts) <= n else pts[np.linspace(0, len(pts) - 1, n).astype(int)]


def _median(view: View, pts: np.ndarray) -> float:
    return float(np.median(distances(view, pts))) if len(pts) else math.inf


def _judge(view: View, pts: np.ndarray) -> FrameFit:
    med = _median(view, pts)
    return FrameFit(view, round(med, 3), len(pts), bool(len(pts) >= MIN_POINTS and med <= MAX_MEDIAN_PX))


def find_gantry(anchors: list[np.ndarray], width: int, height: int) -> tuple[float, float, float]:
    """The gantry that lets the anchor frames fit best. Every grid gantry is ranked by how well
    the anchor with the most markings fits from it (its best aim and lens); the best few are
    scored on several anchors; the winner is refined jointly with every anchor that fits it."""
    anchors = sorted((a for a in anchors if len(a) >= MIN_POINTS), key=len, reverse=True)
    if not anchors:
        raise ValueError("no frame shows enough pitch markings to place the camera")
    anchors = [_sample(a, SEARCH_POINTS) for a in anchors]
    grid = [(gx, -back, back * math.tan(math.radians(dn)))
            for gx in GANTRY_X for back in GANTRY_BACK for dn in GANTRY_DOWN_DEG]

    def fitted(g, a):
        return search(a, width, height, gantry=g, keep=1)[0]

    first = sorted(grid, key=lambda g: cost(fitted(g, anchors[0]), anchors[0]))[:GANTRY_FINALISTS]
    some = anchors[:GANTRY_SCORE_FRAMES]
    g = min(first, key=lambda g: sum(cost(fitted(g, a), a) for a in some))
    views = [fitted(g, a) for a in anchors]
    keep = [k for k, (v, a) in enumerate(zip(views, anchors, strict=True))
            if _median(v, a) <= JOINT_MAX_MEDIAN_PX]
    if not keep:
        return g
    views, anchors = [views[k] for k in keep], [anchors[k] for k in keep]
    for sc in JOINT_SCALES_PX:  # coarse to fine, as a search's refine
        g = refine_joint(g, views, anchors, scale=sc)
        views = [refine(View(*g, v.pan, v.tilt, v.focal, width, height), a, scale=sc)
                 for v, a in zip(views, anchors, strict=True)]
    g, views = polish_gantry(g, views, anchors)
    # Near the bottom the floor is smooth again: finish with the joint step.
    return refine_joint(g, views, anchors, scale=CAUCHY_PX)


def refine_joint(g, views: list[View], anchors: list[np.ndarray], iters: int = 30,
                 scale: float = CAUCHY_PX) -> tuple[float, float, float]:
    """Levenberg-Marquardt over the gantry and every anchor's aim and lens at once, with Cauchy
    weights. The gantry's columns of the Jacobian touch every anchor; an anchor's own only its."""
    W, H = views[0].width, views[0].height
    n = len(views)
    x = np.concatenate([np.asarray(g, dtype=float)] + [v.vector()[3:] for v in views])

    def view(x, k):
        return View(*x[:3], *x[3 + 3 * k:6 + 3 * k], W, H)

    def resid(x):
        return [distances(view(x, k), anchors[k]) for k in range(n)]

    def obj(rs):
        return sum(float(np.sum(scale ** 2 * np.log1p((r / scale) ** 2))) for r in rs)

    lam = 1e-3
    rs = resid(x)
    for _ in range(iters):
        sizes = [len(a) for a in anchors]
        J = np.zeros((sum(sizes), len(x)))
        r = np.concatenate(rs)
        w2 = _cauchy_weights(r, scale)
        off = np.cumsum([0] + sizes)
        for j in range(3):
            xp = x.copy()
            xp[j] += FD_STEP[j]
            J[:, j] = (np.concatenate(resid(xp)) - r) / FD_STEP[j]
        for k in range(n):
            for j in range(3):
                col = 3 + 3 * k + j
                xp = x.copy()
                xp[col] += FD_STEP[3 + j]
                J[off[k]:off[k + 1], col] = (distances(view(xp, k), anchors[k]) - rs[k]) / FD_STEP[3 + j]
        A = (J * w2[:, None]).T @ J
        grad = (J * w2[:, None]).T @ r
        before = obj(rs)
        while True:
            step = np.linalg.solve(A + lam * np.diag(np.diag(A) + 1e-9), -grad)
            trial = x + step
            trs = resid(trial)
            if obj(trs) <= before:
                x, rs, lam = trial, trs, max(lam / 3, 1e-6)
                break
            lam *= 4
            if lam > 1e6:
                return float(x[0]), float(x[1]), float(x[2])
        if np.all(np.abs(step[:3]) < 1e-3):
            break
    return float(x[0]), float(x[1]), float(x[2])


def polish_gantry(g, views: list[View], anchors: list[np.ndarray], step_m: float = 4.0,
                  min_step_m: float = 0.02) -> tuple[tuple[float, float, float], list[View]]:
    """Compass search on the gantry, each trial scored with every anchor's aim and lens refitted
    from its last fit. The fit's valley along the line of sight is long and shallow with a narrow
    lens (distance trades against zoom), and its floor is rough where pixels change their nearest
    marking, which stalls a gradient step; comparing whole refits walks along it."""
    W, H = views[0].width, views[0].height

    def fitted(gv, vs):
        out = [refine(View(*gv, v.pan, v.tilt, v.focal, W, H), a, iters=6)
               for v, a in zip(vs, anchors, strict=True)]
        return sum(cost(v, a) for v, a in zip(out, anchors, strict=True)), out

    best, views = fitted(np.asarray(g, dtype=float), views)
    g = np.asarray(g, dtype=float)
    step = step_m
    while step >= min_step_m:
        moved = False
        for k in range(3):
            for sign in (1.0, -1.0):
                trial = g.copy()
                trial[k] += sign * step
                c, vs = fitted(trial, views)
                if c < best:
                    best, g, views, moved = c, trial, vs, True
                    break
        if not moved:
            step /= 2
    return (float(g[0]), float(g[1]), float(g[2])), views


def fit_clip(points: list[np.ndarray], width: int, height: int,
             anchor_every: int = 25) -> tuple[tuple, list[FrameFit]]:
    """The gantry and one FrameFit per frame, in order. Each frame starts from the last good
    one, held near it by STEP_SD; a frame that fits badly from there (a camera cut, a fast pan) is
    searched afresh with the gantry fixed, and kept only if that search fits."""
    g = find_gantry(points[::anchor_every], width, height)
    fits: list[FrameFit] = []
    last: View | None = None
    for pts in points:
        if len(pts) < MIN_POINTS:
            fits.append(FrameFit(None, None, len(pts), False))
            continue
        fit = None
        if last is not None:
            v = refine(last, pts, prior=last.vector(), prior_sd=STEP_SD)
            fit = _judge(v, pts)
        if fit is None or not fit.ok:
            v = refine(search(_sample(pts, SEARCH_POINTS), width, height, gantry=g, keep=1)[0], pts)
            fresh = _judge(v, pts)
            better = (fresh.median_px or 1e9) < (fit.median_px or 1e9) if fit else True
            fit = fresh if fit is None or fresh.ok or better else fit
        fits.append(fit)
        if fit.ok:
            last = fit.view
    return g, fits
