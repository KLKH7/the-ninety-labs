"""O3: attackers off the ball move to be open to a pass, and look again only when they scan."""

import math

from ninety.sim import decisions as D
from ninety.sim.engine import Engine
from ninety.sim.perception import Sighting

PASSER, SLOT = (45.0, 34.0), (60.0, 34.0)


def test_an_attacker_whose_lane_is_blocked_moves_to_where_it_is_open():
    blocker = [(52.5, 34.3)]  # on the line from the carrier to his place in the shape
    dx, dy = D.open_spot(SLOT, (0.0, 0.0), PASSER, blocker, 80.0, 1.0)
    assert abs(dy) > 1.0  # off the line, not along it
    blocked = D.lane_margin(*PASSER, *SLOT, blocker)
    opened = D.lane_margin(*PASSER, SLOT[0] + dx, SLOT[1] + dy, blocker)
    assert blocked < 0 < opened  # the defender would cut out the pass to his place, not to the new one


def test_an_attacker_with_space_stays_at_his_place():
    far = [(30.0, 10.0), (75.0, 60.0)]  # nobody near the lane: every spot is open enough
    assert D.open_spot(SLOT, (0.0, 0.0), PASSER, far, 80.0, 1.0) == (0.0, 0.0)
    assert D.open_spot(SLOT, (0.0, 0.0), PASSER, [], 80.0, 1.0) == (0.0, 0.0)


def test_he_keeps_his_spot_unless_another_is_clearly_more_open():
    blocker = [(52.5, 34.3)]
    moved = D.open_spot(SLOT, (0.0, 0.0), PASSER, blocker, 80.0, 1.0)
    assert D.open_spot(SLOT, moved, PASSER, blocker, 80.0, 1.0) == moved  # asked again: the same answer
    nudged = [(52.5, 34.0)]  # the defender shifts a little: not enough to change his mind
    assert D.open_spot(SLOT, moved, PASSER, nudged, 80.0, 1.0) == moved


def test_he_never_moves_offside_off_the_pitch_or_out_of_passing_range():
    crowd = [(x, y) for x in (50.0, 55.0, 62.0) for y in (30.0, 34.0, 38.0)]
    for slot, onside, fwd in (((60.0, 34.0), 61.0, 1.0), ((78.0, 10.0), 90.0, 1.0), ((76.0, 2.0), 90.0, 1.0),
                              ((40.0, 34.0), 30.0, -1.0)):
        dx, dy = D.open_spot(slot, (0.0, 0.0), PASSER, crowd + [(slot[0] - 4.0, slot[1])], onside, fwd)
        x, y = slot[0] + dx, slot[1] + dy
        assert math.hypot(dx, dy) <= D.OPEN_RADIUS_M + 1e-9
        assert 0.5 <= x <= 104.5 and 0.5 <= y <= 67.5
        assert fwd * x <= fwd * onside + 1e-9
        assert math.hypot(x - PASSER[0], y - PASSER[1]) <= D.MAX_PASS_M + 1e-9
    # Out of passing range already, he is nobody's option: he keeps his place.
    assert D.open_spot((100.0, 60.0), (0.0, 0.0), PASSER, crowd, 104.0, 1.0) == (0.0, 0.0)


def _carrier_and_mate():
    """h6 holds the ball at (45, 34) for the home team; h8 is off the ball, his place in the shape
    within passing range."""
    e = Engine(1)
    e.give("h6")
    carrier = e.by_id["h6"]
    carrier.x, carrier.y, carrier.vx, carrier.vy = 45.0, 34.0, 0.0, 0.0
    e.ball = (45.4, 34.0, 0.0, 0.0, 0.0, 0.0)
    e.brains["home"].in_possession = True
    return e, carrier, e.by_id["h8"]


