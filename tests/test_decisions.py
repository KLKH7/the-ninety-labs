"""On-ball decisions score options from what the player believes; the scoring behaves like football."""

import copy
import math
import random
from collections import Counter

import pytest

from ninety.sim import decisions as D
from ninety.sim import offball
from ninety.sim.profiles import Profile
from ninety.sim.value import CELLS_X, CELLS_Y, Table, Tables


@pytest.fixture(autouse=True)
def hand_written_values(monkeypatch):
    """These tests pin the decision rules, not whatever table was last measured."""
    monkeypatch.setattr(D, "POSSESSION", None)


PASSER = Profile.generate("CM", random.Random(7))  # a real passer: every estimate carries his kick error


def scene(**kw) -> D.Scene:
    """A scene as the engine builds one (engine.scene_for): a real passer facing the goal he
    attacks, and the opponents as he sees them now, standing unless `moving` says otherwise."""
    base = dict(x=60.0, y=34.0, goal_x=105.0, mates=[], opponents=[], keeper=None, decisions=0.5,
                composure=0.5, dribbling=0.5, traits=(), risk=0.0, absorb={}, passer=PASSER)
    base.update(kw)
    base.setdefault("heading", 0.0 if base["goal_x"] > 52.5 else math.pi)
    base.setdefault("moving", [(ox, oy, 0.0, 0.0, (ox, oy) == base["keeper"])
                               for ox, oy in base["opponents"]])
    return D.Scene(**base)


def test_shot_estimate_follows_the_sourced_rates_by_distance():
    central = lambda d: D.shot_estimate(105 - d, 34, 105, [], None)  # noqa: E731
    # Nobody in the cone: better than the average shot the published rates describe.
    assert math.isclose(central(3), 0.31 * D.CLEAR_SHOT) and math.isclose(central(11), 0.177 * D.CLEAR_SHOT)
    assert math.isclose(central(20), 0.053 * D.CLEAR_SHOT) and math.isclose(central(30), 0.023 * D.CLEAR_SHOT)
    assert central(2) <= 0.31 * D.CLEAR_SHOT  # never near-certain: close shots are contested in real matches
    assert central(11) > D.shot_estimate(105 - 11, 10, 105, [], None)  # a tight angle is worse

def test_the_typical_shot_keeps_the_published_rate_and_defenders_do_not_compound():
    # Lucey et al. 2015: 11.59% unscreened, 7.49% screened, 23.18% unscreened.
    assert math.isclose(0.2318 * D.CLEAR_SHOT + (1 - 0.2318) * D.SCREENED_SHOT, 1.0)
    one = D.shot_estimate(90, 34, 105, [(97, 34)], None)
    three = D.shot_estimate(90, 34, 105, [(97, 34), (96, 33), (98, 35)], None)
    assert one == three == D.shot_estimate(90, 34, 105, [], None) * D.SCREENED_SHOT / D.CLEAR_SHOT
    usual = offball.keeper_spot(90, 34, 105)
    on_spot = D.shot_estimate(90, 34, 105, [], usual)
    assert math.isclose(on_spot, D.shot_estimate(90, 34, 105, [], None))  # his usual spot is the typical case


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
    s.moving = [(105 - ox, oy, -vx, vy, k) for ox, oy, vx, vy, k in s.moving]
    s.heading = math.pi
    s.passer = copy.copy(PASSER)  # a mirror image kicks with the other foot
    s.passer.foot = "left" if PASSER.foot == "right" else "right"
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
    conf = lambda opps: D.pass_confidence(scene(opponents=opps), 96.5, 34.0, 95.0, 34.0, 0.0, True)  # noqa: E731
    assert conf([(66.0, 34.0)]) == conf([])  # over his head
    assert conf([(92.0, 34.0)]) < conf([])  # but one where it comes down can get to it

def test_a_pass_is_led_toward_the_goal_being_attacked():
    assert D.pass_option(scene(), ("h9", 75.0, 34.0, 0.0)).target[0] > 75.0
    assert D.pass_option(mirror(), ("a9", 30.0, 34.0, 0.0)).target[0] < 30.0


def test_a_pass_the_receiver_cannot_get_to_in_time_is_less_certain():
    s = scene(x=60.0)
    conf = lambda tx, ty: D.pass_confidence(s, tx, ty, 70.0, 40.0, 0.0, False, 14.0, "h9")  # noqa: E731
    assert conf(70.0, 39.5) > 0.5  # played to his feet
    assert conf(70.0, 30.0) < 0.2 * conf(70.0, 39.5)  # 10 m from him: four times in five it has gone by


def test_an_opponent_on_the_dribble_path_makes_the_dribble_worse():
    free = max(o.value for o in D.options(scene(x=70.0)) if o.kind == "dribble")
    blocked = max(o.value for o in D.options(scene(x=70.0, opponents=[(73.0, 34.0), (72.0, 37.0),
                                                                     (72.0, 31.0)])) if o.kind == "dribble")
    assert blocked < free


def test_a_dribble_is_valued_by_the_published_threat_where_it_ends():
    from ninety.sim import threat
    s = scene(x=88.0)  # nobody near: the carry certainly works
    straight = next(o for o in D.options(s) if o.kind == "dribble")
    assert math.isclose(straight.value, threat.at(*straight.target, 105.0), rel_tol=1e-6)

