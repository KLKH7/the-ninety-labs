"""Corners (docs/GROUNDING.md S rows and L9): the routine places players and never decides an
outcome; the corner is taken when the teams are ready and the Law's distance is kept, not on a
timer; the taker never touches his own corner; and the Law 17 check in the validator passes
legal corners and fails each planted breach. Each test names the mutation it must catch."""

import json
import math

import pytest
from test_validate import FPS, event, run

from ninety.sim import setpieces
from ninety.sim.engine import PENALTY_DEPTH, PENALTY_HALF_WIDTH, Engine, simulate
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
    """Put every player on his spot, standing still, and the taker at his run-up."""
    c = e.set_play
    for p in e.players:
        spot = c.run_up if p.id == c.taker else setpieces.target(e, p)
        if spot:
            p.x, p.y, p.vx, p.vy = spot[0], spot[1], 0.0, 0.0
    for p in e.players:  # markers depend on where their attackers now stand
        if p.id in c.marks or p.id in c.rest_marks:
            p.x, p.y = setpieces.target(e, p)


# --- the routine -------------------------------------------------------------------------------

def test_every_player_has_a_place_and_the_best_crosser_takes_it():
    e = corner_engine()
    c = e.set_play
    eligible = [p for p in e.players if p.team == "home" and p.role in setpieces.TAKER_ROLES]
    assert c.taker == max(eligible, key=lambda p: p.profile["crossing"]).id
    for p in e.players:
        placed = p.id in c.targets or p.id in c.marks or p.id in c.rest_marks
        assert p.id == c.taker or placed, p.id
    box = [pid for pid, z in c.zones.items() if z != "edge"]
    assert len(box) >= 4 and set(c.marks.values()) == set(box)  # each attacker in the box is marked


def test_rest_defence_stands_goal_side_of_the_counter_attackers():
    """Mutation caught: rest defenders placed upfield of the players they guard."""
    e = corner_engine()
    settle_everyone(e)
    c = e.set_play
    assert c.rest_marks
    for rest_id, counter_id in c.rest_marks.items():
        rest, counter = e.by_id[rest_id], e.by_id[counter_id]
        assert rest.x < counter.x  # home defends x = 0: nearer his own goal than the forward


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


def test_not_ready_until_the_ball_is_placed_and_everyone_is_set():
    """Mutations caught: PLACE_S = 0; ready() ignoring the other players; ready() ignoring the
    Law's distance."""
    e = corner_engine()
    settle_everyone(e)
    assert not setpieces.ready(e)  # the taker has only just reached the ball
    e.t += setpieces.PLACE_S - 0.1
    assert not setpieces.ready(e)  # still placing it
    e.t += 0.2
    assert setpieces.ready(e)
    runner = e.by_id[next(iter(e.set_play.zones))]
    runner.x, runner.vx = runner.x - 10.0, 5.0  # far from his spot and still running to it
    assert not setpieces.ready(e)
    runner.vx = 0.0  # stopped short (someone in the way): he does not hold the corner up
    assert setpieces.ready(e)
    intruder = e.by_id[e.set_play.short_block]
    intruder.x, intruder.y = 100.0, 4.0  # about 6 m from the flag
    assert not setpieces.ready(e)


def test_no_drawn_delay_and_the_taker_settles_it_like_any_carrier():
    e = corner_engine()
    assert e.restart.ready_at == math.inf
    taker = e.set_play.taker
    kick = run_until_kick(e)
    placed = next(ev for ev in e.match.events if ev["type"] == "set_piece")
    assert kick["player"] == placed["player"] == taker
    settle = kick["t"] - placed["t"]
    assert 0.3 - 1e-9 <= settle <= 0.6 + 1 / FPS + 1e-9  # D5: the first touch, not a drawn wait


def test_the_box_is_crowded_and_the_law_is_kept_at_every_frame_to_the_kick():
    e = corner_engine(seed=5)
    run_until_kick(e)
    placed = next(ev for ev in e.match.events if ev["type"] == "set_piece")["frame"]
    for f in e.match.frames[placed:-1]:
        for p in f["players"]:
            if p["team"] == "away":
                assert math.hypot(p["x"] - 105.0, p["y"]) >= setpieces.LAW_DISTANCE_M
    f = e.match.frames[-1]
    assert sum(in_box(p["x"], p["y"], 105.0) for p in f["players"] if p["team"] == "home") >= 4
    assert sum(in_box(p["x"], p["y"], 105.0) for p in f["players"] if p["team"] == "away") >= 7


def test_the_delivery_is_struck_with_execution_error(monkeypatch):
    """Mutation caught: deliver() striking the intended velocity. Same state, same choice: only
    the execution draw differs, and the strike is never exactly the intention."""
    target = (100.0, 38.5)
    monkeypatch.setattr(setpieces, "choose_delivery", lambda engine, taker: target)
    struck = []
    for draw in (1, 2):
        e = corner_engine(seed=4)
        settle_everyone(e)
        e.t += setpieces.PLACE_S + 0.1
        tick(e)  # placed and given to the taker
        taker = e.by_id[e.set_play.taker]
        e.rng.seed(draw)
        setpieces.deliver(e, taker)
        aim = setpieces.intended(e.set_play, *target)
        struck.append(e.ball[3:6])
        assert any(abs(a - b) > 1e-6 for a, b in zip(e.ball[3:6], aim, strict=True))
    assert struck[0] != struck[1]


