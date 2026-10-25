"""The ball's height from its flight: detected ball pixels + each frame's fitted camera -> 3D.

    uv run python -m ninety.vision.flight <observations.jsonl> --out <observations-flight.jsonl>
    uv run python -m ninety.vision.flight --derive <observations of validation clips...> --report <json>

observe.py places every detected ball on the ground (its centre one radius up), so a ball in the
air lands beyond where it is, along the camera's line of sight. One camera cannot tell a near, slow
ball from a far, fast one on the same rays; physics can. Between two touches or bounces the ball's
centre follows

    r'' = g - K |r'| r'        (gravity, and air drag: a deceleration K * speed^2)

and its 6 unknowns (position and velocity at the segment's first frame) are fitted by
Levenberg-Marquardt on the pixel distance between each frame's detected ball centre and the path
projected through that frame's camera. Gravity is the one known length in the problem: how far the
ball falls in a given time fixes how far along each ray it is. Drag is needed as well as gravity:
over 0.4 s it slows a 30 m/s ball about as much as gravity pulls it down, and a drag-free fit
makes up for the missing slowing by tilting the flight along the line of sight.

Segments. The ball's track (one ball per frame: the highest-scoring detection on a trusted camera,
the one the scorers read) is cut into pieces greedily: a piece starts with MIN_FRAMES frames and
grows one frame at a time while one of two models still fits every frame within GATE_SIGMA pixel
noise standard deviations:
- on the ground: centre one radius up, a straight line at a steady deceleration (5 unknowns);
- in flight: the equation above (6 unknowns), never below the ground by more than Z_TOL_M.
A frame neither fits is taken as a stray detection if the frame after it fits again; two in a row
end the piece (a touch, a bounce, a landing). A finished piece is in flight when the flight model
is physical and beats the ground model by more than the extra unknown is worth (the Bayesian
information criterion: a fall in squared error, in noise units, above ln of the number of pixel
coordinates); otherwise it is on the ground. Ground frames keep observe.py's positions, and so
does a flight frame whose fitted place is less sure than MAX_SE_M (a short, low hop).

DRAG_K and NOISE_PX are derived on validation clips by `--derive`, from pixel residuals only
(derive_noise, derive_drag), and the ball-size spread from its box sizes (derive_size); the answer
key is never read here.
"""

from __future__ import annotations

import argparse
import copy
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from ninety.vision.observe import BALL_CENTRE_Z
from ninety.vision.track import SCORE_MIN