def test_a_pass_is_valued_by_its_estimate_of_reaching_him_and_where_it_would_be_lost():
    s = scene(x=60.0, opponents=[(72.0, 40.0)])  # 6 m off the line at its midpoint
    mate = ("h9", 82.5, 34.0, 0.0)  # a 24 m ground pass to (84, 34)
    chosen = D.pass_option(s, mate)
    conf = D.pass_confidence(s, 84.0, 34.0, 82.5, 34.0, 0.0, chosen.lofted, chosen.pace, "h9")
    gain = D.value(84.0, 34.0, 105.0) * (0.7 + 0.3 * min(1.0, math.hypot(84.0 - 72.0, 6.0) / 5.0))
    expected = conf * gain - (1 - conf) * D.loss_cost(72.0, 34.0, 105.0)
    assert math.isclose(chosen.value, expected, rel_tol=1e-9)
    assert D.pass_option(scene(x=60.0), mate).value > chosen.value


def test_an_opponent_on_the_lane_is_a_risk_and_one_well_off_it_is_not():
    def conf(opponents):
        return D.pass_confidence(scene(x=60.0, opponents=opponents), 84.0, 34.0, 82.5, 34.0, 0.0, False, 10.0,
                                 "h9")
    free = conf([])
    by_offset = [conf([(72.0, 34.0 + off)]) for off in (0.0, 1.0, 2.0, 4.0, 8.0, 15.0)]
    assert by_offset[0] < 0.1 < 0.9 * free < by_offset[-1]
    assert all(a <= b + 1e-9 for a, b in zip(by_offset, by_offset[1:], strict=False))


def test_an_opponent_beyond_where_the_team_mate_takes_it_cannot_cut_it_out():
    """He is raced against the team-mate's take, not against the ball reaching his own nearest point."""
    def conf(opponents):
        return D.pass_confidence(scene(x=60.0, opponents=opponents), 75.0, 34.0, 75.0, 34.0, 0.0, False, 10.0,
                                 "h9")
    assert conf([(84.0, 34.0)]) > 0.9 * conf([])  # on the line, 9 m past him
    assert conf([(70.0, 35.0)]) < 0.5 * conf([])  # in foot reach of the line, before him


def test_a_body_in_the_lane_stops_a_ball_before_he_can_react_but_a_foot_needs_a_reaction():
    def conf(opponents):
        return D.pass_confidence(scene(x=60.0, opponents=opponents), 75.0, 34.0, 75.0, 34.0, 0.0, False, 14.0,
                                 "h9")
    assert conf([(63.0, 34.0)]) < 0.05  # standing on the line 3 m away: the ball hits him
    assert conf([(63.0, 35.0)]) > 0.9 * conf([])  # 1 m off it: in foot reach, but it is past before he reacts


def test_the_receivers_first_touch_decides_a_hard_pass():
    def conf(absorb):
        s = scene(x=60.0, absorb={"h9": absorb})
        return D.pass_confidence(s, 90.0, 34.0, 90.0, 34.0, 0.0, False, 14.0, "h9")
    assert conf(24.0) > 0.9 > 0.1 > conf(8.0)  # it arrives at about 14 m/s


def test_a_pass_that_leaves_the_pitch_first_is_lost():
    s = scene(x=60.0, y=60.0)
    assert D.pass_confidence(s, 72.0, 67.5, 72.0, 67.5, 0.0, False, 14.0, "h9") > 0.5  # he meets it first
    assert D.pass_confidence(s, 72.0, 67.5, 66.0, 58.0, 0.0, False, 14.0, "h9") < 0.05  # it runs out


def test_a_keeper_takes_a_ball_in_his_box_with_his_hands():
    def conf(keeper):
        s = scene(x=75.0, moving=[(97.0, 34.0, 0.0, 0.0, keeper)])
        return D.pass_confidence(s, 98.0, 34.0, 99.0, 30.0, 0.0, True, D.ARRIVE_MPS, "h9")
    assert conf(True) < conf(False)


def test_the_strikes_he_weighs_reproduce_his_kick_error():
    from ninety.sim.profiles import Profile
    passer = Profile.generate("CM", random.Random(3))
    s = scene(x=60.0, passer=passer, heading=0.0, opponents=[(61.5, 35.0)])
    for lofted in (False, True):
        nodes = D.strike_nodes(s, 85.0, 34.0, lofted, 10.0)
        g0, up0 = D.loft_launch(25.0) if lofted else (D.launch_speed(25.0, 10.0), 0.0)
        speed, nearest = math.hypot(g0, up0), math.hypot(1.5, 1.0)
        dir_sd, speed_sd, loft_sd, foot = passer.strike_error("passing", speed, nearest, 1.0, 0.0)
        assert math.isclose(sum(w for w, *_ in nodes), 1.0)
        assert math.isclose(sum(w * d for w, d, *_ in nodes), 0.0, abs_tol=1e-12)
        assert math.isclose(sum(w * d * d for w, d, *_ in nodes), math.radians(dir_sd) ** 2)
        speeds = [math.hypot(g, u) / math.hypot(g0, up0) for _, _, g, u in nodes]
        mean = sum(w * v for (w, *_), v in zip(nodes, speeds, strict=True))
        assert math.isclose(mean, foot)
        assert math.isclose(sum(w * (v - mean) ** 2 for (w, *_), v in zip(nodes, speeds, strict=True)),
                            (speed_sd * foot) ** 2)
        lofts = [math.atan2(u, g) - math.atan2(up0, g0) for _, _, g, u in nodes]
        spread = sum(w * a * a for (w, *_), a in zip(nodes, lofts, strict=True))
        assert math.isclose(spread, math.radians(loft_sd) ** 2 if lofted else 0.0, abs_tol=1e-12)
    passer.foot = "right"  # the pass goes 60 degrees to his left: struck with his left, weaker foot
    turned = scene(x=60.0, passer=passer, heading=math.radians(-60))
    across = D.strike_nodes(turned, 85.0, 34.0, False, 10.0)
    shares = [g / D.launch_speed(25.0, 10.0) for _, _, g, _ in across]
    mean = sum(w * v for (w, *_), v in zip(across, shares, strict=True))
    assert math.isclose(mean, passer.weak_foot_speed())
    assert passer.weak_foot_speed() < 1


