"""The Ask grader (ninety/eval/ask_grade): the answer key stays off the live path, its rules catch
the defects they are for, and the Ask's graded rates on the frozen fixture only go up."""

import json
import re
from pathlib import Path

import pytest

from ninety.eval.ask_grade import grade as G
from ninety.eval.ask_grade import run as R
from ninety.eval.ask_grade import truth as T

ROOT = Path(__file__).resolve().parents[1]
LIVE = ("agents", "intel", "mcp", "api", "vision")
# The grader's package, its truth table and the full run it was read from: none may appear on the live path.
TRUTH_MARKS = re.compile(r"ask_grade|truth-8324|demo-engine-v2|ask-grade-insights")
INTENTS, CLUBS = G.load_intents()
TOL = G.load_tolerances()
TABLE = T.read(R.TRUTH_TABLE)
ROSTER = TABLE["_roster"]


def intent(iid):
    return next(i for i in INTENTS if i["id"] == iid)


def graded(iid, q, t, text, status="verified", t_to=None):
    it = intent(iid)
    tv = TABLE.get(G.wkey(it, t, G.window_of(it, q, t)))
    return G.grade(it, q, t, {"status": status, "text": text, "t_to": t_to}, tv, TOL, CLUBS, ROSTER, True)[
        "checks"
    ]


def test_live_path_never_reads_the_grader_or_its_truth():
    hits = []
    for pkg in LIVE:
        for py in sorted((ROOT / "ninety" / pkg).rglob("*.py")):
            for n, line in enumerate(py.read_text().splitlines(), 1):
                if TRUTH_MARKS.search(line):
                    hits.append(f"{py.relative_to(ROOT)}:{n}: {line.strip()}")
    assert not hits, "the live path names the Ask grader or its answer key:\n" + "\n".join(hits)


def test_the_truth_table_is_only_read_inside_ninety_eval():
    for py in sorted((ROOT / "ninety").rglob("*.py")):
        rel = py.relative_to(ROOT).as_posix()
        if rel.startswith("ninety/eval/"):
            continue
        assert "ask_grade" not in py.read_text(), f"{rel} imports the Ask grader"


def test_every_intent_has_ten_paraphrases_a_metric_rule_and_a_window():
    for it in INTENTS:
        assert len(it["questions"]) >= 10, it["id"]
        assert it["window"] == "so_far" or re.fullmatch(r"(?:last|since):\d+", it["window"]), it["id"]
        assert "metric" in it and "scope" in it
    chips = [q for it in INTENTS for q in it["questions"] if q.get("chip")]
    assert len(chips) >= 20


def test_every_tolerance_says_why():
    body = json.loads((R.HERE / "tolerances.json").read_text())
    for k, v in body.items():
        if isinstance(v, dict):
            assert v.get("why") and "value" in v, k


# ---- the rules catch what they are for (each must fail on its defect) ------------------------


def test_total_shots_is_not_an_answer_to_on_target():
    c = graded(
        "on_target",
        "shots on target?",
        2030.0,
        "In the footage we've seen there were 3 shots from minute 1 to minute 33.",
    )
    assert c["relevant"] is False and c["correct"] is False


def test_an_unattributed_total_is_not_one_clubs_count():
    # truth at 85:00: London 8 shots in the match; "8 shots" with no club is a total, and the total is not 8
    c = graded(
        "shots", "How many shots have London had?", 5100.0, "There were 8 shots from minute 1 to minute 85."
    )
    assert c["correct"] is False
    total = graded(
        "shots", "How many shots have London had?", 5100.0, "There were 31 shots from minute 1 to minute 85."
    )
    assert total["correct"] is False  # the match's total is not London's count
    c = graded(
        "shots",
        "How many shots have London had?",
        5100.0,
        "London Athletic had 8 shots from minute 1 to minute 85.",
    )
    assert c["correct"] is True