GRAVITY = 9.81  # m/s^2, standard gravity; it varies by under 0.3% over the Earth's surface
# K, the drag deceleration per speed squared (1/m): 0.5 * air density * Cd * ball cross-section /
# mass. Fitted, not fixed from a published Cd, because the published values do not agree with each
# other or with one number: wind-tunnel drag coefficients of match balls are about 0.12 to 0.15
# above the drag crisis (about 15 to 22 m/s; Asai & Seo 2013, SpringerPlus 2:171) and about 0.45
# below it, so K depends on the ball and its speed. One K is fitted on validation clips' flights by
# pixel error alone (derive_drag), before any test number was read.
# Derived 2026-10-24 by `--derive` on the 13 validation clips' observations (seeds 108 109 114 115
# 116 120 121 122 2041 2042 2043 3041 3042, branch pr-assets/detector-validation-observations at
# 4d42fbf, sha256 as in docs/eval/detector-derive-observations.sha256; 2045 and 3045 are not there):
# 13 flights, 278 frames, K = 0.0124 +- 0.00046 (Cd 0.234 +- 0.009, air 1.2 kg/m^3, radius 0.11 m,
# mass 0.43 kg by Law 2). The clips' engine uses Cd 0.25 (ninety/sim/ball.py); the published value
# above, 0.15, would have been a third too low. The +- counts pixel noise only, not camera error.
DRAG_K = 0.0124
# The detected ball centre's pixel noise, one coordinate's standard deviation, from the pieces'
# residuals on the same 13 clips and run (derive_noise). At the derived K the error left over is
# what that noise predicts (274 px^2 against about 265), so the model misses no large error.
NOISE_PX = 0.742
GATE_SIGMA = 3.5  # a frame fits within this many sigma: a 2D normal lands outside 0.2% of the time
MIN_FRAMES = 5  # a piece's first window: 10 pixel coordinates for 6 unknowns, so a misfit can show
MAX_GAP_S = 0.5  # frames further apart than this (ball unseen, camera untrusted) start a new piece
Z_TOL_M = 0.15  # a flight may dip this far below the ground at most: noise, not a ball underground
# Two physical facts the pixels of a short piece cannot pin alone (on 5 to 15 frames a flight's
# depth along the rays is uncertain by metres): the ball is never under the ground, and its place
# is continuous through a touch or a bounce (only its velocity jumps). Both enter the fit as soft
# terms, in noise units. GROUND_SD_M: a centre this far under its resting height counts as one
# sigma (design: ten times the 5 mm a rounding of positions allows). ANCHOR_SD_M: a piece that
# starts within ANCHOR_MAX_S of the last one's end starts where that one's model puts the ball then,
# give or take this; a 30 m/s kick moves the ball about 0.6 m in the half frame the touch can fall
# in (design).
GROUND_SD_M = 0.05
ANCHOR_SD_M = 0.5
ANCHOR_MAX_S = 0.1
# A flight frame is moved only where the fit knows the ball's place on the pitch to this standard
# error or better (centre_se); else it keeps observe.py's ground place. A short, low hop (a few
# frames, little curve) cannot fix its speed along the line of sight, and its fit can be metres
# out where the ground place is about 1 m out. 1.0 m is the strict place tolerance the events are
# graded by (docs/EVALUATION.md, Vision scoring): a place less sure than that is not used (design).
MAX_SE_M = 1.0
# The ball's apparent size is a second measure of its depth, which gravity does not enter: a ball
# BALL_D_M across at depth d is f * BALL_D_M / d pixels wide (f the focal length in pixels). Each
# frame's log(box size / that size) is compared at a flight's depth and at the ground place's, and
# a flight the sizes speak against is not one (Piece.in_flight). The size only chooses; it does
# not move the fit (over a long flight gravity pins the depth better). On validation, short
# pieces with impossible launch speeds (85 to 494 m/s) showed a box 0.60 to 0.88 of the size their
# fit implies, while the ground place explained it (0.98 to 0.99): frames of them passed MAX_SE_M
# near the anchor and were moved.
# The box's shorter side is the size (motion blur stretches the longer one). SIZE_BIAS_LOG and
# SIZE_SD_LOG: the median and the robust spread (1.4826 * MAD) of that log ratio over every frame
# of the validation ground pieces of 10 frames or more (derive_size; 927 frames, 50 pieces, the
# 13 clips DRAG_K came from); 3% of those frames lie beyond 3 sigma (a ball half hidden), so one
# frame's term is capped at SIZE_CAP_SIGMA (design).
BALL_D_M = 0.22  # Law 2: circumference 68 to 70 cm, so 0.216 to 0.223 m across
SIZE_BIAS_LOG = -0.0161
SIZE_SD_LOG = 0.0293
SIZE_CAP_SIGMA = 3.0
# No football is struck faster than this: the fastest shot on record is about 211 km/h (58.6 m/s;
# Ronny Heberson, 2006, as media reported it, verify). A flight whose fitted start is faster is not
# physical (design: the record, rounded up).
MAX_LAUNCH_MPS = 60.0
# A model dropped from a growing piece is retried from a cold start only while the piece is this
# short: a wrong first guess drops a flight on a few frames, not on a second of them, and a cold
# flight fit over a long roll costs seconds (design, for speed).
RETRY_MAX_FRAMES = 25
MAX_STEP_S = 0.04  # integration step (RK4); one frame at 25 fps. Gravity is integrated exactly
FD_STEP = 1e-3  # finite-difference step for the Jacobian, metres and m/s
LM_ITERS = 30
RESERVED_FROM = 900000  # seeds at or above this are evaluation seeds (ninety/render/splits.py)


# ---------------------------------------------------------------------------------------------
# The ball's track


@dataclass
class Track:
    """The chosen ball of every usable frame, in time order."""

    rows: np.ndarray  # (N,) index of the frame's observation row
    balls: np.ndarray  # (N,) index of the chosen ball in that row's "ball" list
    t: np.ndarray  # (N,) seconds
    uv: np.ndarray  # (N, 2) detected centre, pixels
    P: np.ndarray  # (N, 3, 4) camera
    size: np.ndarray | None = None  # (N,) the box's shorter side, pixels

    def __len__(self) -> int:
        return len(self.t)


