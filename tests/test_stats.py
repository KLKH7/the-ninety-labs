from ninety.intel.stats import (
    calculate_facts,
    control_vs_chaos,
    pass_facts,
    player_movement_facts,
    possession_facts,
    shot_facts,
)
from ninety.sim.engine import simulate


def _by_id(facts):
    return {fact.id: fact for fact in facts}


def test_pass_and_shot_facts_are_deterministic_and_cited():
    match = simulate(7, 5)
    first = calculate_facts(match.events)
    second = calculate_facts(match.events)
    assert first == second
    facts = _by_id(first)
    assert facts["passes_attempted:home"].value > 0
    assert 0 <= facts["pass_completion_rate:home"].value <= 1
    assert facts["shots:home"].value + facts["shots:away"].value > 0
    assert all(fact.source_ids for fact in first)


def test_pass_and_shot_groupings_match_event_truth():
    match = simulate(11, 3)
    passes = pass_facts(match.events)
    shots = shot_facts(match.events)
    assert _by_id(passes)["passes_attempted:home"].value == sum(
        event["team"] == "home" and event["type"] == "pass" for event in match.events
    )
    assert _by_id(shots)["goals:away"].value == sum(
        event["team"] == "away" and event["type"] == "shot" and event["outcome"] == "goal"
        for event in match.events
    )


def test_possession_shares_sum_to_one():
    match = simulate(3, 1)
    facts = _by_id(possession_facts(match.frames))
    assert facts["possession_share:team_home"].value + facts["possession_share:team_away"].value == 1


def test_player_movement_has_non_negative_values_and_cap():
    match = simulate(5, 1)
    facts = player_movement_facts(match.frames)
    assert len(facts) == 22 * 3
    for fact in facts:
        assert fact.value >= 0
    assert max(fact.value for fact in facts if fact.metric == "peak_speed") <= 40


def test_control_vs_chaos_rejects_invalid_window():
    try:
        control_vs_chaos([], 0)
    except ValueError as error:
        assert "positive" in str(error)
    else:
        raise AssertionError("expected invalid window to be rejected")
