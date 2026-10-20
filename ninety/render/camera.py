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
# An operator eases a pan in and out instead of starting and stopping it dead (design, after the
# critic's review of 0.5.0: pans went from still to full speed in one frame). The aim point gathers
# speed at most this fast, so a full-speed pan takes about half a second to build up.
PAN_ACCEL_MPS2 = 40.0


def in_box(x: float, y: float) -> bool:
    """True when (x, y) is inside either penalty area."""
    return 13.84 <= y <= 54.16 and (x <= 16.5 or x >= 88.5)


CUT_HOLD_S = 4.0  # a cut stays put this long; shorter than this reads as a flicker
GANTRY_LINE_DEG = 23.0  # handbook: 22-24° from the gantry down to the near touchline
GANTRY_HALF_M = 14.5  # longer than the widest sampled lens, so a player still has a body from here
# Play on the far side is foreshortened, so the same width of ground shows more of the stand above
# it: the lens closes up as the play goes away, down to this share of its width at the far corners
# (design; 0.7 against 1.0 and 0.6 on seeds 7, 21 and 42, test_render_camera uses other seeds).
ZOOM_MIN = 0.7
TIGHT_ACTIONS = ("throw", "thigh", "chest", "head", "hands")
NET_SETTLE_S = 2.6  # the mesh is back to rest by here; the angle itself holds CUT_HOLD_S


# How a broadcast frames live play (design, after the Coordinator's review of 0.4.1 and broadcast
# practice): the main camera keeps the play near the middle of the picture with the pitch filling
# most of it, the stands a band across the top. A frame is well framed when the pitch (Law 1) covers
# at least PITCH_SHARE_MIN of the picture and the ball is inside the CENTRAL box (shares of width
# and height: left, right, top, bottom).
PITCH_SHARE_MIN = 0.60
CENTRAL = (0.2, 0.8, 0.15, 0.85)


