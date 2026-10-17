"""Law 11 (L10): offside position judged as the ball is played; an offence when that player then plays it."""

from ninety.sim.engine import Engine


def setup() -> tuple[Engine, object, object]:
    e = Engine(2)
    for p in e.players:
        p.vx = p.vy = 0.0
        if p.role != "GK":
            p.x = 30.0 if p.team == "home" else 70.0  # away defenders deep at x=70
    passer, runner = e.by_id["h6"], e.by_id["h9"]
    passer.x, passer.y = 55.0, 34.0
    e.give(passer.id)
    e.ball = (55.37, 34.0, 0.0, 0.0, 0.0, 0.0)
    return e, passer, runner


def test_a_team_mate_beyond_the_second_last_defender_and_the_ball_is_marked_offside():
    e, passer, runner = setup()
    runner.x = 80.0  # beyond the away line at 70 (the keeper is the last man)
    e.kick(passer, 15.0, 0.0, 0.0)
    assert runner.id in e.offside


def test_level_or_in_his_own_half_or_behind_the_ball_is_onside():
    for x in (70.0, 50.0, 54.0):
        e, passer, runner = setup()
        runner.x = x
        e.kick(passer, 15.0, 0.0, 0.0)
        assert runner.id not in e.offside, x


def test_playing_the_ball_from_an_offside_position_gives_a_free_kick_to_the_defenders():
    e, passer, runner = setup()
    runner.x, runner.y = 80.0, 34.0
    e.kicked = e.emit("pass", "home", 55.0, 34.0, player=passer.id)
    e.kick(passer, 15.0, 0.0, 0.0)
    assert e.touched(runner, 80.0, 34.0, controls=True)
    assert e.match.events[-1]["type"] == "offside" and e.restart.kind == "free_kick"
    assert e.restart.team == "away"
    assert next(ev for ev in e.match.events if ev["type"] == "pass")["outcome"] == "fail"


def test_no_offside_straight_from_a_throw_in():
    e, passer, runner = setup()
    runner.x = 80.0
    e.from_restart = "throw_in"
    e.kick(passer, 15.0, 0.0, 0.0)
    assert not e.offside


def test_an_opponents_deliberate_play_ends_the_offside_phase():
    e, passer, runner = setup()
    runner.x = 80.0
    e.kick(passer, 15.0, 0.0, 0.0)
    e.touched(e.by_id["a4"], 65.0, 34.0, controls=True)
    assert not e.offside


def test_in_his_own_half_he_is_onside_even_beyond_a_high_line():
    e, passer, runner = setup()
    for p in e.players:
        if p.team == "away" and p.role != "GK":
            p.x = 40.0  # a very high line, inside the home half
    passer.x = 30.0
    e.ball = (30.37, 34.0, 0.0, 0.0, 0.0, 0.0)
    runner.x = 50.0  # beyond their line, but in his own half
    e.kick(passer, 15.0, 0.0, 0.0)
    assert runner.id not in e.offside


def test_behind_the_ball_he_is_onside_even_beyond_their_line():
    e, passer, runner = setup()
    passer.x = 85.0
    e.ball = (85.37, 34.0, 0.0, 0.0, 0.0, 0.0)
    runner.x = 80.0  # beyond the line at 70, but behind the ball
    e.kick(passer, -15.0, 0.0, 0.0)
    assert runner.id not in e.offside
