"""Attacking shape (O6) and passes into space (O7)."""

from ninety.sim import decisions as D
from ninety.sim import offball as O


def slot(role, ball_x=50.0, ball_y=34.0, line=80.0, own=0.0):
    return O.attacking_slot(role, own, ball_x, ball_y, line)


def test_with_the_ball_the_team_spreads_wide_and_its_attackers_hold_the_last_line_onside():
    rb, lb = slot("RB"), slot("LB")
    assert abs(rb[1] - lb[1]) > 45  # full-backs give width
    st = slot("ST", ball_x=70.0, line=80.0)
    assert 78.0 <= st[0] < 80.0  # on their last line, a step onside
    assert slot("RCB")[0] < 50.0 < st[0]  # centre-backs behind the ball, striker ahead of it


def test_the_shape_mirrors_for_the_team_attacking_the_other_way():
    home = slot("RB", ball_x=50.0, ball_y=34.0, line=80.0, own=0.0)
    away = slot("RB", ball_x=55.0, ball_y=34.0, line=25.0, own=105.0)
    assert abs(home[0] - (105 - away[0])) < 1e-9 and abs(home[1] - (68 - away[1])) < 1e-9


def test_with_the_ball_wide_in_the_final_third_the_box_is_attacked():
    near = slot("ST", ball_x=90.0, ball_y=60.0)
    far = slot("RW", ball_x=90.0, ball_y=60.0)  # the right winger is on the far side from the left flank
    assert near[0] > 95 and abs(near[1] - 34) < 8
    assert far[0] > 95 and far[1] < 34
    assert slot("RB", ball_x=90.0, ball_y=60.0)[0] < 95  # a full-back is not one of the box runners


def test_a_pass_leads_a_running_team_mate_into_the_space_ahead_of_him():
    s = D.Scene(50.0, 34.0, 105.0, [], [], None, 0.5, 0.5, 0.5, (), 0.0)
    standing = D.pass_option(s, ("h9", 70.0, 34.0, 0.0, 0.0, 0.0))
    running = D.pass_option(s, ("h9", 70.0, 34.0, 0.0, 7.0, 0.0))
    assert running.target[0] > standing.target[0] + 5.0
