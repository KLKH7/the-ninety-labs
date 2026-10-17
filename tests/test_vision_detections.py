"""The detections.jsonl contract between the detector (workstream A) and the vision scorer (B)."""

import json
from pathlib import Path

import pytest

from ninety.vision.detections import (
    SCORE_FLOOR,
    Detection,
    FrameDetections,
    read_detections,
    write_detections,
)

FIXTURE = Path(__file__).parent / "fixtures" / "detections-seed900001.jsonl"


def _rows() -> list[dict]:
    return [json.loads(line) for line in FIXTURE.read_text(encoding="utf-8").splitlines()]


def _write_rows(path: Path, rows: list[dict]) -> Path:
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    return path


def test_fixture_loads():
    frames = read_detections(FIXTURE)
    assert [f.frame for f in frames] == [1200, 1201, 1202, 1203]
    assert {f.clip for f in frames} == {"seed900001"}
    assert frames[0].model.size == "small"
    assert frames[0].detections[0] == Detection("player", (412.0, 288.0, 431.0, 341.0), 0.91)
    assert frames[2].detections == ()  # a frame the detector ran on but found nothing


def test_write_then_read_returns_it_unchanged(tmp_path):
    frames = read_detections(FIXTURE)
    out = tmp_path / "detections.jsonl"
    write_detections(out, frames)
    assert read_detections(out) == frames
    written = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
    assert written == _rows()


def test_no_threshold_is_applied(tmp_path):
    scores = [d.score for f in read_detections(FIXTURE) for d in f.detections]
    assert min(scores) == SCORE_FLOOR
    out = tmp_path / "detections.jsonl"
    write_detections(out, read_detections(FIXTURE))
    assert [d.score for f in read_detections(out) for d in f.detections] == scores


@pytest.mark.parametrize("cls", ["person", "sports ball", "referee", "Player", ""])
def test_a_class_other_than_player_or_ball_is_refused(tmp_path, cls):
    rows = _rows()
    rows[1]["detections"][0]["cls"] = cls
    with pytest.raises(ValueError, match="cls"):
        read_detections(_write_rows(tmp_path / "d.jsonl", rows))
    with pytest.raises(ValueError, match="cls"):
        Detection(cls, (0.0, 0.0, 1.0, 1.0), 0.5)


@pytest.mark.parametrize(
    "bbox",
    [
        [431.0, 288.0, 412.0, 341.0],  # x1 < x0
        [412.0, 341.0, 431.0, 288.0],  # y1 < y0
        [412.0, 288.0, 411.9, 341.0],  # x1 a fraction under x0
    ],
)
def test_a_box_with_its_corners_swapped_is_refused(tmp_path, bbox):
    rows = _rows()
    rows[0]["detections"][0]["bbox"] = bbox
    with pytest.raises(ValueError, match="bbox"):
        read_detections(_write_rows(tmp_path / "d.jsonl", rows))
    with pytest.raises(ValueError, match="bbox"):
        Detection("player", tuple(bbox), 0.5)


def test_a_zero_width_box_is_legal():
    assert Detection("ball", (10.0, 10.0, 10.0, 12.0), 0.5).bbox == (10.0, 10.0, 10.0, 12.0)


@pytest.mark.parametrize(
    "bbox", [[1.0, 2.0, 3.0], [1.0, 2.0, 3.0, 4.0, 5.0], [1.0, "2", 3.0, 4.0], [1.0, None, 3.0, 4.0]]
)
def test_a_box_that_is_not_four_numbers_is_refused(tmp_path, bbox):
    rows = _rows()
    rows[0]["detections"][0]["bbox"] = bbox
    with pytest.raises(ValueError, match="bbox"):
        read_detections(_write_rows(tmp_path / "d.jsonl", rows))


@pytest.mark.parametrize("score", [-0.01, 1.01, "0.9", None])
def test_a_score_outside_0_to_1_is_refused(tmp_path, score):
    rows = _rows()
    rows[0]["detections"][0]["score"] = score
    with pytest.raises(ValueError, match="score"):
        read_detections(_write_rows(tmp_path / "d.jsonl", rows))


@pytest.mark.parametrize("size", ["atto", "femto", "pico", "xl", "2xl", "plus"])
def test_a_model_size_outside_the_apache_sizes_is_refused(tmp_path, size):
    rows = _rows()
    rows[0]["model"]["size"] = size
    with pytest.raises(ValueError, match="size"):
        read_detections(_write_rows(tmp_path / "d.jsonl", rows))


def test_a_frame_written_twice_is_refused(tmp_path):
    rows = _rows()
    rows.append(rows[0])
    with pytest.raises(ValueError, match="appears twice"):
        read_detections(_write_rows(tmp_path / "d.jsonl", rows))


def test_a_missing_or_extra_key_is_refused(tmp_path):
    rows = _rows()
    del rows[0]["t"]
    with pytest.raises(ValueError, match="keys"):
        read_detections(_write_rows(tmp_path / "d.jsonl", rows))
    rows = _rows()
    rows[0]["detections"][0]["label"] = "player"
    with pytest.raises(ValueError, match="keys"):
        read_detections(_write_rows(tmp_path / "d.jsonl", rows))


def test_the_error_names_the_line(tmp_path):
    rows = _rows()
    rows[3]["detections"][0]["cls"] = "person"
    with pytest.raises(ValueError, match=r"d\.jsonl:4:"):
        read_detections(_write_rows(tmp_path / "d.jsonl", rows))


def test_frame_must_be_a_non_negative_integer():
    model = read_detections(FIXTURE)[0].model
    for frame in (-1, 1.5, True):
        with pytest.raises(ValueError, match="frame"):
            FrameDetections("seed900001", frame, 0.0, model, ())
