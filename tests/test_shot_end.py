"""A pass or shot ends where the ball is when the next thing happens to it (data contract C7)."""

from collections import defaultdict

from ninety.sim.engine import FPS, Engine
from ninety.validate import ON_BALL, check_events


def c7(m):
    problems = defaultdict(list)
    check_events(m.events, m.frames, FPS, {"score": m.score}, problems)
    return problems.get("C7 ball path", [])


def test_a_blocked_shot_poked_loose_ends_where_the_tackle_met_the_ball():
    # Seed 21, the demo window: a10's shot at 4:37 is blocked, he gets back to the ball, and h4 pokes
    # it loose at 4:39. The shot once stayed open until h8 controlled the ball at 4:41, so its end
    # point lay beyond the tackle, where C7 says the ball never reached it.
    e = Engine(21)
    open_at_strike = []
    for name in ("shoot", "pass_to"):
        strike = getattr(e, name)

        def checked(*args, _strike=strike, **kwargs):
            if e.kicked is not None:  # a kick still open as a carrier strikes: nothing ended it
                open_at_strike.append((round(e.t, 2), e.kicked["id"]))
            return _strike(*args, **kwargs)

        setattr(e, name, checked)
    m = e.run(4.75)
    # The case is in the match (lesson 41): a shot whose next event on the ball is a tackle.
    on_ball = [ev for ev in m.events if ev["type"] in ON_BALL]
    pairs = zip(on_ball, on_ball[1:], strict=False)
    assert any(a["type"] == "shot" and b["type"] == "tackle" for a, b in pairs)
    assert c7(m) == []
    # Every kick ends at a touch, a tackle, a whistle or the ball going out before the next strike.
    assert open_at_strike == []


def _open_shot_then_dribbler(seed=21):
    """a10 shot from (26.5, 36.6); h4 blocked it (a defender touched it); a10 is back on the ball,
    dribbling it, as in seed 21."""
    e = Engine(seed)
    shooter, blocker = e.by_id["a10"], e.by_id["h4"]
    e.kicked = e.emit("shot", "away", 26.5, 36.6, player=shooter.id, ball_speed_kmh=58.8)
    e.shot_touched_by, e.shot_was_on_target = "defender", False
    shooter.x, shooter.y = 26.0, 33.4
    e.ball = (26.4, 33.5, 0.0, 0.0, 0.0, 0.0)
    e.possessor, e.dribbler = None, shooter.id
    return e, e.kicked, shooter, blocker


def test_a_tackle_on_the_ball_ends_the_shot_still_in_flight_where_the_ball_is():
    e, shot, holder, tackler = _open_shot_then_dribbler()
    e.poke(tackler, holder)
    assert (shot["end_x"], shot["end_y"]) == (26.4, 33.5) and shot["outcome"] == "blocked"
    assert e.kicked is None
    assert [ev["type"] for ev in e.match.events[-2:]] == ["shot", "tackle"]  # nothing recorded between


def test_a_shot_ended_by_a_tackle_is_judged_on_its_own_flight_not_the_tackles_push():
    # An untouched shot going wide, then a poke that may knock the ball goalward: it missed.
    for seed in range(30):
        e, shot, holder, tackler = _open_shot_then_dribbler(seed)
        e.shot_touched_by, e.shot_was_on_target = None, None
        e.ball = (26.4, 33.5, 0.0, -3.0, 12.0, 0.0)  # toward the touchline, away from the goal at x = 0
        tackler.x, tackler.y, tackler.vx, tackler.vy = 27.5, 33.5, -6.0, 0.0  # lunging goalward
        e.poke(tackler, holder)
        assert shot["outcome"] == "off_target", seed
