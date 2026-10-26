"""Why a detected free kick was given: offside from the offside reading of the last completed pass,
otherwise likely a foul, unknown when too close to call; a penalty is a foul (Laws 11 to 14).

Scenes are built here on the offside reader's own planted scene (tests/test_referee_offside.py), so
each premise is the reader's own verdict, asserted before the cause is (lesson 47).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from ninety.intel import offside, restart_cause

sys.path.insert(0, str(Path(__file__).parent))
from test_referee_offside import pass_to, scene  # noqa: E402


def restart(kind, t=8.0, team="away", **kw):
    return {"id": f"r-{kind}", "t": t, "frame": int(t * 25), "type": "set_piece", "team": team,
            "x": 86.0, "y": 30.0, "restart": kind, "source": "vision", "confidence": 0.8} | kw


@pytest.mark.parametrize("receiver_x, verdict, cause", [
    (90.0, "offside", "offside"), (86.0, "too_close", "unknown"), (80.0, "onside", "foul_likely")])
def test_a_free_kick_takes_its_cause_from_the_last_pass_offside_reading(receiver_x, verdict, cause):
    frames = scene(receiver_x)
    assert offside.offsides([pass_to()], frames)[0]["verdict"] == verdict  # the premise
    assert restart_cause.causes([pass_to(), restart("free_kick")], frames) == {"r-free_kick": cause}


def test_an_offside_with_a_defender_untracked_is_unknown():
    frames = scene(90.0, opp_missing=2)
    assert offside.offsides([pass_to()], frames)[0]["verdict"] == "unsure"
    assert restart_cause.causes([pass_to(), restart("free_kick")], frames) == {"r-free_kick": "unknown"}


def test_a_free_kick_with_no_pass_since_the_last_restart_is_likely_a_foul():
    frames = scene(90.0)
    earlier = restart("throw_in", t=6.0)  # after the offside pass: a new phase began
    found = restart_cause.causes([pass_to(), earlier, restart("free_kick")], frames)
    assert found == {"r-free_kick": "foul_likely"}


def test_a_penalty_is_a_foul_and_other_restarts_have_no_cause():
    frames = scene(80.0)
    events = [pass_to(), restart("penalty_kick")]
    assert restart_cause.causes(events, frames) == {"r-penalty_kick": "foul"}
    for kind in ("corner", "goal_kick", "throw_in"):
        assert restart_cause.causes([pass_to(), restart(kind)], frames) == {}


def test_annotate_sets_the_cause_on_copies():
    events = [pass_to(), restart("free_kick")]
    out = restart_cause.annotate(events, scene(90.0))
    assert out[1]["cause"] == "offside" and "cause" not in events[1]


def test_annotated_events_are_valid_match_events():
    import json

    import jsonschema
    schema = json.loads((Path(__file__).parents[1] / "schemas" / "match_event.schema.json").read_text())
    for e in restart_cause.annotate([restart("free_kick"), restart("penalty_kick")], scene(80.0)):
        jsonschema.validate(e, schema)


@pytest.mark.parametrize("went_on", ["possession_change", "tackle", "interception", "out_of_play", "shot"])
def test_play_that_went_on_after_an_offside_position_was_not_stopped_for_it(went_on):
    frames = scene(90.0)
    assert offside.offsides([pass_to()], frames)[0]["verdict"] == "offside"  # the premise
    later = {"id": "v5", "t": 6.0, "frame": 150, "type": went_on, "team": "away", "x": 70.0, "y": 30.0}
    found = restart_cause.causes([pass_to(), later, restart("free_kick")], frames)
    assert found == {"r-free_kick": "foul_likely"}


def test_a_pass_after_an_offside_one_means_play_went_on():
    frames = scene(90.0)
    lost = pass_to() | {"id": "v2", "t": 6.0, "frame": 150, "outcome": "fail", "receiver": None}
    found = restart_cause.causes([pass_to(), lost, restart("free_kick")], frames)
    assert found == {"r-free_kick": "foul_likely"}
