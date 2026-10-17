"""The shape of a player's body in the pitch plane, shared by the contact physics (engine.py) and
the renderer (ninety/render/scene.py), so the body the ball bounces off is the body that is drawn.

Seen from above, a footballer is wide across the shoulders and shallow front to back. The body is
a stadium (a rectangle with round ends): as wide as the shoulders over the deltoids, as deep as
the chest, its long axis across the way he faces. Every point within CHEST_DEPTH_M / 2 of the
spine, a segment of length SHOULDER_BREADTH_M - CHEST_DEPTH_M through the body's centre at right
angles to his heading, is inside him. The sizes are measured at the shoulders and chest; using the
same outline from the grass to BODY_HEIGHT (engine.py), around the legs, is *design* (a striding
foot reaching further is the foot's reach, CONTROL_M in engine.py). Sources: docs/GROUNDING.md, P11.
"""

from __future__ import annotations

import math

SHOULDER_BREADTH_M = 0.50  # P11: bideltoid breadth of adult men, 50.2 cm (SD 3.3)
CHEST_DEPTH_M = 0.20  # P11: anteroposterior chest depth of professional footballers, about 20 cm
RADIUS_M = CHEST_DEPTH_M / 2  # how far the body's surface is from its spine
HALF_SPINE_M = (SHOULDER_BREADTH_M - CHEST_DEPTH_M) / 2  # the spine runs this far either side


def spine(x: float, y: float, heading: float) -> tuple[float, float, float, float]:
    """The ends of the spine of a player at (x, y) facing `heading` (radians)."""
    lx, ly = -math.sin(heading) * HALF_SPINE_M, math.cos(heading) * HALF_SPINE_M  # to his left
    return x + lx, y + ly, x - lx, y - ly


def nearest_on_spine(px: float, py: float, x: float, y: float, heading: float) -> tuple[float, float]:
    """The point of the spine closest to (px, py)."""
    x0, y0, x1, y1 = spine(x, y, heading)
    dx, dy = x1 - x0, y1 - y0
    s = min(max(((px - x0) * dx + (py - y0) * dy) / (dx * dx + dy * dy), 0.0), 1.0)
    return x0 + s * dx, y0 + s * dy


def clearance(px: float, py: float, x: float, y: float, heading: float) -> float:
    """How far (px, py) is outside the body's surface (negative inside)."""
    sx, sy = nearest_on_spine(px, py, x, y, heading)
    return math.hypot(px - sx, py - sy) - RADIUS_M


def surface(angle: float, heading: float, pad: float = 0.0) -> float:
    """How far the body's surface, or a line `pad` outside it, is from its centre in the
    direction `angle`: half the chest depth straight ahead or behind, half the shoulder breadth
    to the side. With pad = a ball's radius, it is where a ball's centre rests against him."""
    r = RADIUS_M + pad
    phi = angle - heading
    fwd, side = abs(math.cos(phi)), abs(math.sin(phi))
    if fwd > 1e-12 and r * side / fwd <= HALF_SPINE_M:  # through the flat front or back
        return r / fwd
    # through a round end: |t (fwd, side) - (0, HALF_SPINE_M)| = r, the far root
    return HALF_SPINE_M * side + math.sqrt(max(0.0, r**2 - (HALF_SPINE_M * fwd) ** 2))


def first_contact(x0: float, y0: float, x1: float, y1: float, x: float, y: float, heading: float,
                  pad: float) -> float | None:
    """The share of the way from (x0, y0) to (x1, y1) at which a ball of radius `pad` first
    touches the body, or None if it never does. Its distance to the spine falls and then rises
    along the path (the distance from a straight path to a segment is convex), so the first
    touch lies between the start and the closest approach and is found by halving."""
    r = RADIUS_M + pad
    a0x, a0y, a1x, a1y = spine(x, y, heading)

    def gap(s: float) -> float:
        px, py = x0 + s * (x1 - x0), y0 + s * (y1 - y0)
        return segments_closest(px, py, px, py, a0x, a0y, a1x, a1y)[1]

    if gap(0.0) <= r:
        return 0.0
    near, d, _, _ = segments_closest(x0, y0, x1, y1, a0x, a0y, a1x, a1y)
    if d > r:
        return None
    lo, hi = 0.0, near  # gap(lo) > r >= gap(hi)
    for _ in range(40):
        mid = (lo + hi) / 2
        lo, hi = (lo, mid) if gap(mid) <= r else (mid, hi)
    return hi


def between(x1: float, y1: float, h1: float, x2: float, y2: float,
            h2: float) -> tuple[float, float, float, float, float]:
    """The closest points of two bodies' spines: (distance, ax, ay, bx, by). Two bodies touch
    when the distance is under CHEST_DEPTH_M (two radii)."""
    p0x, p0y, p1x, p1y = spine(x1, y1, h1)
    q0x, q0y, q1x, q1y = spine(x2, y2, h2)
    s, d, bx, by = segments_closest(p0x, p0y, p1x, p1y, q0x, q0y, q1x, q1y)
    return d, p0x + s * (p1x - p0x), p0y + s * (p1y - p0y), bx, by


def segments_closest(p0x: float, p0y: float, p1x: float, p1y: float, q0x: float, q0y: float,
                     q1x: float, q1y: float) -> tuple[float, float, float, float]:
    """Closest points of segments P and Q in the plane: (s along P, distance, qx, qy)."""
    ux, uy, vx, vy = p1x - p0x, p1y - p0y, q1x - q0x, q1y - q0y
    wx, wy = p0x - q0x, p0y - q0y
    a, b, c = ux * ux + uy * uy, ux * vx + uy * vy, vx * vx + vy * vy
    d, e = ux * wx + uy * wy, vx * wx + vy * wy

    def clamp01(v: float) -> float:
        return min(max(v, 0.0), 1.0)

    if a < 1e-12 and c < 1e-12:
        s = t = 0.0
    elif a < 1e-12:  # P is a point
        s, t = 0.0, clamp01(e / c)
    elif c < 1e-12:  # Q is a point
        s, t = clamp01(-d / a), 0.0
    else:
        den = a * c - b * b
        s = clamp01((b * e - c * d) / den) if den > 1e-12 else 0.0
        t = (b * s + e) / c
        if t < 0.0:
            s, t = clamp01(-d / a), 0.0
        elif t > 1.0:
            s, t = clamp01((b - d) / a), 1.0
    qx, qy = q0x + t * vx, q0y + t * vy
    return s, math.hypot(p0x + s * ux - qx, p0y + s * uy - qy), qx, qy
