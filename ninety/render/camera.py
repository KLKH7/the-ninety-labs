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


CUT_HOLD_S = 4.0  # a cut stays put this long; shorter than this reads as a flicker
BOX_LEAVE_M = 6.0  # the goal camera gives the ball back only once it is clearly out of the box
FAR_CLOSER = 0.50  # the far stand is better when it is at most half the gantry's distance to the ball
FAR_LEAVE = 0.70  # stay on that stand until it is no longer clearly closer
GANTRY_LINE_DEG = 23.0  # handbook: 22-24° from the gantry down to the near touchline
GANTRY_AIM_Z = 1.5  # a band of the far stand. Higher fills half the frame and crops the near players.
GANTRY_HALF_M = 14.5  # longer than the widest sampled lens, so a player still has a body from here
# One sideline camera, in front of the near stand (its lip is y=-46) and short of both end stands
# (they start at x=-11 and x=116). It travels with the ball. Closer than the far gantry, so a
# player is readable at 720p. Picture choices, not numbers taken from a game binary.
SIDE_BACK_M = 18.0
SIDE_HEIGHT_M = 10.5
SIDE_HALF_M = 9.0
SIDE_BOX_HALF_M = 7.0
SIDE_AIM_Z = 0.4
# y=-18 is in front of the near stand and short of both end stands (they occupy y from 2).
# The x range is wide enough that a corner flag stays inside a 720p frame.
SIDE_X_MIN, SIDE_X_MAX = 2.0, 103.0
REVERSE_Z = 12.0  # above the lower far tier; the sampled gantry height puts this lens in the sky
REVERSE_AIM_Z = 4.5  # this camera is low, so it looks up to keep the opposite bowl in the shot
REVERSE_HALF_M = 16.0  # same kind of lens as the gantry, so the far angle is not a wide overview
BLUR_CAP_PX = 12.0  # a longer streak at 720p breaks into steps
TIGHT_ACTIONS = ("throw", "thigh", "chest", "head", "hands")
NET_SETTLE_S = 2.6  # the mesh is back to rest by here; the angle itself holds CUT_HOLD_S
GOAL_LOOK_S = 1.5  # the net, before the camera leaves it
GOAL_PAN_S = 2.5  # travel to the centre spot. Look plus pan is the engine's KICKOFF_WAIT_S.


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


def box_side(x: float, y: float, margin: float = 0.0) -> str:
    """'L' or 'R' when (x, y) is in that penalty area, widened by `margin` metres. Else ''."""
    if not (13.84 - margin <= y <= 54.16 + margin):
        return ""
    if x <= 16.5 + margin:
        return "L"
    if x >= 88.5 - margin:
        return "R"
    return ""


