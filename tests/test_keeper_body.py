"""The keeper's hands and body over a dive (GROUNDING P15, decision 0002 step 2).

The source numbers are written here as literals, not imported from the engine (lessons 25, 36):
- Higueras-Herbada et al. 2020, Fig. 2: hands crouched at about 0.5 to 0.65 m when the ball is struck;
  height known about 245 ms after it; then up about 1 m at about 4 m/s; high kicks average 2.03 m,
  low ones 0.37 m.
- Monteiro et al. 2022: the centre of mass rises 0.40 to 0.43 m on a dive at a high ball.
- P11: standing reach about 1 m, about 1.8 m stretched; shoulders 0.50 m across.
"""

import math

from ninety.sim import engine, offball
from ninety.sim.engine import Engine, first_within


def test_at_the_strike_his_hands_are_crouched_and_cover_neither_a_high_nor_a_low_ball():
    floor, top = offball.hands_band(0.0)
    assert floor <= 0.6 <= top  # crouched, about 0.5 to 0.65 m
    assert not floor <= 2.03 <= top and not floor <= 0.37 <= top
    assert offball.hands_band(0.24) == (floor, top)  # height not yet known


def test_once_the_height_is_known_his_hands_move_toward_it_at_about_4_mps():
    floor, top = offball.hands_band(0.245 + 0.25)  # a quarter second later: about 1 m further
    assert 1.6 <= top <= 2.0 and floor == 0.0
    assert offball.hands_band(0.245 + 0.1)[1] < 1.4  # never all at once
    assert offball.hands_band(10.0) == (0.0, 2.8)  # in the end, from the grass to a jump's reach


def test_down_after_a_dive_his_hands_reach_about_an_arm_above_the_ground():
    assert offball.reach_for(True, 1.0, 10.0, down=True)[2] <= 1.0 + 1e-9
    assert offball.reach_for(True, 1.0, 10.0, down=False)[2] == 2.8


def test_in_the_air_his_body_is_laid_out_and_rises_about_0_4_m_toward_a_high_ball():
    on_feet = offball.body_band(None)
    pushing = offball.body_band(0.1, 2.03)
    assert on_feet == pushing == (0.0, 1.8)  # until his last foot leaves the ground: as on his feet
    start = offball.dive_com_z(0.0, 2.03)
    end = offball.dive_com_z(5.0, 2.03)
    assert 0.40 <= end - start <= 0.43  # Monteiro et al. 2022
    lo, hi = offball.body_band(5.0, 2.03)
    assert math.isclose(hi - lo, 0.50 + 2 * 0.11, abs_tol=0.01)  # his shoulders' breadth, with the ball's
    assert hi < 1.8 + 0.11  # no longer a column up to his head


def test_toward_a_low_ball_his_body_goes_down_and_a_ball_over_it_is_not_met():
    lo, hi = offball.body_band(5.0, 0.37)
    assert lo <= 0.37 <= hi
    assert not lo <= 1.2 <= hi  # a ball at chest height passes over the laid-out body


def test_down_on_his_side_his_body_meets_only_a_low_ball():
    lo, hi = offball.body_band(None, down=True)
    assert lo == 0.0 and math.isclose(hi, 0.50 + 2 * 0.11, abs_tol=0.01)
    assert not lo <= 1.2 <= hi


def test_first_within_keeps_to_the_heights_and_the_side_asked():
    # a ball rolling across at 0.11 m, past a point 0.5 m off its line
    path = (-2.0, 0.5, 0.11, 4.0, 0.0, 0.0)
    assert first_within(*path, 0.0, 0.0, 1.0, 0.0, 1.0) is not None
    assert first_within(*path, 0.0, 0.0, 1.0, 0.3, 1.0) is None  # under the floor
    assert first_within(*path, 0.0, 0.0, 1.0, 0.0, 0.1) is None  # over the top
    ahead = first_within(*path, 0.0, 0.0, 1.0, 0.0, 1.0, (1.0, 0.0))
    behind = first_within(*path, 0.0, 0.0, 1.0, 0.0, 1.0, (-1.0, 0.0))
    assert math.isclose(ahead, 0.5) and behind < ahead  # x >= 0 from half way; behind from the start
    # dropping through the band: first in it once below the top
    drop = (0.0, 0.0, 2.0, 0.0, 0.0, -2.0)
    assert math.isclose(first_within(*drop, 0.0, 0.0, 1.0, 0.0, 1.5), 0.25)
    assert first_within(*drop, 0.0, 0.0, 1.0, 2.5, 3.0) is None


