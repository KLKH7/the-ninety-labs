"""The running-patterns report (docs/GROUNDING.md, R2): distance split by whether the ball is in play."""

import math
from types import SimpleNamespace

from ninety.sim import patterns
from ninety.sim.engine import FPS, Engine


def frame(n: int, x: float) -> dict:
    return {"frame": n, "t": n / FPS, "possessor": None,
            "players": [{"id": "h9", "x": x, "y": 30.0}, {"id": "a1", "x": 5.0, "y": 34.0}]}


def test_distance_while_the_ball_is_out_is_split_from_the_rest():
    # The striker moves 0.04 m a frame (1 m/s) while the ball is in play and 0.10 m a frame
    # while a restart waits; the keeper stands. Frames 4 to 6 are dead, and a step counts in the
    # state of the frame it moves into.
    xs = [50.0]
    for n in range(1, 10):
        xs.append(xs[-1] + (0.10 if 4 <= n <= 6 else 0.04))
    m = SimpleNamespace(roster=[{"id": "h9", "role": "ST", "team": "home"},
                                {"id": "a1", "role": "GK", "team": "away"}],
                        events=[], frames=[frame(n, x) for n, x in enumerate(xs)])
    minutes = len(xs) / FPS / 60
    out = patterns.tally(m, {4, 5, 6}, minutes)
    (row,) = out["groups"]["centre-forward"]
    scale = 90 / minutes / 1000
    assert math.isclose(row["out_km"], 3 * 0.10 * scale)
    assert math.isclose(row["km"] - row["out_km"], 6 * 0.04 * scale)
    assert math.isclose(out["in_play_min"], 6 / FPS / 60 * 90 / minutes)


def test_the_report_plays_the_same_match_as_the_engine():
    engine, _ = patterns.run(7, 0.5)
    other = Engine(7).run(0.5)
    assert engine.match.frames == other.frames and engine.match.events == other.events


def test_out_of_play_runs_from_the_stoppage_to_the_restart():
    # Seed 7's first minute holds balls going out and restarts taken; the test says so (lesson 41),
    # and checks a goal or foul the same way if the draw holds one. The ball is out from the frame
    # play stops until the frame the restart is taken, which is in play, and in play everywhere
    # between a restart and the next stoppage.
    engine, dead = patterns.run(7, 1)
    events = sorted((e["frame"], e["type"]) for e in engine.match.events
                    if e["type"] in ("out_of_play", "foul", "goal", "set_piece"))
    kinds = {k for _, k in events}
    assert {"out_of_play", "set_piece"} <= kinds
    assert 0 in dead, "the match starts with the kick-off still to be taken"
    for (f, kind), nxt in zip(events, events[1:] + [(len(engine.match.frames), None)], strict=True):
        if kind == "set_piece":
            assert f - 1 in dead and f not in dead
            assert not dead & set(range(f, nxt[0])), "in play between a restart and the next stoppage"
        else:
            assert f in dead


def test_the_split_table_reads_pace_over_the_minutes_in_each_state():
    rows = [{"km": 9.0, "out_km": 1.5}, {"km": 7.0, "out_km": 0.5}]  # two players per position
    result = {"in_play_min": 60.0, "groups": dict.fromkeys(patterns.PUBLISHED_KM, rows)}
    table = "\n".join(patterns.split_table([result]))
    # in play 7.0 km over 60 minutes, out of play 1.0 km over the other 30
    assert "| centre-back | 7.0 | 117 | 1.0 | 33 |" in table
    assert "| all outfield | 7.0 | 117 | 1.0 | 33 |" in table
    assert f"| {patterns.PUBLISHED_IN_PLAY_KM:.1f} | 149 | 2.8 | 65 |" in table
