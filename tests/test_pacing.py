"""P17: a player prices running above critical speed by the hazard score (strain times the match
left) and weighs it against what the run is worth. The choice reads the body; it never changes it."""

import math
from dataclasses import astuple

from ninety.sim import pacing
from ninety.sim.body import D0, Body
from ninety.sim.body import move as move_body
from ninety.sim.engine import DT, Engine
from ninety.sim.style import Style

MIN = 60.0


def average(p) -> None:
    """Average stamina and work rate, so the scene tests the rule rather than who was drawn."""
    p.profile.attributes["stamina"] = 0.5
    p.profile.attributes["work_rate"] = 0.5


def press_scene():
    """Home is out of possession; its brain has ranked h7 then h6 then h8 as soonest to the ball."""
    e = Engine(1, styles={"home": Style(), "away": Style()})
    first, second, third = e.by_id["h7"], e.by_id["h6"], e.by_id["h8"]
    for p in (first, second, third):
        average(p)
    brain = e.brains["home"]
    brain.in_possession = False
    brain.ranked = [first.id, second.id, third.id]
    return e, first, brain


def outcomes():
    """Who presses: a fresh h7 in minute 15; h7 at 40% of his reserve in minute 60; the same h7 in
    minute 88, with little of the match left to save it for."""
    e, first, brain = press_scene()
    e.t = 15 * MIN
    fresh = e.who_presses(brain)
    first.physique.reserve = 0.4 * D0
    e.t = 60 * MIN
    tired = e.who_presses(brain)
    e.t = 88 * MIN
    late = e.who_presses(brain)
    return fresh, tired, late


def test_a_fresh_player_accepts_a_press_that_a_tired_one_declines_until_the_end():
    fresh, tired, late = outcomes()
    assert fresh == ["h7", "h6"]  # he presses, the next soonest covers
    assert tired == ["h6", "h8"]  # he declines: the next soonest is asked, and the one after covers
    assert late == ["h7", "h6"]  # minutes from the end the same reserve is worth spending


def test_the_scene_fails_when_the_price_ignores_the_clock(monkeypatch):
    """The planted defect (lesson 8): with the price blind to the match left, at any fixed share
    of it, the scene above cannot come out as it should."""
    for share in (1.0, 0.5, 0.0):
        monkeypatch.setattr(pacing, "time_left", lambda t, share=share: share)
        assert outcomes() != (["h7", "h6"], ["h6", "h8"], ["h7", "h6"]), share


def test_nobody_presses_when_none_of_them_thinks_it_worth_it():
    e, first, brain = press_scene()
    e.t = 30 * MIN
    for pid in brain.ranked:
        e.by_id[pid].physique.reserve = 0.0
    assert e.who_presses(brain) == []


def test_the_price_rises_as_the_reserve_falls_and_with_the_match_left():
    body = Body(5.18, 10.0, 3.9)
    assert pacing.price(body, 0.5, 0.0) == 0.0  # fresh: running hard costs him nothing
    body.reserve = 0.4 * D0
    early, mid, end = (pacing.price(body, 0.5, m * MIN) for m in (10, 60, 90))
    assert early > mid > end == 0.0
    body.reserve = 0.2 * D0
    assert pacing.price(body, 0.5, 60 * MIN) > mid


def test_stamina_lowers_the_price_and_work_rate_raises_what_a_run_is_worth():
    body = Body(5.18, 10.0, 3.9, reserve=0.4 * D0)
    assert pacing.price(body, 0.9, 60 * MIN) < pacing.price(body, 0.1, 60 * MIN)
    assert pacing.worth(pacing.ROUTINE_VALUE, 0.9) > pacing.worth(pacing.ROUTINE_VALUE, 0.1)


def test_a_run_is_asked_for_at_full_capability_while_free_and_slower_as_it_costs_more():
    body = Body(5.18, 10.0, 3.9)
    assert pacing.run_speed(body, 0.5, 0.5, 30 * MIN, pacing.CONTEST_VALUE) == body.v0
    body.reserve = 0.3 * D0
    contest = pacing.run_speed(body, 0.5, 0.5, 30 * MIN, pacing.CONTEST_VALUE)
    routine = pacing.run_speed(body, 0.5, 0.5, 30 * MIN, pacing.ROUTINE_VALUE)
    assert body.cs < routine < contest < body.v0
    assert pacing.run_speed(body, 0.5, 0.5, 90 * MIN, pacing.ROUTINE_VALUE) == body.v0  # the final whistle


