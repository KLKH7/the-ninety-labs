"""The camera trust bound's comparison (ninety/eval/detector_derive.py, `bound`): each candidate's worst
trusted frame, its good frames kept, the frames it could not measure, and the plan's adoption rule."""

from __future__ import annotations

from ninety.eval import detector_derive as dd
from ninety.vision import observe
from tests.test_vision_observe import clip


def errors_for(offsets):
    """A stand-in truth: each frame's ground error is its camera's offset (0.1 m when right), and
    frame 10 cannot be measured."""
    def camera_errors(rows, frames):
        return [{"frame": r["frame"], "ok": r["camera"]["ok"],
                 "error_m": None if r["frame"] == 10 else (offsets.get(r["frame"]) or 0.1)} for r in rows]
    return camera_errors


def test_each_candidate_reports_its_worst_its_good_frames_and_what_it_could_not_measure(monkeypatch):
    offsets = {5: dd.MAX_TRUSTED_M + 1.5}
    monkeypatch.setattr(dd, "camera_errors", errors_for(offsets))
    rows = clip(offsets)
    out = dd.bound([(1, rows, {})])
    table = out["candidates"]
    assert table["height"]["worst_m"] == offsets[5] and not table["height"]["qualifies"]
    assert table["C2"]["worst_m"] == 0.1 <= dd.MAX_TRUSTED_M
    assert table["height"]["unmeasured"] == 1 and table["height"]["worst_by_seed"] == {1: offsets[5]}
    # Frame 6 is judged against frame 5 (the earlier on a tie) and lost with it: 8 of the 9 measured
    # good frames kept.
    assert table["C2"]["good_kept"] == 8 and table["height"]["good_kept"] == 9


def test_a_candidate_that_keeps_too_few_good_frames_does_not_qualify(monkeypatch):
    offsets = {5: dd.MAX_TRUSTED_M + 1.5}
    monkeypatch.setattr(dd, "camera_errors", errors_for(offsets))
    monkeypatch.setattr(dd, "KEEP_GOOD", 0.95)
    out = dd.bound([(1, clip(offsets), {})])
    assert out["candidates"]["C2"]["good_kept_share_of_height"] < 0.95
    assert not out["candidates"]["C2"]["qualifies"] and out["adopted"] is None


def test_with_a_long_clip_the_one_good_frame_lost_leaves_the_share_above_the_bar(monkeypatch):
    offsets = {5: dd.MAX_TRUSTED_M + 1.5}
    monkeypatch.setattr(dd, "camera_errors", errors_for(offsets))
    long_clip = clip(offsets, frames=60)
    out = dd.bound([(1, long_clip, {})])
    assert out["candidates"]["C2"]["qualifies"] and out["adopted"] == "C2"
    assert observe.NEIGHBOUR_M == 2.0 and observe.NEIGHBOUR_FRAMES == 5  # the plan's values