def test_a_worse_passer_is_less_sure_of_a_pass_through_a_narrow_gap():
    """Two opponents 4 m out, 1.6 m apart: the ball is past them before they react, so only a
    strike off line hits one; a wider kick error sends more of his strikes into them."""
    from ninety.sim.profiles import Profile
    passer = Profile.generate("CM", random.Random(3))
    gap = [(64.0, 34.8), (64.0, 33.2)]

    def conf(skill):
        passer.attributes["passing"] = skill
        s = scene(x=60.0, passer=passer, heading=0.0, opponents=gap)
        return D.pass_confidence(s, 85.0, 34.0, 85.0, 34.0, 0.0, False, 14.0, "h9")
    poor, average, good = conf(0.1), conf(0.5), conf(0.9)
    assert 0.3 < average < 0.7  # genuinely in doubt
    assert poor < average < good and good - poor > 0.1


def test_carrying_on_with_a_dribble_is_slightly_preferred_and_holding_gets_no_bonus():
    def first(kind, s):
        return next(o for o in D.options(s) if o.kind == kind).value
    assert math.isclose(first("dribble", scene(current="dribble")) - first("dribble", scene()), D.STICKY)
    assert math.isclose(first("hold", scene(current="dribble")), first("hold", scene()))  # raw best


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


def test_a_failed_pass_is_costed_where_it_would_end_if_that_is_worse():
    s = scene(x=40.0, y=34.0, opponents=[(28.0, 37.0)])
    back = D.pass_option(s, ("h4", 18.5, 34.0, 0.0))  # 20 m back along the ground, toward his own goal
    conf = D.pass_confidence(s, *back.target, 18.5, 34.0, 0.0, back.lofted, back.pace)
    gain = D.value(*back.target, 105.0, s.opponents) * (0.7 + 0.3 * min(1.0, math.hypot(8.0, 3.0) / 5.0))
    at_target = D.loss_cost(*back.target, 105.0)
    assert at_target > D.loss_cost(30.0, 34.0, 105.0)  # the end is worse than the midpoint here
    assert math.isclose(back.value, conf * gain - (1 - conf) * at_target, rel_tol=1e-9)


def test_the_first_touch_is_judged_on_the_speed_a_lofted_ball_comes_down_at():
    points, _ = D.flight(*D.loft_launch(30.0))
    down = next(p for p in points[1:] if p[4] < 0 and p[2] <= D.FOOT_REACH_Z)
    landing, launch = math.hypot(down[3], down[4]), math.hypot(*D.loft_launch(30.0))
    assert landing < 0.8 * launch  # drag slows it in the air

    def conf(absorb):
        s = scene(x=60.0, absorb={"h9": absorb})
        return D.pass_confidence(s, 90.0, 34.0, 90.0, 34.0, 0.0, True, D.ARRIVE_MPS, "h9")
    assert conf(landing + 4.0) > 0.8 > 0.2 > conf(landing - 4.0)  # the landing speed, not the launch

def test_a_shot_into_a_crowd_risks_losing_the_ball_where_he_stands():
    shoot = lambda s: next(o for o in D.options(s) if o.kind == "shoot")  # noqa: E731
    clear = scene(x=75.0)
    crowded = scene(x=75.0, opponents=[(80.0, 34.0), (85.0, 33.0)])
    q_clear = D.shot_estimate(75.0, 34.0, 105.0, [], None)
    q_crowd = D.shot_estimate(75.0, 34.0, 105.0, crowded.opponents, None)
    assert math.isclose(shoot(clear).value, q_clear - (1 - q_clear) * D.loss_cost(99.5, 34.0, 105.0))
    blocked = 1 - D.BLOCKER_FACTOR ** 2
    lost = blocked * D.loss_cost(75.0, 34.0, 105.0) + (1 - blocked) * D.loss_cost(99.5, 34.0, 105.0)
    assert math.isclose(shoot(crowded).value, q_crowd - (1 - q_crowd) * lost)


def test_the_keeper_is_counted_once_in_a_shot_but_can_still_stop_a_dribble():
    k = (103.0, 34.0)
    assert D.shot_estimate(90, 34, 105, [k], k) == D.shot_estimate(90, 34, 105, [], k)
    free = max(o.value for o in D.options(scene(x=97.0, keeper=k)) if o.kind == "dribble")
    with_keeper = scene(x=97.0, keeper=k, opponents=[k])
    keeper_there = max(o.value for o in D.options(with_keeper) if o.kind == "dribble")
    assert keeper_there < free


def ramp(near_goal: float, far: float, finishing: float = 0.1) -> Tables:
    """Made-up tables: possessions worth near_goal next to the goal attacked, falling to far at
    the other end; shots going in at `finishing` from anywhere."""
    threat = Table([[near_goal + (far - near_goal) * i / (CELLS_X - 1)] * CELLS_Y for i in range(CELLS_X)])
    return Tables(threat, Table([[finishing] * CELLS_Y for _ in range(CELLS_X)]))


