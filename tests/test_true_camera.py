"""The true-camera diagnostic (ninety/eval/true_camera.py) and the label stand-in for detections
(ninety/eval/label_detections.py), both evaluation only. Scenes are built here (lesson 47)."""

from __future__ import annotations

import json

from ninety.eval import label_detections, true_camera

# A planted camera: pixel u = 10 x + 100 and v = 10 (y - z) + 50, so a point placed at height z lands
# z further along y than the same pixel on the grass.
P = [[10.0, 0.0, 0.0, 100.0], [0.0, 10.0, -10.0, 50.0], [0.0, 0.0, 0.0, 1.0]]


def test_every_frame_is_trusted_and_placed_through_its_true_camera_keeping_what_the_pixels_gave():
    live = [{"frame": 7, "t": 0.28, "camera": {"ok": False, "P": None, "points": 12, "shot": 2},
             "players": [{"bbox": [190, 240, 210, 300], "score": 0.9, "x": None, "y": None,
                          "rgb": [1, 2, 3]}],
             "ball": [{"bbox": [296, 146, 304, 154], "score": 0.8, "x": None, "y": None}]}]
    [row] = true_camera.re_place(live, [{"frame": 7, "camera": {"P": P}}])
    assert row["camera"]["ok"] and row["camera"]["true_camera"] and row["camera"]["shot"] == 2
    assert (row["players"][0]["x"], row["players"][0]["y"]) == (10.0, 25.0)  # the foot point
    assert row["players"][0]["rgb"] == [1, 2, 3] and row["players"][0]["score"] == 0.9
    assert (row["ball"][0]["x"], row["ball"][0]["y"]) == (20.0, 10.11)  # its centre, one radius up


def test_labels_on_screen_become_detections_of_score_one_and_hidden_ones_do_not(tmp_path):
    (tmp_path / "clip.json").write_text(json.dumps({"clip_id": "seed5"}))
    frames = [
        {"frame": 40, "t": 1.6, "ball": {"bbox": [5, 5, 9, 9], "visibility": 1.0},
         "players": [{"bbox": [0, 0, 10, 30], "visibility": 0.6},
                     {"bbox": [50, 0, 60, 30], "visibility": 0.0},  # a box, but none of him on screen
                     {"bbox": None, "visibility": 0.0}]},
        {"frame": 41, "t": 1.64, "ball": {"bbox": None, "visibility": 0.0}, "players": []},
    ]
    (tmp_path / "frames.jsonl").write_text("".join(json.dumps(f) + "\n" for f in frames))
    rows = label_detections.label_detections(tmp_path)
    assert [(r.clip, r.frame, r.t) for r in rows] == [("seed5", 40, 1.6), ("seed5", 41, 1.64)]
    assert [(d.cls, d.bbox, d.score) for d in rows[0].detections] == [
        ("player", (0.0, 0.0, 10.0, 30.0), 1.0), ("ball", (5.0, 5.0, 9.0, 9.0), 1.0)]
    assert rows[1].detections == ()
