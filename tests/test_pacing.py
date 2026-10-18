"""P17: a player prices each metre run above critical speed by the hazard score (how far his slow
store has fallen times the match left), so a run costs the metres it takes above it, and weighs
that against what the run is worth in the situation, in goals. The choice reads the body; it never
changes it."""

import math
from dataclasses import astuple

from ninety.sim import decisions, pacing
from ninety.sim.body import BRAKE_MAX, D0, SLOW_SCALE, Body, can_get_to
from ninety.sim.body import move as move_body
from ninety.sim.engine import DT, SPRINT, Engine
from ninety.sim.style import Style

MIN = 60.0


def worn(body: Body, share_gone: float) -> Body:
    """His slow store `share_gone` down (P10), his reserve full to what it allows."""
    body.spent = -math.log(1.0 - share_gone) * SLOW_SCALE * D0
    body.reserve = body.ceiling
    return body


def average(p) -> None:
    """Average stamina and work rate, so a scene tests the rule rather than who was drawn."""
    p.profile.attributes["stamina"] = 0.5
    p.profile.attributes["work_rate"] = 0.5


def press_scene(carrier_at=(52.5, 34.0), presser_at=(32.5, 34.0)):
    """Away's a10 has the ball; home's brain has ranked h7, then h6, then h8 as soonest to it.
    Everyone stands still."""
    e = Engine(1, styles={"home": Style(), "away": Style()})
    for p in e.players:
        p.vx = p.vy = 0.0
    carrier, first = e.by_id["a10"], e.by_id["h7"]
    carrier.x, carrier.y = carrier_at
    first.x, first.y = presser_at
    e.ball = (*carrier_at, 0.0, 0.0, 0.0, 0.0)
    e.possessor, e.restart, e.kicked = carrier.id, None, None
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
    """Who presses a settled carrier at halfway, h7 20 m off: a fresh h7 in minute 15; h7 with his
    slow store 40% down in minute 60; the same h7 in minute 88."""
    e, first, brain = press_scene()
    at(e, 15, 0.0)
    run = e.press_run(first)
    fresh = e.who_presses(brain)
    worn(first.physique, 0.4)
    at(e, 60, 0.0)
    tired = e.who_presses(brain)
    at(e, 88, 0.0)
    late = e.who_presses(brain)
    return run, fresh, tired, late


def test_a_fresh_player_accepts_a_press_that_a_tired_one_declines_until_the_end():
    (goals, metres), fresh, tired, late = outcomes()
    # The scene's worth sits between what the run costs the tired player in minute 88 and in
    # minute 60 (lesson 36: if the design values move, this says why the scene no longer tests it).
    body = worn(Body(5.18, 10.0, 3.9), 0.4)
    assert pacing.cost(body, 0.5, 88 * MIN, metres) < goals < pacing.cost(body, 0.5, 60 * MIN, metres)
    assert fresh == ["h7", "h6"]  # he presses, the next soonest covers
    assert tired == ["h6", "h8"]  # he declines: the next soonest is asked, and the one after covers
    assert late == ["h7", "h6"]  # minutes from the end what is left is worth spending


def test_the_scene_fails_when_the_price_ignores_the_clock(monkeypatch):
    """The planted defect (lesson 8): with the price blind to the match left, at any fixed share
    of it, the scene above cannot come out as it should."""
    for share in (1.0, 0.5, 0.0):
        monkeypatch.setattr(pacing, "time_left", lambda t, share=share: share)
        assert outcomes()[1:] != (["h7", "h6"], ["h6", "h8"], ["h7", "h6"]), share


def test_a_short_press_costs_little_and_a_long_one_more():
    """The price is per metre above critical speed: a step to pressing distance costs a fraction of
    a 20 m press, so a tired player still makes the one and not the other."""
    near, first, brain = press_scene(carrier_at=(52.5, 34.0), presser_at=(48.5, 34.0))
    worn(first.physique, 0.4)
    at(near, 60, 0.0)
    short_goals, short_metres = near.press_run(first)
    _, long_metres = outcomes()[0]
    assert short_metres < long_metres / 5
    assert near.who_presses(brain)[0] == "h7"


