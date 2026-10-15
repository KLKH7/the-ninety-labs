"""Corners (docs/GROUNDING.md S rows and L9): the routine places players and never decides an
outcome; the corner is taken when the teams are ready and the Law's distance is kept, not on a
timer; the taker never touches his own corner; and the Law 17 check in the validator passes
legal corners and fails each planted breach. Each test names the mutation it must catch."""

import json
import math

import pytest
from test_validate import FPS, event, run

from ninety.sim import decisions, setpieces
from ninety.sim.engine import PENALTY_DEPTH, PENALTY_HALF_WIDTH, SPRINT, Engine, simulate
from ninety.validate import validate


def corner_engine(seed: int = 3, side: float = 0.0) -> Engine:
    e = Engine(seed)
    e.ball = (105.5, abs(side - 8.0), 0.0, 0.0, 0.0, 0.0)
    e.stop("corner", "home", (105.0, side))
    return e


def in_box(x: float, y: float, line: float) -> bool:
    return abs(x - line) <= PENALTY_DEPTH and abs(y - 34.0) <= PENALTY_HALF_WIDTH


def tick(e: Engine) -> None:
    e.moved = None
    e.perceive_and_think()
    if e.possessor:
        e.tick_carrier()
    elif e.restart:
        e.tick_restart()
    else:
        e.tick_free()
    e.move_players()
    e.snapshot()
    e.t += 1 / FPS
    e.frame += 1


def run_until_kick(e: Engine, limit_s: float = 60.0) -> dict:
    for _ in range(int(limit_s * FPS)):
        tick(e)
        kicks = [ev for ev in e.match.events if ev["type"] == "pass"]
        if kicks:
            return kicks[0]
    raise AssertionError("the corner was never taken")


def settle_everyone(e: Engine) -> None:
    """Put every player on his spot, standing still, and the taker at the ball."""
    c = e.set_play
    for p in e.players:
        spot = c.run_up if p.id == c.taker else setpieces.target(e, p)
        if spot:
            p.x, p.y, p.vx, p.vy = spot[0], spot[1], 0.0, 0.0
    for p in e.players:  # markers depend on where their attackers now stand
        if p.id in c.marks or p.id in c.rest_marks:
            p.x, p.y = setpieces.target(e, p)


def placed(e: Engine) -> None:
    """Everyone set, the ball placed, the taker stepped back and the placing time over."""
    settle_everyone(e)
    assert not setpieces.advance(e)
    c = e.set_play
    taker = e.by_id[c.taker]
    taker.x, taker.y = c.approach
    e.t += setpieces.PLACE_S


# --- the routine -------------------------------------------------------------------------------

def test_every_player_has_a_place_and_the_best_crosser_takes_it():
    e = corner_engine()
    c = e.set_play
    eligible = [p for p in e.players if p.team == "home" and p.role in setpieces.TAKER_ROLES]
    assert c.taker == max(eligible, key=lambda p: p.profile["crossing"]).id
    for p in e.players:
        placed_ = p.id in c.targets or p.id in c.marks or p.id in c.rest_marks
        assert p.id == c.taker or placed_, p.id
    box = [pid for pid, z in c.zones.items() if z in setpieces.ATTACK_ZONES and z != "edge"]
    assert len(box) >= 4 and set(c.marks.values()) == set(box)  # each attacker in the box is marked


def test_each_corner_draws_its_own_routine():
    """Mutations caught: a fixed role-to-zone table; zones without jitter; a fixed run-up; a
    fixed number of defenders left up; no short corner ever set up."""
    plans = [corner_engine(seed=s).set_play for s in range(40)]
    by_zone = {tuple(sorted((z, pid) for pid, z in c.zones.items())) for c in plans}
    assert len(by_zone) > 20  # who goes where differs from corner to corner
    assert len({c.targets[next(p for p, z in c.zones.items() if z == "far_post")] for c in plans}) == 40
    assert len({c.approach for c in plans}) == 40
    assert {len(c.left_up) for c in plans} == set(setpieces.LEFT_UP)
    assert any("short" in c.zones.values() for c in plans)


def test_rest_defence_marks_only_the_defenders_left_up():
    """Regression (audit 5): a forward who defends in the box was marked as if he had stayed up.
    Mutation caught: rest defenders placed upfield of the players they guard."""
    for seed in range(20):
        e = corner_engine(seed=seed)
        c = e.set_play
        assert set(c.rest_marks.values()) <= set(c.left_up), seed
    e = corner_engine()
    settle_everyone(e)
    for rest_id, counter_id in e.set_play.rest_marks.items():
        rest, counter = e.by_id[rest_id], e.by_id[counter_id]
        assert math.isclose(math.dist((rest.x, rest.y), (counter.x, counter.y)), 2.0)  # S5
        assert rest.x < counter.x  # home defends x = 0: nearer his own goal than the forward


