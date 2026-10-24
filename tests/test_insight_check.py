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
    # A reversal never passes (held or rejected); a true sentence is never rejected (it may be held:
    # the closed check holds words it cannot vouch for, which is the cost of failing closed).
    status = status_for(verify(Claim(text, [fid]), K, CLUBS, NAMED, NAMES))
    assert status != "verified" if reject else status != "rejected", (text, status)


# What failing closed costs: true sentences in words the direction check does not know are held, not
# passed (they reach the phone as code's sentence instead). Measured here, not hidden.
TRUE_PARAPHRASES = [
    ("Lisbon Esportes won it back 2.4 seconds after losing it.", "cp:v7", "verified"),
    ("Lisbon Esportes regained possession 2.4 seconds later.", "cp:v7", "held"),
    ("Lisbon Esportes got the ball back quickly.", "cp:v7", "held"),
    ("Lisbon Esportes lost the ball and had 1 player near it in the next 5 seconds.", "cp:v8", "verified"),
    ("Lisbon Esportes did not win it back.", "cp:v8", "verified"),
    ("Lisbon Esportes could not regain the ball.", "cp:v8", "held"),
    ("London Athletic had 3 teammates free further up the pitch.", "po:v9", "verified"),
    ("London Athletic completed the pass with 3 open teammates ahead.", "po:v9", "verified"),
    ("London Athletic kept possession with 3 options free.", "po:v9", "held"),
    ("London Athletic lost the ball with no teammate free further up the pitch.", "po:f", "verified"),
]


@pytest.mark.parametrize("text, fid, status", TRUE_PARAPHRASES)
def test_true_paraphrases_pass_or_are_held_never_rejected(text, fid, status):
    v = verify(Claim(text, [fid]), K, CLUBS, NAMED, NAMES)
    assert status_for(v) == status, (text, v.reasons)