def test_a_tired_player_presses_in_midfield_and_near_his_goal_but_not_defenders_with_time():
    """The same tired h7 (slow store 40% down, minute 60), 15 m from a settled carrier: worth it at
    halfway, not against away's centre-back 10 m from his own goal; and a carrier who has just
    received 18 m from home's goal with h7 4 m off is worth it by far."""
    choices = {}
    for name, carrier_at, presser_at, settling in (("midfield", (52.5, 34.0), (37.5, 34.0), 0.0),
                                                   ("their back", (95.0, 34.0), (80.0, 34.0), 0.0),
                                                   ("near our goal", (18.0, 34.0), (14.0, 34.0), 0.4)):
        e, first, brain = press_scene(carrier_at, presser_at)
        worn(first.physique, 0.4)
        at(e, 60, settling)
        choices[name] = e.who_presses(brain)[0] == "h7"
    assert choices == {"midfield": True, "their back": False, "near our goal": True}


def test_a_press_is_worth_more_the_sooner_he_gets_there_and_the_more_the_ball_is_worth_there():
    def goals(carrier_at=(30.0, 34.0), presser_at=(26.0, 34.0), settling=0.4):
        e, first, _ = press_scene(carrier_at, presser_at)
        at(e, 30, settling)
        return e.press_goals(first)

    assert goals(presser_at=(27.0, 34.0)) > goals(presser_at=(23.0, 34.0))  # nearer

    def running(vx: float) -> float:  # already on his way toward the carrier, or away from him
        e, first, _ = press_scene((30.0, 34.0), (20.0, 34.0))
        first.vx = vx
        at(e, 30, 0.0)
        return e.press_goals(first)

    assert running(5.0) > running(0.0) > running(-3.0)
    assert goals(settling=0.6) > goals(settling=0.0)  # the carrier still has the ball to settle
    # Against a settled carrier 8 m off: worth most near our goal, less in midfield, least at their
    # back, where a defender with time plays it before a presser can win it.
    down = [goals((x, 34.0), (x - 8.0, 34.0), 0.0) for x in (12.0, 30.0, 52.0, 75.0, 95.0)]
    assert all(a >= b for a, b in zip(down, down[1:], strict=False)), down
    assert down[-1] < down[0] / 5
    # But a defender still settling the ball at his own goal with the presser on him can lose it.
    assert goals((95.0, 34.0), (92.5, 34.0), 0.5) > 5 * down[-1]


def test_a_press_is_worth_the_danger_removed_and_the_regain_from_the_engines_own_rules():
    """Lesson 23: the press's worth is built from the engine's definitions: closing down to pressing
    distance at his pressing pace (T3, T4) while the carrier still has it (from when the ball is
    under control where play is going, O8) takes away their threat there; reaching him before he
    can react and play it (D1), then D8's race from the edge of his reach, wins ours (D9). Its
    metres are the run to pressing distance at that pace."""
    scenes = (((30.0, 34.0), (18.0, 34.0), 0.3, 0.0), ((30.0, 34.0), (18.0, 34.0), 0.3, 3.0),
              ((92.0, 20.0), (89.0, 21.0), 0.3, 0.0))
    for carrier_at, presser_at, settling, vx in scenes:
        e, first, _ = press_scene(carrier_at, presser_at)
        first.vx = vx  # running toward the carrier along x, or standing
        first.profile.attributes["work_rate"] = 0.2  # a slow press: his pace binds well below his top speed
        at(e, 30, settling)
        gap = e.brains["home"].press_gap_m
        d = math.hypot(carrier_at[0] - presser_at[0], carrier_at[1] - presser_at[1])
        along = vx * (carrier_at[0] - presser_at[0]) / d
        pace = 5.0 + 2.0 * 0.2
        controlled = e.ball_eta(*carrier_at)
        closed = pacing.closes_down(first.physique.time_to_cover(d - gap, along, pace), controlled)
        reach = min(gap, decisions.LUNGE_REACH_M)  # he commits once the carrier is within his reach
        in_reach = first.physique.time_to_cover(d - reach, along, pace)
        late = controlled + decisions.GENERIC_REACTION_S - in_reach
        before = decisions.sigmoid(late / decisions.LANE_MARGIN_S)
        wins = before * decisions.tackle_chance(reach, first.profile["tackling"])
        theirs, ours = decisions.value(*carrier_at, 0.0), decisions.value(*carrier_at, 105.0)
        goals, metres = e.press_run(first)
        assert math.isclose(goals, closed * theirs + wins * ours, rel_tol=1e-12)
        assert math.isclose(metres, pacing.metres_above(d - gap, pace, first.physique.cs))
        assert closed > 0 and wins > 0
    # The danger term reads when the ball is under control: a carrier who has it later is caught more.
    assert pacing.closes_down(2.0, 1.5) > pacing.closes_down(2.0, 0.0)


