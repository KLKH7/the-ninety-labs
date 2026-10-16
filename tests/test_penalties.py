"""The penalty report (ninety.sim.penalties) measures what it says it does."""

from ninety.sim import penalties


def test_a_penalty_is_taken_and_its_outcome_is_read_from_what_happened():
    rows = [penalties.take(seed) for seed in range(1, 9)]
    assert all(r["taken"] for r in rows)
    for r in rows:
        assert r["right_way"] in (True, False, None)
        assert not (r["goal"] and r["keeper"])  # a stop is a keeper's touch with no goal
        assert 0.2 < r["flight"] < 1.5 and r["wide"] >= 0.0
    assert any(r["goal"] for r in rows)
