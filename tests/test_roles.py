"""Roles and mentalities (roles.py): what an archetype makes a player want to do off the ball."""

import math

from ninety.sim import engine, offball, perception, roles
from ninety.sim.body import Body, move, sprint_cost_m
from ninety.sim.engine import PITCH_Y, Engine


def attacking(archetype: str, pid: str, ball: tuple[float, float], build_up: str = "quick"):
    """Home has the ball at `ball`, settled and unpressed; everyone else stands still and away."""
    e = Engine(3)
    p = e.by_id[pid]
    p.profile.archetype = archetype
    p.profile.traits = []
    brain = e.brains["home"]
    brain.in_possession, brain.build_up = True, build_up
    carrier = e.by_id["h7"] if pid != "h7" else e.by_id["h8"]
    for q in e.players:
        q.vx = q.vy = 0.0
        if q.team == "away":
            q.x, q.y = 103.0, 66.0 if q.y > PITCH_Y / 2 else 2.0
    e.brains["away"].line_x = 100.0
    carrier.x, carrier.y = ball
    e.give(carrier.id)
    e.hold_until = e.t
    e.ball = (*ball, 0.0, 0.0, 0.0, 0.0)
    return e, p, carrier, brain


def sees_them(e: Engine) -> None:
    """Every home player has just seen every opponent where he stands (so knows he is onside)."""
    for q in e.players:
        if q.team == "home":
            e.beliefs[q.id].seen = {o.id: perception.Sighting(o.x, o.y, 0.0, 0.0, e.t)
                                    for o in e.players if o.team == "away"}


def test_an_overlapping_full_back_runs_beyond_the_ball_on_his_flank():
    e, p, carrier, brain = attacking("overlapping", "h2", (60.0, 12.0))  # RB, the ball on his flank
    p.x, p.y = 50.0, 12.0
    sees_them(e)
    run = e.move_spot(p, carrier, brain, "overlap")
    assert run and run[0] > carrier.x and run[1] < 10.0  # past the ball, along his touchline
    e, p, carrier, brain = attacking("defensive", "h2", (60.0, 12.0))
    p.x, p.y = 50.0, 12.0
    sees_them(e)
    assert e.move_spot(p, carrier, brain, "overlap") is None  # not in a defensive full back's repertoire


def test_a_box_to_box_midfielder_arrives_late_once_the_ball_is_in_the_final_third():
    e, p, carrier, brain = attacking("box_to_box", "h6", (80.0, 30.0))
    p.x, p.y = 65.0, 30.0
    sees_them(e)
    run = e.move_spot(p, carrier, brain, "late")
    assert run and abs(run[0] - (105.0 - roles.LATE_RUN_DEPTH_M)) < 1e-9
    e, p, carrier, brain = attacking("box_to_box", "h6", (50.0, 30.0))  # not yet in the final third
    p.x, p.y = 40.0, 30.0
    sees_them(e)
    assert e.move_spot(p, carrier, brain, "late") is None


def test_an_inside_forward_runs_from_wide_into_the_half_space():
    e, p, carrier, brain = attacking("inside_forward", "h9", (60.0, 30.0))  # RW
    p.x, p.y = 70.0, 8.0
    e.brains["away"].line_x = 80.0
    sees_them(e)
    run = e.move_spot(p, carrier, brain, "channel")
    assert run and abs(run[1] - (PITCH_Y / 2 - roles.DIAGONAL_HALF_SPACE_M)) < 1e-9 and run[0] > 80.0


def test_a_direct_side_sends_only_its_attacking_roles():
    e, p, carrier, brain = attacking("touchline_winger", "h9", (60.0, 30.0), "direct")
    p.x, p.y = 70.0, 8.0
    e.brains["away"].line_x = 80.0
    sees_them(e)
    assert e.move_spot(p, carrier, brain, "in_behind") is None  # balanced duty: he holds on a direct side
    e, p, carrier, brain = attacking("touchline_winger", "h9", (60.0, 30.0), "quick")
    p.x, p.y = 70.0, 8.0
    e.brains["away"].line_x = 80.0
    sees_them(e)
    assert e.move_spot(p, carrier, brain, "in_behind")


