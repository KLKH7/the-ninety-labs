"""The phone's tracked positions (ninety/vision/tracked_frames.py): built from the video's
observations without the answer key, in the frame schema, and smoothed so jitter is not running."""

from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path

from ninety.agents.contracts import schema_validator
from ninety.intel.window import player_window
from ninety.vision import track as tr
from ninety.vision import tracked_frames as tf
from tests.test_vision_live_path import run_audited, truth_reads

ROOT = Path(__file__).resolve().parents[1]
OBSERVATIONS = ROOT / "tests" / "fixtures" / "observations-seed900001.jsonl"
FIXTURE = ROOT / "tests" / "fixtures" / "tracked-seed900001.json"
REPORT = ROOT / "docs" / "eval" / "companion-tracked.json"
FRAME = schema_validator("frame")


def test_the_committed_tracked_frames_are_what_the_builder_writes_from_the_observations():
    body = tf.build(tr.read_observations(OBSERVATIONS), "seed900001")
    assert FIXTURE.read_text() == tf.text(body), (
        "re-run: uv run python -m ninety.vision.tracked_frames tests/fixtures/observations-seed900001.jsonl"
    )


def test_every_tracked_frame_meets_the_frame_schema_and_says_tracked():
    body = json.loads(FIXTURE.read_text())
    assert set(body) == {"restarts", "frames"} and body["restarts"] == []
    frames = body["frames"]
    assert len(frames) > 200
    for f in frames:
        FRAME.validate(f)
        assert f["source"] == "tracked" and f["clip"] == "seed900001"
        for p in f["players"]:
            assert re.fullmatch(r"[ha]-t\d+", p["id"]) and p["id"][0] == p["team"][0]


def test_the_graded_report_is_about_the_committed_file():
    report = json.loads(REPORT.read_text())
    assert report["graded_sha256"] == hashlib.sha256(FIXTURE.read_bytes()).hexdigest()
    assert report["shipped_smoothing"] == tf.SMOOTH_FRAMES


BUILD_STAGE = """
    from ninety.vision import track, tracked_frames
    rows = track.read_observations("tests/fixtures/observations-seed900001.jsonl")
    body = tracked_frames.build(rows, "seed900001")
    OUT = {"frames": len(body["frames"]), "sources": sorted({f["source"] for f in body["frames"]})}
"""


def test_building_the_tracked_frames_opens_no_truth():
    run = run_audited(BUILD_STAGE)
    assert run["out"]["frames"] > 200 and run["out"]["sources"] == ["tracked"]  # it did the work
    assert any(o.endswith("observations-seed900001.jsonl") for o in run["opened"])
    assert truth_reads(run) == []


def jittered(speed_mps: float, n: int = 100, jitter: float = 0.5) -> list[dict]:
    """One home player moving along x at `speed_mps`, his position off by +-jitter metres in turn,
    as the camera fit moves a foot point between neighbouring frames (track.py, GATE_M)."""
    frames = []
    for i in range(n):
        x = 30.0 + speed_mps * i / tr.FPS + (jitter if i % 2 else -jitter)
        frames.append((1000 + i, (x, 34.0)))
    return frames


def window_speed(frames, positions, since: int | None = None, upto: int | None = None) -> tuple[float, float]:
    """The companion's speed now and top speed (ninety/intel/window.py) from frame `since` to `upto`."""
    rows = [{"frame": f, "t": f / tr.FPS, "players": [{"id": "h1", "team": "home", "x": x, "y": y}]}
            for f, (x, y) in zip(frames, positions, strict=True)]
    start = rows[0]["t"] if since is None else since / tr.FPS
    end = rows[-1]["t"] if upto is None else upto / tr.FPS
    w = player_window(rows, "h1", start, end)
    return w.speed_now.value, w.peak_speed.value


def test_smoothing_turns_jitter_back_into_standing_and_keeps_running():
    jitter = 0.5
    # Inside a track the line through SMOOTH_FRAMES positions sits at their average. Jitter that
    # flips sign every frame is the average's worst case: over an odd width W one sign wins by one
    # sample, leaving +-jitter/W that flips every frame, a step of 2 * jitter / W.
    bound_kmh = 2 * jitter / tf.SMOOTH_FRAMES * tr.FPS * 3.6
    # Whatever the width, standing must not read as more than a walk: Bradley et al. 2009 (the
    # source of GROUNDING FS4) start jogging at 7.2 km/h.
    jogging_kmh = 7.2
    for speed in (0.0, 5.0):  # standing, then a run at 18 km/h
        track = jittered(speed, jitter=jitter)
        frames = [f for f, _ in track]
        raw = [p for _, p in track]
        # Away from the track's ends: a full window of positions either side of every frame read.
        inside = (frames[tf.SMOOTH_FRAMES], frames[-tf.SMOOTH_FRAMES])
        _, raw_peak = window_speed(frames, raw, *inside)
        now, peak = window_speed(frames, tf.smooth(raw, frames), *inside)
        assert raw_peak > speed * 3.6 + 40  # the jitter alone reads as an impossible sprint
        assert abs(now - speed * 3.6) <= bound_kmh + 0.1, (speed, now)  # 0.1: the facts' rounding
        assert peak <= speed * 3.6 + bound_kmh + 0.1, (speed, peak)
        if speed == 0:
            assert peak < jogging_kmh, peak


