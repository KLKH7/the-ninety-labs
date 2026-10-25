"""The match MCP server serves a fixed list of matches, the same whether computed or precomputed."""

import json
from pathlib import Path

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


def test_team_shape_serves_tracked_facts_and_nothing_for_a_simulated_match():
    shaped = match_server.team_shape("seed900001", 1, 99)
    assert shaped["tracked"] and shaped["facts"]
    assert all(f["type"] == "shape" and f["id"].startswith("shape:") for f in shaped["facts"])
    # The broadcast camera's tracked frames see too few players: every fact says so.
    assert not any(f["confident"] for f in shaped["facts"])
    none = {"match": "seed7", "tracked": False, "need": 11, "facts": []}
    assert match_server.team_shape("seed7", 1, 5) == none
    with pytest.raises(ValueError, match="unknown match"):
        match_server.team_shape("seed99", 1, 5)


def test_team_shape_filters_by_minute():
    facts = match_server.team_shape("seed900001", 1, 99)["facts"]
    minute = facts[0]["minute"]
    assert match_server.team_shape("seed900001", minute + 1, 99)["facts"] == [
        f for f in facts if f["minute"] > minute]


def test_re_perceive_looks_again_through_a_camera_the_clip_has(tmp_path, monkeypatch):
    from ninety.match import detected

    views = tmp_path / detected.M1_CLIP / "tactical1"
    views.mkdir(parents=True)
    obs = Path(__file__).resolve().parent / "fixtures" / "observations-seed900001.jsonl"
    (views / "observations.jsonl").write_text(obs.read_text())
    monkeypatch.setattr(match_server, "VIEWS_DIR", str(tmp_path))
    match_server._perceiver.cache_clear()
    try:
        look = match_server.re_perceive(detected.M1_CLIP, "v00001", "tactical1", "window")
        assert look["found"]["type"] == "pass" and look["found"]["team"] == "away"
        assert match_server.re_perceive(detected.M1_CLIP, "v00001", "tactical2", "window")["found"] is None
    finally:
        match_server._perceiver.cache_clear()


def test_re_perceive_without_camera_views_says_so_and_refuses_what_it_cannot_look_at():
    from ninety.match import detected

    match_server._perceiver.cache_clear()
    look = match_server.re_perceive(detected.M1_CLIP, "v00001", "tactical1", "window")
    assert look["found"] is None and "no per-camera observations" in look["why"]
    with pytest.raises(ValueError, match="no detected events"):
        match_server.re_perceive("seed7", "e1", "tactical1", "window")
    with pytest.raises(ValueError, match="no detected event"):
        match_server.re_perceive(detected.M1_CLIP, "nope", "tactical1", "window")
