"""The first half against the second, and the key moments (GROUNDING I23)."""

import json

import pytest

from ninety.agents import companion_match as cm
from ninety.eval.companion_tools import STANDIN
from ninety.intel.match_insights import HALF_MIN, MatchInsights


def standin(minutes=None) -> MatchInsights:
    body = json.loads(STANDIN.read_text())
    if minutes:
        body["minutes"] = minutes
    return MatchInsights.from_dict(body)


def test_the_halves_split_at_laws_45_minutes_and_stop_at_now():
    mi = standin(minutes=90)
    spans = {(r["minute_from"], r["minute_to"]) for r in mi.halves(1, 70)["summary"]}
    assert spans == {(1, HALF_MIN), (HALF_MIN + 1, 70)}
    assert {(r["minute_from"], r["minute_to"]) for r in mi.halves(1, 30)["summary"]} == {(1, 30)}


def test_key_moments_are_confident_facts_latest_first_with_the_biggest_line_breaks():
    mi = standin()
    got = mi.key_moments(1, mi.minutes)["facts"]
    assert got and all(f["confident"] for f in got)
    assert [f["t"] for f in got] == sorted((f["t"] for f in got), reverse=True)
    breaks = [f for f in got if f["kind"] == "line_break"]
    allb = [f for f in mi.facts["line_break"] if f.get("confident")]
    top3 = {f["id"] for f in sorted(allb, key=lambda r: (-r["value"], r["t"]))[:3]}
    assert len(breaks) <= 3 and {b["id"] for b in breaks} <= top3  # the latest twelve keep any of them


def test_a_recap_with_a_goal_in_it_leads_with_the_goal():
    mi = standin()
    a, calls = cm.code_match_answer(cm.Question("s", None, "What have I missed?", 60.0 * 20 - 1), mi)
    goals = [f for f in mi.facts["goal"] if f["minute"] <= 20]
    assert [c["name"] for c in calls] == ["key_moments"] and a.status == "verified"
    if goals:
        assert a.headline.startswith("Goal: ")


@pytest.mark.parametrize(
    "q, tool",
    [
        ("How did the second half compare to the first?", "halves"),
        ("What's changed since the break?", "halves"),
        ("What have I missed?", "key_moments"),
        ("Catch me up", "key_moments"),
    ],
)
def test_halves_and_recap_questions_route_to_their_tools(q, tool):
    assert tool in cm.route(q)


def test_a_planted_window_keeps_only_sure_moments_and_its_three_biggest_line_breaks():
    body = json.loads(STANDIN.read_text())
    lb = [{"id": f"lb:{v}", "kind": "line_break", "team": "home", "club": "London Athletic", "minute": 5,
           "t": 240.0 + v, "value": v, "confident": True} for v in (1, 2, 3, 4, 5)]
    lb.append({**lb[0], "id": "lb:unsure", "value": 9, "confident": False})
    body["facts"] = {"line_break": lb, "goal": [], "shot": [], "counter": [], "one_two": []}
    got = MatchInsights.from_dict(body).key_moments(1, 10)["facts"]
    assert [f["id"] for f in got] == ["lb:5", "lb:4", "lb:3"]


def _planted(facts, minutes=21):
    body = json.loads(STANDIN.read_text())
    body["facts"] = {"line_break": [], "goal": [], "shot": [], "counter": [], "one_two": [], **facts}
    body["minutes"] = minutes
    return MatchInsights.from_dict(body)


def test_a_recap_never_drops_a_goal_however_many_moments_follow():
    # The merge queue's review of #326: the minute-12 goal fell off the twelve latest moments.
    lon = {"team": "home", "club": "London Athletic", "confident": True}
    goal = {"id": "goal:g1", "kind": "goal", "minute": 5, "t": 250.0, **lon}
    shots = [{"id": f"shot:s{k}", "kind": "shot", "minute": 6 + k, "t": 300.0 + 60 * k, "value": 18, **lon}
             for k in range(14)]
    got = _planted({"goal": [goal], "shot": shots}).key_moments(1, 21)["facts"]
    assert "goal:g1" in [f["id"] for f in got]
    assert len(got) == 12  # the goal and the eleven latest shots


def test_the_halves_split_at_minute_45():
    mi = standin(minutes=90)
    spans = {(r["minute_from"], r["minute_to"]) for r in mi.halves(1, 90)["summary"]}
    assert spans == {(1, 45), (46, 90)}


def test_only_a_recap_or_a_goal_question_is_headed_by_the_goal():
    mi = standin()
    goal = {"kind": "goal", "club": "London Athletic", "minute": 12}
    assert cm.headline("What have I missed?", [goal], mi).startswith("Goal: ")
    assert cm.headline("Where has the ball been?", [goal], mi) is None or not cm.headline(
        "Where has the ball been?", [goal], mi).startswith("Goal: ")
    assert not cm.headline("Who scored?", [goal], mi).startswith("Goal: ")  # a who question names who
    assert cm.headline("What have I missed?", [{**goal, "minute": None}], mi) is None
