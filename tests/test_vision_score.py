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
    pairs = score([{
        "frame": 0, "camera": {"width": 1280, "height": 720}, "boxes": labels,
    }], detections)["pairs"]
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


@pytest.mark.parametrize("cls", ["player", "ball"])
@pytest.mark.parametrize("bbox,group", [
    ([0, 20, 10, 40], "edge-touching"),
    ([20, 0, 30, 10], "edge-touching"),
    ([1270, 20, 1280, 40], "edge-touching"),
    ([1041, 705, 1053, 720], "edge-touching"),
    ([0, 0, 1280, 720], "edge-touching"),
    ([0.01, 0.01, 1279.99, 719.99], "interior"),
    ([20, 20, 30, 40], "interior"),
])
@pytest.mark.parametrize("visibility,visibility_name", [
    (1.0, "visible"), (0.8, "partly hidden"), (0.4, "mostly hidden"),
])
def test_boundary_and_visibility_are_independent(cls, bbox, group, visibility, visibility_name):
    rows = [{
        "frame": 0, "camera": {"width": 1280, "height": 720},
        "boxes": [{"cls": cls, "bbox": bbox, "visibility": visibility}],
    }]
    report = score(rows, [{"frame": 0, "cls": cls, "bbox": bbox, "score": 1.0}])
    perfect = {"tp": 1, "fp": 0, "fn": 0, "precision": 1.0, "recall": 1.0, "f1": 1.0}
    assert report["image_boundary"][cls][group] == perfect
    assert report["visibility"][cls][visibility_name] == perfect
    assert report["overall"] == report["by_class"][cls] == perfect
    assert len(report["pairs"]) == 1
    other = "interior" if group == "edge-touching" else "edge-touching"
    assert report["image_boundary"][cls][other] == {
        "tp": 0, "fp": 0, "fn": 0, "precision": None, "recall": None, "f1": None,
    }


@pytest.mark.parametrize("cls", ["player", "ball"])
def test_boundary_errors_use_one_global_match_and_nearest_truth(cls):
    edge = [0, 20, 10, 40]
    interior = [50, 20, 60, 40]
    rows = [{
        "frame": 0, "camera": {"width": 100, "height": 80},
        "boxes": [
            {"cls": cls, "bbox": edge, "visibility": 1.0},
            {"cls": cls, "bbox": interior, "visibility": 0.4},
        ],
    }]
    predicted = [
        {"frame": 0, "cls": cls, "bbox": edge, "score": 1.0},
        {"frame": 0, "cls": cls, "bbox": edge, "score": 1.0},  # duplicate
        {"frame": 0, "cls": cls, "bbox": [70, 20, 80, 40], "score": 1.0},
        {"frame": 1, "cls": cls, "bbox": edge, "score": 1.0},  # no truth frame
        {"frame": 0, "cls": "ball" if cls == "player" else "player",
         "bbox": edge, "score": 1.0},  # no truth class
        {"frame": 0, "cls": cls, "bbox": interior, "score": 0.4},
    ]
    report = score(rows, predicted)
    groups = report["image_boundary"][cls]
    assert groups["edge-touching"] == {
        "tp": 1, "fp": 1, "fn": 0, "precision": 0.5, "recall": 1.0, "f1": pytest.approx(2 / 3),
    }
    assert groups["interior"] == {
        "tp": 0, "fp": 1, "fn": 1, "precision": 0.0, "recall": 0.0, "f1": None,
    }
    assert report["visibility"][cls]["visible"] == groups["edge-touching"]
    assert report["visibility"][cls]["mostly hidden"] == groups["interior"]
    assert report["overall"] == {
        "tp": 1, "fp": 4, "fn": 1, "precision": 0.2, "recall": 0.5, "f1": pytest.approx(2 / 7),
    }
    assert report["by_class"][cls]["fp"] == 3
    assert len(report["pairs"]) == 1


def test_boundary_is_from_truth_not_the_matched_prediction():
    rows = [{
        "frame": 0, "camera": {"width": 100, "height": 80},
        "boxes": [{"cls": "player", "bbox": [0, 20, 10, 40]}],
    }]
    report = score(rows, [{"frame": 0, "cls": "player", "bbox": [1, 20, 11, 40], "score": 1.0}])
    assert report["image_boundary"]["player"]["edge-touching"]["tp"] == 1
    assert report["image_boundary"]["player"]["interior"]["tp"] == 0


