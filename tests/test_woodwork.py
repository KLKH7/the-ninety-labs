"""The woodwork (Law 1; docs/GROUNDING.md P17): the ball rebounds off the goal frame (posts,
crossbar and the corners between them) from any direction, including a ball moving along the goal
line, never passes through it, and never gains energy from it. Every case runs at both goal lines.
Distances are measured with the validator's own goal-frame geometry. Each test names the mutation
it must catch."""


import pytest

from ninety.sim import ball
from ninety.sim.engine import DT, Engine
from ninety.validate import frame_axes, segment_gap

R = ball.RADIUS
TOUCHING = R + 0.06  # ball radius plus the post's half-width (Law 1: at most 12 cm wide)
POST = 34.0 - 3.66 - 0.06  # the near post's axis
BAR = 2.44 + 0.06  # the crossbar's axis


def mirror(state: tuple, end: float) -> tuple:
    """A state written for the x = 105 goal, moved to the goal at `end`."""
    if end == 105.0:
        return state
    x, y, z, vx, vy, vz = state
    return 105.0 - x, y, z, -vx, vy, vz


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


def centre(b: tuple) -> tuple:
    return b[0], b[1], b[2] + R


def closest(path: list[tuple], end: float, which: slice = slice(None)) -> float:
    """Closest approach of the ball's centre to the frame's axes along each frame's straight path."""
    axes = frame_axes(end)[which]
    return min(segment_gap(centre(a), centre(b), q0, q1)
               for a, b in zip(path, path[1:], strict=False) for q0, q1 in axes)


def energy(b: tuple) -> float:
    return 0.5 * (b[3] ** 2 + b[4] ** 2 + b[5] ** 2) + 9.81 * (b[2] + R)


ENDS = pytest.mark.parametrize("end", [105.0, 0.0])


@ENDS
def test_a_ball_struck_at_the_post_rebounds_with_sixty_percent_of_its_speed(end):
    """Mutations caught: restitution 1.0; goal line at x = 0 ignored."""
    path = fly(mirror((103.0, POST, 0.3, 20.0, 0.0, 0.0), end), frames=6)
    assert closest(path, end) >= TOUCHING - 0.002
    hit = next(k for k, b in enumerate(path) if b[3] * path[0][3] < 0)
    before = path[hit - 1][3]
    assert abs(path[hit][3]) == pytest.approx(0.6 * abs(before), rel=0.05)  # GROUNDING P17: 60 percent


@ENDS
def test_a_ball_moving_along_the_goal_line_cannot_pass_through_the_post(end):
    """Regression (audit 6): the woodwork was tested only where the ball's path crossed the goal
    line, so a ball rolling along it went through the post (and a goal was given). Mutation
    caught: the old crossing-only test."""
    path = fly(mirror((105.03, 26.0, 0.4, 0.3, 10.0, 0.0), end))
    assert closest(path, end) >= TOUCHING - 0.002
    assert all(b[1] < POST for b in path if abs(b[0] - end) < TOUCHING)  # stopped on its side


@ENDS
def test_a_ball_dropping_onto_the_bar_bounces_up_from_where_it_touched(end):
    """Regression (corner report, seed 78): a ball falling just past the line passed through the
    crossbar. Mutation caught: the rebound placed at the wrong height (the contact's centre left
    uncorrected for the radius)."""
    path = fly(mirror((105.09, 35.1, 3.0, 0.0, 0.0, -8.0), end), frames=10)
    assert closest(path, end) >= TOUCHING - 0.002
    hit = next(k for k, b in enumerate(path) if k and b[5] > 0)
    gap = min(segment_gap(centre(path[hit]), centre(path[hit]), q0, q1) for q0, q1 in frame_axes(end))
    assert gap == pytest.approx(TOUCHING, abs=0.002)  # it rebounds from the touch point


@ENDS
def test_the_post_is_where_law_1_puts_it(end):
    """Regression (corner report, seed 70): the engine put the post's axis at the inner edge, so a
    ball crossing 13 cm from the true axis went past it. Mutation caught: axis at 3.66 m."""
    path = fly(mirror((104.0, 28.50, 0.6, 11.0, 17.9, -4.0), end), frames=8)
    assert closest(path, end) >= TOUCHING - 0.002


@ENDS
def test_the_top_corner_of_the_goal_is_closed(end):
    """Regression (audit 7): a ball above the bar's axis and outside the post's passed through the
    corner where they meet."""
    path = fly(mirror((103.8, POST - 0.04, BAR + 0.04 - R, 30.0, 0.0, 0.0), end), frames=4)
    assert closest(path, end) >= TOUCHING - 0.002


@ENDS
def test_the_earliest_touch_decides_the_rebound(end):
    """Mutation caught: the last touch in a frame taken instead of the first. Rising along the
    line at the post-and-bar junction, the ball meets the side of the post before the bar."""
    e = Engine(1)
    start = mirror((end if end == 105.0 else 105.0, 29.95, 2.15 - R, 0.0, 15.0, 10.0), end)
    e.ball = start
    before = e.ball
    e.ball = ball.step(before, DT)
    e.woodwork(before)
    assert e.ball[4] < 0  # sent back along the line by the post, not just down by the bar


@ENDS
def test_only_the_frame_itself_is_solid(end):
    """Mutations caught: the bar treated as running past the posts; the posts as rising above the
    bar. At bar height outside the post, and over the post well above the bar, the ball flies on."""
    wide = fly(mirror((103.0, POST - 1.0, BAR - R, 20.0, 0.0, 0.0), end), frames=6)
    assert all(b[3] * wide[0][3] > 0 for b in wide)
    over = fly(mirror((105.0, 26.0, 3.5 - R, 0.0, 15.0, 0.0), end), frames=10)
    assert all(b[4] > 0 for b in over)


@ENDS
def test_a_ball_already_overlapping_is_pushed_out(end):
    """Mutation caught: a ball that starts the frame overlapping the post and moving into it left
    alone, so it passes through."""
    e = Engine(1)
    e.ball = mirror((end - 0.0 if end == 105.0 else 105.0, POST - 0.10, 0.3, 0.0, 2.0, 0.0), end)
    before = e.ball
    e.ball = ball.step(before, DT)
    e.woodwork(before)
    gap = min(segment_gap(centre(e.ball), centre(e.ball), q0, q1) for q0, q1 in frame_axes(end))
    assert gap >= TOUCHING - 1e-6 and e.ball[4] < 0


@ENDS
def test_a_ball_resting_on_the_bar_gains_no_energy_and_rolls_off(end):
    """Regression (audit 7): a ball that started a frame overlapping the bar was put back where it
    began but kept the frame's gravity in its speed, so a ball resting on the bar gained energy
    without bound and stayed there."""
    path = fly(mirror((105.0001, 34.0, BAR + TOUCHING - R + 0.02, 0.0, 0.0, 0.0), end), frames=150)
    start = energy(path[0])
    assert max(energy(b) for b in path) <= start + 0.05
    assert closest(path[-2:], end) > TOUCHING + 0.05  # it has rolled off


@ENDS
def test_a_ball_into_the_middle_of_the_goal_is_untouched(end):
    path = fly(mirror((100.0, 34.0, 0.5, 20.0, 0.0, 0.0), end), frames=10)
    assert all(b[3] * path[0][3] > 0 for b in path)  # never turned back
