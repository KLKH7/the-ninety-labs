import asyncio
from pathlib import Path

from jsonschema import validate

from ninety.agents.cues import SCHEMA, build_fixture, write_fixture
from ninety.agents.factcheck import Claim, check
from ninety.agents.ledger import InMemoryLedger, load_match
from ninety.match.facts import match_events

FIXTURE = Path(__file__).parent / "fixtures" / "cues-seed7.jsonl"


def test_cues_validate_and_analyst_numbers_are_cited():
    cues = asyncio.run(build_fixture(7, 5))
    events = {event.id: event.payload for event in asyncio.run(_events())}
    event_counts = {
        event_type: sum(1 for event in events.values() if event["type"] == event_type)
        for event_type in ("pass", "shot", "goal")
    }
    assert len(cues) == 2 * sum(event_counts.values())
    for cue in cues:
        validate(cue, SCHEMA)
        if cue["persona"] == "analyst":
            assert check(Claim(cue["text"], cue["evidence"]), events).ok


async def _events():
    ledger = InMemoryLedger()
    await load_match(ledger, list(match_events(7, 5)), ())
    return await ledger.query(kind="event")


def test_fixture_regenerates_byte_for_byte(tmp_path):
    path = tmp_path / "cues.jsonl"
    asyncio.run(_write(path))
    assert path.read_bytes() == FIXTURE.read_bytes()


async def _write(path):
    write_fixture(await build_fixture(7, 5), path)
