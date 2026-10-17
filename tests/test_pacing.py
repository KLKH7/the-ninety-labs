"""P17: a player prices running above critical speed by the hazard score (strain times the match
left) and weighs it against what the run is worth in the situation, in goals. The choice reads the
body; it never changes it."""

import math
from dataclasses import astuple

from ninety.sim import decisions, pacing
from ninety.sim.body import BRAKE_MAX, D0, Body, can_get_to
from ninety.sim.body import move as move_body
from ninety.sim.engine import DT, SPRINT, Engine
from ninety.sim.style import Style

MIN = 60.0


def average(p) -> None:
    """Average stamina and work rate, so a scene tests the rule rather than who was drawn."""
    p.profile.attributes["stamina"] = 0.5
    p.profile.attributes["work_rate"] = 0.5


def press_scene(carrier_at=(30.0, 34.0), presser_at=(26.0, 34.0)):
    """Away's a10 has the ball; home's brain has ranked h7, then h6, then h8 as soonest to it.
    Everyone stands still."""
    e = Engine(1, styles={"home": Style(), "away": Style()})
    for p in e.players:
        p.vx = p.vy = 0.0
    carrier, first = e.by_id["a10"], e.by_id["h7"]
    carrier.x, carrier.y = carrier_at
    first.x, first.y = presser_at
    e.ball = (*carrier_at, 0.0, 0.0, 0.0, 0.0)
    e.possessor, e.restart = carrier.id, None
    for pid in ("h7", "h6", "h8"):
        average(e.by_id[pid])
    brain = e.brains["home"]
    brain.in_possession = False
    brain.ranked = ["h7", "h6", "h8"]
    return e, first, brain


def at(e, minute: float, settling: float) -> None:
    """Match time `minute`, the carrier still settling the ball for `settling` s."""
    e.t = minute * MIN
    e.hold_until = e.t + settling


def outcomes():
    """Who presses a carrier settling the ball 30 m from home's goal, h7 4 m away: a fresh h7 in
    minute 15; h7 at 40% of his reserve in minute 60; the same h7 in minute 88."""
    e, first, brain = press_scene()
    at(e, 15, 0.4)
    goals = e.press_goals(first)
    fresh = e.who_presses(brain)
    first.physique.reserve = 0.4 * D0
    at(e, 60, 0.4)
    tired = e.who_presses(brain)
    at(e, 88, 0.4)
    late = e.who_presses(brain)
    return goals, fresh, tired, late


def test_a_fresh_player_accepts_a_press_that_a_tired_one_declines_until_the_end():
    goals, fresh, tired, late = outcomes()
    # The scene's worth sits between the tired player's price in minute 60 and in minute 88
    # (lesson 36: if the design values move, this says why the scene no longer tests the rule).
    body = Body(5.18, 10.0, 3.9, reserve=0.4 * D0)
    assert pacing.price(body, 0.5, 88 * MIN) < pacing.worth(goals, 0.5) < pacing.price(body, 0.5, 60 * MIN)
    assert fresh == ["h7", "h6"]  # he presses, the next soonest covers
    assert tired == ["h6", "h8"]  # he declines: the next soonest is asked, and the one after covers
    assert late == ["h7", "h6"]  # minutes from the end the same reserve is worth spending


def test_the_scene_fails_when_the_price_ignores_the_clock(monkeypatch):
    """The planted defect (lesson 8): with the price blind to the match left, at any fixed share
    of it, the scene above cannot come out as it should."""
    for share in (1.0, 0.5, 0.0):
        monkeypatch.setattr(pacing, "time_left", lambda t, share=share: share)
        assert outcomes()[1:] != (["h7", "h6"], ["h6", "h8"], ["h7", "h6"]), share


def test_a_tired_player_presses_a_promising_ball_near_his_goal_but_not_defenders_with_time():
    """The same tired h7 (40% reserve, minute 60): a carrier who has just received 18 m from
    home's goal with h7 2 m away is worth pressing; away's centre-back on the ball 10 m from his
    own goal, settled, with h7 15 m off, is worth almost nothing."""
    e, first, brain = press_scene(carrier_at=(18.0, 34.0), presser_at=(16.0, 34.0))
    first.physique.reserve = 0.4 * D0
    at(e, 60, 0.5)
    promising = e.press_goals(first)
    assert e.who_presses(brain)[0] == "h7"
    e, first, brain = press_scene(carrier_at=(95.0, 34.0), presser_at=(80.0, 34.0))
    first.physique.reserve = 0.4 * D0
    at(e, 60, 0.0)
    hopeless = e.press_goals(first)
    assert e.who_presses(brain)[0] != "h7"
    assert promising > 100 * hopeless


