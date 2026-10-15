import asyncio
from pathlib import Path

import pytest
from jsonschema import validate

from ninety.agents import cues
from ninety.agents.cues import SCHEMA, build_fixture, template_cues, write_fixture
from ninety.agents.factcheck import Claim, check
from ninety.agents.ledger import InMemoryLedger, Record, load_match
from ninety.match.facts import match_events

FIXTURE = Path(__file__).parent / "fixtures" / "cues-seed7.jsonl"


def test_cues_validate_and_analyst_numbers_are_cited():
    fixture = asyncio.run(build_fixture(7, 5))
    events = {event.id: event.payload for event in asyncio.run(_events())}
    event_counts = {
        event_type: sum(1 for event in events.values() if event["type"] == event_type)
        for event_type in ("pass", "shot", "goal")
    }
    assert len(fixture) == 2 * sum(event_counts.values())
    for cue in fixture:
        validate(cue, SCHEMA)
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


def _cue_texts(event):
    ledger = InMemoryLedger()
    asyncio.run(ledger.append(Record(event["id"], 1, "event", event["t"], "truth", None, (), event)))
    return {cue["persona"]: cue["text"] for cue in asyncio.run(template_cues(ledger))}


PASS = {"id": "e1", "t": 3.0, "type": "pass", "team": "home", "player": "h7", "receiver": "h9",
        "outcome": "success", "distance_m": 24.0, "ball_speed_kmh": 61.0}


def test_completed_pass_finds_its_receiver():
    texts = _cue_texts(PASS)
    assert texts == {"analyst": "h7 → h9, 24.0 m, 61.0 km/h", "casual": "h7 finds h9"}


def test_failed_pass_never_says_it_found_the_receiver():
    # planted defect: before the fix, a failed pass aired as "h7 finds h9"
    texts = _cue_texts({**PASS, "outcome": "fail"})
    assert "finds" not in texts["casual"] and "doesn't arrive" in texts["casual"]
    assert "(incomplete)" in texts["analyst"]


def test_shot_and_goal_cues():
    shot = {"id": "e2", "t": 5.0, "type": "shot", "team": "away", "player": "a10", "outcome": "blocked",
            "ball_speed_kmh": 99.1}
    assert _cue_texts(shot) == {"analyst": "a10 shot, blocked, 99.1 km/h", "casual": "a10 takes a shot"}
    goal = {"id": "e3", "t": 5.2, "type": "goal", "team": "away", "player": "a10"}
    assert _cue_texts(goal) == {"analyst": "a10 scores", "casual": "a10 scores"}


def test_a_cue_with_an_uncited_number_is_refused(monkeypatch):
    # planted defect: a template that invents a number must not produce a cue
    monkeypatch.setattr(cues, "_text", lambda event, persona: f"{event['player']} pass, 99 m")
    with pytest.raises(ValueError, match="99"):
        _cue_texts(PASS)


def test_cue_times_are_rounded_to_event_precision():
    ledger = InMemoryLedger()
    asyncio.run(ledger.append(Record("e4", 1, "event", 4.12, "truth", None, (), {**PASS, "id": "e4"})))
    assert {cue["t_out"] for cue in asyncio.run(template_cues(ledger))} == {9.12}