def test_a_defender_covers_the_edge_of_the_box():
    """Regression (audit 5): the edge cover was never filled, so the man on the edge was free."""
    for seed in range(20):
        c = corner_engine(seed=seed).set_play
        edge = c.zone_point(*setpieces.DEFEND_ZONES["edge_cover"])
        assert any(c.targets.get(p.id) == edge for p in corner_engine(seed=seed).players
                   if p.team == "away"), seed


def test_defenders_are_held_at_the_laws_distance_even_when_marking_near_the_flag():
    """Mutation caught: keep_off removed from target(). An attacker drifts toward the flag (to
    offer a short corner); his marker follows him only as far as the Law allows."""
    e = corner_engine(side=68.0)
    c = e.set_play
    spot = setpieces.target(e, e.by_id[c.short_block])
    assert math.isclose(math.hypot(spot[0] - 105.0, spot[1] - 68.0), setpieces.STAND_OFF_M)
    marker, attacker = next(iter(c.marks.items()))
    e.by_id[attacker].x, e.by_id[attacker].y = 101.0, 64.0  # about 5.7 m from the flag
    mx, my = setpieces.target(e, e.by_id[marker])
    assert math.isclose(math.hypot(mx - 105.0, my - 68.0), setpieces.STAND_OFF_M)
    for p in e.players:
        if p.team == "away" and (s := setpieces.target(e, p)):
            assert math.hypot(s[0] - 105.0, s[1] - 68.0) >= setpieces.STAND_OFF_M - 1e-9


def test_placed_then_stepped_back_then_signalled_only_when_everyone_is_set():
    """Mutations caught: PLACE_S = 0; no step back; the signal or the strike ignoring the other
    players or the Law's distance; the set-piece event at placement."""
    e = corner_engine()
    settle_everyone(e)
    c = e.set_play
    assert not setpieces.advance(e)
    assert c.placed_at == e.t and e.ball[:2] == c.ball_spot
    assert not any(ev["type"] == "set_piece" for ev in e.match.events)  # placed, not yet ready
    taker = e.by_id[c.taker]
    assert setpieces.target(e, taker) == c.run_up  # still placing it
    e.t += setpieces.PLACE_S - 0.1
    assert setpieces.target(e, taker) == c.run_up
    e.t += 0.2
    assert setpieces.target(e, taker) == c.approach  # steps back
    assert not setpieces.advance(e) and c.signalled_at is None  # not back yet
    taker.x, taker.y = c.approach
    runner = e.by_id[next(iter(c.zones))]
    runner.x, runner.vx = runner.x - 10.0, 5.0  # far from his spot and still running to it
    assert not setpieces.advance(e) and c.signalled_at is None
    runner.vx = 0.0  # stopped short (someone in the way): he does not hold the corner up
    intruder = e.by_id[c.short_block]
    intruder.x, intruder.y = 100.0, 4.0  # about 6 m from the flag
    assert not setpieces.advance(e) and c.signalled_at is None
    intruder.x, intruder.y = setpieces.target(e, intruder)
    assert not setpieces.advance(e) and c.signalled_at == e.t
    assert e.match.events[-1]["type"] in ("set_piece", "possession_change")  # ready: L9 from here
    assert setpieces.target(e, taker) == c.run_up  # the run-up
    taker.x, taker.y = c.run_up
    intruder.x, intruder.y = 100.0, 4.0  # steps in during the run-up: he does not strike
    assert not setpieces.advance(e)
    intruder.x, intruder.y = setpieces.target(e, intruder)
    assert setpieces.advance(e)


def test_the_corner_is_struck_when_the_taker_arrives_on_his_run_up():
    """No drawn delay and no settle: the kick comes when his run-up reaches the ball."""
    e = corner_engine()
    assert e.restart.ready_at == math.inf
    c = e.set_play
    kick = run_until_kick(e)
    assert kick["player"] == c.taker
    assert c.signalled_at is not None and kick["t"] > c.signalled_at
    taker = next(p for p in e.match.frames[kick["frame"]]["players"] if p["id"] == c.taker)
    assert math.dist((taker["x"], taker["y"]), c.run_up) <= setpieces.TAKER_AT_M + 0.3
    run = math.dist(c.approach, c.run_up)
    assert kick["t"] - c.signalled_at <= run / 2.0 + 1.0  # a run-up, not a wait