def test_a_why_that_cites_a_later_minute_is_not_the_build_up():
    c = graded(
        "why_goal",
        "Why did London Athletic score?",
        2030.0,
        "London Athletic scored in minute 12. Just "
        "before it, in minute 32, a London Athletic player played a pass that took 4 players out.",
    )
    assert c["correct"] is False


def test_when_is_not_why():
    c = graded("why_goal", "Why did London Athletic score?", 2030.0, "London Athletic scored in minute 12.")
    assert c["relevant"] is False and c["correct"] is False


def test_a_span_to_the_bins_end_is_not_a_leak_but_a_minute_past_now_is():
    span = graded(
        "shots", "How many shots?", 2030.0, "In the footage, 3 shots from minute 1 to minute 34.", t_to=2040.0
    )
    assert span["span_clipped"] is False and span["no_future"] is True
    told = graded("shots", "How many shots?", 2030.0, "In the footage, 3 shots from minute 1 to minute 36.")
    assert told["no_future"] is False


def test_a_cited_fact_or_aggregate_from_after_now_is_a_leak():
    insights = R.load_insights(R.FIXTURE)
    late = next(f for f in insights.facts["shot"] if f.get("t"))
    t = float(late["t"]) - 5.0
    minute = int(late["minute"])
    assert R.leaks(insights, [late["id"]], t) == [late["id"]]
    assert R.leaks(insights, [late["id"]], float(late["t"])) == []
    agg = f"shots:all:m1-{minute}"
    assert R.leaks(insights, [agg], t) == [agg]
    assert R.leaks(insights, [f"shots:all:m1-{minute - 1}"], t) == []


def test_a_footage_figure_must_say_so():
    c = graded(
        "possession", "Who has had more of the ball?", 2030.0, "London Athletic had 63% of possession."
    )
    assert c["coverage_honest"] is False
    c = graded(
        "possession",
        "Who has had more of the ball?",
        2030.0,
        "In the footage we've seen, London Athletic had 57% of the ball.",
    )
    assert c["coverage_honest"] is True and c["correct"] is True


def test_cant_when_the_insights_hold_it_is_a_false_unknown():
    c = graded("possession", "possession?", 2030.0, "Possession can't be split between the clubs yet.")
    assert c["answered"] is False and c["no_false_unknown"] is False


@pytest.mark.parametrize(
    "text,flag",
    [
        ("The ball was in the footage shown 40% of the time.", "footage shown"),
        ("Lisbon Esportes's best player.", "s's"),
        ("Lisbon had between 22% and 28% of it.", "bare range"),
        ("a London Athletic player shot.", "lowercase start"),
    ],
)
def test_robotic_wording_is_flagged(text, flag):
    it = intent("territory")
    g = G.grade(it, "q", 2030.0, {"status": "verified", "text": text}, None, TOL, CLUBS, ROSTER, True)
    assert flag in g["flags"]


def test_a_scorer_must_be_the_scorer():
    good = graded(
        "scorers",
        "Who scored?",
        5400.0,
        "London Athletic scored in minute 12. Lisbon Esportes scored in minutes 35, 76 and 85.",
    )
    assert good["correct"] is True
    good = graded(
        "scorers",
        "Who scored?",
        5400.0,
        "London Athletic scored in minute 12. Lisbon Esportes scored "
        "in minute 35. Lisbon Esportes scored in minute 76. Lisbon Esportes scored in minute 85.",
    )
    assert good["correct"] is True
    bad = graded("scorers", "Who scored?", 2030.0, "Lisbon Esportes scored in minute 35.")
    assert bad["correct"] is False  # London's goal (12') missing, and minute 35 has not been played


def test_unmeasured_must_say_so_and_point_to_a_measured_fact():
    law = graded(
        "unmeasured",
        "Was anyone offside before the goal?",
        2700.0,
        "The Laws say that a player is in an offside position if he is nearer the goal line.",
    )
    assert law["correct"] is False
    plain = graded(
        "unmeasured",
        "Was anyone offside before the goal?",
        2700.0,
        "Offside isn't measured from this video, but here's what is: London Athletic scored in minute 12.",
    )
    assert plain["correct"] is True


