"""The match funnel counts what its report says it counts."""

from types import SimpleNamespace

from ninety.sim.funnel import tally

ROSTER = [{"id": "h1", "team": "home"}, {"id": "a1", "team": "away"}]


def match(steps, events=()):
    frames = [{"possessor": who, "ball": {"x": x, "y": 34.0}} for who, x in steps]
    return SimpleNamespace(roster=ROSTER, frames=frames, events=list(events))


def test_an_entry_is_a_crossing_once_per_crossing_and_not_where_a_possession_starts():
    m = match([("h1", 50.0), ("h1", 75.0), (None, 80.0), ("h1", 92.0), ("h1", 60.0), ("h1", 75.0),
               ("a1", 30.0), ("a1", 20.0)])  # away wins it inside its own final third: no entry
    t = tally(m)
    assert t["final_third"] == 2 / 2  # home entered twice; per team = halved
    assert t["box"] == 1 / 2
    assert t["possessions"] == 2 / 2


def test_completion_counts_only_received_passes():
    events = [{"type": "pass", "outcome": "success"}, {"type": "pass", "outcome": "fail"},
              {"type": "pass", "outcome": None}, {"type": "shot"}]
    t = tally(match([("h1", 50.0)], events))
    assert abs(t["completion"] - 1 / 3) < 1e-9 and t["passes"] == 3 / 2 and t["shots"] == 1 / 2
