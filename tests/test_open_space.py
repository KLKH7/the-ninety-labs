"""O3: attackers off the ball move to be open to a pass, and look again only when they scan."""

import math

from ninety.sim import decisions as D
from ninety.sim.engine import PERCEIVE_EVERY, Engine
from ninety.sim.perception import Sighting

PASSER, SLOT = (45.0, 34.0), (60.0, 34.0)


def test_an_attacker_whose_lane_is_blocked_moves_to_where_it_is_open():
    blocker = [(52.5, 34.3)]  # on the line from the carrier to his place in the shape
    dx, dy = D.open_spot(SLOT, (0.0, 0.0), PASSER, blocker, 80.0, 105.0)
    assert abs(dy) > 1.0  # off the line, not along it
    blocked = D.lane_margin(*PASSER, *SLOT, blocker)
    opened = D.lane_margin(*PASSER, SLOT[0] + dx, SLOT[1] + dy, blocker)
    assert blocked < 0 < opened  # the defender would cut out the pass to his place, not to the new one


def test_an_attacker_with_space_in_midfield_stays_and_one_near_goal_attacks_the_space():
    far = [(30.0, 10.0), (75.0, 60.0)]  # nobody near: every spot is open
    # In midfield 5 m forward is worth under CHOICE_NOISE_GOALS more (D9): not worth moving for.
    assert D.open_spot(SLOT, (0.0, 0.0), PASSER, far, 80.0, 105.0) == (0.0, 0.0)
    assert D.open_spot(SLOT, (0.0, 0.0), PASSER, [], 80.0, 105.0) == (0.0, 0.0)
    # Near goal it is: he steps toward goal, as far as his radius and the onside line allow.
    dx, dy = D.open_spot((85.0, 34.0), (0.0, 0.0), (70.0, 34.0), [], 95.0, 105.0)
    assert dx > 2.0 and 85.0 + dx <= 95.0
    dx, _ = D.open_spot((85.0, 34.0), (0.0, 0.0), (70.0, 34.0), [], 86.0, 105.0)
    assert 85.0 + dx <= 86.0 + 1e-9  # never past the onside line as he sees it


def test_he_keeps_his_spot_unless_another_is_clearly_more_open():
    blocker = [(52.5, 34.3)]
    moved = D.open_spot(SLOT, (0.0, 0.0), PASSER, blocker, 80.0, 105.0)
    assert D.open_spot(SLOT, moved, PASSER, blocker, 80.0, 105.0) == moved  # asked again: the same answer
    nudged = [(52.5, 34.0)]  # the defender shifts a little: not enough to change his mind
    assert D.open_spot(SLOT, moved, PASSER, nudged, 80.0, 105.0) == moved


def test_he_never_moves_offside_off_the_pitch_or_out_of_passing_range():
    crowd = [(x, y) for x in (50.0, 55.0, 62.0) for y in (30.0, 34.0, 38.0)]
    for slot, onside, goal in (((60.0, 34.0), 61.0, 105.0), ((78.0, 10.0), 90.0, 105.0),
                               ((76.0, 2.0), 90.0, 105.0), ((40.0, 34.0), 30.0, 0.0)):
        fwd = 1.0 if goal else -1.0
        dx, dy = D.open_spot(slot, (0.0, 0.0), PASSER, crowd + [(slot[0] - 4.0, slot[1])], onside, goal)
        x, y = slot[0] + dx, slot[1] + dy
        assert math.hypot(dx, dy) <= D.OPEN_RADIUS_M + 1e-9
        assert 0.5 <= x <= 104.5 and 0.5 <= y <= 67.5
        assert fwd * x <= fwd * onside + 1e-9
        assert math.hypot(x - PASSER[0], y - PASSER[1]) <= D.MAX_PASS_M + 1e-9
    # Out of passing range already, he is nobody's option: he keeps his place.
    assert D.open_spot((100.0, 60.0), (0.0, 0.0), PASSER, crowd, 104.0, 105.0) == (0.0, 0.0)


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
        r = math.dist(base, (carrier.x, carrier.y)) or 1.0
        step = (2.5 * (base[0] - carrier.x) / r, 2.5 * (base[1] - carrier.y) / r)  # further out: legal
        e.open_at[q.id] = step
        moved = e.shape_target(q)[:2]
        e.open_at.pop(q.id, None)
        if math.isclose(moved[0], base[0] + step[0]) and math.isclose(moved[1], base[1] + step[1]):
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