def test_the_box_is_crowded_and_the_law_is_kept_at_every_frame_to_the_kick():
    e = corner_engine(seed=5)
    run_until_kick(e)
    placed_at = next(ev for ev in e.match.events if ev["type"] == "set_piece")["frame"]
    for f in e.match.frames[placed_at:-1]:
        for p in f["players"]:
            if p["team"] == "away":
                assert math.hypot(p["x"] - 105.0, p["y"]) >= setpieces.LAW_DISTANCE_M
    f = e.match.frames[-1]
    assert sum(in_box(p["x"], p["y"], 105.0) for p in f["players"] if p["team"] == "home") >= 4
    assert sum(in_box(p["x"], p["y"], 105.0) for p in f["players"] if p["team"] == "away") >= 7


def test_runners_wait_then_set_off_to_arrive_with_the_ball():
    """Mutations caught: runners standing on their zones; runners leaving at the signal whatever
    the distance; no reaction to the signal; runners (or their markers) not sprinting."""
    e = corner_engine(seed=3)
    c = e.set_play
    assert c.starts and set(c.starts) <= set(c.zones)
    for pid, start in c.starts.items():
        assert setpieces.target(e, e.by_id[pid]) == start
        assert math.dist(start, c.targets[pid]) > 0.5
        assert not setpieces.running(e, e.by_id[pid])
    placed(e)
    taker = e.by_id[c.taker]
    taker.x, taker.y = c.approach
    near, far = list(c.starts)[:2]
    e.by_id[near].x, e.by_id[near].y = c.targets[near][0] - 1.0, c.targets[near][1]
    e.by_id[far].x, e.by_id[far].y = c.targets[far][0] - 30.0, c.targets[far][1]
    c.signalled_at = e.t
    setpieces.set_off(e, c)
    assert not c.going  # nobody responds before a reaction time
    e.t += 0.3
    setpieces.set_off(e, c)
    assert far in c.going and near not in c.going  # the far one must go now; the near one waits
    assert setpieces.target(e, e.by_id[far]) == c.targets[far]
    markers = [m for m, att in c.marks.items() if att == far]
    for pid in [far, *markers]:
        assert setpieces.running(e, e.by_id[pid]) and e.shape_target(e.by_id[pid])[2] == SPRINT


def test_beyond_a_short_corner_the_delivery_goes_through_the_air():
    """Regression (corner report): with the shared pass estimates and no heading, 199 of 200
    deliveries were struck along the ground into the box. Mutation caught: dropping S8's lofted
    delivery beyond SHORT_CORNER_M."""
    for seed in range(10):
        m = simulate(seed, 0.5, "corner")
        kick = next(ev for ev in m.events if ev["type"] == "pass")
        heights = [f["ball"]["z"] for f in m.frames[kick["frame"]:kick["frame"] + 10]]
        travelled = math.dist((kick["x"], kick["y"]), (m.frames[kick["frame"] + 9]["ball"]["x"],
                                                       m.frames[kick["frame"] + 9]["ball"]["y"]))
        if travelled > 5.0:  # not a short ball
            assert max(heights) > 0.5, seed


def test_the_taker_only_strikes_in_front_of_the_ball():
    """Mutation caught: strikeable() accepting a target behind the ball."""
    c = corner_engine().set_play
    bx, by = c.ball_spot
    ux, uy = c.facing
    assert setpieces.strikeable(c, bx + ux * 5, by + uy * 5)
    assert not setpieces.strikeable(c, bx - ux * 5, by - uy * 5)


def struck(monkeypatch, seed: int, target: tuple[float, float], draw: int, spy=None):
    option = decisions.Option("pass", 1.0, target, None, True)
    monkeypatch.setattr(setpieces, "choose_delivery", lambda engine, taker: option)
    e = corner_engine(seed=seed)
    placed(e)
    c = e.set_play
    taker = e.by_id[c.taker]
    taker.x, taker.y = c.run_up
    taker.heading = math.atan2(c.facing[1], c.facing[0])  # running up along his line
    if spy:
        spy(taker)
    e.rng.seed(draw)
    setpieces.deliver(e, taker)
    return e, setpieces.intended(c, option)


def test_the_delivery_is_struck_with_execution_error(monkeypatch):
    """Mutation caught: deliver() striking the intended velocity. Same state, same choice: only
    the execution draw differs, and the strike is never exactly the intention."""
    balls = []
    for draw in (1, 2):
        e, aim = struck(monkeypatch, 4, (100.0, 38.5), draw)
        balls.append(e.ball[3:6])
        assert any(abs(a - b) > 1e-6 for a, b in zip(e.ball[3:6], aim, strict=True))
    assert balls[0] != balls[1]


