"""A pass or shot ends where the ball is when the next thing happens to it (data contract C7)."""

from collections import defaultdict

from ninety.sim.engine import FPS, Engine, simulate
from ninety.validate import check_events


def c7(m):
    problems = defaultdict(list)
    check_events(m.events, m.frames, FPS, {"score": m.score}, problems)
    return problems.get("C7 ball path", [])


def test_a_blocked_shot_poked_loose_ends_where_the_tackle_met_the_ball():
    # Seed 21, the demo window: a10's shot at 4:37 is blocked, he gets back to the ball, and h4 pokes
    # it loose at 4:39. The shot once stayed open until h8 controlled the ball at 4:41, so its end
    # point lay beyond the tackle, where C7 says the ball never reached it.
    m = simulate(21, 4.75)
    assert c7(m) == []


def _open_shot_then_holder():
    """a10 shot from (26.5, 36.6); h4 blocked it (a defender touched it), a10 holds the ball again."""
    e = Engine(21)
    shooter, blocker = e.by_id["a10"], e.by_id["h4"]
    e.kicked = e.emit("shot", "away", 26.5, 36.6, player=shooter.id, ball_speed_kmh=58.8)
    e.shot_touched_by, e.shot_was_on_target = "defender", False
    shooter.x, shooter.y = 26.0, 33.4
    e.ball = (26.4, 33.5, 0.0, 0.0, 0.0, 0.0)
    e.possessor = shooter.id
    return e, e.kicked, shooter, blocker


def test_a_tackle_on_the_ball_ends_the_shot_still_in_flight_where_the_ball_is():
    e, shot, holder, tackler = _open_shot_then_holder()
    e.poke(tackler, holder)
    assert (shot["end_x"], shot["end_y"]) == (26.4, 33.5) and shot["outcome"] == "blocked"
    assert e.kicked is None
    tackle = e.match.events[-1]
    assert tackle["type"] == "tackle" and tackle["t"] >= shot["t"]


def test_a_new_strike_ends_the_pass_still_in_flight_where_the_ball_is():
    e = Engine(21)
    passer, mate = e.by_id["h6"], e.by_id["h7"]
    old = e.emit("pass", "home", 40.0, 30.0, player=passer.id, intended=mate.id, interceptor=None,
                 deflected_by=None)
    e.kicked = old
    mate.x, mate.y = 50.0, 34.0
    e.ball = (50.4, 34.0, 0.0, 0.0, 0.0, 0.0)
    e.give(mate.id)
    e.kicked = old  # a team-mate's touch that did not keep it: still in flight when he strikes it
    e.pass_to(mate, 70.0, 34.0, lofted=False)
    assert (old["end_x"], old["end_y"]) == (50.4, 34.0) and old["outcome"] == "fail"
    assert e.kicked is not old and e.kicked["type"] == "pass"
