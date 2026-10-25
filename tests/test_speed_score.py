"""The speed error scorer (ninety/eval/speed_score.py, docs/eval/speed-plan.md).

Scenes are built here as observations and truth frames, so each premise holds by construction
(lesson 47); the pass scene is the event detector's own test scene. Legal cases must score as no
error; each planted defect must show as the error it is.
"""

from __future__ import annotations

import hashlib
import math

import pytest

from ninety.eval import event_score
from ninety.eval import speed_score as ss
from ninety.eval.vision_score import IN_AIR_Z
from ninety.vision import events as ev
from ninety.vision import track as tr
from tests.test_vision_events import BLUE, pass_scene, row

FPS = tr.FPS


def truth_frame(frame, x, y, z=0.0):
    """A truth frame as a rendered clip writes it: the ball's place, and no velocity."""
    return {"frame": frame, "t": round(frame / FPS, 2), "ball": {"x": x, "y": y, "z": z}}


def rolling(speed=20.0, frames=30, scale=1.0):
    """A ball rolling along y = 34 at `speed` m/s; vision sees it at `scale` times the distance."""
    obs, truth = [], {}
    for f in range(frames):
        x = 30.0 + speed * f / FPS
        obs.append(row(f, [], (30.0 + scale * (x - 30.0), 34.0)))
        truth[f] = truth_frame(f, x, 34.0)
    return obs, truth


def pass_truth(frames=60, kick=20, speed=12.0):
    """The truth beside tests.test_vision_events.pass_scene: the same ball, and the pass."""
    out, bx = [], 50.3
    for f in range(frames):
        if f > kick:
            bx = min(bx + speed / FPS, 61.7)
        out.append(truth_frame(f, bx, 34.0))
    event = {"id": "e00001", "type": "pass", "team": "home", "t": round(kick / FPS, 2), "x": 50.3, "y": 34.0,
             "ball_speed_kmh": round(speed * 3.6, 1), "source": "truth"}
    return out, [event]


# Legal cases: no error.

def test_a_ball_seen_where_it_is_has_no_frame_speed_error():
    obs, truth = rolling()
    rows = ss.frame_speeds(obs, truth)
    assert [r["frame"] for r in rows] == list(range(1, 29))  # the true velocity needs both neighbours
    assert all(r["true_kmh"] == pytest.approx(72.0) for r in rows)
    assert all(abs(r["error_kmh"]) < 1e-6 and r["height"] == "on the ground" for r in rows)
    s = ss.summarise(rows)
    assert s["median_abs_kmh"] == 0.0 and s["mean_signed_kmh"] == 0.0 and s["median_abs_relative"] == 0.0


def test_a_detected_pass_matched_to_its_true_pass_has_no_event_speed_error():
    detected, _ = ev.detect(pass_scene(BLUE))
    frames, truth = pass_truth()
    rows = ss.event_speeds(truth, detected, frames)
    assert [(r["type"], r["error_kmh"], r["lofted"]) for r in rows] == [("pass", 0.0, False)]


def test_a_lofted_ball_seen_flat_is_exact_against_the_flat_truth_and_low_by_cos_theta_against_3d():
    theta, speed = math.radians(30.0), 20.0
    obs, truth = [], {}
    for f in range(20):
        x = 30.0 + speed * math.cos(theta) * f / FPS
        obs.append(row(f, [], (x, 34.0)))
        truth[f] = truth_frame(f, x, 34.0, z=1.0 + speed * math.sin(theta) * f / FPS)
    rows = ss.frame_speeds(obs, truth)
    assert all(r["height"] == "in the air" for r in rows)
    assert all(abs(r["error_flat_kmh"]) < 1e-6 for r in rows)
    want = (math.cos(theta) - 1.0) * speed * ss.KMH  # 13% low at 30 degrees (speed-plan.md)
    assert all(abs(r["error_kmh"] - want) < 1e-6 for r in rows)