def _diving(e):
    k = e.keeper("away")
    k.x, k.y, k.vx, k.vy = 104.0, 34.0, 0.0, 0.0
    e.possessor = None
    e.kicked = {"type": "shot", "team": "home", "x": 90.0, "y": 34.0}
    e.kicked_at = e.free_since = e.t - 2.0
    e.dive = (k.id, e.t - 0.6, k.y, 1.0, e.t - 1.6, 0.0, 1.0)  # well into a dive toward +y
    return k


def test_mid_dive_he_reaches_further_ahead_of_it_than_behind_it():
    e = Engine(1)
    k = _diving(e)
    ahead = e.reach(k, 104.0, 35.5)[0]
    behind = e.reach(k, 104.0, 32.5)[0]
    assert ahead > 1.7 and behind == 1.0  # stretched toward the dive; only standing reach behind (P11)


def test_the_touch_rule_uses_the_dive_side():
    e = Engine(1)
    k = _diving(e)
    k.vx = k.vy = 0.0
    # a ball rolling past him 1.5 m behind the dive, 0.8 m behind it (in his standing reach), 1.5 m ahead
    for y, met in ((32.5, False), (33.2, True), (35.5, True)):
        e.ball = (104.0 - 0.5, y, 0.11, 10.0, 0.0, 0.0)
        e.ball = engine.ball.step(e.ball, engine.DT)
        before = (104.0 - 0.5, y, 0.11, 10.0, 0.0, 0.0)
        touched = []
        e.touched = lambda p, cx, cy, controls, seen=touched: (seen.append(p.id), True)[1]
        e.contact(before)
        assert (k.id in touched) == met, y


def test_the_body_meets_only_a_ball_in_its_band():
    e = Engine(1)
    k = _diving(e)
    k.vx = k.vy = 0.0
    e.dive = (k.id, e.t - 0.55, k.y, 1.0, e.t - 0.55, 0.0, 0.37)  # in the air, at a low ball
    e.reaction = lambda p: 10.0  # nobody reacts: only bodies count
    for z, met in ((0.37, True), (1.4, False)):
        before = (103.0, 34.0, z, 25.0, 0.0, 0.0)
        e.ball = before
        e.ball = (before[0] + 25.0 * engine.DT, 34.0, z, 25.0, 0.0, 0.0)
        hit = []
        e.touched = lambda p, cx, cy, controls, seen=hit: (seen.append(p.id), True)[1]
        e.contact(before)
        assert (k.id in hit) == met, z


def test_the_engines_keeper_raises_his_hands_only_after_the_strike_shows_the_height():
    e = Engine(1)
    k = _diving(e)
    e.dive = None
    e.kicked_at = e.free_since = e.t  # just struck
    assert e.reach(k, 104.0, 34.0)[2] < 2.03  # a high kick's height: not yet
    assert e.reach(k, 104.0, 34.0, at=e.t + 2.0)[2] == 2.8


def test_against_a_far_shot_he_waits_to_dive_so_he_is_not_down_when_it_arrives():
    e = Engine(1)
    k = e.keeper("away")
    k.x, k.y, k.vx, k.vy = 104.0, 34.0, 0.0, 0.0
    e.possessor = None
    e.kicked = {"type": "shot", "team": "home", "x": 80.0, "y": 34.0}
    e.ball = (80.0, 34.0, 0.3, 20.0, 2.5, 0.0)  # 24 m out: over a second to reach him, wide of him
    e.kicked_at = e.free_since = e.t
    e.t += e.reaction(k)
    assert not e.keeper_dive(k)  # reacted, but a dive now would land well before the ball
    while not e.keeper_dive(k):
        e.ball = engine.ball.step(e.ball, engine.DT)
        e.t += engine.DT
        assert e.t < 3.0
    when = e.ball_at_x(k.x)[0]
    assert when <= offball.dive_time_to(abs(e.dive[3]), e.dive[5]) + engine.DT  # lands as it arrives
