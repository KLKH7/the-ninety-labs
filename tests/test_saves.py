from ninety.sim.saves import shoot_once


def test_an_isolated_shot_always_ends_with_an_outcome():
    # seed 3 at 11 m is parried loose with nobody near: the engine's own close still names it
    for spot in ("o1", "line"):
        for seed in range(6):
            assert shoot_once(seed, 11, spot) in {"goal", "on_target", "off_target"}


def test_into_an_empty_net_nothing_is_saved():
    # A control that can fail: with the keeper out of the way, an on-target shot from 11 m goes in.
    outcomes = [shoot_once(seed, 11, "none") for seed in range(12)]
    assert "on_target" not in outcomes and outcomes.count("goal") >= 6
