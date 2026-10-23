"""O1 at a direct free kick: the wall hides the goal from the near post to a third past its centre
(Bray 2014, Engine.wall_cover), and the keeper covers the part it leaves open. Once he set himself
on the bisector of the whole goal, behind the middle of his own wall."""

import math

from ninety.sim import offball
from ninety.sim.engine import GOAL_HALF_WIDTH, PITCH_X, PITCH_Y, Engine


def kick(at: tuple[float, float], direct: bool = True) -> tuple[Engine, object]:
    """A free kick to home at `at`, the away keeper defending the goal at x = PITCH_X."""
    e = Engine(3)
    e.possessor = e.kicked = None
    e.ball = (*at, 0.0, 0.0, 0.0, 0.0)
    e.stop("free_kick", "home", at, taker="h9", direct=direct)
    return e, e.keeper("away")


def bearing(frm: tuple[float, float], to: tuple[float, float]) -> float:
    return math.atan2(to[1] - frm[1], to[0] - frm[0])


def test_with_the_wall_up_he_covers_the_part_of_the_goal_it_leaves_open():
    for at in [(PITCH_X - 22.0, 30.0), (PITCH_X - 20.0, 40.0), (PITCH_X - 25.0, 34.0)]:
        e, k = kick(at)
        assert e.restart.wall  # the premise: a wall is up
        near, edge = e.wall_cover(e.restart)
        far = PITCH_Y - near
        assert abs(abs(near - PITCH_Y / 2) - GOAL_HALF_WIDTH) < 1e-9  # the wall's near end is at a post
        tx, ty, _ = e.shape_target(k)
        # on the line that halves the open part's angle as seen from the ball
        a, b = bearing(at, (PITCH_X, edge)), bearing(at, (PITCH_X, far))
        assert abs(bearing(at, (tx, ty)) - (a + b) / 2) < 1e-9
        # so to the open side of where he stood for the whole goal, toward the far post
        sx, sy = offball.keeper_spot(*at, PITCH_X)
        assert (ty - sy) * (far - PITCH_Y / 2) > 0.3
        # and as far off his line as O1 sets him from there
        assert abs((PITCH_X - tx) - (PITCH_X - sx)) < 0.5


def test_with_no_wall_he_covers_the_whole_goal_as_before():
    for direct, at in [(False, (PITCH_X - 22.0, 30.0)), (True, (PITCH_X - 45.0, 30.0))]:
        e, k = kick(at, direct=direct)
        assert not e.restart.wall  # the premise: an indirect kick, or one out of shooting range
        tx, ty, _ = e.shape_target(k)
        assert (tx, ty) == offball.keeper_spot(*at, PITCH_X)
