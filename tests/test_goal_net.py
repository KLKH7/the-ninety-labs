"""The goal's net (lesson 184): a ball that goes in is held by the net and stays in the goal until a
player of the side that conceded fetches it out through the goal mouth; a ball going wide hits no
net; nobody walks through a net. Each defect test fails on the engine before this change (lesson 8):
there the ball rolled on through the back of the net to the advertising boards, and the keeper
walked through the net after it."""

import math

import pytest

from ninety.sim import ball, engine
from ninety.sim.engine import (
    CROSSBAR,
    DT,
    GOAL_AREA_X,
    GOAL_HALF_WIDTH,
    NET_BACK_M,
    NET_CLEAR_M,
    NET_DEPTH_M,
    PITCH_X,
    PITCH_Y,
    Engine,
    net_stop,
)

R = ball.RADIUS
MID = PITCH_Y / 2
EPS = 1e-9
# Shots at the away side's goal (x = PITCH_X) from close in, each into a different part of the net:
# low and hard into the back, rising into the roof, across into the side netting.
SHOTS = {
    "back": (100.0, 34.5, 0.2, 26.0, 0.5, 1.0),
    "roof": (101.0, 34.0, 1.2, 20.0, 0.0, 5.0),
    "side": (103.0, 34.0, 0.2, 8.0, 8.0, 0.0),
}


def roof(x: float) -> float:
    """The highest the ball's lowest point can be under the roof, this far into the goal: the roof
    slopes from the crossbar down to the top of the back net."""
    behind = min(x - PITCH_X, NET_DEPTH_M)
    return CROSSBAR + (NET_BACK_M - CROSSBAR) * behind / NET_DEPTH_M - 2 * R


def through(a: tuple[float, float], b: tuple[float, float], c: tuple[float, float],
            d: tuple[float, float]) -> bool:
    """Whether the step from a to b passes through the stretch of net from c to d (touching it
    counts), solved as two lines meeting: a + s (b - a) = c + u (d - c), s and u in [0, 1]."""
    rx, ry, qx, qy = b[0] - a[0], b[1] - a[1], d[0] - c[0], d[1] - c[1]
    den = rx * qy - ry * qx
    if den == 0:
        return False  # along it, never through it
    s = ((c[0] - a[0]) * qy - (c[1] - a[1]) * qx) / den
    u = ((c[0] - a[0]) * ry - (c[1] - a[1]) * rx) / den
    return 0 <= s <= 1 and 0 <= u <= 1


def nets() -> list[tuple[tuple[float, float], tuple[float, float]]]:
    """Both goals' nets seen from above: two sides and a back each, NET_DEPTH_M behind the line."""
    out = []
    for line, sign in ((0.0, -1.0), (PITCH_X, 1.0)):
        back = line + sign * NET_DEPTH_M
        lo, hi = MID - GOAL_HALF_WIDTH, MID + GOAL_HALF_WIDTH
        out += [((line, lo), (back, lo)), ((line, hi), (back, hi)), ((back, lo), (back, hi))]
    return out


def walked_through(track: list[dict]) -> list[tuple[float, str]]:
    """Every (time, player) whose step from one frame to the next passed through a net."""
    sides = nets()
    return [(b["t"], pid) for a, b in zip(track, track[1:], strict=False) for pid in b["players"]
            if any(through(a["players"][pid], b["players"][pid], c, d) for c, d in sides)]


def frame(e: Engine) -> dict:
    r = e.restart
    return {"t": e.t, "ball": e.ball, "players": {p.id: (p.x, p.y) for p in e.players},
            "carried_by": r.carried_by if r else None, "passed_by": r.passed_by if r else None,
            "restart": r.kind if r else None}


def shot_at_goal(shot: tuple[float, ...]) -> Engine:
    """A minute into a match, a shot by h9 flies at the away side's goal with nobody near enough
    to touch it."""
    e = Engine(2)
    e.run(1)
    for p in e.players:
        p.x, p.vx, p.vy = min(p.x, 80.0), 0.0, 0.0
    e.possessor, e.restart, e.throw_by, e.set_by = None, None, None, None
    e.ball = shot
    e.last_touch = "h9"
    e.kicked = e.emit("shot", "home", shot[0], shot[1], player="h9")
    e.shot_touched_by = e.shot_was_on_target = None
    return e


