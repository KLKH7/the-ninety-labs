"""The commentary track (ninety/speech/commentary.py): checked calls, one voice, never a guessed side."""

import json
import random

import pytest

from ninety.speech import bundle, commentary
from ninety.speech.commentary import GAP_S, MAX_LAG_S

CLUBS = {"home": "London", "away": "Lisbon"}


def ev(i, t, kind, team="home", side=0.99, conf=0.9, **kw):
    return {"id": i, "t": t, "type": kind, "team": team, "team_confidence": side, "player": None,
            "x": 90.0, "y": 34.0, "source": "vision", "confidence": conf, **kw}


def lines(events, cues=(), clubs=CLUBS):
    return commentary.commentary(events, list(cues), clubs)["lines"]


def texts(events, cues=(), clubs=CLUBS):
    return [line["text"] for line in lines(events, cues, clubs)]


def test_a_commentator_calls_goals_shots_and_restarts_in_the_present_tense():
    events = [ev("v1", 10.0, "shot", outcome="on_target"), ev("v2", 20.0, "goal", team="away"),
              ev("v3", 40.0, "out_of_play", y=68.0), ev("v4", 60.0, "out_of_play", x=105.0, y=40.0),
              ev("v5", 80.0, "kickoff")]
    assert texts(events) == ["London shoot, on target.", "Goal! Lisbon score!", "It's gone out for a throw.",
                             "It's gone out of play.", "London kick off."]


@pytest.mark.parametrize("side", [None, 0.3, 0.96])  # unknown, unsure, at the threshold (not above it)
def test_a_side_not_told_surely_is_never_said(side):
    events = [ev("v1", 10.0, "shot", side=side, outcome="off_target"), ev("v2", 20.0, "goal", side=side),
              ev("v3", 40.0, "kickoff", side=side)]
    said = texts(events)
    assert said == ["A shot, wide.", "Goal!", "Kick-off."]
    assert not any(word in " ".join(said) for word in ("London", "Lisbon", "home", "away", "Home", "Away"))


def test_a_detection_below_the_confidence_gate_is_not_called():
    body = commentary.commentary([ev("v1", 10.0, "goal", conf=0.4)], [], CLUBS)
    assert body["lines"] == [] and "below" in body["refused"][0]["reason"]


def test_a_goal_is_never_crowded_out_by_an_insight_or_a_restart():
    pass_ = ev("v3", 10.4, "pass", player="h-t4", receiver="h-t8", outcome="success", end_x=78.0, end_y=34.0,
               ball_speed_kmh=40.0)
    events = [ev("v1", 10.0, "out_of_play", y=0.0), ev("v2", 10.2, "goal"), pass_]
    cue = {"id": "insight-m-v3", "kind": "insight", "persona": "analyst", "verified": True, "t_in": 10.4,
           "text": "h-t4 plays it 12 m to h-t8, at 40 km/h.", "evidence": ["v3"]}
    said = lines(events, [cue])
    assert said[0]["kind"] == "goal" and said[0]["t_in"] == 10.2  # on its moment, whatever came first
    assert all(line["kind"] != "insight" or line["t_in"] >= said[0]["t_out"] + GAP_S for line in said)


def test_an_insight_is_said_only_when_verified_and_never_names_an_unsure_side():
    events = [ev("v3", 10.0, "pass", side=0.3, player="h-t4", receiver="h-t8", outcome="success",
                 end_x=78.0, end_y=34.0, ball_speed_kmh=40.0)]
    cue = {"id": "insight-m-v3", "kind": "insight", "persona": "analyst", "t_in": 10.0,
           "text": "h-t4 plays it 12 m to h-t8, at 40 km/h.", "evidence": ["v3"]}
    assert texts(events, [{**cue, "verified": False}]) == []
    (said,) = texts(events, [{**cue, "verified": True}])
    assert said == "A player plays it 12 metres to another player, at 40 kilometres an hour."
    assert "London" not in said and "h-t" not in said


def test_a_number_the_evidence_does_not_hold_is_refused():
    events = [ev("v3", 10.0, "pass", player="h-t4", receiver="h-t8", outcome="success",
                 end_x=78.0, end_y=34.0)]
    cue = {"id": "insight-m-v3", "kind": "insight", "persona": "analyst", "verified": True, "t_in": 10.0,
           "text": "h-t4 plays it 30 m to h-t8.", "evidence": ["v3"]}
    body = commentary.commentary(events, [cue], CLUBS)
    assert body["lines"] == [] and "30" in body["refused"][0]["reason"]


def test_lines_never_overlap_leave_silence_and_are_never_late():
    rng = random.Random(7)
    kinds = ["goal", "shot", "out_of_play", "kickoff", "shot", "out_of_play"]
    events = sorted((ev(f"v{n}", round(rng.uniform(0, 120), 2), rng.choice(kinds),
                        team=rng.choice(["home", "away"]), side=rng.choice([0.3, 0.99]),
                        outcome=rng.choice(["on_target", "off_target", None]),
                        y=rng.choice([0.0, 34.0, 68.0]))
                     for n in range(80)), key=lambda e: e["t"])
    body = commentary.commentary(events, [], CLUBS)
    said = body["lines"]
    assert said and body["dropped"]  # the play outruns one voice: some calls must go
    for a, b in zip(said, said[1:], strict=False):
        assert b["t_in"] >= a["t_out"] + GAP_S - 1e-9
    assert all(0 <= line["t_in"] - line["t_event"] <= MAX_LAG_S + 1e-9 for line in said)
    goals = [e for e in events if e["type"] == "goal"]
    called = {line["evidence"][0] for line in said}
    # A goal is dropped only when another goal holds the voice.
    for g in goals:
        if g["id"] not in called:
            assert any(line["kind"] == "goal" and line["t_in"] - GAP_S < g["t"] + MAX_LAG_S
                       and line["t_out"] + GAP_S > g["t"] for line in said)


def test_the_bundle_voices_every_call_and_the_estimate_calls_nothing(tmp_path):
    body = commentary.commentary([ev("v1", 10.0, "shot", outcome="on_target")], [], CLUBS)
    summary = commentary.write(body, tmp_path)
    assert summary == {"lines": 1, "dropped": 0, "refused": 0, "chars": len("London shoot, on target.")}
    assert ("London shoot, on target.", "commentary") in bundle.lines(tmp_path)
    cost = bundle.estimate(tmp_path, cache=tmp_path / "empty-cache")
    assert cost["by_kind"]["commentary"] == 1 and cost["new_lines"] == cost["lines"]
    assert cost["usd_at_s1"] == round(cost["chars"] * bundle.USD_PER_CHAR, 4)
    assert not (tmp_path / "speech.json").exists()  # an estimate synthesises nothing
    assert json.loads((tmp_path / "commentary.json").read_text())["format"] == 1