def test_a_ball_exactly_at_the_cut_off_is_on_the_ground_and_a_pass_through_it_is_not_lofted():
    obs, truth = rolling(frames=10)
    truth = {f: truth_frame(f, t["ball"]["x"], 34.0, z=IN_AIR_Z) for f, t in truth.items()}
    assert {r["height"] for r in ss.frame_speeds(obs, truth)} == {"on the ground"}
    assert not ss.lofted(0.0, truth)
    truth[ss.LOOK_FRAMES] = truth_frame(ss.LOOK_FRAMES, 0.0, 34.0, z=IN_AIR_Z + 0.01)
    assert ss.lofted(0.0, truth)
    assert not ss.lofted((ss.LOOK_FRAMES + 1) / FPS, truth)  # the window ends at LOOK_FRAMES


def test_a_frame_whose_true_velocity_cannot_be_had_is_left_out():
    obs, truth = rolling(frames=10)
    del truth[5]  # a cut: frames 4 and 6 lose a neighbour
    assert [r["frame"] for r in ss.frame_speeds(obs, truth)] == [1, 2, 3, 7, 8]


def test_the_true_speed_comes_from_the_true_places_and_a_missing_place_is_an_error_not_zero():
    """Rendered truth frames hold no velocity: a scorer that read a missing vx as 0 graded vision's
    own speed as its error (docs/LESSONS.md). The true speed here is 20 m/s from the places alone."""
    obs, truth = rolling(frames=5)
    assert ss.true_ball(truth, 2)[0] == pytest.approx(72.0)
    del truth[3]["ball"]["x"]
    with pytest.raises(KeyError):
        ss.frame_speeds(obs, truth)


def test_relative_error_counts_a_true_speed_exactly_at_its_floor_and_not_below():
    rows = [{"error_kmh": 9.0, "true_kmh": ss.REL_MIN_KMH},
            {"error_kmh": 1.0, "true_kmh": ss.REL_MIN_KMH - 0.01}]
    s = ss.summarise(rows)
    assert s["n"] == 2 and s["n_relative"] == 1 and s["median_abs_relative"] == 0.5
    assert s["mean_signed_kmh"] == 5.0 and s["p90_abs_kmh"] == 1.0  # pitch_score's order statistic


def test_no_rows_give_no_numbers_never_a_made_up_zero():
    assert ss.summarise([]) == {"n": 0, "enough": False, "median_abs_kmh": None, "p90_abs_kmh": None,
                                "mean_signed_kmh": None, "n_relative": 0, "median_abs_relative": None}


def test_a_summary_is_claimed_from_min_pairs_and_not_one_fewer():
    row = {"error_kmh": 1.0, "true_kmh": 40.0}
    assert ss.summarise([row] * ss.MIN_PAIRS)["enough"]
    assert not ss.summarise([row] * (ss.MIN_PAIRS - 1))["enough"]


def clip_files(root, crlf=False):
    """A two-image clip folder and its digest as render/checks.py writes it (\\n line endings)."""
    (root / "images").mkdir(parents=True)
    for i, b in enumerate((b"one", b"two")):
        (root / "images" / f"{i:05d}.jpg").write_bytes(b)
    frames, events = b'{"frame": 0}\n{"frame": 1}\n', b'{"id": "e1"}\n'
    for name, text in (("frames.jsonl", frames), ("events.jsonl", events)):
        (root / name).write_bytes(text.replace(b"\n", b"\r\n") if crlf else text)
    return {"frames_jsonl": hashlib.sha256(frames).hexdigest(),
            "events_jsonl": hashlib.sha256(events).hexdigest(),
            "images": hashlib.sha256(b"onetwo").hexdigest(), "image_count": 2}


def test_a_clip_matching_its_digests_is_scored_even_with_windows_line_endings(tmp_path):
    assert ss.mismatched(tmp_path / "a", clip_files(tmp_path / "a")) == []
    assert ss.mismatched(tmp_path / "b", clip_files(tmp_path / "b", crlf=True)) == []


# Planted defects: each must show.

