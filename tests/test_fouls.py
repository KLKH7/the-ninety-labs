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
    assert e.leg_meets(dfd, att, 61.0, 34.0)
    e, dfd, att = lunge_scene(35.5)
    assert not e.leg_meets(dfd, att, 61.0, 34.0)


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
    assert e.leg_meets(dfd, att, 61.0, 34.0)
    att.heading = 1.5708  # facing across it: it passes in front of his chest
    assert not e.leg_meets(dfd, att, 61.0, 34.0)


def test_his_leg_reaches_a_foot_from_his_body_and_no_further():
    # The ball 3 m away along y = 34; h9 stands 1.5 m out on that line, beyond a foot's reach
    # (CONTROL_M): the lunge's leg stops short of him.
    e, dfd, att = lunge_scene(34.0)
    att.x = 61.5
    assert not e.leg_meets(dfd, att, 63.0, 34.0)
    att.x = 60.6
    assert e.leg_meets(dfd, att, 63.0, 34.0)
