"""Duels (D8): the tackle race, the decision to commit, the carrier's reaction, shielding."""

import math
import random

from ninety.sim import decisions as D
from ninety.sim.engine import DT, OFF_BALANCE_S, SHIELD_M, Engine


def one_on_one(gap: float = 1.2, keeper_holds: bool = False) -> tuple[Engine, object, object]:
    """h9 holding the ball at (60, 34), a4 `gap` metres goal-side; everyone else far away."""
    e = Engine(3)
    att, dfd = e.by_id["h9"], e.by_id["a4"]
    if keeper_holds:
        att = e.keeper("home")
    for p in e.players:
        p.vx = p.vy = 0.0
        if p not in (att, dfd):
            p.x, p.y = (2.0, 2.0) if p.team == "home" else (103.0, 66.0)
    att.x, att.y, att.heading = (8.0, 34.0, 0.0) if keeper_holds else (60.0, 34.0, 0.0)
    dfd.x, dfd.y = att.x + gap, 34.0
    e.give(att.id)
    e.ball = (att.x + 0.37, 34.0, 0.0, 0.0, 0.0, 0.0)
    return e, att, dfd


def test_the_tackle_race_is_lost_beyond_reach_and_won_more_often_up_close_and_by_good_tacklers():
    assert D.tackle_chance(D.LUNGE_REACH_M + 0.01) == 0.0
    assert D.tackle_chance(0.5) > D.tackle_chance(1.5) > 0
    assert D.tackle_chance(1.5, tackling=0.9) > D.tackle_chance(1.5, tackling=0.1)


def test_a_defender_commits_more_often_up_close_and_when_aggressive():
    def commits(gap: float, aggression: float) -> int:
        n = 0
        for seed in range(150):
            e, att, dfd = one_on_one(gap)
            e.rng = random.Random(seed)
            dfd.profile.attributes.update(aggression=aggression, decisions=0.5)
            for k in range(6):  # one decision tick for him within these frames
                e.frame = k
                e.duels()
            n += dfd.id in e.lunges
        return n
    assert commits(0.6, 0.5) > commits(1.6, 0.5)
    assert commits(1.4, 1.0) > commits(1.4, 0.0)


def test_a_lunge_that_arrives_before_the_carrier_reacts_wins_the_ball():
    e, att, dfd = one_on_one(0.9)
    e.lunges[dfd.id] = e.t + 0.1
    e.evade_at[dfd.id] = e.t + 0.5  # he reacts too late
    e.t += 0.12
    e.duels()
    assert e.possessor is None and any(ev["type"] == "tackle" for ev in e.match.events)


def test_a_carrier_who_reacts_first_gets_the_ball_away_and_leaves_the_defender_off_balance():
    e, att, dfd = one_on_one(1.5)
    e.lunges[dfd.id] = e.t + 0.4
    e.evade_at[dfd.id] = e.t + 0.1
    e.t += 0.12
    e.duels()  # he reacts: the ball goes sideways and forward of the defender's foot
    assert e.dribbler == att.id and e.possessor is None
    vx, vy = e.ball[3], e.ball[4]
    assert abs(vy) > abs(vx) * 0.5  # pushed across the line of the challenge
    for _ in range(int(0.3 / DT) + 2):  # the ball runs on until the lunge arrives
        e.ball = (e.ball[0] + e.ball[3] * DT, e.ball[1] + e.ball[4] * DT, 0.0, *e.ball[3:])
        e.t += DT
    e.duels()
    assert not any(ev["type"] == "tackle" for ev in e.match.events)
    assert e.off_balance[dfd.id] > e.t and e.off_balance[dfd.id] <= e.t + OFF_BALANCE_S


def test_an_off_balance_defender_neither_commits_nor_chases():
    e, att, dfd = one_on_one(0.6)
    e.off_balance[dfd.id] = e.t + 1.0
    for k in range(12):
        e.frame = k
        e.duels()
    assert dfd.id not in e.lunges
    assert e.shape_target(dfd)[:2] == (dfd.x, dfd.y)


def test_a_holding_carrier_keeps_the_ball_on_the_far_side_from_his_man():
    e, att, dfd = one_on_one(1.5)  # the defender is in front (larger x)
    e.dribble_to = None
    for _ in range(10):
        e.tick_carrier()
    assert e.ball[0] < att.x  # behind him, away from the defender
    assert SHIELD_M > 1.5


def test_nobody_challenges_a_keeper_holding_the_ball_in_his_box():
    e, keeper, dfd = one_on_one(0.6, keeper_holds=True)
    for k in range(12):
        e.frame = k
        e.duels()
    assert not e.lunges


def test_the_carrier_judges_a_dribble_by_the_same_tackle_race():
    near = D.Scene(60.0, 34.0, 105.0, [], [(62.0, 34.0)], None, 0.5, 0.5, 0.5, (), 0.0)
    far = D.Scene(60.0, 34.0, 105.0, [], [(62.0, 45.0)], None, 0.5, 0.5, 0.5, (), 0.0)
    straight = lambda s: next(o for o in D.options(s) if o.kind == "dribble").value  # noqa: E731
    assert straight(near) < straight(far)
    assert math.isclose(D.tackle_chance(0.0), D.sigmoid(D.GENERIC_REACTION_S / D.LANE_MARGIN_S))


def test_a_defender_inside_lunge_reach_of_the_carry_counts_by_his_tackle_chance(monkeypatch):
    monkeypatch.setattr(D, "POSSESSION", None)
    s = D.Scene(60.0, 34.0, 105.0, [], [(62.0, 34.5)], None, 0.5, 0.5, 0.5, (), 0.0)
    straight = next(o for o in D.options(s) if o.kind == "dribble")
    win = 1 - D.tackle_chance(0.5)
    gain = D.value(*straight.target, 105.0, s.opponents, None)
    assert math.isclose(straight.value, win * gain - (1 - win) * D.loss_cost(60.0, 34.0, 105.0))
