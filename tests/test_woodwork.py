"""The woodwork (Law 1; docs/GROUNDING.md P15): the ball rebounds off a post or the crossbar from
any direction, including a ball moving along the goal line, and never passes through. Each test
names the mutation it must catch."""

import math

from ninety.sim import ball
from ninety.sim.engine import DT, GOAL_HALF_WIDTH, POST_RADIUS, Engine
from ninety.validate import closest_on_segment

POST_Y = 34.0 - GOAL_HALF_WIDTH - POST_RADIUS  # the near post's axis (Law 1: inner edges 7.32 m apart)
BAR_Z = 2.44 + POST_RADIUS
TOUCHING = ball.RADIUS + POST_RADIUS


def fly(state: tuple, frames: int = 25) -> list[tuple]:
    """The ball on its own: flight, then the woodwork, frame by frame."""
    e = Engine(1)
    e.ball = state
    path = [state]
    for _ in range(frames):
        before = e.ball
        e.ball = ball.step(before, DT)
        e.woodwork(before)
        path.append(e.ball)
    return path


def closest_to_post(path: list[tuple]) -> float:
    """Closest approach of the ball's centre to the post's axis, along each frame's straight path
    (a ball can pass a post between two frames)."""
    steps = zip(path, path[1:], strict=False)
    return min(closest_on_segment(a[0], a[1], b[0], b[1], 105.0, POST_Y)[0] for a, b in steps)


def test_a_ball_struck_at_the_post_rebounds():
    path = fly((95.0, POST_Y, 0.3, 20.0, 0.0, 2.0))
    assert closest_to_post(path) >= TOUCHING - 0.02
    assert path[-1][3] < 0  # coming back out


def test_a_ball_moving_along_the_goal_line_cannot_pass_through_the_post():
    """Regression (audit 6): the woodwork was tested only where the ball's path crossed the goal
    line, so a ball rolling along it went through the post (and a goal was given). Mutation
    caught: the old crossing-only test."""
    path = fly((105.03, 26.0, 0.4, 0.3, 10.0, 0.0))
    assert closest_to_post(path) >= TOUCHING - 0.02
    assert all(b[1] < POST_Y for b in path if abs(b[0] - 105.0) < TOUCHING)  # stopped on its side


def test_a_ball_dropping_onto_the_bar_bounces_up():
    """Regression (corner report, seed 78): a ball falling just past the line passed through the
    crossbar."""
    path = fly((105.09, 35.1, 3.0, 0.0, 0.0, -8.0), frames=10)
    centres = [(b[0], b[2] + ball.RADIUS) for b in path]
    assert min(math.hypot(x - 105.0, z - BAR_Z) for x, z in centres) >= TOUCHING - 0.02
    assert any(b[5] > 0 for b in path[1:])  # sent back up


def test_the_post_is_where_law_1_puts_it():
    """Regression (corner report, seed 70): the engine put the post's axis at the inner edge, so a
    ball crossing 13 cm from the true axis went past it. Mutation caught: axis at 3.66 m."""
    path = fly((104.0, 28.50, 0.6, 11.0, 17.9, -4.0), frames=8)  # crosses about 0.15 m from the axis
    assert closest_to_post(path) >= TOUCHING - 0.02


def test_a_ball_into_the_middle_of_the_goal_is_untouched():
    path = fly((100.0, 34.0, 0.5, 20.0, 0.0, 0.0), frames=10)
    assert all(b[3] > 0 for b in path)  # never turned back
