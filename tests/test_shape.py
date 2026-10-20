"""Attacking shape (O6) and passes into space (O7)."""

import random

from ninety.sim import decisions as D
from ninety.sim import offball as O
from ninety.sim.profiles import Profile


def slot(role, ball_x=50.0, ball_y=34.0, line=80.0, own=0.0):
    return O.attacking_slot(role, own, ball_x, ball_y, line)


def test_with_the_ball_the_team_spreads_wide_and_its_attackers_hold_the_last_line_onside():
    rb, lb = slot("RB"), slot("LB")
    assert 30 < abs(rb[1] - lb[1]) < 48  # full-backs give width, within published team widths
    st = slot("ST", ball_x=70.0, line=80.0)
    assert 78.0 <= st[0] < 80.0  # on their last line, a step onside
    assert slot("RCB")[0] < 50.0 < st[0]  # centre-backs behind the ball, striker ahead of it


def test_stays_wide_moves_him_toward_his_own_touchline():
    home = slot("RB")
    wider = O.attacking_slot("RB", 0.0, 50.0, 34.0, 80.0, O.STAYS_WIDE_M)
    assert wider[1] < home[1]  # the right back's side is the near touchline
    assert abs(wider[1] - home[1]) == O.STAYS_WIDE_M
    centre = slot("ST", ball_x=60.0, line=80.0)
    still = O.attacking_slot("ST", 0.0, 60.0, 34.0, 80.0, O.STAYS_WIDE_M)
    assert still == centre  # a central role has no touchline to drift to
    away = O.attacking_slot("RB", 105.0, 55.0, 34.0, 25.0, O.STAYS_WIDE_M)
    assert abs(wider[0] - (105 - away[0])) < 1e-9 and abs(wider[1] - (68 - away[1])) < 1e-9


def test_the_shape_mirrors_for_the_team_attacking_the_other_way():
    home = slot("RB", ball_x=50.0, ball_y=34.0, line=80.0, own=0.0)
    away = slot("RB", ball_x=55.0, ball_y=34.0, line=25.0, own=105.0)
    assert abs(home[0] - (105 - away[0])) < 1e-9 and abs(home[1] - (68 - away[1])) < 1e-9


def test_with_the_ball_wide_in_the_final_third_the_box_is_attacked():
    near = slot("ST", ball_x=90.0, ball_y=60.0, line=101.0)  # their defenders deep in the box
    far = slot("RW", ball_x=90.0, ball_y=60.0, line=101.0)  # the right winger is on the far side
    assert near[0] > 95 and abs(near[1] - 34) < 8
    assert far[0] > 95 and far[1] < 34
    assert slot("RB", ball_x=90.0, ball_y=60.0)[0] < 95  # a full-back is not one of the box runners


def test_a_pass_leads_a_running_team_mate_into_the_space_ahead_of_him():
    s = D.Scene(50.0, 34.0, 105.0, [], [], None, 0.5, 0.5, 0.5, (), 0.0, [], {},
                Profile.generate("CM", random.Random(7)))
    standing = D.pass_option(s, ("h9", 70.0, 34.0, 0.0, 0.0, 0.0))
    running = D.pass_option(s, ("h9", 70.0, 34.0, 0.0, 7.0, 0.0))
    assert running.target[0] > standing.target[0] + 5.0


def test_box_runners_wait_onside_for_the_delivery():
    st = slot("ST", ball_x=88.0, ball_y=60.0, line=93.0)
    assert st[0] <= 92.0  # held a step onside of their line, not parked at the near post
    beyond_ball = slot("ST", ball_x=95.0, ball_y=60.0, line=93.0)
    assert beyond_ball[0] <= 95.0  # level with the ball at most, when the ball is further on


BEHIND = [r for r, (b, _) in O.SHAPE_IN_POSSESSION.items() if b is not None]
ALL = list(O.SHAPE_IN_POSSESSION)
R8_LENGTH_MAX_M = 46.0  # R8: the top of the published in-possession team length (Rico-Gonzalez)