def test_a_habit_of_running_in_behind_sends_him_even_when_his_side_would_not():
    e, p, carrier, brain = attacking("touchline_winger", "h9", (60.0, 30.0), "direct")
    p.x, p.y = 70.0, 8.0
    e.brains["away"].line_x = 80.0
    p.profile.traits = ["runs_in_behind"]
    sees_them(e)
    assert e.move_spot(p, carrier, brain, "in_behind")


def test_coming_short_is_back_toward_the_ball_and_only_in_the_roles_that_do_it():
    e, p, carrier, brain = attacking("deep_playmaker", "h7", (25.0, 20.0))
    p.x, p.y = 50.0, 34.0  # well ahead of the ball
    assert e.move_spot(p, carrier, brain, "short") == (25.0 + roles.DROP_AHEAD_M, (20.0 + PITCH_Y / 2) / 2)
    p.x = 30.0  # already nearer the ball than that: there is nothing to come short to
    assert e.move_spot(p, carrier, brain, "short") is None
    e, p, carrier, brain = attacking("stopper", "h7", (25.0, 20.0))
    p.x, p.y = 50.0, 34.0
    assert e.move_spot(p, carrier, brain, "short") is None


def test_coming_short_never_goes_beyond_the_onside_line():
    e, p, carrier, brain = attacking("target_forward", "h10", (85.0, 34.0))
    p.x, p.y = 101.0, 34.0
    for q in e.players:
        if q.team == "away":
            q.x = 104.0 if q.role == "GK" else 92.0
    sees_them(e)
    spot = e.move_spot(p, carrier, brain, "short")
    assert spot and spot[0] <= 92.0  # 85 + 12 = 97 would be offside


def runner(archetype: str, build_up: str = "quick"):
    """A striker (h10) level with their line, the carrier 25 m behind him, settled and unpressed."""
    e, p, carrier, brain = attacking(archetype, "h10", (55.0, 34.0), build_up)
    e.brains["away"].line_x = 80.0
    for q in e.players:
        if q.team == "away":
            q.x, q.y = (81.0, 20.0 + 3.0 * int(q.id[1:])) if q.role != "GK" else (104.0, 34.0)
    p.x, p.y = 79.0, 34.0
    sees_them(e)
    return e, p, carrier, brain


def choices(archetype: str, build_up: str = "quick", n: int = 300) -> dict[str, int]:
    """How often he chooses each move over n fresh looks at the same picture, every move he may
    make being worth the same to his team: only the priors tell the moves apart."""
    e, p, carrier, brain = runner(archetype, build_up)
    p.x = 70.0  # ahead of the ball by enough to come short as well as to run
    p.profile.attributes["decisions"] = 0.3  # a loose decision-maker, so a lean shows as a lean (D4)
    e.move_worth = lambda *_: 0.02
    count: dict[str, int] = {}
    for _ in range(n):
        e.moves = {}
        e.movement(p, carrier, brain)
        kind = e.moves[p.id][0]
        count[kind] = count.get(kind, 0) + 1
    return count


def test_a_habit_strengthens_a_move_of_his_role_and_never_adds_one():
    e, p, carrier, brain = runner("poacher")
    plain = e.move_prior(p, brain, "in_behind")
    p.profile.traits = ["runs_in_behind"]
    assert e.move_prior(p, brain, "in_behind") > plain
    p.role, p.profile.archetype = "RCB", "stopper"  # no run in behind in his role, whatever his habits
    assert e.move_prior(p, brain, "in_behind") == 0.0 and e.move_spot(p, carrier, brain, "in_behind") is None


def test_a_role_leans_toward_its_move_without_choosing_it_for_him():
    poacher, target = choices("poacher"), choices("target_forward")
    assert poacher.get("in_behind", 0) > 1.5 * target.get("in_behind", 0)  # priors 1.5 against 0.7
    assert target.get("short", 0) > 1.5 * poacher.get("short", 0)  # 1.5 against none
    assert poacher.get("hold", 0) > 0 and poacher.get("in_behind", 0) < 300  # a lean, not a rule


def test_a_direct_side_sends_its_striker_in_behind_more_than_a_patient_side():
    direct, patient = choices("poacher", "direct"), choices("poacher", "patient")
    assert direct.get("in_behind", 0) > 1.3 * patient.get("in_behind", 0)  # style weights 1.5 against 0.7


