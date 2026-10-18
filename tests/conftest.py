"""Splits the suite across CI machines: `--shard K/N` runs every N-th test, starting at the K-th.

Collection is the same on every machine, so the N shards together run each test exactly once.
"""

import pytest


def pytest_addoption(parser):
    parser.addoption("--shard", default=None, help="K/N: run only the K-th of N equal parts of the suite")


def pytest_collection_modifyitems(config, items):
    shard = config.getoption("--shard")
    if not shard:
        return
    k, n = (int(x) for x in shard.split("/"))
    if not 1 <= k <= n:
        raise pytest.UsageError(f"--shard {shard}: K must be between 1 and N")
    keep = [item for i, item in enumerate(items) if i % n == k - 1]
    config.hook.pytest_deselected(items=[item for i, item in enumerate(items) if i % n != k - 1])
    items[:] = keep
