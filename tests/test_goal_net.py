"""The goal's net (lesson 184): a ball that goes in is held by the net and stays in the goal until a
player of the side that conceded fetches it out through the goal mouth; a ball going wide hits no
net; nobody walks through a net. Each defect test fails on the engine before this change (lesson 8):
there the ball rolled on through the back of the net to the advertising boards, and the keeper
walked through the net after it."""

import math
import re
from pathlib import Path

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
    steer,
)

R = ball.RADIUS
MID = PITCH_Y / 2
EPS = 1e-9
# Shots at the away side's goal (x = PITCH_X) from close in, and the part of the net each meets: low
# and hard into the back, rising into the roof, across into the side netting, and across so fast,
# just inside the post, that in the frame it goes in it is already past the side netting's line.
SHOTS = {
    "low and hard": ((100.0, 34.5, 0.2, 26.0, 0.5, 1.0), "back"),
    "rising": ((101.0, 34.0, 1.2, 20.0, 0.0, 5.0), "roof"),
    "across": ((103.0, 34.0, 0.2, 8.0, 8.0, 0.0), "side"),
    "just inside the post": ((102.0, 34.4, 0.4, 25.0, 22.0, 0.0), "side"),
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


def shot_at_goal(shot: tuple[float, ...], shooter: str = "h9") -> Engine:
    """A minute into a match, a shot by `shooter` flies at the other side's goal (the home side
    attacks x = PITCH_X) with nobody near enough to touch it."""
    e = Engine(2)
    e.run(1)
    home = shooter.startswith("h")
    for p in e.players:
        p.x, p.vx, p.vy = (min(p.x, 80.0) if home else max(p.x, PITCH_X - 80.0)), 0.0, 0.0
    e.possessor, e.restart, e.throw_by, e.set_by = None, None, None, None
    e.ball = shot
    e.last_touch = shooter
    e.kicked = e.emit("shot", "home" if home else "away", shot[0], shot[1], player=shooter)
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


def goal_then_kickoff(shot: tuple[float, ...], shooter: str = "h9") -> tuple[Engine, list[dict], list[dict],
                                                                         tuple[float, float]]:
    """The shot until the goal, then on until the kick-off is taken; and where the engine, at the
    goal, said the ball would come to rest."""
    e = shot_at_goal(shot, shooter)
    before = play_on(e, lambda e: any(ev["type"] == "goal" for ev in e.match.events), 3)
    netted = e.netted
    rest = e.dead_ball_rest()
    assert e.netted == netted  # a prediction: it changes nothing
    after = play_on(e, lambda e: e.restart is None, 120)
    return e, before, after, rest


@pytest.mark.parametrize("name", SHOTS)
def test_a_shot_into_the_goal_stays_in_the_goal_held_by_its_net(name):
    """Defect: the ball rolled on through the net to the advertising boards, 4 m behind the line.
    It is held from the frame the goal is given (the first of `after`)."""
    shot, part = SHOTS[name]
    e, _, after, rest = goal_then_kickoff(shot)
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


@pytest.mark.parametrize("name", SHOTS)
def test_the_side_that_conceded_fetches_it_out_through_the_goal_mouth(name):
    e, _, after, _ = goal_then_kickoff(SHOTS[name][0])
    first = next(f for f in after if f["carried_by"] or f["passed_by"])
    assert (first["carried_by"] or first["passed_by"]).startswith("a")  # the away side conceded
    out = next(b for a, b in zip(after, after[1:], strict=False) if a["ball"][0] > PITCH_X >= b["ball"][0])
    assert abs(out["ball"][1] - MID) < GOAL_HALF_WIDTH  # out over the goal line, between the posts
    assert e.match.events[-1]["type"] == "kickoff"
    assert e.netted is None  # out of the goal, the net lets it go


@pytest.mark.parametrize("name", SHOTS)
def test_nobody_walks_through_the_net_after_a_goal(name):
    """Defect: the keeper walked through the net to the ball behind the goal. The side that conceded
    has a player standing behind the goal, whose straight way to the ball in it is through the back
    of the net (the audit of lesson 184 found the goals alone never sent anyone that way)."""
    e = shot_at_goal(SHOTS[name][0])
    before = play_on(e, lambda e: any(ev["type"] == "goal" for ev in e.match.events), 3)
    rest = e.dead_ball_rest()
    behind, keeper = e.by_id["a2"], e.keeper("away")
    behind.x, behind.y, behind.vx, behind.vy = PITCH_X + NET_DEPTH_M + 0.4, rest[1], 0.0, 0.0
    keeper.x, keeper.y, keeper.vx, keeper.vy = PITCH_X - 20.0, MID, 0.0, 0.0
    assert any(through((behind.x, behind.y), rest, c, d) for c, d in nets())
    track = play_on(e, lambda e: e.restart is not None and e.restart.carried_by is not None, 60)
    assert e.restart.carried_by == "a2"  # he is the nearest, and he went round the net to it
    assert walked_through(before) == [] and walked_through(track) == []  # placed between the two


def test_a_ball_played_on_after_the_whistle_into_the_goal_is_held_by_its_net():
    """Defect: a shot struck as the whistle went for a foul flew on into the goal and out through
    the back of its net to the boards (seed 112 at 17:17). Any ball that goes in over the goal
    line between the posts and under the bar is held, not only a goal."""
    e = Engine(2)
    e.run(1)
    for p in e.players:
        p.x, p.vx, p.vy = min(p.x, 80.0), 0.0, 0.0
    e.possessor, e.throw_by, e.set_by = None, None, None
    goals = sum(ev["type"] == "goal" for ev in e.match.events)
    e.stop("free_kick", "away", (60.0, MID))  # the whistle: the ball is dead
    e.ball = (100.0, 34.5, 0.4, 20.0, 0.5, 1.0)
    track = play_on(e, lambda e: math.hypot(*e.ball[3:]) == 0.0, 10)
    assert sum(ev["type"] == "goal" for ev in e.match.events) == goals  # dead: no goal
    for f in track:
        bx, by, bz = f["ball"][:3]
        if bx > PITCH_X:
            assert bx - PITCH_X <= NET_DEPTH_M - R + EPS, f["t"]
            assert abs(by - MID) <= GOAL_HALF_WIDTH - R + EPS, f["t"]
    assert track[-1]["ball"][0] > PITCH_X  # at rest in the goal


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
    (((106.95, 37.6), (107.2, 37.8)), (106.95, 37.6)),  # through the corner, the back met first
    (((106.0, 37.5), (106.0, 37.66)), (106.0, 37.5)),  # onto the side netting's line: touching it
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
    shot = SHOTS["low and hard"][0]
    netted = shot_at_goal(shot)
    play_on(netted, lambda e: any(ev["type"] == "goal" for ev in e.match.events), 3)
    no_net = shot_at_goal(shot)
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(engine, "in_the_net", lambda s, line: (s, None))
        play_on(no_net, lambda e: any(ev["type"] == "goal" for ev in e.match.events), 3)
    assert netted.match.events == no_net.match.events
    # and from the goal on the ball moves on from where it was, by no more than its own speed
    # allows in a frame: the net holds it where it meets it, it does not put it anywhere
    track = play_on(netted, lambda e: math.hypot(*e.ball[3:]) == 0.0, 5)
    fastest = math.hypot(*shot[3:]) * DT
    for a, b in zip(track, track[1:], strict=False):
        assert math.dist(a["ball"][:3], b["ball"][:3]) <= fastest, b["t"]
        assert b["ball"][0] > PITCH_X  # in the goal
    goal = netted.match.events[-1]
    shot_event = next(ev for ev in netted.match.events if ev["type"] == "shot" and ev["player"] == "h9")
    assert goal["type"] == "goal" and shot_event["outcome"] == "goal" and goal["player"] == "h9"


def test_the_engines_net_is_the_net_the_renderer_draws():
    """L1: the net's shape is the one drawn (web/render/render.js, buildNet), so the ball stops at
    the net the viewer sees."""
    src = (Path(__file__).parents[1] / "web" / "render" / "render.js").read_text()
    drawn = re.search(r"const y0 = ([\d.]+), y1 = ([\d.]+), depth = ([\d.]+), backZ = ([\d.]+);", src)
    y0, y1, depth, back = map(float, drawn.groups())
    assert (y0, y1) == pytest.approx((MID - GOAL_HALF_WIDTH, MID + GOAL_HALF_WIDTH))
    assert (depth, back) == (NET_DEPTH_M, NET_BACK_M)


def test_nobody_takes_the_dead_ball_through_the_net():
    """A player of the side that conceded, standing outside the side netting within a foot's
    reach of the ball at rest inside it, does not take it through the net (the audit's probe B):
    whoever takes it has no net between him and it."""
    e = shot_at_goal(SHOTS["across"][0])
    play_on(e, lambda e: any(ev["type"] == "goal" for ev in e.match.events), 3)
    play_on(e, lambda e: math.hypot(*e.ball[3:]) == 0.0, 5)
    bx, by = e.ball[:2]
    assert by >= MID + GOAL_HALF_WIDTH - R - EPS  # at rest against the side netting
    near = e.by_id["a2"]
    near.x, near.y, near.vx, near.vy = bx, MID + GOAL_HALF_WIDTH + 0.45, 0.0, 0.0
    assert math.dist((near.x, near.y), (bx, by)) < 1.0  # within a foot's reach (CONTROL_M)
    track = play_on(e, lambda e: e.restart.carried_by is not None, 60)
    taker = track[-1]["players"][e.restart.carried_by]
    assert not any(through(taker, track[-2]["ball"][:2], c, d) for c, d in nets())


def test_a_player_running_at_a_net_is_stopped_by_it():
    """steer: the net stops the part of a run that goes into it, as the boards do."""
    p = Engine(2).keeper("away")
    p.x, p.y, p.vx, p.vy = PITCH_X + 1.0, MID + GOAL_HALF_WIDTH - 0.6, 0.0, 4.0  # in the goal, at its side
    for _ in range(25):
        steer(p, p.x, MID + GOAL_HALF_WIDTH + 3.0, 7.0)
        assert p.y < MID + GOAL_HALF_WIDTH
    assert p.vy == 0.0


def test_a_keeper_diving_at_his_net_is_stopped_by_it():
    """keeper_dive: a dive from inside the goal toward the side netting stops at it, and he lands
    with no speed into it."""
    e = Engine(2)
    k = e.keeper("away")
    k.x, k.y, k.vx, k.vy = PITCH_X + 0.8, MID + GOAL_HALF_WIDTH - 1.0, 0.0, 0.0
    e.dive = (k.id, e.t, k.y, 2.5, e.t, 0.0)  # 2.5 m sideways, through where the side netting is
    stopped = False
    while e.keeper_dive(k):
        assert k.y < MID + GOAL_HALF_WIDTH
        stopped = stopped or k.vy == 0.0
        e.t += DT
    assert stopped and k.vy == 0.0


def test_the_net_of_the_goal_at_the_other_end_holds_the_ball_too():
    """The away side scores at x = 0: the home side's net holds the ball, nobody walks through a
    net, and it is fetched out through the mouth; going round that goal's net, a player leaves
    through its mouth."""
    e, before, after, _ = goal_then_kickoff((5.0, 34.5, 0.2, -26.0, 0.5, 1.0), "a9")
    assert next(ev for ev in e.match.events if ev["type"] == "goal")["team"] == "away"
    held = [f for f in after if f["ball"][0] < 0]
    assert held and all(-f["ball"][0] <= NET_DEPTH_M - R + EPS for f in held)
    assert all(abs(f["ball"][1] - MID) <= GOAL_HALF_WIDTH - R + EPS for f in held)
    out = next(b for a, b in zip(after, after[1:], strict=False) if a["ball"][0] < 0 <= b["ball"][0])
    assert abs(out["ball"][1] - MID) < GOAL_HALF_WIDTH
    assert walked_through(before + after) == []
    p = e.keeper("home")
    p.x, p.y = -1.0, MID
    assert e.round_the_net(p, -3.5, MID) == (NET_CLEAR_M, MID)


@pytest.mark.parametrize("ball_state", [
    (100.0, MID + GOAL_HALF_WIDTH + 1.0, 0.3, 20.0, 0.0, 0.5),  # wide of the post
    (100.0, MID, 2.4, 20.0, 0.0, 3.0),  # over the bar
], ids=["wide of the post", "over the bar"])
def test_a_ball_played_on_after_the_whistle_wide_or_over_is_not_pulled_into_the_goal(ball_state):
    """Only a ball that goes in over the goal line between the posts and under the bar is held: one
    played on after the whistle wide of a post or over the bar flies on as it would anyway."""
    e = Engine(2)
    e.run(1)
    for p in e.players:
        p.x, p.vx, p.vy = min(p.x, 80.0), 0.0, 0.0
    e.possessor, e.throw_by, e.set_by = None, None, None
    e.stop("free_kick", "away", (60.0, MID))
    e.ball = ball_state
    free = ball.predict(e.ball, DT, 1.0)
    track = play_on(e, lambda e: e.ball[0] > PITCH_X + NET_DEPTH_M + 0.5, 2)
    assert e.netted is None and len(track) <= len(free)
    for f, s in zip(track, free, strict=False):
        assert f["ball"] == s


def dead_ball(state: tuple[float, ...]) -> Engine:
    """A minute in, the whistle has gone for a free kick in midfield and the dead ball is moving
    near the away side's goal (x = PITCH_X), everyone else far from it."""
    e = Engine(2)
    e.run(1)
    for p in e.players:
        p.x, p.vx, p.vy = min(p.x, 80.0), 0.0, 0.0
    e.possessor, e.throw_by, e.set_by = None, None, None
    e.stop("free_kick", "away", (60.0, MID))
    e.ball = state
    return e


def in_the_goal(b: tuple[float, ...]) -> bool:
    """The ball's centre inside the goal: behind its line, between its side nets and under its roof."""
    behind = b[0] - PITCH_X
    return 0 < behind < NET_DEPTH_M and abs(b[1] - MID) < GOAL_HALF_WIDTH and b[2] < roof(b[0]) + 2 * R


# Lesson 200: a ball outside the goal meets the net's outside. Each starts outside the goal and
# would go into it through the net: beside the post into the side netting, from behind into the
# back, dropping onto the roof. On main each went through the net and into (or across) the goal.
OUTSIDE = {
    "beside the post": ((104.0, 39.0, 0.0, 6.0, -3.0, 0.0), "side"),
    "from behind the goal": ((109.0, 34.0, 0.0, -5.0, 0.0, 0.0), "back"),
    "dropping onto the roof": ((106.0, 34.0, 3.0, 0.0, 0.0, 0.0), "roof"),
}


@pytest.mark.parametrize("name", OUTSIDE)
def test_a_dead_ball_outside_the_goal_meets_its_net_from_outside(name):
    state, part = OUTSIDE[name]
    e = dead_ball(state)
    track = play_on(e, lambda e: math.hypot(*e.ball[3:]) == 0.0 and e.ball[2] == 0.0, 15)
    assert not any(in_the_goal(f["ball"]) for f in track)
    met = []
    for f in track:
        bx, by, bz, vx, vy, vz = f["ball"]
        if part == "side" and abs(abs(by - MID) - (GOAL_HALF_WIDTH + R)) <= EPS and bx > PITCH_X:
            met.append(f)
            assert vy * (by - MID) >= 0, f["t"]  # not on into the net: the net took that speed
        if part == "back" and abs(bx - (PITCH_X + NET_DEPTH_M + R)) <= EPS:
            met.append(f)
            assert vx >= 0, f["t"]
        if part == "roof" and bz > 0 and abs(bz - (roof(bx) + 2 * R)) <= 1e-6:
            met.append(f)
    assert met  # it met that part of the net
    assert track[-1]["ball"][0] > PITCH_X  # and came to rest outside the goal, behind its line


def test_a_ball_on_the_roof_rolls_down_it_and_off_the_back():
    """Lesson 200: a ball dropped onto the roof does not stay up there (the fetcher could never take
    it): it rolls down the slope toward the back and drops off behind the goal."""
    e = dead_ball(OUTSIDE["dropping onto the roof"][0])
    track = play_on(e, lambda e: math.hypot(*e.ball[3:]) == 0.0 and e.ball[2] == 0.0, 15)
    on = [f for f in track if f["ball"][2] > 0 and abs(f["ball"][2] - (roof(f["ball"][0]) + 2 * R)) <= 1e-6]
    assert len(on) > 2
    assert all(b["ball"][0] >= a["ball"][0] for a, b in zip(on, on[1:], strict=False))  # toward the back
    assert track[-1]["ball"][0] > PITCH_X + NET_DEPTH_M  # down behind the goal


def test_a_shot_wide_of_the_post_meets_the_side_netting_in_the_frame_it_crosses():
    """Lesson 200: in play, a ball crossing the goal line just wide of the post and on into where the
    side netting is, within one frame, is stopped there too (Engine.woodwork), not only once dead."""
    e = shot_at_goal((104.9, MID + GOAL_HALF_WIDTH + 0.24, 0.3, 20.0, -10.0, 0.0))
    play_on(e, lambda e: e.ball[0] > PITCH_X, 1)
    assert abs(e.ball[1] - MID) >= GOAL_HALF_WIDTH + R - EPS
    assert e.ball[4] == 0.0
    assert e.restart is not None and e.restart.kind == "goal_kick"
