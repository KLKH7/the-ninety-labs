"""The shot and long-ball report (docs/EVALUATION.md) listens to the engine without changing it, and
reads what it reports from the events as the protocol defines them."""

import math
import re
from pathlib import Path

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


def test_the_protocol_is_the_one_written_down():
    """Lesson 51: the seeds and published figures in the code are the ones EVALUATION.md fixed."""
    doc = (Path(__file__).resolve().parents[1] / "docs/EVALUATION.md").read_text()
    text = doc[doc.index("## Shots by distance and long balls (R3, R4)"):]
    text = text[:text.index("\n## ", 1)]
    m = re.search(r"(\d+) full matches, seeds (\d+) to (\d+), 90 minutes", text)
    n, first, last = map(int, m.groups())
    assert R.SEEDS == tuple(range(first, last + 1)) and len(R.SEEDS) == n and R.MINUTES == 90
    assert "31.7 to 48.2%" in text and "8.3 to 13.3" in text and "47.3%" in text and "6.5 to 23.1%" in text
    assert (R.OUTSIDE_SHARE, R.OUTSIDE_PER_MATCH, R.LONG_COMPLETION, R.LONG_SHARE) == (
        (0.317, 0.482), (8.3, 13.3), 0.473, (0.065, 0.231))
    assert "16.2 yards" in text and "19.3" in text and R.LONG_BALL_M == 32.0
