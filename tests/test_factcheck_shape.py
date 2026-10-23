"""The fact-checker on claims about team shape (ninety/agents/factcheck.shape_reasons and the
confidence gate): a true claim passes, every planted false one is caught, an unsure fact is held."""

import pytest

from ninety.agents.contracts import status_for
from ninety.agents.factcheck import Claim, check, confidence_gate


def row(metric, team, value, change=None, unit="m", minute=4, tracked=11, confident=True):
    return {"id": f"shape:{metric}:{team}:m{minute}", "type": "shape", "metric": metric, "team": team,
            "minute": minute, "value": value, "unit": unit, "change": change, "tracked": tracked,
            "of": 11, "need": 11, "frames": 1500, "confident": confident}


ROWS = [
    row("line_height", "home", 38, 8), row("line_height", "away", 21, -3),
    row("width", "home", 46, -4), row("width", "away", 33, 2),
    row("area", "home", 1110, -120, unit="m²"), row("area", "away", 700, 40, unit="m²"),
    row("length", "home", 30, 0), row("back_to_mid", "home", 15, 1), row("mid_to_front", "home", 12, 0),
    row("behind_ball", "home", 9, 2, unit="players"), row("ahead_of_ball", "home", 2, -2, unit="players"),
]
GOAL = {"id": "e00040", "type": "goal", "team": "away", "player": "a-t9", "minute": 4, "second": 2,
        "clock": "03:02"}
KNOWN = {r["id"]: r for r in ROWS} | {GOAL["id"]: GOAL}
HL, AL = "shape:line_height:home:m4", "shape:line_height:away:m4"
HW, AW = "shape:width:home:m4", "shape:width:away:m4"
HA, AA = "shape:area:home:m4", "shape:area:away:m4"
HB = "shape:behind_ball:home:m4"
LINES = ["shape:back_to_mid:home:m4", "shape:mid_to_front:home:m4"]


def verdict(text, *evidence, known=KNOWN):
    return check(Claim(text, list(evidence)), known)


TRUE = [
    ("After away's goal, home's back line pushed up 8 m.", [GOAL["id"], HL]),
    ("Home's back line pushed up eight metres in the 4th minute.", [HL]),
    ("Home played a high line, 38 m from their own goal.", [HL]),
    ("Away sat in a deep block, their line 21 m from goal.", [AL]),
    ("Away's back line dropped back 3 m.", [AL]),
    ("Home pushed up 8 m while away dropped back 3 m.", [HL, AL]),
    ("Home narrowed by 4 m to 46 m wide.", [HW]),
    ("Away were narrow, 33 m across.", [AW]),
    ("Away widened by 2 m.", [AW]),
    ("Home were more compact, down to 1110 m².", [HA]),
    ("Away were compact, covering 700 square metres.", [AA]),
    ("Away stretched by 40 m2.", [AA]),
    ("Home were 30 m from front to back.", ["shape:length:home:m4"]),
    ("Home left 15 m between the lines.", LINES),
    ("Home had 9 players behind the ball.", [HB]),
    ("Home had nine men behind the ball.", [HB]),
]


@pytest.mark.parametrize(("text", "evidence"), TRUE)
def test_a_true_claim_about_shape_passes(text, evidence):
    v = verdict(text, *evidence)
    assert v.ok, v.reasons


