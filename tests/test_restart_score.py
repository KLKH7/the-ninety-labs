"""Grading detected kick-offs: a true kick-off is timed at its kick, not at the engine's event.

Clips are built here (frames.jsonl, events.jsonl), so each premise holds by construction
(lesson 47); constants come from the module under test (lesson 36).
"""

from __future__ import annotations

import json

from ninety.eval import restart_score as rsc

FPS = 25


def clip(tmp_path, kick_at=60, event_at=30, frames=120, team="home"):
    """The ball on the mark until `kick_at`, then rolling; the engine's kickoff event at `event_at`."""
    d = tmp_path / "clip"
    d.mkdir()
    rows = []
    for f in range(frames):
        x = 52.5 if f <= kick_at else 52.5 - 0.4 * (f - kick_at)
        rows.append({"frame": f, "t": round(f / FPS, 2), "ball": {"x": x, "y": 34.0, "z": 0.0}})
    (d / "frames.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    ev = {"id": "e00001", "t": event_at / FPS, "frame": event_at, "type": "kickoff", "team": team,
          "x": 52.5, "y": 34.0, "source": "truth"}
    (d / "events.jsonl").write_text(json.dumps(ev) + "\n")
    return d


def found(tmp_path, *events):
    p = tmp_path / "restarts.jsonl"
    p.write_text("".join(json.dumps({"id": f"r{i}", "type": "kickoff", "source": "vision"} | e) + "\n"
                         for i, e in enumerate(events)))
    return p


def test_a_true_kick_off_is_timed_at_its_kick(tmp_path):
    assert rsc.truth_kickoffs(clip(tmp_path)) == [{"id": "e00001", "team": "home", "frame": 60, "t": 2.4}]


def test_a_kick_the_clip_does_not_show_is_not_counted(tmp_path):
    assert rsc.truth_kickoffs(clip(tmp_path, kick_at=200)) == []


def test_a_detection_matches_within_the_window_of_the_kick_with_the_right_side(tmp_path):
    c = clip(tmp_path)
    near = 2.4 + rsc.WINDOW_S - 0.04
    r = rsc.score([(c, found(tmp_path, {"t": near, "team": "home"}))])
    assert r["recall"]["k"] == 1 and r["precision"]["k"] == 1
    # At the engine's event instead (1.2 s before the kick), it is outside the window.
    r = rsc.score([(c, found(tmp_path, {"t": 30 / FPS, "team": "home"}))])
    assert r["recall"]["k"] == 0 and r["clips"][0]["false"] == ["r0"]


def test_the_wrong_side_counts_only_where_the_side_is_not_asked(tmp_path):
    r = rsc.score([(clip(tmp_path), found(tmp_path, {"t": 2.4, "team": "away"}))])
    assert r["recall"]["k"] == 0 and r["recall_any_side"]["k"] == 1
