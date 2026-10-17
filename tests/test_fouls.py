"""Fouls (Law 12): a lunge that arrives with the ball gone and sweeps through the man he went for."""

from ninety.sim.engine import Engine


def lunge_scene(victim_y: float):
    """a4 at (60, 34) lunging at the ball at (61, 34); h9 standing at (60.6, victim_y)."""
    e = Engine(3)
    dfd, att = e.by_id["a4"], e.by_id["h9"]
    for p in e.players:
        p.vx = p.vy = 0.0
        if p not in (att, dfd):
            p.x, p.y = (2.0, 2.0) if p.team == "home" else (103.0, 66.0)
    dfd.x, dfd.y = 60.0, 34.0
    att.x, att.y = 60.6, victim_y
    return e, dfd, att


def test_his_leg_meets_a_man_in_its_sweep_and_misses_one_off_it():
    e, dfd, att = lunge_scene(34.0)
    assert e.leg_meets(dfd.x, dfd.y, att.x, att.y, 61.0, 34.0, att.heading)
    e, dfd, att = lunge_scene(35.5)
    assert not e.leg_meets(dfd.x, dfd.y, att.x, att.y, 61.0, 34.0, att.heading)


def test_a_late_lunge_through_the_man_is_a_foul_and_a_free_kick_to_his_side():
    e, dfd, att = lunge_scene(34.0)
    e.possessor = None
    e.ball = (63.0, 34.0, 0.0, 0.0, 0.0, 0.0)  # he moved it on: beyond a foot's reach
    e.lunges[dfd.id] = e.t
    e.lunge_at[dfd.id] = att.id
    e.duels()
    fouls = [ev for ev in e.match.events if ev["type"] == "foul"]
    assert fouls and fouls[0]["player"] == dfd.id and fouls[0]["receiver"] == att.id
    assert e.restart and e.restart.kind == "free_kick" and e.restart.team == att.team


def test_a_lunge_that_misses_the_ball_and_the_man_is_no_foul():
    e, dfd, att = lunge_scene(36.0)
    e.possessor = None
    e.ball = (63.0, 34.0, 0.0, 0.0, 0.0, 0.0)
    e.lunges[dfd.id] = e.t
    e.lunge_at[dfd.id] = att.id
    e.duels()
    assert not [ev for ev in e.match.events if ev["type"] == "foul"]
    assert e.off_balance[dfd.id] > e.t and e.restart is None


def test_no_foul_while_the_ball_is_dead_for_a_restart():
    from ninety.sim.engine import Restart

    e, dfd, att = lunge_scene(34.0)
    e.possessor = None
    e.ball = (63.0, 34.0, 0.0, 0.0, 0.0, 0.0)
    e.restart = Restart("throw_in", "home", 63.0, 0.0, "h2", e.t + 10.0)
    e.lunges[dfd.id] = e.t
    e.lunge_at[dfd.id] = att.id
    e.duels()
    assert not [ev for ev in e.match.events if ev["type"] == "foul"]


def test_a_foul_closes_the_pass_in_flight_and_counts_one_in_his_own_box():
    e, dfd, att = lunge_scene(34.0)
    dfd.x, att.x = 95.0, 95.6  # inside the away side's own box (it defends the goal at x = 105)
    e.possessor = None
    e.ball = (98.0, 34.0, 0.0, 0.0, 0.0, 0.0)
    e.kicked = e.emit("pass", "home", 95.6, 34.0, player=att.id, receiver="h10", outcome=None)
    e.lunges[dfd.id] = e.t
    e.lunge_at[dfd.id] = att.id
    e.duels()
    passes = [ev for ev in e.match.events if ev["type"] == "pass"]
    assert passes[0]["outcome"] == "fail" and e.kicked is None
    assert e.penalties == 1


def test_whether_the_leg_meets_him_depends_on_which_way_he_faces():
    # The leg sweeps along y = 34; he stands 0.2 m off that line (GROUNDING P11: his body is wide
    # across the shoulders and shallow through the chest).
    e, dfd, att = lunge_scene(34.2)
    att.heading = 0.0  # facing along the leg's line: his shoulder is in its way
    assert e.leg_meets(dfd.x, dfd.y, att.x, att.y, 61.0, 34.0, att.heading)
    att.heading = 1.5708  # facing across it: it passes in front of his chest
    assert not e.leg_meets(dfd.x, dfd.y, att.x, att.y, 61.0, 34.0, att.heading)


def test_his_leg_reaches_a_foot_from_his_body_and_no_further():
    # The ball 3 m away along y = 34; h9 stands 1.5 m out on that line, beyond a foot's reach
    # (CONTROL_M): the lunge's leg stops short of him.
    e, dfd, att = lunge_scene(34.0)
    att.x = 61.5
    assert not e.leg_meets(dfd.x, dfd.y, att.x, att.y, 63.0, 34.0, att.heading)
    att.x = 60.6
    assert e.leg_meets(dfd.x, dfd.y, att.x, att.y, 63.0, 34.0, att.heading)


def box_foul():
    """a4 fouls h9 inside the away side's own box (it defends the goal at x = 105)."""
    e, dfd, att = lunge_scene(34.0)
    dfd.x, att.x = 95.0, 95.6
    e.possessor = None
    e.ball = (98.0, 34.0, 0.0, 0.0, 0.0, 0.0)
    e.lunges[dfd.id] = e.t
    e.lunge_at[dfd.id] = att.id
    e.duels()
    return e


def test_a_foul_in_his_own_box_is_a_penalty_from_the_mark_by_the_best_finisher():
    e = box_foul()
    r = e.restart
    assert r.kind == "penalty_kick" and r.team == "home" and (r.x, r.y) == (105.0 - 11.0, 34.0)
    outfield = [q for q in e.players if q.team == "home" and q.role != "GK"]
    best = max(outfield, key=lambda q: q.profile["finishing"])
    assert r.taker == best.id


