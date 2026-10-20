"""Restarts: the dead ball is fetched, never placed (defect sweep row 2); the kick-off after a goal
is walked back to, never reset (row 3); opponents keep the Laws' distance until the ball is in play
(row 5). Each defect test fails on the engine before this change (lesson 8)."""

import math

from ninety.sim.decisions import PENALTY_DEPTH, PENALTY_HALF_WIDTH
from ninety.sim.engine import (
    BALL_TO_FEET,
    DT,
    KEEP_OFF_MARGIN_M,
    PITCH_X,
    PITCH_Y,
    Engine,
    Restart,
    segment_distance,
    throw_stand,
)
from ninety.validate import MAX_BALL_MPS, MAX_PLAYER_MPS

# The fastest a ball may travel (the validator's P3); a jump of more than this in a frame is a teleport.
MAX_STEP_M = MAX_BALL_MPS * DT


def still(e: Engine) -> None:
    for p in e.players:
        p.vx = p.vy = 0.0


def state(e: Engine) -> tuple:
    return e.ball[:3], {p.id: (p.x, p.y) for p in e.players}


def run_until(e: Engine, done, seconds: float, before: tuple | None = None) -> list[tuple]:
    """Step the engine until done(e), recording the ball and every player each frame, from
    `before` (the state before the restart was given) if there is one."""
    track = ([before] if before else []) + [state(e)]
    for _ in range(int(seconds / DT)):
        e.step()
        track.append(state(e))
        if done(e):
            return track
    raise AssertionError("the restart was never taken")


def taken(e: Engine) -> bool:
    return e.restart is None


def biggest_ball_step(track: list[tuple]) -> float:
    return max(math.dist(a[0], b[0]) for a, b in zip(track, track[1:], strict=False))


def fastest_player(track: list[tuple]) -> float:
    return max(math.dist(a[1][pid], b[1][pid]) / DT
               for a, b in zip(track, track[1:], strict=False) for pid in a[1])


def test_a_dead_ball_that_rolled_away_is_fetched_to_the_spot_not_teleported():
    """Defect: after the whistle the ball rolled on and appeared at the taker's feet. Here the taker
    starts 25 m from the spot and the ball rolls away from both, so it must really be fetched."""
    e = Engine(1)
    still(e)
    e.possessor = None
    taker = e.by_id["h9"]
    taker.x, taker.y = 40.0, 9.0
    for p in e.players:  # nobody near the spot or the ball's path
        if p.team == "home" and p is not taker and 30.0 < p.x < 75.0 and 24.0 < p.y < 44.0:
            p.y = 50.0
    e.ball = (40.0, 34.0, 0.0, 8.0, 0.0, 0.0)  # rolling on toward x = 65 after the whistle
    e.stop("free_kick", "home", (40.0, 34.0), taker=taker.id)
    e.restart.ready_at = e.t  # waits are R1's business; this is about the ball
    track = run_until(e, taken, 90)
    assert len(track) > 5 / DT  # it took a real fetch, not a placement
    assert biggest_ball_step(track) <= MAX_STEP_M
    # carried onto the spot at a carried ball's pace (P6), never put there
    assert math.dist(track[-2][0], (40.0, 34.0, 0.0)) <= BALL_TO_FEET * DT + 1e-9
    set_piece = next(ev for ev in reversed(e.match.events) if ev["type"] == "set_piece")
    assert (set_piece["x"], set_piece["y"]) == (40.0, 34.0)  # Law 13: where it happened


def test_a_carried_dead_ball_moves_no_faster_than_a_carried_ball_settles():
    """P6: the ball goes to his feet at up to BALL_TO_FEET, never in one jump."""
    e = Engine(1)
    still(e)
    e.possessor = None
    e.stop("free_kick", "home", (40.0, 34.0))
    r = e.restart
    carrier = e.by_id[r.taker]
    carrier.x, carrier.y, carrier.heading = 30.0, 34.0, 0.0
    r.carried_by = carrier.id
    e.ball = (30.0, 34.95, 0.0, 0.0, 0.0, 0.0)  # within his reach, beside him
    e.tick_restart()
    moved = math.dist(e.ball[:2], (30.0, 34.95))
    assert 0.0 < moved <= BALL_TO_FEET * DT + 1e-9