def test_a_press_is_timed_to_where_a_pass_in_flight_is_going():
    """O8: once he has reacted to a pass travelling to a receiver near home's goal, the presser
    near the receiver is judged against the ball arriving there (the moment to press), not
    against the ball in the air."""
    e, first, brain = press_scene(carrier_at=(40.0, 34.0), presser_at=(19.0, 34.0))
    e.by_id["a9"].x, e.by_id["a9"].y = 22.0, 34.0
    e.t = 30 * MIN
    passer = e.by_id["a10"]
    passer.heading = math.pi
    e.give(passer.id)
    e.ball = (39.63, 34.0, 0.0, 0.0, 0.0, 0.0)
    e.pass_to(passer, 22.0, 34.0, lofted=False, receiver="a9")
    assert e.possessor is None and e.pass_target == (22.0, 34.0)
    at_strike = e.press_goals(first)
    e.t += 2 * e.reaction(first)
    reacted = e.press_goals(first)
    assert math.hypot(e.play_point(first)[0] - 22.0, e.play_point(first)[1] - 34.0) < 5.0
    assert reacted > at_strike and reacted > 0.01


def test_nobody_presses_when_none_of_them_thinks_it_worth_it():
    e, first, brain = press_scene(carrier_at=(95.0, 34.0), presser_at=(80.0, 34.0))
    for pid, at_x in (("h6", 79.0), ("h8", 78.0)):
        e.by_id[pid].x, e.by_id[pid].y = at_x, 34.0
    at(e, 30, 0.0)
    for pid in brain.ranked:
        worn(e.by_id[pid].physique, 0.9)
    assert e.who_presses(brain) == []
    e.by_id["h8"].physique = Body(5.18, 10.0, 3.9)  # the third is fresh: asked in turn, he goes
    assert e.who_presses(brain) == ["h8"]


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


def test_stamina_and_work_rate_change_the_choice_per_player():
    """A1, A5: in the same 16 m press at halfway at minute 60 with the slow store 40% down, an
    average player declines; more stamina alone (he pays less) or a higher work rate alone (he
    values it more) changes the choice, through the engine's own call."""
    def presses(stamina: float, work_rate: float) -> bool:
        e, first, brain = press_scene((52.5, 34.0), (36.5, 34.0))
        first.profile.attributes["stamina"], first.profile.attributes["work_rate"] = stamina, work_rate
        worn(first.physique, 0.4)
        at(e, 60, 0.0)
        return e.accepts_press(first)

    assert not presses(0.5, 0.5)
    assert presses(1.0, 0.5) and presses(0.5, 1.0)
    body = worn(Body(5.18, 10.0, 3.9), 0.4)
    assert pacing.cost(body, 0.9, 60 * MIN, 5.0) < pacing.cost(body, 0.1, 60 * MIN, 5.0)
    assert pacing.worth(0.01, 0.9) > pacing.worth(0.01, 0.1)
    assert pacing.worth(-0.01, 0.5) == 0.0  # a run that loses ground is worth nothing, never less


def test_the_price_rises_as_the_slow_store_falls_and_with_the_match_left():
    body = Body(5.18, 10.0, 3.9)
    assert pacing.hazard(body, 0.5, 0.0) == 0.0  # fresh: running hard costs him nothing
    worn(body, 0.4)
    early, mid, end = (pacing.hazard(body, 0.5, m * MIN) for m in (10, 60, 90))
    assert early > mid > end == 0.0
    worn(body, 0.6)
    assert pacing.hazard(body, 0.5, 60 * MIN) > mid
    assert pacing.cost(body, 0.5, 60 * MIN, 10.0) == 2 * pacing.cost(body, 0.5, 60 * MIN, 5.0)  # per metre
    # A dip in the reserve after a sprint refills in minutes: it is his body's limit, not a reason to
    # save himself for the rest of the match.
    body = Body(5.18, 10.0, 3.9)
    body.reserve = 0.3 * D0
    assert pacing.hazard(body, 0.5, 10 * MIN) == 0.0
    assert pacing.metres_above(20.0, 10.0, 3.9) == 20.0 * 6.1 / 10.0
    assert pacing.metres_above(20.0, 3.0, 3.9) == 0.0


