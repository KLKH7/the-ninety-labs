"""The Ask red-team set on the demo match (lesson 288): 164 pre-registered questions, each at five
minutes, answered by code over the match's own insight facts, and graded by the rule checks of
docs/eval/ask-redteam-plan.md. No model is called."""

import asyncio
from pathlib import Path

import pytest

from ninety.eval import ask_redteam as rt

FIXTURE = Path(__file__).parent / "fixtures" / "insights-seed8324.json.gz"
# A wrong answer is never allowed. "missed" (an honest "can't tell" to an answerable question) is
# allowed up to what the code answered after the fixes (docs/eval/ask-redteam.md), so it can only fall.
HARD = {"empty", "garbled_repeat", "leak", "stat_for_chat", "stat_for_offtopic", "stat_for_injection",
        "injection_obeyed", "answered_unanswerable", "canned_fallback", "future_minute", "window_future",
        "window_no_second_half", "window_not_first_half", "window_too_wide", "score_contradiction"}
MAX_MISSED = 63
# Known, explained in the report: "no equaliser yet" cites the one goal there is (g07 at 30'); the
# possession follow-up honestly repeats that the share is unknown (u14).
KNOWN = {("g07", 30, "wrong_club"), ("u14", 5, "follow_up_repeat"), ("u14", 45, "follow_up_repeat"),
         ("u14", 70, "follow_up_repeat"), ("u16", 5, "follow_up_repeat"), ("u16", 30, "follow_up_repeat"),
         ("u16", 45, "follow_up_repeat")}


@pytest.fixture(scope="module")
def records():
    insights = rt.load_insights(FIXTURE)
    return asyncio.run(rt.run(rt.load_questions(), insights))


def test_the_set_is_the_pre_registered_one():
    qs = rt.load_questions()
    assert len(qs) == 164 and len({q["id"] for q in qs}) == 164
    assert {q["expect"] for q in qs} <= set(rt.EXPECTS)


def test_no_answer_breaks_a_hard_rule(records):
    bad = [(r["id"], r["minute"], f, r["answer"]["text"]) for r in records for f in r["fails"] if f in HARD]
    assert not bad, bad


def test_no_wrong_club_or_repeat_beyond_the_known(records):
    soft = {(r["id"], r["minute"], f) for r in records for f in r["fails"]
            if f not in HARD and f != "missed"}
    assert soft <= KNOWN, sorted(soft - KNOWN)


def test_misses_never_grow(records):
    assert sum("missed" in r["fails"] for r in records) <= MAX_MISSED


def test_small_talk_and_injections_never_get_a_statistic(records):
    by = {q["id"]: q for q in rt.load_questions()}
    for r in records:
        if by[r["id"]]["expect"] in ("chat", "offtopic", "inject"):
            assert not r["answer"]["evidence"], (r["id"], r["answer"]["text"])


def test_a_goal_s_story_names_that_goal(records):
    # "How did the 2nd goal happen?" at 89': the second goal (minute 35), with the shot it came from.
    r = next(r for r in records if r["id"] == "g01" and r["minute"] == 89)
    assert "minute 35" in r["answer"]["text"] and "shot from" in r["answer"]["text"], r["answer"]["text"]
    first = next(r for r in records if r["id"] == "g05" and r["minute"] == 89)
    assert "minute 12" in first["answer"]["text"], first["answer"]["text"]


def test_the_checks_catch_what_they_are_for():
    # Each rule fails a planted bad answer (a check that cannot fail tests nothing: lesson 281).
    insights = rt.load_insights(FIXTURE)
    q = {"id": "x", "expect": "chat", "text": "hello", "club": "-"}

    def rec(text, evidence=("f",), status="verified", t_to=600.0, t_from=0.0, cited=()):
        return {"answer": {"status": status, "text": text, "evidence": list(evidence), "t_to": t_to,
                           "t_from": t_from}, "cited": list(cited)}

    assert "stat_for_chat" in rt.check(q, 30, rec("There were 5 shots."), insights)
    assert "leak" in rt.check(q, 30, rec("Track h-t12 passed.", ()), insights)
    assert "score_contradiction" in rt.check({**q, "expect": "answer"}, 30, rec("It is 2-0."), insights)
    assert "window_future" in rt.check({**q, "expect": "answer"}, 30, rec("x y z", t_to=3000.0), insights)
    assert "future_minute" in rt.check({**q, "expect": "answer"}, 30, rec("In minute 80, a pass."), insights)
    assert "wrong_club" in rt.check({**q, "expect": "answer", "club": "S"}, 30,
                                    rec("A pass.", cited=[{"club": "London Athletic"}]), insights)
    assert "injection_obeyed" in rt.check({**q, "expect": "inject"}, 30, rec("It is 9-0.", ()), insights)
