"""On-ball decisions score options from what the player believes; the scoring behaves like football."""

import math
import random
from collections import Counter

import pytest

from ninety.sim import decisions as D
from ninety.sim import offball
from ninety.sim.value import CELLS_X, CELLS_Y, Table, Tables


@pytest.fixture(autouse=True)
def hand_written_values(monkeypatch):
    """These tests pin the decision rules, not whatever table was last measured."""
    monkeypatch.setattr(D, "POSSESSION", None)


def scene(**kw) -> D.Scene:
    base = dict(x=60.0, y=34.0, goal_x=105.0, mates=[], opponents=[], keeper=None, decisions=0.5,
                composure=0.5, dribbling=0.5, traits=(), risk=0.0)
    base.update(kw)
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


def test_a_dribble_is_valued_by_the_published_threat_where_it_ends():
    from ninety.sim import threat
    s = scene(x=88.0)  # nobody near: the carry certainly works
    straight = next(o for o in D.options(s) if o.kind == "dribble")
    assert math.isclose(straight.value, threat.at(*straight.target, 105.0), rel_tol=1e-6)

def test_a_lane_is_judged_where_the_opponent_meets_the_line_not_by_his_distance_from_the_passer():
    s = scene(x=60.0)
    mate = ("h9", 82.5, 34.0, 0.0)  # a 24 m ground pass to (84, 34)
    free = D.pass_option(s, mate)
    s.opponents = [(72.0, 40.0)]  # 6 m off the line at its midpoint
    chosen = D.pass_option(s, mate)
    v0 = D.launch_speed(24.0, chosen.pace)
    conf = D.sigmoid((D.generic_time(5.0) - D.ground_time(v0, 12.0)) / D.LANE_MARGIN_S)
    receive = D.sigmoid((D.ground_time(v0, 24.0) + 0.5 - D.generic_time(1.5)) / D.RECEIVE_MARGIN_S)
    receive *= D.sigmoid((D.CONTROL_EST_MPS - chosen.pace) / D.CONTROL_MARGIN_MPS)
    space = 0.7 + 0.3 * min(1.0, math.hypot(84.0 - 72.0, 6.0) / 5.0)
    gain = D.value(84.0, 34.0, 105.0) * space
    expected = conf * receive * gain - (1 - conf * receive) * D.loss_cost(72.0, 34.0, 105.0)
    assert math.isclose(chosen.value, expected, rel_tol=1e-9)
    assert free.value > expected


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


def test_the_control_estimate_uses_the_speed_a_lofted_ball_arrives_at():
    for d in (20.0, 30.0, 40.0):
        assert D.loft_arrival(d) < 0.8 * math.hypot(*D.loft_launch(d))  # drag slows it in the air
    assert D.loft_arrival(30.0) > D.loft_arrival(20.0)  # but a longer ball still lands faster


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



def test_screened_means_any_outfield_defender_nearer_the_goal_as_in_the_source():
    wide = [(100.0, 44.0)]  # 11 m from goal (he is 15 m), outside the posts' cone
    assert D.shot_estimate(90, 34, 105, wide, None) < D.shot_estimate(90, 34, 105, [], None)
    behind = [(85.0, 34.0)]
    assert D.shot_estimate(90, 34, 105, behind, None) == D.shot_estimate(90, 34, 105, [], None)


def test_the_keeper_term_is_how_much_goal_he_leaves_open():
    usual = offball.keeper_spot(85, 34, 105)
    assert math.isclose(D.open_goal_share(85, 34, 105, usual), D.open_goal_share(85, 34, 105, usual))
    off = (usual[0], usual[1] + 3.0)  # caught three metres off his line
    assert D.open_goal_share(85, 34, 105, off) > D.open_goal_share(85, 34, 105, usual)
    assert D.shot_estimate(85, 34, 105, [], off) > D.shot_estimate(85, 34, 105, [], usual)
    assert 0.0 <= D.open_goal_share(85, 34, 105, usual) < 1.0
    assert D.shot_estimate(104, 34, 105, [], (95.0, 60.0)) <= 1.0  # a probability, even into an empty net
