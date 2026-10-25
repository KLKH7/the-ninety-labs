"""A foul made legible on screen (lesson 173): the body is drawn at the engine's `fall` and
`fall_dir`. The renderer does not time the fall. x and y stay the feet; `tip` pivots the drawn
body over them. (The fouler's leg going out is a contact like a tackle's: scene.contacts.)

`fall` is degrees over the feet. `fall_dir` is radians, the same convention as heading: the way
the head goes. `tip` takes the angle in radians.

The players react to the whistle (lesson 234), drawn from the engine's own foul event (its frame,
`player` the fouler, `receiver` the fouled) and positions, never moving anyone: the engine already
stops play, so they walk and stand there. The fouler raises a hand, owning up to it, and the fouled
side's nearest team-mates turn their heads to the man on the grass. The head only: a body's facing is
the engine's `heading`, a truth field, which the drawing never contradicts.
"""

from __future__ import annotations

import math


def drawn_fall(player: dict) -> tuple[float, float]:
    """(radians over, direction in radians) from the engine's fields. Standing when `fall` is
    absent or not above 0. Does not change the player."""
    deg = player.get("fall")
    if type(deg) not in (int, float) or deg <= 0:
        return 0.0, 0.0
    way = player.get("fall_dir")
    if type(way) not in (int, float):
        way = 0.0
    return math.radians(float(deg)), float(way)


def apply_fall(gait, player: dict) -> None:
    """Put the engine's fall on the gait this frame. A frame with no fall stands him up."""
    gait.fall, gait.fall_dir = drawn_fall(player)


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


def row(player: dict, angle: float) -> dict:
    """The player's frame row with `fall`, the degrees his drawn body is over, while he is down; the
    row unchanged while he stands (render-check judges a lying body's box by it)."""
    return {**player, "fall": round(math.degrees(angle), 1)} if angle else player


# How the reactions are drawn (*design*, kept short: a beat a viewer reads, not a performance).
REACT_S = 2.0  # the hand stays up, the heads stay turned, this long after the foul frame
REACT_EASE_S = 0.3  # each comes up and goes down over this
LOOKERS = 3  # the fouled side's players nearest him who turn to him
LOOK_MAX = math.radians(70.0)  # as far as a head turns on the neck (*design*)
HAND_UP = 1.12  # the raised hand, as a share of his height: just above his head, within his reach
HAND_SIDE = 0.2  # metres to the side of his body (his right)


def reactions(frames: list[dict], events: list[dict]) -> dict[str, list[dict]]:
    """Per player, his reactions to fouls: {"kind": "signal" | "look", "frame" (the foul's frame index),
    "to" (for a look, who he turns to)}. From the engine's foul events and where everyone stands."""
    index = {fr.get("frame", i): i for i, fr in enumerate(frames)}
    out: dict[str, list[dict]] = {}
    for ev in events:
        i = index.get(ev.get("frame"))
        if ev.get("type") != "foul" or i is None or not ev.get("player"):
            continue
        out.setdefault(ev["player"], []).append({"kind": "signal", "frame": i})
        fouled = ev.get("receiver")
        pos = {p["id"]: p for p in frames[i]["players"]}
        him = pos.get(fouled)
        if him is None:
            continue
        mates = sorted((p for p in frames[i]["players"] if p["team"] == him["team"] and p["id"] != fouled),
                       key=lambda p: math.hypot(p["x"] - him["x"], p["y"] - him["y"]))
        for p in mates[:LOOKERS]:
            out.setdefault(p["id"], []).append({"kind": "look", "frame": i, "to": fouled})
    return out


def _weight(fi: int, start: int, fps: int) -> float:
    """0 before the foul frame, up over REACT_EASE_S, held, down over REACT_EASE_S by REACT_S."""
    u = (fi - start) / fps
    if u < 0 or u > REACT_S:
        return 0.0
    w = min(u / REACT_EASE_S, (REACT_S - u) / REACT_EASE_S, 1.0)
    return 0.5 - 0.5 * math.cos(math.pi * max(w, 0.0))  # eased


def signal_at(gait, mine: list[dict], fi: int, fps: int, x: float, y: float, height_m: float) -> None:
    """The fouler's hand up at frame `fi` (gait.signal), or None."""
    gait.signal = None
    w = max((_weight(fi, r["frame"], fps) for r in mine if r["kind"] == "signal"), default=0.0)
    if w <= 0.0:
        return
    h = gait.heading
    rx, ry = math.sin(h), -math.cos(h)  # his right
    gait.signal = {"side": "r", "at": [round(x + HAND_SIDE * rx, 4), round(y + HAND_SIDE * ry, 4),
                                       round(HAND_UP * height_m, 4)], "w": round(w, 4)}


def look_at(gait, mine: list[dict], fi: int, fps: int, x: float, y: float, frame: dict) -> None:
    """A team-mate's head turned to the fouled player at frame `fi` (gait.look), or None."""
    gait.look = None
    best = None
    for r in mine:
        if r["kind"] != "look":
            continue
        w = _weight(fi, r["frame"], fps)
        if w > 0.0 and (best is None or w > best[0]):
            best = (w, r["to"])
    if best is None:
        return
    him = next((p for p in frame["players"] if p["id"] == best[1]), None)
    if him is None:
        return
    want = math.atan2(him["y"] - y, him["x"] - x)
    yaw = (want - gait.heading + math.pi) % (2 * math.pi) - math.pi
    gait.look = {"yaw": round(max(-LOOK_MAX, min(LOOK_MAX, yaw)), 4), "w": round(best[0], 4)}
