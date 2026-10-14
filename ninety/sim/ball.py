"""Ball physics: flight under gravity and air drag, bouncing, rolling on grass.

Pure functions on a state (x, y, z, vx, vy, vz) in metres and m/s, z being the height of the
bottom of the ball. Every constant cites its source in docs/GROUNDING.md (rows P5, P8).
"""

from __future__ import annotations

import math

GRAVITY = 9.81
RADIUS = 0.11  # Law 2: circumference 68 to 70 cm
MASS = 0.43  # Law 2: 410 to 450 g
AIR_DENSITY = 1.2
DRAG_COEFFICIENT = 0.25  # verify: a football at match speeds
DRAG_K = 0.5 * AIR_DENSITY * DRAG_COEFFICIENT * math.pi * RADIUS**2 / MASS  # deceleration = K * speed²
ROLL_DECEL = 1.2  # verify: m/s² of grass rolling resistance
RESTITUTION = 0.6  # verify: share of vertical speed kept in a bounce on grass
BOUNCE_GRIP = 0.85  # verify: share of horizontal speed kept in a bounce
SETTLE_MPS = 0.6  # below this vertical speed a bounce becomes a roll

State = tuple[float, float, float, float, float, float]


def step(s: State, dt: float) -> State:
    x, y, z, vx, vy, vz = s
    speed = math.sqrt(vx * vx + vy * vy + vz * vz)
    drag = DRAG_K * speed * dt
    vx, vy, vz = vx * (1 - drag), vy * (1 - drag), vz * (1 - drag)
    if z > 0 or vz > 0:
        vz -= GRAVITY * dt
    else:
        ground = math.hypot(vx, vy)
        slow = ROLL_DECEL * dt
        keep = 0.0 if ground <= slow else (ground - slow) / ground
        vx, vy, vz = vx * keep, vy * keep, 0.0
    x, y, z = x + vx * dt, y + vy * dt, z + vz * dt
    if z < 0:
        z = 0.0
        if vz < -SETTLE_MPS:
            vz, vx, vy = -vz * RESTITUTION, vx * BOUNCE_GRIP, vy * BOUNCE_GRIP
        else:
            vz = 0.0
    return x, y, z, vx, vy, vz


def predict(s: State, dt: float, seconds: float) -> list[State]:
    """The ball's path if nobody touches it, one state per step, stopping when it comes to rest."""
    path = [s]
    for _ in range(int(seconds / dt)):
        s = step(s, dt)
        path.append(s)
        if s[2] == 0 and s[5] == 0 and s[3] == 0 and s[4] == 0:
            break
    return path


def _bisect(f, lo: float, hi: float, want: float, rounds: int = 30) -> float:
    """f increasing in its argument; returns the argument where f is closest to want."""
    for _ in range(rounds):
        mid = (lo + hi) / 2
        if f(mid) < want:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def _travel(vx: float, vz: float, dt: float, until: float = 8.0) -> list[tuple[float, float, float]]:
    """Distance, height and ground speed along a kick in a straight line."""
    s, out = (0.0, 0.0, 0.0, vx, 0.0, vz), []
    for _ in range(int(until / dt)):
        s = step(s, dt)
        out.append((s[0], s[2], math.hypot(s[3], s[4])))
        if s[3] == 0:
            break
    return out


def ground_pass(distance: float, arrive_mps: float, dt: float) -> float:
    """Launch speed for a pass along the ground that is still moving at arrive_mps on arrival."""
    def speed_at_target(v0: float) -> float:
        for d, _, v in _travel(v0, 0.0, dt):
            if d >= distance:
                return v
        return 0.0
    return _bisect(speed_at_target, 0.5, 40.0, arrive_mps)


def lofted_pass(distance: float, angle_deg: float, dt: float) -> tuple[float, float]:
    """Horizontal and vertical launch speeds for a ball that first lands at distance."""
    c, s = math.cos(math.radians(angle_deg)), math.sin(math.radians(angle_deg))

    def first_bounce(v0: float) -> float:
        prev = 0.0
        for d, z, _ in _travel(v0 * c, v0 * s, dt):
            if z == 0 and d > 0.5:
                return d
            prev = d
        return prev
    v0 = _bisect(first_bounce, 1.0, 40.0, distance)
    return v0 * c, v0 * s


def shot(distance: float, speed: float, aim_height: float, dt: float) -> tuple[float, float]:
    """Horizontal and vertical launch speeds for a ball struck at speed that is at aim_height
    when it has travelled distance."""
    def height_at(vz: float) -> float:
        vx = math.sqrt(max(speed * speed - vz * vz, 0.01))
        for d, z, _ in _travel(vx, vz, dt):
            if d >= distance:
                return z
        return 0.0
    vz = _bisect(height_at, 0.0, speed * 0.6, aim_height)
    return math.sqrt(max(speed * speed - vz * vz, 0.01)), vz
