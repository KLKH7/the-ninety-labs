"""The keeper's hands and body over a dive (GROUNDING P15, decision 0002 step 2).

The source numbers are written here as literals, not imported from the engine (lessons 25, 36):
- Higueras-Herbada et al. 2020, Fig. 2: hands crouched at about 0.5 to 0.65 m when the ball is struck;
  height known about 245 ms after it; then up about 1 m at about 4 m/s; high kicks average 2.03 m,
  low ones 0.37 m (heights of the ball's centre).
- Monteiro et al. 2022: the centre of mass rises 0.40 to 0.43 m on a dive at a high ball.
- P11: standing reach about 1 m, about 1.8 m stretched; shoulders 0.50 m across.
The engine keeps the ball's lowest point, a radius (0.11 m) below its centre.
"""

import math

from ninety.sim import decisions, engine, offball
from ninety.sim.engine import Engine, first_within

R = 0.11  # a size-5 ball's radius


def covers(band, centre_z):
    return band[0] <= centre_z - R <= band[1]


def test_at_the_strike_his_hands_are_crouched_and_cover_neither_a_high_nor_a_low_ball():
    band = offball.hands_band(0.0)
    assert covers(band, 0.6)  # crouched, about 0.5 to 0.65 m
    assert not covers(band, 2.03) and not covers(band, 0.37)
    assert offball.hands_band(0.24) == band  # height not yet known


def test_once_the_height_is_known_his_hands_move_toward_it_at_about_4_mps():
    later = offball.hands_band(0.245 + 0.25)  # a quarter second later: about 1 m further
    assert covers(later, 0.6 + 1.0) and not covers(later, 0.6 + 1.0 + 0.2 + 0.05)
    assert later[0] == 0.0  # and down to the grass
    assert not covers(offball.hands_band(0.245 + 0.1), 1.6)  # never all at once
    assert offball.hands_band(10.0) == (0.0, 2.8)  # in the end, from the grass to a jump's reach


def test_down_after_a_dive_his_hands_reach_about_an_arm_above_the_ground():
    assert offball.reach_for(True, 1.0, 10.0, down=True)[2] <= 1.0 + 1e-9
    assert offball.reach_for(True, 1.0, 10.0, down=False)[2] == 2.8


def test_in_the_air_his_body_is_laid_out_and_rises_about_0_4_m_toward_a_high_ball():
    assert offball.body_band(None) == (0.0, 1.8)  # on his feet
    start = offball.dive_com_z(0.0, 2.03)
    end = offball.dive_com_z(5.0, 2.03)
    assert 0.40 <= end - start <= 0.43  # Monteiro et al. 2022
    lo, hi = offball.body_band(5.0, 2.03)
    assert math.isclose(hi - lo, 0.50 + 2 * R, abs_tol=1e-9)  # his shoulders' breadth, and the ball
    assert covers((lo, hi), end) and hi < 1.8  # round his centre of mass, no longer a column to his head


def test_toward_a_low_ball_his_body_goes_down_no_lower_than_lying_on_his_side():
    lo, hi = offball.body_band(5.0, 0.37)
    assert covers((lo, hi), 0.37)
    assert not covers((lo, hi), 1.2)  # a ball at chest height passes over the laid-out body
    assert offball.dive_com_z(5.0, 0.0) >= 0.50 / 2 - 1e-9  # never below lying on his side


def test_his_body_leans_out_over_the_push_off_without_a_jump():
    bands = [offball.body_band(i * 0.02, 2.03) for i in range(0, 40)]
    assert bands[0] == (0.0, 1.8)
    for a, b in zip(bands, bands[1:], strict=False):
        assert abs(b[0] - a[0]) < 0.1 and abs(b[1] - a[1]) < 0.1  # no step at the end of the push-off


def test_down_on_his_side_his_body_meets_only_a_low_ball():
    band = offball.body_band(None, down=True)
    assert band[0] == 0.0 and math.isclose(band[1], 0.50, abs_tol=1e-9)  # a ball resting on him
    assert not covers(band, 1.2)


def test_a_dive_launched_now_covers_further_the_longer_it_has():
    full = 1.45 + 1.8  # the body's travel and the stretched reach (P11, P15)
    times = [offball.dive_cover_time(m) for m in (1.2, 2.0, 2.8, full)]
    assert times == sorted(times) and times[0] > 0
    assert offball.dive_cover_time(full + 1.0) == offball.dive_cover_time(full)  # no further than that


