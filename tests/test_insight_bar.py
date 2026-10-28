"""The INSIGHT bar (ninety/agents/insight_bar.py): only what the broadcast can't show, fact-checked,
spaced, named by the ID feed or the club, never a track id or a one-event restatement."""

from __future__ import annotations

import copy

from ninety.agents import insight_bar
from ninety.agents.onair import TRACK_ID
from tests.test_companion_match import insights

LB = {"id": "lb:s13-v00002", "kind": "line_break", "metric": "opponents_bypassed", "team": "home",
      "minute": 31, "t": 1816.88, "value": 5, "unit": "opponents", "lo": 5, "hi": 5, "confident": True,
      "tracked": {"home": 12, "away": 12}, "event": "s13-v00002", "event_confidence": 0.9,
      "team_confidence": 0.99, "passer": "h-t13005", "receiver": "h-t13008", "also": [[1, "passes"]],
      "club": "London Athletic", "receiver_is": None, "passer_is": None}
SPELL = {"id": "spell:s01-v00009", "kind": "spell", "metric": "spell_passes", "team": None, "minute": 6,
         "t": 351.56, "value": 9, "unit": "passes", "confident": True, "club": None,
         "events": ["s01-v00001", "s01-v00009"]}


def bar(facts: dict, names: dict | None = None, gap_video=lambda t: t):
    mi = insights()
    mi.facts = {k: [] for k in mi.facts} | copy.deepcopy(facts)
    return insight_bar.build(mi, gap_video, set(), {"home": "London", "away": "Lisbon"}, names or {})


def test_a_confident_insight_airs_checked_with_its_trace_and_an_unsure_one_never():
    cues, claims = bar({"line_break": [LB], "spell": [SPELL]})
    texts = [c["text"] for c in cues]
    assert texts == ["In minute 6, one side strung 9 passes together in a row.",
                     "In minute 31, one of London Athletic's players played a pass that took 5 Lisbon "
                     "Esportes players out of the game."]
    assert all(c["kind"] == "insight" and c["verified"] for c in cues)
    assert [c["evidence"] for c in cues] == [["s01-v00001", "s01-v00009"], ["s13-v00002"]]
    # How we know: one trace per insight, the same evidence (the viewer joins them by it).
    assert [c["evidence"] for c in claims] == [c["evidence"] for c in cues]
    assert [s["action"] for s in claims[1]["steps"]] == ["pick", "verify", "air"]
    assert bar({"line_break": [LB | {"confident": False}]})[0] == []


def test_below_the_bar_is_silence_not_filler():
    assert bar({"line_break": [LB | {"value": 2, "lo": 2, "hi": 2}],
                "spell": [SPELL | {"value": 4}]})[0] == []


def test_at_most_one_insight_per_stretch_of_footage_the_most_significant_and_a_goal_always():
    near = LB | {"id": "lb:near", "t": LB["t"] + 10, "value": 7, "lo": 7, "hi": 7, "event": "near"}
    cues, _ = bar({"line_break": [LB, near]})
    assert [c["id"] for c in cues] == ["insight-lb:near"]  # 10 s apart: only the bigger one
    apart = near | {"t": LB["t"] + insight_bar.MIN_GAP_S + 1}
    assert len(bar({"line_break": [LB, apart]})[0]) == 2
    goal = {"id": "goal:g1", "kind": "goal", "team": "home", "club": "London Athletic", "minute": 31,
            "t": LB["t"] + 5, "event": "g1", "event_confidence": 0.9, "side_known": True, "confident": True}
    ids = [c["id"] for c in bar({"line_break": [LB], "goal": [goal]})[0]]
    assert "insight-goal:g1" in ids and "insight-lb:s13-v00002" not in ids  # the goal first


def test_a_player_is_the_id_feeds_name_or_his_club_never_a_track_id():
    cues, _ = bar({"line_break": [LB]}, names={"h-t13005": "Rondell"})
    assert cues[0]["text"].startswith("In minute 31, Rondell played a pass"), cues[0]["text"]
    # A name field holding a track id: the sentence is refused or rendered, never aired with the id.
    cues, _ = bar({"line_break": [LB | {"passer_is": "h-t13005"}]})
    assert not any(TRACK_ID.search(c["text"]) for c in cues), cues


def test_a_one_event_restatement_is_not_an_insight():
    kinds = {"e2": "shot", "e1": "pass"}
    assert insight_bar.restates_one_event({"kind": "insight", "evidence": ["e2"]}, kinds)
    assert not insight_bar.restates_one_event({"kind": "insight", "evidence": ["e1", "e2"]}, kinds)
    assert not insight_bar.restates_one_event({"kind": "pass_arc", "evidence": ["e1"]}, kinds)


def test_a_name_the_feed_does_not_give_never_reaches_the_bar():
    # The role gate's guess (roles.say) is not the feed: without the feed naming him, he is his club.
    cues, _ = bar({"line_break": [LB | {"passer_is": "Isaac Tendell"}]})
    # Unnamed, he is said as one of his club's players (lesson 297: never "a London Athletic player").
    text = cues[0]["text"] if cues else ""
    assert cues and "Isaac Tendell" not in text and "one of London Athletic's players" in text, text


def test_the_bundle_takes_its_insight_bar_from_the_insights_file(tmp_path):
    import json

    from tests.test_e2e import cues as bundle_cues
    from tests.test_e2e import run

    mi = insights()
    mi.facts = {k: [] for k in mi.facts} | {"line_break": [LB | {"t": 61.0}]}
    path = tmp_path / "insights.json"
    path.write_text(json.dumps(mi.as_dict()))
    out, _ = run(tmp_path, "--insights", str(path))
    bar_cues = [c for c in bundle_cues(out) if c["kind"] == "insight"]
    assert [c["id"] for c in bar_cues] == ["insight-lb:s13-v00002"]
    claims = json.loads((out / "trace.json").read_text())["claims"]
    assert any(c["id"] == "bar-lb:s13-v00002" and c["evidence"] == bar_cues[0]["evidence"] for c in claims)
