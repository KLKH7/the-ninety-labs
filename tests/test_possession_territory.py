"""Possession share (the pass ratio) and territory (where the ball was): GROUNDING I17, I18."""

import pytest

from ninety.agents import companion_match as cm
from ninety.intel import ball_share as terr


def ev(i, team, t=60.0, side=0.99, conf=0.9):
    return {"id": f"e{i}", "type": "pass", "team": team, "t": t, "confidence": conf, "team_confidence": side}


def test_the_share_is_stated_only_when_no_pass_is_in_doubt():
    rows = terr.possession_rows([ev(1, "home"), ev(2, "home"), ev(3, "home"), ev(4, "away")])
    got = terr.possession(rows, 1, 5)
    assert got["home"]["value"] == 75 and got["away"]["value"] == 25
    assert got["home"]["confident"] and got["home"]["lo"] == got["home"]["hi"] == 75
    # One pass whose side the video could not tell: bounds, and nothing stated.
    passes = [ev(1, "home"), ev(2, "home"), ev(3, "home"), ev(4, "away"), ev(5, "away", side=0.9)]
    rows = terr.possession_rows(passes)
    got = terr.possession(rows, 1, 5)
    assert (got["home"]["lo"], got["home"]["hi"]) == (60, 80) and not got["home"]["confident"]
    assert cm.code_texts({**got["home"], "club": "London Athletic"}) == []


def test_a_pass_counts_for_its_side_only_past_the_side_gate():
    rows = terr.possession_rows([ev(1, "home", side=0.97), ev(2, "home", side=0.9)])
    assert [r["side_known"] for r in rows] == [True, False]
    truth = {"id": "e3", "type": "pass", "team": "away", "t": 1.0}  # the simulator's, no detection score
    assert terr.possession_rows([truth])[0]["side_known"]
    assert terr.possession_rows([{**truth, "type": "shot"}]) == []


def frame(k, x):
    return {"frame": 25 * k, "t": float(k), "ball": None if x is None else {"x": x, "y": 30.0}, "players": []}


def test_territory_is_the_ball_by_third_along_each_teams_attack():
    # 10 seconds: home's final third (x > 70) 6 s, its own third 2 s, near the 35 m line 1 s, unseen 1 s.
    xs = [80, 90, 100, 75, 72, 95, 10, 20, 35.5, None]
    rows = terr.territory_rows([frame(k, x) for k, x in enumerate(xs)])
    got = terr.territory(rows, 1, 1)
    home, away = got["home"], got["away"]
    assert home["shares"]["final"] == round(100 * 6 / 9) and (home["lo"], home["hi"]) == (67, 78)
    assert away["shares"]["final"] == round(100 * 2 / 9)  # away attacks toward x = 0
    assert home["seconds"] == 9 and home["confident"]
    assert cm.code_texts({**home, "club": "London Athletic"}) == [
        f"The ball was in London Athletic's attacking third between 67% and 78% {SHOWN}"
    ]


SHOWN = "of the footage shown in minute 1."  # one minute is "in minute 1", never "from minute 1 to minute 1"
XS = [80, 90, 100, 75, 72, 95, 10, 20, 35.5, None]


@pytest.mark.parametrize(
    "text, ok",
    [
        (f"The ball was in London Athletic's attacking third between 67% and 78% {SHOWN}", True),
        (f"The ball was in London Athletic's attacking third 90% {SHOWN}", False),
        (f"The ball was rarely in London Athletic's attacking third between 67% and 78% {SHOWN}", False),
        (f"The ball was in Lisbon Esportes's attacking third between 67% and 78% {SHOWN}", False),
    ],
)
def test_a_territory_sentence_is_said_in_its_own_words(text, ok):
    from ninety.agents.factcheck import Claim
    from ninety.agents.insight_check import verify
    from ninety.intel.teamsheet import Fixture

    rows = terr.territory_rows([frame(k, x) for k, x in enumerate(XS)])
    fx = Fixture(7, "OAK", "FEN")
    fact = {**terr.territory(rows, 1, 1)["home"], "club": "London Athletic", "clubs": fx.clubs}
    names = [s.name for t in ("home", "away") for s in fx.sheet(t)]
    v = verify(Claim(text, [fact["id"]]), {fact["id"]: fact}, fx.clubs, {}, names)
    assert v.ok is ok, v.reasons


@pytest.mark.parametrize(
    "q, tool",
    [
        ("Who has had more possession?", "possession"),
        ("Are London Athletic dominating the ball?", "possession"),
        ("Where has the ball been?", "territory"),
        ("Are Lisbon Esportes pinned back?", "territory"),
    ],
)
def test_possession_and_territory_questions_route_to_their_tools(q, tool):
    assert tool in cm.route(q)


def test_the_headline_of_a_territory_answer_is_its_range():
    fact = {"metric": "final_third_share", "lo": 25, "hi": 31, "value": 25, "unit": "%"}
    assert cm._figure(fact) == "25 to 31%"


@pytest.mark.parametrize("x", [-3.0, -0.5, 106.0, 108.0])
def test_a_ball_beyond_a_goal_line_is_in_no_third(x):
    # The merge queue's review of #314: a ball off the pitch gave a depth past the thirds, and
    # THIRDS[-1] is "final", so both clubs got final-third seconds.
    rows = terr.territory_rows([frame(k, xk) for k, xk in enumerate([50.0, x])])
    got = terr.territory(rows, 1, 1)
    assert got["home"]["seconds"] == got["away"]["seconds"] == 1
    assert got["home"]["shares"]["final"] == got["away"]["shares"]["final"] == 0