def test_a_delivery_across_the_body_carries_the_turn(monkeypatch):
    """Mutation caught: the taker turned to face the target before the strike. He runs up along
    the line to the penalty spot, so a ball to the near post is struck across his body."""
    seen = {}

    def spy(taker):
        original = taker.profile.kick_error

        def wrapped(skill, speed, pressure, fresh, weak, turn):
            seen["turn"] = turn
            return original(skill, speed, pressure, fresh, weak, turn)

        monkeypatch.setattr(taker.profile, "kick_error", wrapped)

    struck(monkeypatch, 4, (101.0, 30.0), 1, spy)
    assert abs(seen["turn"]) > 10.0


def test_the_taker_never_touches_his_own_corner():
    """Regression: the ball was placed inside the taker's body and deflected off him on 39 of 60
    corners. The struck ball must leave him without a contact."""
    for seed in range(20, 32):
        m = simulate(seed, 0.9, "corner")
        kick = next(ev for ev in m.events if ev["type"] == "pass")
        soon = [ev for ev in m.events if kick["frame"] < ev["frame"] <= kick["frame"] + 10]
        assert not any(ev["type"] == "deflection" and ev["player"] == kick["player"] for ev in soon), seed


def test_the_routine_holds_after_the_kick_until_the_ball_is_won_or_four_seconds_pass():
    """Mutations caught: SECOND_PHASE_S widened or dropped; the routine kept after a player wins
    the ball."""
    e = corner_engine(seed=6)
    run_until_kick(e)
    c = e.set_play
    e.possessor, e.restart = None, None
    e.t = c.delivered_at + 3.9  # S3: 4 s
    assert not setpieces.over(e)
    e.t += 0.2
    assert setpieces.over(e)
    e.t = c.delivered_at + 1.0
    e.give("a4")
    assert setpieces.over(e)
    e.shape_target(e.by_id["h4"])
    assert e.set_play is None


def test_scenario_corners_meet_the_data_contract(tmp_path):
    for seed in range(8):
        m = simulate(seed, 0.9, "corner")
        d = tmp_path / str(seed)
        d.mkdir()
        (d / "events.jsonl").write_text("".join(json.dumps(ev) + "\n" for ev in m.events))
        (d / "frames.jsonl").write_text("".join(json.dumps(f) + "\n" for f in m.frames))
        (d / "meta.json").write_text(json.dumps({"fps": FPS, "score": m.score, "roster": m.roster}))
        assert validate(d) == {}, seed


def test_scenario_mode_is_deterministic_and_unknown_scenarios_fail():
    a, b = simulate(2, 0.3, "corner"), simulate(2, 0.3, "corner")
    assert a.events == b.events and a.frames[-1] == b.frames[-1]
    assert a.events[0]["type"] == "out_of_play"
    with pytest.raises(ValueError):
        simulate(2, 0.1, "penalty_shootout")


# --- the Law 17 check in the validator ------------------------------------------------------------

ROSTER = [{"id": "hk", "team": "home", "role": "GK"}, {"id": "ak", "team": "away", "role": "GK"}]


def corner_clip(defender=(60.0, 40.0), ball_at=(104.6, 0.4), crossed_y=20.0, taker_team="home",
                out_team="away", intrude_at=None) -> dict:
    """The ball went out over the line the away keeper defends, off an away player; h1 places it
    and passes 10 m to h2 at frame 15. a1 stands at `defender`, or at `intrude_at` = (frame, x, y)."""
    place, strike = 10, 15
    sx, sy = ball_at
    ex, ey = sx - 6.0, sy + 8.0  # 10 m away
    frames = []
    for n in range(60):
        u = min(max((n - strike) / 25, 0.0), 1.0)
        ax, ay = defender
        if intrude_at and n == intrude_at[0]:
            ax, ay = intrude_at[1], intrude_at[2]
        frames.append({
            "frame": n, "t": n / FPS,
            "ball": {"x": sx + (ex - sx) * u, "y": sy + (ey - sy) * u, "z": 0.0},
            "possessor": "h1" if place <= n < strike else ("h2" if u == 1 else None),
            "players": [
                {"id": "h1", "team": "home", "x": sx, "y": sy},
                {"id": "h2", "team": "home", "x": ex, "y": ey},
                {"id": "hk", "team": "home", "x": 5.0, "y": 34.0},
                {"id": "a1", "team": "away", "x": ax, "y": ay},
                {"id": "ak", "team": "away", "x": 104.0, "y": 34.0},
            ],
        })
    events = [
        event("e1", 0, "out_of_play", out_team, x=105.0, y=crossed_y),
        event("e2", place, "set_piece", taker_team, "h1", x=min(sx, 105.0), y=sy),
        event("e3", strike, "pass", "home", "h1", "h2", x=min(sx, 105.0), y=sy, end_x=ex, end_y=ey,
              outcome="success", ball_speed_kmh=36.0),
    ]
    meta = {"fps": FPS, "score": {"home": 0, "away": 0}, "roster": ROSTER}
    return {"events": events, "frames": frames, "meta": meta}