# The merge queue's third review: 64 more reversals and 20 true sentences (its adv2.py and
# true2.py). With the closed check every reversal is held or rejected, and no true one is rejected.
R_SUMMARY0 = {
    "also": [[2, "turnovers"], [5.0, "s", WITHIN]],
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
R_SUMMARY2 = {**R_SUMMARY0, "id": "cps:t", "value": 2, "also": [[4, "turnovers"], [5.0, "s", WITHIN]]}
R_PASSFAIL = {**OPTIONS, "id": "po:f", "outcome": "fail", "target_open": False, "value": 0, "lo": 0, "hi": 0}
R_R_PASSFAIL1 = {**R_PASSFAIL, "id": "po:f1", "value": 3, "lo": 3, "hi": 3}
R_NOOPEN0 = {
    "id": "po:home:m1-15",
    "kind": "pass_options",
    "metric": "passes_with_no_open_teammate_ahead",
    "team": "home",
    "club": "London Athletic",
    "minute_from": 1,
    "minute_to": 15,
    "value": 0,
    "unit": "passes",
    "lo": 0,
    "hi": 0,
    "confident": True,
    "passes": 9,
    "confident_passes": 9,
}
R_NOOPEN4 = {**R_NOOPEN0, "id": "po:n4", "value": 4, "lo": 4, "hi": 4}
K2 = {
    f["id"]: f
    for f in (
        COUNTER,
        PRESS_LOST,
        OPTIONS,
        R_SUMMARY0,
        R_SUMMARY2,
        R_PASSFAIL,
        R_R_PASSFAIL1,
        OVERLOAD,
        R_NOOPEN0,
        R_NOOPEN4,
    )
}
L = "Lisbon Esportes"
H = "London Athletic"
REVERSALS2 = [  # all should be rejected
    (f"{L} immediately regained the ball.", "cp:v8"),
    (f"{L} lost the ball and quickly recovered it.", "cp:v8"),
    (f"{L} lost the ball but the press paid off.", "cp:v8"),
    (f"{L} lost the ball and had it again within 3 seconds.", "cp:v8"),
    (f"{L} lost the ball and the ball was theirs again.", "cp:v8"),
    (f"{L} lost the ball, then reclaimed it.", "cp:v8"),
    (f"{L} lost the ball and the press succeeded.", "cp:v8"),
    (f"{L} lost the ball and the counter-press worked.", "cp:v8"),
    (f"{L} lost the ball and the press failed to win it.", "cp:v7"),
    (f"{L} lost the ball and the opponents kept it despite the press.", "cp:v7"),
    (f"{L} lost the ball and the press was beaten.", "cp:v7"),
    (f"{L} lost the ball and could not get it back.", "cp:v7"),
    (f"{L} lost the ball and 3 players pressed but in vain.", "cp:v7"),
    (f"{L} lost the ball and the press went unrewarded.", "cp:v7"),
    (f"{L} lost the ball and never recovered it.", "cp:v7"),
    (f"{L} lost the ball and 3 players hunted it down in vain.", "cp:v7"),
    (f"{L} regained possession {2} times from minute 1 to minute 15.", "cps:z"),
    (f"{L} made 2 regains from minute 1 to minute 15.", "cps:z"),
    (f"{L} lost the ball 4 times and won it back every time from minute 1 to minute 15.", "cps:z"),
    (f"{L} lost the ball 4 times and recovered none of them from minute 1 to minute 15.", "cps:t"),
    (f"{L} lost the ball 4 times and never got it back from minute 1 to minute 15.", "cps:t"),
    (f"{L} lost the ball 4 times and reclaimed it twice from minute 1 to minute 15.", "cps:z"),
    (f"{L} lost the ball 4 times and the press got nothing from minute 1 to minute 15.", "cps:t"),
    (f"{L} had 0 regains from minute 1 to minute 15.", "cps:t"),
    (f"{H} had 3 open teammates ahead, but the pass broke down.", "po:v9"),
    (f"{H} had 3 open teammates ahead, but the ball was turned over.", "po:v9"),
    (f"{H} had 3 open teammates ahead, yet the pass was blocked.", "po:v9"),
    (f"{H} had 3 open teammates ahead, yet the pass missed its target.", "po:v9"),
    (f"{H} had 3 open teammates ahead, and the pass hit a defender.", "po:v9"),
    (f"{H} had 3 open teammates ahead, and gifted possession to the opponents.", "po:v9"),
    (f"{H} had 3 open teammates ahead, but the receiver was tightly guarded.", "po:v9"),
    (f"{H} had 3 open teammates ahead, and the pass was delivered to a defended player.", "po:v9"),
    (f"{H} had 3 open teammates ahead and the pass was perfectly delivered.", "po:f1"),
    (f"{H} had 3 open teammates ahead and the pass was accurate.", "po:f1"),
    (f"{H} had 3 open teammates ahead and the pass was received by a free man.", "po:f1"),
    (f"{H} had 3 open teammates ahead and the pass hit the free man.", "po:f1"),
    (f"{H} had 3 open teammates ahead and the pass was on target.", "po:f1"),
    (f"{H} had 3 open teammates ahead and the pass picked out a free man.", "po:f1"),
    (f"{H} had 3 open teammates ahead and the pass was a success.", "po:f1"),
    (f"{H} had 3 open teammates ahead and the move continued.", "po:f1"),
    (f"{H} had 4 passes with nobody ahead to receive.", "po:n4"),
    (f"{H} had 4 passes where every teammate was marked.", "po:n4"),
    (f"{H} had 4 passes with a free teammate ahead.", "po:n4"),
    (f"{H} had 4 passes with every option open.", "po:n4"),
    (f"{H} had no passes with an unmarked teammate ahead.", "po:n4"),
    (f"{H} had all passes with a free teammate ahead and not one was stuck.", "po:n4"),
    (f"{H} never lacked an open teammate ahead.", "po:n4"),
    (f"{H} had 4 passes with no open teammate ahead.", "po:n0"),
    (f"{H} were outnumbered 1 to 4 in minute 12.", "ov:v3"),
    (f"{H} lacked any numerical edge in minute 12.", "ov:v3"),
    (f"{H} had a deficit of players around the ball in minute 12.", "ov:v3"),
    (f"{H} had no numerical advantage around the ball in minute 12.", "ov:v3"),
    (f"{H} had an even fight around the ball in minute 12, with no extra man.", "ov:v3"),
    (f"{H} were level on numbers in minute 12.", "ov:v3"),
    (f"{H} held a numerical edge in minute 12.", "ov:v1"),
    (f"{H} had no overload to speak of in minute 12.", "ov:v3"),
    (f"{H} never built an overload in minute 12.", "ov:v3"),
    (f"{H} were not outnumbered, yet had no overloads in minute 12.", "ov:v3"),
    # mixed two-fact sentences (reverse one)
    (
        f"{L} lost the ball and won it back, while {H} had 3 open teammates ahead but lost the pass.",
        "cp:v8,po:v9",
    ),
    (
        f"{L} lost the ball and never won it back, while {H} had 3 open teammates ahead and completed the "
        f"pass.",
        "cp:v7,po:v9",
    ),
    (
        f"{L} lost the ball, and the press did not work, yet {H} had 3 open teammates ahead and completed "
        f"the pass.",
        "cp:v8,po:v9",
    ),
    (
        f"{L} won it back after losing it, and {H} had 3 open teammates ahead and kept the ball, but {L} "
        f"stole it.",
        "cp:v7,po:v9",
    ),
    (f"{H} had 3 open teammates ahead and had no extra players around the ball in minute 12.", "po:v9,ov:v3"),
    (f"{L} lost the ball and had 3 players near it, and {H} had no teammate open ahead.", "cp:v7,po:v9"),
]
TRUE2 = [
    (f"{L} lost the ball and won it back 2.4 seconds later.", "cp:v7"),
    (f"{L} lost the ball, then won it back within 5 seconds.", "cp:v7"),
    (f"After losing it, {L} sent 3 players to press and won the ball back.", "cp:v7"),
    (f"{L} lost the ball and 3 players pressed straight away.", "cp:v7"),
    (f"{L} lost the ball and sent 1 player to press, but did not win it back.", "cp:v8"),
    (f"{L} lost the ball and could not win it back.", "cp:v8"),
    (f"{L} lost the ball and only 1 player pressed.", "cp:v8"),
    (f"{L} lost the ball 4 times from minute 1 to minute 15 and won it back once.", "cps:t"),
    (f"{L} made 2 regains from minute 1 to minute 15.", "cps:t"),
    (f"{L} won the ball back 2 times from minute 1 to minute 15.", "cps:t"),
    (f"{L} had no regains from minute 1 to minute 15.", "cps:z"),
    (f"{H} had 3 teammates open further forward and completed the pass.", "po:v9"),
    (f"{H} had 3 open teammates ahead and the pass found one of them.", "po:v9"),
    (f"{H} had 3 open teammates ahead and played it to an open teammate.", "po:v9"),
    (f"{H} kept the ball with 3 teammates free ahead.", "po:v9"),
    (f"{H} lost the ball with 3 open teammates further up the pitch.", "po:f1"),
    (f"{H} had 3 open teammates ahead, but the pass went elsewhere and was lost.", "po:f1"),
    (f"{H} had no open teammate ahead and lost the pass.", "po:f"),
    (f"{H} had 4 passes with no open teammate ahead from minute 1 to minute 15.", "po:n4"),
    (f"{H} had 3 extra players around the ball in minute 12.", "ov:v3"),
]


@pytest.mark.parametrize("text, fids", REVERSALS2)
def test_no_reversal_passes(text, fids):
    assert status_for(verify(Claim(text, fids.split(",")), K2, CLUBS, NAMED, NAMES)) != "verified", text


@pytest.mark.parametrize("text, fids", TRUE2)
def test_no_true_sentence_is_rejected(text, fids):
    assert status_for(verify(Claim(text, fids.split(",")), K2, CLUBS, NAMED, NAMES)) != "rejected", text


# Each phrase the closed check accepts is pinned by a true sentence that needs it: drop the phrase
# from `_approved` and the sentence is held, so the test turns red (the review's surviving mutations).
PINNED = [
    ("Lisbon Esportes lost the ball and had 1 player near it in the next 5 seconds.", "cp:v8"),
    ("Lisbon Esportes won the ball back 2.4 seconds after losing it, with 3 players around it.", "cp:v7"),
    ("Lisbon Esportes lost the ball and could not win it back.", "cp:v8"),
    ("Lisbon Esportes lost the ball 2 times in open play and never won it back within 5 seconds.", "cps:z"),
    ("London Athletic had 3 teammates free further up the pitch and kept the ball.", "po:v9"),
    ("London Athletic completed the pass and found an open teammate.", "po:v9"),
    (
        "London Athletic had 3 teammates free further up the pitch, but the pass went elsewhere and was "
        "lost.",
        "po:f1",
    ),
    ("London Athletic lost the ball with no teammate free further up the pitch.", "po:f"),
    ("London Athletic had 3 extra players around the ball in minute 12.", "ov:v3"),
]


@pytest.mark.parametrize("text, fid", PINNED)
def test_each_approved_phrase_is_pinned(text, fid):
    v = verify(Claim(text, [fid]), K2, CLUBS, NAMED, NAMES)
    assert v.ok, (text, v.reasons)


# The merge queue's fourth review: 30 more reversals (its new30.py), each held or rejected.
REVERSALS3 = [
    (f"{L} lost the ball and the press snuffed out the break.", "cp:v8"),
    (f"{L} lost the ball and swarmed it straight back.", "cp:v8"),
    (f"{L} lost the ball and the hunt paid dividends.", "cp:v8"),
    (f"{L} lost the ball and snatched it off them.", "cp:v8"),
    (f"{L} lost the ball and the press delivered.", "cp:v8"),
    (f"{L} lost the ball and pinched it back.", "cp:v8"),
    (f"{L} lost the ball and the press came up empty.", "cp:v7"),
    (f"{L} lost the ball and 3 players chased shadows.", "cp:v7"),
    (f"{L} lost the ball and the opponents escaped the press.", "cp:v7"),
    (f"{L} lost the ball and the press was bypassed.", "cp:v7"),
    (f"{L} lost the ball and the opponents kept hold of it.", "cp:v7"),
    (f"{L} lost the ball and nothing came of the press.", "cp:v7"),
    (f"{H} had 3 open teammates ahead and the pass sailed out of play.", "po:v9"),
    (f"{H} had 3 open teammates ahead and the opponents snuffed out the pass.", "po:v9"),
    (f"{H} had 3 open teammates ahead and the pass was cleared.", "po:v9"),
    (f"{H} had 3 open teammates ahead and handed the ball to the opposition.", "po:v9"),
    (f"{H} had 3 open teammates ahead and the pass never made it.", "po:v9"),
    (f"{H} had 3 open teammates ahead and the pass fell short.", "po:v9"),
    (f"{H} had 3 open teammates ahead and the pass hit the target.", "po:f1"),
    (f"{H} had 3 open teammates ahead and the move came off nicely.", "po:f1"),
    (f"{H} had 3 open teammates ahead and the pass was well received.", "po:f1"),
    (f"{H} had 3 open teammates ahead and played it neatly.", "po:f1"),
    (f"{H} had 4 passes with a spare man ahead from minute 1 to minute 15.", "po:n4"),
    (f"{H} had 4 passes where every teammate was well covered from minute 1 to minute 15.", "po:n4"),
    (f"{H} were outnumbered around the ball in minute 12.", "ov:v3"),
    (f"{H} fell short of an extra man in minute 12.", "ov:v3"),
    (f"{H} did not have extra players in minute 12.", "ov:v3"),
    (f"{H} had fewer players than the opponents around the ball in minute 12.", "ov:v3"),
    (
        f"{L} lost the ball and the press snuffed it out, while {H} had 3 open teammates ahead and the "
        f"pass broke down.",
        "cp:v7,po:v9",
    ),
    (f"{L} lost the ball 4 times and the press paid off every time from minute 1 to minute 15.", "cps:z"),
]


@pytest.mark.parametrize("text, fids", REVERSALS3)
def test_no_reversal_of_the_fourth_review_passes(text, fids):
    assert status_for(verify(Claim(text, fids.split(",")), K2, CLUBS, NAMED, NAMES)) != "verified", text


# The merge queue's fifth review: 40 reversals made of glue words and the fact's own phrases, and 20
# true sentences (its new40.py). No reversal passes; no true sentence is rejected.
REVERSALS4 = [  # glue-only / idiom reversals; all should NOT be verified
    (f"{L} lost the ball but had it again straight away.", "cp:v8"),
    (f"{L} lost the ball and had the ball again.", "cp:v8"),
    (f"{L} lost the ball and it was theirs again.", "cp:v8"),
    (f"{L} lost the ball and then the ball was on their side again.", "cp:v8"),
    (f"{L} lost the ball but the ball came to them at the same moment.", "cp:v8"),
    (f"{L} lost the ball and had the ball in their possession.", "cp:v8"),
    (f"{L} lost the ball and it was all theirs.", "cp:v8"),
    (f"{L} lost the ball but had it after only a second.", "cp:v8"),
    (f"{L} lost the ball and then had it within 2 seconds.", "cp:v8"),
    (f"{L} lost the ball and the ball was with them again within 5 seconds.", "cp:v8"),
    (f"{L} lost the ball and pressed, and it was theirs.", "cp:v8"),
    (f"{L} lost the ball and had no ball after 3 seconds.", "cp:v7"),
    (f"{L} lost the ball and the ball stayed away from them.", "cp:v7"),
    (f"{L} lost the ball and it was gone for good.", "cp:v7"),
    (f"{L} lost the ball and that was it.", "cp:v7"),
    (f"{L} lost the ball and then it was the other side's ball.", "cp:v7"),
    (f"{L} lost the ball but it was the same for all of the time.", "cp:v7"),
    (f"{H} had 3 open teammates ahead and the pass was to a marked player.", "po:v9"),
    (f"{H} had 3 open teammates ahead and the pass was to an open teammate.", "po:f1"),
    (f"{H} had 3 open teammates ahead and the pass was to one of them.", "po:f1"),
    (f"{H} had 3 open teammates ahead and the pass went to them.", "po:f1"),
    (f"{H} had 3 open teammates ahead and the pass was in the same place as the open teammate.", "po:f1"),
    (f"{H} had 3 open teammates ahead and the pass was on the open teammate.", "po:f1"),
    (f"{H} had 3 open teammates ahead and the pass was theirs.", "po:v9"),
    (f"{H} had 4 passes with an open teammate ahead.", "po:n4"),
    (f"{H} had 4 passes with a teammate open ahead.", "po:n4"),
    (f"{H} had 4 passes with all teammates open ahead.", "po:n4"),
    (f"{H} had 4 passes with one open teammate there.", "po:n4"),
    (f"{H} had 4 passes with each teammate open.", "po:n4"),
    (f"{H} had 4 passes, all with open teammates further forward.", "po:n4"),
    (f"{L} lost the ball 4 times and had it again each time from minute 1 to minute 15.", "cps:z"),
    (f"{L} won it back 2 times, all of the time from minute 1 to minute 15.", "cps:z"),
    (f"{H} had 3 extra players, but only 1 player was there.", "ov:v3"),
    (f"{H} had an overload, but it was the same as the other side.", "ov:v3"),
    (f"{H} had 3 extra players and then the other side had them too.", "ov:v3"),
    (f"{H} had 3 extra players but the other side had all of them.", "ov:v3"),
    (
        f"{L} lost the ball and won it back, and {H} had 3 open teammates ahead and kept the ball.",
        "cp:v8,po:v9",
    ),
    (
        f"{L} lost the ball but had it again, and {H} had 3 open teammates ahead and the pass was to an "
        f"open teammate.",
        "cp:v8,po:f1",
    ),
    (f"{L} lost the ball, and {H} had 3 extra players but only 1 player was there.", "cp:v7,ov:v3"),
    (f"{L} lost the ball and had it again straight away, with 3 players pressing.", "cp:v8"),
]
TRUE4 = [
    (f"{L} lost the ball and won it back within 5 seconds.", "cp:v7"),
    (f"{L} lost the ball and 3 players pressed it.", "cp:v7"),
    (f"{L} lost the ball, sent 1 player to press and did not win it back.", "cp:v8"),
    (f"{L} lost the ball and 1 player pressed, but they never won it back.", "cp:v8"),
    (f"{L} lost the ball 4 times in open play and made 2 regains.", "cps:t"),
    (f"{L} made 2 regains from minute 1 to minute 15.", "cps:t"),
    (f"{L} had no regains from minute 1 to minute 15.", "cps:z"),
    (f"{H} had 3 open teammates ahead and completed the pass.", "po:v9"),
    (f"{H} completed the pass and found an open teammate.", "po:v9"),
    (f"{H} had 3 teammates free further forward and kept the ball.", "po:v9"),
    (f"{H} lost the pass; the pass went elsewhere with 3 teammates open.", "po:f1"),
    (f"{H} lost the ball and the pass went elsewhere.", "po:f1"),
    (f"{H} had 4 passes with no open teammate ahead from minute 1 to minute 15.", "po:n4"),
    (f"{H} made 4 passes with no open teammate further forward.", "po:n4"),
    (f"{H} had 3 extra players around the ball in minute 12.", "ov:v3"),
    (f"{H} built an overload in minute 12.", "ov:v3"),
    (f"{H} had 4 players against 1 player around the ball in minute 12.", "ov:v3"),
    (
        f"{L} lost the ball and won it back, and {H} had 3 open teammates ahead and completed the pass.",
        "cp:v7,po:v9",
    ),
    (f"{L} lost the ball with 1 player pressing, and {H} built an overload in minute 12.", "cp:v8,ov:v3"),
    (f"{H} had 3 open teammates ahead and completed the pass in minute 31.", "po:v9"),
]


@pytest.mark.parametrize("text, fids", REVERSALS4)
def test_no_glue_only_reversal_passes(text, fids):
    assert status_for(verify(Claim(text, fids.split(",")), K2, CLUBS, NAMED, NAMES)) != "verified", text


@pytest.mark.parametrize("item", TRUE4)
def test_no_true_sentence_of_the_fifth_review_is_rejected(item):
    text, fids = item[0], item[1]
    assert status_for(verify(Claim(text, fids.split(",")), K2, CLUBS, NAMED, NAMES)) != "rejected", text


# The glue list is pinned: each word taken out of it because it carries direction holds a sentence
# that would otherwise pass (put it back in GLUE and the test turns red).
GLUE_PINS = [  # each sentence's only word outside the fact's phrases, names and glue is the pinned one
    ("Lisbon Esportes lost the ball and had it again.", "cp:v8"),  # again (and it)
    ("Lisbon Esportes lost the ball and had the ball again.", "cp:v8"),  # again
    ("London Athletic had 4 passes open from minute 1 to minute 15.", "po:n4"),  # open
    ("London Athletic had 4 passes with a teammate from minute 1 to minute 15.", "po:n4"),  # teammate
    ("Lisbon Esportes lost the ball and had it.", "cp:v8"),  # it
    ("Lisbon Esportes lost the ball and that was the ball.", "cp:v7"),  # that
    ("Lisbon Esportes lost the ball and had the ball straight.", "cp:v8"),  # straight
    ("Lisbon Esportes lost the ball and had the same ball.", "cp:v8"),  # same
    ("Lisbon Esportes lost the ball away.", "cp:v8"),  # away
    ("Lisbon Esportes lost the ball only.", "cp:v7"),  # only
    ("Lisbon Esportes lost the ball and had all the ball.", "cp:v8"),  # all
    ("Lisbon Esportes lost the ball and had one.", "cp:v8"),  # one
]


@pytest.mark.parametrize("text, fid", GLUE_PINS)
def test_direction_words_are_not_glue(text, fid):
    assert status_for(verify(Claim(text, [fid]), K2, CLUBS, NAMED, NAMES)) != "verified", text


@pytest.mark.parametrize(
    "text, fid",
    [
        ("Lisbon Esportes had no regains from minute 1 to minute 15.", "cps:z"),
        ("London Athletic built an overload in minute 12.", "ov:v3"),
    ],
)
def test_review_phrases_are_pinned(text, fid):
    v = verify(Claim(text, [fid]), K2, CLUBS, NAMED, NAMES)
    assert v.ok, (text, v.reasons)
