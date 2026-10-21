"""O2 beyond the box: a defender in the block tracks the attacker in his zone, goal-side, and looks
again only when he scans."""

import math

from ninety.sim import offball as O
from ninety.sim.engine import Engine
from ninety.sim.perception import Sighting

SLOT = (40.0, 30.0)  # a home defender's place in the block; his goal is at x = 0


def test_he_tracks_the_attacker_nearest_his_place_and_only_inside_his_zone():
    near, far = (43.0, 31.0), (40.0, 30.0 + O.ZONE_RADIUS_M + 0.5)
    assert O.zone_man(SLOT, {"a9": near, "a10": far}) == "a9"
    assert O.zone_man(SLOT, {"a10": far}) is None  # nobody in his zone: he holds his place
    closer = (41.0, 30.0)
    assert O.zone_man(SLOT, {"a9": near, "a8": closer}, current="a9") == "a9"  # keeps his man inside
    assert O.zone_man(SLOT, {"a9": far, "a8": closer}, current="a9") == "a8"  # who has left it


def test_he_stands_goal_side_of_his_man_but_never_leaves_his_zone():
    x, y = O.zone_spot(SLOT, (43.0, 31.0), 0.0)
    gx, gy = 0.0, 34.0
    d = math.hypot(gx - 43.0, gy - 31.0)
    assert math.isclose(x, 43.0 + (gx - 43.0) / d * O.MARK_GOAL_SIDE_M)
    assert math.isclose(y, 31.0 + (gy - 31.0) / d * O.MARK_GOAL_SIDE_M)
    assert math.hypot(x - 43.0, y - 31.0) <= O.MARK_GOAL_SIDE_M + 1e-9 and x < 43.0  # goal-side
    for man in ((52.0, 30.0), (40.0, 45.0), (30.0, 22.0)):  # a man running out of his zone
        x, y = O.zone_spot(SLOT, man, 0.0)
        assert math.hypot(x - SLOT[0], y - SLOT[1]) <= O.ZONE_RADIUS_M + 1e-9


def _home_without_the_ball():
    """The away team has the ball deep in its own half; the home team is out of possession."""
    e = Engine(1)
    e.give("a4")
    carrier = e.by_id["a4"]
    carrier.x, carrier.y, carrier.vx, carrier.vy = 80.0, 30.0, 0.0, 0.0
    e.ball = (80.4, 30.0, 0.0, 0.0, 0.0, 0.0)
    e.brains["home"].in_possession, e.brains["away"].in_possession = False, True
    e.brains["home"].pressers, e.brains["home"].markers = [], {}
    e.track_due.clear()
    return e, carrier


def _block_defenders(e):
    """Home outfielders whose target is their place in the block: (player, place)."""
    out = []
    for q in e.players:
        if q.team == "home" and q.role != "GK":
            e.track.pop(q.id, None)
            place = e.shape_target(q)[:2]
            slot = e.brains["home"].slot(q.role, q.ay, max(0.0, min(68.0, e.ball[1])))
            if slot and math.isclose(place[0], max(0.5, min(104.5, slot[0]))) and \
                    math.isclose(place[1], max(0.5, min(67.5, slot[1]))):
                out.append((q, place))
    return out


def test_a_defender_follows_the_attacker_in_his_zone_once_he_scans():
    """Fails before O2 reached beyond the box: a defender's place in the block was a function of the
    ball alone, so an attacker moving through his zone left him standing."""
    e, carrier = _home_without_the_ball()
    blocks = _block_defenders(e)
    assert blocks
    me, place = blocks[0]
    a = next(q for q in e.players if q.team == "away" and q.role != "GK" and q.id != carrier.id)
    a.x, a.y, a.vx, a.vy = place[0] + 3.0, place[1] + 1.0, 0.0, 2.0  # in his zone
    e.beliefs[me.id].seen[a.id] = Sighting(a.x, a.y, 0.0, 0.0, e.t)
    assert e.shape_target(me)[:2] == place  # until he scans he holds his place
    e.track_due.add(me.id)  # he scans
    first = e.shape_target(me)[:2]
    assert first != place and math.dist(first, place) <= 5.0 + 1e-9 and first[0] < a.x  # goal-side
    e.beliefs[me.id].seen[a.id] = Sighting(a.x, a.y + 2.0, 0.0, 0.0, e.t)  # the man moves on
    second = e.shape_target(me)[:2]
    assert second != first  # he moves with his man, between scans too


def test_the_carrier_is_left_to_the_presser():
    e, carrier = _home_without_the_ball()
    me, place = _block_defenders(e)[0]
    carrier.x, carrier.y = place[0] + 2.0, place[1]
    for v in e.beliefs.values():
        v.seen[carrier.id] = Sighting(carrier.x, carrier.y, 0.0, 0.0, e.t)
    e.track_due.add(me.id)
    e.shape_target(me)
    assert e.track.get(me.id) != carrier.id