def test_a_choice_never_changes_the_body():
    """Pricing, choosing and asking for a speed read the body and leave it as it was; the speed he
    gets is still capped by his body."""
    e, first, brain = press_scene()
    first.physique.reserve = 0.4 * D0
    e.t = 60 * MIN
    before = astuple(first.physique), first.physique.top_speed(), first.physique.accel_limit(3.0)
    e.who_presses(brain)
    e.accepts(first)
    asked = e.run_speed(first, pacing.CONTEST_VALUE)
    pacing.price(first.physique, 0.5, e.t)
    after = astuple(first.physique), first.physique.top_speed(), first.physique.accel_limit(3.0)
    assert before == after
    assert first.physique.cs < asked <= first.physique.v0
    body = Body(5.18, 10.0, 3.9, reserve=0.05 * D0)  # nearly empty: his body allows little above cs
    want = pacing.run_speed(body, 0.5, 0.5, 89 * MIN, pacing.CONTEST_VALUE)
    assert want > body.top_speed()  # he wants more than he has
    x = y = vx = vy = 0.0
    for _ in range(200):
        limit = body.top_speed()  # what his body allows when he takes the step
        x, y, vx, vy = move_body(x, y, vx, vy, 500.0, 0.0, want, body, DT)
        assert math.hypot(vx, vy) <= limit + 1e-9


def test_the_chase_estimate_at_a_chosen_speed_matches_running_at_it():
    """Lesson 23: the estimate of how far he gets at the speed he chooses is the body running it,
    within a frame's discretisation."""
    for cap in (5.0, 6.5, 8.0):
        body = Body(5.18, 10.0, 3.9)
        body.spend = lambda *a, **k: None  # hold the reserve, so the body's limits stay put
        x = y = vx = vy = 0.0
        frames = int(4.0 / DT)
        for _ in range(frames):
            x, y, vx, vy = move_body(x, y, vx, vy, 500.0, 0.0, cap, body, DT)
        estimate = body.distance_in(frames * DT, 0.0, cap)
        assert abs(estimate - x) < cap * DT * 2, (cap, estimate, x)
        assert math.isclose(body.time_to_cover(estimate, 0.0, cap), frames * DT, rel_tol=1e-3)
    body = Body(5.18, 10.0, 3.9)
    assert body.distance_in(3.0, 2.0, cap=50.0) == body.distance_in(3.0, 2.0)  # a cap above the body is none


def test_a_run_in_behind_asks_for_the_speed_its_price_allows():
    """O4 through P17: the forward on a run asks for its routine worth, which a tired player
    finds is less than his body could give, and a contest is still all-out."""
    e = Engine(1, styles={"home": Style(), "away": Style()})
    carrier, runner = e.by_id["h7"], e.by_id["h9"]
    average(runner)
    e.possessor = carrier.id
    e.brains["home"].in_possession = True
    e.t = 30 * MIN
    e.runs[runner.id] = (80.0, 30.0, e.t)  # a run already under way
    assert e.shape_target(runner)[2] == runner.physique.v0  # fresh: as fast as his body allows
    runner.physique.reserve = 0.6 * D0
    asked = e.shape_target(runner)[2]
    assert asked == e.run_speed(runner, pacing.ROUTINE_VALUE)
    assert runner.physique.cs < asked < runner.physique.top_speed()  # less than he has: a choice
    # With a contest worth 1, average stamina and a full slow store, what he asks never falls below
    # what his body allows: 1/(1 + s) >= 1 - s for any strain s.
    for share in (0.9, 0.6, 0.3, 0.05):
        runner.physique.reserve = share * D0
        assert e.run_speed(runner, pacing.CONTEST_VALUE) >= runner.physique.top_speed() - 1e-9
