"""The insight fact-check: true claims pass, each planted defect is caught, unsure ones are held."""

import pytest

from ninety.agents.contracts import status_for
from ninety.agents.factcheck import Claim
from ninety.agents.insight_check import verify
from ninety.intel.counter_press import WITHIN
from ninety.intel.teamsheet import Fixture

FX = Fixture(7, "OAK", "FEN")
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


# The merge queue's second review: 61 paraphrases (its adv.py), each must be rejected or passed as
# marked. The direction check is closed-world, so a paraphrase it does not know is refused.
NOREGAIN = {**PRESS_LOST}
SUMMARY0 = {
    "id": "cps:z",
    "kind": "counter_press",
    "metric": "regains_within_5s",
    "team": "away",
    "club": "Lisbon Esportes",
    "minute_from": 1,
    "minute_to": 15,
    "value": 0,
    "unit": "regains",
    "confident": True,
}
SUMMARY2 = {**SUMMARY0, "id": "cps:t", "value": 2}
PASSFAIL = {**OPTIONS, "id": "po:f", "outcome": "fail", "target_open": False, "value": 0, "lo": 0, "hi": 0}
PASSFAIL1 = {**PASSFAIL, "id": "po:f1", "value": 3}
K = {f["id"]: f for f in (COUNTER, PRESS_LOST, OPTIONS, OVERLOAD, SUMMARY0, SUMMARY2, PASSFAIL, PASSFAIL1)}
PARAPHRASES = [
    # (text, fid, should_reject)
    ("Lisbon Esportes never won it back.", "cp:v7", True),
    ("Lisbon Esportes never got the ball back.", "cp:v7", True),
    ("Lisbon Esportes failed to regain possession.", "cp:v7", True),
    ("Lisbon Esportes did not regain the ball.", "cp:v7", True),
    ("Lisbon Esportes lost it for good.", "cp:v7", True),
    ("Lisbon Esportes could not recover the ball.", "cp:v7", True),
    ("Lisbon Esportes got it back within 5 seconds.", "cp:v8", True),
    ("Lisbon Esportes recovered the ball after losing it.", "cp:v8", True),
    ("Lisbon Esportes took it back.", "cp:v8", True),
    ("Lisbon Esportes had the ball back in 2 seconds.", "cp:v8", True),
    ("Lisbon Esportes won possession straight back.", "cp:v8", True),
    ("Lisbon Esportes won it back within 5 seconds.", "cp:v8", True),
    ("Lisbon Esportes won it back 2.4 seconds after losing it.", "cp:v7", False),
    ("London Athletic played it with nobody open ahead.", "po:v9", True),
    ("London Athletic played it with no one free ahead.", "po:v9", True),
    ("London Athletic had no teammates open ahead.", "po:v9", True),
    ("London Athletic had zero open teammates ahead.", "po:v9", True),
    ("London Athletic had none open ahead.", "po:v9", True),
    ("London Athletic had 0 open teammates ahead.", "po:v9", True),
    ("London Athletic had only 1 open teammate ahead.", "po:v9", True),
    ("London Athletic lost a pass with no open teammate further forward.", "po:v9", True),
    ("London Athletic gave away a pass with 3 open teammates ahead.", "po:v9", True),
    ("London Athletic's pass was intercepted with 3 open teammates ahead.", "po:v9", True),
    ("London Athletic's pass was cut out with 3 open teammates ahead.", "po:v9", True),
    ("London Athletic's pass went astray with 3 open teammates ahead.", "po:v9", True),
    ("London Athletic overhit the pass with 3 open teammates ahead.", "po:v9", True),
    ("London Athletic had 3 open teammates ahead but the pass failed.", "po:v9", True),
    ("London Athletic had 3 open teammates ahead and the pass did not arrive.", "po:v9", True),
    ("London Athletic had 3 open teammates ahead but the pass was incomplete.", "po:v9", True),
    ("London Athletic had 3 open teammates ahead and chose to pass to a marked player.", "po:v9", True),
    ("London Athletic had 3 open teammates ahead and played it to a covered man.", "po:v9", True),
    ("London Athletic had 3 open teammates ahead and passed to someone else.", "po:v9", True),
    (
        "London Athletic had 3 open teammates ahead and the pass went to a teammate who was marked.",
        "po:v9",
        True,
    ),
    ("London Athletic had 3 open teammates ahead but lost the pass.", "po:v9", True),
    ("London Athletic had 3 open teammates ahead and kept the ball.", "po:f1", True),
    ("London Athletic had 3 open teammates ahead and completed the pass.", "po:f1", True),
    ("London Athletic had 3 open teammates ahead and the pass found an open teammate.", "po:f1", True),
    ("London Athletic had 3 open teammates ahead and the pass reached a teammate.", "po:f1", True),
    ("London Athletic had 3 open teammates ahead and the pass was successful.", "po:f1", True),
    ("London Athletic had 3 open teammates ahead and the pass came off.", "po:f1", True),
    ("London Athletic had 3 open teammates ahead and the pass got through.", "po:f1", True),
    ("London Athletic had no open teammate ahead and lost the pass.", "po:f", False),
    ("Lisbon Esportes had no regains from minute 1 to minute 15.", "cps:t", True),
    ("Lisbon Esportes had only 2 regains from minute 1 to minute 15.", "cps:t", False),
    ("Lisbon Esportes had 2 regains from minute 1 to minute 15.", "cps:z", True),
    ("Lisbon Esportes did not win it back once from minute 1 to minute 15.", "cps:t", True),
    ("Lisbon Esportes never won it back from minute 1 to minute 15.", "cps:t", True),
    ("Lisbon Esportes won it back from minute 1 to minute 15.", "cps:z", True),
    ("Lisbon Esportes made zero regains from minute 1 to minute 15.", "cps:t", True),
    ("Lisbon Esportes made not one regain from minute 1 to minute 15.", "cps:t", True),
    ("Lisbon Esportes made none of their regains from minute 1 to minute 15.", "cps:t", True),
    ("Lisbon Esportes did not make a single regain from minute 1 to minute 15.", "cps:t", True),
    ("Lisbon Esportes won none of it back from minute 1 to minute 15.", "cps:t", True),
    ("London Athletic built no overloads in minute 12.", "ov:v3", True),
    ("London Athletic built zero overloads in minute 12.", "ov:v3", True),
    ("London Athletic built an overload in minute 12.", "ov:v3", False),
    ("London Athletic were never outnumbered in minute 12.", "ov:v3", False),
    ("London Athletic never had an overload in minute 12.", "ov:v3", True),
    ("London Athletic did not have an overload in minute 12.", "ov:v3", True),
    ("London Athletic had no extra players in minute 12.", "ov:v3", True),
    ("London Athletic had no extra man in minute 12.", "ov:v3", True),
]


@pytest.mark.parametrize("text, fid, reject", PARAPHRASES)
def test_paraphrases_of_a_direction(text, fid, reject):
    v = verify(Claim(text, [fid]), K, CLUBS, NAMED, NAMES)
    assert (not v.ok) is reject, (text, v.reasons)
