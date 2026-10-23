"""The Judge evaluation's true labels are true by the event's own fields (lesson 34, audit 4a): a
claim that a tackle "wins the ball" is labelled true only for a tackle that won it, and no claim is
written about a goal that names no scorer."""

from ninety.eval import factcheck_eval as fe


def ev(n, type_, **fields):
    base = {"id": f"e{n:03d}", "minute": 2, "second": n, "clock": f"01:{n:02d}", "type": type_,
            "team": "home", "player": f"h{2 + n % 9}"}
    return {**base, **fields}


EVENTS = [
    ev(1, "pass", receiver="h9", outcome="success", distance_m=12, ball_speed_kmh=40),
    ev(2, "tackle", receiver="a7", outcome="fail"),     # lost the tackle: did not win the ball
    ev(3, "tackle", receiver="a8", outcome="success"),  # won it
    ev(4, "goal", player=None, outcome="goal"),         # no scorer named
    ev(5, "goal", player="h9", outcome="goal"),
]


def built(monkeypatch):
    monkeypatch.setattr(fe, "events_in", lambda seed, minutes, a, b: list(EVENTS))
    return fe.cases(7, 5)


def test_only_a_won_tackle_is_said_to_win_the_ball(monkeypatch):
    for case in built(monkeypatch):
        if case["true"] and "wins the ball" in case["claim"].text:
            (e,) = case["evidence"]
            assert e["type"] == "tackle" and e["outcome"] == "success", case["claim"].text


def test_a_goal_without_a_scorer_gets_no_claim(monkeypatch):
    cases = built(monkeypatch)
    assert not [c for c in cases if "None" in c["claim"].text]
    assert [c["claim"].text for c in cases if c["kind"] == "true: goal"] == ["h9 scores."]


def test_a_failed_tackle_is_still_used_where_its_words_fit(monkeypatch):
    # "a risky tackle" and "a bold challenge" are true of any tackle; only "wins the ball" needs a win.
    kinds = {c["kind"] for c in built(monkeypatch) if c["evidence"][0]["id"] == "e002"}
    assert {"true: negative interpretation", "true: held-out tone, bold challenge"} <= kinds
    assert not kinds & {"true: tackle", "true: interpreted tackle"}
