"""The insight fact-check: true claims pass, each planted defect is caught, unsure ones are held."""

import pytest

from ninety.agents.contracts import status_for
from ninety.agents.factcheck import Claim
from ninety.agents.insight_check import verify
from ninety.intel.counter_press import WITHIN
from ninety.intel.teamsheet import Fixture

FX = Fixture(7, "LON", "LIS")
CLUBS = FX.clubs  # home London Athletic, away Lisbon Esportes
LB = FX.sheet("home")[4]  # the left-back on London Athletic's sheet

LINE_BREAK = {
    "id": "lb:v1",
    "kind": "line_break",
    "metric": "opponents_bypassed",
    "team": "home",
    "club": "London Athletic",
    "minute": 23,
    "t": 1330.0,
    "value": 4,
    "unit": "opponents",
    "lo": 4,
    "hi": 4,
    "confident": True,
    "event": "v1",
    "event_confidence": 0.9,
    "team_confidence": 0.9,
    "passer": "h-t5",
    "receiver": "h-t9",
    "also": [[1, "passes"]],
    "visual": {"kind": "line_break"},
}
COUNTER = {
    "id": "cp:v7",
    "kind": "counter_press",
    "metric": "pressers",
    "team": "away",
    "club": "Lisbon Esportes",
    "minute": 30,
    "t": 1790.0,
    "value": 3,
    "unit": "players",
    "lo": 3,
    "hi": 3,
    "confident": True,
    "event": "v7",
    "event_confidence": 0.8,
    "regain_s": 2.4,
    "regained": True,
    "also": [[5.0, "s", WITHIN], [2.4, "s"]],
    "visual": {"kind": "counter_press"},
}
OVERLOAD = {
    "id": "ov:v3",
    "kind": "overload",
    "metric": "extra_players",
    "team": "home",
    "club": "London Athletic",
    "minute": 12,
    "t": 700.0,
    "value": 3,
    "unit": "extra players",
    "lo": 3,
    "hi": 3,
    "confident": True,
    "own_players": 4,
    "other_players": 1,
    "also": [[4, "players"], [1, "players", r"\bagainst\s+$"]],
}
KNOWN = {f["id"]: f for f in (LINE_BREAK, COUNTER, OVERLOAD)}
NAMED = {
    "h-t5": {
        "track": "h-t5",
        "team": "home",
        "club": "London Athletic",
        "role": "LB",
        "share": 0.9,
        "name": LB.name,
        "position": "left-back",
        "line": "defender",
        "sheet_name": LB.name,
    }
}
UNNAMED = {"h-t5": {**NAMED["h-t5"], "name": None, "position": None, "share": 0.5}}
NAMES = [s.name for t in ("home", "away") for s in FX.sheet(t)]


def run(text, evidence=("lb:v1",), known=KNOWN, people=NAMED):
    return verify(Claim(text, list(evidence)), known, CLUBS, people, NAMES)


@pytest.mark.parametrize(
    "text, evidence",
    [
        (
            "In minute 23, London Athletic played a pass that took 4 Lisbon Esportes players out of the "
            "game.",
            ("lb:v1",),
        ),
        (
            f"In minute 23, {LB.name} played a pass that took 4 Lisbon Esportes players out of the game.",
            ("lb:v1",),
        ),
        (f"{LB.name}'s pass in minute 23 bypassed 4 opponents.", ("lb:v1",)),
        ("London Athletic's left-back cut through 4 Lisbon Esportes players with one pass.", ("lb:v1",)),
        (
            "Lisbon Esportes won it back 2.4 seconds after losing it, with 3 players around the ball.",
            ("cp:v7",),
        ),
        ("Lisbon Esportes won the ball back within five seconds, with three players pressing.", ("cp:v7",)),
        ("In minute 12, London Athletic had 4 players against 1 player around the ball.", ("ov:v3",)),
        ("London Athletic had 3 extra players around the ball in minute 12.", ("ov:v3",)),
    ],
)
def test_true_claims_pass(text, evidence):
    v = run(text, evidence)
    assert v.ok, v.reasons


@pytest.mark.parametrize(
    "text, evidence, why",
    [
        (
            "London Athletic took 5 Lisbon Esportes players out of the game in minute 23.",
            ("lb:v1",),
            "number",
        ),
        ("London Athletic took 4 metres out of Lisbon Esportes in minute 23.", ("lb:v1",), "number"),
        ("London Athletic took fifty Lisbon Esportes players out of the game.", ("lb:v1",), "number"),
        ("Lisbon Esportes bypassed 4 London Athletic players in minute 23.", ("lb:v1",), "not the side"),
        (f"{LB.name} took 4 London Athletic players out of the game.", ("lb:v1",), "passing side"),
        ("The home team bypassed 4 opponents in minute 23.", ("lb:v1",), "home or away"),
        ("h-t5 bypassed 4 opponents in minute 23.", ("lb:v1",), "an id"),
        ("London Athletic bypassed 4 opponents in minute 24.", ("lb:v1",), "minute"),
        (f"{FX.sheet('home')[9].name} bypassed 4 opponents.", ("lb:v1",), "not a player"),
        ("London Athletic's striker bypassed 4 opponents.", ("lb:v1",), "striker"),
        ("London Athletic overloaded Lisbon Esportes's left with 4 players.", ("lb:v1",), "overload"),
        ("Lisbon Esportes won it back within 5 seconds.", ("lb:v1",), "counter_press"),
        ("London Athletic bypassed 4 opponents.", (), "cite"),
        ("London Athletic bypassed 4 opponents.", ("lb:v99",), "unknown"),
        ("Lisbon Esportes won it back 3 seconds after losing it.", ("cp:v7",), "number"),
        (
            "Lisbon Esportes won it back 5 seconds after losing it.",
            ("cp:v7",),
            "number",
        ),  # the window, not the regain
        ("Lisbon Esportes had 3 players near the ball in the next 2.4 seconds.", ("cp:v7",), "number"),
        ("London Athletic had 3 players against 4 players around the ball.", ("ov:v3",), "number"),
        (
            "London Athletic had 4 players against 3 players around the ball.",
            ("ov:v3",),
            "number",
        ),  # 3 is the extra
    ],
)
def test_planted_false_claims_are_rejected(text, evidence, why):
    v = run(text, evidence)
    assert not v.ok and status_for(v) == "rejected", v
    assert any(why in r for r in v.reasons), v.reasons


