"""Corners (lesson 202): the taker runs up to the ball, the attackers make their runs as he does, and
the defending side guards its near post. Each defect test fails on the engine before this change
(lesson 8): there the taker stood over the ball and struck it from a standstill, the box stood still
through the wait and the delivery, and nobody stood in the near-post area unless he marked a man
there."""

import math

import pytest

from ninety.sim import offball
from ninety.sim.engine import (
    DT,
    GOAL_HALF_WIDTH,
    PITCH_X,
    PITCH_Y,
    RUNUP_M,
    Engine,
)

AREA_DEPTH_M, AREA_HALF_WIDTH_M = 16.5, 20.16  # Law 1: the penalty area
CASES = [(seed, team, flag) for seed in (2, 3, 5, 7) for team, flag in (("home", 0.0), ("away", PITCH_Y))]


def corner(seed: int, team: str, flag_y: float) -> Engine:
    """A minute of play, then a corner to `team` from the flag on `flag_y`'s touchline, the ball just
    over the goal line there. The whistle ends what was in play, as it does for a foul: the ball in
    flight, the chase, any lunge."""
    e = Engine(seed)
    e.run(1)
    e.possessor, e.restart, e.set_by, e.throw_by, e.dribbler = None, None, None, None, None
    e.celebration = None
    e.kicked, e.dribble_to, e.windup, e.chase = None, None, None, {}
    e.lunges.clear(), e.lunge_at.clear(), e.evade_at.clear()
    line = goal_line(team)
    e.ball = (line + (1.5 if line > PITCH_X / 2 else -1.5), flag_y, 0.0, 0.0, 0.0, 0.0)
    e.stop("corner", team, (line, flag_y))
    return e


def goal_line(team: str) -> float:
    """The goal line `team` attacks (one long half, L3)."""
    return PITCH_X if team == "home" else 0.0


def frame(e: Engine) -> dict:
    return {"t": e.t, "players": {p.id: (p.x, p.y, p.vx, p.vy) for p in e.players},
            "run_in": e.restart.run_in_at if e.restart else None, "set": e.restart is None}


def kick(e: Engine) -> list[dict]:
    """Run the corner until it is kicked; every frame on the way."""
    n = len(e.match.events)
    track = []
    for _ in range(int(80 / DT)):
        e.step()
        track.append(frame(e))
        if any(ev["type"] in ("pass", "shot") for ev in e.match.events[n:]):
            return track
    raise AssertionError("the corner was never kicked")


def in_area(e: Engine, team: str, line: float) -> int:
    """How many of `team`'s outfielders stand in the penalty area at the goal on `line`."""
    return sum(1 for p in e.players if p.team == team and p.role != "GK"
               and abs(p.x - line) <= AREA_DEPTH_M and abs(p.y - PITCH_Y / 2) <= AREA_HALF_WIDTH_M)


@pytest.mark.parametrize(("seed", "team", "flag"), CASES)
def test_the_corner_taker_runs_up_to_the_ball_and_strikes_it_as_he_gets_there(seed, team, flag):
    """Defect: he stood over the set ball and struck it from a standstill. He waits RUNUP_M back from
    it, stopped; then runs in, at a run-up's pace (faster than a walk), and the kick comes as he
    arrives, with no pause over the ball."""
    e = corner(seed, team, flag)
    taker = e.restart.taker
    track = kick(e)
    sx, sy = track[-1]["players"][taker][:2]
    start = next(i for i, f in enumerate(track) if f["run_in"] is not None)
    rx, ry = track[start]["players"][taker][:2]
    bx, by = e.kicked["x"], e.kicked["y"]
    assert math.hypot(rx - bx, ry - by) == pytest.approx(RUNUP_M, abs=0.15)
    assert math.hypot(sx - bx, sy - by) < 1.0  # at the ball when he strikes it
    fastest = max(math.hypot(f["players"][taker][2], f["players"][taker][3]) for f in track[start:])
    assert fastest > 2.0  # ran in, faster than a walk (L4: about 1.36 m/s)
    assert (len(track) - start) * DT < 3.0  # and struck it off his run-up, not after standing over it


@pytest.mark.parametrize(("seed", "team", "flag"), CASES)
def test_the_box_runners_wait_off_goal_then_run_in_as_the_taker_runs_up(seed, team, flag):
    """Defect: the striker and the far winger stood at the near and far post through the whole wait,
    and the box stood still for the delivery. They wait no nearer the goal line than the penalty mark
    (BOX_RUN_START_M), and as the taker runs up they run in toward the posts."""
    e = corner(seed, team, flag)
    track = kick(e)
    line = goal_line(team)
    start = next(i for i, f in enumerate(track) if f["run_in"] is not None)
    # the striker and the far-side winger make the post runs (O6, offball.BOX_RUNS); not the taker
    ball_side = 1.0 if flag > PITCH_Y / 2 else -1.0
    across = 1.0 if team == "home" else -1.0
    far = "RW" if ball_side * across > 0 else "LW"
    runners = [p.id for p in e.players if p.team == team and p.role in ("ST", far)
               and p.id != e.kicked["player"]]
    assert runners
    for pid in runners:
        x, y, vx, vy = track[start]["players"][pid]
        assert abs(x - line) >= offball.BOX_RUN_START_M - 0.5, pid  # waiting no nearer than the mark
        gained = abs(x - line) - abs(track[-1]["players"][pid][0] - line)
        assert gained >= 1.0, pid  # on his run in by the kick (on main he stood: 0 m)


@pytest.mark.parametrize(("seed", "team", "flag"), CASES)
def test_at_a_corner_the_defending_side_guards_its_near_post(seed, team, flag):
    """Defect: nobody stood in the near-post area unless he marked a man there. At the kick one
    defending outfielder stands within a stride of the near post, inside it, marking nobody."""
    e = corner(seed, team, flag)
    guard_spot = None
    kick(e)
    line = goal_line(team)
    near = PITCH_Y / 2 + (GOAL_HALF_WIDTH if flag > PITCH_Y / 2 else -GOAL_HALF_WIDTH)
    defending = "away" if team == "home" else "home"
    guards = [p for p in e.players if p.team == defending and p.role != "GK"
              and abs(p.x - line) <= 2.0 and abs(p.y - near) <= 2.0]
    assert guards, guard_spot


def test_at_a_corner_the_defending_side_outnumbers_the_attackers_in_its_area():
    """Each attacker in the area is marked and the near post is guarded besides (Pulling & Newton
    2017), so the defending side has more outfielders there than the attacking side at every kick."""
    for seed, team, flag in CASES:
        e = corner(seed, team, flag)
        kick(e)
        line = goal_line(team)
        defending = "away" if team == "home" else "home"
        assert in_area(e, defending, line) > in_area(e, team, line), (seed, team)
