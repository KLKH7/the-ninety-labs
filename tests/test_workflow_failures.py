"""The failure table (docs/eval/failure-table.md): each injected failure in the multi-agent workflow,
and what must recover. Expected values are written here, not read from the table (lesson 8)."""

from __future__ import annotations

import pytest

from ninety.eval import workflow_failures as wf

ROWS = {r["scenario"]: r for r in wf.rows()}
BASE = ROWS["none"]

# scenario -> (claim status, verdict category, Judge calls, an insight airs, template graphics lost)
EXPECTED = {
    "none": ("verified", None, 1, True, 0),
    # The real Judge wrapper retries once, then holds: two calls, then the template stays.
    "judge timeout": ("held", "timeout", 2, False, 0),
    # The Tactician never answers, so there is nothing for the Judge to read.
    "tactician outage": ("held", "service", 0, False, 0),
    # The confidence gate holds the claim before the Judge, and the unsure pass's two graphics
    # (analyst and casual) are not drawn.
    "low confidence": ("held", "low_confidence", 0, False, 2),
}


def test_every_scenario_has_an_expectation():
    assert list(ROWS) == list(EXPECTED)


@pytest.mark.parametrize("name", list(EXPECTED))
def test_failure_row(name):
    status, category, asked, insight, lost = EXPECTED[name]
    row = ROWS[name]
    assert row["status"] == status and row["category"] == category
    assert row["judge_asked"] == asked
    assert bool(row["insights"]) is insight
    assert all(i["verified"] for i in row["insights"])
    assert set(row["templates"]) <= set(BASE["templates"])
    assert len(BASE["templates"]) - len(row["templates"]) == lost
    if lost:  # only the unsure detection's graphics are gone
        assert all(f"-{wf.SIDE}-" in i for i in set(BASE["templates"]) - set(row["templates"]))
    if name != "none":
        assert any("stays" in step for step in row["fallback"])  # the trace says the template stayed


def test_every_injected_failure_recovers():
    assert [r["scenario"] for r in ROWS.values() if not r["recovers"]] == []


def test_the_recovery_check_can_fail():
    # A row that aired an unchecked claim, dropped a template and recorded no fallback is caught on
    # each count: the table's "yes" is a measurement, not a constant.
    broken = {**ROWS["tactician outage"], "insights": [{"text": "x", "verified": False}],
              "templates": BASE["templates"][1:], "fallback": [], "status": "verified"}
    assert wf.recovered(broken, BASE) == {
        "templates stay": False, "nothing unverified airs": False,
        "claim held or rejected": False, "fallback recorded": False,
    }


def test_the_committed_table_is_up_to_date():
    stale = [p.name for p, text in wf.render().items() if not p.exists() or p.read_text() != text]
    assert stale == [], f"run {wf.COMMAND}"