def test_a_clip_with_one_image_byte_changed_or_an_image_missing_is_not_scored(tmp_path):
    digest = clip_files(tmp_path)
    (tmp_path / "images" / "00001.jpg").write_bytes(b"twO")
    assert ss.mismatched(tmp_path, digest) == ["images"]
    (tmp_path / "images" / "00001.jpg").unlink()
    assert ss.mismatched(tmp_path, digest) == ["images", "image_count"]


def test_a_clip_whose_truth_differs_is_not_scored(tmp_path):
    digest = clip_files(tmp_path)
    (tmp_path / "events.jsonl").write_bytes(b'{"id": "e2"}\n')
    assert ss.mismatched(tmp_path, digest) == ["events_jsonl"]


def test_a_ball_seen_at_twice_its_distance_reads_twice_as_fast():
    obs, truth = rolling(scale=2.0)
    s = ss.summarise(ss.frame_speeds(obs, truth))
    assert s["median_abs_relative"] == pytest.approx(1.0) and s["mean_signed_kmh"] == pytest.approx(72.0)


def test_a_wrong_vision_speed_on_a_matched_pass_is_its_error():
    detected, _ = ev.detect(pass_scene(BLUE))
    for e in detected:
        e["ball_speed_kmh"] = round(e["ball_speed_kmh"] / ss.KMH, 1)  # written in m/s
    frames, truth = pass_truth()
    [r] = ss.event_speeds(truth, detected, frames)
    assert r["error_kmh"] == pytest.approx(12.0 - 43.2) and r["relative"] == pytest.approx(-0.722, abs=1e-3)


def test_a_detected_pass_more_than_the_window_away_is_not_paired_and_another_type_never_is():
    detected, _ = ev.detect(pass_scene(BLUE))
    frames, truth = pass_truth()
    late = [dict(truth[0], t=truth[0]["t"] + event_score.WINDOW_S + ev.SPEED_FRAMES / FPS + 0.1)]
    assert ss.event_speeds(late, detected, frames) == []
    other = [dict(truth[0], type="out_of_play")]
    assert ss.event_speeds(other, detected, frames) == []


def test_the_scorer_is_not_on_the_live_path():
    import ast
    from pathlib import Path

    for f in Path(ev.__file__).parent.glob("*.py"):
        names = {n.module for n in ast.walk(ast.parse(f.read_text(encoding="utf-8")))
                 if isinstance(n, ast.ImportFrom) and n.module}
        assert "ninety.eval.speed_score" not in names, f


def test_the_command_scores_a_clip_that_matches_its_digests_and_lists_one_that_does_not(tmp_path):
    """End to end on a synthetic clip set: the pass scene as clip 1, the same with one image byte
    changed as clip 2. Only clip 1 is scored; the report is strict JSON and its Markdown."""
    import json

    from ninety.render.checks import digest

    frames, truth = pass_truth()
    entries = []
    for seed in (1, 2):
        root = tmp_path / "clips" / f"seed{seed}"
        (root / "images").mkdir(parents=True)
        for f in frames:
            (root / "images" / f"{f['frame']:05d}.jpg").write_bytes(b"jpg%d" % f["frame"])
        # \n as the render writes them: a digest is of those bytes, and write_text on Windows writes \r\n.
        lines = "".join(json.dumps(f | {"players": []}) + "\n" for f in frames)
        (root / "frames.jsonl").write_bytes(lines.encode())
        (root / "events.jsonl").write_bytes("".join(json.dumps(e) + "\n" for e in truth).encode())
        entries.append({"seed": seed, "digest": digest(root)})
    (tmp_path / "clips" / "seed2" / "images" / "00003.jpg").write_bytes(b"changed")
    (tmp_path / "set.json").write_text(json.dumps({"tag": "synthetic", "seeds": [1, 2], "clips": entries}))
    (tmp_path / "obs").mkdir()
    obs = "".join(json.dumps(r) + "\n" for r in pass_scene(BLUE))
    for seed in (1, 2):
        (tmp_path / "obs" / f"observations-seed{seed}.jsonl").write_text(obs)
    out = tmp_path / "report"
    ss.main(["--set", str(tmp_path / "set.json"), "--clips", str(tmp_path / "clips"),
             "--observations", str(tmp_path / "obs"), "--detector", "synthetic", "--out", str(out)])
    body = json.loads(out.with_suffix(".json").read_text())
    assert [c["seed"] for c in body["clips"]] == [1]
    assert body["not_scored"] == [{"seed": 2, "mismatched": ["images"]}]
    assert body["pooled"]["matched"] == {"pass": 1, "shot": 0}
    assert body["pooled"]["event_speed"]["pass"] == ss.summarise([{"error_kmh": 0.0, "true_kmh": 43.2}])
    md = out.with_suffix(".md").read_text()
    assert "Clips scored: 1 of 2." in md and "too few (under 10)" in md
    clips = tmp_path / "clips"  # a private copy: its path never reaches a committed report
    assert str(clips) not in md and clips.as_posix() not in md


