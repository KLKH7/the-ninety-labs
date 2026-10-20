"""Every row of docs/eval/failure-table-m1.md (the M1 live path's): the injected failure, the
fallback that must run, and what the viewer must see. Expected values are written here, not read
from the table."""

import pytest

from ninety.eval import failure_table

BASE = failure_table.run(failure_table.SCENARIOS[0])

# scenario -> (claim status, drafts, fallback text starts with, insight airs, template cues lost)
EXPECTED = {
    "none": ("verified", 1, "accepted", True, 0),
    "judge down": ("held", 3, "held, out of rewrites: judge service error", False, 0),
    "judge timeout": ("held", 3, "held, out of rewrites: judge timeout", False, 0),
    "judge malformed": ("held", 3, "held, out of rewrites: judge returned invalid response", False, 0),
    "analyst down": ("none", 0, "workflow stopped (AgentFrameworkException", False, 0),
    "mcp timeout": ("none", 0, "workflow stopped (no checked claim within", False, 0),
    "analyst malformed": ("none", 0, "workflow stopped (JSONDecodeError", False, 0),
    "low confidence": ("held", 3, "held, out of rewrites: event standin-e011 was detected with "
                       "confidence 0.30", False, 2),
}


def test_every_scenario_has_an_expectation():
    assert [s.name for s in failure_table.SCENARIOS] == list(EXPECTED)


@pytest.mark.parametrize("scenario", failure_table.SCENARIOS, ids=lambda s: s.name)
def test_failure_row(scenario):
    status, drafts, fallback, insight, lost = EXPECTED[scenario.name]
    row = BASE if scenario.name == "none" else failure_table.run(scenario)
    assert row["status"] == status
    assert row["drafts"] == drafts
    assert row["fallback"].startswith(fallback)
    assert bool(row["insight"]) is insight
    # The template graphics stay up: the same cues as with no failure, less only those on the unsure
    # detection, which the gate keeps off the screen.
    assert set(row["template_ids"]) <= set(BASE["template_ids"])
    assert len(BASE["template_ids"]) - len(row["template_ids"]) == lost
    if lost:
        assert all(row["event"] in i for i in set(BASE["template_ids"]) - set(row["template_ids"]))
        assert row["event"] in row["held_detections"]
