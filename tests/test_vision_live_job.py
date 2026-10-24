"""The live detection job (ninety/vision/live_job.py): it runs every stage of the live path on a clip
folder that holds only the frame index and the images, refuses any other folder before a model
loads, and opens no answer-key file while it runs (AGENTS.md, hard rule; lesson 17).

The detector is a stand-in that returns a committed-style detections file: rfdetr is in the optional
vision group, and what is tested here is the job around it. Every stage after it is the real one.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from ninety.vision import live_job
from tests.test_vision_live_path import TRUTH_FILES, run_audited, synthetic_clip, truth_reads

OUTPUTS = ["detected.jsonl", "detections.jsonl", "observations.jsonl", "run.json", "tracked.json"]


def clean_clip(tmp_path: Path) -> tuple[Path, Path]:
    """The synthetic clip's images and a labels-free index, in a folder of their own, and the
    detections the stand-in detector returns. The source folder, with its traps, stays apart."""
    dets = synthetic_clip(tmp_path / "src" / "clip")
    clip = tmp_path / "clip"
    shutil.copytree(tmp_path / "src" / "clip" / "images", clip / "images")
    rows = [{"clip": "c", "frame": k, "t": k / 25, "image": f"images/{k:05d}.jpg"} for k in range(2)]
    (clip / "index.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    return clip, dets


def never_loaded():
    raise AssertionError("the model loaded before the input was checked")


def test_a_clean_clip_runs_the_whole_live_path_and_opens_no_truth(tmp_path):
    clip, dets = clean_clip(tmp_path)
    out = tmp_path / "out"
    run = run_audited(f"""
        from pathlib import Path
        from ninety.vision import live_job, pitch
        from ninety.vision.detections import read_detections
        pitch.find_gantry = lambda anchors, w, h: (58.0, -37.0, 16.0)  # the search is tested elsewhere
        found = read_detections({str(dets)!r})
        report = live_job.run(Path({str(clip)!r}), Path({str(out)!r}), lambda: (lambda rows: found),
                              {{"commit": "test"}})
        OUT = {{"report": report, "files": sorted(p.name for p in Path({str(out)!r}).iterdir())}}
    """)
    report = run["out"]["report"]
    assert run["out"]["files"] == OUTPUTS
    assert report["frames"] == 2 and report["camera_ok"] == 2  # it ran the whole path
    assert set(report["seconds"]) == {"load", "detect", "observe", "events", "tracked", "total"}
    assert report["commit"] == "test" and report["cpus"] >= 1
    assert any(o.endswith(".jpg") for o in run["opened"])
    assert truth_reads(run) == []


def test_with_flight_the_events_read_the_fitted_ball_and_no_truth_is_opened(tmp_path):
    # The flight fit itself is tested in tests/test_vision_flight.py; here, that the job runs it
    # between observe and events, writes what it gave, and hands exactly that to events. Its
    # heights are a stand-in that marks every ball, so the test does not hang on a 2-frame clip
    # holding no flight.
    clip, dets = clean_clip(tmp_path)
    out = tmp_path / "out"
    run = run_audited(f"""
        from pathlib import Path
        from ninety.vision import events, flight, live_job, pitch
        from ninety.vision.detections import read_detections
        pitch.find_gantry = lambda anchors, w, h: (58.0, -37.0, 16.0)
        seen = []
        def marked(rows):
            return [r | {{"fitted": True}} for r in rows]  # every row, ball seen or not
        flight.heights = marked
        real = events.detect
        events.detect = lambda rows, *a, **k: (seen.append(rows), real(rows, *a, **k))[1]
        found = read_detections({str(dets)!r})
        report = live_job.run(Path({str(clip)!r}), Path({str(out)!r}), lambda: (lambda rows: found),
                              {{"commit": "test"}}, fit_flight=True)
        OUT = {{"report": report, "files": sorted(p.name for p in Path({str(out)!r}).iterdir()),
               "seen": seen}}
    """)
    got = run["out"]
    assert got["files"] == sorted([*OUTPUTS, "observations-flight.jsonl"])
    assert got["report"]["flight"] is True and "flight" in got["report"]["seconds"]
    written = [json.loads(x) for x in (out / "observations-flight.jsonl").read_text().splitlines()]
    assert got["seen"] == [written]
    assert written and all(r["fitted"] for r in written)
    assert truth_reads(run) == []


def test_without_flight_the_events_read_observe_s_rows_unchanged(tmp_path):
    clip, dets = clean_clip(tmp_path)
    out = tmp_path / "out"
    run = run_audited(f"""
        from pathlib import Path
        from ninety.vision import events, flight, live_job, pitch
        from ninety.vision.detections import read_detections
        pitch.find_gantry = lambda anchors, w, h: (58.0, -37.0, 16.0)
        seen = []
        def never(rows):
            raise AssertionError("the flight fit ran without --flight")
        flight.heights = never
        real = events.detect
        events.detect = lambda rows, *a, **k: (seen.append(rows), real(rows, *a, **k))[1]
        found = read_detections({str(dets)!r})
        report = live_job.run(Path({str(clip)!r}), Path({str(out)!r}), lambda: (lambda rows: found))
        OUT = {{"report": report, "seen": seen}}
    """)
    written = [json.loads(x) for x in (out / "observations.jsonl").read_text().splitlines()]
    assert run["out"]["seen"] == [written] and run["out"]["report"]["flight"] is False


@pytest.mark.parametrize("name", [*TRUTH_FILES, "notes.txt"])
def test_a_clip_folder_holding_anything_else_is_refused_before_the_model_loads(tmp_path, name):
    clip, _ = clean_clip(tmp_path)
    (clip / name).write_text("{}\n")
    with pytest.raises(SystemExit, match=name):
        live_job.run(clip, tmp_path / "out", never_loaded)
    assert not (tmp_path / "out").exists()


def test_a_clip_without_its_index_is_refused(tmp_path):
    clip, _ = clean_clip(tmp_path)
    (clip / "index.jsonl").unlink()
    with pytest.raises(SystemExit, match="index.jsonl"):
        live_job.run(clip, tmp_path / "out", never_loaded)


def test_an_index_that_misses_an_image_is_refused(tmp_path):
    clip, _ = clean_clip(tmp_path)
    index = clip / "index.jsonl"
    index.write_text(index.read_text().splitlines()[0] + "\n")
    with pytest.raises(SystemExit, match="every image"):
        live_job.run(clip, tmp_path / "out", never_loaded)


def test_an_index_that_points_outside_the_images_is_refused(tmp_path):
    clip, _ = clean_clip(tmp_path)
    index = clip / "index.jsonl"
    rows = [json.loads(line) for line in index.read_text().splitlines()]
    rows[1]["image"] = "../src/clip/images/00001.jpg"
    index.write_text("".join(json.dumps(r) + "\n" for r in rows))
    with pytest.raises(SystemExit, match="every image"):
        live_job.run(clip, tmp_path / "out", never_loaded)


def checkpoint(tmp_path: Path, name: str = "ours-v4", sha: str | None = None) -> Path:
    """A stand-in weights file and its training record, as ninety/vision/train.py writes it."""
    weights = tmp_path / "ckpt" / "checkpoint_best_total.pth"
    weights.parent.mkdir()
    weights.write_bytes(b"not really weights")
    record = {"name": name, "checkpoint_sha256": sha or live_job.sha256(weights),
              "config": {"resolution": 640}}
    (weights.parent / "train-manifest.json").write_text(json.dumps(record))
    return weights


def test_weights_matching_their_record_pass(tmp_path):
    weights = checkpoint(tmp_path)
    assert live_job.verify_checkpoint(weights, "ours-v4")["config"]["resolution"] == 640


def test_weights_whose_sha256_differs_from_their_record_are_refused(tmp_path):
    weights = checkpoint(tmp_path, sha="0" * 64)
    with pytest.raises(SystemExit, match="sha256"):
        live_job.verify_checkpoint(weights, "ours-v4")


def test_a_record_of_another_checkpoint_is_refused(tmp_path):
    weights = checkpoint(tmp_path, name="ours-v4-ctrl")
    with pytest.raises(SystemExit, match="ours-v4-ctrl"):
        live_job.verify_checkpoint(weights, "ours-v4")


def test_weights_without_their_record_are_refused(tmp_path):
    weights = checkpoint(tmp_path)
    (weights.parent / "train-manifest.json").unlink()
    with pytest.raises(SystemExit, match="training record"):
        live_job.verify_checkpoint(weights, "ours-v4")


def test_a_record_passed_elsewhere_is_the_one_checked(tmp_path):
    weights = checkpoint(tmp_path)
    other = tmp_path / "round2-manifest.json"
    other.write_text(json.dumps({"name": "ours-r2", "checkpoint_sha256": "1" * 64}))
    with pytest.raises(SystemExit, match="sha256"):
        live_job.verify_checkpoint(weights, "ours-r2", other)


class FakeModel:
    """Stands in for RF-DETR: finds nothing, so the command runs end to end without rfdetr."""
    class_names = ["player", "ball"]

    def predict(self, images, **kw):
        import numpy as np

        empty = type("P", (), {"xyxy": np.zeros((0, 4)), "confidence": np.zeros(0), "class_id": np.zeros(0)})
        return [empty() for _ in images]


def test_the_command_checks_the_checkpoint_then_runs_at_its_recorded_size(tmp_path, monkeypatch):
    from ninety.vision import pitch

    clip, _ = clean_clip(tmp_path)
    weights = checkpoint(tmp_path)
    loaded = {}
    monkeypatch.setattr(live_job, "load", lambda w, **kw: loaded.update(weights=w, **kw) or FakeModel())
    monkeypatch.setattr(pitch, "find_gantry", lambda anchors, w, h: (58.0, -37.0, 16.0))
    live_job.main([str(clip), "--checkpoint", "ours-v4", "--weights", str(weights),
                   "--out", str(tmp_path / "out")])
    report = json.loads((tmp_path / "out" / "run.json").read_text())
    assert loaded == {"weights": str(weights), "resolution": 640}
    assert report["weights_sha256"] == live_job.sha256(weights) and report["frames"] == 2
    assert report["model"]["checkpoint"] == "ours-v4"


def test_the_command_refuses_mismatched_weights_before_the_model_loads(tmp_path, monkeypatch):
    clip, _ = clean_clip(tmp_path)
    weights = checkpoint(tmp_path, sha="0" * 64)
    monkeypatch.setattr(live_job, "load", lambda *a, **kw: never_loaded())
    with pytest.raises(SystemExit, match="sha256"):
        live_job.main([str(clip), "--checkpoint", "ours-v4", "--weights", str(weights),
                       "--out", str(tmp_path / "out")])


def test_the_command_refuses_the_folder_before_reading_the_weights(tmp_path):
    clip, _ = clean_clip(tmp_path)
    (clip / "frames.jsonl").write_text("{}\n")
    missing = tmp_path / "no-such-weights.pth"  # hashing or loading it would fail differently
    with pytest.raises(SystemExit, match="frames.jsonl"):
        live_job.main([str(clip), "--checkpoint", "ours-v4", "--weights", str(missing),
                       "--out", str(tmp_path / "out")])


TAC = ("tac-l", "tac-r")


def views_clip(tmp_path: Path) -> tuple[Path, Path]:
    """The clean clip as the tactical camera's two views, each its own index and images."""
    single, dets = clean_clip(tmp_path)
    clip = tmp_path / "tac"
    for name in TAC:
        shutil.copytree(single, clip / "views" / name)
    return clip, dets


