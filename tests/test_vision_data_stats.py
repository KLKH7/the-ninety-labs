"""Dataset counts on hand-built clips with known answers, and floors that must fail when missed."""

import argparse
import json

import pytest

from ninety.render.params import LIGHTING, WEATHER
from ninety.vision.data_stats import FLOORS, dataset_stats, floor_failures, main, parse_input


def write_clip(root, seed, split, ball_vis, players=3, lighting="day", **params):
    d = root / f"seed{seed}"
    d.mkdir()
    p = {"lighting": lighting, "weather": "clear", "kit_contrast": "normal", "occlusion": "natural",
         "camera_cut": False, **params}
    (d / "clip.json").write_text(json.dumps({"seed": seed, "split": split, "params": p}))
    rows = []
    for i, v in enumerate(ball_vis):
        ball = {"bbox": [100, 100, 110, 106] if v > 0 else None, "visibility": v}
        pl = [{"bbox": [0, 0, 10, 50], "visibility": 1.0} for _ in range(players)]
        pl.append({"bbox": None, "visibility": 0.0})  # off screen: not a label
        rows.append({"frame": i, "camera": {"width": 1280, "height": 720}, "ball": ball, "players": pl})
    (d / "frames.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    return d


def test_counts_boxes_and_visibility_groups(tmp_path):
    d = write_clip(tmp_path, 1, "train", [1.0, 0.7, 0.3, 0.0])
    s = dataset_stats([d], stride=1)["train"]
    assert (s["clips"], s["frames"], s["player_boxes"], s["ball_boxes"]) == (1, 4, 12, 3)
    assert s["ball_by_visibility"] == {"visible": 1, "partly hidden": 1, "mostly hidden": 1}
    assert s["ball_mostly_hidden_share"] == pytest.approx(1 / 3, abs=1e-4)


def test_stride_keeps_every_nth_frame(tmp_path):
    d = write_clip(tmp_path, 1, "train", [1.0] * 10)
    assert dataset_stats([d], stride=5)["train"]["frames"] == 2
    with pytest.raises(ValueError):
        dataset_stats([d], stride=0)


def test_ball_size_scales_to_the_training_input(tmp_path):
    d = write_clip(tmp_path, 1, "train", [1.0])
    assert dataset_stats([d], stride=1)["train"]["ball_size_px"]["median"] == 10
    # 1280x720 squeezed to 512x512: width x0.4, height x0.711; the larger side wins
    assert dataset_stats([d], stride=1, input_size=(512, 512))["train"]["ball_size_px"]["median"] == 4.27


def test_splits_are_counted_apart(tmp_path):
    dirs = [write_clip(tmp_path, 1, "train", [1.0]), write_clip(tmp_path, 900001, "test", [0.2, 0.2])]
    s = dataset_stats(dirs, stride=1)
    assert s["train"]["ball_boxes"] == 1 and s["test"]["ball_boxes"] == 2


def big_train():
    """A train split exactly at every floor."""
    n = FLOORS["clips"]
    balls = FLOORS["ball_boxes"]
    hidden = max(FLOORS["ball_mostly_hidden"], int(balls * FLOORS["ball_mostly_hidden_share"]) + 1)
    return {
        "clips": n,
        "frames": FLOORS["frames"],
        "player_boxes": FLOORS["player_boxes"],
        "ball_boxes": balls,
        "ball_by_visibility": {"visible": balls - hidden, "partly hidden": 0, "mostly hidden": hidden},
        "ball_mostly_hidden_share": hidden / balls,
        "clips_by": {
            "lighting": {v: FLOORS["clips_per_lighting"] for v in LIGHTING},
            "weather": {v: FLOORS["clips_per_weather"] for v in WEATHER},
        },
        "kit_contrast_low_share": FLOORS["kit_contrast_low_share"],
        "occlusion_crowded_share": FLOORS["occlusion_crowded_share"],
    }


def test_a_split_at_every_floor_passes():
    assert floor_failures(big_train(), LIGHTING, WEATHER) == []


@pytest.mark.parametrize(
    "change, expect",
    [
        (lambda t: t.update(clips=FLOORS["clips"] - 1), "clips"),
        (lambda t: t.update(ball_boxes=FLOORS["ball_boxes"] - 1), "ball_boxes"),
        (lambda t: t.update(ball_mostly_hidden_share=0.0008), "ball_mostly_hidden_share"),
        (lambda t: t["ball_by_visibility"].update({"mostly hidden": 10}), "ball_mostly_hidden"),
        (lambda t: t["clips_by"]["lighting"].pop("night"), "lighting=night"),
        (lambda t: t["clips_by"]["weather"].update(rain=3), "weather=rain"),
        (lambda t: t.update(occlusion_crowded_share=0.1), "occlusion_crowded_share"),
        (lambda t: t.update(kit_contrast_low_share=None), "kit_contrast_low_share"),
    ],
)
def test_each_missed_floor_is_reported(change, expect):
    t = big_train()
    change(t)
    fails = floor_failures(t, LIGHTING, WEATHER)
    assert any(f.startswith(expect) for f in fails), fails


def test_no_train_split_fails():
    assert floor_failures(None, LIGHTING, WEATHER) == ["no train clips"]


def test_cli_exits_nonzero_under_the_floors(tmp_path, capsys):
    d = write_clip(tmp_path, 1, "train", [1.0])
    report = tmp_path / "out" / "stats.json"
    with pytest.raises(SystemExit) as e:
        main([str(d), "--stride", "1", "--floors", "--report", str(report)])
    assert e.value.code == 1
    assert json.loads(report.read_text())["train_floor_failures"]
    main([str(d), "--stride", "1"])  # without --floors it only reports


def test_input_size_parsing():
    assert parse_input("512x512") == (512, 512)
    for bad in ("512", "0x512", "ax5", "512x"):
        with pytest.raises(argparse.ArgumentTypeError):
            parse_input(bad)
