"""R8, T2, T3: out of possession the team keeps the length it keeps on the ball (O6), so a high press
up to a goal kick brings its line up behind its forwards instead of stretching the team."""

import pytest

from ninety.sim.offball import LENGTH_MAX_M
from ninety.sim.style import HIGH, LOW, MID, Style
from ninety.sim.team import BLOCKS, LINE_GAPS_M, TeamBrain

GOAL_KICK_BALL_X = 99.5  # an away goal kick, the ball in the away goal area: 99.5 m from home's goal


def _length(style: Style, ball_x: float) -> float:
    brain = TeamBrain("home", style)
    brain.update(0.0, False, ball_x, {})
    return brain.front_x - brain.line_x


@pytest.mark.parametrize("line", [LOW, MID, HIGH])
def test_a_high_press_at_a_goal_kick_is_no_longer_than_the_cap(line):
    """Fails before the cap: the forwards waited at the ball and the line at its block, 49 m apart
    with a high line and 77 m with a low one."""
    assert _length(Style(line, HIGH), GOAL_KICK_BALL_X) == pytest.approx(LENGTH_MAX_M)


def test_the_line_steps_up_only_when_the_forwards_are_too_far_ahead():
    """Where the team is short enough the line is where its block puts it (T2), unchanged."""
    lo, hi = BLOCKS["mid"]
    brain = TeamBrain("home", Style(MID, MID))
    brain.update(0.0, False, 80.0, {})
    assert brain.line_x == pytest.approx(hi)  # ball 80 m out: the mid block's top
    assert brain.front_x - brain.line_x < LENGTH_MAX_M
    brain = TeamBrain("home", Style(MID, HIGH))
    brain.update(0.0, False, 60.0, {})
    assert brain.line_x == pytest.approx(30.0)  # half the ball's distance: inside the block
    assert brain.front_x == pytest.approx(60.0)


def test_the_capped_line_stays_goal_side_of_the_ball_for_the_away_side_too():
    brain = TeamBrain("away", Style(LOW, HIGH))
    brain.update(0.0, False, 105.0 - GOAL_KICK_BALL_X, {})
    assert brain.line_x - brain.front_x == pytest.approx(LENGTH_MAX_M)
    assert brain.line_x > 105.0 - GOAL_KICK_BALL_X + LINE_GAPS_M["attack"]


def test_the_midfield_recovers_level_with_a_ball_inside_the_block():
    """Fails before the recovery: the midfield kept 12 m ahead of the line wherever the ball was, so
    with the ball 30 m from goal the line stood at 25 m and the midfield at 37 m, behind the play."""
    for team, own in (("home", 0.0), ("away", 105.0)):
        brain = TeamBrain(team, Style(MID, MID))
        brain.update(0.0, False, abs(own - 30.0), {})
        line = abs(brain.line_x - own)
        mid = abs(brain.slot("CM", 34.0, 34.0)[0] - own)
        assert line == pytest.approx(25.0) and mid == pytest.approx(30.0)  # level with the ball
        brain.update(0.0, False, abs(own - 60.0), {})  # ball in front of the block: the usual gap
        assert abs(brain.slot("CM", 34.0, 34.0)[0] - brain.line_x) == pytest.approx(LINE_GAPS_M["midfield"])


def test_the_midfield_is_never_behind_its_own_line():
    """A ball in our goal area pulls the line to its floor (Law 1, the goal area): the midfield
    stands level with the line, never behind it."""
    for team, own in (("home", 0.0), ("away", 105.0)):
        brain = TeamBrain(team, Style(LOW, MID))
        brain.update(0.0, False, abs(own - 3.0), {})
        line = abs(brain.line_x - own)
        assert abs(brain.slot("CM", 34.0, 34.0)[0] - own) == pytest.approx(line)