# ---- the ratchet ----------------------------------------------------------------------------


def test_the_asks_rates_only_go_up():
    # every column on its own (the core pass rate, each check, the all-checks rate), per intent,
    # overall and for the chips. A change to how insights are built refreshes the fixture (rebuild it
    # from runs/demo-8324-final with that code: run.py grade --rebuild-insights) and the baseline in
    # the same PR. An intent may not disappear, and a rate that becomes None (no answer it applies to)
    # is a drop unless the block's `answered` rate did not change.
    base = json.loads(R.BASELINE.read_text())
    now = R.ratchet_rates()
    missing = set(base["intents"]) - set(now["intents"])
    assert not missing, f"intents gone from the grade: {sorted(missing)}"
    blocks = [("all", base["all"], now["all"]), ("chips", base["chips"], now["chips"])]
    blocks += [(iid, rates, now["intents"][iid]) for iid, rates in base["intents"].items()]
    down = []
    for name, rates, got in blocks:
        for k, v in rates.items():
            if v is None:
                continue
            if got.get(k) is None:
                if got.get("answered") != rates.get("answered"):
                    down.append(f"{name} {k} {v} -> None")
            elif got[k] < v:
                down.append(f"{name} {k} {v} -> {got[k]}")
    assert not down, (
        "the Ask's graded rates went down on the frozen fixture (docs/eval/companion-full-eval.md):\n"
        + "\n".join(down)
    )


def test_one_clubs_figure_is_not_a_comparison():
    # since the half hour at 33:50 the truth's margin is within tolerance, so either club passes, but
    # only in a reply that compares the two
    q = "who's been on top since the half hour?"
    one = graded("on_top", q, 2030.0, "London Athletic took 4 opponents out with one pass.")
    assert one["correct"] is False
    both = graded(
        "on_top",
        q,
        2030.0,
        "London Athletic have had the ball in their attacking third a little more "
        "than Lisbon Esportes since minute 31.",
    )
    assert both["correct"] is True


def test_one_clubs_pass_is_not_where_the_ball_has_been():
    one = graded(
        "territory",
        "who's been in the attacking third more",
        5400.0,
        "a Lisbon Esportes player has taken "
        "the most opponents out of the game with passes from minute 76 to minute 90: 4 opponents in 1 pass.",
    )
    assert one["correct"] is False


def test_the_scorebugs_wording_is_a_score():
    said = "London Athletic 1 goal, Lisbon Esportes 1 goal, read from the broadcast's scorebug."
    assert graded("score", "What's the score?", 2700.0, said)["correct"] is True
    assert graded("score", "What's the score?", 5400.0, said)["correct"] is False  # 1-3 at full time


def test_no_goal_yet_must_be_said():
    busy = graded("scorers", "Who scored?", 600.0, "Alex Finnet has been the busiest player so far.")
    assert busy["correct"] is False
    none = graded("scorers", "Who scored?", 600.0, "No goals yet: London Athletic 0, Lisbon Esportes 0.")
    assert none["correct"] is True
    bug = graded(
        "scorers",
        "Who scored?",
        600.0,
        "London Athletic 0 goals, Lisbon Esportes 0 goals, read from the broadcast's scorebug.",
    )
    assert bug["correct"] is True


def test_a_shares_range_is_not_a_minute():
    said = (
        "London Athletic had the ball in their attacking third for 15% to 20% of the time in the footage "
        "we've seen from minute 1 to minute 11."
    )
    assert set(G.minutes_said(said)) == {1, 11}  # not 20
    assert graded("territory", "Where has the ball been?", 600.0, said)["no_future"] is True


