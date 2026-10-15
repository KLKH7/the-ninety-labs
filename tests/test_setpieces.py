"""Corners (docs/GROUNDING.md S rows and L9): the routine places players and never decides an
outcome; the corner is taken when the teams are ready, not on a timer; and the Law 17 check in
the validator passes a legal corner and fails each planted breach."""

import math

import pytest
from test_validate import FPS, event, run

from ninety.sim import setpieces
from ninety.sim.engine import PENALTY_DEPTH, PENALTY_HALF_WIDTH, Engine, simulate


def corner_engine(seed: int = 3, side: float = 0.0) -> Engine:
    e = Engine(seed)
    e.ball = (105.0, side, 0.0, 0.0, 0.0, 0.0)
    e.stop("corner", "home", (105.0, side))
    return e


def in_box(x: float, y: float, line: float) -> bool:
    return abs(x - line) <= PENALTY_DEPTH and abs(y - 34.0) <= PENALTY_HALF_WIDTH


def run_until_kick(e: Engine, limit_s: float = 60.0) -> dict:
    for _ in range(int(limit_s * FPS)):
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
        kicks = [ev for ev in e.match.events if ev["type"] == "pass"]
        if kicks:
            return kicks[0]
    raise AssertionError("the corner was never taken")


# --- the routine -------------------------------------------------------------------------------

def test_every_player_has_a_place_and_the_best_crosser_takes_it():
    e = corner_engine()
    c = e.set_play
    home = [p for p in e.players if p.team == "home"]
    eligible = [p for p in home if p.role in setpieces.TAKER_ROLES]
    assert c.taker == max(eligible, key=lambda p: p.profile["crossing"]).id
    for p in e.players:
        assert p.id == c.taker or p.id in c.targets or p.id in c.marks, p.id
    box = [pid for pid, z in c.zones.items() if z != "edge"]
    assert len(box) >= 4  # attackers in the box
    assert set(c.marks.values()) == set(box)  # each of them is marked


def test_defenders_keep_their_distance_until_the_kick():
    e = corner_engine(side=68.0)
    for p in e.players:
        if p.team == "away":
            spot = setpieces.target(e, p)
            if spot:
                assert math.hypot(spot[0] - 105.0, spot[1] - 68.0) >= setpieces.STAND_OFF_M - 1e-9
    # A spot inside the distance is pushed out along the line from the flag.
    x, y = setpieces.keep_off(e.set_play, 100.0, 64.0)
    assert math.isclose(math.hypot(x - 105.0, y - 68.0), setpieces.STAND_OFF_M)


def test_the_corner_waits_for_the_teams_not_a_timer():
    e = corner_engine()
    assert e.restart.ready_at == math.inf  # no drawn delay
    assert not setpieces.ready(e)  # the taker is far from the flag
    taker = e.set_play.taker
    kick = run_until_kick(e)
    placed = next(ev for ev in e.match.events if ev["type"] == "set_piece")
    assert kick["player"] == placed["player"] == taker
    assert kick["t"] - placed["t"] >= 0.3  # the taker settles the ball before striking it
    # Taken once everyone had reached his spot or stopped moving toward it, never before.
    assert e.set_play.placed_at is not None and placed["t"] - e.set_play.placed_at >= setpieces.PLACE_S - 1e-9


def test_at_the_kick_the_box_is_crowded_and_the_law_is_kept():
    e = corner_engine(seed=5)
    run_until_kick(e)
    f = e.match.frames[-1]
    attackers = sum(in_box(p["x"], p["y"], 105.0) for p in f["players"] if p["team"] == "home")
    defenders = sum(in_box(p["x"], p["y"], 105.0) for p in f["players"] if p["team"] == "away")
    assert attackers >= 4 and defenders >= 7
    for p in f["players"]:
        if p["team"] == "away":
            assert math.hypot(p["x"] - 105.0, p["y"]) - 1.0 >= 9.15


