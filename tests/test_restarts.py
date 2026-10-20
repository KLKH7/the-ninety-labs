"""Restarts: the dead ball is fetched, never placed (defect sweep row 2); the kick-off after a goal
is walked back to, never reset (row 3); opponents keep the Laws' distance until the ball is in play
(row 5). Each defect test fails on the engine before this change (lesson 8)."""

import math

from ninety.sim import ball
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


def holding_a_dead_ball_away_from_the_spot() -> tuple[Engine, object]:
    """A home player, not the taker, has just taken the dead ball 20 m from the spot."""
    e = Engine(3)
    still(e)
    free_kick(e, "home", 40.0, 34.0)
    r = e.restart
    p = e.by_id["h7"]
    p.x, p.y, p.heading = 60.0, 34.0, math.pi  # facing the spot
    r.carried_by, r.gathered_at = p.id, e.t
    e.ball = (60.0 - 0.35, 34.0, 0.0, 0.0, 0.0, 0.0)  # at his feet, in front of him
    return e, p


def test_a_fetcher_settles_the_ball_before_he_knocks_it_on():
    """A4: he has it under control only after his first touch has settled it (settle_s)."""
    from ninety.sim.engine import settle_s
    e, p = holding_a_dead_ball_away_from_the_spot()
    e.tick_restart()
    assert e.restart.carried_by == p.id  # not struck in the frame he took it
    e.t += settle_s(p.profile["first_touch"])
    e.tick_restart()
    assert e.restart.carried_by is None and e.restart.passed_by == p.id
    assert e.ball[3] < -1.0  # on its way back toward the spot


def test_a_fetcher_faces_the_spot_before_he_knocks_it_on():
    """P16: a strike needs him facing within STRIKE_FACING of its line."""
    from ninety.sim.engine import settle_s
    e, p = holding_a_dead_ball_away_from_the_spot()
    p.heading = 0.0  # facing away from the spot, the ball behind him
    e.ball = (60.0 + 0.35, 34.0, 0.0, 0.0, 0.0, 0.0)
    e.t += settle_s(p.profile["first_touch"])
    e.tick_restart()
    assert e.restart.carried_by == p.id


def test_taking_a_rolling_dead_ball_gives_it_his_velocity():
    """The ball goes with him as a controlled ball does (P6), not dead still."""
    e = Engine(3)
    still(e)
    free_kick(e, "home", 40.0, 34.0)
    p = e.by_id["h9"]
    p.x, p.y, p.vx, p.vy = 40.0, 34.0, 3.0, 0.0
    e.ball = (40.3, 34.0, 0.0, 5.0, 0.0, 0.0)
    e.tick_restart()
    assert e.restart.carried_by == p.id and e.ball[3:5] == (3.0, 0.0)


def test_at_a_goal_kick_an_opponent_near_the_side_of_the_area_goes_out_wide():
    e = Engine(3)
    e.restart = Restart("goal_kick", "home", 5.5, 34.0, "h1", e.t + 5)
    tx, ty = e.keep_off(e.by_id["a9"], 5.0, 53.0)  # deep, a metre inside the side of the area
    assert tx == 5.0 and ty >= PITCH_Y / 2 + PENALTY_HALF_WIDTH + KEEP_OFF_MARGIN_M - 1e-9


def test_a_set_piece_offers_no_dribble():
    """Laws 8, 13, 16, 17: carrying a set ball off is touching it twice before anyone else has."""
    from ninety.sim import decisions
    e = Engine(3)
    e.possessor = "h9"
    scene = e.scene_for(e.by_id["h9"])
    assert any(o.kind == "dribble" for o in decisions.options(scene))  # open play: he may carry it
    scene.set_piece = True
    assert not any(o.kind == "dribble" for o in decisions.options(scene))


def set_free_kick_in_space(seed: int) -> tuple[Engine, object]:
    """A home free kick in midfield with nobody within 15 m of it: carrying it would tempt him."""
    e = Engine(seed)
    still(e)
    e.possessor = None
    e.stop("free_kick", "home", (50.0, 34.0))
    r = e.restart
    taker = e.by_id[r.taker]
    for p in e.players:
        if p is not taker and math.hypot(p.x - 50.0, p.y - 34.0) < 15.0:
            p.x = 50.0 - 16.0 if p.team == "home" else 50.0 + 16.0
    taker.x, taker.y = 49.64, 34.0
    r.carried_by = taker.id
    e.ball = (50.0, 34.0, 0.0, 0.0, 0.0, 0.0)
    r.ready_at = e.t
    return e, taker