def test_a_name_below_its_gate_is_held():
    v = run(f"{LB.name} bypassed 4 opponents in minute 23.", people=UNNAMED)
    assert status_for(v) == "held"
    assert (
        run("London Athletic's left-back bypassed 4 opponents.", people=UNNAMED).category == "low_confidence"
    )


def test_an_unsure_fact_is_held():
    known = {"lb:v1": {**LINE_BREAK, "confident": False, "lo": 3, "hi": 6}}
    assert status_for(run("London Athletic bypassed 4 opponents in minute 23.", known=known)) == "held"


def test_a_weak_detection_is_held():
    known = {"lb:v1": {**LINE_BREAK, "event_confidence": 0.3}}
    assert status_for(run("London Athletic bypassed 4 opponents in minute 23.", known=known)) == "held"


def test_a_wrong_claim_on_an_unsure_fact_is_rejected_not_held():
    known = {"lb:v1": {**LINE_BREAK, "confident": False}}
    assert status_for(run("London Athletic bypassed 7 opponents.", known=known)) == "rejected"


def test_ordinary_english_is_not_a_team_word():
    assert run(
        "London Athletic pulled Lisbon Esportes away from their goal and bypassed 4 players in minute 23."
    ).ok


# Polarity: the merge queue's review found sentences that reverse a fact passing (lesson 11).
PRESS_LOST = {
    "id": "cp:v8",
    "kind": "counter_press",
    "metric": "pressers",
    "team": "away",
    "club": "Lisbon Esportes",
    "minute": 30,
    "t": 1790.0,
    "value": 1,
    "unit": "players",
    "lo": 1,
    "hi": 1,
    "confident": True,
    "regained": False,
    "regain_s": None,
    "also": [[5.0, "s", WITHIN]],
}
OPTIONS = {
    "id": "po:v9",
    "kind": "pass_options",
    "metric": "open_teammates_ahead",
    "team": "home",
    "club": "London Athletic",
    "minute": 31,
    "t": 1850.0,
    "value": 3,
    "unit": "teammates",
    "lo": 3,
    "hi": 3,
    "confident": True,
    "outcome": "success",
    "target_open": True,
    "also": [[1, "passes"]],
}
POLARITY = {f["id"]: f for f in (COUNTER, PRESS_LOST, OPTIONS)}


@pytest.mark.parametrize(
    "text, fid",
    [
        ("Lisbon Esportes won the ball back after losing it.", "cp:v8"),
        ("Lisbon Esportes won it back within 5 seconds.", "cp:v8"),
        ("Lisbon Esportes never won it back.", "cp:v7"),
        ("London Athletic lost a pass with no open teammate further forward.", "po:v9"),
        ("London Athletic played it with nobody open ahead.", "po:v9"),
        ("London Athletic had 3 open teammates ahead but lost the pass.", "po:v9"),
        ("London Athletic had 3 teammates free, but the pass went elsewhere.", "po:v9"),
    ],
)
def test_a_sentence_that_reverses_the_fact_is_rejected(text, fid):
    v = verify(Claim(text, [fid]), POLARITY, CLUBS, NAMED, NAMES)
    assert not v.ok and status_for(v) == "rejected", v


@pytest.mark.parametrize(
    "text, fid",
    [
        ("Lisbon Esportes won it back 2.4 seconds after losing it.", "cp:v7"),
        ("Lisbon Esportes lost the ball and had 1 player near it in the next 5 seconds.", "cp:v8"),
        ("London Athletic had 3 teammates free and the pass found an open teammate.", "po:v9"),
    ],
)
def test_a_sentence_that_keeps_the_facts_direction_passes(text, fid):
    v = verify(Claim(text, [fid]), POLARITY, CLUBS, NAMED, NAMES)
    assert v.ok, v.reasons


def test_none_of_something_needs_a_zero():
    summary = {
        "id": "ov:home:m1-15",
        "kind": "overload",
        "metric": "overload_moments",
        "team": "home",
        "club": "London Athletic",
        "minute_from": 1,
        "minute_to": 15,
        "value": 2,
        "unit": "overloads",
        "confident": True,
    }
    v = verify(
        Claim("London Athletic built no overloads from minute 1 to minute 15.", [summary["id"]]),
        {summary["id"]: summary},
        CLUBS,
    )
    assert not v.ok
