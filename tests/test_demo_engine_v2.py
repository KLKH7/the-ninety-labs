"""Demo engine v2 (GROUNDING V1 to V6): the causes behind the demo's missing take-ons, aimless
clearances and flat-footed keepers. Each test fails on main's rule."""

import math

from ninety.sim import decisions as D
from ninety.sim import offball
from ninety.sim.body import CS_MEAN, F0_MEAN, V0_MEAN, Body
from ninety.sim.engine import DT, Engine
from tests.test_decisions import scene


def test_the_carry_cap_is_derived_from_the_with_ball_sprint():
    # V1: with the cap, an average body takes 20 m from standing 1/0.91 as long as without it
    # (Preissler et al. 2023: 20.37 against 22.39 km/h). Main carried at 2.5 to 4.5 m/s.
    body = Body(F0_MEAN, V0_MEAN, CS_MEAN)
    free, carried = body.time_to_cover(20.0), body.time_to_cover(20.0, 0.0, cap=D.carry_speed())
    assert abs(carried * D.WITH_BALL_SHARE - free) < 1e-6
    assert D.carry_speed() > D.dribble_speed(1.0) + 1.0  # faster than main let the best dribbler go


def test_a_carry_into_space_beats_a_defender_who_must_run_to_it():
    # V1: a defender 4 m off the line of a carry straight at goal, standing. At main's carrying pace
    # he gets there first; at the measured pace the carry is more often the carrier's.
    s = scene(x=70.0, y=34.0, opponents=[(73.0, 38.0)])
    fast = next(o for o in D.options(s) if o.kind == "dribble" and abs(o.target[1] - 34.0) < 1e-6)
    slow_s = scene(x=70.0, y=34.0, opponents=[(73.0, 38.0)], carry_mps=D.dribble_speed(0.5))
    slow = next(o for o in D.options(slow_s) if o.kind == "dribble" and abs(o.target[1] - 34.0) < 1e-6)
    assert fast.value > slow.value


def test_a_carrier_can_go_round_a_defender_between_at_him_and_well_away():
    # V2: carries at 0.4 and 1.2 rad either side of goal are on offer, besides 0 and 0.8.
    s = scene(x=70.0, y=34.0)
    turns = sorted(round(math.atan2(o.target[1] - 34.0, o.target[0] - 70.0), 3)
                   for o in D.options(s) if o.kind == "dribble")
    assert turns == [-1.2, -0.8, -0.4, 0.0, 0.4, 0.8, 1.2]


def _shot(e: Engine, b: tuple):
    k = e.keeper("away")
    k.x, k.y, k.vx, k.vy = 104.0, 34.0, 0.0, 0.0
    shooter = e.by_id["h9"]
    shooter.x, shooter.y, shooter.vx, shooter.vy = b[0] - 1.0, b[1], 0.0, 0.0
    e.possessor = None
    e.kicked = {"type": "shot", "team": "home", "player": shooter.id, "x": b[0], "y": b[1]}
    e.last_touch = shooter.id
    e.ball = b
    e.kicked_at = e.free_since = e.t
    return k


def test_a_keeper_leaves_a_shot_going_over_the_bar_that_his_hands_could_reach():
    # V5: a shot rising over his head and over the bar. Main's keeper took it overhead.
    e = Engine(1)
    b = (94.0, 34.0, 2.3, 20.0, 0.0, 4.0)
    k = _shot(e, b)
    assert e.going_wide("home")  # the premise: it crosses the line over the bar,
    when, _, z = e.ball_at_x(k.x)
    _, top = offball.reach_for(True, 0.0, z, when)
    assert z < top  # and passes within his reach
    for _ in range(int(1.5 / DT)):
        e.step()
    assert e.shot_touched_by != "keeper" and e.held_by != k.id


def test_a_keeper_takes_a_shot_on_target_within_his_standing_reach():
    # V5's other side: the same height under the bar, it is his.
    e = Engine(1)
    k = _shot(e, (94.0, 34.0, 1.2, 20.0, 0.0, 0.0))
    assert not e.going_wide("home") and e.heading_on_target("home")
    for _ in range(int(1.5 / DT)):
        e.step()
        if e.shot_touched_by:
            break
    assert e.shot_touched_by == "keeper"
    assert k.id in (e.held_by, e.last_touch)