def test_a_track_ends_at_the_speed_its_player_was_running():
    # At a track's last frame there is no second ahead to average over; an average there trails
    # the player and reads him slower than he ran. A straight run must read its own speed.
    track = jittered(5.0, jitter=0.0)
    frames = [f for f, _ in track]
    now, peak = window_speed(frames, tf.smooth([p for _, p in track], frames))
    assert math.isclose(now, 18.0, abs_tol=0.1) and math.isclose(peak, 18.0, abs_tol=0.1), (now, peak)


def test_the_ball_is_filled_across_short_gaps_only():
    def row(frame, ball):
        return {"frame": frame, "camera": {"ok": True}, "players": [],
                "ball": [] if ball is None else [{"bbox": [0, 0, 1, 1], "score": 0.9, "x": ball, "y": 34.0}]}

    gap = tf.MAX_GAP_FRAMES
    rows = [row(0, 10.0), *[row(i, None) for i in range(1, gap)], row(gap, 20.0),
            *[row(gap + i, None) for i in range(1, gap + 1)], row(2 * gap + 1, 30.0)]
    ball = tf.ball_positions(rows)
    assert ball[gap // 2][0] == 10.0 + 10.0 * (gap // 2) / gap  # on the line between the two
    assert all(f in ball for f in range(gap + 1))
    assert not any(gap + i in ball for i in range(1, gap + 1))  # one frame too long: left out


def test_the_builder_takes_any_clips_observations(tmp_path):
    # The freeze-day clip runs through the same command: id and output follow the file's name.
    obs = tmp_path / "observations-demo42.jsonl"
    obs.write_text(OBSERVATIONS.read_text())
    tf.main([str(obs)])
    frames = json.loads((tmp_path / "tracked-demo42.json").read_text())["frames"]
    assert frames and {f["clip"] for f in frames} == {"demo42"}
    tf.main([str(OBSERVATIONS), "--clip", "seed900001", "--out", str(tmp_path / "m1.json")])
    assert (tmp_path / "m1.json").read_text() == FIXTURE.read_text()


# --- the builder's own rules, each on its own (not only through the fixture) ---------------------------


def fake_tracks(monkeypatch, tracks, balls):
    """track.py's steps replaced by fixed results, so a rule of tracked_frames is tested alone."""
    monkeypatch.setattr(tr, "track_players", lambda rows: tracks)
    monkeypatch.setattr(tr, "assign_teams", lambda ts: {"reason": "fixed by the test"})
    monkeypatch.setattr(tr, "ball_path", lambda rows: [tr.BallPoint(f, 50.0, 30.0, 0.9) for f in balls])


def rows(frames, ok=lambda f: True):
    return [{"frame": f, "camera": {"ok": ok(f)}, "players": [], "ball": []} for f in frames]


def test_a_track_shorter_than_one_minimap_frame_is_left_out(monkeypatch):
    n = tf.MIN_TRACK_FRAMES
    short = tr.Track(1, list(range(n - 1)), [(10.0, 10.0)] * (n - 1), team="home")
    long = tr.Track(2, list(range(n)), [(20.0, 20.0)] * n, team="away")
    fake_tracks(monkeypatch, [short, long], range(n))
    ids = {p["id"] for f in tf.build(rows(range(n)), "c")["frames"] for p in f["players"]}
    assert ids == {"a-t2"}


def test_a_frame_whose_camera_fit_failed_is_left_out(monkeypatch):
    t = tr.Track(3, list(range(10)), [(30.0, 30.0)] * 10, team="home")
    fake_tracks(monkeypatch, [t], range(10))
    frames = tf.build(rows(range(10), ok=lambda f: f != 4), "c")["frames"]
    assert [f["frame"] for f in frames] == [0, 1, 2, 3, 5, 6, 7, 8, 9]


def test_a_tracked_player_is_his_side_and_his_track_never_a_shirt_number(monkeypatch):
    home = tr.Track(7, list(range(10)), [(30.0, 30.0)] * 10, team="home")
    away = tr.Track(12, list(range(10)), [(60.0, 30.0)] * 10, team="away")
    nobody = tr.Track(13, list(range(10)), [(60.0, 40.0)] * 10, team=None)  # no team: not shown
    fake_tracks(monkeypatch, [home, away, nobody], range(10))
    ids = {p["id"] for f in tf.build(rows(range(10)), "c")["frames"] for p in f["players"]}
    assert ids == {"h-t7", "a-t12"}