def test_while_a_penalty_waits_everyone_stands_where_law_14_puts_them():
    from ninety.sim import decisions
    from ninety.sim.engine import PITCH_Y

    e = box_foul()
    r = e.restart
    for p in e.players:
        if p.id == r.taker:
            continue
        x, y = e.penalty_wait_spot(p)
        if p.role == "GK" and p.team == "away":
            assert (x, y) == (105.0, PITCH_Y / 2)
            continue
        assert not decisions.in_box(x, y, 105.0)
        assert ((x - r.x) ** 2 + (y - r.y) ** 2) ** 0.5 >= 9.15
        assert x <= r.x  # behind the mark


def test_when_the_penalty_is_taken_he_shoots_from_the_mark():
    e = box_foul()
    r = e.restart
    taker = e.by_id[r.taker]
    taker.x, taker.y, taker.heading = r.x - 0.9, r.y, 0.0  # in reach of the mark, not on it
    e.t = r.ready_at
    e.decide = lambda *a, **k: None  # only Law 14 may make him shoot
    for _ in range(25):
        e.step()
        if any(ev["type"] == "shot" for ev in e.match.events):
            break
    shots = [ev for ev in e.match.events if ev["type"] == "shot"]
    assert shots and shots[0]["player"] == taker.id and abs(shots[0]["x"] - r.x) < 0.05


def test_a_taker_facing_away_turns_to_the_goal_before_he_strikes_the_penalty():
    """P16: the ball on the mark is at his feet, not in his hands, so he faces the goal to strike it."""
    import math

    from ninety.sim.decisions import STRIKE_FACING

    e = box_foul()
    r = e.restart
    taker = e.by_id[r.taker]
    taker.x, taker.y, taker.heading = r.x, r.y, math.pi  # on the mark, his back to the goal
    e.t = r.ready_at
    e.decide = lambda *a, **k: None  # only Law 14 may make him shoot
    heading_at_shot = None
    for _ in range(4 * 25):
        e.step()
        if any(ev["type"] == "shot" for ev in e.match.events):
            heading_at_shot = taker.heading
            break
    assert heading_at_shot is not None
    to_goal = math.atan2(34.0 - taker.y, 105.0 - taker.x)
    off = abs((heading_at_shot - to_goal + math.pi) % (2 * math.pi) - math.pi)
    assert off <= STRIKE_FACING + 1e-9


def test_in_his_own_box_a_lunge_through_the_man_needs_a_surer_win():
    from ninety.sim.engine import COMMIT_P

    e, dfd, att = lunge_scene(34.0)
    dfd.x, att.x = 95.0, 95.6  # behind him, the ball beyond: the man is in his line
    line = e.foul_line(dfd, att, 96.0, 34.0)
    assert line > COMMIT_P
    dfd.x, att.x = 45.0, 45.6  # the same challenge in midfield: a miss is a free kick there
    assert e.foul_line(dfd, att, 46.0, 34.0) == 0.0
    dfd.x, dfd.y, att.x, att.y = 96.0, 36.0, 95.6, 34.0  # in the box, from in front and wide,
    e.dribble_to = (100.0, 34.0)  # the man carrying it on, not holding it
    assert e.foul_line(dfd, att, 96.0, 34.0) == 0.0


def test_he_foresees_the_man_running_on_into_his_lunge():
    e, dfd, att = lunge_scene(34.0)
    dfd.x, dfd.y = 95.5, 34.6  # beside him: his leg to the ball misses the man as they stand
    att.x, att.y, att.vx = 95.5, 34.0, 0.0
    e.dribble_to = (100.0, 34.0)  # carrying it, so not shielding it from him
    assert not e.leg_meets(dfd.x, dfd.y, att.x, att.y, 95.87, 34.0, att.heading)
    assert e.foul_line(dfd, att, 95.87, 34.0) == 0.0  # standing still: no risk
    att.vx = 5.0  # running on toward goal with it: by the time his foot arrives, the man is there
    assert e.foul_line(dfd, att, 95.87, 34.0) > 0.0


def test_at_a_penalty_the_keeper_guesses_the_side_about_as_often_as_keepers_do():
    import random

    from ninety.sim.engine import PENALTY_CORRECT_SIDE, SHOT_AIM_OFF_M

    e = box_foul()
    keeper, taker = e.keeper("away"), e.by_id[e.restart.taker]
    keeper.x, keeper.y, keeper.heading = 105.0, 34.0, 3.14159  # on his line, facing the kicker
    taker.x, taker.y = 93.6, 34.0
    e.rng = random.Random(5)

    def right_side(restart_kind):
        e.from_restart = restart_kind
        n = right = 0
        for _ in range(4000):
            aim = 34.0 + random.choice([-1, 1]) * random.uniform(*SHOT_AIM_OFF_M)
            read = e.keeper_read(keeper, taker, aim)
            n += 1
            right += (read - 34.0) * (aim - 34.0) > 0
        return right / n

    assert abs(right_side("penalty_kick") - PENALTY_CORRECT_SIDE) < 0.03
    assert right_side(None) > 0.75  # open play keeps his own read


def test_he_foresees_a_holding_man_shielding_it_from_him():
    e, dfd, att = lunge_scene(34.0)
    dfd.x, dfd.y = 95.5, 34.6
    att.x, att.y, att.vx = 95.5, 34.0, 0.0
    e.dribble_to = (100.0, 34.0)
    carrying = e.foul_line(dfd, att, 95.87, 34.0)
    e.dribble_to = None  # holding: the ball goes to his far side from the defender
    assert carrying == 0.0 and e.foul_line(dfd, att, 95.87, 34.0) > 0.0
