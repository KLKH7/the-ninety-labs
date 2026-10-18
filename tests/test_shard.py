"""The CI split (tests/conftest.py) runs every test exactly once and keeps the slowest apart."""

from types import SimpleNamespace

from conftest import SLOWEST, shard_of


def items(nodeids):
    return [SimpleNamespace(nodeid=n) for n in nodeids]


def test_every_test_runs_in_exactly_one_part():
    suite = items([f"tests/test_x.py::test_{i}" for i in range(50)] + list(SLOWEST))
    for n in (1, 2, 3, 4):
        part = shard_of(suite, n)
        assert sorted(part) == list(range(len(suite)))
        assert set(part.values()) == set(range(n))


def test_the_slowest_tests_land_in_different_parts():
    suite = items([f"tests/test_x.py::test_{i}" for i in range(50)] + list(SLOWEST)[::-1])
    part = shard_of(suite, 3)
    where = {s.nodeid: part[i] for i, s in enumerate(suite) if s.nodeid in SLOWEST}
    assert [where[n] for n in SLOWEST[:3]] == [0, 1, 2]