def test_a_measured_table_values_possession_and_loss_for_both_directions(monkeypatch):
    monkeypatch.setattr(D, "POSSESSION", ramp(0.3, 0.01))
    assert D.value(100.0, 34.0, 105.0) > D.value(20.0, 34.0, 105.0)
    assert math.isclose(D.value(100.0, 34.0, 105.0), D.value(5.0, 34.0, 0.0))  # mirrored
    assert D.loss_cost(10.0, 34.0, 105.0) > D.loss_cost(90.0, 34.0, 105.0)  # losing it near our goal hurts
    table = D.POSSESSION.threat
    assert D.value(60.0, 20.0, 105.0) == table.at(60.0, 20.0, 105.0)  # the measured number, as is
    assert D.loss_cost(60.0, 20.0, 105.0) == table.at(60.0, 20.0, 0.0)  # theirs, from their side


def test_a_measured_table_makes_keeping_the_ball_beat_a_hopeless_shot(monkeypatch):
    s = scene(x=70.0)  # 35 m out
    # Possessions from 35 m score 3% of the time; shots from there go in 1% of the time.
    monkeypatch.setattr(D, "POSSESSION", ramp(0.3, 0.0, finishing=0.01))
    shoot = next(o for o in D.options(s) if o.kind == "shoot").value
    hold = next(o for o in D.options(s) if o.kind == "hold").value
    assert hold > shoot
    assert max(D.options(s), key=lambda o: o.value).kind != "shoot"


def test_a_missed_shot_is_never_a_reward(monkeypatch):
    monkeypatch.setattr(D, "POSSESSION", ramp(0.3, 0.0, finishing=0.0))
    s = scene(x=70.0)
    assert next(o for o in D.options(s) if o.kind == "shoot").value <= 0.0


def test_the_shot_chance_is_the_measured_rate_scaled_by_the_situation(monkeypatch):
    monkeypatch.setattr(D, "POSSESSION", ramp(0.3, 0.0, finishing=0.2))
    assert math.isclose(D.shot_chance(scene(x=90.0)), 0.2 * D.CLEAR_SHOT)  # the measured average, unscreened
    blocked = scene(x=90.0, opponents=[(97.0, 34.0)])
    assert math.isclose(D.shot_chance(blocked), 0.2 * D.SCREENED_SHOT)


def test_holding_is_worth_the_best_move_a_moment_later_never_more():
    s = scene(x=60.0, mates=[("h9", 75.0, 34.0, 0.0)])  # no pressure
    opts = D.options(s)
    hold = next(o for o in opts if o.kind == "hold").value
    best = max(o.value for o in opts if o.kind != "hold")
    assert math.isclose(hold, best * (1 - D.HOLD_DECAY))
    assert hold < best  # waiting never beats the move he is waiting to make


def test_when_every_move_is_bad_waiting_is_a_little_worse_still(monkeypatch):
    monkeypatch.setattr(D, "pressure", lambda _s: 0.0)  # unpressed: he could wait, but not for ever
    hopeless = [(60.0 + dx, 34.0 + dy) for dx in (2.0, 4.0) for dy in (-3.0, 0.0, 3.0)]
    s = scene(x=60.0, opponents=hopeless)
    opts = D.options(s)
    best = max(o.value for o in opts if o.kind != "hold")
    assert best < 0  # the premise: nothing good to do
    assert max(opts, key=lambda o: o.value).kind != "hold"


def test_under_pressure_holding_is_never_better_than_both_of_its_outcomes(monkeypatch):
    """With pressure he either loses the ball where he stands or still makes his move; holding is
    a mix of the two, so it can never beat both (the old form valued the lost share at nothing)."""
    hopeless = [(60.0 + dx, 34.0 + dy) for dx in (2.0, 4.0) for dy in (-3.0, 0.0, 3.0)]
    lost_here = -D.loss_cost(60.0, 34.0, 105.0)
    for p in (0.0, 0.3, 0.6, 0.9, 1.0):
        monkeypatch.setattr(D, "pressure", lambda _s, p=p: p)
        opts = D.options(scene(opponents=hopeless))
        best = max(o.value for o in opts if o.kind != "hold")
        hold = next(o for o in opts if o.kind == "hold").value
        assert best < 0 and hold < max(best, lost_here)
    calm = []
    for p in (0.0, 0.5, 1.0):
        monkeypatch.setattr(D, "pressure", lambda _s, p=p: p)
        calm.append(next(o for o in D.options(scene(opponents=[(75.0, 50.0)])) if o.kind == "hold").value)
    assert calm[0] > calm[1] > calm[2]


def test_choice_randomness_is_relative_to_how_different_the_options_are():
    rng = random.Random(4)
    s = scene(x=60.0, decisions=1.0, mates=[("h9", 75.0, 34.0, 0.0)])
    best = max(D.options(s), key=lambda o: o.value).kind
    picks = Counter(D.choose(s, rng).kind for _ in range(500))
    assert picks[best] / 500 > 0.7  # a good decision-maker usually takes the best, even in midfield


def test_the_passer_picks_the_pace_the_lane_needs():
    mate = ("h9", 72.5, 34.0, 0.0)  # a 14 m pass: too short to loft, so pace is the answer
    open_lane = D.pass_option(scene(x=60.0), mate)
    tight = D.pass_option(scene(x=60.0, opponents=[(68.0, 36.0)]), mate)  # 2 m off the lane
    assert not tight.lofted and tight.pace > open_lane.pace
    assert D.launch_speed(20.0, 14.0) > D.launch_speed(20.0, 6.0)