def in_own_box(spot, own=0.0):
    return abs(spot[0] - own) <= 16.5 and abs(spot[1] - 34.0) <= 20.16  # Law 1


def test_with_the_ball_deep_the_team_spreads_instead_of_dropping_into_its_own_box():
    # A centre-back on the ball 20 m out, their last line 70 m out: the shape builds up from
    # there, nobody's spot is in the box (it once put both centre-backs, both full-backs and the
    # holding midfielder on one line 12 m out).
    spots = {r: slot(r, ball_x=20.0, line=70.0) for r in ALL}
    assert not [r for r, s in spots.items() if in_own_box(s)]
    assert max(s[0] for s in spots.values()) - min(s[0] for s in spots.values()) <= R8_LENGTH_MAX_M


def test_with_the_keeper_on_the_ball_only_the_centre_backs_stay_near_him():
    spots = {r: slot(r, ball_x=5.0, line=70.0) for r in ALL}
    assert {r for r, s in spots.items() if in_own_box(s)} <= {"RCB", "LCB"}
    assert spots["CM"][0] > 16.5 and spots["RB"][0] > 16.5


def test_the_team_is_never_longer_than_the_published_range_and_the_back_line_never_ahead_of_the_ball():
    # Every ball position, central and wide (the box runs too), their line ahead of or behind it.
    for ball_x in range(0, 106, 5):
        for ball_y in (4.0, 20.0, 34.0, 50.0, 64.0):
            for line in range(53, 105, 4):
                spots = [slot(r, ball_x=float(ball_x), ball_y=ball_y, line=float(line)) for r in ALL]
                xs = [s[0] for s in spots]
                assert max(xs) - min(xs) <= R8_LENGTH_MAX_M + 1e-9, (ball_x, ball_y, line)
                back = min(slot(r, ball_x=float(ball_x), ball_y=ball_y, line=float(line))[0] for r in BEHIND)
                assert back <= max(ball_x, O.DEEPEST_M) + 1e-9, (ball_x, ball_y, line)


def test_in_midfield_the_shape_is_the_template_behind_the_ball():
    # Ball on halfway with their line 70 m out: the R8 limit does not bind, so every role stands
    # where the template puts him behind the ball, and the forwards on their line.
    for r in BEHIND:
        assert abs(slot(r, ball_x=50.0, line=70.0)[0] - (50.0 - O.SHAPE_IN_POSSESSION[r][0])) < 1e-9
    assert abs(slot("ST", ball_x=50.0, line=70.0)[0] - 69.0) < 1e-9


def test_pressed_high_the_team_may_still_be_deep():
    # Their last line 55 m out squeezes the team: the back line stays deep, the length is short.
    spots = {r: slot(r, ball_x=20.0, line=55.0) for r in ALL}
    assert spots["RCB"][0] == O.DEEPEST_M


def test_with_the_ball_deep_the_forwards_still_hold_their_line_as_far_as_the_length_allows():
    # Ball 20 m out, their line 70 m out: the back line moves up level with the ball and the
    # striker stands 46 m ahead of it, pinning their defence (not 25 m from the ball, as it once was).
    assert abs(slot("RCB", ball_x=20.0, line=70.0)[0] - 20.0) < 1e-9
    assert abs(slot("ST", ball_x=20.0, line=70.0)[0] - (20.0 + R8_LENGTH_MAX_M)) < 1e-9


def test_against_a_deep_block_the_whole_shape_moves_up():
    # Ball on halfway, their line 85 m out: the forwards hold it and the team is 46 m long, so the
    # centre-backs stand 38 m out, not 26 m.
    assert abs(slot("ST", ball_x=50.0, line=85.0)[0] - 84.0) < 1e-9
    assert abs(slot("RCB", ball_x=50.0, line=85.0)[0] - (84.0 - R8_LENGTH_MAX_M)) < 1e-9


def test_with_the_ball_beyond_their_line_the_forwards_stay_near_it():
    # Ball 90 m out in the middle, their line 85 m: nobody waits behind; forwards within 5 m of it.
    assert slot("ST", ball_x=90.0, line=85.0)[0] >= 85.0
