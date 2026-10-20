"""The match funnel counts what its report says it counts."""

import math
from types import SimpleNamespace

from ninety.sim.funnel import GOALS_A_MATCH, goals_range, poisson_quantile, tally

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


def miss(mu, matches=12):
    """The chance that `matches` matches of a league scoring `mu` goals a match fall outside the
    range: Poisson goals, counted exactly."""
    low, high = goals_range(matches)
    lam = mu * matches
    return poisson_cdf(lam, round(low * 2 * matches) - 1) + 1 - poisson_cdf(lam, round(high * 2 * matches))


def test_a_league_scoring_like_the_premier_league_passes_and_one_far_off_it_does_not():
    # Legal: every season in the source's range passes all but about 1% of the time.
    for mu in (GOALS_A_MATCH[0], 2.8, GOALS_A_MATCH[1]):
        assert miss(mu) <= 0.01, mu
    # Defects: an engine scoring a third as often, or twice as often, is caught nine times in ten.
    assert miss(2.8 / 3) > 0.9 and miss(2.8 * 2) > 0.9
    # The one-match check it replaces failed a real league about one time in eleven.
    one = poisson_cdf(2.8, 0) + 1 - poisson_cdf(2.8, 6)
    assert 0.08 < one < 0.09