def test_the_metre_price_is_the_stated_argument():
    """Design (P17), stated before measuring: a hard 20 m chase by a moderately tired player costs
    about what a press in midfield is worth. The reference press is the engine's own worth for a
    settled carrier at halfway with the presser 8 m off; if the engine's estimate moves, the
    recorded anchor must be re-derived (this fails)."""
    e, first, _ = press_scene((52.5, 34.0), (44.5, 34.0))
    at(e, 45, 0.0)
    assert math.isclose(e.press_goals(first), pacing.MIDFIELD_PRESS_GOALS, rel_tol=0.05)
    body = worn(Body(5.18, 10.0, 3.9), 0.2)
    assert math.isclose(pacing.hazard(body, 0.5, 45 * MIN), pacing.MODERATE_HAZARD)
    chase = pacing.metres_above(20.0, 10.0, 3.9)
    assert math.isclose(chase, pacing.CHASE_ABOVE_M)
    assert math.isclose(pacing.cost(body, 0.5, 45 * MIN, chase), pacing.MIDFIELD_PRESS_GOALS)


def test_a_run_is_asked_for_at_full_capability_while_free_and_slower_as_it_costs_more():
    body = Body(5.18, 10.0, 3.9)
    assert pacing.run_speed(body, 0.5, 0.5, 30 * MIN, 0.01, 30.0) == body.v0
    assert pacing.run_speed(body, 0.5, 0.5, 30 * MIN, 0.0, 30.0) == body.v0  # costs nothing: as before pacing
    worn(body, 0.5)
    valuable = pacing.run_speed(body, 0.5, 0.5, 30 * MIN, 0.01, 30.0)
    slight = pacing.run_speed(body, 0.5, 0.5, 30 * MIN, 0.001, 30.0)
    short = pacing.run_speed(body, 0.5, 0.5, 30 * MIN, 0.001, 3.0)
    assert body.cs < slight < valuable < body.v0
    assert slight < short  # the same worth over a shorter run is cheaper, so asked faster
    assert pacing.run_speed(body, 0.5, 0.5, 90 * MIN, 0.001, 30.0) == body.v0  # the final whistle


def test_a_choice_never_changes_the_body():
    """Pricing, choosing and asking for a speed read the body and leave it as it was; the speed he
    gets is still capped by his body."""
    e, first, brain = press_scene()
    worn(first.physique, 0.4)
    at(e, 60, 0.0)
    before = astuple(first.physique), first.physique.top_speed(), first.physique.accel_limit(3.0)
    e.who_presses(brain)
    e.accepts_press(first)
    asked = e.run_speed(first, 0.001, 70.0, 34.0)
    pacing.hazard(first.physique, 0.5, e.t)
    after = astuple(first.physique), first.physique.top_speed(), first.physique.accel_limit(3.0)
    assert before == after
    assert first.physique.cs < asked < first.physique.v0
    body = Body(5.18, 10.0, 3.9, reserve=0.05 * D0)  # nearly empty: his body allows little above cs
    want = pacing.run_speed(body, 0.5, 0.5, 89 * MIN, 0.05, 30.0)  # the slow store is full: nothing to save
    assert want > body.top_speed()  # he wants more than he has
    x = y = vx = vy = 0.0
    for _ in range(200):
        limit = body.top_speed()  # what his body allows when he takes the step
        x, y, vx, vy = move_body(x, y, vx, vy, 500.0, 0.0, want, body, DT)
        assert math.hypot(vx, vy) <= limit + 1e-9


