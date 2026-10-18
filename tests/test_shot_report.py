"""The shot and long-ball report (docs/EVALUATION.md) listens to the engine without changing it, and
reads what it reports from the events as the protocol defines them."""

import math

from ninety.sim import shot_report as R
from ninety.sim.engine import FPS, Engine, goal_x


def test_listening_does_not_change_the_match():
    """Lesson 7's rule for listeners: the same seed gives the same match with the report attached."""
    heard = R.measure(203, 3.0)
    e = Engine(203)
    e.kickoff("home")
    for _ in range(int(3.0 * 60 * FPS)):
        e.step()
    shots = [ev for ev in e.match.events if ev["type"] == "shot"]
    assert heard["events"] == len(e.match.events)
    assert [round(s["d"], 6) for s in heard["shots"]] == [
        round(math.hypot(goal_x(ev["team"]) - ev["x"], 34.0 - ev["y"]), 6) for ev in shots]
    assert heard["decided"], "no on-ball decision was heard"


def test_bands_cover_every_distance_once():
    edges = (0.0, 10.99, 11.0, 16.49, 16.5, 31.99, 32.0, 80.0)
    assert [R.band_of(d) for d in edges] == [0, 0, 1, 1, 2, 3, 4, 4]


def test_the_report_reads_the_shares_the_protocol_defines():
    """Planted numbers: 1 of 4 shots outside the box, 1 of 2 long balls completed, of 10 kicked passes."""
    shot = lambda d, inside, outcome: {"d": d, "inside": inside, "outcome": outcome}  # noqa: E731
    results = [{"seed": 1, "events": 0, "passes": 10, "decided": [(4, "shoot", 0.02, 0.01)],
                "shots": [shot(8, True, "goal"), shot(12, True, "on_target"), shot(14, True, "blocked"),
                          shot(30, False, "off_target")],
                "long_balls": [{"how": "completed", "contested": False, "nearest": 5.0},
                               {"how": "an opponent got to it", "contested": True, "nearest": 2.0}]}]
    text = R.report(results, "test")
    assert "| share of shots from outside the box | 25.0% |" in text
    assert "| long-ball completion | 50.0% |" in text
    assert "| long balls, share of kicked passes | 20.0% |" in text
    assert "| goals per match | 1.00 |" in text
