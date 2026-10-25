"""The shot map: distance, angle and the penalty area from a shot's own spot (GROUNDING I19)."""

import math

import pytest

from ninety.agents import companion_match as cm
from ninety.intel import shot_map


def shot(i, team, x, y, side=0.99, t=600.0):
    return {"id": f"e{i}", "type": "shot", "team": team, "t": t, "x": x, "y": y, "player": None,
            "confidence": 0.9, "team_confidence": side}


def test_distance_and_angle_are_to_the_goal_the_club_attacks():
    # Straight in front of home's goal (x = 105), 11 m out: the penalty spot (Law 14).
    d, a = shot_map.geometry(94.0, 34.0, "home")
    assert d == pytest.approx(11.0)
    assert a == pytest.approx(math.degrees(2 * math.atan(3.66 / 11)))
    # The same spot for away is the far end of the pitch, attacking x = 0.
    assert shot_map.geometry(94.0, 34.0, "away")[0] == pytest.approx(94.0)
    # Out wide, the posts close up: a smaller angle than from the centre at the same depth.
    assert shot_map.geometry(94.0, 10.0, "home")[1] < a


def test_a_shot_whose_side_is_unknown_is_measured_to_the_nearer_goal_and_said_without_its_club():
    rows = shot_map.shots([shot(1, "away", 94.0, 34.0, side=0.9)])  # the detected side may be wrong
    assert rows[0]["value"] == 11 and not rows[0]["side_known"] and rows[0]["confident"]
    text = cm.code_texts({**rows[0], "club": "Lisbon Esportes"})[0]
    assert "Lisbon" not in text and text.startswith("In minute 11, a shot came from 11 m out")


def test_the_penalty_area_is_lawsized():
    assert shot_map.inside_box(105 - 16.5, 34 + 20.16, "home")
    assert not shot_map.inside_box(105 - 16.6, 34.0, "home")
    assert not shot_map.inside_box(100.0, 34 + 20.3, "home")
    assert shot_map.inside_box(10.0, 34.0, "away")


THREE = [shot(1, "home", 94, 34), shot(2, "home", 80, 34), shot(3, "away", 20, 34, side=0.9)]
SPAN = "from minute 1 to minute 90, and players took"


def test_a_clubs_count_has_bounds_until_every_shot_has_a_side():
    rows = shot_map.shots(THREE)
    got = shot_map.summary(rows, 1, 90)
    assert (got["home"]["lo"], got["home"]["hi"]) == (2, 3) and not got["home"]["confident"]
    assert got["home"]["inside_box"] == 1
    every = got["all"]
    assert every["value"] == 3 and every["inside_box"] == 1 and every["confident"]
    assert cm.code_texts(every) == [
        f"There were 3 shots {SPAN} 1 shot from inside the penalty area."
    ]


@pytest.mark.parametrize(
    "text, ok",
    [
        (f"There were 3 shots {SPAN} 1 shot from inside the penalty area.", True),
        (f"There were 4 shots {SPAN} 1 shot from inside the penalty area.", False),
        (f"There were 3 shots {SPAN} 3 shots from inside the penalty area.", False),
    ],
)
def test_the_inside_count_is_bound_to_its_own_words(text, ok):
    from ninety.agents.factcheck import Claim
    from ninety.agents.insight_check import verify
    from ninety.intel.teamsheet import Fixture

    rows = shot_map.shots(THREE)
    fact = shot_map.summary(rows, 1, 90)["all"]
    fx = Fixture(7, "OAK", "FEN")
    names = [s.name for t in ("home", "away") for s in fx.sheet(t)]
    assert verify(Claim(text, [fact["id"]]), {fact["id"]: fact}, fx.clubs, {}, names).ok is ok


@pytest.mark.parametrize("q", ["How many shots have there been?", "Where did London Athletic shoot from?"])
def test_shot_questions_route_to_the_shot_map(q):
    assert "shots" in cm.route(q)


