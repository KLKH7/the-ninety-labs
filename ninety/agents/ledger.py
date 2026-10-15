"""Append-only shared state for the agent pipeline.

The in-memory implementation uses an asyncio lock around a synchronous core. A future Cosmos
implementation can satisfy the same protocol without changing its callers.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Literal, Protocol, cast

from jsonschema import validate
from jsonschema.exceptions import ValidationError

from ninety.intel.stats import calculate_facts
from ninety.match.facts import compact

Kind = Literal["event", "fact", "claim", "cue"]
OVERLAY_SCHEMA = Path(__file__).resolve().parents[2] / "schemas" / "overlay_cue.schema.json"


@dataclass(frozen=True)
class Record:
    id: str
    version: int
    kind: Kind
    t: float
    source: str
    confidence: float | None
    evidence: tuple[str, ...]
    payload: dict


class Ledger(Protocol):
    async def append(self, record: Record) -> Record: ...

    async def get(self, id: str, version: int | None = None) -> Record | None: ...

    async def history(self, id: str) -> list[Record]: ...

    async def query(
        self,
        kind: Kind | None = None,
        t_from: float | None = None,
        t_to: float | None = None,
        source: str | None = None,
        as_of: int | None = None,
    ) -> list[Record]: ...

    async def snapshot(self) -> int: ...


class InMemoryLedger:
    """Async-safe append-only Ledger with a monotonically increasing global sequence."""

    def __init__(self) -> None:
        self._records: dict[str, list[tuple[int, Record]]] = {}
        self._sequence = 0
        self._lock = asyncio.Lock()

    async def append(self, record: Record) -> Record:
        async with self._lock:
            return self._append(record)

    def _append(self, record: Record) -> Record:
        self._validate(record)
        history = self._records.setdefault(record.id, [])
        version = len(history) + 1
        stored = replace(record, version=version, evidence=tuple(record.evidence))
        self._sequence += 1
        history.append((self._sequence, stored))
        return stored

    async def get(self, id: str, version: int | None = None) -> Record | None:
        async with self._lock:
            history = self._records.get(id, [])
            if version is None:
                return history[-1][1] if history else None
            return next((record for _, record in history if record.version == version), None)

    async def history(self, id: str) -> list[Record]:
        async with self._lock:
            return [record for _, record in self._records.get(id, [])]

    async def query(
        self,
        kind: Kind | None = None,
        t_from: float | None = None,
        t_to: float | None = None,
        source: str | None = None,
        as_of: int | None = None,
    ) -> list[Record]:
        async with self._lock:
            latest: list[Record] = []
            for history in self._records.values():
                visible = [
                    record
                    for sequence, record in history
                    if as_of is None or sequence <= as_of
                ]
                if not visible:
                    continue
                record = visible[-1]
                if kind is not None and record.kind != kind:
                    continue
                if t_from is not None and record.t < t_from:
                    continue
                if t_to is not None and record.t > t_to:
                    continue
                if source is not None and record.source != source:
                    continue
                latest.append(record)
            return sorted(latest, key=lambda record: (record.t, record.id))

    async def snapshot(self) -> int:
        async with self._lock:
            return self._sequence

    def _validate(self, record: Record) -> None:
        if not record.id:
            raise ValueError("record id must not be empty")
        if record.kind not in {"event", "fact", "claim", "cue"}:
            raise ValueError(f"record {record.id}: invalid kind {record.kind!r}")
        try:
            json.dumps(record.payload)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"record {record.id}: payload is not JSON-serialisable") from exc
        for evidence_id in record.evidence:
            if evidence_id not in self._records:
                raise ValueError(f"record {record.id}: unknown evidence id {evidence_id}")
        if record.source == "vision" and (
            record.confidence is None or not 0 <= record.confidence <= 1
        ):
            raise ValueError(f"record {record.id}: vision records require confidence from 0 to 1")
        if record.source in {"truth", "stats"} and record.confidence is not None:
            raise ValueError(f"record {record.id}: {record.source} records require confidence=None")
        if record.kind == "cue":
            try:
                validate(record.payload, json.loads(OVERLAY_SCHEMA.read_text()))
            except ValidationError as exc:
                raise ValueError(f"record {record.id}: cue payload fails overlay schema: {exc}") from exc
        if record.kind == "event" and record.source == "vision" and record.confidence is None:
            raise ValueError(f"record {record.id}: vision event requires confidence")
        if record.kind == "claim" and record.payload.get("status") not in {
            "draft", "verified", "rejected", "held"
        }:
            raise ValueError(f"record {record.id}: invalid claim status")


async def load_match(ledger: Ledger, events: Iterable[Mapping], frames: Iterable[Mapping]) -> None:
    """Load events and computed facts while preserving their original evidence references."""
    event_list = [dict(event) for event in events]
    event_by_id = {str(event["id"]): event for event in event_list}
    for event in event_list:
        await ledger.append(
            Record(
                id=str(event["id"]),
                version=1,
                kind="event",
                t=float(event["t"]),
                source=str(event.get("source", "truth")),
                confidence=event.get("confidence"),
                evidence=(),
                payload=compact(event),
            )
        )
    for fact in calculate_facts(event_list, frames):
        event_ids = tuple(source_id for source_id in fact.source_ids if source_id in event_by_id)
        event_times = [float(event_by_id[event_id]["t"]) for event_id in event_ids]
        # Frame ranges remain in the fact payload; frames are not Ledger records.
        payload = fact.as_dict()
        await ledger.append(
            Record(
                id=fact.id,
                version=1,
                kind="fact",
                t=max(event_times, default=0.0),
                source="stats",
                confidence=None,
                evidence=event_ids,
                payload=payload,
            )
        )


def record_from_dict(data: Mapping) -> Record:
    return Record(
        id=str(data["id"]),
        version=int(data.get("version", 1)),
        kind=cast(Kind, data["kind"]),
        t=float(data["t"]),
        source=str(data["source"]),
        confidence=data.get("confidence"),
        evidence=tuple(data.get("evidence", ())),
        payload=dict(data["payload"]),
    )
