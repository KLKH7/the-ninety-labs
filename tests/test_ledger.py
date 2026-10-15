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


def test_load_match_refuses_a_fact_citing_a_missing_event(monkeypatch):
    # planted defect: before the fix, the unknown id was silently dropped from evidence
    from ninety.agents import ledger as ledger_module
    from ninety.intel.stats import Fact

    monkeypatch.setattr(
        ledger_module, "calculate_facts",
        lambda events, frames: [Fact("f1", "passes", 1, "count", "home", ("e99999",))],
    )
    with pytest.raises(ValueError, match="e99999"):
        run(load_match(InMemoryLedger(), list(match_events(7, 0.5)), ()))


def test_load_match_keeps_frame_ranges_out_of_evidence_and_times_them():
    from ninety.sim.engine import simulate

    match = simulate(7, 1)
    ledger = InMemoryLedger()
    run(load_match(ledger, match.events, match.frames))
    framed = [r for r in run(ledger.query(kind="fact"))
              if any(s.startswith("frames:") for s in r.payload["source_ids"])]
    assert framed, "seed 7 with frames should give possession or movement facts"
    for fact in framed:
        assert not any(s.startswith("frames:") for s in fact.evidence)
        assert 0 < fact.t <= match.frames[-1]["t"]
