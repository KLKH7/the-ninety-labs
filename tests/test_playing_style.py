"""Playing style on planted passes: channels, crosses, the keeper, counter-attacks, one-twos."""

import pytest

from ninety.agents import companion_match as companion
from ninety.agents.factcheck import Claim
from ninety.agents.insight_check import verify
from ninety.intel import style

CLUBS = {"home": "London Athletic", "away": "Lisbon Esportes"}


def p(eid, t, team, x, y, ex, ey, outcome="success", player=None, receiver=None):
    return {
        "id": eid,
        "t": t,
        "frame": round(t * 25),
        "type": "pass",
        "team": team,
        "x": x,
        "y": y,
        "end_x": ex,
        "end_y": ey,
        "outcome": outcome,
        "player": player,
        "receiver": receiver,
        "confidence": 0.9,
    }


def ev(eid, t, kind, team, x=50.0, y=34.0, **kw):
    return {
        "id": eid,
        "t": t,
        "frame": round(t * 25),
        "type": kind,
        "team": team,
        "x": x,
        "y": y,
        "confidence": 0.9,
        **kw,
    }


def test_channels_are_named_as_each_team_attacks():
    rows = style.passes(
        [
            p("v1", 1, "home", 40, 60, 50, 60),
            p("v2", 2, "home", 40, 60, 50, 60),
            p("v3", 3, "home", 40, 60, 50, 60),
            p("v4", 4, "home", 40, 10, 50, 10),
            p("v5", 5, "away", 60, 60, 50, 60),
        ]
    )
    home = style.channels(rows, "home", 1, 5, "London Athletic")
    assert home["shares"] == {"left": 75, "centre": 0, "right": 25} and home["most"] == "left"
    assert style.channels(rows, "away", 1, 5, "Lisbon Esportes")["most"] == "right"  # y = 60 is away's right
    bands = {b["channel"]: (b["y0"], b["y1"]) for b in home["visual"]["bands"]}
    assert bands["left"][0] > bands["right"][0]  # home's left is high y


def test_a_channel_share_is_said_of_its_channel():
    rows = style.passes([p("v1", 1, "home", 40, 60, 50, 60)] * 3 + [p("v4", 4, "home", 40, 10, 50, 10)])
    fact = {**style.channels(rows, "home", 1, 5, "London Athletic"), "clubs": CLUBS}
    known = {fact["id"]: fact}
    [text] = companion.code_texts(fact)
    assert verify(Claim(text, [fact["id"]]), known, CLUBS).ok, text
    wrong = "London Athletic played most through the right: 75% of their passes started there."
    assert not verify(Claim(wrong, [fact["id"]]), known, CLUBS).ok  # 75% is the left's share
    assert not verify(
        Claim("London Athletic sent 25% of their passes down the left.", [fact["id"]]), known, CLUBS
    ).ok


def test_crosses_are_wide_final_third_passes_into_the_box():
    rows = style.passes(
        [
            p("c1", 1, "home", 80, 62, 95, 34),
            p("c2", 2, "home", 80, 62, 90, 60),
            p("c3", 3, "home", 80, 34, 95, 34),
            p("c4", 4, "away", 25, 6, 10, 34, "fail"),
        ]
    )
    assert (
        style.crosses(rows, "home", 1, 5, "London Athletic")["value"] == 1
    )  # c2 ends outside, c3 is central
    away = style.crosses(rows, "away", 1, 5, "Lisbon Esportes")
    assert (away["value"], away["completed"]) == (1, 0)


def test_keeper_distribution_needs_the_keeper_named_by_position():
    rows = style.passes(
        [p("k1", 1, "home", 5, 34, 50, 34, player="h-t1"), p("k2", 2, "home", 5, 34, 20, 30, player="h-t1")]
    )
    people = {"h-t1": {"team": "home", "role": "GK", "position": "goalkeeper"}}
    k = style.keeper(rows, "home", 1, 5, "London Athletic", people)
    assert (k["value"], k["short"], k["lands"]["middle"]) == (1, 1, 1)
    assert (
        style.keeper(rows, "home", 1, 5, "London Athletic", {"h-t1": {**people["h-t1"], "position": None}})
        is None
    )


def test_a_counter_attack_is_a_regain_then_a_shot_before_losing_it():
    events = [
        ev("v1", 10, "pass", "away", x=40, outcome="fail"),
        ev("v2", 11, "interception", "home", x=40),
        ev("v3", 13, "pass", "home", x=60, outcome="success"),
        ev("v4", 17.3, "shot", "home", x=90),
    ]
    [c] = style.counters(events)
    assert (c["team"], c["value"], c["metres"]) == ("home", 6.3, 50)
    dead = events[:3] + [ev("v9", 14, "out_of_play", "home"), events[3]]
    assert style.counters(dead) == []
    lost = events[:3] + [ev("v8", 14, "interception", "away"), events[3]]
    assert style.counters(lost) == []


@pytest.mark.parametrize("gap, between, want", [(3.0, False, 1), (6.0, False, 0), (3.0, True, 0)])
def test_one_two(gap, between, want):
    rows = [p("a", 10, "home", 40, 30, 50, 30, player="h-t1", receiver="h-t2")]
    if between:
        rows.append(p("x", 11, "home", 50, 30, 55, 40, player="h-t2", receiver="h-t3"))
    rows.append(p("b", 10 + gap, "home", 50, 30, 60, 32, player="h-t2", receiver="h-t1"))
    assert len(style.one_twos(style.passes(rows))) == want


def test_a_pass_to_himself_and_back_is_no_one_two():
    # The simulator logs a knock-on as a pass whose receiver is the passer (runs/u7: 22 of 265): two
    # of them in a row looked like a one-two between a player and himself.
    rows = [
        p("a", 10, "home", 40, 30, 45, 30, player="h-t1", receiver="h-t1"),
        p("b", 12, "home", 45, 30, 50, 31, player="h-t1", receiver="h-t1"),
    ]
    assert style.one_twos(style.passes(rows)) == []


def test_style_questions_route_to_the_style_tool():
    assert companion.route("Why are London Athletic playing like this?")[0] == "style"
    assert companion.route("Is their keeper going long?")[0] == "style"


def test_long_and_short_counts_keep_their_own_words():
    fact = {
        "id": "style:keeper:home:m1-15",
        "kind": "keeper",
        "team": "home",
        "club": "London Athletic",
        "value": 1,
        "unit": "times",
        "confident": True,
        "minute_from": 1,
        "minute_to": 15,
        "also": [[1, "times", style.LONG_CONTEXT], [2, "times", style.SHORT_CONTEXT]],
    }
    known = {fact["id"]: fact}
    ok = "London Athletic went long 1 time and short 2 times from minute 1 to minute 15."
    assert verify(Claim(ok, [fact["id"]]), known, CLUBS).ok
    assert not verify(Claim(ok.replace("short 2", "short 1"), [fact["id"]]), known, CLUBS).ok
    assert not verify(Claim(ok.replace("long 1 time", "long 2 times"), [fact["id"]]), known, CLUBS).ok
