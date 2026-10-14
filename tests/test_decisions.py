"""On-ball decisions score options from what the player believes; the scoring behaves like football."""

import math
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


def mirror(**kw) -> D.Scene:
    """The same scene for a team attacking the goal at x=0."""
    s = scene(**kw)
    s.x, s.goal_x = 105 - s.x, 0.0
    s.mates = [(m[0], 105 - m[1], m[2], m[3]) for m in s.mates]
    s.opponents = [(105 - ox, oy) for ox, oy in s.opponents]
    s.keeper = None if s.keeper is None else (105 - s.keeper[0], s.keeper[1])
    return s


def test_every_option_is_valued_the_same_attacking_either_goal():
    kw = dict(x=80.0, y=30.0, mates=[("m", 92.0, 26.0, 0.0), ("n", 70.0, 50.0, 0.0)],
              opponents=[(86.0, 29.0), (75.0, 40.0)], keeper=(103.0, 34.0))
    home = sorted((o.kind, round(o.value, 9)) for o in D.options(scene(**kw)))
    away = sorted((o.kind, round(o.value, 9)) for o in D.options(mirror(**kw)))
    assert home == away


def test_pressure_depends_on_direction_for_the_away_team_too():
    assert D.pressure(mirror(opponents=[(65.0, 34.0)])) > 0
    assert D.pressure(mirror(opponents=[(55.0, 34.0)])) == 0


def test_losing_the_ball_costs_more_near_his_own_goal():
    assert D.loss_cost(10.0, 34.0, 105.0) > D.loss_cost(90.0, 34.0, 105.0)
    assert D.loss_cost(95.0, 34.0, 0.0) > D.loss_cost(15.0, 34.0, 0.0)


def test_only_defenders_between_ball_and_goal_block_a_shot():
    assert D.shot_estimate(90, 34, 105, [(85, 34)], None) == D.shot_estimate(90, 34, 105, [], None)


def test_the_shot_estimate_stays_a_chance_even_on_the_line():
    assert 0 < D.shot_estimate(104.0, 34.0, 105, [], None) < 1
    assert D.value(103.0, 34.0, 105.0) < 1.1


def test_a_lofted_pass_goes_over_an_opponent_near_the_passer():
    mate = ("h9", 95.0, 34.0, 0.0)  # 35 m: lofted
    clear = D.pass_option(scene(), mate)
    near_passer = D.pass_option(scene(opponents=[(66.0, 34.0)]), mate)
    near_landing = D.pass_option(scene(opponents=[(92.0, 34.0)]), mate)
    assert clear.lofted and near_passer.value == clear.value and near_landing.value < clear.value


def test_a_pass_is_led_toward_the_goal_being_attacked():
    assert D.pass_option(scene(), ("h9", 75.0, 34.0, 0.0)).target[0] > 75.0
    assert D.pass_option(mirror(), ("a9", 30.0, 34.0, 0.0)).target[0] < 30.0


def test_a_pass_too_short_for_the_receiver_to_reach_the_lead_is_less_certain():
    s = scene(x=60.0)
    short = D.pass_option(s, ("h9", 64.5, 34.0, 0.0))  # the ball is there before he can step to it
    gain = D.value(*short.target, 105.0)
    assert short.value < 0.8 * gain


def test_an_opponent_on_the_dribble_path_makes_the_dribble_worse():
    free = max(o.value for o in D.options(scene(x=70.0)) if o.kind == "dribble")
    blocked = max(o.value for o in D.options(scene(x=70.0, opponents=[(73.0, 34.0), (72.0, 37.0),
                                                                     (72.0, 31.0)])) if o.kind == "dribble")
    assert blocked < free


def test_a_dribble_toward_goal_is_valued_by_the_same_shot_estimate_as_shooting():
    # Two opponents equally far from the carry's end (so equally able to stop it); only one
    # stands in the shooting cone from there.
    in_cone = next(o for o in D.options(scene(x=88.0, opponents=[(104.0, 34.0)])) if o.kind == "dribble")
    outside = next(o for o in D.options(scene(x=88.0, opponents=[(100.0, 42.0)])) if o.kind == "dribble")
    assert in_cone.target == outside.target == (94.0, 34.0)
    assert in_cone.value < outside.value


def test_a_lane_is_judged_where_the_opponent_meets_the_line_not_by_his_distance_from_the_passer():
    s = scene(x=60.0)
    mate = ("h9", 82.5, 34.0, 0.0)  # a 24 m ground pass to (84, 34)
    free = D.pass_option(s, mate)
    s.opponents = [(72.0, 40.0)]  # 6 m off the line at its midpoint
    v0 = D.launch_speed(24.0)
    conf = D.sigmoid((D.generic_time(5.0) - D.ground_time(v0, 12.0)) / D.LANE_MARGIN_S)
    receive = D.sigmoid((D.ground_time(v0, 24.0) + 0.5 - D.generic_time(1.5)) / D.RECEIVE_MARGIN_S)
    receive *= D.sigmoid((D.CONTROL_EST_MPS - D.ARRIVE_MPS) / D.CONTROL_MARGIN_MPS)
    space = 0.7 + 0.3 * min(1.0, math.hypot(84.0 - 72.0, 6.0) / 5.0)
    gain = D.value(84.0, 34.0, 105.0) * space
    expected = conf * receive * gain - (1 - conf * receive) * D.loss_cost(72.0, 34.0, 105.0)
    assert math.isclose(D.pass_option(s, mate).value, expected, rel_tol=1e-9)
    assert free.value > expected


def test_carrying_on_is_slightly_preferred():
    hold = next(o for o in D.options(scene(current="hold")) if o.kind == "hold").value
    assert hold > next(o for o in D.options(scene(current="dribble")) if o.kind == "hold").value


def test_a_throw_in_is_only_ever_a_throw():
    s = scene(x=60.0, y=0.5, throw=True, mates=[("h9", 70.0, 8.0, 0.0)])
    kinds = {o.kind for o in D.options(s)}
    assert kinds == {"pass"} and all(o.lofted for o in D.options(s))
    assert D.options(scene(x=60.0, y=0.5, throw=True)) == []


def test_a_lofted_ball_toward_his_own_goal_is_costed_where_it_would_end():
    s = scene(x=40.0, y=34.0, opponents=[(20.0, 34.0)])
    back = D.pass_option(s, ("h1", 6.0, 34.0, 0.0))  # 34 m back to the keeper, through the air
    forward = D.pass_option(s, ("h9", 72.0, 34.0, 0.0))
    assert back.lofted and back.value < forward.value
    assert back.value < -0.1  # a lob that misses ends near his own goal


def test_a_failed_pass_is_costed_where_it_would_end_if_that_is_worse():
    s = scene(x=40.0, y=34.0, opponents=[(28.0, 37.0)])
    back = D.pass_option(s, ("h4", 18.5, 34.0, 0.0))  # 20 m back along the ground, toward his own goal
    conf = D.pass_confidence(s, *back.target, 18.5, 34.0, 0.0, False)
    gain = D.value(*back.target, 105.0, s.opponents) * (0.7 + 0.3 * min(1.0, math.hypot(8.0, 3.0) / 5.0))
    at_target = D.loss_cost(*back.target, 105.0)
    assert at_target > D.loss_cost(30.0, 34.0, 105.0)  # the end is worse than the midpoint here
    assert math.isclose(back.value, conf * gain - (1 - conf) * at_target, rel_tol=1e-9)