def test_a_move_is_worth_the_chance_he_is_found_times_the_race_times_the_ball_there():
    e, p, carrier, brain = runner("poacher")
    spot = e.move_spot(p, carrier, brain, "in_behind")
    base = e.move_worth(p, carrier, spot)
    assert base > 0
    away = next(q for q in e.players if q.team == "away" and q.role != "GK")
    away.x, away.y = spot[0] + 3.0, spot[1]  # beyond the spot, off the lane: only the race changes
    sees_them(e)
    assert e.move_worth(p, carrier, spot) < base
    e, p, carrier, brain = runner("poacher")
    e.hold_until = e.t + 2.0  # the carrier needs two more seconds: the ball arrives later
    assert e.move_worth(p, carrier, spot) < base
    import ninety.sim.decisions as D
    real = D.value
    D.value = lambda *a, **k: 0.0  # the ball is worth nothing there
    try:
        assert e.move_worth(p, carrier, spot) == 0.0
    finally:
        D.value = real


def test_a_run_keeps_its_spot_while_he_carries_on_and_is_a_sprint_from_the_first_frame():
    e, p, carrier, brain = runner("poacher")
    spot = e.move_spot(p, carrier, brain, "in_behind")
    e.move_worth = lambda _p, _c, s: 0.05 if s == spot else 0.0
    assert e.movement(p, carrier, brain) == (*spot, engine.SPRINT)  # chosen and sprinting at once
    e.moves[p.id] = ("in_behind", *spot, e.t - engine.LOOK_S - 0.01)  # his next look
    for q in e.players:  # their line has stepped up two metres: a fresh run would aim elsewhere
        if q.team == "away" and q.role != "GK":
            q.x += 2.0
    sees_them(e)
    p.x += 2.0
    assert e.move_spot(p, carrier, brain, "in_behind") != spot
    assert e.movement(p, carrier, brain) == (*spot, engine.SPRINT)


def test_between_looks_he_carries_on_without_weighing_again():
    e, p, carrier, brain = runner("poacher")
    e.moves[p.id] = ("in_behind", 92.0, 30.0, e.t)
    e.move_worth = lambda *_: 1 / 0  # any weighing would fail
    assert e.movement(p, carrier, brain) == (92.0, 30.0, engine.SPRINT)


def test_a_spent_player_cannot_make_the_run():
    e, p, carrier, brain = runner("poacher")
    spot = e.move_spot(p, carrier, brain, "in_behind")
    gap = round(math.hypot(spot[0] - p.x, spot[1] - p.y))
    cost = sprint_cost_m(p.physique.f0, p.physique.v0, p.physique.cs, gap, engine.DT)
    assert cost > 0
    p.physique.reserve = cost * 1.01  # P10: just enough left to sprint it
    assert e.move_spot(p, carrier, brain, "in_behind")
    p.physique.reserve = cost * 0.99  # not quite
    assert e.move_spot(p, carrier, brain, "in_behind") is None


def test_a_sprint_costs_what_the_body_spends_running_it():
    body = Body(5.18, 10.0, 3.9)
    x = vx = 0.0
    for _ in range(1000):
        x, _, vx, _ = move(x, 0.0, vx, 0.0, 30.0, 0.0, math.inf, body, engine.DT)
    assert abs(sprint_cost_m(5.18, 10.0, 3.9, 30, engine.DT) - body.spent) < 0.5
    assert sprint_cost_m(5.18, 10.0, 3.9, 30, engine.DT) > 30 - 3.9 * Body(5.18, 10.0, 3.9).time_to_cover(30)


def test_two_runners_do_not_attack_the_same_space():
    e, p, carrier, brain = runner("poacher")
    spot = e.move_spot(p, carrier, brain, "in_behind")
    e.moves = {"h9": ("in_behind", spot[0], spot[1] + 1.0, e.t)}
    assert e.move_spot(p, carrier, brain, "in_behind") is None
    e.moves = {"h9": ("hold", spot[0], spot[1] + 1.0, e.t)}  # holding there is not running there
    assert e.move_spot(p, carrier, brain, "in_behind")