def test_a_parry_goes_back_and_wide_not_on_along_his_arm():
    # V4: a ball met by his hand 1.3 m to his left as he dives that way, going toward his goal,
    # comes back off his palm and out to that side with his dive. Main bounced it off his spine's
    # normal: across, still on toward goal.
    e = Engine(1)
    k = e.keeper("away")
    k.x, k.y, k.vx, k.vy, k.heading = 104.0, 34.0, 0.0, 3.8, math.pi  # facing up the pitch, diving
    e.ball = (104.0, 35.3, 1.0, 25.0, 0.0, 0.0)
    e.deflect(k, 104.0, 35.3, 1.0, 0.4, (104.0, 34.0, 0.0), palm=True)
    assert e.ball[3] < 0  # back away from his goal
    assert e.ball[4] > 0  # and out to the side he dived
    e.ball = (104.0, 35.3, 1.0, 25.0, 0.0, 0.0)
    e.deflect(k, 104.0, 35.3, 1.0, 0.4, (104.0, 34.0, 0.0))
    assert e.ball[3] > 0  # off the spine's normal (a body), it goes on


def test_a_clearance_is_aimed_where_his_side_can_win_it():
    # V6: in his own third, a team-mate alone 33 m up the far side and an opponent waiting on the
    # default aim. Main aimed at the default spot whatever was there (an even contest).
    s = scene(x=12.0, y=20.0, mates=[("h9", 45.0, 50.0, 0.0)], opponents=[(57.0, 20.0)])
    clear = next(o for o in D.options(s) if o.kind == "clear")
    assert math.hypot(clear.target[0] - 45.0, clear.target[1] - 50.0) < 1e-6
    default = D.clear_value(s, s.x + D.CLEAR_AHEAD_M, D.CLEAR_IN_FROM_LINE_M)
    assert clear.value > default


def test_the_with_ball_share_is_the_cited_figure():
    # V1: Preissler et al. 2023, 20.37 against 22.39 km/h over 20 m.
    assert D.WITH_BALL_SHARE == 20.37 / 22.39
    assert 6.0 < D.carry_speed() < 6.5  # derived, about 6.2 m/s for an average fresh body


def test_the_engine_tells_the_carrier_his_own_carrying_pace_and_velocity():
    # V1: the carrier judges a carry by his own body now (P10) and the speed he has, as he executes it.
    e = Engine(1)
    p = e.by_id["h7"]
    p.vx, p.vy = 3.0, -1.0
    e.possessor = p.id
    e.ball = (p.x + 0.3, p.y, 0.0, 0.0, 0.0, 0.0)
    s = e.scene_for(p)
    assert s.carry_mps == D.carry_speed(p.physique.top_speed())
    assert s.velocity == (3.0, -1.0)


def test_a_keeper_holds_with_both_hands_within_his_standing_reach_and_less_at_full_stretch():
    # V4: his hands' full hold within standing reach; half of it halfway into the dive's extra
    # stretch; nothing at full stretch.
    full, stand, extra = 25.0, offball.KEEPER_STAND_REACH_M, offball.KEEPER_DIVE_EXTRA_M
    assert Engine.hold_mps(full, 0.3) == full and Engine.hold_mps(full, stand) == full
    assert abs(Engine.hold_mps(full, stand + extra / 2) - full / 2) < 1e-9
    assert Engine.hold_mps(full, stand + extra) == 0.0


def test_one_look_holds_one_misjudgement_per_carry_direction():
    # V2: carries 0.4 rad apart are told apart by his held misjudgement (D4), not drawn as one.
    s = scene(x=70.0, y=34.0)
    keys = {D.taste_key(s, o) for o in D.options(s) if o.kind == "dribble"}
    assert len(keys) == 7


def test_a_shot_too_fast_to_hold_comes_back_off_his_palms_in_play():
    # V4 through the contact rule: a 35 m/s shot from 19 m crossing 0.9 m to his side at waist height (his
    # hands, within standing reach, hold at most 28 m/s) comes back off his palms, away from goal.
    e = Engine(1)
    k = _shot(e, (85.0, 34.9, 1.3, 35.0, 0.0, 2.0))
    for _ in range(int(1.0 / DT)):
        e.step()
        if e.last_touch == k.id:
            break
    assert e.last_touch == k.id and e.held_by != k.id
    assert e.ball[3] < 0  # back up the pitch, not on toward his goal
