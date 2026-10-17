import pytest

from ninety.eval.fake_box_detections import fake_detections
from ninety.eval.vision_score import iou, score


def frames():
    return [{"frame": 0, "camera": {"width": 1280, "height": 720},
             "players": [{"bbox": [10, 10, 30, 50], "visibility": 1.0}],
             "ball": {"bbox": [40, 40, 50, 50], "visibility": 1.0}}]


def test_fake_detections_perfect_copy_and_expected_metrics():
    detections, expected = fake_detections(frames())
    assert expected["overall"]["tp"] == 2
    assert expected["overall"]["fp"] == expected["overall"]["fn"] == 0
    assert score(frames(), detections)["overall"]["f1"] == 1.0


def test_fake_detections_refuse_ambiguous_shift():
    with pytest.raises(ValueError, match="matching rule"):
        fake_detections(frames(), shift=1, shift_px=1)


def test_fake_detections_are_deterministic():
    assert fake_detections(frames(), seed=4, drop=1, add=1)[0] == fake_detections(
        frames(), seed=4, drop=1, add=1
    )[0]


def test_added_false_box_is_in_frame_and_away_from_same_class_truth():
    detections, _ = fake_detections(frames(), add=1)
    added = detections[-1]
    assert 0 <= added["bbox"][0] <= added["bbox"][2] <= 1280
    assert 0 <= added["bbox"][1] <= added["bbox"][3] <= 720
    truth = next(label for label in detections[:-1] if label["cls"] == added["cls"])
    if added["cls"] == "player":
        assert iou(added["bbox"], truth["bbox"]) < 0.5


def test_fake_detections_refuse_when_no_false_in_frame_placement_exists():
    full_frame = [{
        "frame": 0,
        "camera": {"width": 20, "height": 20},
        "players": [{"bbox": [0, 0, 20, 20], "visibility": 1.0}],
    }]
    with pytest.raises(ValueError, match="no in-frame placement"):
        fake_detections(full_frame, add=1)
