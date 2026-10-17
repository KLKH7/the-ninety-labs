"""A player's body: how fast they can accelerate, brake and run, and how that fades with fatigue.

Pure functions and a small state object; every constant cites its row in docs/GROUNDING.md
(P2, P9, P10). Capability is set per player; what a player shows in a match (top speeds,
distance, the late drop in high-intensity running) is measured afterwards, never set.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from ninety.sim.shape import SHOULDER_BREADTH_M

GRAVITY = 9.81
BODY_RADIUS = SHOULDER_BREADTH_M / 2  # P11: how far his body reaches sideways (the outline: shape.py)
BODY_HEIGHT = 1.8  # a ball below this height can strike the body
BODY_RESTITUTION = 0.3  # verify: share of the ball's speed into a body that it keeps (the head too)
CONTROL_M = 1.0  # a foot reaches this far from the body's centre
FOOT_REACH_Z = 1.0  # outfield players can play the ball below this height
HAND_REACH_Z = 2.8  # P11: a jumping keeper's hand reach (standing about 2.35 m plus the jump)
# P11: the head. A header meets the ball at the forehead, about 0.1 m below the top of the head, so
# standing (or stooping) a player heads a ball whose lowest point is up to BODY_HEIGHT less that and
# the ball's radius (its centre at the forehead); jumping (about 0.45 m with an arm swing, the same
# jump as HAND_REACH_Z) he reaches higher, once he has had the time to rise. A header is played
# within HEAD_REACH_M of his centre: the head over the body, leaning or stepping into it (design,
# verify); no further than a foot reaches, so the race's lower bounds (decisions) hold for both.
JUMP_M = 0.45  # P11 (verify for outfield players)
HEAD_STAND_Z = BODY_HEIGHT - 0.1 - 0.11  # about 1.59 m: the ball's lowest point at a standing header
HEAD_JUMP_Z = HEAD_STAND_Z + JUMP_M  # about 2.04 m
JUMP_RISE_S = math.sqrt(2 * JUMP_M / GRAVITY)  # about 0.30 s from take-off to the top of the jump
HEAD_REACH_M = 0.5  # design, verify
# P18: the head drives through the ball at up to HEAD_SPEED_MPS (head closing speeds in purposeful
# headers measured up to about 11 m/s; *verify*). The ball leaves along the line he heads it at that
# speed, plus the share of its own speed into his head that it keeps (BODY_RESTITUTION): a hard
# header is about 14 to 19 m/s.
HEAD_SPEED_MPS = 11.0
TURN_RATE = math.radians(350)  # P16: the fastest a body turns, 180° over a 0.52 s plant (rad/s)
STRIKE_FACING = math.radians(60)  # P16 (design): the widest run-up angle tested with no loss
F0_MEAN, F0_SD = 5.18, 0.46  # P2: acceleration from standing, m/s² (professional sprint tests)
V0_MEAN, V0_SD = 10.0, 0.3  # P9: top-speed capability, m/s; a sprint-test fit gives about 10.3
BRAKE_MAX = 7.0  # P2: braking, m/s²; peak about 8.5, about 4.5 averaged over a full stop
CS_MEAN, CS_SD = 3.9, 0.2  # P10: critical speed, m/s, the fastest sustainable running pace
D0 = 225.0  # P10: metres that can be run above critical speed from full
TAU_LIGHT, TAU_HEAVY = 120.0, 336.0  # P10: s to refill, recovering at a walk vs near CS
ACCEL_COST = 2.5  # verify: extra metabolic cost of accelerating, per unit of a/g [design]
SLOW_SCALE = 20.0  # design: reserves of work before recovery capacity falls to 1/e


@dataclass
class Body:
    f0: float  # acceleration from standing, m/s²
    v0: float  # top-speed capability, m/s
    cs: float  # critical speed, m/s
    reserve: float = D0  # metres left above critical speed
    spent: float = 0.0  # total metres spent above critical speed this match
    grip_used: float = 0.0  # velocity change already used this frame, m/s (shared grip limit)

    @property
    def capacity(self) -> float:
        """Share of the reserve available now: 1 when fresh, 0 when spent."""
        return max(0.0, self.reserve) / self.ceiling

    @property
    def ceiling(self) -> float:
        """The slow store: how full the reserve can refill, falling with work done all match."""
        return D0 * math.exp(-self.spent / (SLOW_SCALE * D0))

    def top_speed(self) -> float:
        """Critical-speed model: with an empty reserve no running above critical speed is
        possible; the speed available above it shrinks as the reserve empties (the linear
        shape is design)."""
        return self.cs + (self.v0 - self.cs) * self.capacity

    def accel_limit(self, speed: float) -> float:
        """Force-velocity: available acceleration falls linearly from f0 at rest to 0 at the top
        speed available now, so fatigue lowers acceleration through that one top speed."""
        return self.f0 * max(0.0, 1 - speed / self.top_speed())

    def distance_in(self, seconds: float, speed_along: float = 0.0) -> float:
        """How far this player can run in a straight line in the given time, from a current
        speed along the line, under force-velocity acceleration: v(t) = V - (V - u)e^(-t/tau)."""
        if seconds <= 0:
            return 0.0
        top = self.top_speed()
        u = clamp(speed_along, 0.0, top)
        tau = top / self.f0
        return top * seconds - (top - u) * tau * (1 - math.exp(-seconds / tau))

    def time_to_cover(self, gap: float, speed_along: float = 0.0) -> float:
        """Seconds to run `gap` metres along a line. A player moving away from it must first
        brake to a stop, which takes time and adds distance, even if he is already within the gap
        (as can_get_to charges it: one rule for whether he gets there and when)."""
        brake_t = extra = 0.0
        if speed_along < 0:
            brake_t = -speed_along / BRAKE_MAX
            extra = speed_along * speed_along / (2 * BRAKE_MAX)
            speed_along = 0.0
        if gap + extra <= 0:
            return 0.0
        # Newton's method: distance over time is smooth and its derivative is the speed.
        top = self.top_speed()
        u = clamp(speed_along, 0.0, top)
        tau = top / self.f0
        target = gap + extra
        t = target / max(top, 1e-6) + tau  # a start past the answer: speed only rises
        for _ in range(12):
            fade = math.exp(-t / tau)
            covered = top * t - (top - u) * tau * (1 - fade) if t > 0 else 0.0  # distance_in, inline
            f = covered - target
            speed = top - (top - u) * fade
            step = f / max(speed, 1e-6)
            t -= step
            if abs(step) < 1e-4:
                break
        return brake_t + max(t, 0.0)

    def spend(self, speed: float, accel: float, dt: float) -> None:
        """Running above critical speed spends the reserve, accelerating costs extra; running
        below it refills, faster the slower the recovery."""
        effort = speed * (1 + ACCEL_COST * max(0.0, accel) / GRAVITY)
        if effort > self.cs:
            used = (effort - self.cs) * dt
            self.reserve -= used
            self.spent += used
        else:
            depth = min(1.0, effort / self.cs)
            tau = TAU_LIGHT + (TAU_HEAVY - TAU_LIGHT) * depth
            self.reserve += (self.ceiling - self.reserve) * (1 - math.exp(-dt / tau))
        self.reserve = clamp(self.reserve, 0.0, self.ceiling)


def can_get_to(body: Body, dx: float, dy: float, reach_m: float, vx: float, vy: float,
               seconds: float) -> tuple[bool, float, float]:
    """Can a player running at (vx, vy) get within `reach_m` of a point (dx, dy) away from him in
    `seconds` of running? (reachable, gap still to close, his speed along the way.) Running away
    from the point, he must first brake to a stop, which takes time and adds distance. One test
    for the engine's chase (engine.can_reach) and the passer's estimate of it."""
    d = math.hypot(dx, dy)
    gap = d - reach_m
    along = (vx * dx + vy * dy) / (d or 1.0)
    brake_t = max(0.0, -along) / BRAKE_MAX
    extra = min(0.0, along) ** 2 / (2 * BRAKE_MAX)
    return gap + extra <= body.distance_in(seconds - brake_t, max(0.0, along)), gap, along


def relative_speed(bvx: float, bvy: float, bvz: float, pvx: float, pvy: float) -> float:
    """The ball's speed relative to a player running at (pvx, pvy): what a touch has to absorb."""
    return math.sqrt((bvx - pvx) ** 2 + (bvy - pvy) ** 2 + bvz * bvz)


def clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def move(x: float, y: float, vx: float, vy: float, tx: float, ty: float, want_speed: float,
         body: Body, dt: float) -> tuple[float, float, float, float]:
    """One step toward a target. The velocity change is limited by grip (BRAKE_MAX, shared by
    braking and turning), and any gain in speed by force-velocity, so speeding up can never
    borrow the braking budget, whether turning or reversing. The player slows in time to stop
    on the target."""
    dx, dy = tx - x, ty - y
    d = math.hypot(dx, dy)
    speed = math.hypot(vx, vy)
    want = min(want_speed, body.top_speed(), math.sqrt(2 * BRAKE_MAX * 0.8 * d))
    wx, wy = (dx / d * want, dy / d * want) if d > 1e-6 else (0.0, 0.0)
    cx, cy = wx - vx, wy - vy
    change = math.hypot(cx, cy)
    if change > BRAKE_MAX * dt:
        cx, cy = cx / change * BRAKE_MAX * dt, cy / change * BRAKE_MAX * dt
    nvx, nvy = vx + cx, vy + cy
    new_speed = math.hypot(nvx, nvy)
    gain = body.accel_limit(speed) * dt
    if new_speed > speed + gain:  # speeding up: force-velocity, not grip
        scale = (speed + gain) / new_speed
        nvx, nvy, new_speed = nvx * scale, nvy * scale, speed + gain
    body.grip_used = math.hypot(nvx - vx, nvy - vy)
    body.spend(new_speed, (new_speed - speed) / dt, dt)
    return x + nvx * dt, y + nvy * dt, nvx, nvy
