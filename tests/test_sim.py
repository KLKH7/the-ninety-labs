import json
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from jsonschema import validate

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
    # A Premier League match has roughly 800-1000 passes and 20-30 shots.
    assert 600 <= c["pass"] <= 1300, c
    assert 10 <= c["shot"] <= 45, c
    assert 20 <= c["tackle"] <= 150, c
    assert 150 <= c["pressure"] <= 900, c
    assert c["tackle"] > 0 and c["interception"] > 0 and c["pressure"] > 0
    completed = sum(1 for e in m.events if e["type"] == "pass" and e["outcome"] == "success")
    assert 0.7 <= completed / c["pass"] <= 0.9


GOAL_SEEDS = (7, 11, 21, 31)  # the first four of ninety.sim.funnel's default seeds
GOALS_PER_MATCH = 2.8  # a Premier League match averages about 2.8 (R4: about 1.4 a team)


def _goals(seed: int) -> int:
    return sum(e["type"] == "goal" for e in simulate(seed, 90).events)


def test_goals_per_match_over_several_matches():
    # One match's goals are too noisy to bound: about Poisson with mean 2.8, a correct engine scores
    # 0 in about 6% of matches and 7 or more in about 2%. The mean over n matches has a standard
    # error of about sqrt(2.8 / n); the bound is three of them either side (design: a correct engine
    # fails it by chance about 0.3% of the time).
    with ProcessPoolExecutor() as pool:
        goals = list(pool.map(_goals, GOAL_SEEDS))
    mean, se = sum(goals) / len(goals), (GOALS_PER_MATCH / len(goals)) ** 0.5
    assert GOALS_PER_MATCH - 3 * se <= mean <= GOALS_PER_MATCH + 3 * se, goals
