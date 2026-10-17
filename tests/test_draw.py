import json

from ninety.eval.draw import draw


def label_frame(number):
    return {"frame": number, "image": f"img/{number:05d}.jpg", "camera": {"width": 1280, "height": 720},
            "players": [{"id": "h1", "bbox": [10, 10, 30, 50], "visibility": 1.0}],
            "ball": {"bbox": [40, 40, 50, 50], "visibility": 1.0}}


def test_only_frames_the_detector_ran_on_are_drawn_and_counted(tmp_path):
    # Three labelled frames; the detector ran on 0 (found everything) and 2 (found nothing),
    # and never ran on 1. Frame 1 gets no overlay and its labels are not misses; frame 2's are.
    clip = tmp_path / "clip"
    (clip / "img").mkdir(parents=True)
    rows = [label_frame(number) for number in (0, 1, 2)]
    for row in rows:
        (clip / row["image"]).write_bytes(b"")
    (clip / "frames.jsonl").write_text("".join(json.dumps(row) + "\n" for row in rows))
    detected = tmp_path / "detections.jsonl"
    detected.write_text(
        json.dumps({"frame": 0, "detections": [
            {"cls": "player", "bbox": [10, 10, 30, 50], "score": 1.0},
            {"cls": "ball", "bbox": [40, 40, 50, 50], "score": 1.0},
        ]}) + "\n"
        + json.dumps({"frame": 2, "detections": []}) + "\n"
    )
    out = tmp_path / "out"
    counts = draw(clip, detected, out)
    assert counts == {"frames": 2, "matched": 2, "missed": 2, "false": 0}
    assert sorted(path.name for path in out.iterdir()) == ["00000.svg", "00002.svg"]
    assert "MISSED" in (out / "00002.svg").read_text()
