"""The matchup grid: fingerprints measured from events as defined, the grid's jobs fair to both
sides, intervals honest, and a run that resumes from its cache."""

import json
import math

import pytest

from ninety.sim import grid
from ninety.sim.fingerprint import team_fingerprint


def ev(t, kind, team, x, y=34.0, **kw):
    return {"t": t, "type": kind, "team": team, "x": x, "y": y, **kw}


def test_ppda_counts_their_passes_in_their_own_60_percent_per_defensive_action_there():
    """Away defends x = 105, so its own 60% is x >= 42. Home's actions count only in that zone."""
    events = [
        ev(1, "pass", "away", 100.0, end_x=90.0, end_y=34.0),
        ev(2, "pass", "away", 80.0, end_x=70.0, end_y=34.0),
        ev(3, "pass", "away", 50.0, end_x=40.0, end_y=34.0),
        ev(4, "pass", "away", 30.0, end_x=20.0, end_y=34.0),  # outside the zone: not counted
        ev(5, "interception", "home", 60.0),
        ev(6, "tackle", "home", 20.0),  # outside the zone: not counted
    ]
    assert team_fingerprint("home", events, [], 1.0)["ppda"] == 3.0
    assert math.isinf(team_fingerprint("away", events, [], 1.0)["ppda"])  # no defensive action


def test_passing_measures_read_forward_for_each_end():
    events = [
        ev(1, "pass", "home", 40.0, end_x=75.0, end_y=34.0, outcome="success"),  # 35 m forward: long
        ev(2, "pass", "home", 50.0, end_x=45.0, end_y=34.0, outcome="fail"),
        ev(3, "pass", "away", 60.0, end_x=50.0, end_y=34.0, outcome="success"),  # away attacks x = 0
    ]
    home, away = team_fingerprint("home", events, [], 1.0), team_fingerprint("away", events, [], 1.0)
    assert home["forward_m_per_pass"] == 15.0 and home["long_share"] == 0.5 and home["completion"] == 0.5
    assert away["forward_m_per_pass"] == 10.0


def test_possession_regains_fast_attacks_and_goals():
    owner = ["home"] * 3 + ["away"] + [None] * 6
    events = [
        ev(10, "possession_change", "home", 70.0),
        ev(15, "shot", "home", 95.0),  # 5 s after the regain: a fast attack
        ev(40, "possession_change", "home", 30.0),
        ev(60, "shot", "home", 90.0),  # 20 s after: not fast
        ev(61, "goal", "home", 105.0),
    ]
    fp = team_fingerprint("home", events, owner, 1.0)
    assert fp["possession"] == 0.75
    assert fp["regain_m"] == 50.0  # median of 70 and 30
    assert fp["shots"] == 2 and fp["fast_attack_shots"] == 1 and fp["goals"] == 1


def test_every_pairing_is_played_with_the_sides_swapped_on_alternate_seeds():
    jobs = grid.style_jobs(seeds=4, minutes=1)
    pairs = {tuple(sorted((j.home, j.away))) for j in jobs}
    n = len(grid.GRID_PRESETS)
    assert len(pairs) == n * (n + 1) // 2 and len(jobs) == 4 * len(pairs)
    for a, b in pairs:
        if a != b:
            homes = [j.home for j in jobs if {j.home, j.away} == {a, b}]
            assert homes.count(a) == homes.count(b) == 2
    assert all(j.home_strength == j.away_strength == 0.0 for j in jobs)


def test_the_stronger_side_is_at_home_on_half_the_seeds():
    jobs = grid.strength_jobs(seeds=4, minutes=1)
    for gap in grid.STRENGTH_GAPS:
        these = [j for j in jobs if math.isclose(abs(j.home_strength - j.away_strength), gap)]
        assert len(these) == 4
        if gap:
            assert sum(j.home_strength > j.away_strength for j in these) == 2


def test_the_interval_uses_t_for_small_samples_and_drops_missing_values():
    m, h = grid.interval([1.0, 3.0, math.inf, math.nan])
    assert m == 2.0 and math.isclose(h, 12.71 * math.sqrt(2) / math.sqrt(2))
    assert math.isnan(grid.interval([])[0]) and math.isnan(grid.interval([5.0])[1])


def test_a_prediction_is_within_noise_unless_the_intervals_are_clear_of_each_other():
    assert grid.verdict(3.0, 1.0, 1.0) == "agrees"
    assert grid.verdict(1.5, 1.0, 1.0) == "agrees, within noise"
    assert grid.verdict(-3.0, 1.0, 1.0) == "disagrees"
    assert grid.verdict(-0.5, 1.0, 1.0) == "disagrees, within noise"
    assert grid.verdict(1.0, math.nan, 1.0) == "agrees, within noise"


def fake(job, home_goals, away_goals):
    fp = {"shots": 0, "goals": 0, "possession": 0.5, "ppda": 10.0, "regain_m": 40.0, "field_tilt": 0.5,
          "forward_m_per_pass": 0.0, "long_share": 0.0, "completion": 0.8, "fast_attack_shots": 0}
    return {"job": grid.asdict(job), "key": job.key,
            "fingerprint": {"home": {**fp, "goals": home_goals}, "away": {**fp, "goals": away_goals}}}


def test_the_strength_table_credits_the_stronger_side_wherever_it_plays():
    jobs = grid.strength_jobs(seeds=2, minutes=1)
    big = [j for j in jobs if math.isclose(abs(j.home_strength - j.away_strength), 1.5)]
    strong_home, strong_away = sorted(big, key=lambda j: j.home_strength < j.away_strength)
    table = grid.strength_table([fake(strong_home, 2, 0), fake(strong_away, 0, 1)])
    assert table[1.5] == {"win": 2, "draw": 0, "loss": 0}


def test_a_run_resumes_from_its_cache_without_simulating_again(tmp_path, monkeypatch):
    job = grid.style_jobs(seeds=1, minutes=1)[0]
    cache = tmp_path / "results.jsonl"
    cache.write_text(json.dumps(fake(job, 1, 0)) + "\n")
    monkeypatch.setattr(grid, "run_job", lambda j: pytest.fail("simulated a cached match"))
    assert grid.run([job], cache, workers=1)[0]["fingerprint"]["home"]["goals"] == 1


def test_a_real_short_match_produces_both_fingerprints():
    job = grid.Job("style", 3, "high_press", "low_block", 0.0, 0.0, 0.5)
    result = grid.run_job(job)
    assert result["key"] == job.key
    assert set(result["fingerprint"]) == {"home", "away"}
    assert all(0.0 <= result["fingerprint"][t]["possession"] <= 1.0 for t in ("home", "away"))


def test_the_report_lists_every_prediction_and_writes_json_the_viewer_can_read():
    jobs = grid.style_jobs(seeds=2, minutes=1) + grid.strength_jobs(seeds=2, minutes=1)
    results = [fake(j, 1, 0) for j in jobs]
    text, data = grid.report(results, seeds=2, minutes=1)
    for hid in ("H1", "H2", "H3", "H6", "H7", "H8"):
        assert f"| {hid} " in text
    assert "not yet in the published range" in text  # the R4 caveat stays on the page
    json.dumps(data, default=float)
    assert data["matches"] == len(jobs)
