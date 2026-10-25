"""What the passes did, and who passed to whom (GROUNDING I20, I21)."""

import pytest

from ninety.agents import companion_match as cm
from ninety.intel import passing


def p(i, team, x, y, ex, ey, outcome="success", side=0.99, player="h-t1", receiver="h-t2", interceptor=None):
    return {"id": f"e{i}", "type": "pass", "team": team, "t": 60.0, "x": x, "y": y, "end_x": ex, "end_y": ey,
            "outcome": outcome, "confidence": 0.9, "team_confidence": side, "player": player,
            "receiver": receiver, "interceptor": interceptor}


@pytest.mark.parametrize(
    "x, ex, team, want",
    [
        (10, 41, "home", True),  # own half to own half, 31 m closer: past 30
        (10, 39, "home", False),  # 29 m: not
        (45, 61, "home", True),  # across halfway, 16 m: past 15
        (45, 59, "home", False),
        (70, 81, "home", True),  # in their half, 11 m: past 10
        (70, 79, "home", False),
        (95, 64, "away", True),  # away attacks toward x = 0: 31 m closer within its own half
    ],
)
def test_progressive_is_the_published_three_distances(x, ex, team, want):
    assert passing.progressive(x, 34, ex, 34, team) is want


def test_a_pass_into_the_final_third_starts_outside_it():
    assert passing.into_final_third(60, 75, "home")
    assert not passing.into_final_third(75, 90, "home")  # already inside
    assert passing.into_final_third(45, 30, "away")


def test_a_clubs_count_has_bounds_and_the_total_needs_no_side():
    rows = passing.rows([
        p(1, "home", 10, 34, 41, 34),
        p(2, "home", 70, 34, 81, 34),
        p(3, "away", 95, 34, 64, 34, side=0.9),  # side unknown
        p(4, "home", 50, 34, 90, 34, outcome="fail", interceptor="a-t3"),
    ])
    got = {(r["metric"], r["team"]): r for r in passing.summary(rows, 1, 90)}
    total = got[("progressive_all", None)]
    assert (total["lo"], total["hi"]) == (2, 3) and not total["confident"]  # e3's side is unknown
    home = got[("progressive", "home")]
    assert (home["lo"], home["hi"]) == (2, 2)  # e3 is backward for home: it could only be away's
    away = got[("progressive", "away")]
    assert (away["lo"], away["hi"]) == (0, 1) and not away["confident"]
    assert got[("long_all", None)]["value"] == 1  # only e4's 40 m is 32 m or more; 31 m is not
    assert got[("intercepted", "home")]["value"] == 1 and got[("intercepted", "home")]["confident"]
    sure = {(r["metric"], r["team"]): r for r in passing.summary(rows[:2] + rows[3:], 1, 90)}
    assert cm.code_texts(sure[("progressive_all", None)]) == [
        "There were 2 progressive passes from minute 1 to minute 90."
    ]


def test_the_network_counts_only_passes_both_of_whose_players_are_named():
    people = {
        "h-t1": {"team": "home", "name": "Kai Terrow"},
        "h-t2": {"team": "home", "name": "Femi Railby"},
        "h-t3": {"team": "home", "name": None},
        "h-t9": {"team": "home", "name": "Kai Terrow"},  # another piece of the same player's track
    }
    rows = passing.rows([
        p(1, "home", 10, 34, 20, 34, player="h-t1", receiver="h-t2"),
        p(2, "home", 10, 34, 20, 34, player="h-t9", receiver="h-t2"),
        p(3, "home", 10, 34, 20, 34, player="h-t1", receiver="h-t3"),  # receiver not named
        p(4, "home", 10, 34, 20, 34, player="h-t2", receiver="h-t2"),  # to himself: no pair
    ])
    pairs = passing.network(rows, people, 1, 90)
    got = [(r["passer_is"], r["receiver_is"], r["value"]) for r in pairs]
    assert got == [("Kai Terrow", "Femi Railby", 2)]
    assert cm.code_texts({**pairs[0], "club": "London Athletic"}) == [
        "Kai Terrow passed to Femi Railby 2 times from minute 1 to minute 90, of the passes the video could "
        "name both players of."
    ]


