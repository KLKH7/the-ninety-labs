"""A player's body: how fast they can accelerate, brake and run, and how that fades with fatigue.

Pure functions and a small state object; every constant cites its row in docs/GROUNDING.md
(P2, P9, P10). Capability is set per player; what a player shows in a match (top speeds,
distance, the late drop in high-intensity running) is measured afterwards, never set.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass

GRAVITY = 9.81
F0_MEAN, F0_SD = 5.18, 0.46  # P2: acceleration from standing, m/s² (professional sprint tests)
V0_MEAN, V0_SD = 10.0, 0.3  # P9: top-speed capability, m/s; a sprint-test fit gives about 10.3
BRAKE_MAX = 7.0  # P2: braking, m/s²; peak about 8.5, about 4.5 averaged over a full stop
CS_MEAN, CS_SD = 3.9, 0.2  # P10: critical speed, m/s, the fastest sustainable running pace
D0 = 225.0  # P10: metres that can be run above critical speed from full
TAU_LIGHT, TAU_HEAVY = 120.0, 336.0  # P10: s to refill, recovering at a walk vs near CS
ACCEL_COST = 2.5  # verify: extra metabolic cost of accelerating, per unit of a/g [design]
SLOW_SCALE = 20.0  # design: reserves of work before recovery capacity falls to 1/e
EXHAUSTED = 0.35  # design: share of the speed above CS still available on an empty reserve


@dataclass
class Body:
    f0: float  # acceleration from standing, m/s²
    v0: float  # top-speed capability, m/s
    cs: float  # critical speed, m/s
    reserve: float = D0  # metres left above critical speed
    spent: float = 0.0  # total metres spent above critical speed this match
    grip_used: float = 0.0  # velocity change already used this frame, m/s (shared grip limit)

    @classmethod
    def sample(cls, rng: random.Random) -> Body:
        return cls(
            f0=max(4.0, rng.gauss(F0_MEAN, F0_SD)),
            v0=max(9.0, rng.gauss(V0_MEAN, V0_SD)),
            cs=max(3.3, rng.gauss(CS_MEAN, CS_SD)),
        )

    @property
    def capacity(self) -> float:
        """Share of the reserve available now: 1 when fresh, 0 when spent."""
        return max(0.0, self.reserve) / self.ceiling

    @property
    def ceiling(self) -> float:
        """The slow store: how full the reserve can refill, falling with work done all match."""
        return D0 * math.exp(-self.spent / (SLOW_SCALE * D0))

    def top_speed(self) -> float:
        """Above critical speed, what is left of the sprint fades as the reserve empties."""
        share = EXHAUSTED + (1 - EXHAUSTED) * self.capacity
        return self.cs + (self.v0 - self.cs) * share

    def accel_limit(self, speed: float) -> float:
        """Force-velocity: available acceleration falls linearly from f0 at rest to 0 at top speed."""
        top = self.top_speed()
        return self.f0 * max(0.0, 1 - speed / top) * (EXHAUSTED + (1 - EXHAUSTED) * self.capacity)

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
        self.reserve = min(self.reserve, self.ceiling)


def move(x: float, y: float, vx: float, vy: float, tx: float, ty: float, want_speed: float,
         body: Body, dt: float) -> tuple[float, float, float, float]:
    """One step toward a target: speeding up is limited by force-velocity, braking and turning
    by BRAKE_MAX, and the player slows in time to stop on the target."""
    dx, dy = tx - x, ty - y
    d = math.hypot(dx, dy)
    speed = math.hypot(vx, vy)
    want = min(want_speed, body.top_speed(), math.sqrt(2 * BRAKE_MAX * 0.8 * d))
    wx, wy = (dx / d * want, dy / d * want) if d > 1e-6 else (0.0, 0.0)
    ax, ay = wx - vx, wy - vy
    if speed > 1e-6:  # split into along the run (speed up or brake) and across it (turn)
        ux, uy = vx / speed, vy / speed
        along = ax * ux + ay * uy
        acx, acy = ax - along * ux, ay - along * uy
    else:
        ux = uy = 0.0
        along, acx, acy = 0.0, ax, ay
    cap_along = body.accel_limit(speed) * dt if along > 0 else BRAKE_MAX * dt
    along = math.copysign(min(abs(along), cap_along), along)
    across = math.hypot(acx, acy)
    cap_across = (body.accel_limit(speed) if speed <= 1e-6 else BRAKE_MAX) * dt
    if across > cap_across:
        acx, acy = acx / across * cap_across, acy / across * cap_across
    # Braking and turning share one grip limit: the total change never exceeds BRAKE_MAX.
    cx, cy = along * ux + acx, along * uy + acy
    total = math.hypot(cx, cy)
    if total > BRAKE_MAX * dt:
        cx, cy = cx / total * BRAKE_MAX * dt, cy / total * BRAKE_MAX * dt
    vx, vy = vx + cx, vy + cy
    body.grip_used = math.hypot(cx, cy)
    new_speed = math.hypot(vx, vy)
    body.spend(new_speed, (new_speed - speed) / dt, dt)
    return x + vx * dt, y + vy * dt, vx, vy