def test_a_free_kick_is_played_away_with_its_first_touch():
    """Defect: the taker carried the set ball 2 to 17 m and then passed it (49 of 368 restarts on
    main). The set ball first moves when he passes or shoots it, from its spot."""
    for seed in (3, 4, 5, 6):
        e, taker = set_free_kick_in_space(seed)
        n = len(e.match.events)
        for _ in range(int(20 / DT)):
            e.step()
            if math.dist(e.ball[:2], (50.0, 34.0)) > 1e-6:  # it has moved: what moved it?
                struck = [ev for ev in e.match.events[n:] if ev["type"] in ("pass", "shot")]
                assert struck and struck[0]["player"] == taker.id, seed
                assert (struck[0]["x"], struck[0]["y"]) == (50.0, 34.0), seed
                break
        else:
            raise AssertionError("the free kick was never taken")


def test_the_restart_taker_does_not_play_it_again_before_another_player():
    """Defect: after a restart the taker could play the ball again before anyone else touched it."""
    e, taker = set_free_kick_in_space(3)
    e.restart = None
    e.possessor = taker.id
    e.from_restart = "free_kick"
    taker.heading = 0.0
    e.kick(taker, 2.5, 0.0, 0.0)  # a soft tap forward that stops about 2.5 m on
    taker.vx = 3.0  # and he runs on after it
    for p in e.players:  # nobody else near: only he could get to it
        if p is not taker and p.team == "away":
            p.x = max(p.x, 80.0)
    for _ in range(int(3 / DT)):
        e.step()
        assert e.possessor != taker.id
    assert e.possessor is None and e.restart_kicker == taker.id  # nobody else has touched it yet
    mate = next(p for p in e.players if p.team == "home" and p is not taker and p.role != "GK")
    mate.x, mate.y = e.ball[0] + 0.3, e.ball[1]
    for _ in range(int(2 / DT)):
        e.step()
        if e.possessor == mate.id:
            break
    assert e.possessor == mate.id and e.restart_kicker is None  # another player has touched it


def test_the_taker_steps_round_a_set_ball_never_through_it():
    """Law 13: the set ball stays still while he gets to the side of it he will strike it from."""
    from ninety.sim import shape
    e, taker = set_free_kick_in_space(3)
    for _ in range(3):
        e.step()
    assert e.set_by is not None and e.possessor == taker.id
    struck = []
    e.windup = (30.0, 34.0, lambda: struck.append((taker.x, taker.y)))  # to play it back, behind him
    e.hold_until = e.t + 99.0
    for _ in range(int(5 / DT)):
        e.moved = None
        e.tick_carrier()
        if struck:
            break
        e.move_players()
        assert e.ball == (50.0, 34.0, 0.0, 0.0, 0.0, 0.0)  # still, and reported still
        assert shape.clearance(e.ball[0], e.ball[1], taker.x, taker.y, taker.heading) >= ball.RADIUS
        e.t += DT
        e.frame += 1
    assert struck and struck[0][0] > 50.0  # struck from the far side of the ball from the target


def test_a_taker_still_walking_in_does_not_take_the_restart():
    e, taker = set_free_kick_in_space(3)
    taker.vx = 1.0  # walking onto the ball
    e.tick_restart()
    assert e.restart is not None
    taker.vx = 0.0
    e.tick_restart()
    assert e.restart is None


def kicked_restart() -> tuple[Engine, object]:
    e, taker = set_free_kick_in_space(3)
    e.restart = None
    e.possessor = taker.id
    e.from_restart = "free_kick"
    taker.heading = 0.0
    e.kick(taker, 6.0, 0.0, 0.0)
    return e, taker


def test_a_deflection_off_an_opponent_frees_the_restart_taker():
    """Any other player's touch counts, an opponent's deflection too, not only winning the ball."""
    e, taker = kicked_restart()
    assert e.restart_kicker == taker.id
    e.touched(e.by_id["a7"], 52.0, 34.0, controls=False)
    assert e.restart_kicker is None


