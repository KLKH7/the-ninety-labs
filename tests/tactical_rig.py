"""A stand-in for the fixed tactical camera's two lenses, for tests: both at (52.5, -32, 28) m,
1920 x 1080, 60 degrees across, one aimed at each half (docs: the tactical camera plan)."""

from __future__ import annotations

import math

import numpy as np

W, H = 1920, 1080
EYE = np.array([52.5, -32.0, 28.0])
F = (W / 2) / math.tan(math.radians(30))


def lens(target_x: float, target_y: float = 34.0) -> np.ndarray:
    """P = K [R | -R C] for a lens at EYE looking at (target_x, target_y, 0), level horizon."""
    fwd = np.array([target_x, target_y, 0.0]) - EYE
    fwd /= np.linalg.norm(fwd)
    right = np.cross(fwd, [0.0, 0.0, 1.0])
    right /= np.linalg.norm(right)
    down = np.cross(fwd, right)
    R = np.vstack([right, down, fwd])
    K = np.array([[F, 0, W / 2], [0, F, H / 2], [0, 0, 1]])
    return K @ np.c_[R, -R @ EYE]


LEFT, RIGHT = lens(27.0), lens(78.0)


def project(P: np.ndarray, x: float, y: float, z: float = 0.0) -> tuple[float, float]:
    p = P @ np.array([x, y, z, 1.0])
    return float(p[0] / p[2]), float(p[1] / p[2])


def player_box(P: np.ndarray, x: float, y: float, height: float = 1.8) -> list[float]:
    """The box of an upright player standing at (x, y): feet at the bottom centre."""
    u, v = project(P, x, y)
    _, vh = project(P, x, y, height)
    h = v - vh
    return [u - 0.2 * h, vh, u + 0.2 * h, v]


def ball_box(P: np.ndarray, x: float, y: float, z: float = 0.11) -> list[float]:
    u, v = project(P, x, y, z)
    _, vt = project(P, x, y, z + 0.22)
    r = (v - vt) / 2
    return [u - r, v - r, u + r, v + r]