def test_options_closer_than_the_noise_floor_are_close_to_a_coin_flip():
    rng = random.Random(9)
    s = scene(x=60.0, decisions=1.0)
    opts = [D.Option("a", 0.0200), D.Option("b", 0.0201)]
    picks = Counter()
    original = D.options
    D.options = lambda _s: opts
    try:
        for _ in range(2000):
            picks[D.choose(s, rng).kind] += 1
    finally:
        D.options = original
    assert picks["a"] > 600  # a 0.0001 edge does not decide it


def test_from_fifteen_metres_he_chooses_between_along_the_ground_and_over_the_top():
    blocked = scene(x=60.0, opponents=[(67.0, 34.0), (70.0, 34.5)])  # the ground lane is shut
    over = D.pass_option(blocked, ("h9", 85.0, 34.0, 0.0))
    assert over.lofted
    short = D.pass_option(scene(x=60.0), ("h9", 70.0, 34.0, 0.0))
    assert not short.lofted  # under 15 m it stays on the ground



def test_the_keeper_term_is_how_much_goal_he_leaves_open():
    usual = offball.keeper_spot(85, 34, 105)
    off = (usual[0], usual[1] + 3.0)  # caught three metres off his line
    assert offball.open_goal_share(85, 34, 105, off) > offball.open_goal_share(85, 34, 105, usual)
    assert D.shot_estimate(85, 34, 105, [], off) > D.shot_estimate(85, 34, 105, [], usual)
    assert 0.0 <= offball.open_goal_share(85, 34, 105, usual) < 1.0
    assert D.shot_estimate(104, 34, 105, [], (95.0, 60.0)) <= 1.0  # a probability, even into an empty net


def test_the_keeper_stays_home_against_far_shots_and_comes_out_against_near_ones():
    depth = lambda d: 105 - offball.keeper_spot(105 - d, 34, 105)[0]  # noqa: E731
    assert depth(20) < depth(6)  # his dive has time against a far shot; a near one he must smother
    assert offball.KEEPER_DEPTH[0] <= depth(16) <= offball.KEEPER_DEPTH[1]
    assert depth(50) == offball.KEEPER_DEPTH[1]  # out of shooting range: he sweeps


def test_the_keeper_stands_on_the_bisector_of_the_posts_not_the_line_to_the_goal_centre():
    import math as m
    x, y = offball.keeper_spot(95, 10, 105)  # a tight angle
    a1, a2 = m.atan2(30.34 - 10, 10), m.atan2(37.66 - 10, 10)
    assert abs(m.atan2(y - 10, x - 95) - (a1 + a2) / 2) < 1e-6


def test_before_he_reacts_only_his_body_stops_a_shot_in_the_shooters_judgement_too():
    from ninety.sim import ball
    from ninety.sim.body import BODY_RADIUS
    z = offball.KEEPER_COM_Z  # where his reach across is widest
    assert offball.keeper_reach_m(0.1, 0.36, z) == BODY_RADIUS + ball.RADIUS
    full = offball.KEEPER_STAND_REACH_M + offball.KEEPER_DIVE_EXTRA_M + offball.KEEPER_DIVE_TRAVEL_M
    assert offball.keeper_reach_m(2.0, 0.36, z) == pytest.approx(full)


def test_a_keeper_behind_the_shooter_covers_nothing():
    assert offball.open_goal_share(95, 34, 105, (90, 34)) == 1.0


def test_with_the_ball_almost_on_his_line_the_keeper_stays_on_it_between_the_posts():
    x, y = offball.keeper_spot(104.5, 0.5, 105)
    assert (x, y) == (105, 34 - 3.66)  # at the near post


def test_out_of_shooting_range_the_keeper_sweeps_from_his_furthest_spot():
    depth = lambda d: 105 - offball.keeper_spot(105 - d, 34, 105)[0]  # noqa: E731
    assert depth(25) < offball.KEEPER_DEPTH[1] == depth(50)


def test_keeper_coverage_has_no_cliff_with_distance():
    # Averaged over the speeds shots are struck at, the open share falls smoothly with distance and a
    # keeper caught off his spot still matters from range.
    share = lambda d: offball.open_goal_share(105 - d, 34, 105, offball.keeper_spot(105 - d, 34, 105))  # noqa: E731
    shares = [share(d) for d in (22, 24, 26, 28)]
    assert all(a >= b for a, b in zip(shares, shares[1:], strict=False))
    off = offball.open_goal_share(75, 34, 105, (100.0, 40.0))
    assert off > offball.open_goal_share(75, 34, 105, offball.keeper_spot(75, 34, 105))


def test_screened_is_a_defender_in_the_triangle_to_the_posts_as_in_the_source():
    assert D.shot_estimate(90, 34, 105, [(100.0, 44.0)], None) == D.shot_estimate(90, 34, 105, [], None)
    assert D.shot_estimate(90, 34, 105, [(97.0, 34.0)], None) < D.shot_estimate(90, 34, 105, [], None)


def test_the_dive_never_beats_the_cited_peak_speed():
    step = 0.001
    travel = offball.KEEPER_DIVE_TRAVEL_M
    speeds = [(offball.dive_progress(t + step) - offball.dive_progress(t)) / step * travel
              for t in [i * step for i in range(int(offball.DIVE_TIME_S / step))]]
    peak = max(speeds)
    assert 3.6 <= peak <= 4.0 and offball.dive_progress(offball.DIVE_TIME_S) == pytest.approx(1.0)