def test_first_within_keeps_to_the_heights_and_the_side_asked():
    # a ball rolling across on the grass, past a point 0.5 m off its line
    path = (-2.0, 0.5, 0.0, 4.0, 0.0, 0.0)
    assert first_within(*path, 0.0, 0.0, 1.0, 0.0, 1.0) is not None
    assert first_within(*path, 0.0, 0.0, 1.0, 0.3, 1.0) is None  # under the floor
    assert first_within(-2.0, 0.5, 0.5, 4.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.1) is None  # over the top
    ahead = first_within(*path, 0.0, 0.0, 1.0, 0.0, 1.0, (1.0, 0.0))
    behind = first_within(*path, 0.0, 0.0, 1.0, 0.0, 1.0, (-1.0, 0.0))
    assert math.isclose(ahead, 0.5) and behind < ahead  # x >= 0 from half way; behind from the start
    # dropping through the band: first in it once below the top
    drop = (0.0, 0.0, 2.0, 0.0, 0.0, -2.0)
    assert math.isclose(first_within(*drop, 0.0, 0.0, 1.0, 0.0, 1.5), 0.25)
    assert first_within(*drop, 0.0, 0.0, 1.0, 2.5, 3.0) is None


def _keeper(e, struck_ago=2.0):
    k = e.keeper("away")
    k.x, k.y, k.vx, k.vy = 104.0, 34.0, 0.0, 0.0
    e.possessor = None
    e.kicked = {"type": "shot", "team": "home", "x": 90.0, "y": 34.0}
    e.kicked_at = e.free_since = e.t - struck_ago
    return k


def _diving(e):
    k = _keeper(e)
    e.dive = (k.id, e.t - 0.6, k.y, 1.0, e.t - 0.6, 0.0, 1.0)  # well into a dive toward +y
    return k


def test_mid_dive_he_reaches_further_ahead_of_it_than_behind_it():
    e = Engine(1)
    k = _diving(e)
    ahead = e.reach(k, 104.0, 35.5)[0]
    behind = e.reach(k, 104.0, 32.5)[0]
    assert ahead > 1.7 and behind == 1.0  # stretched toward the dive; only standing reach behind (P11)


def test_on_his_feet_he_has_his_standing_reach_however_long_since_he_reacted():
    e = Engine(1)
    k = _keeper(e)  # reacted long ago, not diving
    assert e.reach(k, 104.0, 35.5)[0] == 1.0 and e.reach(k, 104.0, 32.5)[0] == 1.0


def test_in_the_air_his_hands_stay_within_his_reach_of_his_centre_of_mass():
    e = Engine(1)
    k = _keeper(e)
    e.dive = (k.id, e.t - 0.6, k.y, 1.0, e.t - 0.6, 0.0, 0.0)  # well into a dive at a ball on the grass
    top = e.reach(k, 104.0, 35.0)[2]
    com = offball.dive_com_z(0.6, 0.0)
    assert top < 2.8 and top <= com + 1.8 - R + 1e-9  # not a jump's reach while lying out low


def test_the_touch_rule_uses_the_dive_side():
    e = Engine(1)
    k = _diving(e)
    # a ball rolling past him 1.5 m behind the dive, 0.8 m behind it (in his standing reach), 1.5 m ahead
    for y, met in ((32.5, False), (33.2, True), (35.5, True)):
        before = (104.0 - 0.5, y, 0.0, 10.0, 0.0, 0.0)
        e.ball = engine.ball.step(before, engine.DT)
        touched = []
        e.touched = lambda p, cx, cy, controls, seen=touched: (seen.append(p.id), True)[1]
        e.contact(before)
        assert (k.id in touched) == met, y


def test_the_body_meets_only_a_ball_in_its_band():
    e = Engine(1)
    k = _keeper(e)
    e.dive = (k.id, e.t - 0.55, k.y, 1.0, e.t - 0.55, 0.0, 0.37)  # in the air, at a low ball
    e.reaction = lambda p: 10.0  # nobody reacts: only bodies count
    for z, met in ((0.37 - R, True), (1.4, False)):
        before = (103.0, 34.0, z, 25.0, 0.0, 0.0)
        e.ball = (before[0] + 25.0 * engine.DT, 34.0, z, 25.0, 0.0, 0.0)
        hit = []
        e.touched = lambda p, cx, cy, controls, seen=hit: (seen.append(p.id), True)[1]
        e.contact(before)
        assert (k.id in hit) == met, z


