"""Pressing, territory and tempo windows, and territory shifts: hand-computed cases, each side's
direction, exact citations, and a real match."""

from ninety.intel import calculate_facts
from ninety.intel.windows import (
    field_tilt,
    leader,
    ppda_events,
    territory_shifts,
    window_facts,
)
from ninety.sim.engine import simulate

_ids = iter(range(1, 10_000))


def ev(t, kind, team, x, **kw):
    return {"id": f"e{next(_ids):05d}", "t": t, "type": kind, "team": team, "x": x, "y": 34.0, **kw}


def by(facts, metric, scope):
    return next((f for f in facts if f.metric == metric and f.scope == scope), None)


def test_ppda_counts_the_opponents_passes_in_their_own_60_percent_per_defensive_action_there():
    """Home presses away, who defends x = 105, so away's own 60% is x >= 42. Home's tackle at 20 is
    outside it, and so is away's pass at 30."""
    events = [ev(1, "pass", "away", 100.0), ev(2, "pass", "away", 50.0), ev(3, "pass", "away", 30.0),
              ev(4, "interception", "home", 60.0), ev(5, "tackle", "home", 20.0)]
    passes, actions = ppda_events("home", events)
    assert [e["x"] for e in passes] == [100.0, 50.0] and [e["x"] for e in actions] == [60.0]
    fact = by(window_facts(events), "ppda", "team:home:window:0")
    assert fact.value == 2.0 and set(fact.source_ids) == {e["id"] for e in passes + actions}


def test_away_presses_toward_x_0():
    """Away presses home, who defends x = 0: home's own 60% is x <= 63."""
    events = [ev(1, "pass", "home", 10.0), ev(2, "pass", "home", 70.0),
              ev(3, "tackle", "away", 40.0, outcome="success")]
    fact = by(window_facts(events), "ppda", "team:away:window:0")
    assert fact.value == 1.0 and len(fact.source_ids) == 2


def test_no_defensive_action_means_no_ppda_rather_than_an_invented_number():
    events = [ev(1, "pass", "away", 80.0)]
    assert by(window_facts(events), "ppda", "team:home:window:0") is None


def test_field_tilt_is_a_share_of_both_sides_attacking_third_passes():
    """Home's attacking third is x >= 70, away's is x <= 35."""
    events = [ev(1, "pass", "home", 80.0), ev(2, "pass", "home", 75.0), ev(3, "pass", "home", 50.0),
              ev(4, "pass", "away", 20.0)]
    assert field_tilt("home", events)[0] == 2 / 3
    facts = window_facts(events)
    home, away = by(facts, "field_tilt", "team:home:window:0"), by(facts, "field_tilt", "team:away:window:0")
    assert home.value == 0.67 and away.value == 0.33
    assert len(home.source_ids) == 3  # the 50 m pass is not in an attacking third


def test_passes_a_minute_and_the_window_edges():
    """Fifteen-minute windows: t = 899.9 is still the first, t = 900 the second."""
    events = [ev(t, "pass", "home", 50.0) for t in (0.0, 400.0, 899.9)] + [ev(900.0, "pass", "home", 50.0)]
    facts = window_facts(events)
    assert by(facts, "passes_per_minute", "team:home:window:0").value == 0.2
    assert by(facts, "passes_per_minute", "team:home:window:1").value == 0.07


def spell(start, home, away=0):
    """A window with `home` attacking-third passes by home and `away` by away."""
    return ([ev(start + 10 * i, "pass", "home", 90.0) for i in range(home)]
            + [ev(start + 10 * (home + i), "pass", "away", 10.0) for i in range(away)])


def test_a_side_leads_a_window_only_beyond_one_standard_error_of_level():
    """6 to 4 is a tilt of 0.6, inside 0.5 / sqrt(10) = 0.16 of level: nobody leads. 9 to 1 leads."""
    assert leader(spell(0, 6, 4))[0] is None
    assert leader(spell(0, 9, 1))[0] == "home"
    assert leader(spell(0, 1, 9))[0] == "away"
    assert leader(spell(0, 0, 0))[0] is None


def test_a_shift_is_the_other_side_taking_the_territory():
    events = spell(0, 9, 1) + spell(900, 1, 9) + spell(1800, 1, 9)
    shifts = territory_shifts(events)
    assert len(shifts) == 1
    shift = shifts[0]
    assert shift.scope == "team:away:window:1" and shift.value == 0.9
    assert set(shift.source_ids) == {e["id"] for e in events if 900 <= e["t"] < 1800}


def test_the_opening_lead_is_no_shift_and_a_level_window_keeps_the_leader():
    assert territory_shifts(spell(0, 1, 9)) == []
    assert territory_shifts(spell(0, 9, 1) + spell(900, 5, 5) + spell(1800, 9, 1)) == []
    shifts = territory_shifts(spell(0, 9, 1) + spell(900, 6, 4) + spell(1800, 1, 9))
    assert [f.scope for f in shifts] == ["team:away:window:2"]


def test_a_real_match_cites_only_its_own_events_and_repeats_exactly():
    m = simulate(7, 30)
    ids = {e["id"] for e in m.events}
    facts = [f for f in calculate_facts(m.events) if f.metric in
             ("ppda", "field_tilt", "passes_per_minute", "territory_shift")]
    assert {f.metric for f in facts} >= {"ppda", "field_tilt", "passes_per_minute"}
    assert all(f.source_ids and set(f.source_ids) <= ids for f in facts)
    assert all(0.0 <= f.value <= 1.0 for f in facts if f.metric == "field_tilt")
    again = [f for f in calculate_facts(simulate(7, 30).events) if f.metric in
             ("ppda", "field_tilt", "passes_per_minute", "territory_shift")]
    assert again == facts