FALSE = [
    # wrong number
    ("Home's back line pushed up 11 m.", [HL], "number 11"),
    ("Home's back line pushed up eleven metres.", [HL], "number 11"),
    ("Home played a high line, 46 m from goal.", [HL, HW], "line height"),  # width's number on the line
    ("Home were 38 m wide.", [HW, HL], "width"),
    ("Home had 10 players behind the ball.", [HB], "behind the ball"),
    ("Home had 2 players behind the ball.", [HB, "shape:ahead_of_ball:home:m4"], "behind the ball"),
    ("Home were more compact, down to 1200 m².", [HA], "number 1200"),
    # wrong direction
    ("Home's back line dropped back 8 m.", [HL], "disagrees"),
    ("Away's back line pushed up 3 m.", [AL], "disagrees"),
    ("Home widened by 4 m.", [HW], "disagrees"),
    ("Away narrowed by 2 m.", [AW], "disagrees"),
    ("Home stretched out, spread out to 1110 m².", [HA], "disagrees"),
    ("Away were more compact.", [AA], "disagrees"),
    # wrong degree
    ("Away played a high line.", [AL], "disagrees"),
    ("Home sat in a deep block.", [HL], "disagrees"),
    ("Home were narrow.", [HW], "disagrees"),
    ("Home were compact.", [HA], "disagrees"),
    # wrong team
    ("Away's back line pushed up 8 m.", [HL], "not ['away']"),
    ("Away pushed up 8 m after home's goal.", [GOAL["id"], HL], "cite that shape fact"),
    ("Home dropped back 3 m while away pushed up 8 m.", [HL, AL], "disagrees"),
    # shape talk with no shape fact cited
    ("After the goal, home's back line pushed up 8 m.", [GOAL["id"]], "cite the shape fact"),
    ("a-t9 scored as home were caught with a high line.", [GOAL["id"]], "cite the shape fact"),
    # the wrong metric cited for the words
    ("Home's back line pushed up 4 m.", [HW], "cite that shape fact"),
    # a distance stated without its unit, as a shape fact needs one
    ("Home's back line pushed up 8.", [HL], "number 8"),
]


@pytest.mark.parametrize(("text", "evidence", "why"), FALSE)
def test_a_planted_false_claim_about_shape_is_rejected(text, evidence, why):
    v = verdict(text, *evidence)
    assert not v.ok
    assert any(why in r for r in v.reasons), v.reasons


def test_a_change_never_measured_cannot_be_claimed():
    known = {r["id"]: r for r in [row("line_height", "home", 38, None)]}
    v = verdict("Home's back line pushed up 8 m.", HL, known=known)
    assert not v.ok and any("change" in r for r in v.reasons)


def test_shape_facts_add_nothing_to_the_counts_of_events():
    # Eleven shape rows cited are not 11 events: "11 passes" stays unsupported.
    v = verdict("Home strung together 11 passes.", *[r["id"] for r in ROWS])
    assert not v.ok and any("number 11" in r for r in v.reasons)


def test_a_claim_on_a_fact_built_on_too_few_tracked_players_is_held_not_rejected():
    unsure = row("line_height", "home", 38, None, tracked=7, confident=False)
    known = {unsure["id"]: unsure}
    claim = Claim("Home played a high line, 38 m from their own goal.", [unsure["id"]])
    assert check(claim, known).ok  # the words agree with the fact
    gated = confidence_gate(claim, known)
    assert not gated.ok and gated.category == "low_confidence" and status_for(gated) == "held"
    assert "7 of 11" in gated.reasons[0]


def test_a_confident_fact_passes_the_gate():
    claim = Claim("Home played a high line, 38 m from their own goal.", [HL])
    assert confidence_gate(claim, KNOWN).ok


@pytest.mark.parametrize("text", [
    "a-t9 bent it in from a narrow angle.",
    "h-t4 went wide of the post.",
    "a-t9 dropped deep to collect it and finished.",
])
def test_event_commentary_that_only_shares_a_word_is_not_a_shape_claim(text):
    scorer = "h-t4" if "h-t4" in text else "a-t9"
    assert verdict(text, GOAL["id"], known={GOAL["id"]: {**GOAL, "player": scorer}}).ok


@pytest.mark.parametrize(("text", "evidence"), [
    ("Home's line stood 8 m from their own goal.", [HL]),  # 8 is the change, not where it stands
    ("Home had 2 players behind the ball.", [HB]),  # 2 is the change in the count
])
def test_a_change_written_as_a_value_is_rejected(text, evidence):
    assert not verdict(text, *evidence).ok


def test_a_change_in_a_count_said_as_a_change_passes():
    assert verdict("Home had 2 more players behind the ball.", HB).ok