def test_the_teams_do_not_change_ends():
    # seed 8324: Lisbon scored at the x = 0 end in both halves (35', 76', 85'), so in the second half
    # as in the first the ball in Lisbon's attacking third is near x = 0, and Lisbon lead it from 60'
    it = intent("on_top")
    tv = TABLE[G.wkey(it, 3600.0, (2700.0, 3600.0))]["match"]["territory"]
    assert tv["away"] > tv["home"]


@pytest.mark.parametrize(
    "text,minutes",
    [
        ("Lisbon had between 22% and 28% of it from minute 31 to minute 34.", {31, 34}),
        ("London held 22% to 28% of the ball, up to 35′.", {35}),
        ("In the last 15 minutes, up to 28 passes a minute.", set()),
        ("Goals in minutes 35, 76 and 85.", {35, 76, 85}),
        ("From minutes 20 to 34.", {20, 34}),
        ("At 33:50, in the 34th minute.", {34}),
        ("Lisbon pressed hardest from minute 20 to 34.", {20, 34}),
        ("From minute 34 to 40 London kept the ball.", {34, 40}),
        ("Between minute 41 until 43, 15% to 20% of it.", {41, 43}),
        ("In minute 10, between 22% and 28% of the ball.", {10}),
    ],
)
def test_only_explicit_minutes_are_minutes(text, minutes):
    assert set(G.minutes_said(text)) == minutes


def _shots(half_frame, home_xs, away_xs, start):
    return [
        {"type": "shot", "team": t, "x": x, "frame": start + i}
        for i, (t, x) in enumerate([*(("home", x) for x in home_xs), *(("away", x) for x in away_xs)])
    ]


def test_attacking_directions_come_from_the_data_both_ways():
    half = 1000
    kept = _shots(half, [88, 92], [20, 30], 0) + _shots(half, [80, 95], [12, 25], half + 1)
    assert T.attack_directions(kept, half) == (True, True)
    swapped = _shots(half, [88, 92], [20, 30], 0) + _shots(half, [15, 22], [85, 90], half + 1)
    assert T.attack_directions(swapped, half) == (True, False)
    assert T.attack_directions(_shots(half, [], [], 0), half) == (None, None)


def test_the_demo_match_keeps_its_ends():
    # seed 8324, read from its truth when the table was written: home attacks x = 105 in both halves
    assert TABLE["_directions"] == {"first_half_home_right": True, "second_half_home_right": True}


def test_another_question_set_keeps_the_intents_rules(tmp_path):
    flat = tmp_path / "flat.json"
    flat.write_text(
        json.dumps(
            [
                {"intent": "possession", "q": "who's seen more of it"},
                {"intent": "score", "question": "where's the game at"},
            ]
        )
    )
    got = G.with_questions(INTENTS, flat)
    assert [it["id"] for it in got] == ["score", "possession"]
    assert got[1]["metric"] == intent("possession")["metric"] and got[1]["questions"] == [
        {"q": "who's seen more of it"}
    ]
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps([{"intent": "weather", "q": "is it raining"}]))
    with pytest.raises(ValueError):
        G.with_questions(INTENTS, bad)


def _counts(home, away, slack=0):
    band = {"home": home, "away": away, "total": home + away}
    lo = {"home": home - slack, "away": away - slack, "total": home + away - 2 * slack}
    hi = {"home": home + slack, "away": away + slack, "total": home + away + 2 * slack}
    return {"footage": {"count": band, "count_lo": lo, "count_hi": hi}}


