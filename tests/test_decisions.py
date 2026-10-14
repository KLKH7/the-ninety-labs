"""On-ball decisions score options from what the player believes; the scoring behaves like football."""

import random
from collections import Counter

from ninety.sim import decisions as D


def scene(**kw) -> D.Scene:
    base = dict(x=60.0, y=34.0, goal_x=105.0, mates=[], opponents=[], keeper=None, decisions=0.5,
                composure=0.5, dribbling=0.5, traits=(), risk=0.0)
    base.update(kw)
    return D.Scene(**base)


def test_shot_estimate_follows_the_published_shape():
    central = lambda d: D.shot_estimate(105 - d, 34, 105, [], None)  # noqa: E731
    assert 0.25 < central(11) < 0.35
    assert 0.09 < central(18) < 0.15
    assert central(35) < 0.04
    assert central(11) > D.shot_estimate(105 - 11, 10, 105, [], None)  # a tight angle is worse


def test_a_defender_in_the_cone_or_a_well_placed_keeper_lowers_the_estimate():
    open_shot = D.shot_estimate(90, 34, 105, [], None)
    assert D.shot_estimate(90, 34, 105, [(97, 34)], None) < open_shot
    assert D.shot_estimate(90, 34, 105, [(97, 50)], None) == open_shot  # outside the cone
    assert D.shot_estimate(90, 34, 105, [], (103, 34)) < D.shot_estimate(90, 34, 105, [], (103, 60))


def test_a_blocked_lane_makes_a_pass_worse_than_an_open_one():
    mate = ("h9", 75.0, 34.0, 0.0)
    open_lane = D.pass_option(scene(), mate)
    blocked = D.pass_option(scene(opponents=[(67.0, 34.0)]), mate)
    assert blocked.value < open_lane.value


def test_a_team_mate_not_seen_for_a_while_is_a_less_certain_option():
    fresh = D.pass_option(scene(), ("h9", 75.0, 34.0, 0.0))
    stale = D.pass_option(scene(), ("h9", 75.0, 34.0, 5.0))
    assert stale.value < fresh.value


def test_pressure_is_felt_further_in_front_than_behind():
    ahead = D.pressure(scene(opponents=[(65.0, 34.0)]))
    behind = D.pressure(scene(opponents=[(55.0, 34.0)]))
    assert ahead > 0 and behind == 0


def test_clearing_is_only_an_option_in_his_own_third():
    kinds = lambda s: {o.kind for o in D.options(s)}  # noqa: E731
    assert "clear" in kinds(scene(x=10.0))
    assert "clear" not in kinds(scene(x=60.0))


def test_a_good_decision_maker_takes_the_best_option_more_often():
    s_good, s_poor = scene(decisions=1.0, x=88.0), scene(decisions=0.0, x=88.0)
    s_good.mates = s_poor.mates = [("h9", 95.0, 30.0, 0.0), ("h7", 70.0, 34.0, 0.0)]
    best = max(D.options(s_good), key=lambda o: o.value)
    rng = random.Random(1)
    good = Counter(D.choose(s_good, rng).kind == best.kind for _ in range(400))[True]
    poor = Counter(D.choose(s_poor, rng).kind == best.kind for _ in range(400))[True]
    assert good > poor


def test_chasing_the_game_makes_shooting_more_attractive():
    shot = lambda risk: next(o for o in D.options(scene(x=85.0, risk=risk)) if o.kind == "shoot")  # noqa: E731
    assert shot(1.0).value > shot(-1.0).value