def test_the_chase_estimate_at_a_chosen_speed_matches_running_at_it():
    """Lesson 23: the estimate of how far he gets at the speed he chooses is the body running it,
    within a frame of travel, from below the speed he chooses and from above it."""
    for start, cap in ((0.0, 5.0), (0.0, 6.5), (2.0, 8.0), (9.0, 5.0), (7.0, 6.0)):
        body = Body(5.18, 10.0, 3.9)
        body.spend = lambda *a, **k: None  # hold the reserve, so the body's limits stay put
        x, y, vx, vy = 0.0, 0.0, start, 0.0
        frames = int(3.0 / DT)
        for _ in range(frames):
            x, y, vx, vy = move_body(x, y, vx, vy, 500.0, 0.0, cap, body, DT)
        estimate = body.distance_in(frames * DT, start, cap)
        assert abs(estimate - x) < max(cap, start) * DT, (start, cap, estimate, x)
        assert math.isclose(body.time_to_cover(estimate, start, cap), frames * DT, rel_tol=1e-3)
    body = Body(5.18, 10.0, 3.9)
    assert body.distance_in(3.0, 2.0, cap=50.0) == body.distance_in(3.0, 2.0)  # a cap above the body is none
    for cap in (5.0, 7.0, 9.0):  # he speeds up as the body allows, never past what he chose
        for k in range(1, 200):
            t0, t1 = (k - 1) * 0.02, k * 0.02
            pace = (body.distance_in(t1, 0.0, cap) - body.distance_in(t0, 0.0, cap)) / 0.02
            assert pace <= cap + 1e-6
            assert body.distance_in(t1, 0.0, cap) <= body.distance_in(t1, 0.0) + 1e-9
        assert math.isclose(body.distance_in(10.0, 0.0, cap) - body.distance_in(9.0, 0.0, cap), cap)
    # The reach test the chase uses honours the cap: 10 m to close in 2.5 s from standing is in reach
    # at his body's best (about 11.0 m), not at 5 m/s (about 9.6 m).
    assert can_get_to(body, 11.0, 0.0, 1.0, 0.0, 0.0, 2.5)[0]
    assert not can_get_to(body, 11.0, 0.0, 1.0, 0.0, 0.0, 2.5, cap=5.0)[0]
    slow = 3.0 / BRAKE_MAX  # from 9 m/s braking to 6, then holding 6
    braking = 9 * slow - BRAKE_MAX * slow**2 / 2
    assert math.isclose(body.distance_in(2.0, 9.0, cap=6.0), braking + 6 * (2 - slow))


def test_each_full_speed_run_asks_for_what_the_situation_makes_it_worth():
    """O4, D8 and the chase through P17: a run in behind is worth the threat it adds, a lunge and a
    loose ball what winning it there is worth (ours plus theirs), each over its own distance; a
    keeper's dash stays all-out."""
    e = Engine(1, styles={"home": Style(), "away": Style()})
    runner = e.by_id["h9"]
    average(runner)
    worn(runner.physique, 0.4)
    runner.x, runner.y = 55.0, 30.0
    e.t = 30 * MIN
    e.possessor = "h7"
    e.brains["home"].in_possession = True
    e.ball = (50.0, 34.0, 0.0, 0.0, 0.0, 0.0)
    e.runs[runner.id] = (85.0, 30.0, e.t)  # a run already under way
    gain = decisions.value(85.0, 30.0, 105.0) - decisions.value(50.0, 34.0, 105.0)
    assert e.shape_target(runner)[2] == e.run_speed(runner, gain, 85.0, 30.0) < runner.physique.v0
    # The engine asks the rule over the run he would make, from where he is to where he goes.
    assert e.run_speed(runner, gain, 85.0, 30.0) == pacing.run_speed(
        runner.physique, 0.5, 0.5, e.t, gain, math.hypot(85.0 - 55.0, 30.0 - 30.0))
    del e.runs[runner.id]
    e.possessor = None
    e.lunges[runner.id] = e.t + 0.3
    contest = e.contest_goals("home", 50.0, 34.0)
    assert contest == decisions.value(50.0, 34.0, 105.0) + decisions.value(50.0, 34.0, 0.0)
    assert e.shape_target(runner)[2] == e.run_speed(runner, contest, 50.0, 34.0)
    del e.lunges[runner.id]
    e.chase = {"home": (runner.id, 75.0, 10.0)}
    asked = e.shape_target(runner)[2]
    assert asked == e.run_speed(runner, e.contest_goals("home", 75.0, 10.0), 75.0, 10.0) < runner.physique.v0
    keeper = e.by_id["h1"]
    e.chase = {"home": (keeper.id, 10.0, 34.0)}
    assert e.shape_target(keeper)[2] == SPRINT


