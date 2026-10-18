"""The Data agent's rules: an exact, reproducible split of the budget; only render settings the
renderer has; only training seeds; one commit per round."""

import pytest

from ninety.agents.data_agent import allocate, plan, render_set


def clusters(*misses):
    return [{"name": f"c{i}", "misses": m, "render": {}} for i, m in enumerate(misses)]


@pytest.mark.parametrize(
    "misses, budget, want",
    [
        ((37, 12, 1, 0), 40, [30, 9, 1, 0]),  # proportional; the 1-miss cluster gets its one clip, no more
        ((37, 12, 1), 2, [1, 1, 0]),  # a small budget goes to the biggest failures first
        ((5, 5), 3, [2, 1]),  # ties go to the earlier cluster, so the plan is reproducible
        ((0, 0), 10, [0, 0]),  # nothing failed, nothing rendered
        ((10,), 7, [7]),
    ],
)
def test_the_budget_is_split_by_misses(misses, budget, want):
    got = allocate(clusters(*misses), budget)
    assert got == want and sum(got) == (budget if any(misses) else 0)


def test_render_settings_are_validated_by_the_renderer():
    assert render_set({"occlusion": "crowded", "kit_contrast": "low"}) == "kit_contrast=low;occlusion=crowded"
    with pytest.raises(ValueError):
        render_set({"no_such_knob": 1})
    with pytest.raises(ValueError):
        render_set({"lighting": "underwater"})


def test_a_planned_knob_is_refused():
    # Lighting and weather are pinned to day and clear (params.PLANNED): a round cannot ask for rain.
    with pytest.raises(NotImplementedError):
        render_set({"weather": "rain"})
    with pytest.raises(NotImplementedError):
        render_set({"lighting": "night"})


HANDOFF = {
    "round": "round1",
    "clusters": [
        {"name": "ball hidden in a crowded box", "misses": 30, "render": {"occlusion": "crowded"}},
        {
            "name": "low kit contrast on a camera cut",
            "misses": 10,
            "render": {"camera_cut": True, "kit_contrast": "low"},
        },
    ],
}


def test_a_plan_covers_the_budget_in_requests_of_bounded_size():
    p = plan(HANDOFF, 24, 2001, "abc123", per_request=10)
    assert [c["clips"] for c in p["clusters"]] == [18, 6]
    assert [(r["first_seed"], r["count"]) for r in p["requests"]] == [(2001, 10), (2011, 8), (2019, 6)]
    assert {r["commit"] for r in p["requests"]} == {"abc123"}
    assert p["requests"][2]["set"] == "camera_cut=true;kit_contrast=low"
    assert "crowded box (30 misses)" in p["requests"][0]["reason"]


def test_a_round_never_reaches_the_test_seeds():
    with pytest.raises(ValueError, match="reserved|test"):
        plan(HANDOFF, 40, 899990, "abc123")


def test_a_round_name_cannot_escape_its_folder():
    with pytest.raises(ValueError):
        plan(HANDOFF | {"round": "../x"}, 4, 2001, "abc123")