def detections_folder(root, seeds=(1, 2), frames=3, checkpoint="ours-freeze"):
    """seed<N>.jsonl detections as ninety/vision/detections.py writes them, and their clip set."""
    import json

    root.mkdir()
    for s in seeds:
        rows = [{"clip": f"seed{s}", "frame": f, "t": f / FPS, "detections": [],
                 "model": {"name": "rf-detr", "size": "small", "version": "1.11.2", "checkpoint": checkpoint}}
                for f in range(frames)]
        (root / f"seed{s}.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    return {"clips": [{"seed": s, "digest": {"image_count": frames}} for s in seeds]}


def test_the_scored_runs_detections_pass_the_provenance_check(tmp_path):
    clip_set = detections_folder(tmp_path / "d")
    assert ss.check_detections(tmp_path / "d", clip_set, "ours-freeze") == []


def test_detections_of_another_checkpoint_a_missing_seed_or_a_missing_frame_are_refused(tmp_path):
    import json

    clip_set = detections_folder(tmp_path / "a", checkpoint="ours-v4")
    assert ss.check_detections(tmp_path / "a", clip_set, "ours-freeze") == [
        "seed1: checkpoint ['ours-v4'], not ours-freeze", "seed2: checkpoint ['ours-v4'], not ours-freeze"]
    clip_set = detections_folder(tmp_path / "b")
    (tmp_path / "b" / "seed2.jsonl").unlink()
    (tmp_path / "b" / "seed3.jsonl").write_text((tmp_path / "b" / "seed1.jsonl").read_text())
    assert ss.check_detections(tmp_path / "b", clip_set, "ours-freeze") == [
        "seed2: missing", "seed3: not in the set"]
    clip_set = detections_folder(tmp_path / "c")
    lines = (tmp_path / "c" / "seed1.jsonl").read_text().splitlines()
    (tmp_path / "c" / "seed1.jsonl").write_text("\n".join(lines[:2]) + "\n")
    rows = [json.loads(x) for x in (tmp_path / "c" / "seed2.jsonl").read_text().splitlines()]
    rows[0]["clip"] = "seed9"
    (tmp_path / "c" / "seed2.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    assert ss.check_detections(tmp_path / "c", clip_set, "ours-freeze") == [
        "seed1: 2 lines for 3 frames, or not in order", "seed2: lines of another clip"]


def test_the_command_stops_before_scoring_on_refused_detections(tmp_path):
    import json

    clip_set = detections_folder(tmp_path / "d", checkpoint="ours-v4")
    (tmp_path / "set.json").write_text(json.dumps(clip_set | {"seeds": [1, 2]}))
    with pytest.raises(SystemExit, match="detections refused: seed1: checkpoint"):
        ss.main(["--set", str(tmp_path / "set.json"), "--clips", str(tmp_path),
                 "--observations", str(tmp_path), "--detector", "ours-freeze",
                 "--detections", str(tmp_path / "d"), "--out", str(tmp_path / "r")])
    assert not (tmp_path / "r.json").exists()