def test_a_clip_of_two_views_runs_detects_each_merges_them_and_opens_no_truth(tmp_path):
    clip, dets = views_clip(tmp_path)
    out = tmp_path / "out"
    run = run_audited(f"""
        from pathlib import Path
        from ninety.vision import live_job, pitch
        from ninety.vision.detections import read_detections
        pitch.find_gantry = lambda anchors, w, h: (58.0, -37.0, 16.0)  # the search is tested elsewhere
        found = read_detections({str(dets)!r})
        calls = []
        report = live_job.run(Path({str(clip)!r}), Path({str(out)!r}),
                              lambda: (lambda rows: calls.append(rows[0]["image"]) or found), {{}})
        o = Path({str(out)!r})
        OUT = {{"report": report, "calls": [str(c) for c in calls],
                "files": sorted(str(p.relative_to(o)) for p in o.rglob("*.jsonl"))}}
    """)
    report = run["out"]["report"]
    assert [Path(c).parts[-3] for c in run["out"]["calls"]] == list(TAC)  # each view detected
    assert report["views"] == list(TAC) and report["frames"] == 2 and report["camera_ok"] == 2
    assert "fuse" in report["seconds"]
    assert run["out"]["files"] == sorted(
        ["detected.jsonl", "observations.jsonl"]
        + [f"views/{n}/{f}" for n in TAC for f in ("detections.jsonl", "observations.jsonl")])
    assert truth_reads(run) == []


