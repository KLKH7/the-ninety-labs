"""Pinhole broadcast camera and the director that points it.

World coordinates are pitch metres: x 0..105 along the pitch, y 0..68 from the near touchline,
z up. Camera coordinates follow OpenCV: x right, y down, z forward. Pixel coordinates have their
origin at the top-left corner of the image, so pixel (i, j) covers [i, i+1] x [j, j+1]; the
principal point is the image centre.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass

from ninety.render.params import CameraParams

Vec = tuple[float, float, float]


def _sub(a: Vec, b: Vec) -> Vec:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _cross(a: Vec, b: Vec) -> Vec:
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _norm(a: Vec) -> Vec:
    n = math.sqrt(a[0] ** 2 + a[1] ** 2 + a[2] ** 2)
    return (a[0] / n, a[1] / n, a[2] / n)


def _dot(a: Vec, b: Vec) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


@dataclass(frozen=True)
class Camera:
    position: Vec
    target: Vec
    fov_v_deg: float
    width: int
    height: int

    @property
    def focal_px(self) -> float:
        return (self.height / 2) / math.tan(math.radians(self.fov_v_deg) / 2)

    @property
    def K(self) -> list[list[float]]:
        f = self.focal_px
        return [[f, 0.0, self.width / 2], [0.0, f, self.height / 2], [0.0, 0.0, 1.0]]

    @property
    def R(self) -> list[list[float]]:
        """World-to-camera rotation; rows are the camera's right, down and forward axes."""
        fwd = _norm(_sub(self.target, self.position))
        right = _norm(_cross(fwd, (0.0, 0.0, 1.0)))
        down = _cross(fwd, right)
        return [list(right), list(down), list(fwd)]

    @property
    def t(self) -> list[float]:
        return [-_dot(tuple(row), self.position) for row in self.R]  # type: ignore[arg-type]

    @property
    def P(self) -> list[list[float]]:
        """3x4 projection matrix K [R | t]."""
        K, R, t = self.K, self.R, self.t
        Rt = [R[i] + [t[i]] for i in range(3)]
        return [[sum(K[i][k] * Rt[k][j] for k in range(3)) for j in range(4)] for i in range(3)]

    def to_camera(self, X: Vec) -> Vec:
        R, t = self.R, self.t
        return tuple(_dot(tuple(R[i]), X) + t[i] for i in range(3))  # type: ignore[return-value]

    def project(self, X: Vec) -> tuple[float, float] | None:
        """Pixel position of a world point, or None if it is behind the camera."""
        c = self.to_camera(X)
        if c[2] <= 1e-6:
            return None
        f = self.focal_px
        return (f * c[0] / c[2] + self.width / 2, f * c[1] / c[2] + self.height / 2)

    def depth(self, X: Vec) -> float:
        return self.to_camera(X)[2]

    def to_dict(self) -> dict:
        r = lambda m: [[round(v, 6) for v in row] for row in m]  # noqa: E731
        return {
            "width": self.width,
            "height": self.height,
            "fov_v_deg": round(self.fov_v_deg, 6),
            "position": [round(v, 4) for v in self.position],
            "K": r(self.K),
            "R": r(self.R),
            "t": [round(v, 6) for v in self.t],
            "P": r(self.P),
        }


def project_with(P: list[list[float]], X: Vec) -> tuple[float, float] | None:
    """Project with a saved 3x4 matrix, the way any consumer of frames.jsonl would."""
    h = [P[i][0] * X[0] + P[i][1] * X[1] + P[i][2] * X[2] + P[i][3] for i in range(3)]
    if h[2] <= 1e-9:
        return None
    return (h[0] / h[2], h[1] / h[2])


MAX_PAN_MPS = 22.0  # fastest the aim point moves across the ground


def in_box(x: float, y: float) -> bool:
    """True when (x, y) is inside either penalty area."""
    return 13.84 <= y <= 54.16 and (x <= 16.5 or x >= 88.5)


class Director:
    """Main broadcast camera: fixed gantry position, pans and zooms to follow the ball with lag."""

    def __init__(self, params: CameraParams, width: int, height: int, fps: int, seed: int):
        self.p = params
        self.width, self.height, self.dt = width, height, 1.0 / fps
        self.position: Vec = (52.5 + params.offset_x_m, -params.back_m, params.height_m)
        self.rng = random.Random(f"camera-{seed}")
        self.aim: list[float] | None = None
        self.half_width = params.half_width_m
        self.prev_ball: tuple[float, float] | None = None
        self.shake_phase = (self.rng.uniform(0, 6.28), self.rng.uniform(0, 6.28))
        self.t = 0.0

    def _goal(self, bx: float, by: float, vx: float, vy: float) -> tuple[float, float, float]:
        ax = bx + vx * self.p.lead_s
        ay = by + vy * self.p.lead_s
        ay = 34 + (ay - 34) * 0.75  # broadcasters rarely aim right at a touchline
        ax = min(max(ax, 8.0), 97.0)
        ay = min(max(ay, 12.0), 60.0)
        hw = self.p.box_half_width_m if in_box(bx, by) else self.p.half_width_m
        return ax, ay, hw

    def step(self, ball_x: float, ball_y: float) -> Camera:
        if self.prev_ball is None:
            vx = vy = 0.0
        else:
            vx = (ball_x - self.prev_ball[0]) / self.dt
            vy = (ball_y - self.prev_ball[1]) / self.dt
        self.prev_ball = (ball_x, ball_y)
        gx, gy, ghw = self._goal(ball_x, ball_y, vx, vy)
        if self.aim is None:
            self.aim = [gx, gy]
            self.half_width = ghw
        else:
            a = 1 - math.exp(-self.dt / self.p.pan_lag_s)
            z = 1 - math.exp(-self.dt / (self.p.pan_lag_s * 2.5))
            sx, sy = (gx - self.aim[0]) * a, (gy - self.aim[1]) * a
            step = math.hypot(sx, sy)
            cap = MAX_PAN_MPS * self.dt  # an operator cannot whip the camera across the pitch
            if step > cap:
                sx, sy = sx * cap / step, sy * cap / step
            self.aim[0] += sx
            self.aim[1] += sy
            self.half_width += (ghw - self.half_width) * z
        self.t += self.dt
        sx = self.p.shake_m * math.sin(2 * math.pi * 1.3 * self.t + self.shake_phase[0])
        sy = self.p.shake_m * math.sin(2 * math.pi * 0.9 * self.t + self.shake_phase[1])
        target = (self.aim[0] + sx, self.aim[1] + sy, 0.0)
        dist = math.dist(self.position, target)
        hfov = 2 * math.atan(self.half_width / dist)
        vfov = 2 * math.atan(math.tan(hfov / 2) * self.height / self.width)
        return Camera(self.position, target, math.degrees(vfov), self.width, self.height)


def blur_vector(prev: Camera | None, cur: Camera, shutter: float) -> tuple[float, float]:
    """Image-space motion of the scene during the exposure, from the camera pan and zoom.

    The world point at the image centre now is projected through last frame's camera; the
    displacement over one frame interval, times the shutter fraction, is the blur streak.
    """
    if prev is None or shutter <= 0:
        return (0.0, 0.0)
    p = prev.project(cur.target)
    if p is None:
        return (0.0, 0.0)
    dx, dy = cur.width / 2 - p[0], cur.height / 2 - p[1]
    return (round(dx * shutter, 3), round(dy * shutter, 3))