def test_a_delivery_across_the_body_carries_the_turn(monkeypatch):
    """Mutation caught: the taker turned to face the target before the strike. He stands behind
    the ball facing the penalty spot, so a ball to the near post is struck across his body."""
    target = (101.0, 30.0)  # near post, well off his line of sight from the flag at y = 0
    monkeypatch.setattr(setpieces, "choose_delivery", lambda engine, taker: target)
    seen = {}
    e = corner_engine(seed=4)
    settle_everyone(e)
    e.t += setpieces.PLACE_S + 0.1
    tick(e)
    taker = e.by_id[e.set_play.taker]
    original = taker.profile.kick_error

    def spy(skill, speed, pressure, fresh, weak, turn):
        seen["turn"] = turn
        return original(skill, speed, pressure, fresh, weak, turn)

    monkeypatch.setattr(taker.profile, "kick_error", spy)
    setpieces.face_ball(e, taker)
    setpieces.deliver(e, taker)
    assert abs(seen["turn"]) > 10.0


def test_the_taker_never_touches_his_own_corner():
    """Regression: the ball was placed inside the taker's body and deflected off him on 39 of 60
    corners. The struck ball must leave him without a contact."""
    for seed in range(20, 32):
        m = simulate(seed, 0.9, "corner")
        kick = next(ev for ev in m.events if ev["type"] == "pass")
        soon = [ev for ev in m.events if kick["frame"] < ev["frame"] <= kick["frame"] + 10]
        assert not any(ev["type"] == "deflection" and ev["player"] == kick["player"] for ev in soon), seed


def test_the_routine_ends_when_someone_wins_the_ball():
    e = corner_engine(seed=6)
    run_until_kick(e)
    assert e.set_play is not None
    e.give("a4")
    assert setpieces.target(e, e.by_id["h4"]) is None and e.set_play is None


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
    (None, True),  # the ball nudged 1 cm off its spot before the kick (built below)
    (corner_clip(ball_at=(104.15, 0.85)), True),  # centre 1.20 m from the flag: off the arc line
    (corner_clip(ball_at=(104.215, 0.785)), False),  # centre 1.11 m: still on the arc line
    (corner_clip(defender=(105.0, 10.149)), True),  # 1 mm inside the distance
], ids=["ball nudged 1 cm", "1.20 m from the flag", "1.11 m from the flag", "1 mm inside"])
def test_the_check_is_exact_to_the_rounding(tmp_path, clip, breach):
    """Mutations caught: the stationary tolerance, the ball radius and the rounding slack loosened.
    Each case sits just past (or just inside) the limit."""
    if clip is None:
        clip = corner_clip()
        for f in clip["frames"][11:15]:
            f["ball"]["x"] -= 0.01
    assert ("L9 corner" in run(tmp_path, clip)) is breach


def test_scenario_opens_from_open_play_by_that_goal_line():
    """Mutation caught: the opening left in the kick-off shape."""
    m = simulate(3, 0.05, "corner")
    first = m.frames[0]["players"]
    home_up = sum(p["x"] > 52.5 for p in first if p["team"] == "home" and p["id"] != "h1")
    away_back = sum(p["x"] > 70.0 for p in first if p["team"] == "away")
    assert home_up >= 6 and away_back >= 8


def test_corners_cannot_be_checked_without_keepers(tmp_path):
    clip = corner_clip(defender=(100.0, 5.0))
    clip["meta"]["roster"] = []
    assert "L9 corner" in run(tmp_path, clip)  # reported, never silently skipped


def goal_clip(touches, scorer, team="home", holder="h1", receiver_has_it=None) -> dict:
    """h1 has the ball for 5 frames and strikes it at frame 5 toward goal; it crosses the line at
    frame 30. `touches` are extra events (frame, type, player, team, outcome) on the way in.
    `receiver_has_it` = (player, from_frame): a player controls the ball from that frame."""
    frames = []
    for n in range(31):
        u = min(max((n - 5) / 25, 0.0), 1.0)
        poss = holder if n < 5 else None
        if receiver_has_it and n >= receiver_has_it[1]:
            poss = receiver_has_it[0]
        frames.append({"frame": n, "t": n / FPS, "possessor": poss,
                       "ball": {"x": 90.0 + 15.0 * u, "y": 34.0, "z": 0.0},
                       "players": [{"id": "h1", "team": "home", "x": 90.0, "y": 34.0},
                                   {"id": "h2", "team": "home", "x": 100.0, "y": 36.0},
                                   {"id": "hk", "team": "home", "x": 5.0, "y": 34.0},
                                   {"id": "a1", "team": "away", "x": 98.0, "y": 32.0},
                                   {"id": "ak", "team": "away", "x": 104.0, "y": 34.0}]})
    events = [event("e0", 0, "kickoff", "home", "h1", x=90.0, y=34.0)]
    for k, (f, kind, pid, tm, outcome) in enumerate(touches):
        events.append(event(f"t{k}", f, kind, tm, pid, x=90.0 + 15.0 * (f - 5) / 25, y=34.0, outcome=outcome))
    events.append(event("g1", 30, "goal", team, scorer, x=105.0, y=34.0))
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
    "goal for a player of the other team": goal_clip([SHOT], "a1"),
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
    clip["events"].insert(-1, event("k2", 29, "kickoff", "away", "a1", x=52.5, y=34.0))
    assert "C8 event order" in run(tmp_path, clip)


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
