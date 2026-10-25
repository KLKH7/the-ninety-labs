"""A pass or shot ends where the ball is when the next thing happens to it (data contract C7)."""

import math
from collections import defaultdict

from ninety.sim.engine import FPS, Engine
from ninety.validate import ON_BALL, check_events


def c7(m):
    problems = defaultdict(list)
    check_events(m.events, m.frames, FPS, {"score": m.score}, problems)
    return problems.get("C7 ball path", [])


def test_a_blocked_shot_poked_loose_ends_where_the_tackle_met_the_ball():
    # Seed 21, the demo window. Once its shot at 4:37 was blocked, the shooter got back to the ball and
    # a defender poked it loose at 4:39; the shot stayed open until someone controlled the ball, so its end
    # point lay beyond the tackle, where C7 says the ball never reached it. The off-ball movement of #179
    # changed how seed 21 plays, and a tackle on a kick still open is rare (none in about 480 minutes of
    # play on that engine), so the case is made at seed 21's own moment: at 4:37 a shot by the player on
    # the ball is still open, as if blocked back to him, and his nearest opponent pokes the ball; then the
    # match plays on.
    e = Engine(21)
    open_at_strike = []
    for name in ("shoot", "pass_to"):
        strike = getattr(e, name)

        def checked(*args, _strike=strike, **kwargs):
            if e.kicked is not None:  # a kick still open as a carrier strikes: nothing ended it
                open_at_strike.append((round(e.t, 2), e.kicked["id"]))
            return _strike(*args, **kwargs)

        setattr(e, name, checked)
    e.kickoff("home", setup=True)
    for _ in range(int(4.62 * 60 * FPS)):
        e.step()
    holder = e.by_id[e.possessor] if e.possessor else min(
        (q for q in e.players if q.role != "GK"), key=lambda q: math.hypot(q.x - e.ball[0], q.y - e.ball[1]))
    tackler = min((q for q in e.players if q.team != holder.team and q.role != "GK"),
                  key=lambda q: math.hypot(q.x - holder.x, q.y - holder.y))
    shot = e.kicked = e.emit("shot", holder.team, e.ball[0], e.ball[1], player=holder.id, ball_speed_kmh=58.8)
    e.shot_touched_by, e.shot_was_on_target = "defender", False
    e.possessor, e.dribbler = None, holder.id
    poked = []
    poke = e.poke

    def watched(p, held, _poke=poke):
        at = (round(e.ball[0], 2), round(e.ball[1], 2))  # where the tackle meets the ball
        poked.append((e.kicked is not None, at))
        _poke(p, held)
        poked.append((shot.get("end_x"), shot.get("end_y")))  # the shot as the tackle left it

    e.poke = watched
    e.poke(tackler, holder)
    for _ in range(int(0.5 * 60 * FPS)):
        e.step()
    m = e.match
    assert poked[0][0]  # the case is in the match (lesson 41): the tackle met the shot still open
    assert poked[1] == poked[0][1]  # and ended it there, at the tackle, not at a later touch
    on_ball = [ev for ev in m.events if ev["type"] in ON_BALL]
    nxt = on_ball[on_ball.index(shot) + 1]
    assert nxt["type"] == "tackle" and nxt["player"] == tackler.id  # nothing recorded between
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
    # An untouched shot going wide 5 m out, then a poke toward the goal: it missed, whatever the push.
    for seed in range(30):
        e, shot, holder, tackler = _open_shot_then_dribbler(seed)
        e.shot_touched_by, e.shot_was_on_target = None, None
        holder.x, holder.y, holder.vx, holder.vy = 5.6, 34.0, 0.0, 0.0
        e.ball = (5.0, 34.0, 0.0, 0.0, 12.0, 0.0)  # across the face of goal toward the touchline
        tackler.x, tackler.y, tackler.vx, tackler.vy = 6.5, 34.0, -7.0, 0.0  # lunging at the goal (x = 0)
        e.poke(tackler, holder)
        assert shot["outcome"] == "off_target", seed


def _open_pass(e):
    passer, mate = e.by_id["h6"], e.by_id["h7"]
    e.kicked = e.emit("pass", "home", 40.0, 30.0, player=passer.id, intended=mate.id, interceptor=None,
                      deflected_by=None)
    e.ball = (48.0, 33.0, 0.0, 0.0, 0.0, 0.0)
    return e.kicked, mate


def test_a_tackle_on_a_team_mate_who_only_touched_a_pass_ends_it_failed_where_the_ball_is():
    e = Engine(21)
    pas, mate = _open_pass(e)
    mate.x, mate.y, e.possessor, e.dribbler = 47.6, 33.0, None, mate.id  # his touch did not keep it
    e.poke(e.by_id["a6"], mate)
    assert (pas["end_x"], pas["end_y"], pas["outcome"]) == (48.0, 33.0, "fail") and e.kicked is None


def test_a_foul_or_an_offside_ends_the_pass_in_flight():
    e = Engine(21)
    pas, mate = _open_pass(e)
    e.foul(e.by_id["a6"], mate)  # the whistle stops a pass that had not arrived
    assert (pas["end_x"], pas["end_y"], pas["outcome"]) == (48.0, 33.0, "fail") and e.kicked is None
    e = Engine(21)
    pas, mate = _open_pass(e)
    e.offside_offence(mate, 52.0, 31.0)  # he played it from an offside position, there
    assert (pas["end_x"], pas["end_y"], pas["outcome"]) == (52.0, 31.0, "fail") and e.kicked is None