@pytest.mark.parametrize("where", ["views/tac-l", "views/tac-l/images", "views", "",
                                   "views/tac-r/images/sub"])
@pytest.mark.parametrize("name", [*TRUTH_FILES, "notes.txt"])
def test_an_answer_key_file_anywhere_in_a_views_clip_is_refused_before_the_model_loads(tmp_path, where, name):
    clip, _ = views_clip(tmp_path)
    (clip / where).mkdir(parents=True, exist_ok=True)
    (clip / where / name).write_text("{}\n")
    with pytest.raises(SystemExit, match="refused"):
        live_job.run(clip, tmp_path / "out", never_loaded)
    assert not (tmp_path / "out").exists()


def test_a_planted_frame_file_in_a_single_clip_s_images_is_refused(tmp_path):
    clip, _ = clean_clip(tmp_path)
    (clip / "images" / "frames.jsonl").write_text("{}\n")
    with pytest.raises(SystemExit, match="frames.jsonl"):
        live_job.run(clip, tmp_path / "out", never_loaded)


def test_views_listing_different_frames_are_refused(tmp_path):
    clip, _ = views_clip(tmp_path)
    index = clip / "views" / "tac-r" / "index.jsonl"
    rows = [json.loads(line) for line in index.read_text().splitlines()]
    rows[1]["frame"] = 7
    index.write_text("".join(json.dumps(r) + "\n" for r in rows))
    with pytest.raises(SystemExit, match="same frames"):
        live_job.run(clip, tmp_path / "out", never_loaded)


def test_a_views_clip_with_one_view_is_refused(tmp_path):
    clip, _ = views_clip(tmp_path)
    shutil.rmtree(clip / "views" / "tac-r")
    with pytest.raises(SystemExit, match="two views"):
        live_job.run(clip, tmp_path / "out", never_loaded)