def play_on(e: Engine, done, seconds: float) -> list[dict]:
    track = [frame(e)]
    for _ in range(int(seconds / DT)):
        e.step()
        track.append(frame(e))
        if done(e):
            return track
    raise AssertionError("never happened")


def goal_then_kickoff(shot: tuple[float, ...]) -> tuple[Engine, list[dict], list[dict], tuple[float, float]]:
    """The shot until the goal, then on until the kick-off is taken; and where the engine, at the
    goal, said the ball would come to rest."""
    e = shot_at_goal(shot)
    before = play_on(e, lambda e: any(ev["type"] == "goal" for ev in e.match.events), 3)
    netted = e.netted
    rest = e.dead_ball_rest()
    assert e.netted == netted  # a prediction: it changes nothing
    after = play_on(e, lambda e: e.restart is None, 120)
    return e, before, after, rest


@pytest.mark.parametrize("part", SHOTS)
def test_a_shot_into_the_goal_stays_in_the_goal_held_by_its_net(part):
    """Defect: the ball rolled on through the net to the advertising boards, 4 m behind the line."""
    e, _, after, rest = goal_then_kickoff(SHOTS[part])
    goal = next(ev for ev in e.match.events if ev["type"] == "goal")
    assert (goal["team"], goal["player"]) == ("home", "h9")
    met = set()
    for f in after:
        bx, by, bz, vx, vy, vz = f["ball"]
        if bx <= PITCH_X:
            continue  # out of the goal
        assert bx - PITCH_X <= NET_DEPTH_M - R + EPS, f["t"]
        assert abs(by - MID) <= GOAL_HALF_WIDTH - R + EPS, f["t"]
        assert bz <= roof(bx) + EPS, f["t"]
        if f["carried_by"] or f["passed_by"]:
            continue  # taken: it moves with him (carry_dead_ball)
        # where it is against the net, it is not moving on into it: the net took that speed
        if bx - PITCH_X >= NET_DEPTH_M - R - EPS:
            met.add("back")
            assert vx <= 0, f["t"]
        if abs(by - MID) >= GOAL_HALF_WIDTH - R - EPS:
            met.add("side")
            assert vy * (by - MID) <= 0, f["t"]
        if bz >= roof(bx) - EPS and bz > 0:
            met.add("roof")
            assert vz <= 0, f["t"]
    assert part in met  # the shot went where it was aimed
    # It comes to rest in the goal, where the engine said it would, before anyone takes it.
    untouched = [f for f in after if f["carried_by"] is None and f["passed_by"] is None]
    still = next(f for f in untouched if math.hypot(*f["ball"][3:]) == 0.0)
    assert still["ball"][0] > PITCH_X
    assert math.dist(still["ball"][:2], rest) <= EPS


@pytest.mark.parametrize("part", SHOTS)
def test_the_side_that_conceded_fetches_it_out_through_the_goal_mouth(part):
    e, _, after, _ = goal_then_kickoff(SHOTS[part])
    first = next(f for f in after if f["carried_by"] or f["passed_by"])
    assert (first["carried_by"] or first["passed_by"]).startswith("a")  # the away side conceded
    out = next(b for a, b in zip(after, after[1:], strict=False) if a["ball"][0] > PITCH_X >= b["ball"][0])
    assert abs(out["ball"][1] - MID) < GOAL_HALF_WIDTH  # out over the goal line, between the posts
    assert e.match.events[-1]["type"] == "kickoff"


@pytest.mark.parametrize("part", SHOTS)
def test_nobody_walks_through_the_net_after_a_goal(part):
    """Defect: the keeper walked through the net to the ball behind the goal."""
    _, before, after, _ = goal_then_kickoff(SHOTS[part])
    assert walked_through(before + after) == []


@pytest.mark.parametrize("start", [(106.0, 34.0), (100.0, 34.0), (106.0, 40.0), (108.5, 30.0)])
def test_a_ball_behind_the_goal_is_fetched_round_the_net_not_through_it(start):
    """A goal kick whose ball came to rest behind the goal (a wide ball rolls on to the boards):
    the keeper goes round the net to it, from inside the goal out through its mouth."""
    e = Engine(2)
    e.run(1)
    e.possessor, e.throw_by, e.set_by = None, None, None
    e.ball = (PITCH_X + 3.5, MID + 0.5, 0.0, 0.0, 0.0, 0.0)
    gk = e.keeper("away")
    gk.x, gk.y, gk.vx, gk.vy = *start, 0.0, 0.0
    e.stop("goal_kick", "away", (PITCH_X - GOAL_AREA_X, MID), gk.id)
    track = play_on(e, lambda e: e.restart is not None and e.restart.carried_by is not None, 60)
    assert walked_through(track) == []


