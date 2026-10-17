"""A surface for each height (firsttouch.SURFACES, A4, P14): foot, thigh, chest or head by where the
ball meets him, each with its own cushion and its own aim, and the body drawn with the part used."""

import math
from statistics import pstdev

import pytest

from ninety.sim import firsttouch
from ninety.sim.engine import DT, Engine


@pytest.mark.parametrize("z, part", [
    (0.0, "foot"), (0.45, "foot"), (0.46, "thigh"), (0.9, "thigh"), (0.99, "thigh"),
    (1.01, "chest"), (1.1, "chest"), (1.5, "chest"), (1.56, "head"), (1.7, "head"),
])
def test_the_part_is_read_from_the_height_with_the_gaps_to_the_nearer(z, part):
    assert firsttouch.surface(z) == part


def ball_at(z: float, speed: float, first_touch: float = 0.5) -> Engine:
    """A ball at height z arriving square on a standing outfielder who has long since reacted."""
    e = Engine(1)
    for q in e.players:
        q.vx = q.vy = 0.0
    p = e.by_id["a6"]
    p.x, p.y, p.heading = 50.0, 30.0, math.pi
    p.profile.attributes["first_touch"] = first_touch
    e.possessor, e.last_touch, e.kicker_clear, e.kicked_at = None, "h2", True, e.t - 2.0
    e.ball = (49.7 + speed * DT, 30.0, z, speed, 0.0, 0.0)
    e.contact((49.7, 30.0, z, speed, 0.0, 0.0))
    return e


def test_the_chest_drops_a_ball_at_his_feet_that_the_head_only_redirects():
    p = Engine(1).by_id["a6"]
    p.profile.attributes["first_touch"] = 0.5
    foot = p.profile.absorb_mps(False)
    # Faster than a head kills by more than he keeps at his feet, slower than a chest kills.
    speed = (foot * firsttouch.CUSHION["chest"] + foot * firsttouch.CUSHION["head"] + firsttouch.KEEP_MPS) / 2
    assert foot * firsttouch.CUSHION["head"] + firsttouch.KEEP_MPS < speed < foot * firsttouch.CUSHION["chest"]
    chest = ball_at(1.3, speed)
    assert chest.possessor == "a6" and chest.pose(chest.by_id["a6"])[0] == "chest"
    head = ball_at(1.7, speed)
    assert head.possessor is None and head.dribbler == "a6"  # a heavy touch off the head, still his
    assert head.pose(head.by_id["a6"])[0] == "head"


def spread(z: float, n: int = 300) -> float:
    """The SD (degrees) of where a cushioned touch is sent from height z, at a fixed speed."""
    e = Engine(1)
    p = e.by_id["a6"]
    p.x, p.y, p.vx, p.vy, p.heading = 50.0, 30.0, 0.0, 0.0, math.pi
    angles = []
    for _ in range(n):
        vx, vy = e.cushion(p, 49.6, 30.0, 6.0, z)
        angles.append(math.degrees(math.atan2(vy, vx)))
    mid = angles[0]
    return pstdev((a - mid + 180) % 360 - 180 for a in angles)


def test_each_part_aims_as_well_as_it_is_made_to():
    foot, thigh, chest, head = (spread(z) for z in (0.2, 0.7, 1.3, 1.7))
    # Ordered as AIM_ERROR orders them, and in proportion to it (300 draws: within 15%).
    assert foot < head < thigh < chest
    for part, sd in (("thigh", thigh), ("chest", chest), ("head", head)):
        assert sd / foot == pytest.approx(firsttouch.AIM_ERROR[part], rel=0.15)


@pytest.mark.parametrize("z, part", [(0.7, "thigh"), (0.97, "thigh"), (1.3, "chest"), (1.52, "chest"), (1.7, "head")])
def test_the_body_is_drawn_with_the_part_the_engine_used(z, part):
    e = ball_at(z, 4.0)
    assert e.pose(e.by_id["a6"])[0] == part == firsttouch.surface(z)