def focal_px(P: np.ndarray) -> np.ndarray:
    """(N, 3, 4) -> (N,) focal length in pixels: P = K [R | t] with square pixels and no skew, so
    the first row's rotation part is f * r1 + cx * r3 and r1 is a unit vector at right angles to r3."""
    m0, m2 = P[:, 0, :3], P[:, 2, :3] / np.linalg.norm(P[:, 2, :3], axis=1, keepdims=True)
    along = np.einsum("ni,ni->n", m0, m2)
    return np.sqrt(np.einsum("ni,ni->n", m0, m0) - along**2)


def depth(P: np.ndarray, X: np.ndarray) -> np.ndarray:
    """(N, 3, 4), (..., N, 3) -> (..., N): each point's distance in front of its camera."""
    n = np.linalg.norm(P[:, 2, :3], axis=1)
    return (np.einsum("ni,...ni->...n", P[:, 2, :3], X) + P[:, 2, 3]) / n


def ball_track(rows: list[dict]) -> Track:
    """One ball per frame whose camera is trusted: the highest-scoring detection at SCORE_MIN or
    above (as tracks and the scorers choose it)."""
    keep = []
    for i, r in enumerate(rows):
        cam = r["camera"]
        if not cam.get("ok") or cam.get("P") is None:
            continue
        cands = [(b["score"], j) for j, b in enumerate(r["ball"]) if b["score"] >= SCORE_MIN]
        if not cands:
            continue
        _, j = max(cands)
        x0, y0, x1, y1 = r["ball"][j]["bbox"]
        keep.append((i, j, r["t"], ((x0 + x1) / 2, (y0 + y1) / 2), cam["P"], min(x1 - x0, y1 - y0)))
    if not keep:
        return Track(np.zeros(0, int), np.zeros(0, int), np.zeros(0), np.zeros((0, 2)), np.zeros((0, 3, 4)),
                     np.zeros(0))
    i, j, t, uv, P, size = zip(*keep, strict=True)
    return Track(np.array(i), np.array(j), np.array(t, float), np.array(uv, float), np.array(P, float),
                 np.array(size, float))


def project(P: np.ndarray, X: np.ndarray) -> np.ndarray:
    """(N, 3, 4) cameras, (..., N, 3) points -> (..., N, 2) pixels; a point behind its camera is
    sent far off so it never fits."""
    h = np.einsum("nij,...nj->...ni", P[:, :, :3], X) + P[:, :, 3]
    w = h[..., 2:3]
    out = h[..., :2] / np.where(np.abs(w) < 1e-9, 1e-9, w)
    return np.where(w > 0, out, 1e6)


def on_plane(P: np.ndarray, uv: np.ndarray, z: float) -> np.ndarray:
    """(N, 3, 4), (N, 2) -> (N, 2): where each pixel's ray meets the plane at height z."""
    H = np.stack([P[:, :, 0], P[:, :, 1], P[:, :, 2] * z + P[:, :, 3]], axis=2)
    g = np.linalg.solve(H, np.c_[uv, np.ones(len(uv))][:, :, None])[:, :, 0]
    return g[:, :2] / g[:, 2:3]


# ---------------------------------------------------------------------------------------------
# The two models: unknowns -> the centre's place at each time (times from the piece's first frame)


def flight_paths(p: np.ndarray, times: np.ndarray, k: float) -> np.ndarray:
    """(B, 6) starts (x, y, z, vx, vy, vz) -> (B, N, 3) centres at `times` (ascending, >= 0),
    integrating r'' = g - k |r'| r' by RK4."""
    def f(s):
        v = s[:, 3:]
        a = -k * np.linalg.norm(v, axis=1, keepdims=True) * v
        a[:, 2] -= GRAVITY
        return np.concatenate([v, a], axis=1)

    s, now = np.array(p, float), 0.0
    out = np.empty((len(s), len(times), 3))
    for n, tn in enumerate(times):
        while tn - now > 1e-9:
            h = min(MAX_STEP_S, tn - now)
            k1 = f(s)
            k2 = f(s + h / 2 * k1)
            k3 = f(s + h / 2 * k2)
            k4 = f(s + h * k3)
            s = s + h / 6 * (k1 + 2 * k2 + 2 * k3 + k4)
            now += h
        out[:, n] = s[:, :3]
    return out


