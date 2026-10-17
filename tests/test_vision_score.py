import json

import pytest

from ninety.eval.vision_score import main, score


def frames():
    return [{"frame": 0, "camera": {"width": 1280, "height": 720}, "players": [
        {"id": "h1", "bbox": [10, 10, 30, 50], "visibility": 1.0},
        {"id": "h2", "bbox": [60, 10, 80, 50], "visibility": 0.4},
    ], "ball": {"bbox": [40, 40, 50, 50], "visibility": 0.8}}]


def detections(score_value=1.0):
    return [{"frame": 0, "cls": "player", "bbox": [10, 10, 30, 50], "score": score_value},
            {"frame": 0, "cls": "player", "bbox": [60, 10, 80, 50], "score": score_value},
            {"frame": 0, "cls": "ball", "bbox": [40, 40, 50, 50], "score": score_value}]


def test_perfect_copy():
    report = score(frames(), detections())
    assert report["overall"] == {"tp": 3, "fp": 0, "fn": 0, "precision": 1.0, "recall": 1.0, "f1": 1.0}
    assert report["visibility"]["player"]["visible"]["tp"] == 1
    assert report["visibility"]["player"]["visible"]["fp"] == 0
    assert report["visibility"]["player"]["visible"]["fn"] == 0
    assert report["visibility"]["player"]["visible"]["precision"] == 1.0
    assert report["visibility"]["player"]["visible"]["recall"] == 1.0
    assert report["visibility"]["player"]["visible"]["f1"] == 1.0
    assert report["visibility"]["player"]["mostly hidden"]["tp"] == 1
    assert report["visibility"]["ball"]["partly hidden"]["tp"] == 1
    assert report["visibility"]["ball"]["partly hidden"]["fp"] == 0
    assert report["visibility"]["ball"]["partly hidden"]["fn"] == 0
    assert report["visibility"]["ball"]["partly hidden"]["precision"] == 1.0
    assert report["visibility"]["ball"]["partly hidden"]["recall"] == 1.0
    assert report["visibility"]["ball"]["partly hidden"]["f1"] == 1.0


def test_exact_planted_metrics():
    damaged = detections()
    damaged.pop(0)
    damaged.append({"frame": 0, "cls": "ball", "bbox": [100, 100, 110, 110], "score": 1.0})
    row = score(frames(), damaged)["overall"]
    assert (row["tp"], row["fp"], row["fn"]) == (2, 1, 1)
    assert row["precision"] == pytest.approx(2 / 3)
    assert row["recall"] == pytest.approx(2 / 3)


def test_shifted_past_rule_is_a_miss():
    damaged = detections()
    damaged[0]["bbox"] = [30, 10, 50, 50]
    row = score(frames(), damaged)["by_class"]["player"]
    assert (row["tp"], row["fp"], row["fn"]) == (1, 1, 1)


def test_best_first_uses_iou_for_players_and_distance_for_balls():
    labels = [
        {"frame": 0, "cls": "player", "bbox": [0, 0, 10, 10], "visibility": 1.0},
        {"frame": 0, "cls": "ball", "bbox": [40, 40, 50, 50], "visibility": 1.0},
    ]
    detections = [
        {"frame": 0, "cls": "player", "bbox": [0, 0, 9, 9], "score": 1.0},
        {"frame": 0, "cls": "player", "bbox": [0, 0, 10, 10], "score": 1.0},
        {"frame": 0, "cls": "ball", "bbox": [44, 40, 54, 50], "score": 1.0},
        {"frame": 0, "cls": "ball", "bbox": [40, 40, 50, 50], "score": 1.0},
    ]
    pairs = score([{"frame": 0, "boxes": labels}], detections)["pairs"]
    assert [(pair["cls"], pair["detection"]) for pair in pairs] == [
        ("player", 1), ("ball", 3)
    ]


def test_thresholding():
    report = score(frames(), detections(0.4))
    assert report["overall"]["tp"] == 0
    assert report["overall"]["fp"] == 0
    assert report["overall"]["fn"] == 3


def test_cli(tmp_path, capsys):
    frame_path = tmp_path / "frames.jsonl"
    det_path = tmp_path / "detections.jsonl"
    report_path = tmp_path / "report.json"
    frame_path.write_text(json.dumps(frames()[0]) + "\n")
    det_path.write_text("".join(json.dumps(d) + "\n" for d in detections()))
    main(["--frames", str(frame_path), "--detected", str(det_path), "--report", str(report_path)])
    assert json.loads(report_path.read_text())["overall"]["f1"] == 1.0
    assert json.loads(capsys.readouterr().out)["overall"]["tp"] == 3