def test_he_never_comes_nearer_the_carrier_to_be_open():
    # Spots nearer the ball are always safer to pass to, so a search that allowed them would draw the
    # whole team toward the carrier and shorten the passing (it did: 13.6 to 12.7 m on average).
    import itertools
    pts = [(x, y) for x, y in itertools.product((48.0, 52.0, 56.0, 62.0), (28.0, 33.0, 38.0))]
    for crowd in (pts[:3], pts[3:7], pts[6:], [(52.5, 34.3)], pts):
        dx, dy = D.open_spot(SLOT, (0.0, 0.0), PASSER, crowd, 80.0, 105.0)
        assert math.dist((SLOT[0] + dx, SLOT[1] + dy), PASSER) >= math.dist(SLOT, PASSER) - 1e-9, crowd


def test_he_never_comes_nearer_even_where_a_nearer_spot_would_be_worth_more():
    # Found by search: with spots nearer the carrier allowed, he would choose one in these scenes
    # (a team-mate behind the ball, a defender at his shoulder). He steps across or further out.
    for slot, carrier, defenders in (((34.2, 4.2), (41.0, 13.7), [(34.5, 2.2)]),
                                     ((49.9, 22.5), (66.3, 37.7), [(67.1, 29.0), (71.8, 25.8), (49.9, 20.1),
                                                                   (67.1, 17.1)])):
        dx, dy = D.open_spot(slot, (0.0, 0.0), carrier, defenders, 100.0, 105.0)
        assert (dx, dy) != (0.0, 0.0)  # he does move, just not toward the ball
        assert math.dist((slot[0] + dx, slot[1] + dy), carrier) >= math.dist(slot, carrier) - 1e-9


def test_he_takes_the_spot_with_room_to_play():
    # The same lane both ways; one way leaves him under 4 m from a defender, the other over 5 m.
    slot, carrier, defenders = (86.0, 15.7), (82.2, 33.3), [(92.4, 29.4), (86.6, 39.1), (87.1, 16.1)]
    dx, dy = D.open_spot(slot, (0.0, 0.0), carrier, defenders, 100.0, 105.0)
    assert min(math.dist((slot[0] + dx, slot[1] + dy), o) for o in defenders) >= 5.0


def test_near_his_own_goal_he_steps_out_of_a_lane_a_defender_can_cut():
    # Played back toward his own box, a pass cut out there costs most: he moves out of the lane.
    slot, carrier, defenders = (16.1, 28.4), (50.6, 24.6), [(32.3, 29.5)]
    dx, dy = D.open_spot(slot, (0.0, 0.0), carrier, defenders, 100.0, 105.0)
    assert (dx, dy) != (0.0, 0.0)
    moved = D.lane_margin(*carrier, slot[0] + dx, slot[1] + dy, defenders)
    assert moved > D.lane_margin(*carrier, *slot, defenders)