def test_a_press_is_worth_more_the_sooner_he_gets_there_and_the_more_the_ball_is_worth_there():
    def goals(carrier_at=(30.0, 34.0), presser_at=(26.0, 34.0), settling=0.4):
        e, first, _ = press_scene(carrier_at, presser_at)
        at(e, 30, settling)
        return e.press_goals(first)

    assert goals(presser_at=(27.0, 34.0)) > goals(presser_at=(23.0, 34.0))  # nearer
    assert goals(settling=0.6) > goals(settling=0.0)  # the carrier still has the ball to settle
    assert goals((20.0, 34.0), (16.0, 34.0)) > goals((70.0, 34.0), (66.0, 34.0))  # nearer our goal


def test_nobody_presses_when_none_of_them_thinks_it_worth_it():
    e, first, brain = press_scene(carrier_at=(95.0, 34.0), presser_at=(80.0, 34.0))
    at(e, 30, 0.0)
    for pid in brain.ranked:
        e.by_id[pid].physique.reserve = 0.0
    assert e.who_presses(brain) == []


def test_the_press_is_asked_in_the_match_loop(monkeypatch):
    """The brain's ranking is still the suggestion; in the match loop the first-ranked player who
    declines is passed over and the next willing one presses."""
    e = Engine(1, styles={"home": Style(), "away": Style()})
    e.possessor, e.restart, e.poss_team = "a10", None, "away"
    e.frame = 0  # home's brain reads the game on this frame
    e.perceive_and_think()
    first = e.brains["home"].ranked[0]
    monkeypatch.setattr(e, "accepts_press", lambda p: p.id != first)
    e.perceive_and_think()
    brain = e.brains["home"]
    assert brain.ranked[0] == first and brain.pressers[:2] == brain.ranked[1:3]


def test_the_price_rises_as_the_reserve_falls_and_with_the_match_left():
    body = Body(5.18, 10.0, 3.9)
    assert pacing.price(body, 0.5, 0.0) == 0.0  # fresh: running hard costs him nothing
    body.reserve = 0.4 * D0
    early, mid, end = (pacing.price(body, 0.5, m * MIN) for m in (10, 60, 90))
    assert early > mid > end == 0.0
    body.reserve = 0.2 * D0
    assert pacing.price(body, 0.5, 60 * MIN) > mid
    body = Body(5.18, 10.0, 3.9, spent=40 * D0)  # the slow store has fallen, and he is at its ceiling
    body.reserve = body.ceiling
    assert pacing.strain(body) == 1 - body.ceiling / D0 > 0  # a match-long decline is felt


def test_stamina_lowers_the_price_and_work_rate_raises_what_a_run_is_worth():
    body = Body(5.18, 10.0, 3.9, reserve=0.4 * D0)
    assert pacing.price(body, 0.9, 60 * MIN) < pacing.price(body, 0.1, 60 * MIN)
    assert pacing.worth(0.01, 0.9) > pacing.worth(0.01, 0.1)
    assert pacing.worth(-0.01, 0.5) == 0.0  # a run that loses ground is worth nothing, never less


def test_a_run_is_asked_for_at_full_capability_while_free_and_slower_as_it_costs_more():
    body = Body(5.18, 10.0, 3.9)
    assert pacing.run_speed(body, 0.5, 0.5, 30 * MIN, 0.05) == body.v0
    body.reserve = 0.3 * D0
    valuable = pacing.run_speed(body, 0.5, 0.5, 30 * MIN, 0.05)
    slight = pacing.run_speed(body, 0.5, 0.5, 30 * MIN, 0.005)
    assert body.cs < slight < valuable < body.v0
    assert pacing.run_speed(body, 0.5, 0.5, 90 * MIN, 0.005) == body.v0  # the final whistle


def test_a_choice_never_changes_the_body():
    """Pricing, choosing and asking for a speed read the body and leave it as it was; the speed he
    gets is still capped by his body."""
    e, first, brain = press_scene()
    first.physique.reserve = 0.4 * D0
    at(e, 60, 0.4)
    before = astuple(first.physique), first.physique.top_speed(), first.physique.accel_limit(3.0)
    e.who_presses(brain)
    e.accepts_press(first)
    asked = e.run_speed(first, e.contest_goals("home", 30.0, 34.0))
    pacing.price(first.physique, 0.5, e.t)
    after = astuple(first.physique), first.physique.top_speed(), first.physique.accel_limit(3.0)
    assert before == after
    assert first.physique.cs < asked <= first.physique.v0
    body = Body(5.18, 10.0, 3.9, reserve=0.05 * D0)  # nearly empty: his body allows little above cs
    want = pacing.run_speed(body, 0.5, 0.5, 89 * MIN, 0.05)
    assert want > body.top_speed()  # he wants more than he has
    x = y = vx = vy = 0.0
    for _ in range(200):
        limit = body.top_speed()  # what his body allows when he takes the step
        x, y, vx, vy = move_body(x, y, vx, vy, 500.0, 0.0, want, body, DT)
        assert math.hypot(vx, vy) <= limit + 1e-9


