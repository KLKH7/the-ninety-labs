"""Splits the suite across CI machines: `--shard K/N` runs the K-th of N parts.

Every collected test goes to exactly one part, so the N parts together run the whole suite; the
split only decides which machine runs what. Collection is the same on every machine.

Simulations slow each other down when they share a machine, so the slowest tests (measured on
CI) are dealt out first, one per part, and the rest round-robin. A test missing from SLOWEST
still runs; it is only placed less well.
"""

import pytest

SLOWEST = (  # slowest first, measured in CI's test job on 2026-10-18
    "tests/test_judge.py::test_tone_labels_fit_their_events",  # seed 7 over 30 and 90 minutes
    "tests/test_sim.py::test_football_realistic_rates_over_a_full_match",  # a 90-minute match
    "tests/test_clock.py::test_agent_events_use_the_same_clock_as_the_scorebug",  # 30 minutes
    "tests/test_engine_rules.py::test_a_throw_in_taker_runs_to_his_spot_and_stops_there",
    "tests/test_match_server.py::test_a_precomputed_match_is_the_computed_match",
)


def pytest_addoption(parser):
    parser.addoption("--shard", default=None, help="K/N: run only the K-th of N parts of the suite")


def shard_of(items, n):
    """The part (0 to n-1) each item runs in."""
    slow = sorted((i for i, item in enumerate(items) if item.nodeid in SLOWEST),
                  key=lambda i: SLOWEST.index(items[i].nodeid))
    rest = [i for i in range(len(items)) if items[i].nodeid not in SLOWEST]
    return {i: j % n for j, i in enumerate(slow + rest)}


def pytest_collection_modifyitems(config, items):
    shard = config.getoption("--shard")
    if not shard:
        return
    k, n = (int(x) for x in shard.split("/"))
    if not 1 <= k <= n:
        raise pytest.UsageError(f"--shard {shard}: K must be between 1 and N")
    part = shard_of(items, n)
    config.hook.pytest_deselected(items=[item for i, item in enumerate(items) if part[i] != k - 1])
    items[:] = [item for i, item in enumerate(items) if part[i] == k - 1]


@pytest.fixture(autouse=True)
def _ask_trace_in_tmp(tmp_path, monkeypatch):
    """The API's per-question trace (ninety/agents/telemetry.py) goes to the test's folder, not runs/."""
    monkeypatch.setenv("NINETY_ASK_TRACE", str(tmp_path / "ask-trace.jsonl"))
    monkeypatch.delenv("APPLICATIONINSIGHTS_CONNECTION_STRING", raising=False)