def test_a_ball_at_the_boards_is_fetched_for_the_throw_in_not_teleported():
    """Defect: a ball out of play at the boards hopped to the thrower's hands."""
    e = Engine(1)
    still(e)
    e.possessor = None
    e.ball = (62.0, -4.0, 0.0, 0.0, 0.0, 0.0)  # against the boards, 12 m along from where it went out
    e.stop("throw_in", "home", (50.0, 0.0))
    e.restart.ready_at = e.t
    track = run_until(e, taken, 60)
    assert biggest_ball_step(track) <= MAX_STEP_M
    assert e.throw_by is not None
    for _ in range(25):  # he lifts it into both hands over his head (Law 15), then throws
        before = e.ball[:3]
        e.step()
        assert math.dist(before, e.ball[:3]) <= MAX_STEP_M
        if e.ball[2] > 1.5:
            break
    assert e.ball[2] > 1.5


def test_only_the_restarting_side_takes_the_dead_ball():
    e = Engine(1)
    still(e)
    e.possessor = None
    opp = e.by_id["a6"]
    opp.x, opp.y = 30.5, 34.0  # an opponent stands on the dead ball
    e.ball = (30.0, 34.0, 0.0, 0.0, 0.0, 0.0)
    e.stop("free_kick", "home", (30.0, 34.0))
    e.tick_restart()
    assert e.restart.carried_by != opp.id
    assert e.restart.fetcher is not None and e.by_id[e.restart.fetcher].team == "home"


def test_after_a_goal_the_players_walk_back_and_nobody_is_reset():
    """Defect: at a goal all 22 players and the ball jumped to their kick-off spots in one frame."""
    e = Engine(2)
    e.run(1)  # a minute of play: everyone somewhere
    e.possessor, e.restart, e.throw_by = None, None, None
    e.ball = (106.0, 34.0, 0.5, 2.0, 0.0, 0.0)  # in the net
    before = state(e)
    e.kickoff("away")  # the away side conceded
    track = run_until(e, taken, 120, before)
    assert biggest_ball_step(track) <= MAX_STEP_M
    assert fastest_player(track) <= MAX_PLAYER_MPS
    kick = e.match.events[-1]
    assert kick["type"] == "kickoff" and (kick["x"], kick["y"]) == (PITCH_X / 2, PITCH_Y / 2)
    # Law 8 holds until the ball is kicked and moves, including while the kicker stands over it.
    for _ in range(int(5 / DT)):
        for p in e.players:
            if p.id == kick["player"]:
                continue
            own_half = p.x >= PITCH_X / 2 if p.team == "away" else p.x <= PITCH_X / 2
            assert own_half, p.id
            if p.team == "home":
                assert math.hypot(p.x - PITCH_X / 2, p.y - PITCH_Y / 2) >= 9.15, p.id
        e.step()
        if math.dist(e.ball[:2], (PITCH_X / 2, PITCH_Y / 2)) > 1e-6:
            break
    else:
        raise AssertionError("the kick-off was never kicked")


def test_the_kickoff_waits_for_the_teams_to_line_up():
    """Law 8: not taken while a player is still in the wrong half, however long the pause."""
    e = Engine(2)
    e.kickoff("home", setup=True)
    late = e.by_id["a9"]
    late.x, late.y = 30.0, 34.0  # an away player still deep in the home half
    e.restart.ready_at = e.t
    for _ in range(3):
        e.tick_restart()
    assert e.restart is not None
    late.x = 70.0
    for _ in range(3):
        if e.restart:
            e.tick_restart()
    assert e.restart is None


def opponents(e: Engine, team: str) -> list:
    return [p for p in e.players if p.team != team]


def take_with_opponents_close(kind: str, spot: tuple[float, float], close: list[tuple[str, float, float]],
                              taker_side: str = "home") -> tuple[Engine, dict]:
    """A restart about to be taken, the ball already on its spot with the taker, and opponents placed
    where they should not be. Returns the engine and everyone's position in the frame the ball
    first moves (it is in play: Laws 13, 15 to 17)."""
    e = Engine(3)
    still(e)
    e.possessor = None
    e.stop(kind, taker_side, spot)
    r = e.restart
    taker = e.by_id[r.taker]
    if kind == "throw_in":
        taker.x, taker.y = throw_stand(*spot)
    else:
        taker.x, taker.y = spot[0] - (0.3 if taker_side == "home" else -0.3), spot[1]
    e.ball = (*spot, 0.0, 0.0, 0.0, 0.0)
    for pid, x, y in close:
        e.by_id[pid].x, e.by_id[pid].y = x, y
    r.ready_at = e.t + 3.0  # three seconds to get out of the way
    placed = None
    for _ in range(int(30 / DT)):
        e.step()
        if placed is None and e.restart is None:
            placed = e.ball[:2]
        if placed is not None and math.dist(e.ball[:2], placed) > 1e-6:
            return e, {p.id: (p.x, p.y) for p in e.players}
    raise AssertionError("the restart was never kicked")


