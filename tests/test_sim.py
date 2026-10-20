import json
import os
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from statistics import mean

import pytest
from jsonschema import validate

from ninety.sim import funnel
from ninety.sim.engine import BOARDS_M, FPS, PITCH_X, PITCH_Y, simulate

ROOT = Path(__file__).resolve().parent.parent
EVENT_SCHEMA = json.loads((ROOT / "schemas/match_event.schema.json").read_text())
FRAME_SCHEMA = json.loads((ROOT / "schemas/frame.schema.json").read_text())


def test_deterministic_for_a_seed():
    a, b = simulate(3, 2), simulate(3, 2)
    assert a.events == b.events
    assert a.frames[-1] == b.frames[-1]


def test_frames_cover_the_clock_and_stay_on_the_pitch():
    m = simulate(5, 2)
    assert len(m.frames) == 2 * 60 * FPS
    for fr in m.frames[::50]:
        assert len(fr["players"]) == 22
        # Players may run past a line and the ball may roll on out of play (Law 9), as far as
        # the advertising boards.
        for p in fr["players"]:
            assert -BOARDS_M <= p["x"] <= PITCH_X + BOARDS_M and -BOARDS_M <= p["y"] <= PITCH_Y + BOARDS_M
            assert "heading" in p and "vx" in p and p["action"] in (
                "stand", "walk", "run", "strike", "dive", "throw",
                "foot", "thigh", "chest", "head", "hands",
            )
        assert "vx" in fr["ball"]
        assert -BOARDS_M <= fr["ball"]["x"] <= PITCH_X + BOARDS_M
        assert -BOARDS_M <= fr["ball"]["y"] <= PITCH_Y + BOARDS_M


def test_events_match_schema():
    m = simulate(9, 3)
    for ev in m.events:
        validate(ev, EVENT_SCHEMA)
    for fr in m.frames[::250]:
        validate(fr, FRAME_SCHEMA)


def test_football_realistic_rates_over_a_full_match():
    m = simulate(11, 90)
    c = Counter(e["type"] for e in m.events)
    # A Premier League match has roughly 800-1000 passes and 20-30 shots. Its goals are not read
    # from one match: they are a draw of a few (8% of Premier League matches end 0-0), checked over
    # twelve below (lesson 136).
    assert 600 <= c["pass"] <= 1300, c
    assert 10 <= c["shot"] <= 45, c
    assert 20 <= c["tackle"] <= 150, c
    assert 150 <= c["pressure"] <= 900, c
    assert c["tackle"] > 0 and c["interception"] > 0 and c["pressure"] > 0
    completed = sum(1 for e in m.events if e["type"] == "pass" and e["outcome"] == "success")
    assert 0.7 <= completed / c["pass"] <= 0.9


@pytest.mark.skipif(os.environ.get("NINETY_HELD_OUT") != "1",
                    reason="12 full matches, about 25 minutes on two cores: NINETY_HELD_OUT=1")
def test_goals_over_twelve_matches_fall_where_a_real_leagues_would():
    # R4, held out: the range is the Premier League's (funnel.goals_range), fixed before any engine
    # number was read, and nothing is tuned to it. Two full matches at a time at most.
    with ProcessPoolExecutor(max_workers=2) as pool:
        goals = [r["goals"] for r in pool.map(funnel.measure, funnel.SEEDS)]
    low, high = funnel.goals_range(len(goals))
    assert low <= mean(goals) <= high, goals


def test_a_pass_names_who_it_was_for_who_got_it_and_who_cut_it_out():
    """`receiver` is the team-mate who got a completed pass, `intended` the team-mate it was played
    for, `interceptor` the opponent who won a failed one, `deflected_by` one who only touched it:
    never one read as another."""
    m = simulate(7, 6)
    team = {r["id"]: r["team"] for r in m.roster}
    passes = [e for e in m.events if e["type"] == "pass"]
    assert any(e["interceptor"] for e in passes) and any(e["intended"] for e in passes)
    assert any(e["deflected_by"] for e in passes)  # a touch without control is not a win
    for e in passes:
        assert e["receiver"] is None or (e["outcome"] == "success" and team[e["receiver"]] == e["team"])
        assert e["intended"] is None or team[e["intended"]] == e["team"]
        assert e["interceptor"] is None or (e["outcome"] == "fail" and team[e["interceptor"]] != e["team"])
        assert e["deflected_by"] is None or (e["outcome"] == "fail" and team[e["deflected_by"]] != e["team"])
        assert not (e["interceptor"] and e["deflected_by"])  # won it, or only touched it