@pytest.mark.parametrize("clip", [
    corner_clip(),
    corner_clip(defender=(105.0, 10.15)),  # exactly 9.15 m from the arc, along the goal line
    corner_clip(ball_at=(105.0 - 0.85, 0.6)),  # resting on the arc line: centre 1.04 m from the flag
    corner_clip(ball_at=(105.05, 0.3)),  # on the goal line itself
    corner_clip(intrude_at=(15, 102.0, 5.0)),  # moves in on the frame the ball is kicked
], ids=["legal", "at the distance", "on the arc line", "on the goal line", "moves in at the kick"])
def test_a_legal_corner_passes(tmp_path, clip):
    assert "L9 corner" not in run(tmp_path, clip)


@pytest.mark.parametrize("clip", [
    corner_clip(defender=(100.0, 5.0)),  # about 6 m from the arc throughout
    corner_clip(defender=(105.0, 10.1)),  # 5 cm inside the distance
    corner_clip(intrude_at=(12, 102.0, 5.0)),  # moves in between placing and the kick
    corner_clip(ball_at=(103.0, 1.5)),  # placed outside the arc
    corner_clip(ball_at=(100.0, 3.0)),  # placed 5.8 m from the flag, a mistaken "goal kick"
    corner_clip(ball_at=(105.5, 0.5)),  # behind the goal line, outside the field
    corner_clip(crossed_y=60.0),  # went out near the other corner
    corner_clip(taker_team="away"),  # given to the team that put it out
], ids=["inside", "5 cm inside", "moves in before the kick", "outside the arc", "far from the flag",
        "behind the line", "wrong corner", "wrong team"])
def test_a_breach_of_law_17_fails(tmp_path, clip):
    assert "L9 corner" in run(tmp_path, clip)


def test_the_ball_must_stay_where_it_was_placed_until_the_kick(tmp_path):
    clip = corner_clip()
    for f in clip["frames"][11:15]:  # carried 4 m out of the arc after placing, then crossed
        f["ball"]["x"] -= 3.0 * (f["frame"] - 10) / 4
    assert "L9 corner" in run(tmp_path, clip)


@pytest.mark.parametrize("clip, breach", [
    (None, True),  # the ball nudged 2 mm off its spot before the kick (built below)
    (corner_clip(ball_at=(104.15, 0.85)), True),  # centre 1.20 m from the flag: off the arc line
    (corner_clip(ball_at=(104.215, 0.785)), False),  # centre 1.11 m: still on the arc line
    (corner_clip(defender=(105.0, 10.149)), True),  # 1 mm inside the distance
], ids=["ball nudged 2 mm", "1.20 m from the flag", "1.11 m from the flag", "1 mm inside"])
def test_the_check_is_exact_to_the_rounding(tmp_path, clip, breach):
    """Mutations caught: the stationary tolerance, the ball radius and the rounding slack loosened.
    Each case sits just past (or just inside) the limit."""
    if clip is None:
        clip = corner_clip()
        for f in clip["frames"][11:15]:
            f["ball"]["x"] = round(f["ball"]["x"] - 0.002, 3)
    assert ("L9 corner" in run(tmp_path, clip)) is breach


def test_scenario_opens_from_open_play_by_that_goal_line():
    """Mutation caught: the opening left in the kick-off shape."""
    m = simulate(3, 0.05, "corner")
    first = m.frames[0]["players"]
    home_up = sum(p["x"] > 52.5 for p in first if p["team"] == "home" and p["id"] != "h1")
    away_back = sum(p["x"] > 70.0 for p in first if p["team"] == "away")
    assert home_up >= 6 and away_back >= 8


def test_a_keeper_out_of_place_at_the_exit_does_not_hide_the_corner(tmp_path):
    """Regression (audit 5): the defending team was the one whose keeper was nearest the line at
    that moment, so an attacking keeper up for a late corner (and the defending keeper off his
    line) turned a corner into a goal kick and skipped the Law 17 check. Over the clip, the away
    keeper defends x = 105."""
    clip = corner_clip(intrude_at=(12, 102.0, 5.0))  # a breach: inside 9.15 m before the kick
    for p in clip["frames"][0]["players"]:
        if p["id"] == "hk":
            p["x"] = 103.0
        if p["id"] == "ak":
            p["x"] = 90.0
    assert "L9 corner" in run(tmp_path, clip)


