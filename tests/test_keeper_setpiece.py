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
        # and as far off his line as O1 sets him from there (equal by construction)
        assert abs(tx - sx) < 1e-9


def test_his_spots_at_three_free_kicks():
    # Written out (lesson 190), from the wall's cover (near post to 1.22 m past the centre, Bray's
    # q = p / 3) and O1's depth: 22 m out at y = 30, the open part 35.22 to 37.66 m, he stands at
    # y = 35.31, 3.80 m off his line; 20 m out at y = 40, at y = 33.11; 25 m out straight on (the
    # wall anchored on the high post), at y = 31.97.
    for at, want in [((PITCH_X - 22.0, 30.0), (101.2049, 35.314)),
                     ((PITCH_X - 20.0, 40.0), (101.3899, 33.1052)),
                     ((PITCH_X - 25.0, 34.0), (100.875, 31.9674))]:
        e, k = kick(at)
        tx, ty, _ = e.shape_target(k)
        assert abs(tx - want[0]) < 1e-3 and abs(ty - want[1]) < 1e-3, (at, tx, ty)


def test_he_covers_the_open_part_until_the_kick_and_the_whole_goal_after_it():
    # The restart given (restart), then set and waiting to be struck (set_by): the wall stands until
    # the kick, and so does his cover. After the kick he sets himself for the whole goal again.
    at = (PITCH_X - 22.0, 30.0)
    e, k = kick(at)
    covered = e.shape_target(k)[:2]
    e.set_by, e.restart = e.restart, None  # taken: the set ball waiting for its kick
    assert e.shape_target(k)[:2] == covered
    e.set_by = None  # struck
    assert e.shape_target(k)[:2] == offball.keeper_spot(*at, PITCH_X)


def test_his_own_sides_free_kick_moves_him_nowhere_new():
    # The wall is the opponents' at their kick: at his own team's free kick he covers the whole goal.
    e = Engine(3)
    e.possessor = e.kicked = None
    at = (22.0, 30.0)  # home's own half, in range of home's goal at x = 0
    e.ball = (*at, 0.0, 0.0, 0.0, 0.0)
    e.stop("free_kick", "away", at, taker="a9")
    assert e.restart.wall  # the premise: home's wall is up
    k = e.keeper("away")  # the kicking side's keeper, at the other end
    for brain in e.brains.values():
        brain.in_possession = False  # before the first look of the team brain, as at the whistle
    tx, ty, _ = e.shape_target(k)
    assert (tx, ty) == offball.keeper_spot(e.ball[0], e.ball[1], PITCH_X)


def test_with_no_wall_he_covers_the_whole_goal_as_before():
    for direct, at in [(False, (PITCH_X - 22.0, 30.0)), (True, (PITCH_X - 45.0, 30.0))]:
        e, k = kick(at, direct=direct)
        assert not e.restart.wall  # the premise: an indirect kick, or one out of shooting range
        tx, ty, _ = e.shape_target(k)
        assert (tx, ty) == offball.keeper_spot(*at, PITCH_X)
