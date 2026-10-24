"""The Judge evaluation's true labels are true by the event's own fields (lesson 34, audit 4a): a
claim that a tackle "wins the ball" is labelled true only for a tackle that won it, and no claim is
written about a goal that names no scorer."""

from ninety.eval import factcheck_eval as fe


def ev(n, type_, **fields):
    base = {"id": f"e{n:03d}", "minute": 2, "second": n, "clock": f"01:{n:02d}", "type": type_,
            "team": "home", "player": f"h{2 + n % 9}"}
    return {**base, **fields}


EVENTS = [
    ev(1, "pass", receiver="h9", intended="h9", outcome="success", distance_m=12, ball_speed_kmh=40),
    # Completed, but to a team-mate other than the one it was meant for.
    ev(6, "pass", receiver="h6", intended="h2", outcome="success", distance_m=35, ball_speed_kmh=60),
    ev(7, "tackle", receiver="a9", outcome=None),        # unresolved: did not win the ball either
    # Short and slow, completed, but meant for someone else: no "cautious pass to h5".
    ev(8, "pass", receiver="h5", intended="h3", outcome="success", distance_m=8, ball_speed_kmh=30),
    ev(2, "tackle", receiver="a7", outcome="fail"),     # lost the tackle: did not win the ball
    ev(3, "tackle", receiver="a8", outcome="success"),  # won it
    ev(4, "goal", player=None, outcome="goal"),         # no scorer named
    ev(5, "goal", player="h9", outcome="goal"),
]


def built(monkeypatch):
    monkeypatch.setattr(fe, "events_in", lambda seed, minutes, a, b: list(EVENTS))
    return fe.cases(7, 5)


def test_only_a_won_tackle_is_said_to_win_the_ball(monkeypatch):
    cases = built(monkeypatch)
    winners = [c["evidence"][0]["id"] for c in cases if c["true"] and "wins the ball" in c["claim"].text
               and c["evidence"][0]["type"] == "tackle"]
    assert winners and set(winners) == {"e003"}  # the won tackle, never the lost or unresolved one


def test_a_pass_is_said_to_go_to_its_receiver_only_when_he_was_the_one_meant(monkeypatch):
    for case in built(monkeypatch):
        text = case["claim"].text
        if case["true"] and (" to h" in text or "picks out" in text):
            (e,) = case["evidence"]
            assert e["intended"] in (None, e["receiver"]), text
    completed = [c["evidence"][0]["id"] for c in built(monkeypatch) if c["kind"] == "true: completed pass"]
    assert completed == ["e001"]  # the one completed pass meant for its receiver


def test_a_goal_without_a_scorer_gets_no_claim(monkeypatch):
    cases = built(monkeypatch)
    assert not [c for c in cases if "None" in c["claim"].text]
    assert [c["claim"].text for c in cases if c["kind"] == "true: goal"] == ["h9 scores."]


def test_a_failed_tackle_is_still_used_where_its_words_fit(monkeypatch):
    # "a risky tackle" and "a bold challenge" are true of any tackle; only "wins the ball" needs a win.
    kinds = {c["kind"] for c in built(monkeypatch) if c["evidence"][0]["id"] == "e002"}
    assert {"true: negative interpretation", "true: held-out tone, bold challenge"} <= kinds
    assert not kinds & {"true: tackle", "true: interpreted tackle"}
