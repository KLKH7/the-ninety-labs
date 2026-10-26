"""The ball-source scorer (ninety/eval/ball_sources.py) on hand-built clips: recall and precision by
zone and radius, and coverage, from the ball the tracker takes."""

from __future__ import annotations

import json
from pathlib import Path

from ninety.eval import ball_sources as bs


def truth_row(frame, x, y, z=0.11, bbox=(100, 100, 104, 104)):
    return {"frame": frame, "t": frame / 25, "image": f"images/{frame:05d}.jpg", "players": [],
            "ball": {"x": x, "y": y, "z": z, "bbox": list(bbox), "visibility": 1.0}}


def obs_row(frame, balls, ok=True):
    return {"frame": frame, "t": frame / 25, "camera": {"ok": ok}, "players": [],
            "ball": [{"bbox": [100, 100, 104, 104], "score": 0.9, **b} for b in balls]}


def write(path: Path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))


def test_zones_cut_the_width_in_thirds():
    assert [bs.zone(y) for y in (0.0, 22.6, 22.7, 45.3, 45.4, 68.0)] == [
        "near", "near", "centre", "centre", "far", "far"]


def test_recall_and_precision_by_zone_and_radius(tmp_path):
    clips, obs = tmp_path / "clips", tmp_path / "obs"
    truth = [truth_row(0, 50.0, 10.0), truth_row(1, 50.0, 30.0), truth_row(2, 50.0, 60.0, z=3.0),
             truth_row(3, 120.0, 30.0)]  # frame 3: the ball is off the pitch
    write(clips / "seed5" / "frames.jsonl", truth)
    write(obs / "v" / "seed5.jsonl", [
        obs_row(0, [{"x": 50.5, "y": 10.0}]),  # strict hit, near
        obs_row(1, [{"x": 51.5, "y": 30.0}]),  # lenient only, centre
        obs_row(2, []),                         # missed, far, in the air
        obs_row(3, [{"x": 51.0, "y": 30.0}]),  # reported while the ball is off the pitch: wrong
    ])
    r = bs.score(clips, obs, [5], ["v"])["variants"]["v"]
    assert r["all"]["recall_strict"]["k"] == 1 and r["all"]["recall_strict"]["n"] == 3
    assert r["all"]["recall_lenient"]["k"] == 2
    assert r["all"]["precision_strict"] == {"k": 1, "n": 3, "rate": 0.3333, "wilson95": [0.06, 0.79]}
    assert r["near"]["recall_strict"]["rate"] == 1.0 and r["centre"]["recall_strict"]["rate"] == 0.0
    assert r["centre"]["recall_lenient"]["rate"] == 1.0 and r["far"]["recall_lenient"]["rate"] == 0.0
    assert r["in the air"]["recall_lenient"]["n"] == 1 and r["on the ground"]["recall_lenient"]["k"] == 2
    # Coverage: a ball placed at all on frames with the true ball on the pitch (2 of 3).
    assert r["all"]["coverage"]["k"] == 2 and r["all"]["coverage"]["n"] == 3
    assert r["far"]["coverage"]["k"] == 0


def test_the_band_is_derived_per_lens_folder_and_never_on_a_test_seed(tmp_path):
    import pytest

    from ninety.eval import band_derive

    clip = tmp_path / "seed108"
    for v in ("tac-l", "tac-r"):
        (clip / "views" / v).mkdir(parents=True)
    assert band_derive._view("view-tac-l-ours-freeze", clip) == "tac-l"
    assert band_derive._view("view-tac-r-ours-tactical", clip) == "tac-r"
    with pytest.raises(SystemExit, match="validation"):
        band_derive.derive(tmp_path, tmp_path, [900001])