def test_a_new_ball_may_be_placed_when_the_clip_ends_before_the_restart(tmp_path):
    """Regression (corner report, seeds 51 and 132): the ball went out, the taker placed a new
    one in the corner area, and the clip ended before the corner was ready. The ball is out of
    play until the restart (Law 9), so the placement is not a 4 m jump in play. A jump after a
    restart still fails (the existing P3 cases)."""
    clip = corner_clip()
    clip["events"] = clip["events"][:1]  # out of play, then the clip ends
    for f in clip["frames"][30:]:
        f["ball"].update(x=104.5, y=0.5)  # placed; before it the ball lay where corner_clip put it
    for f in clip["frames"][:30]:
        f["ball"].update(x=108.0, y=4.0)  # by the boards
        f["possessor"] = None
    assert "P3 ball speed" not in run(tmp_path, clip)


def test_corners_cannot_be_checked_without_keepers(tmp_path):
    clip = corner_clip(defender=(100.0, 5.0))
    clip["meta"]["roster"] = []
    assert "L9 corner" in run(tmp_path, clip)  # reported, never silently skipped


def goal_clip(touches, scorer, team="home", holder="h1", receiver_has_it=None, path=None) -> dict:
    """Shaped like engine output. h1 has the ball for 5 frames and strikes it at frame 5; it moves
    0.6 m a frame toward the home side's attacking goal and crosses the line during frame 30. As
    the engine writes it, the goal frame already shows the kick-off reset: the ball on the centre
    spot with the conceding team's striker (a9), and a kick-off event after the goal.
    `touches` are extra events (frame, type, player, team, outcome); `receiver_has_it` =
    (player, from_frame) gives that player the ball; `path(n)` overrides the ball's (x, y, z)."""
    conceding = "away" if team == "home" else "home"
    frames = []
    for n in range(31):
        u = min(max((n - 5) / 25, 0.0), 1.0)
        ball = path(n) if path else (90.0 + 15.0 * u, 34.0, 0.0)
        poss = holder if n < 5 else None
        if receiver_has_it and n >= receiver_has_it[1]:
            poss = receiver_has_it[0]
        a9 = (65.0, 34.0)
        if n == 30:  # the kick-off reset
            ball, poss, a9 = (52.5, 34.0, 0.0), "a9", (52.5, 34.0)
        frames.append({"frame": n, "t": n / FPS, "possessor": poss,
                       "ball": {"x": ball[0], "y": ball[1], "z": ball[2]},
                       "players": [{"id": "h1", "team": "home", "x": 90.0, "y": 34.0},
                                   {"id": "h2", "team": "home", "x": 100.0, "y": 36.0},
                                   {"id": "hk", "team": "home", "x": 5.0, "y": 34.0},
                                   {"id": "a1", "team": "away", "x": 98.0, "y": 32.0},
                                   {"id": "a9", "team": "away", "x": a9[0], "y": a9[1]},
                                   {"id": "ak", "team": "away", "x": 104.0, "y": 34.0}]})
    events = [event("e0", 0, "kickoff", "home", "h1", x=90.0, y=34.0)]
    for k, (f, kind, pid, tm, outcome) in enumerate(touches):
        events.append(event(f"t{k}", f, kind, tm, pid, x=min(105.0, 90.0 + 0.6 * max(f - 5, 0)), y=34.0,
                            outcome=outcome))
    events.append(event("g1", 30, "goal", team, scorer, x=105.0, y=34.0))
    events.append(event("k1", 30, "kickoff", conceding, "a9", x=52.5, y=34.0))
    score = {"home": int(team == "home"), "away": int(team == "away")}
    return {"events": events, "frames": frames, "meta": {"fps": FPS, "score": score, "roster": ROSTER}}