def test_the_delivery_is_struck_with_error_not_placed():
    """The same choice, struck by the same taker from two random streams, lands differently:
    where the ball goes is physics and execution error, never set to the target."""
    landed = set()
    for seed in (11, 12):
        e = corner_engine(seed=4)
        e.rng.seed(seed)
        run_until_kick(e)
        landed.add(tuple(round(v, 3) for v in e.ball[3:6]))
    assert len(landed) == 2


def test_the_routine_ends_when_someone_wins_the_ball():
    e = corner_engine(seed=6)
    run_until_kick(e)
    assert e.set_play is not None
    e.give(e.by_id["a4"].id)
    assert setpieces.target(e, e.by_id["h4"]) is None and e.set_play is None


def test_scenario_mode_is_deterministic_and_unknown_scenarios_fail():
    a, b = simulate(2, 0.3, "corner"), simulate(2, 0.3, "corner")
    assert a.events == b.events and a.frames[-1] == b.frames[-1]
    assert a.events[0]["type"] == "out_of_play"
    with pytest.raises(ValueError):
        simulate(2, 0.1, "penalty_shootout")


# --- the Law 17 check in the validator ------------------------------------------------------------

def corner_clip(defender=(60.0, 40.0), ball_at=(104.6, 0.4), crossed_y=20.0) -> dict:
    """The ball went out over the home side's goal line; h1 places it in the corner arc and
    passes 10 m to h2 at frame 15. a1 stands where told."""
    place, strike = 10, 15
    sx, sy = ball_at
    ex, ey = sx - 6.0, sy + 8.0  # 10 m away
    frames = []
    for n in range(60):
        u = min(max((n - strike) / 25, 0.0), 1.0)
        frames.append({
            "frame": n, "t": n / FPS,
            "ball": {"x": sx + (ex - sx) * u, "y": sy + (ey - sy) * u, "z": 0.0},
            "possessor": "h1" if place <= n < strike else ("h2" if u == 1 else None),
            "players": [
                {"id": "h1", "team": "home", "x": sx, "y": sy},
                {"id": "h2", "team": "home", "x": ex, "y": ey},
                {"id": "a1", "team": "away", "x": defender[0], "y": defender[1]},
            ],
        })
    events = [
        event("e1", 0, "out_of_play", "away", x=105.0, y=crossed_y),
        event("e2", place, "set_piece", "home", "h1", x=sx, y=sy),
        event("e3", strike, "pass", "home", "h1", "h2", x=sx, y=sy, end_x=ex, end_y=ey,
              outcome="success", ball_speed_kmh=36.0),
    ]
    return {"events": events, "frames": frames, "meta": {"fps": FPS, "score": {"home": 0, "away": 0}}}


def test_a_legal_corner_passes(tmp_path):
    assert run(tmp_path, corner_clip()) == {}


def test_a_defender_at_the_limit_passes(tmp_path):
    # 9.15 m from the arc: 10.15 m from the corner, along the goal line.
    assert run(tmp_path, corner_clip(defender=(105.0, 10.15))) == {}


@pytest.mark.parametrize("clip", [
    corner_clip(defender=(100.0, 5.0)),  # about 6 m from the arc
    corner_clip(defender=(105.0, 10.1)),  # 5 cm inside the distance
    corner_clip(ball_at=(103.0, 1.5)),  # placed outside the arc
    corner_clip(crossed_y=60.0),  # went out near the other corner
])
def test_a_breach_of_law_17_fails(tmp_path, clip):
    assert "L9 corner" in run(tmp_path, clip)


def test_a_throw_in_near_a_corner_is_not_judged_as_a_corner(tmp_path):
    """Over the touchline close to the flag: a throw-in, where opponents need only 2 m."""
    clip = corner_clip(defender=(100.0, 5.0))
    clip["events"][0].update(x=103.0, y=0.0)  # crossed the touchline, not the goal line
    assert "L9 corner" not in run(tmp_path, clip)
