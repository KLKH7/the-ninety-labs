import asyncio

import pytest

from ninety.agents.ledger import InMemoryLedger, Record, load_match
from ninety.match.facts import match_events


def run(coro):
    return asyncio.run(coro)


def record(id="r1", *, kind="event", t=1.0, source="truth", payload=None, evidence=(), confidence=None):
    return Record(id, 1, kind, t, source, confidence, tuple(evidence), payload or {"type": "pass"})


def test_versioning_and_history_are_append_only():
    ledger = InMemoryLedger()
    first = run(ledger.append(record(payload={"value": 1})))
    second = run(ledger.append(record(payload={"value": 2})))
    assert first.version == 1 and second.version == 2
    assert run(ledger.get("r1", 1)).payload == {"value": 1}
    assert [item.version for item in run(ledger.history("r1"))] == [1, 2]


def test_as_of_hides_later_records_and_versions():
    ledger = InMemoryLedger()
    run(ledger.append(record(payload={"value": 1})))
    snapshot = run(ledger.snapshot())
    run(ledger.append(record(payload={"value": 2})))
    run(ledger.append(record("r2", t=2)))
    rows = run(ledger.query(as_of=snapshot))
    assert [(row.id, row.version) for row in rows] == [("r1", 1)]


@pytest.mark.parametrize(
    "bad",
    [
        record("bad-evidence", evidence=("missing",)),
        record("bad-vision", source="vision"),
        record("bad-claim", kind="claim", payload={"status": "unknown"}),
        record("bad-cue", kind="cue", payload={"id": "missing"}),
    ],
)
def test_invalid_records_are_rejected(bad):
    with pytest.raises(ValueError, match=bad.id):
        run(InMemoryLedger().append(bad))


def test_vision_confidence_zero_is_valid():
    stored = run(InMemoryLedger().append(record("vision", source="vision", confidence=0.0)))
    assert stored.confidence == 0.0


def test_load_match_resolves_event_evidence():
    events = list(match_events(7, 5))
    ledger = InMemoryLedger()
    run(load_match(ledger, events, ()))
    records = run(ledger.query())
    assert len([record for record in records if record.kind == "event"]) == len(events)
    event_ids = {record.id for record in records if record.kind == "event"}
    for fact in (record for record in records if record.kind == "fact"):
        assert set(fact.evidence) <= event_ids