def ground_paths(p: np.ndarray, times: np.ndarray) -> np.ndarray:
    """(B, 5) starts (x, y, vx, vy, decel) -> (B, N, 3): a straight roll at a steady deceleration
    (its size: a rolling ball only slows) along its direction, at rest once stopped; the centre
    one radius up."""
    p = np.asarray(p, float)
    v = p[:, 2:4]
    speed = np.linalg.norm(v, axis=1)
    a = np.abs(p[:, 4])
    stop = np.where(a > 0, speed / np.maximum(a, 1e-12), np.inf)
    tau = np.minimum(times[None, :], stop[:, None])  # (B, N)
    unit = v / np.maximum(speed, 1e-12)[:, None]
    along = speed[:, None] * tau - 0.5 * a[:, None] * tau**2
    xy = p[:, None, :2] + unit[:, None, :] * along[:, :, None]
    return np.concatenate([xy, np.full(xy.shape[:2] + (1,), BALL_CENTRE_Z)], axis=2)


@dataclass
class Fit:
    kind: str  # "ground" or "flight"
    p: np.ndarray
    t0: float
    sse: float  # squared pixel residuals of the frames used, plus the soft terms (pixel^2 units)
    resid: np.ndarray  # (N,) pixel distance per frame of the window
    centres: np.ndarray  # (N, 3)
    times: np.ndarray  # (N,) from the window's first frame
    k: float
    residuals: object  # the fitted function: (B, n) parameters -> (B, m) residuals, noise units
    size_sse: float | None = None  # a flight's box sizes against its depth (size_sse), pixel^2 units
    size_sse_ground: float | None = None  # the same at observe.py's ground place


def centre_se(f: Fit, noise_px: float) -> np.ndarray:
    """(N,) standard error (m) of the fitted centre's place on the pitch (x and y) at each frame:
    the parameters' covariance noise^2 (J^T J)^-1, carried to each centre by its own Jacobian."""
    n = len(f.p)
    batch = np.vstack([f.p, f.p + FD_STEP * np.eye(n)])
    rs = f.residuals(batch)
    J = (rs[1:] - rs[0]).T / FD_STEP
    cov = noise_px**2 * np.linalg.pinv(J.T @ J)
    paths = _paths(f.kind, batch, f.times, f.k)[:, :, :2]
    G = (paths[1:] - paths[0]).transpose(1, 2, 0) / FD_STEP  # (N, 2, n)
    return np.sqrt(np.einsum("nij,jk,nik->n", G, cov, G))


def _paths(kind: str, p: np.ndarray, times: np.ndarray, k: float) -> np.ndarray:
    return flight_paths(p, times, k) if kind == "flight" else ground_paths(p, times)


def _lm(residuals, p0: np.ndarray) -> np.ndarray:
    """Levenberg-Marquardt: `residuals((B, n) parameters) -> (B, m)`, minimised in its sum of
    squares, with a forward-difference Jacobian."""
    n = len(p0)
    p, lam = np.array(p0, float), 1e-3
    r0 = residuals(p[None])[0]
    c0 = float(r0 @ r0)
    for _ in range(LM_ITERS):
        rs = residuals(np.vstack([p, p + FD_STEP * np.eye(n)]))
        J = (rs[1:] - rs[0]).T / FD_STEP
        A, b = J.T @ J, J.T @ rs[0]
        c_prev = c0
        for _ in range(8):
            q = p + np.linalg.solve(A + lam * (np.diag(np.diag(A)) + 1e-9 * np.eye(n)), -b)
            rq = residuals(q[None])[0]
            cq = float(rq @ rq)
            if cq < c0:
                p, c0, lam = q, cq, max(lam / 3, 1e-7)
                break
            lam *= 4
        if c_prev - c0 <= 1e-6 * max(c_prev, 1e-12):
            break
    return p


def _start_flight(times: np.ndarray, P: np.ndarray, uv: np.ndarray, use: np.ndarray) -> np.ndarray:
    """A drag-free flight through the rays, in closed form: with r = r0 + v0 t + g t^2/2 each
    pixel's two projective equations are linear in (r0, v0)."""
    rows, rhs = [], []
    g = np.array([0.0, 0.0, -GRAVITY])
    for i in np.flatnonzero(use):
        for c in (0, 1):
            a = P[i, c] - uv[i, c] * P[i, 2]
            scale = 1.0 / max(np.linalg.norm(a[:3]), 1e-12)
            rows.append(np.r_[a[:3], a[:3] * times[i]] * scale)
            rhs.append(-(a[:3] @ (0.5 * g * times[i] ** 2) + a[3]) * scale)
    sol, *_ = np.linalg.lstsq(np.array(rows), np.array(rhs), rcond=None)
    return sol