def test_the_shot_estimate_is_continuous_in_distance_with_the_keeper_off_his_spot():
    def q(d, off):
        kx, ky = offball.keeper_spot(105 - d, 34, 105)
        return D.shot_estimate(105 - d, 34, 105, [], (kx, ky + off))
    for off in (0.0, 1.0, 3.0):
        values = [q(d, off) for d in range(18, 40)]
        assert all(b <= a + 1e-9 for a, b in zip(values, values[1:], strict=False))  # never up with distance
    assert q(30, 1.0) < 0.1  # the old ratio gave 0.64 here


def test_keeper_coverage_is_averaged_over_shot_speeds_so_it_never_hits_zero_too_early():
    usual = offball.keeper_spot(79, 34, 105)  # 26 m out, where a single speed left nothing open
    assert offball.open_goal_share(79, 34, 105, usual) > 0


def test_a_one_on_one_with_the_keeper_rushing_out_is_never_hopeless_nor_certain():
    kx, ky = offball.close_down_spot((91.0, 34.0), 105.0)
    q = D.shot_estimate(91, 34, 105, [], (kx, ky))
    assert 0 < q < D.shot_estimate(91, 34, 105, [], None)
    assert D.shot_estimate(91, 34, 105, [], (60.0, 34.0)) < 1.0  # an empty net is likely, not certain


def test_the_keeper_term_is_the_published_save_rate_with_odds_scaled_by_coverage():
    usual = offball.keeper_spot(90, 34, 105)
    assert math.isclose(D.shot_estimate(90, 34, 105, [], usual), D.shot_estimate(90, 34, 105, [], None))
    near_post = (usual[0], usual[1] - 1.0)
    far = (usual[0], usual[1] + 2.5)
    assert D.shot_estimate(90, 34, 105, [], near_post) < D.shot_estimate(90, 34, 105, [], far)



def test_an_opponent_just_short_of_the_lane_is_nearly_as_much_a_risk_as_one_who_just_reaches_it():
    """No cliff: one who cannot quite make it is raced by how late he would be."""
    def conf(off):
        s = scene(x=60.0, opponents=[(68.0, 34.0 + off)])
        return D.pass_confidence(s, 74.0, 34.0, 72.5, 34.0, 0.0, False, 6.0, "h9")
    confs = [conf(1.5 + k * 0.01) for k in range(61)]
    assert all(b - a < 0.02 for a, b in zip(confs, confs[1:], strict=False))
    assert all(a <= b + 1e-9 for a, b in zip(confs, confs[1:], strict=False))
    assert confs[0] < 0.5 and conf(8.0) > 0.9


def test_any_team_mate_who_gets_there_first_takes_it():
    s = scene(x=60.0, mates=[("h9", 90.0, 50.0, 0.0)])
    alone = D.pass_confidence(s, 90.0, 34.0, 90.0, 50.0, 0.0, False, 14.0, "h9")  # 16 m from him
    s.mates.append(("h8", 80.0, 34.0, 0.0))  # standing on its path
    assert alone < 0.1 < 0.5 < D.pass_confidence(s, 90.0, 34.0, 90.0, 50.0, 0.0, False, 14.0, "h9")


def _crossing(points, height_lo, height_hi):
    """Metres along and seconds of the first path point coming down through this band of heights."""
    return next((a, t) for t, a, z, _, vz in points if vz < 0 and height_lo <= z <= height_hi)


def test_after_he_reacts_a_ball_at_his_feet_is_his_to_play_and_one_at_his_chest_hits_him():
    react = D.perception.CHOICE_REACTION_S
    ground, _ = D.flight(D.launch_speed(20.0, 10.0), 0.0)
    hit = lambda points, along: D.body_hit(points, 9.0, 0.0, 0.0, 1.0, 0.0, along, 0.0, 0.0, 0.0,  # noqa: E731
                                          react, 0.05, 0.0)
    assert hit(ground, 3.0) > 0.99  # 3 m out: there before he reacts
    assert hit(ground, 15.0) == 0.0  # after he reacts, at his feet: a touch, his race (reach_time)
    lofted, _ = D.flight(*D.loft_launch(30.0))
    along, t = _crossing(lofted, 1.2, 1.6)
    assert t > react and hit(lofted, along) > 0.99  # after he reacts, at body height: it hits him


def test_the_body_contact_chance_follows_how_sure_he_is_of_where_the_opponent_stands():
    points, _ = D.flight(D.launch_speed(20.0, 14.0), 0.0)
    react = D.perception.CHOICE_REACTION_S
    hit = lambda side, sigma: D.body_hit(points, 9.0, 0.0, 0.0, 1.0, 0.0, 3.0, side, 0.0, 0.0,  # noqa: E731
                                         react, sigma, 0.0)
    assert hit(0.6, 0.01) < 1e-6 < 0.2 < hit(0.6, 0.4)  # just outside contact: only if he is misjudged
    assert hit(0.0, 0.01) > 0.99 > 0.8 > hit(0.0, 0.4)  # dead on: misjudged, he may not be there