def test_no_run_from_an_offside_position_or_to_a_pressed_carrier():
    e, p, carrier, brain = runner("poacher")
    assert e.move_spot(p, carrier, brain, "in_behind")
    p.x = 85.0  # beyond their second-last defender, as he sees them
    assert e.move_spot(p, carrier, brain, "in_behind") is None
    e, p, carrier, brain = attacking("box_to_box", "h6", (80.0, 30.0))  # a late run, from offside
    for q in e.players:
        if q.team == "away":
            q.x = 104.0 if q.role == "GK" else 90.0
    p.x, p.y = 75.0, 30.0
    sees_them(e)
    assert e.move_spot(p, carrier, brain, "late")
    p.x = 95.0
    assert e.move_spot(p, carrier, brain, "late") is None
    e, p, carrier, brain = runner("poacher")
    presser = next(q for q in e.players if q.team == "away" and q.role != "GK")
    presser.x, presser.y = carrier.x + 2.0, carrier.y  # the carrier is pressed
    sees_them(e)
    assert e.move_spot(p, carrier, brain, "in_behind") is None


def test_an_overlap_needs_the_ball_ahead_on_his_flank_past_his_own_third():
    def overlap(ball, at):
        e, p, carrier, brain = attacking("overlapping", "h2", ball)
        p.x, p.y = at
        sees_them(e)
        return e.move_spot(p, carrier, brain, "overlap")
    assert overlap((60.0, 12.0), (50.0, 12.0))
    assert overlap((60.0, 56.0), (50.0, 12.0)) is None  # the ball is on the other flank
    assert overlap((60.0, 12.0), (65.0, 12.0)) is None  # he is already ahead of it
    assert overlap((30.0, 12.0), (20.0, 12.0)) is None  # still in his own third


def test_anticipation_starts_the_run_before_the_carrier_is_ready():
    e, p, carrier, brain = runner("poacher")
    e.hold_until = e.t + 0.3  # the carrier is still settling the ball
    p.profile.attributes["anticipation"] = 0.9
    assert e.move_spot(p, carrier, brain, "in_behind")
    p.profile.attributes["anticipation"] = 0.3
    assert e.move_spot(p, carrier, brain, "in_behind") is None


def test_the_race_to_a_spot_is_lost_to_whoever_gets_there_later():
    early = offball.receive_chance(1.0, 1.5, 2.5, 0.3)
    assert offball.receive_chance(2.0, 1.5, 2.5, 0.3) < early  # he is later than the ball
    assert offball.receive_chance(1.0, 2.0, 2.5, 0.3) < early  # the ball is later than him
    assert offball.receive_chance(1.0, 1.5, 3.5, 0.3) > early  # the defender is further away


def test_a_good_decision_maker_makes_the_better_move_and_he_carries_on_with_his_move():
    import random
    rng = random.Random(1)
    worth = {"hold": 0.010, "in_behind": 0.020}
    sharp = sum(offball.pick_move(worth, 0.15, None, rng, 0.0) == "in_behind" for _ in range(500))
    loose = sum(offball.pick_move(worth, 0.75, None, rng, 0.0) == "in_behind" for _ in range(500))
    assert sharp > loose > 250
    even = {"hold": 0.010, "in_behind": 0.010}
    kept = sum(offball.pick_move(even, 0.75, "hold", rng, 0.003) == "hold" for _ in range(500))
    assert kept > 300


def test_the_role_shifts_his_spot_with_the_ball_and_never_beyond_the_last_line():
    base = offball.attacking_slot("RB", 0.0, 50.0, 34.0, 80.0)
    higher = offball.attacking_slot("RB", 0.0, 50.0, 34.0, 80.0, 6.0, 0.0)
    inside = offball.attacking_slot("RB", 0.0, 50.0, 34.0, 80.0, 0.0, 5.0)
    assert higher[0] == base[0] + 6.0 and inside[1] == base[1] + 5.0  # RB is on the low-y side
    capped = offball.attacking_slot("RCM", 0.0, 70.0, 34.0, 75.0, 30.0, 0.0)
    assert capped[0] <= 75.0  # L10: not beyond where he would be onside


def test_each_side_draws_a_build_up_style_from_its_own_stream():
    styles = {Engine(s).brains["home"].build_up for s in range(40)}
    assert styles == set(roles.STYLES)
    assert Engine(5).brains["home"].block == Engine(5).brains["home"].block  # blocks unchanged by it
