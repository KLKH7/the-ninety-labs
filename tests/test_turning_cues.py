import pytest
from jsonschema import validate

from ninety.agents import cues
from ninety.agents.cues import SCHEMA, turning_point_cues
from ninety.agents.factcheck import Claim, check
from ninety.intel.terrain import build_terrain
from ninety.match.facts import compact
from ninety.sim.engine import simulate

MINUTES = 12


@pytest.fixture(scope="module")
def played():
    match = simulate(7, MINUTES)
    terrain = build_terrain(match.events, match.frames, match.roster, MINUTES)
    return match, terrain


def test_seeded_cues_validate_pass_the_checker_and_repeat(played):
    match, terrain = played
    out = turning_point_cues(terrain, match.events)
    assert out == turning_point_cues(terrain, match.events)
    assert len(out) == 3 * len(terrain["turning_points"])
    known = {e["id"]: compact(e) for e in match.events}
    for cue in out:
        validate(cue, SCHEMA)
        assert check(Claim(cue["text"], cue["evidence"]), known).ok


def _event(i, minute, kind, team, outcome=None):
    return {"id": f"e{i}", "t": (minute - 1) * 60 + 10 + i * 0.01, "type": kind, "team": team,
            "player": f"{team[0]}7", "receiver": None, "outcome": outcome,
            "ball_speed_kmh": None, "x": 50.0, "y": 34.0, "end_x": None, "end_y": None}


def _point(minute, team, until, held, ids, peak=None):
    return {"minute": minute, "team": team, "until": until, "held": held, "peak_minute": peak or minute,
            "source_ids": ids}


def _texts(points, events, minutes=90):
    terrain = {"minutes": minutes, "turning_points": points}
    return {c["id"]: c["text"] for c in turning_point_cues(terrain, events)}


def test_templates_follow_the_facts():
    events = [_event(1, 6, "pressure", "away"), _event(2, 6, "pressure", "away"),
              _event(3, 6, "pressure", "away"), _event(4, 40, "pass", "home"),
              _event(5, 41, "interception", "home"), _event(6, 41, "interception", "home"),
              _event(7, 45, "pass", "away"), _event(8, 90, "pass", "away")]
    points = [_point(6, "away", 40, 34, ["e1", "e2", "e3"]),
              _point(41, "home", 90, 49, ["e5", "e6"], peak=45)]
    texts = _texts(points, events)
    assert texts["cue-tp6-casual"] == (
        "Away settle first and take control at 6', holding on until 40'. Going in, they press 3 times.")
    assert texts["cue-tp41-casual"] == (
        "Home finally break Away's grip at 41', staying on top until the end, strongest at 45'. "
        "Going in, they intercept 2 times.")
    assert texts["cue-tp41-audio"].startswith(
        "Home take control in minute 41 and keep it until minute 90, the end of the match")
    assert texts["cue-tp6-analyst"] == "Away on top 6'–40'. The three minutes up to it: 3 pressures."


def test_a_short_spell_after_a_short_spell_reads_as_brief():
    events = [_event(1, 10, "pass", "home"), _event(2, 20, "pass", "away"),
              _event(3, 26, "pass", "home")]
    points = [_point(10, "home", 19, 8, ["e1"]), _point(20, "away", 26, 6, ["e2"])]
    assert _texts(points, events)["cue-tp20-casual"] == "Away wrestle it back at 20', but only until 26'."


def test_a_minute_that_only_a_counted_event_could_prove_is_left_out():
    # planted defect: citing the away pass in minute 30 to prove "until 30'" would add a fourth
    # away pass to the evidence, so a stated count of 3 would no longer match the cited events
    events = [_event(1, 6, "pass", "away"), _event(2, 6, "pass", "away"),
              _event(3, 6, "pass", "away"), _event(4, 30, "pass", "away")]
    texts = _texts([_point(6, "away", 30, 24, ["e1", "e2", "e3"])], events)
    assert "30" not in texts["cue-tp6-casual"] and "until" not in texts["cue-tp6-analyst"]
    assert "3 passes" in texts["cue-tp6-analyst"]


def test_a_turning_point_with_no_citable_minute_airs_no_cue():
    assert _texts([_point(6, "away", 30, 24, [])], [_event(1, 7, "pass", "home")]) == {}


def test_a_template_with_an_uncited_count_is_refused(monkeypatch):
    # planted defect: a template that states a count the cited events do not hold must not air
    monkeypatch.setattr(cues, "_turning_text", lambda *args: "Away press 4 times.")
    events = [_event(1, 6, "pressure", "away")]
    with pytest.raises(ValueError, match="4"):
        _texts([_point(6, "away", 30, 24, ["e1"])], events)


def test_goals_in_the_spell_are_named_with_their_minutes():
    events = [_event(1, 20, "pressure", "home"), _event(2, 20, "pressure", "home"),
              _event(3, 20, "pressure", "home"), _event(4, 34, "goal", "home"),
              _event(5, 60, "goal", "home"), _event(6, 90, "pass", "away"),
              _event(7, 70, "goal", "away")]
    texts = _texts([_point(20, "home", 90, 71, ["e1", "e2", "e3"])], events)
    assert texts["cue-tp20-casual"].endswith(
        "They score 2 times, at 34' and 60'. Going in, they press 3 times.")
    assert "They score 2 times, in minute 34 and minute 60." in texts["cue-tp20-audio"]
    assert "Goals in the spell: 34', 60'." in texts["cue-tp20-analyst"]


def test_an_own_goal_is_not_credited_to_the_spell():
    # a goal event with no scorer is an own goal; which side it counts for is not on the event
    own_goal = {**_event(2, 30, "goal", "home"), "player": None}
    texts = _texts([_point(20, "home", 40, 21, ["e1"])], [_event(1, 20, "pass", "home"), own_goal])
    assert "score" not in texts["cue-tp20-casual"] and "Goals" not in texts["cue-tp20-analyst"]


def test_a_turning_point_at_kick_off_says_first_minute():
    events = [_event(i, 1, "pass", "home") for i in range(1, 5)] + [_event(9, 8, "pass", "away")]
    texts = _texts([_point(1, "home", 8, 8, ["e1", "e2", "e3", "e4"])], events)
    assert texts["cue-tp1-casual"].endswith("They play 4 passes in the first minute.")
    assert texts["cue-tp1-analyst"].endswith("The first minute: 4 passes.")
