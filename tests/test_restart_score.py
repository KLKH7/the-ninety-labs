"""Grading detected kick-offs: a true kick-off is timed at its kick, not at the engine's event.

Clips are built here (frames.jsonl, events.jsonl), so each premise holds by construction
(lesson 47); constants come from the module under test (lesson 36).
"""

from __future__ import annotations

import json

from ninety.eval import restart_score as rsc

FPS = 25


VALIDATION_SEED = 920101  # the set-piece set's validation split: graded freely


def clip(tmp_path, kick_at=60, event_at=30, frames=120, team="home", seed=VALIDATION_SEED, name="clip"):
    """The ball on the mark until `kick_at`, then rolling; the engine's kickoff event at `event_at`."""
    d = tmp_path / name
    d.mkdir()
    if seed is not None:
        (d / "meta.json").write_text(json.dumps({"seed": seed}))
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


def two_kickoffs(tmp_path):
    """Kick-offs kicked at frames 60 (home) and 160 (away); the engine's events 30 frames before."""
    d = tmp_path / "clip2"
    d.mkdir()
    (d / "meta.json").write_text(json.dumps({"seed": VALIDATION_SEED}))
    rows = []
    for f in range(240):
        x = 52.5 if f <= 60 or 100 <= f <= 160 else 40.0 + 0.01 * f
        rows.append({"frame": f, "t": round(f / FPS, 2), "ball": {"x": x, "y": 34.0, "z": 0.0}})
    (d / "frames.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    evs = [{"id": f"e{i}", "t": (k - 30) / FPS, "frame": k - 30, "type": "kickoff", "team": team, "x": 52.5,
            "y": 34.0, "source": "truth"} for i, (k, team) in enumerate(((60, "home"), (160, "away")))]
    (d / "events.jsonl").write_text("".join(json.dumps(e) + "\n" for e in evs))
    return d


def test_two_kick_offs_are_matched_one_to_one_nearest_first_and_extras_are_false(tmp_path):
    c = two_kickoffs(tmp_path)
    assert [t["frame"] for t in rsc.truth_kickoffs(c)] == [60, 160]
    # Two detections near the first kick: the nearer takes it, the other is false. A pass is not graded.
    r = rsc.score([(c, found(tmp_path, {"t": 2.4 + 0.5, "team": "home"}, {"t": 2.4 + 0.1, "team": "home"},
                             {"t": 6.4, "team": "away"}, {"t": 6.4, "team": "away", "type": "pass"}))])
    assert r["recall"] == {"k": 2, "n": 2, "rate": 1.0, "wilson95": rsc.wilson(2, 2)}
    assert r["precision"]["k"] == 2 and r["precision"]["n"] == 3
    assert r["clips"][0]["false"] == ["r0"]
    assert r["timing_error_s"] == [0.0, 0.1]  # detected minus true, sorted


def test_the_window_includes_its_edge_and_not_beyond(tmp_path):
    c = clip(tmp_path)
    def hit(t):
        return rsc.score([(c, found(tmp_path, {"t": t, "team": "home"}))])["recall"]["k"]
    assert hit(2.4 + rsc.WINDOW_S) == 1
    assert hit(2.4 + rsc.WINDOW_S + 0.04) == 0


def test_a_late_detection_has_a_positive_timing_error(tmp_path):
    r = rsc.score([(clip(tmp_path), found(tmp_path, {"t": 2.4 + 0.3, "team": "home"}))])
    assert r["timing_error_s"] == [0.3]


def test_the_kick_is_found_from_where_the_ball_lay_not_from_the_mark(tmp_path):
    c = clip(tmp_path)
    rows = [json.loads(x) for x in (c / "frames.jsonl").read_text().splitlines()]
    for r in rows:  # the whole scene 2 m along the halfway line: the ball set a little off the mark
        r["ball"]["y"] += 2.0
    (c / "frames.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    assert [t["frame"] for t in rsc.truth_kickoffs(c)] == [60]


def test_a_move_of_exactly_moved_m_is_not_yet_the_kick(tmp_path):
    c = clip(tmp_path)
    rows = [json.loads(x) for x in (c / "frames.jsonl").read_text().splitlines()]
    for r in rows:  # on y = 0, so the nudge below is exactly MOVED_M in floating point
        r["ball"]["y"] = 0.0
    for r in rows[40:61]:  # nudged by the threshold itself: not moved
        r["ball"]["y"] = rsc.MOVED_M
    (c / "frames.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    assert [t["frame"] for t in rsc.truth_kickoffs(c)] == [60]


def test_an_event_on_a_frame_the_clip_does_not_show_is_not_counted(tmp_path):
    assert rsc.truth_kickoffs(clip(tmp_path, event_at=500)) == []


def test_a_detection_exactly_a_window_away_matches_despite_floating_point(tmp_path):
    # Kicked at 1.16 s: 2.16 - 1.16 is 1.0000000000000002 in floating point, still the window's edge.
    c = clip(tmp_path, kick_at=29, event_at=10)
    assert rsc.score([(c, found(tmp_path, {"t": 2.16, "team": "home"}))])["recall"]["k"] == 1


def test_test_seeds_and_unknown_seeds_are_refused_unless_final(tmp_path):
    import pytest

    from ninety.eval import set_piece_set
    from ninety.render.splits import TEST_SEEDS
    for seed in (TEST_SEEDS[0], set_piece_set.TEST[0], None):
        c = clip(tmp_path, seed=seed, name=f"c{seed}x")
        f = found(tmp_path, {"t": 2.4, "team": "home"})
        with pytest.raises(SystemExit, match="refused"):
            rsc.score([(c, f)])
        assert rsc.score([(c, f)], final_test=True)["recall"]["k"] == 1
    # A validation seed from the folder's name, when meta.json gives none.
    assert rsc.score([(clip(tmp_path, seed=None, name=f"seed{set_piece_set.VALIDATION[0]}"),
                       found(tmp_path, {"t": 2.4, "team": "home"}))])["recall"]["k"] == 1


def test_the_command_line_refuses_a_test_clip(tmp_path):
    import pytest

    from ninety.render.splits import TEST_SEEDS
    c = clip(tmp_path, seed=TEST_SEEDS[0])
    with pytest.raises(SystemExit, match="refused"):
        rsc.main([str(c), str(found(tmp_path, {"t": 2.4, "team": "home"}))])
