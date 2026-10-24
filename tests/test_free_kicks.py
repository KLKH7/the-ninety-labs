"""Attacking free kicks (lesson 202): at a free kick to them in the final third the forwards attack
the box. Each defect test fails on the engine before this change (lesson 8): there the wingers held
their open-play width on the opponents' line, outside the box, and at 6 of 16 free kicks within 35 m
over 20 matches no attacker stood in the box."""

import math

import pytest

from ninety.sim import offball
from ninety.sim.engine import DT, PITCH_X, PITCH_Y, Engine

AREA_DEPTH_M, AREA_HALF_WIDTH_M = 16.5, 20.16  # Law 1: the penalty area
SPOTS = [(PITCH_X - 20.0, 38.0), (PITCH_X - 18.0, 30.0)]  # central, inside shooting range
CASES = [(seed, at) for seed in (3, 7, 11) for at in SPOTS]


def free_kick(seed: int, at: tuple[float, float]) -> Engine:
    """A minute of play, then a direct free kick to home at `at`, its taker over the ball (the whistle
    ends what was in play, as for a foul)."""
    e = Engine(seed)
    e.run(1)
    e.possessor, e.restart, e.set_by, e.throw_by, e.dribbler = None, None, None, None, None
    e.celebration = None
    e.kicked, e.dribble_to, e.windup, e.chase = None, None, None, {}
    e.lunges.clear(), e.lunge_at.clear(), e.evade_at.clear()
    taker = e.by_id["h9"]
    taker.x, taker.y, taker.vx, taker.vy = at[0] - 0.47, at[1], 0.0, 0.0
    e.ball = (*at, 0.0, 0.0, 0.0, 0.0)
    e.stop("free_kick", "home", at, taker=taker.id)
    e.restart.carried_by = taker.id
    return e


def kick(e: Engine) -> None:
    n = len(e.match.events)
    for _ in range(int(80 / DT)):
        e.step()
        if any(ev["type"] in ("pass", "shot") for ev in e.match.events[n:]):
            return
    raise AssertionError("the free kick was never kicked")


def in_box(p) -> bool:
    return abs(p.x - PITCH_X) <= AREA_DEPTH_M and abs(p.y - PITCH_Y / 2) <= AREA_HALF_WIDTH_M


@pytest.mark.parametrize(("seed", "at"), CASES)
def test_at_a_free_kick_near_goal_the_forwards_attack_the_box(seed, at):
    """Defect: only the striker stood in the box; the wingers held their open-play width. At the kick
    every forward but the taker stands in the box (his place is within the goal area's width of the
    goal's centre, on the opponents' line, which their wall 9.15 m from the ball puts inside the box;
    O3 may shift it by up to OPEN_RADIUS_M)."""
    e = free_kick(seed, at)
    r = e.restart
    kick(e)
    forwards = [p for p in e.players
                if p.team == "home" and p.role in ("ST", "RW", "LW") and p.id != r.taker]
    assert len(forwards) == 2  # premise
    for p in forwards:
        assert in_box(p), p.id


@pytest.mark.parametrize("kind", ["free_kick", "corner", "throw_in", "goal_kick", "kick_off", "penalty_kick"])
def test_only_their_own_free_kick_sends_the_forwards_into_the_box(kind):
    """The rule is a free kick's, and the side's own: not the other side's, nor any other restart."""
    from ninety.sim.engine import Restart
    e = Engine(3)
    for given_to in ("home", "away"):
        e.restart, e.set_by = Restart(kind, given_to, 80.0, 30.0, "h9", e.t + 5.0), None
        assert e.own_free_kick("home") is (kind == "free_kick" and given_to == "home")
        e.restart, e.set_by = None, Restart(kind, given_to, 80.0, 30.0, "h9", e.t)  # taken, not kicked
        assert e.own_free_kick("home") is (kind == "free_kick" and given_to == "home")
    e.restart = e.set_by = None
    assert not e.own_free_kick("home")  # in play


def test_the_forwards_box_is_the_goal_area_width_and_only_theirs():
    """SET_PIECE_HALF_WIDTH_M is the goal area's half-width (Law 1: 3.66 m to a post, 5.5 m beyond),
    written out (lesson 190); both wingers are brought in to it, and a midfielder keeps his spot."""
    assert offball.SET_PIECE_HALF_WIDTH_M == pytest.approx(9.16)
    own_goal, line = 0.0, 95.0
    lw = offball.attacking_slot("LW", own_goal, 85.0, 34.0, line, set_piece=True)
    rw = offball.attacking_slot("RW", own_goal, 85.0, 34.0, line, set_piece=True)
    assert lw[1] == pytest.approx(34.0 + 9.16) and rw[1] == pytest.approx(34.0 - 9.16)
    for role in ("RCM", "CM", "LCM", "RB", "LB", "RCB", "LCB"):
        assert (offball.attacking_slot(role, own_goal, 85.0, 34.0, line, set_piece=True)
                == offball.attacking_slot(role, own_goal, 85.0, 34.0, line))


def test_the_box_is_attacked_only_at_their_own_free_kick_in_the_final_third():
    """The rule is the free kick's: in open play, at the other side's free kick, or short of the
    final third, a forward keeps his width."""
    own_goal, line = 0.0, 95.0
    wide = offball.attacking_slot("LW", own_goal, 85.0, 38.0, line)
    assert abs(wide[1] - PITCH_Y / 2) > offball.SET_PIECE_HALF_WIDTH_M  # premise: he stands wide
    near = offball.attacking_slot("LW", own_goal, 85.0, 38.0, line, set_piece=True)
    assert abs(near[1] - PITCH_Y / 2) == pytest.approx(offball.SET_PIECE_HALF_WIDTH_M)
    far = offball.attacking_slot("LW", own_goal, 60.0, 38.0, 75.0, set_piece=True)  # midfield
    assert far == offball.attacking_slot("LW", own_goal, 60.0, 38.0, 75.0)
    assert math.isclose(near[0], wide[0])  # on the same line: offside is unchanged