def test_the_engines_keeper_raises_his_hands_only_after_the_strike_shows_the_height():
    e = Engine(1)
    k = _keeper(e, struck_ago=0.0)  # just struck
    assert not covers(e.reach(k, 104.0, 34.0)[1:], 2.03)  # a high kick's height: not yet
    assert covers(e.reach(k, 104.0, 34.0, at=e.t + 0.245 + 0.4)[1:], 2.03)  # up about 1.6 m by then


def test_a_deflection_does_not_take_back_what_his_hands_have_seen():
    e = Engine(1)
    k = _keeper(e, struck_ago=0.6)
    before = e.reach(k, 104.0, 34.0)[1:]
    e.kicked_at = e.t  # deflected on its way
    assert e.reach(k, 104.0, 34.0)[1:] == before


def test_the_passers_race_gives_the_keeper_the_same_hands():
    box_x = 105.0  # the away keeper's goal line
    for t in (0.1, 0.3, 1.0):
        assert decisions._reach(100.0, 34.0, t, 0.36, box_x) == offball.reach_for(True, 0.0, t)
    assert not covers(decisions._reach(100.0, 34.0, 0.1, 0.36, box_x)[1:], 2.03)  # early: still crouched


def test_against_a_far_shot_he_waits_to_dive_so_he_is_not_down_when_it_arrives():
    e = Engine(1)
    k = _keeper(e, struck_ago=0.0)
    e.ball = (80.0, 34.0, 0.3, 20.0, 2.5, 0.0)  # 24 m out: over a second to reach him, wide of him
    e.t += e.reaction(k)
    assert not e.keeper_dive(k)  # reacted, but a dive now would land well before the ball
    while not e.keeper_dive(k):
        e.ball = engine.ball.step(e.ball, engine.DT)
        e.t += engine.DT
        assert e.t < 3.0
    when, cross, _ = e.ball_at_x(k.x)
    reach_then = abs(e.dive[3]) + 1.0 + 0.8 * offball.dive_progress(when)  # body, then arms (P11)
    assert reach_then >= abs(cross - 34.0) - 0.05  # a hand gets there as it arrives
    assert when > 0.04  # and he did not leave it to the last frame


def test_at_the_strike_his_hands_meet_a_ball_centred_just_above_their_lowest():
    assert covers(offball.hands_band(0.0), 0.6 - 0.2 + 0.02)  # a hand's span below the crouch, just in


def test_in_the_air_the_ball_meets_his_trunk_when_its_centre_is_within_half_his_breadth_and_a_radius():
    com = offball.dive_com_z(5.0, 2.03)
    band = offball.body_band(5.0, 2.03)
    assert covers(band, com - 0.25 - R + 0.02) and covers(band, com + 0.25 + R - 0.02)
    assert not covers(band, com - 0.25 - R - 0.02) and not covers(band, com + 0.25 + R + 0.02)


def test_his_arms_stretching_speed_a_dives_reach():
    # 2.4 m across: the body alone (from 1 m standing reach) would need 1.4 m of travel: about 0.91 m
    # over the 0.48 s push at 7.9 m/s², the rest at 3.8 m/s, about 0.61 s in all (P15); his arms
    # stretching as he goes get there sooner
    assert offball.dive_cover_time(2.4) < 0.55


def test_he_never_dives_at_a_ball_within_his_standing_reach():
    e = Engine(1)
    k = _keeper(e, struck_ago=0.0)
    e.ball = (90.0, 34.0, 0.3, 25.0, 25.0 * 0.8 / 14.0, 0.0)  # crossing 0.8 m to his side
    for _ in range(40):
        assert not e.keeper_dive(k)
        e.ball = engine.ball.step(e.ball, engine.DT)
        e.t += engine.DT


def test_he_launches_no_more_than_about_a_frame_before_he_must():
    e = Engine(1)
    k = _keeper(e, struck_ago=0.0)
    e.ball = (80.0, 34.0, 0.3, 20.0, 2.5, 0.0)
    while not e.keeper_dive(k):
        e.ball = engine.ball.step(e.ball, engine.DT)
        e.t += engine.DT
    when, cross, _ = e.ball_at_x(k.x)
    assert when <= offball.dive_cover_time(abs(cross - 34.0)) + 0.04 * 1.5  # 25 frames a second
