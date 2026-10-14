import json
from collections import Counter
from pathlib import Path

import pytest
from jsonschema import validate

from ninety.sim import realism
from ninety.sim.engine import FPS, HALF_S, PITCH_X, PITCH_Y, SPRINT_MS, simulate

ROOT = Path(__file__).resolve().parent.parent
EVENT_SCHEMA = json.loads((ROOT / "schemas/match_event.schema.json").read_text())
FRAME_SCHEMA = json.loads((ROOT / "schemas/frame.schema.json").read_text())
RATE_SEEDS = [11, 12, 13]


@pytest.fixture(scope="module")
def full_matches():
    """Three 90-minute matches, measured in parallel."""
    return realism.run(RATE_SEEDS)


def test_deterministic_for_a_seed():
    a, b = simulate(3, 2), simulate(3, 2)
    assert a.events == b.events
    assert a.frames[-1] == b.frames[-1]


def test_frames_cover_the_clock_and_stay_on_the_pitch():
    m = simulate(5, 4)
    assert len(m.frames) == 4 * 60 * FPS
    for fr in m.frames[::25]:
        assert len(fr["players"]) == 22
        # the ball may run a little past a line before play stops
        assert -3 <= fr["ball"]["x"] <= PITCH_X + 3 and -3 <= fr["ball"]["y"] <= PITCH_Y + 3


def test_events_match_schema():
    m = simulate(9, 12)
    assert {"set_piece", "out_of_play"} <= {e["type"] for e in m.events}
    for ev in m.events:
        validate(ev, EVENT_SCHEMA)
    for fr in m.frames[::250]:
        validate(fr, FRAME_SCHEMA)


def test_every_pass_gets_an_outcome():
    m = simulate(4, 10)
    passes = [e for e in m.events if e["type"] == "pass"]
    unresolved = [e for e in passes if e["outcome"] is None]
    assert len(unresolved) <= 1  # only a pass still travelling when the clock stops
    for e in passes:
        if e["outcome"] == "success":
            assert e["receiver"] and e["receiver"][0] == e["player"][0] and e["end_x"] is not None


def test_teams_change_ends_at_half_time():
    m = simulate(21, 50)
    kickoffs = [e for e in m.events if e["type"] == "kickoff" and e["t"] >= HALF_S]
    assert kickoffs and kickoffs[0]["team"] == "away" and kickoffs[0]["period"] == 2
    assert all(e["period"] == (1 if e["t"] < HALF_S else 2) for e in m.events)
    for e in m.events:
        if e["type"] == "shot" and e["outcome"] != "blocked":
            attacks_right = (e["team"] == "home") == (e["period"] == 1)
            assert (e["end_x"] > PITCH_X / 2) == attacks_right, e


def test_nothing_teleports_and_players_sprint(full_matches):
    for r in full_matches:
        assert r["top_speed_ms"] <= 10.0, r  # top Premier League sprint speeds are about 10 m/s
        assert r["top_speed_ms"] > SPRINT_MS, r
        assert r["sprints_per_player"] >= 5, r
        assert r["max_ball_step_m"] <= 1.6, r  # a 120 km/h shot moves 1.33 m a frame


def test_set_pieces_and_saves_happen(full_matches):
    for r in full_matches:
        for key in ("corners", "throw_ins", "goal_kicks", "free_kicks", "fouls", "saves", "clearances"):
            assert r[key] > 0, (key, r)


def test_rates_match_published_averages(full_matches):
    """Every banded measure in docs/eval/sim-realism.md, on three seeds."""
    assert realism.out_of_band(full_matches) == []
    # three matches are too few for the goals band; this only catches a broken scoring model
    assert 0.5 <= sum(r["goals"] for r in full_matches) / len(full_matches) <= 6


def test_set_pieces_crowd_the_ball():
    m = simulate(2, 20)
    kinds = Counter(e["kind"] for e in m.events if e["type"] == "set_piece")
    assert kinds["corner"] + kinds["free_kick"] > 0
    assert realism.measure(m, 20)["crowded_share"] > 0.012