def test_nobody_plays_a_struck_ball_before_he_reacts():
    points, rests = D.flight(D.launch_speed(20.0, 14.0), 0.0)
    on_its_path = lambda react: D.reach_time(points, math.inf, rests, 0.0, 0.0, 1.0, 0.0,  # noqa: E731
                                            3.0, 0.0, 0.0, 0.0, react, 9.0)[0]
    assert on_its_path(0.365) > 0.365 > 0.2 > on_its_path(0.0)
    # Standing just where the ball is the frame before he reacts: still not his until he has.
    just_before = next(p for p in points if p[0] <= 0.365 < p[0] + D.RACE_STEP * D.DT)
    for late in (False, True):
        t, _ = D.reach_time(points, math.inf, rests, 0.0, 0.0, 1.0, 0.0, just_before[1], 0.0, 0.0, 0.0,
                            0.365, 9.0, late=late)
        assert t > 0.365


def test_running_away_from_the_ball_he_must_brake_first():
    from ninety.sim.body import can_get_to
    reach = lambda vx: can_get_to(D.AVERAGE_BODY, -3.0, 0.0, 1.0, vx, 0.0, 1.0)[0]  # noqa: E731
    assert reach(0.0)  # 2 m from standing in a second
    assert not reach(8.0)  # going the other way at 8 m/s: a second is spent braking


def test_a_first_touch_absorbs_the_balls_speed_relative_to_him():
    from ninety.sim.body import relative_speed
    assert relative_speed(10.0, 0.0, 0.0, 8.0, 0.0) == 2.0  # running with it
    assert relative_speed(10.0, 0.0, 0.0, -8.0, 0.0) == 18.0  # running into it
    assert math.isclose(relative_speed(10.0, 0.0, 3.0, 0.0, 0.0), math.sqrt(109.0))


def test_a_mishit_keeps_some_speed_and_no_strike_beats_a_foot():
    assert math.isclose(D.struck_speed(10.0, -0.9, 1.0), 3.0)  # the 0.3 floor
    assert D.struck_speed(30.0, 0.5, 1.0) == D.MAX_STRIKE_MPS
    assert math.isclose(D.struck_speed(10.0, 0.1, 0.88), 9.68)


def test_a_keeper_reaches_a_ball_at_rest_in_his_box_with_his_hands_too():
    points, rests = [(0.0, 0.0, 0.0, 1.0, 0.0), (3.4, 10.0, 0.0, 0.0, 0.0)], True  # at rest 10 m on
    # A keeper 18 m to the side of where it stops, inside his box (his goal line at x = 95).
    at = lambda box: D.reach_time(points, math.inf, rests, 80.0, 34.0, 1.0, 0.0,  # noqa: E731
                                  90.0, 52.0, 0.0, 0.0, 0.365, 99.0, box)[0]
    arms = D.offball.arm_reach_m(3.4 - 0.365)
    assert math.isclose(at(95.0), 0.365 + D.AVERAGE_BODY.time_to_cover(18.0 - arms))
    assert math.isclose(at(None), 0.365 + D.AVERAGE_BODY.time_to_cover(18.0 - D.CONTROL_M))
    assert at(95.0) < at(None)


def test_a_body_beyond_the_contact_cutoff_is_not_in_the_way_and_the_shortcut_agrees():
    points, _ = D.flight(D.launch_speed(20.0, 14.0), 0.0)
    r, sigma = D.BODY_RADIUS + D.ball.RADIUS, 0.1
    hit = lambda side: D.body_hit(points, 9.0, 0.0, 0.0, 1.0, 0.0, 3.0, side, 0.0, 0.0,  # noqa: E731
                                  0.365, sigma, 0.0)
    assert hit(r + 5.1 * sigma) == 0.0 < hit(r + 4.8 * sigma)
    assert not D.body_near(r + 5.1 * sigma, 0.0, sigma) and D.body_near(r + 4.9 * sigma, 0.0, sigma)


def test_an_opponent_running_away_from_the_lane_is_no_cliff_either():
    """Within reach but running away, he must brake first: the time he needs, and so the estimate,
    moves smoothly as he nears the edge of his reach (body.time_to_cover agrees with can_get_to)."""
    def conf(off):
        s = scene(x=60.0, opponents=[(70.0, 34.0 + off)], moving=[(70.0, 34.0 + off, 0.0, 5.0, False)])
        return D.pass_confidence(s, 74.0, 34.0, 72.5, 34.0, 0.0, False, 10.0, "h9")
    confs = [conf(0.9 + k * 0.001) for k in range(151)]  # charging no braking inside reach jumped 0.16 here
    assert all(abs(b - a) < 0.01 for a, b in zip(confs, confs[1:], strict=False))


def test_the_time_to_get_there_agrees_with_whether_he_gets_there():
    """body.time_to_cover is the inverse of body.can_get_to, braking included, inside reach or not."""
    from ninety.sim.body import can_get_to
    rng = random.Random(2)
    for _ in range(300):
        dx, along = rng.uniform(0.01, 12.0), rng.uniform(-8.0, 8.0)  # a point dx ahead, his speed toward it
        need = D.AVERAGE_BODY.time_to_cover(dx - D.CONTROL_M, along)
        assert can_get_to(D.AVERAGE_BODY, dx, 0.0, D.CONTROL_M, along, 0.0, need + 1e-3)[0]
        if need > 0:
            assert not can_get_to(D.AVERAGE_BODY, dx, 0.0, D.CONTROL_M, along, 0.0, need - 1e-3)[0]


def test_a_ball_is_out_only_once_the_whole_of_it_has_crossed_the_line():
    """Law 9, one test for the engine (engine.went_out) and the passer's race."""
    r = D.ball.RADIUS
    # On each line, and which way is out: both goal lines, both touchlines.
    for x, y, out_x, out_y in ((D.PITCH_X, 34.0, 1, 0), (0.0, 34.0, -1, 0), (50.0, D.PITCH_Y, 0, 1),
                               (50.0, 0.0, 0, -1)):
        assert not D.out_of_play(x + out_x * 0.9 * r, y + out_y * 0.9 * r)  # centre over, ball not
        assert D.out_of_play(x + out_x * 1.1 * r, y + out_y * 1.1 * r)  # the whole ball over


