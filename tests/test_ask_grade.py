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
    # the same PR; a check with no answer it applies to (None) is not a drop, `answered` holds those.
    base = json.loads(R.BASELINE.read_text())
    now = R.ratchet_rates()
    blocks = [("all", base["all"], now["all"]), ("chips", base["chips"], now["chips"])]
    blocks += [(iid, rates, now["intents"].get(iid, {})) for iid, rates in base["intents"].items()]
    down = [
        f"{name} {k} {v} -> {got.get(k)}"
        for name, rates, got in blocks
        for k, v in rates.items()
        if v is not None and got.get(k) is not None and got[k] < v  # None: no answer it applies to
    ]
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
