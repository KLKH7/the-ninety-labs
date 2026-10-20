"""The match funnel counts what its report says it counts."""

import math
from types import SimpleNamespace

from ninety.sim.funnel import GOALS_MISS_RATE, goals_line, goals_range, poisson_quantile, tally

ROSTER = [{"id": "h1", "team": "home"}, {"id": "a1", "team": "away"}]


def match(steps, events=()):
    frames = [{"possessor": who, "ball": {"x": x, "y": 34.0}} for who, x in steps]
    return SimpleNamespace(roster=ROSTER, frames=frames, events=list(events))


def test_an_entry_is_a_crossing_once_per_crossing_and_not_where_a_possession_starts():
    m = match([("h1", 50.0), ("h1", 75.0), (None, 80.0), ("h1", 92.0), ("h1", 60.0), ("h1", 75.0),
               ("a1", 30.0), ("a1", 20.0)])  # away wins it inside its own final third: no entry
    t = tally(m)
    assert t["final_third"] == 2 / 2  # home entered twice; per team = halved
    assert t["box"] == 1 / 2
    assert t["possessions"] == 2 / 2


def test_completion_counts_only_received_passes():
    events = [{"type": "pass", "outcome": "success"}, {"type": "pass", "outcome": "fail"},
              {"type": "pass", "outcome": None}, {"type": "shot"}]
    t = tally(match([("h1", 50.0)], events))
    assert abs(t["completion"] - 1 / 3) < 1e-9 and t["passes"] == 3 / 2 and t["shots"] == 1 / 2


def poisson_cdf(lam, k):
    return math.fsum(math.exp(i * math.log(lam) - lam - math.lgamma(i + 1)) for i in range(k + 1))


def test_a_poisson_quantile_is_the_first_count_whose_cumulative_chance_reaches_it():
    for lam in (0.5, 1.0, 7.3, 33.84, 78.24):
        for q in (0.005, 0.5, 0.995):
            k = poisson_quantile(lam, q)
            assert poisson_cdf(lam, k) >= q and (k == 0 or poisson_cdf(lam, k - 1) < q), (lam, q, k)
    assert poisson_quantile(1200.0, 0.5) in (1199, 1200)  # exp(-1200) underflows; the sum must not stall


# GROUNDING R4: the leanest and richest Premier League seasons in the source, goals a match.
LEANEST, RICHEST = 2.57, 3.26


def tails(matches):
    """The chance a league at the leanest season falls below the range, and at the richest above
    it, over `matches` matches, with the range's ends as goal counts."""
    low, high = (round(end * 2 * matches) for end in goals_range(matches))
    return low, high, poisson_cdf(LEANEST * matches, low - 1), 1 - poisson_cdf(RICHEST * matches, high)


def test_the_goals_range_is_the_tightest_one_each_real_season_passes_but_for_half_the_miss_rate():
    assert goals_range(12) == (18 / 24, 56 / 24)  # the funnel's 12 matches
    assert goals_range(24) == (42 / 48, 102 / 48)
    for matches in (12, 24):
        low, high, below, above = tails(matches)
        assert below <= GOALS_MISS_RATE / 2 and above <= GOALS_MISS_RATE / 2, matches
        # One goal tighter at either end and that end misses more than half the rate.
        assert poisson_cdf(LEANEST * matches, low) > GOALS_MISS_RATE / 2, matches
        assert 1 - poisson_cdf(RICHEST * matches, high - 1) > GOALS_MISS_RATE / 2, matches


def test_an_engine_far_off_every_real_season_fails_the_goals_range():
    # Defects: a third of the leanest season, or twice the richest, is caught at least nine times in
    # ten (the nine in ten is design).
    low, high, _, _ = tails(12)
    assert poisson_cdf(LEANEST / 3 * 12, low - 1) >= 0.9
    assert 1 - poisson_cdf(RICHEST * 2 * 12, high) >= 0.9


def test_the_report_gives_goals_with_their_error_and_judges_only_full_matches():
    inside = goals_line([1.0, 1.5] * 6, 90)
    assert "1.25 (standard error 0.08" in inside and "0.75 to 2.33" in inside and inside.endswith("inside.")
    assert goals_line([0.5, 0.75] * 6, 90).endswith("OUTSIDE.")  # 0.62 a team: below a real league's
    assert "OUTSIDE" not in goals_line([0.0, 0.5] * 6, 20) and "none is given" in goals_line([1.0] * 4, 20)