def _start_ground(times: np.ndarray, P: np.ndarray, uv: np.ndarray, use: np.ndarray) -> np.ndarray:
    """A steady roll through the ball's places on the ground (observe.py's), by least squares."""
    xy = on_plane(P[use], uv[use], BALL_CENTRE_Z)
    A = np.c_[np.ones(use.sum()), times[use]]
    coef, *_ = np.linalg.lstsq(A, xy, rcond=None)
    return np.r_[coef[0], coef[1], 0.0]


def fit(kind: str, tr: Track, lo: int, hi: int, use: np.ndarray, k: float = DRAG_K,
        start: np.ndarray | None = None, anchor: np.ndarray | None = None,
        noise_px: float = NOISE_PX) -> Fit:
    """Fit one model to frames lo..hi-1 of the track (those in `use`, a mask over the window),
    with the soft terms: no centre under the ground, and the first frame near `anchor` if given.
    A flight fit also records how well the ball's box size agrees with its depth and with the
    ground place's (size_sse, size_sse_ground); the size does not move the fit, because over a long
    flight gravity pins the depth better than a 3% size does."""
    times = tr.t[lo:hi] - tr.t[lo]
    P, uv = tr.P[lo:hi], tr.uv[lo:hi]

    def residuals(ps):
        paths = _paths(kind, ps, times, k)
        parts = [(project(P, paths) - uv)[:, use, :].reshape(len(ps), -1)]
        parts.append(np.minimum(paths[:, :, 2] - BALL_CENTRE_Z, 0.0) * (noise_px / GROUND_SD_M))
        if anchor is not None:
            parts.append((paths[:, 0, :] - anchor) * (noise_px / ANCHOR_SD_M))
        return np.concatenate(parts, axis=1)

    if start is not None:
        starts = [start]
    elif kind == "ground":
        starts = [_start_ground(times, P, uv, use)]
    else:  # the closed form can be far off on a few frames; a ground roll is the other start
        g = _start_ground(times, P, uv, use)
        starts = [_start_flight(times, P, uv, use), np.r_[g[:2], BALL_CENTRE_Z, g[2:4], 0.0]]
    best = None
    for s in starts:
        q = _lm(residuals, s)
        rq = residuals(q[None])[0]
        if best is None or rq @ rq < best[1] @ best[1]:
            best = (q, rq)
    p, r = best
    centres = _paths(kind, p[None], times, k)[0]
    resid = np.linalg.norm(project(P, centres) - uv, axis=1)
    fitted = Fit(kind, p, float(tr.t[lo]), float(r @ r), resid, centres, times, k, residuals)
    if kind == "flight" and tr.size is not None:
        ground = np.c_[on_plane(P, uv, BALL_CENTRE_Z), np.full(len(P), BALL_CENTRE_Z)]
        fitted.size_sse = size_sse(tr.size[lo:hi], P, centres, use, noise_px)
        fitted.size_sse_ground = size_sse(tr.size[lo:hi], P, ground, use, noise_px)
    return fitted


def size_sse(size: np.ndarray, P: np.ndarray, X: np.ndarray, use: np.ndarray, noise_px: float) -> float:
    """Sum over the used frames with a box of ((log(box / BALL_D_M's size at X's depth) - bias) /
    SIZE_SD_LOG)^2, each capped at SIZE_CAP_SIGMA and put in the pixel error's units (noise_px^2)."""
    m = use & (size > 0)
    if not m.any():
        return 0.0
    d = np.maximum(depth(P[m], X[m]), 1e-3)
    r = (np.log(size[m] / (focal_px(P[m]) * BALL_D_M / d)) - SIZE_BIAS_LOG) / SIZE_SD_LOG
    return float(((np.clip(r, -SIZE_CAP_SIGMA, SIZE_CAP_SIGMA) * noise_px) ** 2).sum())


# ---------------------------------------------------------------------------------------------
# Segments


