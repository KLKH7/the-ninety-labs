"""One condensed-match clip from its segments' joined runs (ninety/vision/match_join.py): the match
clock across every jump, no frame twice, ids kept apart per segment, and no answer key read."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ninety.match.timeline import Timeline
from ninety.vision import match_join as mj
from tests.test_vision_live_path import TRUTH_FILES, run_audited, truth_reads

PARAMS = {"width": 1280, "height": 720, "fps": 25, "home_code": "LON", "away_code": "LIS"}
# Two segments: the first from 0 s, the second from 4 s with a dead-ball cut inside it.
SEGMENTS = [{"start_s": 0.0, "end_s": 0.4, "video_start_s": 0.0},
            {"start_s": 4.0, "end_s": 4.8, "video_start_s": 0.4}]
RUNS = {"seed7-t000000": [(0, 10)], "seed7-t000100": [(100, 6), (150, 4)]}


def _write(tmp_path: Path, runs=RUNS, params=PARAMS, obs_shift=0) -> tuple[Path, Path, dict]:
    clips, vision = tmp_path / "clips", tmp_path / "vision"
    for name, rs in runs.items():
        frames = [f for first, n in rs for f in range(first, first + n)]
        c = clips / name
        (c / "images").mkdir(parents=True)
        for i in range(len(frames)):
            (c / "images" / f"{i:05d}.jpg").write_bytes(b"jpg")
        index, timeline = 0, []
        for first, n in rs:
            timeline.append({"index": index, "frame": first, "frames": n})
            index += n
        (c / "clip.json").write_text(json.dumps({
            "clip_id": "seed7", "start_frame": frames[0], "frames": len(frames), "fps": 25,
            "segments": timeline, "params": params, "event_counts": {"pass": 3}}))
        j = vision / name / "joined"
        j.mkdir(parents=True)
        (j / "detected.jsonl").write_text(json.dumps(
            {"id": "v00001", "frame": frames[1], "t": frames[1] / 25, "type": "pass", "player": "h-t8",
             "receiver": "h-t3", "confidence": 0.9}) + "\n")
        (j / "observations.jsonl").write_text("".join(
            json.dumps({"frame": f + obs_shift, "t": (f + obs_shift) / 25, "camera": {"ok": True},
                        "players": [], "ball": []}) + "\n" for f in frames))
        (j / "tracked.json").write_text(json.dumps({"restarts": [], "frames": [
            {"frame": f, "t": f / 25, "players": [{"id": "h-t8", "team": "home", "x": 1.0, "y": 2.0}],
             "ball": {"x": 0.0, "y": 0.0, "z": 0.0}} for f in frames[:2]]}))
        b = vision / name / "broadcast"
        b.mkdir(parents=True)
        (b / "detections.jsonl").write_text("".join(json.dumps(
            {"clip": "seed7", "frame": f, "t": f / 25, "detections": []}) + "\n" for f in frames))
        for v in ("tac-l", "tac-r"):
            w = vision / name / "views" / "views" / v
            w.mkdir(parents=True)
            rows = [{"frame": f, "t": f / 25, "camera": {"ok": True}, "players": [], "ball": []}
                    for f in frames]
            (w / "observations.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
        (j / "association.json").write_text(json.dumps(
            {"match_m": 1.319, "tracks": {"h-t1": {"track": "a-t4", "confidence": 1.0}}}))
    manifest = {"seed": 7, "rule": "docs/eval/demo-match.md", "segments": SEGMENTS,
                "chapters": [{"type": "kickoff", "clock": "00:00", "match_s": 0.0, "video_s": 0.0}]}
    return clips, vision, manifest


def test_the_segments_play_back_to_back_on_the_match_clock(tmp_path):
    clips, vision, manifest = _write(tmp_path)
    out = tmp_path / "match"
    report = mj.build(manifest, clips, vision, out)
    clip = json.loads((out / "clip.json").read_text())
    assert clip["segments"] == [{"index": 0, "frame": 0, "frames": 10},
                                {"index": 10, "frame": 100, "frames": 6},
                                {"index": 16, "frame": 150, "frames": 4}]
    assert clip["frames"] == report["frames"] == 20 and clip["t_start"] == 0.0 and clip["t_end"] == 153 / 25
    assert clip["params"] == PARAMS and "event_counts" not in clip  # only what the viewer reads
    images = sorted((out / "images").iterdir())
    assert [p.name for p in images] == [f"{i:05d}.jpg" for i in range(20)]
    assert images[10].resolve() == (clips / "seed7-t000100" / "images" / "00000.jpg").resolve()
    tl = Timeline.of_clip(clip)  # what the viewer and e2e read: each jump lands where it should
    assert tl.to_match(10 / 25) == 100 / 25 and tl.to_match(16 / 25) == 150 / 25
    assert tl.to_video(150 / 25) == 16 / 25


def test_no_frame_twice_and_ids_kept_apart_per_segment(tmp_path):
    clips, vision, manifest = _write(tmp_path)
    out = tmp_path / "match"
    mj.build(manifest, clips, vision, out)
    obs = [json.loads(x)["frame"] for x in (out / "observations.jsonl").read_text().splitlines()]
    assert obs == sorted(set(obs)) and len(obs) == 20
    events = [json.loads(x) for x in (out / "detected.jsonl").read_text().splitlines()]
    assert [e["id"] for e in events] == ["s00-v00001", "s01-v00001"]
    assert [(e["player"], e["receiver"]) for e in events] == [("h-t8", "h-t3"), ("h-t1008", "h-t1003")]
    tracked = json.loads((out / "tracked.json").read_text())["frames"]
    assert [p["id"] for f in tracked for p in f["players"]] == ["h-t8", "h-t8", "h-t1008", "h-t1008"]
    dets = [json.loads(x) for x in (out / "detections.jsonl").read_text().splitlines()]
    assert [d["frame"] for d in dets] == obs and {d["clip"] for d in dets} == {"seed7-match"}
    for v in ("tac-l", "tac-r"):
        rows = (out / "views" / v / "observations.jsonl").read_text().splitlines()
        assert [json.loads(x)["frame"] for x in rows] == obs
    tracks = json.loads((out / "association.json").read_text())["tracks"]
    assert tracks == {"h-t1": {"track": "a-t4", "confidence": 1.0},
                      "h-t1001": {"track": "a-t1004", "confidence": 1.0}}


def test_the_edit_chapters_stay_apart_from_what_agents_read(tmp_path):
    clips, vision, manifest = _write(tmp_path)
    out = tmp_path / "match"
    mj.build(manifest, clips, vision, out)
    edit = json.loads((out / "edit.json").read_text())
    assert edit["chapters"] == manifest["chapters"] and "never to an agent" in edit["about"]
    for name in ("clip.json", "tracked.json", "association.json"):
        assert "chapters" not in json.loads((out / name).read_text())


@pytest.mark.parametrize("runs, message", [
    ({"seed7-t000000": [(0, 10)], "seed7-t000100": [(5, 6)]}, "not after"),  # overlaps the first
    ({"seed7-t000000": [(0, 10)], "seed7-t000100": [(100, 6), (103, 4)]}, "own timeline"),
])
def test_overlapping_or_out_of_order_segments_are_refused(tmp_path, runs, message):
    clips, vision, manifest = _write(tmp_path, runs)
    with pytest.raises(SystemExit, match=message):
        mj.build(manifest, clips, vision, tmp_path / "match")


def test_runs_on_other_frames_than_the_segment_shows_are_refused(tmp_path):
    clips, vision, manifest = _write(tmp_path, obs_shift=1)
    with pytest.raises(SystemExit, match="not its shown frames"):
        mj.build(manifest, clips, vision, tmp_path / "match")


def test_detections_on_other_frames_are_refused(tmp_path):
    clips, vision, manifest = _write(tmp_path)
    f = vision / "seed7-t000100" / "broadcast" / "detections.jsonl"
    f.write_text("".join(f.read_text().splitlines(keepends=True)[:-1]))
    with pytest.raises(SystemExit, match="detections or views"):
        mj.build(manifest, clips, vision, tmp_path / "match")


def test_a_segment_not_joined_yet_is_refused(tmp_path):
    clips, vision, manifest = _write(tmp_path)
    (vision / "seed7-t000100" / "joined" / "tracked.json").unlink()
    with pytest.raises(SystemExit, match="not joined yet"):
        mj.build(manifest, clips, vision, tmp_path / "match")


def test_track_ids_past_a_segments_range_are_refused():
    with pytest.raises(SystemExit, match="past"):
        mj.renumber("h-t1000", 2)
    assert mj.renumber({"a-t5": ["h-t2", "x"]}, 3) == {"a-t3005": ["h-t3002", "x"]}


def test_the_match_join_opens_no_answer_key(tmp_path):
    """In a fresh interpreter under the audit hook, with the segments' answer-key files planted:
    it reads the manifest, each segment's clip.json and the joined runs, nothing else."""
    clips, vision, manifest = _write(tmp_path)
    for seg in clips.iterdir():
        for name in TRUTH_FILES:
            if name != "clip.json":
                (seg / name).write_text("{}\n")
    m = tmp_path / "manifest.json"
    m.write_text(json.dumps(manifest))
    out = tmp_path / "match"
    run = run_audited(f"""
        from pathlib import Path
        from ninety.vision import match_join
        r = match_join.build(__import__("json").loads(Path({str(m)!r}).read_text()),
                             Path({str(clips)!r}), Path({str(vision)!r}), Path({str(out)!r}))
        OUT = r["frames"]
    """)
    assert run["out"] == 20
    read = [o for o in run["opened"] if o.startswith(str(clips))]
    assert {Path(o).name for o in read} == {"clip.json"}
    assert [r for r in truth_reads(run) if not r.endswith("clip.json")] == []