SHOT = (5, "shot", "h1", "home", "goal")
C8_LEGAL = {
    "shot straight in": goal_clip([SHOT], "h1"),
    "shot deflected in by a defender": goal_clip([SHOT, (20, "deflection", "a1", "away", None)], "h1"),
    "cross deflected in by an attacker": goal_clip([(5, "pass", "h1", "home", "fail"),
                                                   (20, "deflection", "h2", "home", None)], "h2"),
    "corner straight in": goal_clip([(5, "pass", "h1", "home", "fail")], "h1"),
    "own goal off a defender": goal_clip([(5, "pass", "h1", "home", "fail"),
                                          (20, "deflection", "a1", "away", None)], None),
    "same frame: an attacker deflects, then a defender takes it into his own net": goal_clip(
        [(5, "pass", "h1", "home", "fail"), (29, "deflection", "h2", "home", None)], None,
        receiver_has_it=("a1", 29)),
    "the shot's team-mate deflects it in": goal_clip([SHOT, (20, "deflection", "h2", "home", None)], "h2"),
}
C8_WRONG = {
    "shooter credited after a team-mate's touch": goal_clip(
        [SHOT, (20, "deflection", "h2", "home", None)], "h1"),
    "shooter credited after a defender then a team-mate": goal_clip(
        [SHOT, (15, "deflection", "a1", "away", None), (20, "deflection", "h2", "home", None)], "h1"),
    "passer credited after the receiver controls it": goal_clip(
        [(5, "pass", "h1", "home", "success")], "h1", receiver_has_it=("h2", 25)),
    "passer credited after a defender wins it": goal_clip(
        [(5, "pass", "h1", "home", "fail"), (20, "possession_change", "a1", "away", None)], "h1"),
    "own goal but an attacker touched it last": goal_clip(
        [(5, "pass", "h1", "home", "fail"), (20, "deflection", "h2", "home", None)], None),
    "last touch a shot recorded as saved": goal_clip([(5, "shot", "h1", "home", "on_target")], "h1"),
    "goal for a player of the other team": goal_clip([SHOT], "a1", team="home"),
    "a defender who touched it last credited with the attackers' goal": goal_clip(
        [(5, "pass", "h1", "home", "fail"), (20, "deflection", "a1", "away", None)], "a1", team="home"),
    "shooter credited after the keeper held it": goal_clip(
        [SHOT], "h1", receiver_has_it=("ak", 20)),
    "own goal recorded, but the shot it came off is recorded as the goal": goal_clip(
        [SHOT, (20, "deflection", "a1", "away", None)], None),
    "same frame: a defender deflects, then the scorer's team-mate controls": goal_clip(
        [SHOT, (29, "deflection", "a1", "away", None)], "h1", receiver_has_it=("h2", 29)),
}


@pytest.mark.parametrize("name", C8_LEGAL)
def test_c8_credits_the_right_scorer(tmp_path, name):
    assert "C8 event order" not in run(tmp_path, C8_LEGAL[name])


@pytest.mark.parametrize("name", C8_WRONG)
def test_c8_rejects_a_wrong_scorer(tmp_path, name):
    assert "C8 event order" in run(tmp_path, C8_WRONG[name])


def test_a_shot_cannot_score_twice(tmp_path):
    """The same shot reused for a second goal after the kick-off fails."""
    clip = goal_clip([SHOT], "h1")
    clip["events"].insert(-2, event("k2", 29, "kickoff", "away", "a9", x=52.5, y=34.0))
    assert "C8 event order" in run(tmp_path, clip)


L6_WRONG = {
    "wide of the post": lambda n: (90.0 + 0.6 * max(n - 5, 0), 34.0 + 0.215 * max(n - 5, 0), 0.0),
    "over the bar": lambda n: (90.0 + 0.6 * max(n - 5, 0), 34.0, 0.16 * max(n - 5, 0)),
    "already deep in the net": lambda n: (91.5 + 0.6 * max(n - 5, 0), 34.0, 0.0),
    "3 m short of the line the frame before": lambda n: (87.0 + 0.6 * max(n - 5, 0), 34.0, 0.0),
    # just wide: crosses 0.15 m beyond the derived slack outside the post
    "just wide of the post": lambda n: (90.0 + 0.6 * max(n - 5, 0), 34.0 + 0.1505 * max(n - 5, 0), 0.0),
    "moving away from goal": lambda n: (105.0 - 0.6 * max(n - 5, 0) / 25 * 2, 34.0, 0.0) if n > 27 else
    (90.0 + 0.6 * max(n - 5, 0), 34.0, 0.0),
}


@pytest.mark.parametrize("name", L6_WRONG)
def test_l6_rejects_a_goal_that_did_not_cross_inside_the_mouth(tmp_path, name):
    """Mutations caught: the post, bar or line conditions of L6 dropped or loosened."""
    assert "L6 goal" in run(tmp_path, goal_clip([SHOT], "h1", path=L6_WRONG[name]))


def test_l6_rejects_a_goal_touched_in_the_last_frame_from_well_wide(tmp_path):
    """Regression (audit 5): with a touch in the last frame only the distance to the goal line
    was checked, so a ball 2 m wide of the post that a defender touched still "scored". In one
    frame it can travel at most 1.6 m, so it must already be that close to the mouth."""
    wide = lambda n: (90.0 + 0.6 * max(n - 5, 0), 34.0 + 0.25 * max(n - 5, 0), 0.0)  # noqa: E731
    clip = goal_clip([SHOT, (29, "deflection", "a1", "away", None)], "h1", path=wide)
    assert "L6 goal" in run(tmp_path, clip)


