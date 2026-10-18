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


def test_with_a_centre_back_on_the_ball_the_midfield_stands_ahead_of_him():
    """O6, the defect: heights set behind the ball put every midfielder level with or behind a
    centre-back on the ball, leaving him no one between the lines. The team stands in its own
    lines, so they are ahead of him."""
    for ball_x in (15.0, 25.0):  # in his own zone, every midfielder is ahead of him
        for role in ("CM", "RCM", "LCM"):
            assert slot(role, ball_x=ball_x)[0] > ball_x + 2.0
    for role in ("RCM", "LCM"):  # stepped in with it, the two further forward still are
        assert slot(role, ball_x=35.0)[0] > 35.0 + 5.0


def test_the_lines_keep_their_order_and_the_team_its_length():
    """O6: back line, then full-backs and the holding midfielder, then the other two midfielders,
    then the forwards, wherever the ball is; the forwards no further than the team's length (Rico-
    Gonzalez: 31 to 46 m in possession) ahead of the back line, and onside."""
    for ball_x in range(5, 101, 5):
        for line in (60.0, 80.0, 95.0, 103.0):
            # L10: the onside line is never nearer his own goal than halfway or the ball (onside_limit)
            line = max(line, 52.5, ball_x + 0.5)
            u = {r: slot(r, ball_x=float(ball_x), ball_y=34.0, line=line)[0] for r in O.SHAPE_IN_POSSESSION}
            assert u["RCB"] == u["LCB"] < u["RB"] == u["LB"] == u["CM"] < u["RCM"] == u["LCM"] < u["ST"]
            assert u["ST"] - u["RCB"] <= O.TEAM_LENGTH_MAX_M + 1e-9
            assert u["ST"] <= line - 1.0 + 1e-9  # a step onside of their line


def test_the_back_line_follows_the_ball():
    assert slot("RCB", ball_x=60.0)[0] == 60.0 - O.BACK_LINE_BEHIND_M
    assert slot("RCB", ball_x=20.0)[0] == O.DEEPEST_M  # never deeper than this
