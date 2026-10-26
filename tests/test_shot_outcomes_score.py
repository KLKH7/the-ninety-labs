"""The shot-outcome scorer (ninety/eval/shot_outcomes.py) on planted truth and detections."""

from __future__ import annotations

import pytest

from ninety.eval import shot_outcomes as so


def frames(first=0, last=249):
    return [{"frame": k} for k in range(first, last + 1)]


def ev(kind, t, team="home", outcome=None, conf=0.9):
    return {"type": kind, "t": t, "team": team, "outcome": outcome, "confidence": conf}


def test_a_goal_found_in_the_window_is_a_hit_a_late_one_a_miss_and_a_false_one_counted():
    truth = [ev("goal", 4.0), ev("goal", 8.0, "away")]
    det = [ev("goal", 4.0 + so.WINDOW_S), ev("goal", 8.0 + so.WINDOW_S + 0.04, "away"), ev("goal", 6.0)]
    r = so.score_clip(truth, frames(), det, None)["goal"]
    assert (r["tp"], r["fp"], r["fn"]) == (1, 2, 1)


def test_a_goal_the_clip_does_not_show_is_not_owed():
    # Struck before the end, over the line after it (seed 900014): nothing to find.
    r = so.score_clip([ev("goal", 11.0)], frames(0, 249), [], None)["goal"]
    assert (r["tp"], r["fn"]) == (0, 0)


def test_a_save_is_a_shot_on_target_and_the_gate_drops_a_weak_detection():
    truth = [ev("shot", 3.0, outcome="on_target"), ev("shot", 6.0, outcome="off_target")]
    det = [ev("shot", 3.1, outcome="on_target", conf=0.4), ev("shot", 6.0, outcome="on_target")]
    gated = so.score_clip(truth, frames(), det, so.CONFIDENCE_GATE)["save"]
    assert (gated["tp"], gated["fp"], gated["fn"]) == (0, 1, 1)
    every = so.score_clip(truth, frames(), det, None)["save"]
    assert (every["tp"], every["fp"], every["fn"]) == (1, 1, 0)


def test_precision_is_never_measured_on_a_test_seed(tmp_path):
    with pytest.raises(SystemExit):
        so.main(["precision", "--clips", str(tmp_path), "--observations", str(tmp_path), "--seeds", "108",
                 "900004", "--out", str(tmp_path / "x.json")])
