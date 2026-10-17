import json

import pytest

from ninety.vision.data_stats import dataset_stats, find_clips, percentile
from ninety.vision.data_stats import main as stats_main


def write_clip(root, seed, split, n_frames=10, ball_visibility=1.0, **knobs):
    clip = root / f"seed{seed}"
    clip.mkdir(parents=True)
    params = {"width": 1280, "height": 720, "lighting": "day", "weather": "clear",
              "kit_contrast": "normal", "occlusion": "natural", **knobs}
    (clip / "clip.json").write_text(json.dumps({"seed": seed, "split": split, "params": params}))
    rows = []
    for i in range(n_frames):
        rows.append({
            "frame": i,
            "camera": {"width": 1280, "height": 720},
            "players": [
                {"bbox": [10, 10, 30, 50], "visibility": 1.0},
                {"bbox": [60, 10, 80, 50], "visibility": 0.0},
            ],
            "ball": {"bbox": [100, 100, 112, 108], "visibility": ball_visibility},
        })
    (clip / "frames.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    return clip


def test_percentile_interpolates():
    assert percentile([], 0.5) is None
    assert percentile([1.0, 3.0], 0.5) == 2.0
    assert percentile([1.0, 2.0, 3.0, 4.0, 5.0], 0.05) == pytest.approx(1.2)


def test_exact_counts_with_stride_and_skipped_invisible_boxes(tmp_path):
    write_clip(tmp_path, 1, "train", n_frames=10, lighting="night")
    write_clip(tmp_path, 2, "train", n_frames=10, ball_visibility=0.3, weather="rain")
    report = dataset_stats(find_clips([tmp_path]), stride=5, train_width=1280)
    train = report["splits"]["train"]
    assert train["clips"] == 2
    assert train["frames"] == 4  # frames 0 and 5 of each clip
    assert train["player_boxes"] == 4  # the visibility-0 player is never a label
    assert train["ball_boxes"] == 4
    assert train["ball_by_visibility"] == {"visible": 2, "partly hidden": 0, "mostly hidden": 2}
    assert train["ball_mostly_hidden_share"] == 0.5
    assert train["clips_by_knob"]["lighting"] == {"day": 1, "night": 1}
    assert train["clips_by_knob"]["weather"] == {"clear": 1, "rain": 1}
    assert train["seeds"] == [1, 2]


def test_ball_size_scales_to_training_width(tmp_path):
    write_clip(tmp_path, 1, "train")
    full = dataset_stats(find_clips([tmp_path]), train_width=1280)["splits"]["train"]
    half = dataset_stats(find_clips([tmp_path]), train_width=640)["splits"]["train"]
    assert full["ball_size_px"]["median"] == 12.0
    assert half["ball_size_px"]["median"] == 6.0


def test_splits_are_reported_apart(tmp_path):
    write_clip(tmp_path, 1, "train")
    write_clip(tmp_path, 900001, "test")
    report = dataset_stats(find_clips([tmp_path]))
    assert set(report["splits"]) == {"train", "test"}
    assert report["splits"]["test"]["seeds"] == [900001]


def test_bad_stride_is_refused(tmp_path):
    with pytest.raises(ValueError):
        dataset_stats([], stride=0)


def test_cli_writes_strict_json(tmp_path):
    write_clip(tmp_path / "clips", 1, "train")
    out = tmp_path / "stats.json"
    stats_main([str(tmp_path / "clips"), "--out", str(out)])
    assert json.loads(out.read_text())["splits"]["train"]["clips"] == 1