def test_the_chase_estimate_at_a_chosen_speed_matches_running_at_it():
    """Lesson 23: the estimate of how far he gets at the speed he chooses is the body running it,
    within a frame's discretisation, from below the speed he chooses and from above it."""
    for start, cap in ((0.0, 5.0), (0.0, 6.5), (2.0, 8.0), (9.0, 5.0), (7.0, 6.0)):
        body = Body(5.18, 10.0, 3.9)
        body.spend = lambda *a, **k: None  # hold the reserve, so the body's limits stay put
        x, y, vx, vy = 0.0, 0.0, start, 0.0
        frames = int(3.0 / DT)
        for _ in range(frames):
            x, y, vx, vy = move_body(x, y, vx, vy, 500.0, 0.0, cap, body, DT)
        estimate = body.distance_in(frames * DT, start, cap)
        assert abs(estimate - x) < max(cap, start) * DT * 2, (start, cap, estimate, x)
        assert math.isclose(body.time_to_cover(estimate, start, cap), frames * DT, rel_tol=1e-3)
    body = Body(5.18, 10.0, 3.9)
    assert body.distance_in(3.0, 2.0, cap=50.0) == body.distance_in(3.0, 2.0)  # a cap above the body is none
    # The reach test the chase uses honours the cap: 10 m to close in 2.5 s from standing is in reach
    # at his body's best (about 11.0 m), not at 5 m/s (about 9.6 m).
    assert can_get_to(body, 11.0, 0.0, 1.0, 0.0, 0.0, 2.5)[0]
    assert not can_get_to(body, 11.0, 0.0, 1.0, 0.0, 0.0, 2.5, cap=5.0)[0]
    slow = 3.0 / BRAKE_MAX  # from 9 m/s braking to 6, then holding 6
    braking = 9 * slow - BRAKE_MAX * slow**2 / 2
    assert math.isclose(body.distance_in(2.0, 9.0, cap=6.0), braking + 6 * (2 - slow))


def test_each_full_speed_run_asks_for_what_the_situation_makes_it_worth():
    """O4, D8 and the chase through P17: a run in behind is worth the threat it adds, a lunge and a
    loose ball what winning it there is worth; a keeper's dash stays all-out."""
    e = Engine(1, styles={"home": Style(), "away": Style()})
    runner = e.by_id["h9"]
    average(runner)
    runner.physique.reserve = 0.6 * D0
    e.t = 30 * MIN
    e.possessor = "h7"
    e.brains["home"].in_possession = True
    e.ball = (50.0, 34.0, 0.0, 0.0, 0.0, 0.0)
    e.runs[runner.id] = (80.0, 30.0, e.t)  # a run already under way
    gain = decisions.value(80.0, 30.0, 105.0) - decisions.value(50.0, 34.0, 105.0)
    assert e.shape_target(runner)[2] == e.run_speed(runner, gain) < runner.physique.v0
    del e.runs[runner.id]
    e.possessor = None
    e.lunges[runner.id] = e.t + 0.3
    assert e.shape_target(runner)[2] == e.run_speed(runner, e.contest_goals("home", 50.0, 34.0))
    del e.lunges[runner.id]
    e.chase = {"home": (runner.id, 60.0, 30.0)}
    assert e.shape_target(runner)[2] == e.run_speed(runner, e.contest_goals("home", 60.0, 30.0))
    keeper = e.by_id["h1"]
    e.chase = {"home": (keeper.id, 10.0, 34.0)}
    assert e.shape_target(keeper)[2] == SPRINT


def test_the_chase_plan_judges_outfield_players_at_their_chosen_speed(monkeypatch):
    """Lesson 23: who chases a loose ball is decided at the speed each would run, and a keeper at
    his body's best."""
    e = Engine(1, styles={"home": Style(), "away": Style()})
    e.possessor, e.restart = None, None
    e.ball = (52.0, 34.0, 3.0, 0.0, 0.0, 0.0)
    for p in e.players:
        p.physique.reserve = 0.5 * D0
    e.t = 30 * MIN
    caps = {}
    real = e.can_reach

    def spy(p, *a, cap=None, **k):
        caps.setdefault(p.id, cap)
        return real(p, *a, cap=cap, **k)

    monkeypatch.setattr(e, "can_reach", spy)
    monkeypatch.setattr(e, "reacting_since", lambda p: -99.0)
    e.plan_chase()
    outfield = [pid for pid in caps if e.by_id[pid].role != "GK"]
    assert outfield
    for pid in outfield:
        p = e.by_id[pid]
        assert caps[pid] == e.run_speed(p, e.contest_goals(p.team, 52.0, 34.0))
    assert all(cap is None for pid, cap in caps.items() if e.by_id[pid].role == "GK")
