"""A foul made legible on screen (lesson 173): the fouled player goes down at the contact and gets up
before the restart. Drawn from the engine's foul event alone; no position, action or event changes.
(The fouler's leg going out is a contact like a tackle's: scene.contacts.)

The timings are a design (no source measured them for us), each with its reason:
- FALL_S: a standing body toppling over its feet reaches the ground in about half a second (a rigid
  1.8 m body pivoting from a small push falls in roughly 0.5 to 0.6 s).
- DOWN: how far the body lies over, short of flat so the shoulders and head rest just above the grass.
- LIE_S: a fouled player stays down a moment, as players do before getting up.
- RISE_S: getting up takes about a second.
- UP_BEFORE_RESTART_S: he is on his feet well before the free kick is taken.
"""

from __future__ import annotations

import math

FALL_S = 0.5
DOWN = math.radians(85)
LIE_S = 1.5
RISE_S = 1.0
UP_BEFORE_RESTART_S = 1.5
RESTARTS = ("set_piece", "kickoff")


def schedule(events: list[dict], frames: list[dict], fps: int) -> dict[str, dict[int, dict]]:
    """For each fouled player, his fall by frame: {"angle": radians over, "dir": the way he falls},
    the way being from the fouler to him at the foul (the contact pushes him on)."""
    order = sorted(events, key=lambda e: e["frame"])
    out: dict[str, dict[int, dict]] = {}
    for i, e in enumerate(order):
        if e["type"] != "foul" or not e.get("receiver") or not e.get("player"):
            continue
        f = e["frame"]
        restart = next((n["frame"] for n in order[i + 1:] if n["type"] in RESTARTS), f + 60 * fps)
        pos = {p["id"]: (p["x"], p["y"]) for p in frames[min(f, len(frames) - 1)]["players"]}
        if e["receiver"] not in pos or e["player"] not in pos:
            continue
        (vx, vy), (fx, fy) = pos[e["receiver"]], pos[e["player"]]
        direction = math.atan2(vy - fy, vx - fx) if math.hypot(vx - fx, vy - fy) > 1e-6 else 0.0
        fall, lie, rise = round(FALL_S * fps), round(LIE_S * fps), round(RISE_S * fps)
        last_up = restart - round(UP_BEFORE_RESTART_S * fps)  # standing from here on
        lie = max(0, min(lie, last_up - rise - fall - f))  # a quick restart shortens the time down
        mine = out.setdefault(e["receiver"], {})
        for k in range(fall + lie + rise):
            if k < fall:
                u = (k + 1) / fall
                angle = DOWN * u * u  # toppling gathers pace, as a fall does
            elif k < fall + lie:
                angle = DOWN
            else:
                u = (k - fall - lie + 1) / rise
                angle = DOWN * (1 - u * u * (3 - 2 * u))
            if f + k < last_up:
                mine[f + k] = {"angle": angle, "dir": direction}
    return out


def tip(point: tuple[float, float, float], x: float, y: float, angle: float, direction: float):
    """`point` (world metres) tipped over by `angle` about the ground under (x, y), toward `direction`:
    the whole body falls over its feet that way."""
    if not angle:
        return point
    ux, uy = math.cos(direction), math.sin(direction)
    along = (point[0] - x) * ux + (point[1] - y) * uy  # ahead of the feet, the way he falls
    side = -(point[0] - x) * uy + (point[1] - y) * ux
    z = point[2]
    c, s = math.cos(angle), math.sin(angle)
    along, z = along * c + z * s, -along * s + z * c
    return (x + along * ux - side * uy, y + along * uy + side * ux, z)