@dataclass
class Piece:
    lo: int  # first track index
    hi: int  # one past the last
    use: np.ndarray  # (hi - lo,) frames fitted (stray detections left out)
    ground: Fit | None
    flight: Fit | None
    anchor: np.ndarray | None  # where the last piece left the ball, if it ended just before
    noise_px: float

    @property
    def in_flight(self) -> bool:
        f, g = self.flight, self.ground
        if f is None or not _physical(f):
            return False
        m = int(self.use.sum())
        # The box size must not favour the ground place by more than one unknown is worth (BIC).
        if f.size_sse is not None and (f.size_sse - f.size_sse_ground) / self.noise_px**2 > math.log(m):
            return False
        if g is None:
            return True
        return (g.sse - f.sse) / self.noise_px**2 > math.log(2 * m)

    @property
    def best(self) -> Fit | None:
        """The flight if the piece is in flight, else the ground roll; None when only a flight fitted
        the pixels and the ball's size speaks against it (its frames are then left as observed)."""
        return self.flight if self.in_flight else self.ground


def _physical(f: Fit) -> bool:
    """Never far under the ground, and for a flight no faster at its start than any football is
    struck (a falling ball gains a few m/s at most over a flight, far below the bound's margin)."""
    if f.centres[:, 2].min() < BALL_CENTRE_Z - Z_TOL_M:
        return False
    return f.kind != "flight" or bool(np.linalg.norm(f.p[3:6]) <= MAX_LAUNCH_MPS)


def _fits(f: Fit, use: np.ndarray, gate: float) -> bool:
    return bool((f.resid[use] <= gate).all()) and (f.kind == "ground" or _physical(f))


def _fit_both(tr, lo, hi, use, k, noise_px, anchor, prev: Piece | None, retry: bool = False):
    """Both models on the window, None for one that does not fit. A model that no longer fitted
    the piece before it grew is tried again, from a cold start, only with `retry` (when the other
    one has failed too): more frames only add to a least-squares fit's error, but a fit on a few
    frames can miss its best valley."""
    gate = GATE_SIGMA * noise_px
    out = []
    for kind in ("ground", "flight"):
        last = None if prev is None else (prev.ground if kind == "ground" else prev.flight)
        if prev is not None and last is None and not (retry and hi - lo <= RETRY_MAX_FRAMES):
            out.append(None)
            continue
        f = fit(kind, tr, lo, hi, use, k, None if last is None else last.p, anchor, noise_px)
        if not _fits(f, use, gate) and last is not None:  # a warm start can sit in a wrong valley
            f2 = fit(kind, tr, lo, hi, use, k, None, anchor, noise_px)
            f = f2 if f2.sse < f.sse else f
        out.append(f if _fits(f, use, gate) else None)
    return out


def _anchor(tr: Track, last: Piece | None, lo: int, k: float) -> np.ndarray | None:
    """Where the last piece's model puts the ball at frame lo, if that piece ended just before;
    never under the ground (a bounce happens between the two frames)."""
    if last is None or last.best is None or tr.t[lo] - tr.t[last.hi - 1] > ANCHOR_MAX_S:
        return None
    best = last.best
    at = _paths(best.kind, best.p[None], np.array([tr.t[lo] - best.t0]), k)[0, 0]
    return np.r_[at[:2], max(at[2], BALL_CENTRE_Z)]


def segment(tr: Track, k: float = DRAG_K, noise_px: float | None = None) -> list[Piece]:
    """Cut the track into ground and flight pieces (module docstring). The frame that does not
    fit a piece starts the next one."""
    sigma = NOISE_PX if noise_px is None else noise_px
    pieces: list[Piece] = []
    n, lo = len(tr), 0
    while lo + MIN_FRAMES <= n:
        hi = lo + MIN_FRAMES
        if np.any(np.diff(tr.t[lo:hi]) > MAX_GAP_S):
            lo += 1
            continue
        use = np.ones(hi - lo, bool)
        anchor = _anchor(tr, pieces[-1] if pieces else None, lo, k)
        g, f = _fit_both(tr, lo, hi, use, k, sigma, anchor, None)
        if g is None and f is None:
            lo += 1
            continue
        piece = Piece(lo, hi, use, g, f, anchor, sigma)
        while hi < n and tr.t[hi] - tr.t[hi - 1] <= MAX_GAP_S:
            grown = _grow(tr, piece, hi, k)
            if grown is None:
                break
            piece = grown
            hi = piece.hi
        pieces.append(piece)
        lo = piece.hi
    return pieces