def test_opponents_keep_9_15_m_from_a_free_kick_until_it_is_kicked():
    """Defect: opponents stood 1 to 6 m from a free kick and closed in during the taker's touch."""
    e, at = take_with_opponents_close("free_kick", (60.0, 34.0), [("a7", 62.0, 34.0), ("a8", 58.0, 37.0)])
    for p in opponents(e, "home"):
        assert math.dist(at[p.id], (60.0, 34.0)) >= 9.15, p.id


def test_opponents_keep_out_of_the_penalty_area_at_a_goal_kick_until_it_is_kicked():
    """Defect: at a goal kick only two pressers were kept 12 m away; others stood in the six-yard box."""
    e, at = take_with_opponents_close("goal_kick", (5.5, 34.0), [("a9", 4.0, 30.0), ("a10", 12.0, 40.0)])
    for p in opponents(e, "home"):
        x, y = at[p.id]
        assert x > PENALTY_DEPTH or abs(y - PITCH_Y / 2) > PENALTY_HALF_WIDTH, p.id


def test_team_mates_may_stay_in_the_area_at_their_own_goal_kick():
    """Law 16 keeps out only the opponents: a defender of the kicking side is not pushed out."""
    e = Engine(3)
    e.restart = Restart("goal_kick", "home", 5.5, 34.0, "h1", e.t + 5)
    mate = e.by_id["h3"]
    assert e.keep_off(mate, 10.0, 30.0) == (10.0, 30.0)
    assert e.keep_off(e.by_id["a9"], 10.0, 30.0) != (10.0, 30.0)


def test_opponents_keep_2_m_from_a_throw_in_until_it_is_thrown():
    e, at = take_with_opponents_close("throw_in", (50.0, 0.0), [("a5", 50.5, 0.8)])
    for p in opponents(e, "home"):
        assert math.dist(at[p.id], (50.0, 0.0)) >= 2.0, p.id


def test_nobody_challenges_a_set_ball_before_it_is_kicked():
    """Defect: the set ball was in play from the moment the taker had it, so a defender could tackle
    him during his 0.5 to 1.5 s over it. 17 m from goal, where a defender commits without cover."""
    e = Engine(3)
    still(e)
    e.possessor = None
    e.stop("free_kick", "home", (88.0, 34.0))
    r = e.restart
    taker = e.by_id[r.taker]
    taker.x, taker.y = 87.7, 34.0
    e.ball = (88.0, 34.0, 0.0, 0.0, 0.0, 0.0)
    r.ready_at = e.t
    e.step()
    e.step()
    assert e.restart is None and e.possessor == taker.id
    e.hold_until = e.t + 10.0  # he takes his time over it
    d = e.by_id["a4"]
    d.x, d.y = 89.0, 34.0  # right on him, but the ball is not in play
    for _ in range(25):
        e.duels()
        e.frame += 1
    assert d.id not in e.lunges


def free_kick(e: Engine, team: str, x: float, y: float) -> None:
    e.possessor = None
    e.restart = Restart("free_kick", team, x, y, "h9" if team == "home" else "a9", e.t + 5)


def test_at_a_corner_opponents_keep_9_15_m_from_the_arc_not_the_ball():
    """Law 17: from the corner arc (1 m radius, Law 1), so 10.15 m from the corner itself."""
    e = Engine(3)
    e.restart = Restart("corner", "home", PITCH_X, 0.0, "h11", e.t + 5)
    d = e.by_id["a4"]
    d.x, d.y = PITCH_X - 7.0, 6.5  # 9.55 m from the corner, 9.5 m from the ball on its spot
    tx, ty = e.keep_off(d, PITCH_X - 7.0, 6.5)
    assert math.hypot(tx - PITCH_X, ty) >= 9.15 + 1.0


def test_an_opponent_goes_round_the_free_kick_circle_not_across_it():
    e = Engine(3)
    free_kick(e, "home", 60.0, 34.0)
    d = e.by_id["a7"]
    d.x, d.y = 60.0, 45.0  # outside, on one side; his target is straight across, on the other
    tx, ty = e.keep_off(d, 60.0, 23.0)
    clear = 9.15 + KEEP_OFF_MARGIN_M
    # aimed along the circle: the chord to it dips inside by under 4% of the radius
    assert segment_distance(60.0, 34.0, d.x, d.y, tx, ty) >= clear * math.cos(math.radians(15)) - 1e-9


