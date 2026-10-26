"""The served matches' frames (ninety/match/tracking.py)."""

import pytest

from ninety.match import tracking
from ninety.sim import engine


def test_the_frame_rate_is_the_engines():
    assert tracking.FPS == engine.FPS


def test_a_track_refuses_frames_from_two_sources():
    frames = ({"frame": 0, "t": 0.0, "source": "truth", "players": []},
              {"frame": 1, "t": 0.04, "source": "tracked", "players": []})
    with pytest.raises(ValueError, match="mix sources"):
        _ = tracking.Track("x", frames).source


# Tracked positions for the M1 clip (the phone companion's live path).

import json  # noqa: E402


def frame(i, source="tracked", pid="h-t12", team="home"):
    return {"frame": i, "t": i / 25, "source": source, "ball": {"x": 50.0, "y": 30.0, "z": 0.0},
            "players": [{"id": pid, "team": team, "x": 10.0 + i * 0.2, "y": 30.0}]}


def write(tmp_path, rows, restarts=()):
    path = tmp_path / "tracked-seed900001.json"
    path.write_text(json.dumps({"restarts": list(restarts), "frames": rows}))
    return str(path)


def load(path):
    tracking.tracked.cache_clear()
    try:
        return tracking.tracked("seed900001", path)
    finally:
        tracking.tracked.cache_clear()


def test_a_tracked_file_loads_as_tracked_positions(tmp_path):
    t = load(write(tmp_path, [frame(i) for i in range(5)], restarts=[3]))
    assert t.source == "tracked" and t.roster == ("h-t12",) and len(t.frames) == 5
    assert 3 in t.restarts


@pytest.mark.parametrize("rows, message", [
    ([frame(0), frame(1, source="truth")], "source 'truth'"),
    ([frame(0), frame(1, source=None)], "source None"),
    ([frame(0), frame(0)], "strictly increasing"),
    ([frame(0), frame(1, pid="7")], "not track ids"),
    ([frame(0), frame(1, pid="h7")], "not track ids"),  # a track is never given a shirt number
    ([frame(0), frame(1, pid="a-t3")], "not track ids"),  # an away track on the home team
    ([frame(0), {"frame": 1, "t": 0.04, "source": "tracked", "players": []}], "not a frame"),
    ([frame(0)], "fewer than two frames"),
])
def test_anything_but_tracked_roster_frames_is_refused(tmp_path, rows, message):
    if rows[1:] and rows[1].get("source") is None and "source" in rows[1]:
        del rows[1]["source"]
    with pytest.raises(tracking.NotTracked, match=message):
        load(write(tmp_path, rows))


def test_a_missing_tracked_file_or_clip_is_refused(tmp_path):
    with pytest.raises(tracking.NotTracked, match="no tracked positions yet"):
        load(str(tmp_path / "tracked-seed900001.json"))
    with pytest.raises(tracking.NotTracked, match="not a tracked clip"):
        tracking.tracked("seed7")


def test_the_kickoffs_are_the_restarts_a_track_carries():
    # Review of #145: kickoffs() returning () left every test green, so a reset read as running.
    events = [
        {"type": "kickoff", "frame": 0}, {"type": "pass", "frame": 3}, {"type": "kickoff", "frame": 125},
    ]
    assert tracking.kickoffs(events) == (0, 125)
    frames = [frame(i, source="truth", pid="h7") for i in range(3)]
    run = type("Run", (), {"frames": frames, "events": events})
    assert tracking.from_match("seed7", run).restarts == (0, 125)


def test_the_served_clips_come_from_the_deployments_packages(tmp_path):
    # Config, not code (NINETY_SERVED_DIR): a folder per clip with its tracked positions, detected events
    # and clip.json is served by name, beside the M1 clip; an incomplete one is not. Read at import, so
    # checked in a fresh interpreter, as the deployed server starts.
    import os
    import shutil
    import subprocess
    import sys
    from pathlib import Path

    fixtures = Path(__file__).resolve().parent / "fixtures"
    full = tmp_path / "seedtest-match"
    full.mkdir()
    shutil.copy(fixtures / "tracked-seed900001.json", full / "tracked.json")
    shutil.copy(fixtures / "detected-seed900001.jsonl", full / "detected.jsonl")
    shutil.copy(fixtures / "fixture-seed900001.json", full / "clip.json")
    half = tmp_path / "seedhalf-match"
    half.mkdir()
    shutil.copy(fixtures / "tracked-seed900001.json", half / "tracked.json")  # no events, no clip.json
    probe = (
        "from ninety.match import tracking; from ninety.mcp import match_server as m;"
        "from ninety.api import companion as c;"
        "assert tracking.TRACKED_CLIPS == ('seed900001', 'seedtest-match'), tracking.TRACKED_CLIPS;"
        "assert len(tracking.tracked('seedtest-match').frames) > 1;"
        "assert m.insights_of('seedtest-match') is not None;"
        "assert 'seedtest-match' in c.CLIPS and 'seedhalf-match' not in c.CLIPS;"
        "print('ok')"
    )
    env = {**os.environ, "NINETY_SERVED_DIR": str(tmp_path)}
    done = subprocess.run([sys.executable, "-c", probe], env=env, capture_output=True, text=True,
                          timeout=300)
    assert done.returncode == 0 and done.stdout.strip() == "ok", done.stderr[-2000:]
    # Unset, only the M1 clip is served, as before.
    plain = {k: v for k, v in env.items() if k != "NINETY_SERVED_DIR"}
    listed = "from ninety.match import tracking; print(tracking.TRACKED_CLIPS)"
    done = subprocess.run([sys.executable, "-c", listed], env=plain, capture_output=True, text=True,
                          timeout=120)
    assert done.stdout.strip() == "('seed900001',)", done.stderr[-1000:]
