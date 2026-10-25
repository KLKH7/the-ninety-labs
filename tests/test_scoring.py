"""The score, scorers, assists and saves, from vision's goals and shot outcomes (GROUNDING I24)."""

import pytest

from ninety.agents import companion_match as cm
from ninety.intel import scoring

CLUBS = {"home": "London Athletic", "away": "Lisbon Esportes"}


def e(i, kind, team, t, **kw):
    base = {"id": f"e{i}", "type": kind, "team": team, "t": t, "confidence": 0.9, "team_confidence": 0.9}
    return {**base, **kw}


def goal_events(before=None):
    """Home's h-t7 passes to h-t9, who shoots and scores into the end home attacks (x = 105)."""
    rows = [e(1, "pass", "home", 100.0, outcome="success", player="h-t7", receiver="h-t9")]
    rows += before or []
    rows += [e(3, "shot", "home", 102.0, outcome="goal", player="h-t9", x=95.0, y=34.0),
             e(4, "goal", "home", 103.0, player="h-t9", x=105.0, y=34.0)]
    return rows


def test_the_scorer_is_the_shooter_and_the_assist_the_pass_just_before_the_shot():
    [g] = scoring.goals(goal_events())
    assert (g["player"], g["assister"], g["minute"], g["confident"]) == ("h-t9", "h-t7", 2, True)


def test_a_pass_to_someone_else_is_no_assist():
    rows = goal_events()
    rows[0] = {**rows[0], "receiver": "h-t8"}
    assert scoring.goals(rows)[0]["assister"] is None


@pytest.mark.parametrize(
    "between",
    [
        [e(2, "pass", "home", 101.0, outcome="success", player="h-t9", receiver="h-t9b")],  # another pass
        [e(2, "shot", "home", 101.0, outcome="blocked", player="h-t9", x=90.0, y=34.0)],  # a shot first
    ],
)
def test_anything_between_the_pass_and_the_shot_means_no_assist(between):
    [g] = scoring.goals(goal_events(between))
    assert g["assister"] is None


def test_the_club_that_scored_is_told_by_the_end_the_ball_went_in():
    # The detected side says away, but the ball went into the end home attacks: in doubt, so the score
    # is not said (an own goal, or a misread shirt).
    rows = goal_events()
    rows[-1] = {**rows[-1], "team": "away"}
    [g] = scoring.goals(rows)
    assert not g["confident"]
    sc = scoring.score(scoring.goals(rows), 90, CLUBS)
    assert not sc["confident"] and sc["hi"] == {"home": 1, "away": 1}


def test_a_save_is_the_club_defending_the_end_the_shot_was_struck_at():
    shots = [e(5, "shot", "home", 300.0, outcome="on_target", x=92.0, y=30.0),
             e(6, "shot", "home", 400.0, outcome="on_target", x=95.0, y=36.0),
             e(7, "shot", "away", 500.0, outcome="off_target", x=12.0, y=30.0)]
    got = scoring.save_counts(scoring.saves(shots), 1, 90)
    assert (got["away"]["value"], got["home"]["value"]) == (2, 0)  # away's keeper saved both


def test_the_score_is_said_with_each_number_in_its_own_place():
    sc = {**scoring.score(scoring.goals(goal_events()), 90, CLUBS), "clubs": CLUBS}
    want = "By minute 90, London Athletic had scored 1 goal and Lisbon Esportes 0 goals."
    assert cm.code_texts(sc) == [want]
    nil = {**scoring.score([], 90, CLUBS), "clubs": CLUBS}
    assert cm.code_texts(nil) == ["By minute 90, neither London Athletic nor Lisbon Esportes had scored."]


@pytest.mark.parametrize(
    "text, ok",
    [
        ("By minute 90, London Athletic had scored 1 goal and Lisbon Esportes 0 goals.", True),
        ("By minute 90, London Athletic had scored 0 goals and Lisbon Esportes 1 goal.", False),
        ("By minute 90, London Athletic had scored 2 goals and Lisbon Esportes 0 goals.", False),
        ("By minute 90, London Athletic were cruising, 1 goal and Lisbon Esportes 0 goals.", False),
    ],
)
def test_a_score_sentence_cannot_swap_or_dress_up_the_numbers(text, ok):
    from ninety.agents.factcheck import Claim
    from ninety.agents.insight_check import verify
    from ninety.intel.teamsheet import Fixture

    sc = {**scoring.score(scoring.goals(goal_events()), 90, CLUBS), "clubs": CLUBS}
    fx = Fixture(7, "OAK", "FEN")
    names = [s.name for t in ("home", "away") for s in fx.sheet(t)]
    assert verify(Claim(text, [sc["id"]]), {sc["id"]: sc}, fx.clubs, {}, names).ok is ok


@pytest.mark.parametrize(
    "q", ["What's the score?", "Who scored?", "How many saves has the keeper made?", "Who got the assist?"]
)
def test_score_questions_route_to_the_score_first(q):
    assert cm.route(q)[0] == "score"


def test_losing_the_ball_is_not_the_score():
    assert "score" not in cm.route("Why do London Athletic keep losing the ball in midfield?")
    assert cm.route("Who's winning?")[0] == "score"


def test_why_did_they_score_is_still_the_goals_story():
    assert cm.route("Why did London Athletic score?")[0] == "goal_build_up"


def test_a_goal_with_no_shot_before_it_names_no_scorer():
    # C (#271): a goal's `player` is the scoring side's last holder; with no shot, he may not have scored.
    rows = [e(4, "goal", "home", 103.0, player="h-t9", x=105.0, y=34.0)]
    [g] = scoring.goals(rows)
    assert g["player"] is None and g["confident"]


def test_a_goal_under_the_event_gate_holds_the_score():
    rows = goal_events()
    rows[-1] = {**rows[-1], "confidence": 0.4}
    [g] = scoring.goals(rows)
    assert not g["confident"]
    assert not scoring.score(scoring.goals(rows), 90, CLUBS)["confident"]


def test_a_second_goal_with_no_shot_of_its_own_does_not_take_the_firsts():
    # The merge queue's review of #337: a second goal (t = 1300) with no detected shot named the first
    # goal's shooter.
    rows = goal_events() + [e(9, "goal", "home", 1300.0, player="h-t3", x=105.0, y=34.0)]
    first, second = scoring.goals(rows)
    assert first["player"] == "h-t9" and second["player"] is None


def test_a_save_goes_to_the_end_even_when_the_shots_side_is_misread():
    # Read as away's, but struck at home's attacking end: the save is away's keeper's.
    shots = [e(5, "shot", "away", 300.0, outcome="on_target", x=92.0, y=30.0)]
    got = scoring.save_counts(scoring.saves(shots), 1, 90)
    assert (got["away"]["value"], got["home"]["value"]) == (1, 0)


def test_a_save_under_the_event_gate_is_unsure():
    shots = [e(5, "shot", "home", 300.0, outcome="on_target", x=92.0, y=30.0, confidence=0.3)]
    got = scoring.save_counts(scoring.saves(shots), 1, 90)
    assert not got["away"]["confident"] and (got["away"]["lo"], got["away"]["hi"]) == (0, 1)
