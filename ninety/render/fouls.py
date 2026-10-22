"""A foul made legible on screen (lesson 173): the body is drawn at the engine's `fall` and
`fall_dir`. The renderer does not time the fall. x and y stay the feet; `tip` pivots the drawn
body over them. (The fouler's leg going out is a contact like a tackle's: scene.contacts.)

`fall` is degrees over the feet. `fall_dir` is radians, the same convention as heading: the way
the head goes. `tip` takes the angle in radians.
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
