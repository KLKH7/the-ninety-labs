"""The insight fact-check: true claims pass, each planted defect is caught, unsure ones are held."""

import pytest

from ninety.agents.contracts import status_for
from ninety.agents.factcheck import Claim
from ninety.agents.insight_check import verify
from ninety.intel.teamsheet import Fixture

FX = Fixture(7, "OAK", "FEN")
CLUBS = FX.clubs  # home Oakfield, away Fenwick
LB = FX.sheet("home")[4]  # the left-back on Oakfield's sheet

LINE_BREAK = {
    "id": "lb:v1",
    "kind": "line_break",
    "metric": "opponents_bypassed",
    "team": "home",
    "club": "Oakfield",
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
    "club": "Fenwick",
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
    "also": [[5.0, "s"], [2.4, "s"]],
    "visual": {"kind": "counter_press"},
}
KNOWN = {f["id"]: f for f in (LINE_BREAK, COUNTER)}
NAMED = {
    "h-t5": {
        "track": "h-t5",
        "team": "home",
        "club": "Oakfield",
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
        ("In minute 23, Oakfield played a pass that took 4 Fenwick players out of the game.", ("lb:v1",)),
        (f"In minute 23, {LB.name} played a pass that took 4 Fenwick players out of the game.", ("lb:v1",)),
        (f"{LB.name}'s pass in minute 23 bypassed 4 opponents.", ("lb:v1",)),
        ("Oakfield's left-back cut through 4 Fenwick players with one pass.", ("lb:v1",)),
        ("Fenwick won it back 2.4 seconds after losing it, with 3 players around the ball.", ("cp:v7",)),
        ("Fenwick won the ball back within five seconds, with three players pressing.", ("cp:v7",)),
    ],
)
def test_true_claims_pass(text, evidence):
    v = run(text, evidence)
    assert v.ok, v.reasons


@pytest.mark.parametrize(
    "text, evidence, why",
    [
        ("Oakfield took 5 Fenwick players out of the game in minute 23.", ("lb:v1",), "number"),
        ("Oakfield took 4 metres out of Fenwick in minute 23.", ("lb:v1",), "number"),
        ("Oakfield took fifty Fenwick players out of the game.", ("lb:v1",), "number"),
        ("Fenwick bypassed 4 Oakfield players in minute 23.", ("lb:v1",), "not the side"),
        (f"{LB.name} took 4 Oakfield players out of the game.", ("lb:v1",), "passing side"),
        ("The home team bypassed 4 opponents in minute 23.", ("lb:v1",), "home or away"),
        ("h-t5 bypassed 4 opponents in minute 23.", ("lb:v1",), "an id"),
        ("Oakfield bypassed 4 opponents in minute 24.", ("lb:v1",), "minute"),
        (f"{FX.sheet('home')[9].name} bypassed 4 opponents.", ("lb:v1",), "not a player"),
        ("Oakfield's striker bypassed 4 opponents.", ("lb:v1",), "striker"),
        ("Oakfield overloaded Fenwick's left with 4 players.", ("lb:v1",), "overload"),
        ("Fenwick won it back within 5 seconds.", ("lb:v1",), "counter_press"),
        ("Oakfield bypassed 4 opponents.", (), "cite"),
        ("Oakfield bypassed 4 opponents.", ("lb:v99",), "unknown"),
        ("Fenwick won it back 3 seconds after losing it.", ("cp:v7",), "number"),
    ],
)
def test_planted_false_claims_are_rejected(text, evidence, why):
    v = run(text, evidence)
    assert not v.ok and status_for(v) == "rejected", v
    assert any(why in r for r in v.reasons), v.reasons


def test_a_name_below_its_gate_is_held():
    v = run(f"{LB.name} bypassed 4 opponents in minute 23.", people=UNNAMED)
    assert status_for(v) == "held"
    assert run("Oakfield's left-back bypassed 4 opponents.", people=UNNAMED).category == "low_confidence"


def test_an_unsure_fact_is_held():
    known = {"lb:v1": {**LINE_BREAK, "confident": False, "lo": 3, "hi": 6}}
    assert status_for(run("Oakfield bypassed 4 opponents in minute 23.", known=known)) == "held"


def test_a_weak_detection_is_held():
    known = {"lb:v1": {**LINE_BREAK, "event_confidence": 0.3}}
    assert status_for(run("Oakfield bypassed 4 opponents in minute 23.", known=known)) == "held"


def test_a_wrong_claim_on_an_unsure_fact_is_rejected_not_held():
    known = {"lb:v1": {**LINE_BREAK, "confident": False}}
    assert status_for(run("Oakfield bypassed 7 opponents.", known=known)) == "rejected"


def test_ordinary_english_is_not_a_team_word():
    assert run("Oakfield pulled Fenwick away from their goal and bypassed 4 players in minute 23.").ok