def test_going_round_the_net_keeps_a_stride_clear_of_it():
    """From inside the goal to a place behind it, his first step is out of the goal mouth,
    NET_CLEAR_M in front of the line; from beside the goal, round its post NET_CLEAR_M clear."""
    e = Engine(2)
    p = e.keeper("away")
    p.x, p.y = PITCH_X + 1.0, MID
    assert e.round_the_net(p, PITCH_X + 3.5, MID) == (PITCH_X - NET_CLEAR_M, MID)
    p.x, p.y = PITCH_X + 1.0, MID + GOAL_HALF_WIDTH + 0.5  # beside the goal, outside its side net
    assert e.round_the_net(p, PITCH_X + 1.0, MID) == (PITCH_X, MID + GOAL_HALF_WIDTH + NET_CLEAR_M)
    p.x, p.y = 90.0, 20.0
    assert e.round_the_net(p, 95.0, 25.0) == (95.0, 25.0)  # on the pitch the nets are nowhere near


@pytest.mark.parametrize(("step", "kept"), [
    (((106.0, 37.5), (106.0, 37.8)), (106.0, 37.5)),  # into a side net from inside: stops across it
    (((106.5, 34.0), (107.2, 34.1)), (106.5, 34.1)),  # into the back: stops across it, goes along
    (((106.9, 37.6), (107.1, 37.8)), (106.9, 37.6)),  # through its corner: both
    (((104.0, 34.0), (105.5, 34.5)), (105.5, 34.5)),  # in through the goal mouth: free
    (((106.0, 38.0), (106.5, 38.3)), (106.5, 38.3)),  # beside the goal, outside it: free
    (((-1.0, 30.5), (-1.0, 30.0)), (-1.0, 30.5)),  # the other goal's side net
])
def test_a_net_stops_a_player_as_the_boards_do(step, kept):
    (px, py), (x, y) = step
    nx, ny, vx, vy = net_stop(px, py, x, y, (x - px) / DT, (y - py) / DT)
    assert (nx, ny) == kept
    assert vx == (0.0 if nx != x else (x - px) / DT) and vy == (0.0 if ny != y else (y - py) / DT)


def test_a_wide_shot_hits_no_net():
    """Only a goal puts the ball in a net: a shot wide of the post flies on as it would anyway."""
    shot = (101.0, MID + GOAL_HALF_WIDTH + 1.0, 0.3, 22.0, 2.0, 1.5)
    e = shot_at_goal(shot)
    free = ball.predict(e.ball, DT, 1.0)
    track = play_on(e, lambda e: e.ball[0] > PITCH_X + NET_DEPTH_M + 1.0, 3)
    assert not any(ev["type"] == "goal" for ev in e.match.events)
    assert e.netted is None
    # every frame of its flight on past the goal line, through where a net would be, is free flight
    assert len(track) <= len(free)
    for f, s in zip(track, free, strict=False):
        assert f["ball"] == s


def test_the_goal_itself_is_unchanged():
    """C8: the net holds the ball only once the goal is given, so the goal is credited to the
    shot at the frame the ball crosses the line, as it was before there was a net."""
    shot = SHOTS["back"]
    netted = shot_at_goal(shot)
    play_on(netted, lambda e: any(ev["type"] == "goal" for ev in e.match.events), 3)
    no_net = shot_at_goal(shot)
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(engine, "in_the_net", lambda s, line: (s, None))
        play_on(no_net, lambda e: any(ev["type"] == "goal" for ev in e.match.events), 3)
    assert netted.match.events == no_net.match.events
    goal = netted.match.events[-1]
    shot_event = next(ev for ev in netted.match.events if ev["type"] == "shot" and ev["player"] == "h9")
    assert goal["type"] == "goal" and shot_event["outcome"] == "goal" and goal["player"] == "h9"
