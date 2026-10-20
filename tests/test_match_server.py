"""The match MCP server serves a fixed list of matches, the same whether computed or precomputed."""

import json

import pytest

from ninety.match import tracking
from ninety.match.facts import events_in
from ninety.mcp import match_server
from ninety.sim.engine import simulate


def test_an_unknown_match_is_refused(monkeypatch):
    with pytest.raises(ValueError, match="unknown match 'seed99'"):
        match_server.events_of("seed99")
    with pytest.raises(ValueError, match="unknown match"):
        match_server.match_info("seed8")


def test_list_events_filters_by_minute_and_type():
    rows = match_server.list_events("seed7", 2, 3, "pass")
    assert rows and all(r["type"] == "pass" and 2 <= r["minute"] <= 3 for r in rows)
    everything = match_server.list_events("seed7", 1, 5, None)
    assert {r["type"] for r in everything} > {"pass"}
    assert len(everything) <= match_server.MAX_EVENTS


def test_a_precomputed_match_is_the_computed_match(tmp_path, monkeypatch):
    match_server.precompute(tmp_path)
    stored = json.loads((tmp_path / "seed7.json").read_text())
    assert stored == events_in(7, match_server.MINUTES, 1, match_server.MINUTES + 1)
    assert sorted(p.stem for p in tmp_path.glob("*.json")) == sorted(match_server.MATCHES)
    # The phone companion's frames, from the same simulation, read back as the computed track.
    frames = tmp_path / tracking.FRAMES_DIR
    assert sorted(p.stem for p in frames.glob("*.json")) == sorted(match_server.MATCHES)
    tracking.track.cache_clear()
    read = tracking.track("seed7", 7, match_server.MINUTES, str(tmp_path))
    computed = tracking.from_match("seed7", simulate(7, match_server.MINUTES))
    assert read == computed and read.restarts == computed.restarts
    tracking.track.cache_clear()
    stats = json.loads((tmp_path / match_server.STATS_DIR / "seed7.json").read_text())
    assert stats == match_server.agent_rows(match_server.match_events(7, match_server.MINUTES))
    assert sorted(p.stem for p in (tmp_path / match_server.STATS_DIR).glob("*.json")) == sorted(
        match_server.MATCHES
    )


def test_the_server_reads_precomputed_stats(tmp_path, monkeypatch):
    # The stored stats are what match_info serves, not a fresh simulation.
    (tmp_path / match_server.STATS_DIR).mkdir()
    (tmp_path / match_server.STATS_DIR / "seed7.json").write_text(json.dumps([{"id": "s"}]))
    monkeypatch.setattr(match_server, "MATCH_DIR", str(tmp_path))
    match_server.stats_of.cache_clear()
    try:
        assert match_server.stats_of("seed7") == ({"id": "s"},)
    finally:
        match_server.stats_of.cache_clear()


def test_the_server_reads_a_precomputed_match(tmp_path, monkeypatch):
    # Proves the stored file is what is served, not a fresh simulation.
    (tmp_path / "seed7.json").write_text(json.dumps([{"id": "x", "minute": 1, "type": "pass"}]))
    monkeypatch.setattr(match_server, "MATCH_DIR", str(tmp_path))
    match_server.events_of.cache_clear()
    try:
        assert match_server.list_events("seed7", 1, 1, None) == [{"id": "x", "minute": 1, "type": "pass"}]
    finally:
        match_server.events_of.cache_clear()