def _grow(tr: Track, piece: Piece, hi: int, k: float) -> Piece | None:
    """The piece with frame hi added; or with hi left out as a stray detection and hi+1 added;
    None when neither fits."""
    a, s = piece.anchor, piece.noise_px
    use = np.r_[piece.use, True]
    for retry in (False, True):
        g, f = _fit_both(tr, piece.lo, hi + 1, use, k, s, a, piece, retry)
        if g or f:
            return Piece(piece.lo, hi + 1, use, g, f, a, s)
    if hi + 1 < len(tr) and tr.t[hi + 1] - tr.t[hi - 1] <= MAX_GAP_S:
        use = np.r_[piece.use, False, True]
        g, f = _fit_both(tr, piece.lo, hi + 2, use, k, s, a, piece, True)
        if g or f:
            return Piece(piece.lo, hi + 2, use, g, f, a, s)
    return None


# ---------------------------------------------------------------------------------------------
# Output


def heights(rows: list[dict], k: float = DRAG_K, noise_px: float | None = None) -> list[dict]:
    """A copy of the observation rows in which the chosen ball of every frame of a flight piece is
    placed at its fitted centre, where that place's standard error is at most MAX_SE_M: `x`, `y`,
    `z` (centre height, m), `se` (m) and `flight` (the piece's number). Every other chosen ball
    gets `z` one radius up and `flight` null. Frames left out of a piece's fit as stray detections
    are not moved."""
    sigma = NOISE_PX if noise_px is None else noise_px
    out = copy.deepcopy(rows)
    tr = ball_track(rows)
    for n in range(len(tr)):
        b = out[tr.rows[n]]["ball"][tr.balls[n]]
        b["z"], b["flight"] = BALL_CENTRE_Z, None
    for num, piece in enumerate(segment(tr, k, sigma)):
        if not piece.in_flight:
            continue
        se = centre_se(piece.flight, sigma)
        for w in np.flatnonzero(piece.use & (se <= MAX_SE_M)):
            n = piece.lo + w
            b = out[tr.rows[n]]["ball"][tr.balls[n]]
            b["x"], b["y"], b["z"] = (round(float(v), 3) for v in piece.flight.centres[w])
            b["se"], b["flight"] = round(float(se[w]), 3), num
    return out


# ---------------------------------------------------------------------------------------------
# Deriving the constants on validation clips: pixel residuals only


def derive_noise(tracks: list[Track], k: float = DRAG_K, rounds: int = 3) -> float:
    """NOISE_PX from the residuals of the pieces themselves, iterated from the provisional value:
    for a 2D normal the median pixel distance is sigma * sqrt(2 ln 2). Residuals of a fit are a
    little smaller than the noise (the fit absorbs some); the ratio sqrt(n / (n - p)) corrects it."""
    sigma = NOISE_PX
    for _ in range(rounds):
        scaled = []
        for tr in tracks:
            for piece in segment(tr, k, sigma):
                f, m = piece.best, int(piece.use.sum())
                if f is None:
                    continue
                dof = 2 * m - len(f.p)
                if dof > 0:
                    scaled += list(f.resid[piece.use] * math.sqrt(2 * m / dof))
        if not scaled:
            break
        sigma = float(np.median(scaled)) / math.sqrt(2 * math.log(2))
    return sigma


def derive_size(tracks: list[Track], k: float = DRAG_K, noise_px: float = NOISE_PX,
                min_frames: int = 10) -> dict:
    """SIZE_BIAS_LOG and SIZE_SD_LOG: log(box's shorter side / BALL_D_M's size at the fitted depth)
    over every frame of the ground pieces of at least min_frames frames, the pieces found from the
    pixels alone (no size term, so the size does not pick the frames it is measured on). The spread
    is 1.4826 * the median absolute deviation, robust to a half-hidden ball."""
    vals = []
    for tr in tracks:
        bare = Track(tr.rows, tr.balls, tr.t, tr.uv, tr.P)
        for piece in segment(bare, k, noise_px):
            if piece.in_flight or piece.use.sum() < min_frames:
                continue
            idx = piece.lo + np.flatnonzero(piece.use)
            P = tr.P[idx]
            d = depth(P, piece.ground.centres[piece.use])
            vals += list(np.log(tr.size[idx] / (focal_px(P) * BALL_D_M / d)))
    v = np.array(vals)
    if not len(v):
        return {"frames": 0}
    med = float(np.median(v))
    sd = 1.4826 * float(np.median(np.abs(v - med)))
    return {"frames": len(v), "bias_log": round(med, 4), "sd_log": round(sd, 4),
            "beyond_3sd": round(float(np.mean(np.abs(v - med) > 3 * sd)), 4)}