def test_nothing_of_the_keeper_reaches_a_ball_over_his_envelope_in_the_shooters_judgement():
    top = offball.reach_for(True, 2.0, 0.0, 2.0)[1]
    assert offball.keeper_reach_m(2.0, 0.36, top + 0.1) == 0.0
    assert offball.keeper_reach_m(2.0, 0.36, top - 0.1) > 0.0


def test_the_shooter_judges_the_keeper_over_the_heights_shots_are_aimed_at(monkeypatch):
    # His reach is widest at his waist: a shooter who weighed only waist-high shots would see less
    # of the goal open than one who weighs the heights shots are aimed at (P15).
    shooter, keeper = (75.0, 34.0), (103.0, 34.0)  # far enough out for his arms to have stretched
    open_share = offball.open_goal_share(*shooter, 105, keeper)
    monkeypatch.setattr(offball, "SHOT_AIM_Z_M", (offball.KEEPER_COM_Z, offball.KEEPER_COM_Z))
    assert open_share > offball.open_goal_share(*shooter, 105, keeper)


def test_he_strikes_at_most_the_published_approach_angle_off_his_facing_after_turning():
    # P16: facing within 60° he strikes now; otherwise he turns at 350°/s until he is, then strikes at 60°.
    assert D.strike_turn(0.0, 1.0, math.tan(math.radians(40))) == pytest.approx((40.0, 0.0))
    turn, wait = D.strike_turn(0.0, math.cos(math.radians(150)), math.sin(math.radians(150)))
    assert turn == pytest.approx(60.0) and wait == pytest.approx(math.radians(90) / math.radians(350))


def test_the_estimate_and_the_engine_share_one_strike_rule():
    from ninety.sim.engine import Engine
    e = Engine(1)
    c = e.by_id["h6"]
    c.x, c.y = 40.0, 34.0
    for heading, side in ((0.0, 0.21), (math.radians(70), 0.21), (0.0, -0.21)):
        c.heading = heading
        e.ball = (c.x + side, c.y, 0.0, 0.0, 0.0, 0.0)
        assert e.can_strike(c, 60.0, 34.0) == D.can_strike(side, 0.0, heading, 60.0 - c.x - side, 0.0)


def test_how_far_he_must_turn_first_does_not_change_the_kick_he_then_strikes():
    from ninety.sim.profiles import Profile
    passer = Profile.generate("CM", random.Random(3))
    # Pass along +x; facing 60° or 150° off it, he strikes it 60° off either way (P16).
    near = D.strike_nodes(scene(passer=passer, heading=math.radians(60)), 85.0, 34.0, False, 10.0)
    far = D.strike_nodes(scene(passer=passer, heading=math.radians(150)), 85.0, 34.0, False, 10.0)
    assert len(near) == len(far)
    for a, b in zip(near, far, strict=True):
        assert a == pytest.approx(b)


def test_turning_first_gives_an_opponent_closing_on_the_lane_time_to_get_there():
    # An opponent 3 m off the lane, running at it: the turn's delay (P16) is time he uses.
    moving = [(70.0, 37.0, 0.0, -4.0, False)]
    facing = scene(moving=moving, heading=0.0)
    away = scene(moving=moving, heading=math.pi)
    sure = D.pass_confidence(facing, 85.0, 34.0, 85.0, 34.0, 0.0, False)
    late = D.pass_confidence(away, 85.0, 34.0, 85.0, 34.0, 0.0, False)
    assert late < sure


def test_a_throw_in_leaves_his_hands_at_once_whichever_way_he_faces(monkeypatch):
    # Law 15 / P16: a ball in his hands is thrown, not struck off his foot: no turn, no 60° cap.
    from ninety.sim.engine import Engine

    e = Engine(1)  # in his hands: the engine's own case (engine.can_strike), whichever way he faces
    taker = e.by_id["h4"]
    taker.heading, e.throw_by = math.pi, taker.id
    assert e.can_strike(taker, taker.x + 10.0, taker.y)
    turn, wait = D.strike_turn(math.pi, 1.0, 0.0, thrown=True)
    assert abs(turn) == pytest.approx(180.0) and wait == 0.0
    asked = []
    production = D.strike_turn

    def spy(*args):
        asked.append(args)
        return production(*args)
    monkeypatch.setattr(D, "strike_turn", spy)
    D.pass_confidence(scene(throw=True, heading=math.pi, ball_offset=(0.0, 0.0)), 70.0, 34.0, 70.0, 34.0,
                      0.0, True)
    assert asked and all(len(a) == 4 and a[3] for a in asked)


def test_a_thrown_pass_is_estimated_with_no_kicking_side():
    passer = Profile.generate("CM", random.Random(3))
    a = D.strike_nodes(scene(passer=passer, heading=math.radians(10), throw=True), 85.0, 34.0, True, 10.0)
    b = D.strike_nodes(scene(passer=passer, heading=math.radians(55), throw=True), 85.0, 34.0, True, 10.0)
    assert a == pytest.approx(b)  # as engine.execute throws it (hands=True)
    c = D.strike_nodes(scene(passer=passer, heading=math.radians(55)), 85.0, 34.0, True, 10.0)
    assert c != pytest.approx(a)  # a kick at that angle is not