@pytest.mark.parametrize(
    "truth,text,ok",
    [
        (
            _counts(3, 5),
            "Lisbon Esportes have had more shots in the footage, 5 to London Athletic's 3.",
            True,
        ),
        (
            _counts(3, 5),
            "London Athletic have had more shots in the footage, 3 to Lisbon Esportes' 5.",
            False,
        ),
        (_counts(3, 5), "London Athletic have had fewer shots than Lisbon Esportes in the footage.", True),
        (_counts(3, 5), "The two sides are level on shots in the footage.", False),
        (_counts(3, 5), "There were 8 shots in the footage.", False),
        (_counts(4, 4), "The two sides are level on shots in the footage, 4 each.", True),
        (_counts(4, 4), "Lisbon Esportes have had more shots in the footage.", False),
        (
            _counts(4, 5, slack=1),
            "London Athletic and Lisbon Esportes are level on shots in the footage.",
            True,
        ),
        (_counts(4, 5, slack=1), "Lisbon Esportes have had more shots, 5 to 4.", True),
        (_counts(4, 5, slack=1), "London Athletic have had more shots, 4 to 5.", False),
        (
            _counts(2, 2),
            "London Athletic and Lisbon Esportes have had 2 shots each in the footage so far.",
            True,
        ),
        (_counts(0, 0), "Neither side has had a corner in the footage so far.", True),
        (_counts(0, 2), "Neither side has had a corner in the footage so far.", False),
        (
            _counts(3, 5),
            "Lisbon Esportes have had more shots: 5 to London Athletic's 3 in the footage so far.",
            True,
        ),
        (_counts(3, 5), "Each club's shots: London Athletic 3, Lisbon Esportes 5.", False),
        (_counts(4, 5, slack=1), "Each club has had shots in the footage so far.", False),  # no comparison
    ],
)
def test_a_count_leads_with_the_right_club(truth, text, ok):
    assert G.comparison_direction(text, truth, CLUBS) is ok


def test_comparison_direction_is_a_count_check_only():
    shots = graded("shots", "How many shots?", 2700.0, "Lisbon Esportes have had more shots in the footage.")
    assert shots["comparison_direction"] is not None
    poss = graded("possession", "possession?", 2700.0, "London Athletic had 57% of the ball in the footage.")
    assert poss["comparison_direction"] is None


def test_territory_follows_each_halfs_direction():
    # A tiny match whose ends change at half time (frame 4): home has the ball throughout, at x = 100
    # in the first half and at x = 5 in the second. With home attacking right, then left, the ball is
    # in home's attacking third the whole time; a Truth that ignored the second half's direction
    # would put it in home's own third after the break.
    import numpy as np

    tr = T.Truth(
        events=[],
        shown=[(0, 7)],
        side=np.array([1] * 8, np.int8),
        ball_x=np.array([100.0] * 4 + [5.0] * 4, np.float32),
        speed=np.zeros((8, 1), np.float32),
        ids=["h1"],
        home_right=True,
        half_frame=4,
        names={},
        directions=(True, False),
    )
    assert tr.territory(0, 7 / T.FPS, "match")["home"] == 100.0
    assert tr.territory(4 / T.FPS, 7 / T.FPS, "match") == {"home": 100.0, "away": 0.0}
    kept = T.Truth(**{**tr.__dict__, "directions": (True, True)})
    assert kept.territory(4 / T.FPS, 7 / T.FPS, "match") == {"home": 0.0, "away": 100.0}


@pytest.mark.parametrize(
    "home,away,text,ok",
    [
        (
            95.0,
            80.0,
            "London Athletic have passed more accurately than Lisbon Esportes in the footage so far.",
            True,
        ),
        (
            95.0,
            80.0,
            "Lisbon Esportes have passed more accurately than London Athletic in the footage so far.",
            False,
        ),
        (
            85.0,
            90.0,
            "Lisbon Esportes have passed more accurately than London Athletic in the footage so far.",
            True,
        ),
        (
            85.0,
            90.0,
            "London Athletic have passed more accurately than Lisbon Esportes in the footage so far.",
            True,
        ),
        (95.0, 80.0, "Passes are finding a team-mate in the footage so far.", False),
    ],
)
def test_completion_said_as_a_direction(home, away, text, ok):
    tv = {"footage": {"completion": {"home": home, "away": away, "total": None}}}
    assert G.comparison_direction(text, tv, CLUBS, TOL) is ok