def test_an_attacker_off_the_ball_looks_for_space_only_when_he_scans():
    e, carrier, mate = _carrier_and_mate()
    place, onside = (60.0, 30.0), 80.0  # his place in the shape, as the team's shape gives it
    e.beliefs[mate.id].seen.clear()
    e.open_due.discard(mate.id)
    assert e.open_spot(mate, place, onside) == place  # nothing chosen yet: his place
    # A defender steps into the lane to his place, and he sees it.
    a = e.by_id["a4"]
    a.x, a.y = 52.5, 32.0
    e.beliefs[mate.id].seen[a.id] = Sighting(a.x, a.y, 0.0, 0.0, e.t)
    assert e.open_spot(mate, place, onside) == place  # until he scans, he does not change his mind
    e.open_due.add(mate.id)  # he scans
    moved = e.open_spot(mate, place, onside)
    assert moved != place and math.dist(moved, place) <= D.OPEN_RADIUS_M + 1e-9
    assert D.lane_margin(carrier.x, carrier.y, *moved, [(a.x, a.y)]) > 0 > D.lane_margin(
        carrier.x, carrier.y, *place, [(a.x, a.y)])
    # Between scans he keeps his offset and moves with the shape.
    shifted = (place[0] + 2.0, place[1] - 1.0)
    assert e.open_spot(mate, shifted, onside) == (moved[0] + 2.0, moved[1] - 1.0)


def _on_the_shape(e, carrier):
    """Home outfielders whose target is their place in the shape with the ball (O6): moving the
    offset moves the target by exactly that much."""
    out = []
    for q in e.players:
        if q.team != "home" or q.role == "GK" or q.id == carrier.id:
            continue
        e.open_at.pop(q.id, None)
        base = e.shape_target(q)[:2]
        e.open_at[q.id] = (0.0, -2.5)
        moved = e.shape_target(q)[:2]
        e.open_at.pop(q.id, None)
        if math.isclose(moved[0], base[0]) and math.isclose(moved[1], base[1] - 2.5):
            out.append((q, base))
    return out


def test_the_shape_with_the_ball_puts_him_where_he_chose_to_be_open():
    e, carrier, _ = _carrier_and_mate()
    e.open_due.clear()
    assert len(_on_the_shape(e, carrier)) >= 4  # most of the team stands in the shape


def test_a_defender_in_his_lane_moves_an_attacker_once_he_scans():
    """Before O3 was extended, an attacker's place with the ball was a function of the ball alone:
    a defender in his lane left him where he was."""
    e, carrier, _ = _carrier_and_mate()
    e.open_due.clear()
    a = e.by_id["a8"]  # an opposition midfielder: not one of their last two, so the onside line stays
    for mate, place in _on_the_shape(e, carrier):
        if not 15.0 < math.dist(place, (carrier.x, carrier.y)) < 35.0:
            continue
        a.x, a.y, a.vx, a.vy = (carrier.x + place[0]) / 2, (carrier.y + place[1]) / 2, 0.0, 0.0
        for v in e.beliefs.values():
            v.seen[a.id] = Sighting(a.x, a.y, 0.0, 0.0, e.t)
        if e.shape_target(mate)[:2] == place:  # a8 in his lane does not move his place in the shape
            break
    else:
        raise AssertionError("no attacker in range whose place a8 leaves alone")
    e.open_due.add(mate.id)  # he scans
    tx, ty = e.shape_target(mate)[:2]
    assert (tx, ty) != place and math.dist((tx, ty), place) <= D.OPEN_RADIUS_M + 1e-9
    assert D.lane_margin(carrier.x, carrier.y, tx, ty, [(a.x, a.y)]) > D.lane_margin(
        carrier.x, carrier.y, *place, [(a.x, a.y)]) + D.LANE_MARGIN_S


def test_a_new_possession_forgets_every_offset():
    e, _, mate = _carrier_and_mate()
    e.open_at[mate.id] = (2.5, 0.0)
    e.give("a6")  # the other team wins it
    assert e.open_at == {}