def test_l6_accepts_a_goal_just_inside_the_post_and_under_the_bar(tmp_path):
    inside = lambda n: (90.0 + 0.6 * max(n - 5, 0), 34.0 + 0.14 * max(n - 5, 0),  # noqa: E731
                        min(1.7, 0.068 * max(n - 5, 0)))
    assert "L6 goal" not in run(tmp_path, goal_clip([SHOT], "h1", path=inside))


def test_l6_reports_a_goal_it_cannot_check():
    """A gap in the frames already fails C2 and stops the validator; called directly, L6 reports
    the missing frame instead of passing it."""
    from ninety.validate import goal_crossing_problem
    clip = goal_clip([SHOT], "h1")
    by_frame = {f["frame"]: f for f in clip["frames"] if f["frame"] != 29}
    goal = next(e for e in clip["events"] if e["type"] == "goal")
    assert goal_crossing_problem(goal, clip["events"], by_frame, FPS, {"away": 105.0}) is not None


def test_l6_judges_the_goal_the_conceding_keeper_defends(tmp_path):
    """A ball crossing the home side's own goal line is not a home goal."""
    own_end = lambda n: (15.0 - 0.6 * max(n - 5, 0), 34.0, 0.0)  # noqa: E731
    assert "L6 goal" in run(tmp_path, goal_clip([SHOT], "h1", path=own_end))


def test_real_engine_goals_are_credited_and_relabelling_them_fails(tmp_path):
    """Engine output, not a fixture, and no pinned seed (lesson 19): the first three goals in the
    scenario corners each meet the contract, and giving one to the wrong player (or to nobody)
    fails C8. Which seeds score moves with the engine and even with the Python version (CI found
    2 goals in the 32 seeds that gave 4 locally), so it scans until it has three."""
    goals = 0
    for seed in range(200):
        if goals == 3:
            break
        m = simulate(seed, 0.5, "corner")
        goal = next((e for e in m.events if e["type"] == "goal"), None)
        if goal is None:
            continue
        goals += 1
        meta = {"fps": FPS, "score": m.score, "roster": m.roster}
        base = {"events": m.events, "frames": m.frames, "meta": meta}
        (tmp_path / f"ok{seed}").mkdir()
        assert run(tmp_path / f"ok{seed}", base) == {}, seed
        scorer = goal["player"]
        keeper = next(r["id"] for r in m.roster if r["team"] == goal["team"] and r.get("role") == "GK")
        goal["player"] = None if scorer is not None else keeper  # an own goal, or their own keeper
        (tmp_path / f"bad{seed}").mkdir()
        assert "C8 event order" in run(tmp_path / f"bad{seed}", base), seed
    assert goals == 3  # about 1 corner in 15 scores, so 200 seeds always find three


def test_off_an_attacker_it_is_a_goal_kick_not_a_corner(tmp_path):
    clip = corner_clip(defender=(100.0, 5.0), out_team="home")
    assert "L9 corner" not in run(tmp_path, clip)


def test_a_throw_in_near_a_corner_is_not_judged_as_a_corner(tmp_path):
    """Over the touchline close to the flag: a throw-in, where opponents need only 2 m."""
    clip = corner_clip(defender=(100.0, 5.0))
    clip["events"][0].update(x=103.0, y=0.0)
    assert "L9 corner" not in run(tmp_path, clip)


def test_a_team_mates_touch_ends_the_shot_in_the_engine():
    """Mutation caught: a team-mate's deflection leaving the shot in flight, so the shooter would
    be credited with a goal the team-mate put in (C8)."""
    e = Engine(1)
    shooter, mate, defender = e.by_id["h10"], e.by_id["h9"], e.by_id["a4"]
    shooter.x, shooter.y, shooter.heading = 88.0, 34.0, 0.0
    e.give(shooter.id)
    e.ball = (88.37, 34.0, 0.0, 0.0, 0.0, 0.0)
    e.shoot(shooter)
    shot = e.kicked
    assert shot and shot["type"] == "shot"
    e.touched(defender, 95.0, 34.0, controls=False)  # a block leaves the shot in flight
    assert e.kicked is shot
    e.touched(mate, 98.0, 34.0, controls=False)  # a team-mate's touch ends it
    assert e.kicked is None and shot["outcome"] in ("blocked", "on_target", "off_target")