@pytest.mark.parametrize(
    "text",
    [
        f"There were 3 shots {SPAN} 1 shot from outside the penalty area.",
        f"There were 3 shots {SPAN} only 1 shot from inside the penalty area.",
        "There were 3 shots from minute 1 to minute 90, and players took 1 shot from near the penalty area.",
    ],
)
def test_a_shot_sentence_is_said_in_its_own_words(text):
    # The merge queue's review of #318: "took 1 shot from outside the penalty area" passed against a fact
    # of 3 shots with 1 inside. The shot facts are in the closed direction check now.
    from ninety.agents.factcheck import Claim
    from ninety.agents.insight_check import verify
    from ninety.intel.teamsheet import Fixture

    fact = shot_map.summary(shot_map.shots(THREE), 1, 90)["all"]
    fx = Fixture(7, "OAK", "FEN")
    names = [s.name for t in ("home", "away") for s in fx.sheet(t)]
    assert not verify(Claim(text, [fact["id"]]), {fact["id"]: fact}, fx.clubs, {}, names).ok


def test_a_shot_within_the_error_of_the_areas_line_leaves_the_inside_count_unsaid():
    near = shot(9, "home", 105 - 16.5 - 0.8, 34)  # 0.8 m outside the line: could be inside
    got = shot_map.summary(shot_map.shots([shot(1, "home", 94, 34), near]), 1, 90)["all"]
    assert (got["inside_lo"], got["inside_hi"]) == (1, 2) and not got["inside_exact"]
    assert cm.code_texts(got) == ["There were 2 shots from minute 1 to minute 90."]


def test_a_shot_of_unknown_side_is_inside_the_nearer_goals_area():
    assert shot_map.inside_box(10.0, 34.0, None) and shot_map.inside_box(95.0, 34.0, None)
    assert not shot_map.inside_box(40.0, 34.0, None)


def test_an_unsure_inside_count_takes_no_number_after_took():
    # The merge queue's re-review of #318: with the inside count unsure, the total filled its slot.
    from ninety.agents.factcheck import Claim
    from ninety.agents.insight_check import verify
    from ninety.intel.teamsheet import Fixture

    near = shot(9, "home", 105 - 16.5 - 0.8, 34)
    fact = shot_map.summary(shot_map.shots([shot(1, "home", 94, 34), near]), 1, 90)["all"]
    assert not fact["inside_exact"]
    fx = Fixture(7, "OAK", "FEN")
    names = [s.name for t in ("home", "away") for s in fx.sheet(t)]
    for k in (1, 2):
        text = f"There were 2 shots {SPAN} {k} shot{'s' if k > 1 else ''} from inside the penalty area."
        assert not verify(Claim(text, [fact["id"]]), {fact["id"]: fact}, fx.clubs, {}, names).ok, text


def test_a_shot_of_unknown_side_names_no_club():
    from ninety.agents.factcheck import Claim
    from ninety.agents.insight_check import verify
    from ninety.intel.teamsheet import Fixture

    [row] = shot_map.shots([shot(1, "away", 94.0, 34.0, side=0.9)])
    assert row["team"] is None
    fact = {**row, "club": None}
    fx = Fixture(7, "OAK", "FEN")
    names = [s.name for t in ("home", "away") for s in fx.sheet(t)]
    said = "In minute 11, Lisbon Esportes shot from 11 m out, where the posts were 37 degrees apart."
    assert not verify(Claim(said, [fact["id"]]), {fact["id"]: fact}, fx.clubs, {}, names).ok
    assert shot_map.near_box_line(105 - 16.5 - 0.8, 34.0, None)


def test_the_stats_row_of_shots_inside_is_unsure_when_a_shot_is_near_the_line():
    import json

    from ninety.eval.companion_tools import STANDIN
    from ninety.intel.match_insights import MatchInsights
    from ninety.intel.stats_table import stats_table

    body = json.loads(STANDIN.read_text())
    near = shot(9, "home", 105 - 16.5 - 0.8, 34, side=0.99)
    sure = shot(1, "home", 94, 34, side=0.99)
    body["facts"]["shot"] = shot_map.shots([sure, near])
    for r in body["facts"]["shot"]:
        r["club"] = "London Athletic"
    row = next(r for r in stats_table(MatchInsights.from_dict(body))["rows"] if r["key"] == "shots_inside")
    assert not row["series"][-1]["confident"]