@pytest.mark.parametrize(
    "q", ["How many progressive passes have London Athletic made?", "Who has been linking up best?",
          "How often have Lisbon Esportes been intercepted?"],
)
def test_passing_questions_route_to_the_passing_tool(q):
    assert "passing" in cm.route(q)


def test_an_unknown_side_pass_widens_the_club_it_would_be_progressive_for():
    # The merge queue's review of #321: guessed home, x 60 to 20, it is backward for home but 40 m
    # closer to away's goal; the totals and away's count must allow it.
    rows = passing.rows([p(1, "home", 60, 34, 20, 34, side=0.9)])
    got = {(r["metric"], r["team"]): r for r in passing.summary(rows, 1, 90)}
    assert (got[("progressive_all", None)]["lo"], got[("progressive_all", None)]["hi"]) == (0, 1)
    assert not got[("progressive_all", None)]["confident"]
    assert (got[("progressive", "away")]["lo"], got[("progressive", "away")]["hi"]) == (0, 1)
    assert got[("progressive", "home")]["hi"] == 0


def test_only_completed_passes_enter_the_final_third_and_only_failed_ones_are_intercepted():
    rows = passing.rows([p(1, "home", 60, 34, 80, 34, outcome="fail", interceptor="a-t3"),
                         p(2, "home", 60, 34, 80, 34, outcome="success", interceptor="a-t3")])
    got = {(r["metric"], r["team"]): r for r in passing.summary(rows, 1, 90)}
    assert got[("final_third_entry", "home")]["value"] == 1  # e2 only
    assert got[("intercepted", "home")]["value"] == 1  # e1 only


def test_the_network_pairs_only_team_mates_and_only_completed_passes():
    people = {
        "h-t1": {"team": "home", "name": "Kai Terrow"},
        "a-t2": {"team": "away", "name": "Zane Kirrick"},
        "h-t2": {"team": "home", "name": "Femi Railby"},
    }
    rows = passing.rows([
        p(1, "home", 10, 34, 20, 34, player="h-t1", receiver="a-t2"),  # to an opponent: no pair
        p(2, "home", 10, 34, 20, 34, outcome="fail", player="h-t1", receiver="h-t2"),  # not completed
    ])
    assert passing.network(rows, people, 1, 90) == []


@pytest.mark.parametrize(
    "said, ok",
    [
        ("Kai Terrow passed to Femi Railby 2 times from minute 1 to minute 90, of the passes the video could "
         "name both players of.", True),
        ("Femi Railby passed to Kai Terrow 2 times from minute 1 to minute 90, of the passes the video could "
         "name both players of.", False),
        ("Kai Terrow passed to Femi Railby 2 times from minute 1 to minute 90.", False),
        ("Kai Terrow passed to Femi Railby 2 times from minute 1 to minute 90, of the passes the video could "
         "name both players of; Femi Railby passed to Kai Terrow 2 times.", False),
    ],
)
def test_a_pair_is_said_in_its_order_and_with_its_caveat(said, ok):
    from ninety.agents.factcheck import Claim
    from ninety.agents.insight_check import verify
    from ninety.intel.teamsheet import Fixture

    fx = Fixture(7, "OAK", "FEN")
    a, b = fx.sheet("home")[4], fx.sheet("home")[1]
    def named(track, who, role, position):
        return {"track": track, "team": "home", "name": who.name, "role": role, "position": position,
                "sheet_name": who.name, "say": who.name}

    people = {"h-t1": named("h-t1", a, "LB", "left-back"), "h-t2": named("h-t2", b, "RB", "right-back")}
    rows = passing.rows([p(1, "home", 10, 34, 20, 34), p(2, "home", 10, 34, 20, 34)])
    [pair] = passing.network(rows, people, 1, 90)
    fact = {**pair, "club": "London Athletic"}
    text = said.replace("Kai Terrow", a.name).replace("Femi Railby", b.name)
    names = [s.name for t in ("home", "away") for s in fx.sheet(t)]
    assert verify(Claim(text, [fact["id"]]), {fact["id"]: fact}, fx.clubs, people, names).ok is ok