def derive_drag(tracks: list[Track], ks, noise_px: float, min_frames: int = 10, rounds: int = 2) -> dict:
    """K by pixel error: the flight pieces of at least min_frames frames, each refitted at every K
    in `ks`; the pooled squared error per K, and the K at its minimum (a parabola through the
    lowest three). The pieces are found with the provisional K first, then again with the K just
    found. The error sum is a chi-square in noise units, so K's standard error is where it has
    risen by one: sqrt(noise^2 / a) for the parabola's a."""
    k, se, ks = DRAG_K, None, [float(x) for x in ks]
    flights, sse = [], [0.0] * len(ks)
    for _ in range(rounds):
        flights = []
        for tr in tracks:
            flights += [(tr, p) for p in segment(tr, k, noise_px)
                        if p.in_flight and p.use.sum() >= min_frames]
        if not flights:
            break
        sse = [sum(fit("flight", tr, p.lo, p.hi, p.use, kk, noise_px=noise_px).sse for tr, p in flights)
               for kk in ks]
        i = int(np.argmin(sse))
        k, se = ks[i], None
        if 0 < i < len(ks) - 1:
            a, b, _ = np.polyfit(np.array(ks[i - 1:i + 2]), np.array(sse[i - 1:i + 2]), 2)
            if a > 0:
                k, se = float(-b / (2 * a)), math.sqrt(noise_px**2 / a)
    per_cd = 0.43 / (0.5 * 1.2 * math.pi * 0.11**2)  # Cd per unit K (Law 2 ball, air 1.2 kg/m^3)
    return {"flights": len(flights), "frames": int(sum(p.use.sum() for _, p in flights)),
            "ks": ks, "sse_px2": [round(s, 2) for s in sse], "k": round(k, 5),
            "k_se": None if se is None else round(se, 5), "cd": round(k * per_cd, 3),
            "cd_se": None if se is None else round(se * per_cd, 3)}


def _seed(path: Path) -> int | None:
    m = re.search(r"seed(\d+)", path.name)
    return int(m.group(1)) if m else None


def _read(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Fit the ball's flight and give it a height.")
    ap.add_argument("observations", type=Path, nargs="+")
    ap.add_argument("--out", type=Path, help="corrected observations (one input)")
    ap.add_argument("--derive", action="store_true", help="derive NOISE_PX and DRAG_K on these clips")
    ap.add_argument("--report", type=Path, help="where --derive writes its result")
    a = ap.parse_args(argv)
    if a.derive:
        test = [str(p) for p in a.observations if (_seed(p) or 0) >= RESERVED_FROM]
        if test:
            raise SystemExit(f"refused: evaluation seeds are never used to set constants: {test}")
        tracks = [ball_track(_read(p)) for p in a.observations]
        bare = [Track(t.rows, t.balls, t.t, t.uv, t.P) for t in tracks]  # pixels only, as derived
        sigma = derive_noise(bare)
        drag = derive_drag(bare, np.linspace(0.0, 0.03, 13), sigma)
        report = {"clips": [p.name for p in a.observations], "noise_px": round(sigma, 3), "drag": drag,
                  "size": derive_size(tracks, noise_px=sigma)}
        if a.report:
            a.report.write_text(json.dumps(report, indent=1) + "\n", encoding="utf-8")
        print(json.dumps(report))
        return
    if a.out is None or len(a.observations) != 1:
        ap.error("give one observations file and --out")
    rows = heights(_read(a.observations[0]))
    with open(a.out, "w", encoding="utf-8", newline="\n") as f:
        for r in rows:
            f.write(json.dumps(r, separators=(",", ":")) + "\n")
    n_air = sum(1 for r in rows for b in r["ball"] if b.get("flight") is not None)
    print(json.dumps({"out": str(a.out), "frames": len(rows), "ball_in_flight_frames": n_air}))


if __name__ == "__main__":
    main()
