"""The parallel precompute of the live path (ninety/vision/precompute.py): how a match is split,
how many workers it gets, and that one piece gives exactly what live_job gives on the same clip,
opening no answer-key file."""

from __future__ import annotations

import json

import pytest

from ninety.vision import live_job, precompute
from ninety.vision.detections import read_detections
from tests.test_vision_live_job import clean_clip, never_loaded, views_clip
from tests.test_vision_live_path import TRUTH_FILES, run_audited, truth_reads


def covers(split, n):
    from itertools import pairwise

    return split[0][0] == 0 and split[-1][1] == n and all(b == c for (_, b), (c, _) in pairwise(split))


def test_every_shot_starts_a_piece_and_short_shots_stay_whole():
    split = precompute.pieces(1500, [0, 155, 658, 784], workers=4)
    assert covers(split, 1500)
    assert {155, 658, 784} <= {a for a, _ in split}  # never a camera fit running across a cut
    assert (0, 155) in split and (658, 784) in split  # shorter than a share: whole


def test_a_long_shot_is_cut_into_equal_parts_never_shorter_than_the_minimum():
    split = precompute.pieces(1500, [0, 155, 658, 784], workers=5)  # a share is 300 frames
    assert split == [(0, 155), (155, 407), (407, 658), (658, 784), (784, 1142), (1142, 1500)]
    assert all(b - a >= precompute.MIN_PIECE for a, b in split if b - a not in (155, 126))
    one_shot = precompute.pieces(400, [0], workers=8)  # 8 shares of 50 frames would be too short
    assert one_shot == [(0, 400)]


def test_workers_are_limited_by_pieces_cores_and_free_memory():
    gb = precompute.GB
    assert precompute.worker_count(6, cores=12, free_ram=32 * gb) == 6
    assert precompute.worker_count(20, cores=12, free_ram=32 * gb) == 10  # cores less two
    assert precompute.worker_count(20, cores=12, free_ram=10 * gb) == 5  # 2 GB a worker
    assert precompute.worker_count(20, cores=2, free_ram=None) == 1


def in_process(found):
    """`place` for the tests: every piece in this process, with the stand-in detector."""
    def place(chunks):
        out, i = [], 0
        for rows in chunks:
            out.append(precompute.place_piece(rows, lambda r, i=i: found[i:i + len(r)]))
            i += len(rows)
        return out
    return place


def test_one_piece_gives_what_live_job_gives_and_opens_no_truth(tmp_path):
    clip, dets = clean_clip(tmp_path)
    single, pre = tmp_path / "single", tmp_path / "pre"
    run = run_audited(f"""
        from pathlib import Path
        from ninety.vision import live_job, pitch, precompute
        from ninety.vision.detections import read_detections
        from tests.test_vision_precompute import in_process
        pitch.find_gantry = lambda anchors, w, h: (58.0, -37.0, 16.0)  # the search is tested elsewhere
        found = read_detections({str(dets)!r})
        live_job.run(Path({str(clip)!r}), Path({str(single)!r}), lambda: (lambda rows: found))
        report = precompute.run(Path({str(clip)!r}), Path({str(pre)!r}), in_process(found), 4)
        OUT = {{"report": report}}
    """)
    report = run["out"]["report"]
    assert report["frames"] == 2 and report["camera_ok"] == 2 and len(report["pieces"]) == 1
    for name in ("detections.jsonl", "observations.jsonl", "detected.jsonl", "tracked.json"):
        assert (pre / name).read_text() == (single / name).read_text(), name
    assert truth_reads(run) == []


def test_pieces_are_joined_in_frame_order(tmp_path, monkeypatch):
    from ninety.vision import pitch

    clip, dets = clean_clip(tmp_path)
    monkeypatch.setattr(pitch, "find_gantry", lambda anchors, w, h: (58.0, -37.0, 16.0))
    monkeypatch.setattr(pitch, "shot_starts", lambda thumbs: [0, 1])  # a cut between the two frames
    found = read_detections(dets)
    report = precompute.run(clip, tmp_path / "out", in_process(found), 2)
    assert [(p["first"], p["last"]) for p in report["pieces"]] == [(0, 0), (1, 1)]
    obs = [json.loads(line) for line in (tmp_path / "out" / "observations.jsonl").read_text().splitlines()]
    assert [o["frame"] for o in obs] == [0, 1]


@pytest.mark.parametrize("name", TRUTH_FILES)
def test_a_folder_holding_an_answer_key_file_is_refused_before_anything_runs(tmp_path, name):
    clip, _ = clean_clip(tmp_path)
    (clip / name).write_text("{}\n")
    with pytest.raises(SystemExit, match=name):
        precompute.run(clip, tmp_path / "out", lambda chunks: never_loaded(), 2)
    assert not (tmp_path / "out").exists()


def test_a_views_clip_is_left_to_live_job(tmp_path):
    clip, _ = views_clip(tmp_path)
    with pytest.raises(SystemExit, match="single-camera"):
        precompute.run(clip, tmp_path / "out", lambda chunks: never_loaded(), 2)


def test_the_command_checks_the_checkpoint_before_any_worker_starts(tmp_path):
    from tests.test_vision_live_job import checkpoint

    clip, _ = clean_clip(tmp_path)
    weights = checkpoint(tmp_path, sha="0" * 64)
    with pytest.raises(SystemExit, match="sha256"):
        precompute.main([str(clip), "--checkpoint", "ours-v4", "--weights", str(weights),
                         "--out", str(tmp_path / "out")])
    assert live_job  # the same checks as the job's (verify_checkpoint, check_views)