def test_at_a_goal_kick_an_opponents_target_is_moved_clear_of_the_area():
    e = Engine(3)
    e.restart = Restart("goal_kick", "home", 5.5, 34.0, "h1", e.t + 5)
    tx, ty = e.keep_off(e.by_id["a9"], 10.0, 34.0)
    assert tx >= PENALTY_DEPTH + KEEP_OFF_MARGIN_M - 1e-9 and ty == 34.0  # out the short way, up the pitch


def test_a_throw_ins_2_m_is_measured_from_the_point_on_the_touchline():
    """Law 15: the point where it is taken, on the line, not a spot inside the pitch."""
    e = Engine(3)
    e.restart = Restart("throw_in", "home", 50.0, 0.0, "h2", e.t + 5)
    tx, ty = e.keep_off(e.by_id["a5"], 50.0, 2.2)
    assert abs(math.hypot(tx - 50.0, ty) - (2.0 + KEEP_OFF_MARGIN_M)) < 1e-9


def test_a_free_kick_in_the_kicking_sides_own_area_keeps_opponents_out_of_the_area():
    """Law 13: at a free kick from inside its own penalty area, opponents stay outside the area."""
    e = Engine(3)
    free_kick(e, "home", 10.0, 34.0)
    tx, ty = e.keep_off(e.by_id["a10"], 14.0, 50.0)  # 16.5 m from the ball, inside the area
    assert tx > PENALTY_DEPTH or abs(ty - PITCH_Y / 2) > PENALTY_HALF_WIDTH


def test_a_dead_ball_still_dropping_is_left_to_land():
    e = Engine(3)
    still(e)
    free_kick(e, "home", 40.0, 34.0)
    p = e.by_id["h9"]
    p.x, p.y = 40.0, 34.0
    e.ball = (40.3, 34.0, 0.6, 0.0, 0.0, -2.0)  # beside him, falling
    e.tick_restart()
    assert e.restart.carried_by is None
    e.ball = (40.3, 34.0, 0.0, 0.0, 0.0, 0.0)  # on the ground: now he takes it
    e.tick_restart()
    assert e.restart.carried_by == p.id


def test_a_dead_ball_faster_than_his_first_touch_kills_runs_on():
    """A4: his foot kills at most absorb_mps of the ball's speed relative to him."""
    e = Engine(3)
    still(e)
    free_kick(e, "home", 40.0, 34.0)
    p = e.by_id["h9"]
    p.x, p.y = 40.0, 34.0
    fast = p.profile.absorb_mps(False) + 1.0
    e.ball = (40.3, 34.0, 0.0, fast, 0.0, 0.0)
    e.tick_restart()
    assert e.restart.carried_by is None
    e.ball = (40.3, 34.0, 0.0, fast - 2.0, 0.0, 0.0)
    e.tick_restart()
    assert e.restart.carried_by == p.id


def test_the_fetcher_goes_where_the_ball_will_stop_and_is_replanned():
    e = Engine(3)
    still(e)
    free_kick(e, "home", 40.0, 45.0)
    e.ball = (40.0, 45.0, 0.0, 10.0, 0.0, 0.0)  # rolling on along the pitch, past everyone
    e.tick_restart()
    first = e.by_id[e.restart.fetcher]
    tx, _, _ = e.shape_target(first)
    assert tx > e.ball[0] + 10.0  # ahead, where it will come to rest, not where it is
    first.x, first.y = 1.0, 1.0  # he is far away now: somebody nearer goes instead
    for _ in range(8):
        e.tick_restart()
    assert e.restart.fetcher != first.id


def test_a_set_ball_touched_on_is_in_play_and_the_opponents_may_close():
    """Laws 13, 16, 17: in play once it is kicked and moves, by any touch, not only a pass."""
    e = Engine(3)
    still(e)
    e.possessor = None
    e.stop("free_kick", "home", (60.0, 34.0))
    r = e.restart
    taker = e.by_id[r.taker]
    taker.x, taker.y = 59.7, 34.0
    r.carried_by = taker.id
    e.ball = (60.0, 34.0, 0.0, 0.0, 0.0, 0.0)
    r.ready_at = e.t
    e.step()
    assert e.restart is None and e.set_by is not None
    e.ball = (60.3, 34.0, 0.0, 1.0, 0.0, 0.0)  # he touches it on
    e.step()
    assert e.set_by is None
    assert e.keep_off(e.by_id["a7"], 61.0, 34.0) == (61.0, 34.0)