def test_the_restart_taker_does_not_chase_it_even_after_it_comes_off_himself():
    """It came back off his own body: that is no other player's touch, so he still may not play it."""
    e, taker = kicked_restart()
    e.touched(taker, 50.5, 34.0, controls=False)  # it hits him (accidental)
    assert e.touched_since_kick and e.restart_kicker == taker.id
    e.ball = (50.6, 34.0, 0.0, 0.5, 0.0, 0.0)  # trickling at his feet, nobody else near
    e.t += 1.0  # everyone has reacted
    e.plan_chase()
    assert e.chase.get("home", (None,))[0] != taker.id


def test_a_set_ball_beside_him_is_not_struck_through_his_own_body():
    """Defect: a set ball at his shoulder was struck along his body and came straight back off him."""
    e, taker = set_free_kick_in_space(3)
    for _ in range(3):
        e.step()
    assert e.set_by is not None and e.possessor == taker.id
    taker.heading = math.radians(83)  # as in seed 7 at 3:14
    taker.x, taker.y = 50.34, 33.9  # the ball against his right shoulder
    assert not e.can_strike(taker, 51.34, 42.31)  # its way out runs across his shoulder
    taker.heading = math.atan2(8.31, 1.34)
    taker.x, taker.y = 50.0 - 1.34 / 8.42 * 0.4, 34.0 - 8.31 / 8.42 * 0.4  # behind it, facing the kick
    assert e.can_strike(taker, 51.34, 42.31)


def test_a_fetcher_near_the_boards_runs_no_faster_than_he_can_stop_before_them():
    """Defect: a fetcher ran at full pace at a ball against the boards and hit them."""
    from ninety.sim.body import stopping_speed
    e = Engine(3)
    still(e)
    free_kick(e, "home", 40.0, 0.5)
    e.ball = (43.0, -4.0, 0.0, 0.0, 0.0, 0.0)  # against the boards
    p = e.by_id["h2"]
    p.x, p.y = 45.0, -3.0  # a metre from them
    e.restart.fetcher = p.id
    p.vx, p.vy = 0.0, -5.0  # running at the boards
    _, _, speed = e.shape_target(p)
    assert speed <= stopping_speed(1.0) + 1e-9
    p.x, p.y, p.vx, p.vy = 60.0, -3.0, -5.0, 0.0  # running along them toward the ball
    _, _, speed = e.shape_target(p)
    assert speed > stopping_speed(1.0) + 1.0  # not slowed by boards he is not running at


def test_clear_of_his_body_a_strike_he_may_make_never_runs_into_him():
    """The premise of the set-ball strike rule (engine.can_strike): over a grid of ball positions
    and kick directions, a ball a full radius clear of his body that P16 lets him strike never meets
    his body (P11) within a metre of its way out."""
    from ninety.sim import decisions, shape
    for i in range(-12, 13):
        for j in range(-12, 13):
            ox, oy = i * 0.05, j * 0.05
            if shape.clearance(ox, oy, 0.0, 0.0, math.pi / 2) < ball.RADIUS:
                continue
            for deg in range(0, 360, 5):
                dx, dy = math.cos(math.radians(deg)), math.sin(math.radians(deg))
                if decisions.can_strike(ox, oy, math.pi / 2, dx, dy):
                    hit = shape.first_contact(ox, oy, ox + dx, oy + dy, 0.0, 0.0, math.pi / 2, ball.RADIUS)
                    assert hit is None, (ox, oy, deg)


def test_the_taker_waits_a_balls_width_clear_of_the_set_ball():
    from ninety.sim.engine import SET_BALL_CLEAR_M
    e, taker = set_free_kick_in_space(3)
    tx, ty, _ = e.shape_target(taker)
    assert abs(math.hypot(tx - 50.0, ty - 34.0) - SET_BALL_CLEAR_M) < 1e-9


def test_the_restart_taker_does_not_take_it_on_his_chest_either():
    """The bar covers every deliberate touch: a ball arriving into his body at chest height."""
    e, taker = kicked_restart()
    e.possessor = None
    taker.x, taker.y, taker.vx, taker.vy, taker.heading = 60.0, 34.0, 0.0, 0.0, math.pi
    e.ball = (58.5, 34.0, 1.3, 4.0, 0.0, 0.0)  # coming at his chest
    e.kicked_at = e.t - 2.0  # he has long reacted
    e.kicker_clear = True
    for _ in range(int(1 / DT)):
        e.tick_free()
        e.t += DT
        e.frame += 1
        assert e.possessor != taker.id
