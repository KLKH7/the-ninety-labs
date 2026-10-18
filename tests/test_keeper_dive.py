"""P15: what a diving keeper covers, across the goal and up and down, and how a penalty is aimed (A2)."""

import random

import pytest

from ninety.sim import offball
from ninety.sim.body import HAND_REACH_Z
from ninety.sim.engine import (
    GOAL_THIRD_M,
    PENALTY_MIDDLE,
    PENALTY_SIDE_AIM_M,
    SHOT_AIM_OFF_M,
    Engine,
    first_low_within,
)


def test_his_dive_covers_the_middle_third_until_the_flight_shows_the_height():
    low, high = offball.MIDDLE_THIRD_Z
    assert offball.dive_band(0.0) == (low, high) == offball.dive_band(0.2)  # 245 ms (Higueras-Herbada)
    floor, top = offball.dive_band(0.4)  # then out toward the ground and his full reach, not at once
    assert 0.0 < floor < low and high < top < HAND_REACH_Z
    assert offball.dive_band(5.0) == pytest.approx((0.0, HAND_REACH_Z))


def test_a_ball_under_his_dive_passes_beneath_his_hands():
    # a ball rolling at 0.3 m straight through where he is, with his hands no lower than 0.81 m
    args = (100.0, 34.0, 0.3, 5.0, 0.0, 0.0, 102.5, 34.0, 1.0, 2.0)
    assert first_low_within(*args) is not None
    assert first_low_within(*args, floor=0.81) is None
    rising = (100.0, 34.0, 0.3, 5.0, 0.0, 1.0, 102.5, 34.0, 1.0, 2.0)  # rises into his band within reach
    assert first_low_within(*rising, floor=0.81) is not None


def keeper_at_line():
    e = Engine(1)
    k = e.keeper("away")
    k.x, k.y, k.vx, k.vy = 104.0, 34.0, 0.0, 0.0
    e.kicked_at = e.t
    return e, k


def test_mid_dive_his_stretch_goes_the_way_he_dives_not_behind_him():
    e, k = keeper_at_line()
    e.dive = (k.id, e.t - 0.3, k.y, 1.45, e.t - 0.3, 0.0)  # diving toward higher y, 0.3 s in
    ahead, _ = e.reach(k, k.x, k.y + 1.0)
    behind, _ = e.reach(k, k.x, k.y - 1.0)
    assert ahead > offball.KEEPER_STAND_REACH_M and behind == offball.KEEPER_STAND_REACH_M
    e.dive = None  # on his feet the stretch is the same either side
    assert e.reach(k, k.x, k.y + 1.0) == e.reach(k, k.x, k.y - 1.0)


def test_diving_or_down_he_covers_only_the_heights_he_has_reached():
    e, k = keeper_at_line()
    assert e.keeper_band(k, e.t) is None  # on his feet: his usual reach
    e.dive = (k.id, e.t, k.y, 1.45, e.t, 0.0)
    assert e.keeper_band(k, e.t + 0.1) == offball.dive_band(0.1)
    e.dive = None
    e.landed = (k.id, e.t)
    e.off_balance[k.id] = e.t + 0.5  # down after it, on the ground
    assert e.keeper_band(k, e.t) == (0.0, offball.MIDDLE_THIRD_Z[0])
    e.off_balance[k.id] = e.t - 0.1  # back on his feet
    assert e.keeper_band(k, e.t) is None


def aims(restart, n=3000):
    """The aims a taker on the mark chooses, as the keeper is told them (keeper_read's aim)."""
    e = Engine(1)
    taker = e.by_id["h9"]
    seen = []
    e.keeper_read = lambda keeper, kicker, aim: seen.append(aim - 34.0)
    for k in range(n):
        taker.x, taker.y, taker.heading, taker.vx, taker.vy = 93.7, 34.0, 0.0, 0.0, 0.0
        e.ball = (93.9, 34.0, 0.0, 0.0, 0.0, 0.0)
        e.possessor, e.from_restart, e.dead_ball = taker.id, restart, None
        e.rng = random.Random(k)
        e.shoot(taker)
    return seen


def test_a_penalty_goes_down_the_middle_about_as_often_as_penalties_did():
    seen = aims("penalty_kick")
    middle = sum(abs(a) < GOAL_THIRD_M / 2 for a in seen) / len(seen)
    assert abs(middle - PENALTY_MIDDLE) < 0.03  # Bar-Eli et al., 82 of 286
    assert all(abs(a) <= PENALTY_SIDE_AIM_M[1] for a in seen)
    open_play = aims(None, 500)
    assert all(SHOT_AIM_OFF_M[0] <= abs(a) <= SHOT_AIM_OFF_M[1] for a in open_play)  # unchanged


def test_a_low_ball_passes_under_a_keeper_in_mid_dive_but_not_one_on_his_feet():
    """P15: in the air he covers the middle third, so a ball along the ground goes beneath him."""
    def through(diving):
        e, k = keeper_at_line()
        for q in e.players:
            if q is not k:
                q.x, q.y = 5.0, 5.0
        e.possessor = None
        e.ball = (101.0, 34.0, 0.11, 15.0, 0.0, 0.0)  # along the ground, straight at him
        e.kicked = e.emit("shot", "home", 101.0, 34.0, player="h9")
        e.kicked_at = e.t
        e.released_by = e.last_touch = "h9"
        if diving:
            e.dive = (k.id, e.t, k.y, 1.45, e.t, 0.0)
        for _ in range(8):
            e.step()
            if e.ball[0] > k.x + 0.5:  # got past him (it may then go in and play restart)
                return True
        return False
    assert through(diving=True) and not through(diving=False)