def test_he_chooses_from_what_he_believes_not_where_players_really_are():
    e, carrier, mate = _carrier_and_mate()
    place, onside = (60.0, 30.0), 80.0
    a = e.by_id["a4"]
    a.x, a.y = 52.5, 32.0  # really in the lane to his place
    e.beliefs[mate.id].seen[a.id] = Sighting(52.5, 12.0, 0.0, 0.0, e.t)  # but he believes him far away
    for q in e.players:  # and every other opponent too
        if q.team == "away" and q.id != a.id:
            e.beliefs[mate.id].seen[q.id] = Sighting(q.x, 66.0, 0.0, 0.0, e.t)
    e.open_due.add(mate.id)
    assert e.open_spot(mate, place, onside) == place  # he sees an open lane: no reason to move
    e.beliefs[mate.id].seen[a.id] = Sighting(a.x, a.y, 0.0, 0.0, e.t)  # now he sees him
    e.open_due.add(mate.id)
    assert e.open_spot(mate, place, onside) != place


def test_a_held_spot_the_play_has_made_illegal_is_dropped_at_once():
    e, carrier, mate = _carrier_and_mate()
    place, onside = (60.0, 30.0), 80.0
    e.open_due.discard(mate.id)
    e.open_at[mate.id] = (2.5, 0.0)  # chosen at his last scan: 2.5 m further from the carrier
    assert e.open_spot(mate, place, onside) == (62.5, 30.0)
    # The line steps up: 62.5 m is now offside as he sees it. He does not wait for his next scan.
    assert e.open_spot(mate, place, 61.0) == place and e.open_at[mate.id] == (0.0, 0.0)
    # The carrier runs on past him: the held spot would now bring him nearer the ball.
    e.open_at[mate.id] = (2.5, 0.0)
    carrier.x, carrier.y = 70.0, 30.0
    e.beliefs[mate.id].seen[carrier.id] = Sighting(70.0, 30.0, 0.0, 0.0, e.t)
    assert e.open_spot(mate, place, onside) == place and e.open_at[mate.id] == (0.0, 0.0)


def test_a_scan_and_only_a_scan_makes_him_look_again():
    """P13: the engine's own perception step sets both looks (open space, a man in his zone)."""
    e, _, mate = _carrier_and_mate()
    other = e.by_id["h9"]
    e.open_due.clear()
    e.track_due.clear()
    i, j = e.players.index(mate), e.players.index(other)
    e.frame = (-i) % PERCEIVE_EVERY  # mate looks on this frame
    e.beliefs[mate.id].next_scan = e.t  # and his scan is due
    if (e.frame + j) % PERCEIVE_EVERY == 0:
        e.beliefs[other.id].next_scan = e.t + 10.0  # other looks too, without scanning
    e.perceive_and_think()
    assert mate.id in e.open_due and mate.id in e.track_due
    assert other.id not in e.open_due and other.id not in e.track_due


def test_a_defender_within_a_foot_of_the_lane_still_has_to_react():
    """D1: only a body in the way needs no reaction; a foot's reach still needs one."""
    carrier, spot = (40.0, 34.0), (60.0, 34.0)
    near = (50.0, 34.0 + 0.8)  # 0.8 m off the lane at its middle: a foot reaches it, his body does not
    arrive = 20.0 / D.PASS_SPEED_EST_MPS
    assert math.isclose(D.lane_margin(*carrier, *spot, [near]), D.generic_time(0.0) - 0.5 * arrive)
    on = (50.0, 34.0 + 0.1)  # his body is on the lane: no reaction needed
    assert math.isclose(D.lane_margin(*carrier, *spot, [on]), -0.5 * arrive)


def test_the_keeper_counts_in_the_lane_like_any_opponent():
    e, carrier, mate = _carrier_and_mate()
    place, onside = (60.0, 30.0), 80.0
    keeper = next(q for q in e.players if q.team == "away" and q.role == "GK")
    for q in e.players:  # every outfield opponent far from the lane, as he sees it
        if q.team == "away" and q.role != "GK":
            e.beliefs[mate.id].seen[q.id] = Sighting(q.x, 66.0, 0.0, 0.0, e.t)
    e.beliefs[mate.id].seen[keeper.id] = Sighting(52.5, 32.0, 0.0, 0.0, e.t)  # the keeper in his lane
    e.open_due.add(mate.id)
    assert e.open_spot(mate, place, onside) != place