def test_boundary_misses_and_empty_report_have_undefined_metrics():
    report = score(frames(), [])
    assert report["image_boundary"]["player"]["interior"] == {
        "tp": 0, "fp": 0, "fn": 2, "precision": None, "recall": 0.0, "f1": None,
    }
    for groups in score([], [])["image_boundary"].values():
        for metrics in groups.values():
            assert metrics == {
                "tp": 0, "fp": 0, "fn": 0, "precision": None, "recall": None, "f1": None,
            }


def test_boundary_false_positive_tie_uses_first_label():
    rows = [{
        "frame": 0, "camera": {"width": 100, "height": 80},
        "boxes": [{"cls": "player", "bbox": bbox} for bbox in (
            [0, 20, 10, 40], [40, 20, 50, 40],
        )],
    }]
    report = score(rows, [{"frame": 0, "cls": "player", "bbox": [20, 20, 30, 40], "score": 1.0}])
    assert report["image_boundary"]["player"]["edge-touching"]["fp"] == 1
    assert report["image_boundary"]["player"]["interior"]["fp"] == 0


def test_boundary_requires_saved_camera_dimensions():
    rows = frames()
    del rows[0]["camera"]
    with pytest.raises(KeyError, match="width"):
        score(rows, detections())


@pytest.mark.parametrize("dimension", [0, -1, float("inf"), float("nan")])
def test_boundary_rejects_invalid_dimensions(dimension):
    rows = frames()
    rows[0]["camera"]["height"] = dimension
    with pytest.raises(ValueError, match="dimensions"):
        score(rows, detections())


def test_only_frames_the_detector_ran_on_are_scored(tmp_path, capsys):
    # Three labelled frames; the detector ran on 0 (found everything) and 2 (found nothing),
    # and never ran on 1. Frame 1's labels are not misses; frame 2's are.
    rows = []
    for number in (0, 1, 2):
        row = frames()[0]
        row["frame"] = number
        rows.append(row)
    frame_path = tmp_path / "frames.jsonl"
    det_path = tmp_path / "detections.jsonl"
    frame_path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    det_path.write_text(
        json.dumps({"frame": 0, "detections": [
            {k: v for k, v in d.items() if k != "frame"} for d in detections()
        ]}) + "\n"
        + json.dumps({"frame": 2, "detections": []}) + "\n"
    )
    main(["--frames", str(frame_path), "--detected", str(det_path)])
    report = json.loads(capsys.readouterr().out)
    assert report["overall"]["tp"] == 3
    assert report["overall"]["fp"] == 0
    assert report["overall"]["fn"] == 3  # frame 2 only; frame 1 was not run
    assert report["frames"] == {"scored": 2, "label_frames_skipped": 1}


def test_a_run_frame_missing_from_frames_jsonl_is_refused():
    with pytest.raises(ValueError, match="not in frames.jsonl"):
        score(frames(), [], run={0, 5})


def test_a_box_with_visibility_zero_is_not_a_label():
    # EVALUATION.md: boxes with visibility zero are not labels. A ball hidden behind the boards
    # once kept its box at visibility 0 and was counted as a miss in by_class and overall.
    frames = [{"frame": 0, "camera": {"width": 1280, "height": 720},
               "players": [{"id": "h1", "bbox": [10, 10, 30, 50], "visibility": 1.0},
                           {"id": "h2", "bbox": [60, 10, 80, 50], "visibility": 0.0}],
               "ball": {"bbox": [40, 40, 50, 50], "visibility": 0.0}}]
    detections = [{"frame": 0, "cls": "player", "bbox": [10, 10, 30, 50], "score": 0.9}]
    report = score(frames, detections)
    assert report["by_class"]["player"]["fn"] == 0
    assert report["by_class"]["ball"]["fn"] == 0
    assert report["overall"]["fn"] == 0
    assert report["by_class"]["player"]["recall"] == 1.0