def pitch_share(cam: Camera, step: int = 40) -> float:
    """The share of the picture that is the pitch (105 by 68 m on the ground), from a grid of rays
    through the picture, `step` pixels apart, to the ground."""
    right, down, fwd = cam.R
    f = cam.focal_px
    hit = total = 0
    for v in range(step // 2, cam.height, step):
        for u in range(step // 2, cam.width, step):
            a, b = (u - cam.width / 2) / f, (v - cam.height / 2) / f
            d = [fwd[i] + a * right[i] + b * down[i] for i in range(3)]
            total += 1
            if d[2] >= -1e-9:
                continue  # above the horizon
            s = -cam.position[2] / d[2]
            x, y = cam.position[0] + s * d[0], cam.position[1] + s * d[1]
            hit += 0.0 <= x <= 105.0 and 0.0 <= y <= 68.0
    return hit / total


def well_framed(cam: Camera, ball: Vec) -> bool:
    """The pitch fills at least PITCH_SHARE_MIN of the picture and the ball is in its CENTRAL box."""
    uv = cam.project(ball)
    if uv is None:
        return False
    left, right, top, bottom = CENTRAL
    across = left * cam.width <= uv[0] <= right * cam.width
    down = top * cam.height <= uv[1] <= bottom * cam.height
    return across and down and pitch_share(cam) >= PITCH_SHARE_MIN


def gantry_height(back_m: float, sampled: float) -> float:
    """Height that looks down at the near touchline at 23°. A sample already inside 22-24°
    is kept. The draw itself is not moved, so a seed's stored height stays where it was."""
    if back_m <= 0:
        return sampled
    angle = math.degrees(math.atan2(sampled, back_m))
    if 22.0 <= angle <= 24.0:
        return sampled
    return back_m * math.tan(math.radians(GANTRY_LINE_DEG))


def net_push(age: float, speed: float, y: float, z: float, hit_y: float, hit_z: float) -> float:
    """How far one point of the net gives, in metres, straight out behind the goal line.

    The hit arrives first and the cloth further away follows. The result stays outward.
    `web/render/render.js` applies this same curve. Decor only: it never moves the ball."""
    if age < 0.0 or age > NET_SETTLE_S:
        return 0.0
    dist = math.hypot(y - hit_y, z - hit_z)
    delay = 0.035 * dist
    if age < delay:
        return 0.0
    amp = min(0.85, 0.2 + min(speed, 28.0) * 0.02)
    fall = math.exp(-(dist * dist) / 1.6)
    env = math.exp(-(age - delay) * 2.4)
    ring = 0.7 + 0.3 * (0.5 + 0.5 * math.cos(age * 15.0))
    return amp * fall * env * ring


class Director:
    """Main broadcast camera: fixed gantry position, pans and zooms to follow the ball with lag.

    The gantry is the picture the match is watched from. It aims at the play on the grass, so the
    pitch fills the picture and the stands are a band across the top, closes up as the play goes
    away (ZOOM_MIN), and eases each pan in and out (PAN_ACCEL_MPS2).

    With `cuts`, it leaves the gantry for two shots, each held at least CUT_HOLD_S: a tighter lens
    beside the gantry for a throw or an aerial touch, when that shot still holds the player and the
    ball, and, when a goal is scored, a low three-quarter beside that goal, aimed at the mouth the
    event recorded, because the engine has already put the ball back on the centre spot. Live play
    is never shown from across the pitch or from behind a goal: every camera it uses stands on the
    gantry's side, so left and right stay where the viewer has them (the 180-degree rule, as a
    broadcast keeps them; SoccerNet-v2 counts one change of shot every 9 s, replays included).
    The gantry aim keeps updating during a cut, so the return is where it would have been.
    """

    def __init__(
        self, params: CameraParams, width: int, height: int, fps: int, seed: int, cuts: bool = False
    ):
        self.p = params
        self.width, self.height, self.dt = width, height, 1.0 / fps
        self.position: Vec = (
            52.5 + params.offset_x_m,
            -params.back_m,
            gantry_height(params.back_m, params.height_m),
        )
        self.players: list[tuple[float, float, str]] = []
        self.rng = random.Random(f"camera-{seed}")
        self.aim: list[float] | None = None
        self.aim_v = [0.0, 0.0]  # how fast the aim point is moving across the ground (m/s)
        self.tight_aim: list[float] | None = None  # the tighter lens's own aim, while it is up
        self.tight_v = [0.0, 0.0]
        self.half_width = params.half_width_m
        self.prev_ball: tuple[float, float] | None = None
        self.shake_phase = (self.rng.uniform(0, 6.28), self.rng.uniform(0, 6.28))
        self.t = 0.0
        self.cuts = cuts
        self.angle = "main"
        self._cut_until = -1.0
        self._cut_kind = ""  # "", "netL", "netR" or "tight". Empty is the gantry.
        self.net: dict | None = None  # the goal the mesh and the low angle are still showing

    def cut(self) -> None:
        """The edit cuts away from a dead ball to its restart (edit.py): no pan, second angle or goal
        net is carried across the cut, and the camera frames the ball afresh where it is then."""
        self.aim = None
        self.aim_v = [0.0, 0.0]
        self.tight_aim = None
        self.prev_ball = None
        self._cut_kind = ""
        self._cut_until = -1.0
        self.net = None

    def open_on_restart(self) -> None:
        """The first frame after a cut: the picture comes back on the restart with the tighter lens
        beside the gantry, held CUT_HOLD_S, so the edit reads as a cut to another shot rather than
        the players jumping about the same one (as a broadcast returns to a set piece)."""
        self._cut_kind = "tight"
        self._cut_until = self.t + self.dt + CUT_HOLD_S  # from the restart's first frame

    def _goal(self, bx: float, by: float, vx: float, vy: float) -> tuple[float, float, float]:
        ax = bx + vx * self.p.lead_s
        ay = by + vy * self.p.lead_s
        ay = 34 + (ay - 34) * 0.75  # broadcasters rarely aim right at a touchline
        ax = min(max(ax, 8.0), 97.0)
        ay = min(max(ay, 12.0), 60.0)
        wide = min(self.p.half_width_m, GANTRY_HALF_M)
        hw = self.p.box_half_width_m if in_box(bx, by) else wide
        centre = math.dist(self.position[:2], (52.5, 34.0))
        hw *= min(1.0, max(ZOOM_MIN, centre / math.dist(self.position[:2], (ax, ay))))
        return ax, ay, hw

    def step(
        self,
        ball_x: float,
        ball_y: float,
        players: list | None = None,
        goal: tuple | None = None,
        cut_in: float | None = None,
    ) -> Camera:
        """The camera for the next frame. `cut_in` is how long until the edit's next cut, in seconds
        (None when no cut follows): no angle starts or ends that close to one, because the cut is
        itself the change of shot."""
        self.players = [(p[0], p[1], p[2]) for p in players] if players else []
        if self.prev_ball is None:
            vx = vy = 0.0
        else:
            vx = (ball_x - self.prev_ball[0]) / self.dt
            vy = (ball_y - self.prev_ball[1]) / self.dt
        self.prev_ball = (ball_x, ball_y)
        gx, gy, ghw = self._goal(ball_x, ball_y, vx, vy)
        if self.aim is None:
            self.aim = [gx, gy]
            self.aim_v = [0.0, 0.0]
            self.half_width = ghw
        else:
            self._ease(self.aim, self.aim_v, gx, gy)
            z = 1 - math.exp(-self.dt / (self.p.pan_lag_s * 2.5))
            self.half_width += (ghw - self.half_width) * z
        self.t += self.dt
        fresh_goal = False
        if goal:
            side, y, z, speed = goal
            self.net = {
                "side": side,
                "y": float(y),
                "z": float(z),
                "speed": float(speed),
                "t0": self.t,
            }
            fresh_goal = True
        sx = self.p.shake_m * math.sin(2 * math.pi * 1.3 * self.t + self.shake_phase[0])
        sy = self.p.shake_m * math.sin(2 * math.pi * 0.9 * self.t + self.shake_phase[1])
        target = (self.aim[0] + sx, self.aim[1] + sy, 0.0)
        self.angle = "main"
        want = self._better(ball_x, ball_y) if self.cuts else ""
        # The hold covers every angle, including the return to the gantry, so an action on the
        # edge of the rule cannot bounce the camera back and forth. A goal starts the low angle at
        # once, even over a hold. Near the edit's next cut nothing changes: the cut is the change.
        steady = cut_in is not None and cut_in < CUT_HOLD_S
        due = self.t >= self._cut_until - 1e-9 and want != self._cut_kind and not steady
        if (fresh_goal and self.cuts) or due:
            self._cut_kind = want
            self._cut_until = self.t + CUT_HOLD_S
        if self._cut_kind != "tight":
            self.tight_aim = None
        else:
            # The tighter lens has its own operator: framed on the ball when the shot comes up,
            # then following it, eased the same way.
            spot = (min(max(ball_x, 0.0), 105.0), min(max(ball_y, -1.0), 69.0))
            if self.tight_aim is None:
                self.tight_aim, self.tight_v = list(spot), [0.0, 0.0]
            else:
                self._ease(self.tight_aim, self.tight_v, *spot)
        if self._cut_kind:
            return self._second()
        return self._main(target)

    def _ease(self, aim: list[float], vel: list[float], gx: float, gy: float) -> None:
        """Move an aim point toward (gx, gy) like a critically damped spring, gathering and losing
        speed no faster than PAN_ACCEL_MPS2, never faster than MAX_PAN_MPS. Its stiffness, 2 over
        the sampled lag, trails a ball at a steady pace by as much as a plain lag of that time did,
        so the play stays as central as before while each pan eases in and out."""
        w = 2.0 / self.p.pan_lag_s
        ax = w * w * (gx - aim[0]) - 2 * w * vel[0]
        ay = w * w * (gy - aim[1]) - 2 * w * vel[1]
        acc = math.hypot(ax, ay)
        if acc > PAN_ACCEL_MPS2:
            ax, ay = ax * PAN_ACCEL_MPS2 / acc, ay * PAN_ACCEL_MPS2 / acc
        ux, uy = vel[0] + ax * self.dt, vel[1] + ay * self.dt
        speed = math.hypot(ux, uy)
        if speed > MAX_PAN_MPS:  # an operator cannot whip the camera across the pitch
            ux, uy = ux * MAX_PAN_MPS / speed, uy * MAX_PAN_MPS / speed
        vel[0], vel[1] = ux, uy
        aim[0] += ux * self.dt
        aim[1] += uy * self.dt

    def net_view(self) -> dict | None:
        """The hit the mesh is still showing, or None once the cloth has settled."""
        if not self.net:
            return None
        age = self.t - self.net["t0"]
        if age < 0.0 or age > NET_SETTLE_S:
            return None
        return {
            "side": 0 if self.net["side"] == "L" else 1,
            "y": round(self.net["y"], 3),
            "z": round(self.net["z"], 3),
            "speed": round(self.net["speed"], 3),
            "age": round(age, 3),
        }

    def _net_due(self) -> bool:
        return self.net is not None and self.t < self.net["t0"] + CUT_HOLD_S

    def _net_pos(self, side: str) -> Vec:
        left = side == "L"
        line = 0.0 if left else 105.0
        outward = -1.0 if left else 1.0
        # Far enough back that the whole goal reads, and off the near post so the
        # pocket is a three-quarter rather than a flat wall. On the gantry's side of the goal.
        return (line + outward * 7.6, 22.0, 3.6)

    def _better(self, bx: float, by: float) -> str:
        """The angle that frames this moment better than the gantry, or '' to stay on the gantry."""
        if self._net_due():
            return "net" + self.net["side"]
        if self._tight(bx, by):
            return "tight"
        return ""

    def _main(self, target: Vec) -> Camera:
        dist = math.dist(self.position, target)
        hfov = 2 * math.atan(self.half_width / dist)
        vfov = 2 * math.atan(math.tan(hfov / 2) * self.height / self.width)
        return Camera(self.position, target, math.degrees(vfov), self.width, self.height)

    def _framed(self, position: Vec, target: Vec, half_width: float) -> Camera:
        dist = max(math.dist(position, target), 1.0)
        hfov = 2 * math.atan(half_width / dist)
        vfov = 2 * math.atan(math.tan(hfov / 2) * self.height / self.width)
        # A cut stays a broadcast lens. Clamping does not move the aim point, so the ball stays centred.
        vfov = min(max(vfov, math.radians(8.0)), math.radians(32.0))
        return Camera(position, target, math.degrees(vfov), self.width, self.height)

    def _tight_pos(self) -> Vec:
        # Beside the gantry, same side and height. Far enough that the jump is a cut.
        return (self.position[0] + 8.0, self.position[1], self.position[2])

    def _tight(self, bx: float, by: float) -> bool:
        """A throw or an aerial touch, when a tighter lens beside the gantry still holds both."""
        actor = None
        best = 3.0
        for px, py, action in self.players:
            if action not in TIGHT_ACTIONS:
                continue
            dist = math.hypot(px - bx, py - by)
            if dist < best:
                best, actor = dist, (px, py)
        if actor is None:
            return False
        shot = self._framed(self._tight_pos(), (bx, by, 0.5), 9.0)
        ball = shot.project((bx, by, 0.3))
        feet = shot.project((actor[0], actor[1], 0.0))
        head = shot.project((actor[0], actor[1], 1.7))
        if ball is None or feet is None or head is None:
            return False
        pad = 36

        def inside(uv: tuple[float, float]) -> bool:
            return pad <= uv[0] < self.width - pad and pad <= uv[1] < self.height - pad

        return inside(ball) and inside(feet) and 0 <= head[1] < self.height

    def _net_shot(self) -> Camera:
        """Low, off the near post, aimed at the mouth the goal went in by."""
        side = "L" if self._cut_kind == "netL" else "R"
        line = 0.0 if side == "L" else 105.0
        outward = -1.0 if side == "L" else 1.0
        y = min(max(self.net["y"], 31.0), 37.0)
        z = min(max(self.net["z"], 0.4), 2.1)
        return self._framed(self._net_pos(side), (line + outward * 1.0, y, z), 7.0)

    def _second(self) -> Camera:
        if self._cut_kind in ("netL", "netR"):
            self.angle = "net"
            return self._net_shot()
        self.angle = "tight"
        return self._framed(self._tight_pos(), (self.tight_aim[0], self.tight_aim[1], 0.5), 9.0)


def blur_vector(prev: Camera | None, cur: Camera, shutter: float) -> tuple[float, float]:
    """Image-space motion of the scene during the exposure, from the camera pan and zoom.

    The world point at the image centre now is projected through last frame's camera; the
    displacement over one frame interval, times the shutter fraction, is the blur streak.
    """
    if prev is None or shutter <= 0:
        return (0.0, 0.0)
    # A cut changes the gantry. That displacement is not a pan, so it must not streak the frame.
    if math.dist(prev.position, cur.position) > 1.0:
        return (0.0, 0.0)
    p = prev.project(cur.target)
    if p is None:
        return (0.0, 0.0)
    dx, dy = cur.width / 2 - p[0], cur.height / 2 - p[1]
    return (round(dx * shutter, 3), round(dy * shutter, 3))
