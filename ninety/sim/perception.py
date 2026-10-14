"""What each player believes about the pitch: physics uses the truth, decisions use this.

A player sees what is in front of him and what is very close; he refreshes the rest only when
he scans (looks around). Positions he sees carry an error that grows with distance; positions
he has not seen for a while are extrapolated from the last velocity he saw, so they go stale.
A pass chosen on a stale picture is how misplaced passes happen. Constants cite
docs/GROUNDING.md (P12, P13).
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

SIMPLE_REACTION_S = 0.255  # P12: footballers' simple visual reaction
CHOICE_REACTION_S = 0.365  # P12: reaction when a direction must also be chosen
KEEPER_ANTICIPATION_S = 0.25  # P12: keepers start 50 to 350 ms before the strike; design within it
VIEW_HALF_ANGLE = math.radians(60)  # design: the useful field of view either side of facing
SENSE_RADIUS_M = 3.0  # design: anyone this close is noticed whichever way the player faces
POSITION_ERROR_PER_M = 0.02  # design: 1 m of error at 50 m
SCAN_INTERVAL_S = (1.5, 3.5)  # P13: design; scanning frequency varies with role and pressure


@dataclass
class Sighting:
    x: float
    y: float
    vx: float
    vy: float
    t: float


@dataclass
class Belief:
    """One player's picture of everyone else."""
    seen: dict[str, Sighting] = field(default_factory=dict)
    next_scan: float = 0.0

    def where(self, pid: str, now: float) -> tuple[float, float] | None:
        """Believed position now: the last sighting, carried forward at the velocity seen."""
        s = self.seen.get(pid)
        if s is None:
            return None
        age = now - s.t
        return s.x + s.vx * age, s.y + s.vy * age

    def age(self, pid: str, now: float) -> float:
        s = self.seen.get(pid)
        return math.inf if s is None else now - s.t


def facing(vx: float, vy: float, x: float, y: float, bx: float, by: float) -> float:
    """A moving player looks where he runs; a still one looks at the ball."""
    if math.hypot(vx, vy) > 0.5:
        return math.atan2(vy, vx)
    return math.atan2(by - y, bx - x)


def visible(heading: float, x: float, y: float, ox: float, oy: float) -> bool:
    dx, dy = ox - x, oy - y
    if math.hypot(dx, dy) <= SENSE_RADIUS_M:
        return True
    off = (math.atan2(dy, dx) - heading + math.pi) % (2 * math.pi) - math.pi
    return abs(off) <= VIEW_HALF_ANGLE


def observe(belief: Belief, me: tuple[float, float, float, float], others: list[tuple],
            ball: tuple[float, float], now: float, rng: random.Random) -> bool:
    """Refresh what this player can see now. `others` holds (id, x, y, vx, vy). Returns True if
    he scanned (looked all round) this time."""
    x, y, vx, vy = me
    scanning = now >= belief.next_scan
    if scanning:
        belief.next_scan = now + rng.uniform(*SCAN_INTERVAL_S)
    heading = facing(vx, vy, x, y, ball[0], ball[1])
    for pid, ox, oy, ovx, ovy in others:
        if not (scanning or visible(heading, x, y, ox, oy)):
            continue
        sigma = POSITION_ERROR_PER_M * math.hypot(ox - x, oy - y)
        belief.seen[pid] = Sighting(ox + rng.gauss(0, sigma), oy + rng.gauss(0, sigma), ovx, ovy, now)
    return scanning
