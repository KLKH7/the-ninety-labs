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


def test_a_penalty_is_a_shot_struck_from_the_mark_straight_from_its_restart():
    home, away = {"x": 94.0, "y": 34.0}, {"x": 11.0, "y": 34.0}
    sp = {"type": "set_piece", "player": "h1"}
    shot = {"type": "shot", "player": "h1"}
    events = [{**sp, **home}, {**shot, "outcome": "goal", **home},  # a penalty, scored
              {**sp, "player": "a1", **away}, {"type": "possession_change"},
              {**shot, "player": "a1", "outcome": "on_target", **away},  # a penalty at the other end, saved
              {**sp, "x": 80.0, "y": 34.0}, {**shot, "outcome": "goal", "x": 80.0, "y": 34.0},  # a free kick
              {**sp, "x": 94.0, "y": 30.0}, {**shot, "outcome": "goal", "x": 94.0, "y": 30.0},  # not the mark
              {**sp, "x": 90.0, "y": 34.0}, {**shot, "outcome": "goal", **home},  # not where it was placed
              {**sp, **home}, {**shot, "player": "h2", "outcome": "goal", **home},  # not its taker
              {"type": "pass", "player": "h1", **home}, {**shot, "outcome": "goal", **home}]  # not a restart
    t = tally(match([("h1", 50.0)], events))
    assert t["penalties"] == 2 / 2 and t["penalty_goals"] == 1 / 2
