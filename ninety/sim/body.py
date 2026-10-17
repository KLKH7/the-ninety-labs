"""A player's body: how fast they can accelerate, brake and run, and how that fades with fatigue.

Pure functions and a small state object; every constant cites its row in docs/GROUNDING.md
(P2, P9, P10). Capability is set per player; what a player shows in a match (top speeds,
distance, the late drop in high-intensity running) is measured afterwards, never set.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from ninety.sim import fmath

GRAVITY = 9.81
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
        return D0 * fmath.exp(-self.spent / (SLOW_SCALE * D0))

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
        return top * seconds - (top - u) * tau * (1 - fmath.exp(-seconds / tau))

    def time_to_cover(self, gap: float, speed_along: float = 0.0) -> float:
        """Seconds to run `gap` metres along a line. A player moving away from it must first
        brake to a stop, which takes time and adds distance."""
        if gap <= 0:
            return 0.0
        brake_t = extra = 0.0
        if speed_along < 0:
            brake_t = -speed_along / BRAKE_MAX
            extra = speed_along * speed_along / (2 * BRAKE_MAX)
            speed_along = 0.0
        # Newton's method: distance over time is smooth and its derivative is the speed.
        top = self.top_speed()
        u = clamp(speed_along, 0.0, top)
        tau = top / self.f0
        target = gap + extra
        t = target / max(top, 1e-6) + tau  # a start past the answer: speed only rises
        for _ in range(12):
            f = self.distance_in(t, u) - target
            speed = top - (top - u) * fmath.exp(-t / tau)
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
            self.reserve += (self.ceiling - self.reserve) * (1 - fmath.exp(-dt / tau))
        self.reserve = clamp(self.reserve, 0.0, self.ceiling)


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
