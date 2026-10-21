"""T3: the presser and the cover keep their jobs while the press is on the same carrier or the same kick,
so the cover has time to reach his place goal-side of the ball."""

from ninety.sim.engine import BRAIN_EVERY, Engine


def _away_on_the_ball():
    """The away team has the ball at halfway; the home team presses (every home player accepts)."""
    e = Engine(1)
    e.give("a6")
    carrier = e.by_id["a6"]
    carrier.x, carrier.y, carrier.vx, carrier.vy = 52.5, 34.0, 0.0, 0.0
    e.ball = (52.9, 34.0, 0.0, 0.0, 0.0, 0.0)
    e.accepts_press = lambda p: True
    return e, carrier


def _home_look(e):
    """Run the engine's own perception step on a frame where the home brain reads the game."""
    e.frame = BRAIN_EVERY * (e.frame // BRAIN_EVERY + 1)  # the home brain looks on multiples of BRAIN_EVERY
    e.perceive_and_think()
    return list(e.brains["home"].pressers)


def _place(e, near, far):
    """Two home midfielders nearest the ball, `near` the nearer; everyone else far away."""
    for q in e.players:
        if q.team == "home" and q.role != "GK":
            q.x, q.y, q.vx, q.vy = 20.0, 5.0 + 4.0 * int(q.id[1:]), 0.0, 0.0
    e.by_id[near].x, e.by_id[near].y = 48.5, 34.0  # 4.4 m from the ball
    e.by_id[far].x, e.by_id[far].y = 46.5, 34.0  # 6.4 m


def test_the_presser_and_cover_keep_their_jobs_while_the_carrier_keeps_the_ball():
    """Fails before the hold: the brain named them afresh at every look, so two players about as near
    swapped the jobs and the cover never reached his place (median 0.5 s in the job at a long shot)."""
    e, _ = _away_on_the_ball()
    _place(e, "h7", "h8")
    first = _home_look(e)
    assert first[:2] == ["h7", "h8"]
    _place(e, "h8", "h7")  # now h8 is the step nearer: the same carrier still has the ball
    assert _home_look(e) == first
    assert _home_look(e) == first


def test_a_new_carrier_or_a_new_kick_has_the_jobs_named_again():
    e, _ = _away_on_the_ball()
    _place(e, "h7", "h8")
    first = _home_look(e)
    _place(e, "h8", "h7")
    e.give("a7")  # the ball changes feet
    e.ball = (52.9, 34.0, 0.0, 0.0, 0.0, 0.0)
    assert _home_look(e)[:2] == ["h8", "h7"] != first[:2]


def test_a_presser_who_will_not_press_or_a_player_beaten_is_replaced():
    e, _ = _away_on_the_ball()
    _place(e, "h7", "h8")
    assert _home_look(e)[:2] == ["h7", "h8"]
    e.accepts_press = lambda p: p.id != "h7"  # he no longer thinks pressing is worth it (P17)
    assert _home_look(e)[0] == "h8"
    e.accepts_press = lambda p: True
    _place(e, "h7", "h8")
    e.give("a7")
    assert _home_look(e)[:2] == ["h7", "h8"]
    e.off_balance["h8"] = e.t + 2.0  # the cover is beaten: down, out of the play
    after = _home_look(e)
    assert after[0] == "h7" and "h8" not in after  # the next man up covers


def test_the_cover_is_whoever_reaches_the_cover_s_place_soonest():
    """Fails before the screening fix: the second soonest to the ball covered, here h8 from beyond the
    ball, while h6 stood almost on the cover's place, between the ball and our goal."""
    e, _ = _away_on_the_ball()
    for q in e.players:
        if q.team == "home" and q.role != "GK":
            q.x, q.y, q.vx, q.vy = 90.0, 5.0 + 4.0 * int(q.id[1:]), 0.0, 0.0
    e.by_id["h7"].x, e.by_id["h7"].y = 50.0, 34.0  # nearest the ball: he presses
    e.by_id["h8"].x, e.by_id["h8"].y = 58.0, 34.0  # beyond the ball, second nearest to it
    e.by_id["h6"].x, e.by_id["h6"].y = 44.0, 34.0  # goal-side, by the cover's place (8 m behind the ball)
    pressers = _home_look(e)
    assert pressers[0] == "h7" and pressers[1] == "h6"
    cx, cy = e.cover_spot("home", e.ball[0], e.ball[1], e.brains["home"].press_gap_m)
    assert abs(cx - 44.9) < 0.6 and abs(cy - 34.0) < 0.6  # 8 m from the ball toward our goal
