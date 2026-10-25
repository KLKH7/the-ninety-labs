"""Set-piece counts from vision's detected restarts (GROUNDING I25)."""

import pytest

from ninety.agents import companion_match as cm
from ninety.intel import set_pieces


def sp(i, kind, x, team="home", side=0.9, t=600.0):
    return {"id": f"e{i}", "type": "set_piece", "restart": kind, "team": team, "t": t, "x": x,
            "y": 1.0, "confidence": 0.9, "team_confidence": side}


def test_the_laws_tell_who_took_a_corner_a_penalty_and_a_goal_kick():
    # The detected side says away each time, below the side gate; the end decides instead.
    rows = set_pieces.rows([sp(1, "corner", 104.0, team="away"), sp(2, "penalty_kick", 94.0, team="away"),
                            sp(3, "goal_kick", 100.0, team="home")])
    assert [(r["restart"], r["team"], r["side_known"]) for r in rows] == [
        ("corner", "home", True), ("penalty_kick", "home", True), ("goal_kick", "away", True),
    ]


def test_a_throw_in_or_free_kick_counts_for_its_side_only_past_the_gate():
    rows = set_pieces.rows([sp(1, "throw_in", 40.0, team="home", side=0.97),
                            sp(2, "throw_in", 60.0, team="away", side=0.9),
                            sp(3, "free_kick", 50.0, team="away", side=0.99)])
    got = {(r["metric"], r["team"]): r for r in set_pieces.summary(rows, 1, 90)}
    assert got[("throw_in_all", None)]["value"] == 2
    home = got[("throw_in", "home")]
    assert (home["lo"], home["hi"]) == (1, 2) and not home["confident"]
    assert got[("free_kick", "away")]["value"] == 1 and got[("free_kick", "away")]["confident"]


def test_the_sentences_name_each_restart_as_a_fan_does():
    rows = set_pieces.rows([sp(1, "corner", 104.0), sp(2, "corner", 103.0), sp(3, "penalty_kick", 94.0)])
    got = {(r["metric"], r["team"]): r for r in set_pieces.summary(rows, 1, 90)}
    assert cm.code_texts({**got[("corner", "home")], "club": "London Athletic"}) == [
        "London Athletic had 2 corners from minute 1 to minute 90."
    ]
    want = "There was 1 penalty from minute 1 to minute 90."
    assert cm.code_texts(got[("penalty_kick_all", None)]) == [want]


@pytest.mark.parametrize(
    "text, ok",
    [
        ("London Athletic had 2 corners from minute 1 to minute 90.", True),
        ("London Athletic had 2 free kicks from minute 1 to minute 90.", False),
        ("London Athletic had 3 corners from minute 1 to minute 90.", False),
        ("London Athletic forced 2 corners from minute 1 to minute 90.", False),
    ],
)
def test_a_set_piece_sentence_keeps_its_kind_and_number(text, ok):
    from ninety.agents.factcheck import Claim
    from ninety.agents.insight_check import verify
    from ninety.intel.teamsheet import Fixture

    rows = set_pieces.rows([sp(1, "corner", 104.0), sp(2, "corner", 103.0)])
    home = next(r for r in set_pieces.summary(rows, 1, 90) if r["metric"] == "corner" and r["team"] == "home")
    fact = {**home, "club": "London Athletic"}
    fx = Fixture(7, "OAK", "FEN")
    names = [s.name for t in ("home", "away") for s in fx.sheet(t)]
    assert verify(Claim(text, [fact["id"]]), {fact["id"]: fact}, fx.clubs, {}, names).ok is ok


@pytest.mark.parametrize("q", ["How many corners have London Athletic had?", "Any free kicks?",
                               "How many penalties have there been?"])
def test_set_piece_questions_route_to_the_set_pieces(q):
    assert "set_pieces" in cm.route(q)
