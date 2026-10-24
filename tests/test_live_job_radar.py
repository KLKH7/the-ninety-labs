"""The live detection job's output is what the viewer's radar reads (ninety/radar.py): its
tracked.json and observations.jsonl go into radar.build unchanged, as `ninety-e2e --tracked
--observations` passes them.
"""

from __future__ import annotations

import json

from ninety import radar
from ninety.vision import live_job, pitch, tracked_frames
from ninety.vision.detections import read_detections
from tests.test_vision_live_job import clean_clip

W, H = 640, 360  # the synthetic clip's frames (tests/test_vision_live_path.py, synthetic_clip)


def test_the_radar_takes_a_single_camera_run_as_written(tmp_path, monkeypatch):
    clip, dets = clean_clip(tmp_path)
    monkeypatch.setattr(pitch, "find_gantry", lambda anchors, w, h: (58.0, -37.0, 16.0))
    found = read_detections(dets)
    out = tmp_path / "out"
    live_job.run(clip, out, lambda: (lambda rows: found))
    tracked = json.loads((out / "tracked.json").read_text())
    obs = radar.read_observations(out / "observations.jsonl")
    body = radar.build(tracked, obs, W, H)
    assert body["source"] == tracked_frames.SOURCE == radar.SOURCE
    assert [v["frame"] for v in body["views"]] == [r["frame"] for r in obs] == [0, 1]
    assert all(v["footprint"] for v in body["views"])  # the camera fit is ok on both frames
