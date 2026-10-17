"""A pass goes where the passer believes his team-mate is, as he believes him now (O7, P13): the
velocity he believes is the rate his believed position changes, and a pass that waits for him to
turn is aimed when it is struck, from what he sees then."""

import math

import pytest

from ninety.sim import decisions, perception
from ninety.sim.engine import Engine, goal_x


def test_the_believed_velocity_is_how_the_believed_position_moves():
    """Mutation caught: a sighting's velocity kept after its position is held (a team-mate believed
    to stand still and to run at once, so a pass leads him into space he left)."""
    b = perception.Belief()
    b.seen["x"] = perception.Sighting(10.0, 20.0, 3.0, -1.0, 0.0)
    h = 1e-4
    for now in (0.2, 0.5, 0.9, 1.1, 1.5, 3.0):  # carried forward, then held (EXTRAPOLATE_S)
        (x0, y0), (x1, y1) = b.where("x", now), b.where("x", now + h)
        assert b.velocity("x", now) == pytest.approx(((x1 - x0) / h, (y1 - y0) / h), abs=1e-6)
    assert b.velocity("nobody", 0.0) == (0.0, 0.0)


def _turning_to_pass(receiver):
    e = Engine(1)
    p = e.by_id["h6"]
    e.give(p.id)
    p.x, p.y, p.heading = 40.0, 34.0, math.pi  # facing his own goal
    e.ball = (p.x - 0.4, p.y, 0.0, 0.0, 0.0, 0.0)
    e.beliefs[p.id].seen["h9"] = perception.Sighting(52.0, 34.0, 0.0, 0.0, e.t)  # seen still, 12 m ahead
    mate = next(m for m in e.scene_for(p).mates if m[0] == "h9")
    tx, ty = decisions.lead_target(e.ball[0], e.ball[1], goal_x("home"), mate)
    e.pass_to(p, tx, ty, lofted=False, receiver=receiver)
    assert e.windup is not None and e.intended is None  # he turns first
    return e, p, (tx, ty)


def test_a_pass_that_waits_for_his_turn_is_aimed_at_the_team_mate_as_he_sees_him_when_he_strikes():
    """O7. Mutations caught: the strike kept at the target chosen before he turned; re-aimed by a
    rule other than the decision's own (decisions.lead_target)."""
    e, p, before = _turning_to_pass("h9")
    e.t += 0.3  # turning, he now sees h9 has moved off toward the touchline, running
    e.beliefs[p.id].seen["h9"] = perception.Sighting(50.0, 44.0, 0.0, 4.0, e.t)
    p.heading = math.atan2(44.0 - p.y, 50.0 - p.x)
    e.ball = (p.x + 0.4 * math.cos(p.heading), p.y + 0.4 * math.sin(p.heading), 0.0, 0.0, 0.0, 0.0)
    mate = next(m for m in e.scene_for(p).mates if m[0] == "h9")
    now = decisions.lead_target(e.ball[0], e.ball[1], goal_x("home"), mate)
    strike, e.windup = e.windup[2], None
    strike()
    assert e.windup is None and e.pass_target == pytest.approx(now) and e.intended == "h9"
    assert math.hypot(now[0] - before[0], now[1] - before[1]) > 5.0  # a different spot


def test_a_pass_into_space_keeps_its_spot_when_struck():
    e, p, before = _turning_to_pass(None)
    e.beliefs[p.id].seen["h9"] = perception.Sighting(50.0, 44.0, 0.0, 4.0, e.t)
    p.heading = math.atan2(before[1] - p.y, before[0] - p.x)
    e.ball = (p.x + 0.4 * math.cos(p.heading), p.y + 0.4 * math.sin(p.heading), 0.0, 0.0, 0.0, 0.0)
    strike, e.windup = e.windup[2], None
    strike()
    assert e.windup is None and e.pass_target == pytest.approx(before)


def test_the_scene_gives_everyone_the_velocity_he_is_believed_to_have_now():
    """P13: a team-mate, an opponent or the keeper last seen over EXTRAPOLATE_S ago is believed to
    be where he was held, not still running; one seen just now keeps the velocity seen. Mutations
    caught: any of the scene's three readings using the sighting's velocity whatever its age."""
    e = Engine(1)
    p = e.by_id["h6"]
    e.give(p.id)
    keeper = e.keeper("away").id
    old, new = e.t - 2 * perception.EXTRAPOLATE_S, e.t
    for i, (pid, seen) in enumerate((("h9", old), ("h10", new), ("a6", old), ("a7", new), (keeper, old))):
        # in the home half, where nobody of his is offside (L10)
        e.beliefs[p.id].seen[pid] = perception.Sighting(30.0, 10.0 + 10 * i, 3.0, 0.0, seen)
    scene = e.scene_for(p)
    mates = {m[0]: tuple(m[4:6]) for m in scene.mates}
    assert mates["h9"] == (0.0, 0.0) and mates["h10"] == (3.0, 0.0)
    moving = {(round(m[0], 6), round(m[1], 6)): (m[2], m[3]) for m in scene.moving}
    held = e.beliefs[p.id].where("a6", e.t)
    assert moving[(round(held[0], 6), round(held[1], 6))] == (0.0, 0.0)
    fresh = e.beliefs[p.id].where("a7", e.t)
    assert moving[(round(fresh[0], 6), round(fresh[1], 6))] == (3.0, 0.0)
    assert scene.keeper == pytest.approx(e.beliefs[p.id].where(keeper, e.t))  # held: not anticipated on


def _strike_after_turn(e, p, sighting):
    e.t += 0.3
    e.beliefs[p.id].seen["h9"] = sighting
    mate = next((m for m in e.scene_for(p).mates if m[0] == "h9"), None)
    aim = decisions.lead_target(e.ball[0], e.ball[1], goal_x("home"), mate) if mate else None
    p.heading = math.atan2(sighting.y - p.y, sighting.x - p.x)
    e.ball = (p.x + 0.4 * math.cos(p.heading), p.y + 0.4 * math.sin(p.heading), 0.0, 0.0, 0.0, 0.0)
    strike, e.windup = e.windup[2], None
    strike()
    return aim


def test_a_still_team_mate_is_struck_a_step_ahead_of_where_he_is_seen_toward_goal():
    """O7, as decided. Mutation caught: re-aimed with the wrong team's goal."""
    e, p, before = _turning_to_pass("h9")
    aim = _strike_after_turn(e, p, perception.Sighting(48.0, 40.0, 0.0, 0.0, e.t + 0.3))
    assert aim == pytest.approx((48.0 + 1.5, 40.0)) and e.pass_target == pytest.approx(aim)


def test_he_chooses_again_if_the_team_mate_is_no_longer_a_pass_he_could_choose(monkeypatch):
    """L10 and the pass's range: having turned, he sees the man he chose standing offside, or too far
    for a pass; he does not play it to him but chooses again. Mutation caught: struck anyway."""
    for x, y in ((104.0, 34.0), (40.0 + 0.4 + decisions.MAX_PASS_M + 2.0, 34.0)):
        e, p, _ = _turning_to_pass("h9")
        chose = []
        monkeypatch.setattr(e, "decide", lambda carrier, throw=False, chose=chose: chose.append(carrier.id))
        _strike_after_turn(e, p, perception.Sighting(x, y, 0.0, 0.0, e.t + 0.3))
        assert chose == ["h6"] and e.intended is None and e.kicked is None