class Director:
    """One sideline camera. It travels with the ball and stays in front of the near stand.

    Open play, the box, a throw and a corner are all this camera. It does not go behind a goal
    or into the far stand: both of those sit inside the stadium mesh. When a goal is scored, a
    low three-quarter beside that goal, aimed at the mouth the event recorded, then a pan back
    to the sideline. The engine has already put the ball on the centre spot.
    """

    def __init__(
        self, params: CameraParams, width: int, height: int, fps: int, seed: int, cuts: bool = False
    ):
        self.p = params
        self.width, self.height, self.dt = width, height, 1.0 / fps
        self.position: Vec = (52.5 + params.offset_x_m, -SIDE_BACK_M, SIDE_HEIGHT_M)
        self.players: list[tuple[float, float, str]] = []
        self.rng = random.Random(f"camera-{seed}")
        self.aim: list[float] | None = None
        self.half_width = params.half_width_m
        self.prev_ball: tuple[float, float] | None = None
        self.shake_phase = (self.rng.uniform(0, 6.28), self.rng.uniform(0, 6.28))
        self.t = 0.0
        self.cuts = cuts
        self.angle = "main"
        self._cut_until = -1.0
        self._cut_kind = ""  # "", "L", "R", "netL", "netR", "tight", or "reverse". Empty is the gantry.
        self.net: dict | None = None  # the goal the mesh and the low angle are still showing
        self._ball_v = (0.0, 0.0)

    def _goal(self, bx: float, by: float, vx: float, vy: float) -> tuple[float, float, float]:
        ax = bx + vx * self.p.lead_s
        ay = by + vy * self.p.lead_s
        ay = 34 + (ay - 34) * 0.85  # a little off the touchline, still on the ball
        ax = min(max(ax, SIDE_X_MIN), SIDE_X_MAX)
        ay = min(max(ay, 3.0), 65.0)
        hw = SIDE_BOX_HALF_M if in_box(bx, by) else SIDE_HALF_M
        return ax, ay, hw

    def step(
        self,
        ball_x: float,
        ball_y: float,
        players: list | None = None,
        goal: tuple | None = None,
    ) -> Camera:
        self.players = [(p[0], p[1], p[2]) for p in players] if players else []
        if self.prev_ball is None:
            vx = vy = 0.0
            jumped = False
        else:
            dx, dy = ball_x - self.prev_ball[0], ball_y - self.prev_ball[1]
            # A restart places the ball. The step is a cut, so it has no velocity to lead.
            jumped = math.hypot(dx, dy) > 8.0
            vx, vy = (0.0, 0.0) if jumped else (dx / self.dt, dy / self.dt)
        self._ball_v = (vx, vy)
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
        if jumped:
            self.aim = [gx, gy]
            self.half_width = ghw
        self._slide(self.aim[0], snap=jumped)
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
        if self.cuts:
            want = self._better(ball_x, ball_y, target)
            # The hold covers every angle, including the return to the gantry, so a ball
            # on the edge of the box cannot bounce the camera back and forth.
            # A goal extends the low angle even when that shot is already up. Any other
            # change waits out the hold, including the return to the gantry.
            if fresh_goal or (self.t >= self._cut_until and want != self._cut_kind):
                self._cut_kind = want
                self._cut_until = self.t + CUT_HOLD_S
            if self._cut_kind:
                return self._second(ball_x, ball_y, target)
        return self._main(target)

    def _slide(self, aim_x: float, snap: bool = False) -> None:
        """Travel along the near sideline. Never into a stand."""
        want = min(max(aim_x, SIDE_X_MIN), SIDE_X_MAX)
        if snap:
            self.position = (want, -SIDE_BACK_M, SIDE_HEIGHT_M)
            return
        cur = self.position[0]
        a = 1 - math.exp(-self.dt / max(self.p.pan_lag_s, 1e-3))
        dx = (want - cur) * a
        cap = MAX_PAN_MPS * self.dt
        if abs(dx) > cap:
            dx = math.copysign(cap, dx)
        self.position = (cur + dx, -SIDE_BACK_M, SIDE_HEIGHT_M)

    def _reverse_pos(self) -> Vec:
        # 18 m past the far touchline. A full back_m lands inside the crowd mesh.
        return (52.5 - self.p.offset_x_m, 68.0 + 18.0, REVERSE_Z)

    def _reverse_shot(self, aim: Vec) -> Camera:
        lifted = (aim[0], aim[1], aim[2] + REVERSE_AIM_Z)
        return self._framed(self._reverse_pos(), lifted, REVERSE_HALF_M)

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
        return self.net is not None and self.t < self.net["t0"] + GOAL_LOOK_S + GOAL_PAN_S

    def _net_pos(self, side: str) -> Vec:
        left = side == "L"
        line = 0.0 if left else 105.0
        outward = -1.0 if left else 1.0
        # Far enough back that the whole goal reads, and off the near post so the
        # pocket is a three-quarter rather than a flat wall.
        return (line + outward * 7.6, 22.0, 3.6)

    def _incoming(self, bx: float, by: float) -> str:
        """A shot arriving in the box. Build-up in the box stays on the high goal camera."""
        side = box_side(bx, by)
        if not side:
            return ""
        vx, _vy = self._ball_v
        pace = math.hypot(vx, _vy)
        toward = vx < -8.0 if side == "L" else vx > 8.0
        # A jump across the pitch is the director being shown a new spot, not a shot.
        if not toward or not (10.0 <= pace <= 40.0):
            return ""
        pos = self._net_pos(side)
        shot = self._framed(pos, (bx, by, 0.5), 7.0)
        uv = shot.project((bx, by, 0.4))
        if uv is None:
            return ""
        pad = 36
        if not (pad <= uv[0] < self.width - pad and pad <= uv[1] < self.height - pad):
            return ""
        return "net" + side

    def _better(self, bx: float, by: float, aim: Vec) -> str:
        """Leave the sideline only when a goal is on the net camera. The box, a throw and the
        far side stay here: the other angles sit inside the stands."""
        if self._net_due():
            return "net" + self.net["side"]
        return ""

    def _reverse_readable(self, aim: Vec, bx: float, by: float) -> bool:
        shot = self._reverse_shot(aim)
        ball = shot.project((bx, by, 0.2))
        # Seat deck of the opposite bowl. Above the frame, this angle is grass under the sky.
        deck = shot.project((52.5, -68.0, 14.0))
        if ball is None or deck is None:
            return False
        pad = 48
        u, v = ball
        du, dv = deck
        # The bowl has to sit across the frame. Off to one side, the shot is the shell and the sky.
        return (
            pad <= u < self.width - pad
            and pad <= v < self.height - pad
            and 80 <= du < self.width - 80
            and 0 <= dv < 160
        )

    def _main(self, target: Vec) -> Camera:
        # The stand sits behind the play. Aiming at the grass leaves the bowl above the frame.
        lifted = (target[0], target[1], target[2] + SIDE_AIM_Z)
        dist = math.dist(self.position, lifted)
        hfov = 2 * math.atan(self.half_width / dist)
        vfov = 2 * math.atan(math.tan(hfov / 2) * self.height / self.width)
        return Camera(self.position, lifted, math.degrees(vfov), self.width, self.height)

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

    def _net_shot(self, bx: float, by: float) -> Camera:
        """Low, off the near post. The flight is followed. After the goal, the mouth is."""
        side = "L" if self._cut_kind == "netL" else "R"
        pos = self._net_pos(side)
        if self._net_due():
            line = 0.0 if side == "L" else 105.0
            outward = -1.0 if side == "L" else 1.0
            y = min(max(self.net["y"], 31.0), 37.0)
            z = min(max(self.net["z"], 0.4), 2.1)
            target = (line + outward * 1.0, y, z)
        else:
            target = (min(max(bx, 0.0), 105.0), min(max(by, 8.0), 60.0), 0.5)
        return self._framed(pos, target, 7.0)

    def _goal_beat(self, bx: float, by: float, aim: Vec) -> Camera:
        """The net, then a pan to the gantry on the centre spot. Play is still waiting there."""
        age = self.t - self.net["t0"]
        net = self._net_shot(bx, by)
        if age <= GOAL_LOOK_S:
            self.angle = "net"
            return net
        self.angle = "kickoff"
        u = min(1.0, (age - GOAL_LOOK_S) / GOAL_PAN_S)
        s = u * u * (3.0 - 2.0 * u)
        main = self._main(aim)
        pos = tuple(net.position[i] + (main.position[i] - net.position[i]) * s for i in range(3))
        target = tuple(net.target[i] + (main.target[i] - net.target[i]) * s for i in range(3))
        fov = net.fov_v_deg + (main.fov_v_deg - net.fov_v_deg) * s
        return Camera(pos, target, fov, self.width, self.height)

    def _second(self, bx: float, by: float, aim: Vec) -> Camera:
        if self._cut_kind in ("netL", "netR"):
            if self._net_due():
                return self._goal_beat(bx, by, aim)
            self.angle = "net"
            return self._net_shot(bx, by)
        return self._main(aim)


def blur_vector(prev: Camera | None, cur: Camera, shutter: float) -> tuple[float, float]:
    """Image-space motion of the scene during the exposure, from the camera pan and zoom.

    The world point at the image centre now is projected through last frame's camera; the
    displacement over one frame interval, times the shutter fraction, is the blur streak.
    A streak longer than BLUR_CAP_PX is shortened. The recorded blur is the one drawn.
    """
    if prev is None or shutter <= 0:
        return (0.0, 0.0)
    # A cut changes the gantry. That displacement is not a pan, so it must not streak the frame.
    if math.dist(prev.position, cur.position) > 1.0:
        return (0.0, 0.0)
    p = prev.project(cur.target)
    if p is None:
        return (0.0, 0.0)
    dx, dy = (cur.width / 2 - p[0]) * shutter, (cur.height / 2 - p[1]) * shutter
    length = math.hypot(dx, dy)
    if length > BLUR_CAP_PX:
        dx, dy = dx * BLUR_CAP_PX / length, dy * BLUR_CAP_PX / length
    return (round(dx, 3), round(dy, 3))
