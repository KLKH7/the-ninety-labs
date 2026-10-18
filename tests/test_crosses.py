"""Crosses in open play to a timed run (X1, X2): the crosser holds it while his team-mate's run comes
on, the runner sets off so that he is on the onside line, running, as it is struck, and it is struck
at him then."""

import math

import pytest

from ninety.sim import decisions, perception
from ninety.sim.engine import DT, Engine, goal_x


def _wide_with_a_runner():
    e = Engine(1)
    crosser, runner = e.by_id["h11"], e.by_id["h9"]  # LW on the ball, ST to run
    e.give(crosser.id)
    e.hold_until = e.t
    crosser.x, crosser.y, crosser.heading = 88.0, 6.0, math.pi / 2  # wide, facing across the pitch
    e.ball = (crosser.x, crosser.y + 0.4, 0.0, 0.0, 0.0, 0.0)
    runner.x, runner.y = 80.0, 38.0
    # Their last two outfield defenders on a line at 91 m, their keeper on his line; everyone
    # else well away from the box.
    for q in e.players:
        if q.team == "away" and q.role != "GK" and q.id not in ("a3", "a4"):
            q.x, q.y = 60.0, 10.0 + 4.0 * int(q.id[1:])
        if q.team == "home" and q.id not in (crosser.id, runner.id) and q.role != "GK":
            q.x, q.y = 55.0, 10.0 + 4.0 * int(q.id[1:])
    e.by_id["a3"].x, e.by_id["a3"].y = 91.0, 30.0
    e.by_id["a4"].x, e.by_id["a4"].y = 91.0, 44.0
    keeper = e.keeper("away")
    keeper.x, keeper.y = 104.0, 34.0
    for p in e.players:
        e.beliefs[p.id].seen = {q.id: perception.Sighting(q.x, q.y, 0.0, 0.0, e.t) for q in e.players
                                if q is not p}
    return e, crosser, runner


def test_the_runner_times_his_run_and_the_cross_is_struck_at_him_on_the_line(monkeypatch):
    """Mutations caught: the runner setting off at once (offside, or there too soon to be running),
    or not at all; the cross struck before the run is on, or at someone else."""
    e, crosser, runner = _wide_with_a_runner()
    scene = e.scene_for(crosser)
    cross = next(c for c in decisions.cross_options(scene) if c.receiver == runner.id)
    monkeypatch.setattr(decisions, "choose", lambda _scene, _rng: cross)
    e.decide(crosser)
    plan = e.cross_run
    assert plan and plan["runner"] == runner.id and e.possessor == crosser.id
    start = (runner.x, runner.y)
    set_off = struck = None
    while e.t < plan["strike"] + 1.0 and struck is None:
        e.step()
        moved = math.hypot(runner.x - start[0], runner.y - start[1])
        if set_off is None and moved > 0.01:
            set_off = e.t - DT  # he was already going in the frame before
        if e.kicked and e.kicked.get("player") == crosser.id:
            struck = e.t
    assert struck is not None and e.kicked["type"] == "pass" and e.intended == runner.id
    assert struck >= plan["strike"] - DT  # held until the run is on
    assert set_off is not None and set_off > plan["read"]  # not before he could read it
    lx, ly = plan["line"]
    assert math.hypot(runner.x - lx, runner.y - ly) < 1.5  # on the line, at the strike
    assert math.hypot(runner.vx, runner.vy) > 3.0  # running
    assert runner.id not in e.offside  # and onside, as judged at the kick (L10)
    # O7: aimed at the runner as the crosser saw him at the strike, not where he was when he chose
    mate = next(m for m in e.scene_for(crosser).mates if m[0] == runner.id)
    seen_then = decisions.lead_target(e.kicked["x"], e.kicked["y"], goal_x("home"), mate)
    assert e.pass_target == pytest.approx(seen_then, abs=0.3)
    assert math.hypot(e.pass_target[0] - plan["aim"][0], e.pass_target[1] - plan["aim"][1]) > 0.0


