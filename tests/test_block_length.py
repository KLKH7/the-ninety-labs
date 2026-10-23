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