def test_the_chase_plan_judges_outfield_players_at_their_chosen_speed(monkeypatch):
    """Lesson 23: who chases a loose ball is decided at the speed each would run to each point, and
    a keeper at his body's best; the arrival time it ranks by uses the same speed."""
    e = Engine(1, styles={"home": Style(), "away": Style()})
    e.possessor, e.restart = None, None
    e.ball = (52.0, 34.0, 3.0, 0.0, 0.0, 0.0)
    for p in e.players:
        worn(p.physique, 0.3)
    e.t = 30 * MIN
    calls, covers = {}, []
    real, real_cover = e.can_reach, Body.time_to_cover

    def spy(p, bx, by, bz, t, *a, cap=None, **k):
        calls.setdefault(p.id, []).append((bx, by, cap))
        return real(p, bx, by, bz, t, *a, cap=cap, **k)

    def cover_spy(body, gap, along=0.0, cap=None):
        covers.append(cap)
        return real_cover(body, gap, along, cap)

    monkeypatch.setattr(e, "can_reach", spy)
    monkeypatch.setattr(Body, "time_to_cover", cover_spy)
    monkeypatch.setattr(e, "reacting_since", lambda p: -99.0)
    e.plan_chase()
    outfield = [pid for pid in calls if e.by_id[pid].role != "GK"]
    assert outfield
    later = 0
    for pid in outfield:  # judged at the speed he would chase the ball to each point at
        p = e.by_id[pid]
        for bx, by, cap in calls[pid]:
            assert cap == e.run_speed(p, e.contest_goals(p.team, bx, by), bx, by)
            later += math.hypot(bx - 52.0, by - 34.0) > 1.0
    assert later  # some points along the ball's path, not only where it is now
    assert all(cap is None for pid, cs in calls.items() if e.by_id[pid].role == "GK" for _, _, cap in cs)
    assert any(cap is not None for cap in covers)  # the arrival time is at the chosen speed too
    monkeypatch.undo()
    # The engine's reach test honours the cap: 10 m to close in 2.5 s is in reach flat out, not at 5 m/s.
    p = e.by_id[outfield[0]]
    p.physique, p.x, p.y, p.vx, p.vy = Body(5.18, 10.0, 3.9), 40.0, 34.0, 0.0, 0.0
    e.reach = lambda p, bx, by, bz, at: (1.0, 2.0)
    assert e.can_reach(p, 51.0, 34.0, 0.0, 2.5)[0] and not e.can_reach(p, 51.0, 34.0, 0.0, 2.5, cap=5.0)[0]


def test_the_speed_rule_at_its_stated_points():
    """P17's shape: half of the speed above critical when worth equals what the run costs flat out
    (cost counted at his top-speed capability, design), and a run worth nothing that costs nothing
    is not made."""
    body = worn(Body(5.18, 10.0, 3.9), 0.4)
    body.reserve = 0.2 * D0  # fatigue has lowered what his body allows; the cost still counts v0
    metres = pacing.metres_above(30.0, body.v0, body.cs)
    c = pacing.cost(body, 0.5, 60 * MIN, metres)
    assert body.top_speed() < body.v0
    half = body.cs + (body.v0 - body.cs) / 2
    assert math.isclose(pacing.run_speed(body, 0.5, 0.5, 60 * MIN, c, 30.0), half)
    assert not pacing.accepts(Body(5.18, 10.0, 3.9), 0.5, 0.5, 0.0, 0.0, 0.0)


def test_the_engine_prices_his_own_run_with_his_own_attributes_and_his_teams_pressing_distance():
    """Engine.run_speed passes the length of the run he would make and his own stamina and work
    rate; the press is priced to his team's pressing distance (T4)."""
    e = Engine(1, styles={"home": Style(pressing_intensity=0.8), "away": Style()})
    p = e.by_id["h9"]
    worn(p.physique, 0.4)
    p.x, p.y = 40.0, 20.0
    p.profile.attributes["stamina"], p.profile.attributes["work_rate"] = 0.9, 0.2
    e.t = 50 * MIN
    asked = e.run_speed(p, 0.004, 52.0, 25.0)
    assert asked == pacing.run_speed(p.physique, 0.9, 0.2, e.t, 0.004, 13.0)
    assert asked != pacing.run_speed(p.physique, 0.5, 0.5, e.t, 0.004, 13.0)
    e.possessor, e.restart, e.kicked = "a10", None, None
    e.by_id["a10"].x, e.by_id["a10"].y = 52.5, 34.0
    e.ball = (52.5, 34.0, 0.0, 0.0, 0.0, 0.0)
    q = e.by_id["h7"]
    q.x, q.y, q.vx, q.vy = 42.5, 34.0, 0.0, 0.0
    gap = e.brains["home"].press_gap_m
    assert gap == 1.5  # high pressing intensity stands tighter than the default 2 m
    _, metres = e.press_run(q)
    assert math.isclose(metres, pacing.metres_above(10.0 - gap, e.press_pace(q), q.physique.cs))


def test_the_brain_asks_its_players_soonest_first():
    """T3: the suggestion is the order they could reach the ball, soonest first."""
    from ninety.sim.team import TeamBrain

    brain = TeamBrain("home")
    brain.update(0.0, False, 50.0, {"h6": 2.0, "h7": 0.5, "h8": 1.2})
    assert brain.ranked == ["h7", "h8", "h6"] and brain.pressers == ["h7", "h8"]