def test_a_cross_plan_ends_with_the_ball():
    """Mutation caught: the plan outliving the possession (a runner still timing a cross nobody holds)."""
    e, crosser, runner = _wide_with_a_runner()
    e.cross_run = dict(passer=crosser.id, runner=runner.id, aim=(95.0, 34.0), zone=(99.5, 37.0),
                       line=(90.0, 36.0), read=e.t, strike=e.t + 1.0, lofted=True, pace=6.0)
    e.give("a3")
    assert e.cross_run is None
    # Nor when nobody has it any more (poked loose, or out of play) without anyone taking it.
    e, crosser, runner = _wide_with_a_runner()
    e.cross_run = dict(passer=crosser.id, runner=runner.id, aim=(95.0, 34.0), zone=(99.5, 37.0),
                       line=(90.0, 36.0), read=e.t, strike=e.t + 1.0, lofted=True, pace=6.0)
    e.possessor = None
    e.shape_target(runner)
    assert e.cross_run is None


def test_a_runner_behind_time_still_sets_off_only_once_he_could_read_the_crosser(monkeypatch):
    """P12: however late his run is, he goes only after a simple reaction to the crosser shaping up.
    Mutation caught: the runner setting off the moment the cross is chosen."""
    e, crosser, runner = _wide_with_a_runner()
    cross = next(c for c in decisions.cross_options(e.scene_for(crosser)) if c.receiver == runner.id)
    monkeypatch.setattr(decisions, "choose", lambda _scene, _rng: cross)
    e.decide(crosser)
    e.cross_run["strike"] = e.t + 0.6  # far less time than his run needs
    start, chose = (runner.x, runner.y), e.t
    while e.t < chose + perception.SIMPLE_REACTION_S - DT:
        e.step()
        assert math.hypot(runner.x - start[0], runner.y - start[1]) < 1e-9
    for _ in range(5):
        e.step()
    assert math.hypot(runner.x - start[0], runner.y - start[1]) > 0.0


def test_a_crosser_facing_away_turns_to_it_while_he_waits_for_the_run(monkeypatch):
    """X1: he turns toward where he means to cross it while he holds, so the strike comes when the
    run is on, not a turn later. Mutation caught: the turn left until the strike."""
    e, crosser, runner = _wide_with_a_runner()
    crosser.heading = math.pi  # facing back up the wing, as he received it
    crosser.vx = -3.0  # and still going that way
    cross = next(c for c in decisions.cross_options(e.scene_for(crosser)) if c.receiver == runner.id)
    assert decisions.strike_turn(math.pi, cross.target[0] - crosser.x, cross.target[1] - crosser.y)[1] > 0
    monkeypatch.setattr(decisions, "choose", lambda _scene, _rng: cross)
    e.decide(crosser)
    plan = e.cross_run
    struck = None
    while e.t < plan["strike"] + 1.0 and struck is None:
        e.step()
        if e.kicked and e.kicked.get("player") == crosser.id:
            struck = e.t
    assert struck is not None and struck <= plan["strike"] + 2 * DT
    assert e.intended == runner.id and math.hypot(crosser.x - 88.0, crosser.y - 6.0) < 1.5  # he pulled up


def test_a_runner_who_would_be_over_the_line_too_soon_slows_to_arrive_on_it_at_the_strike():
    """X2: the line has stepped up; at his speed he would be over it before the strike, so he slows
    to be a step onside of it as it is struck. Mutation caught: running on through it."""
    e, crosser, runner = _wide_with_a_runner()
    runner.x, runner.y, runner.vx, runner.vy = 86.0, 34.0, 7.0, 0.0
    e.beliefs[runner.id].seen["a3"] = perception.Sighting(89.0, 30.0, 0.0, 0.0, e.t)
    e.beliefs[runner.id].seen["a4"] = perception.Sighting(89.0, 44.0, 0.0, 0.0, e.t)
    e.cross_run = dict(passer=crosser.id, runner=runner.id, aim=(97.0, 34.0), zone=(99.5, 34.0),
                       line=(90.0, 34.0), read=e.t - 1.0, strike=e.t + 1.0, lofted=True, pace=6.0)
    tx, ty, speed = e.shape_target(runner)
    limit = 89.0 - 1.0  # a step onside of the line he sees
    assert tx == pytest.approx(limit) and ty == pytest.approx(34.0)
    assert speed == pytest.approx((limit - 86.0) / 1.0)
