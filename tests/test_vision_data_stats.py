import argparse
import json

import pytest

from ninety.render.params import LIGHTING, WEATHER
from ninety.vision.data_stats import (
    TEST_FLOORS,
    TRAIN_FLOORS,
    dataset_stats,
    find_clips,
    floor_failures,
    parse_input,
    percentile,
)
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
    report = dataset_stats(find_clips([tmp_path]), stride=5)
    train = report["splits"]["train"]
    assert train["clips"] == 2
    assert train["frames"] == 4  # frames 0 and 5 of each clip
    assert train["player_boxes"] == 4  # the visibility-0 player is never a label
    assert train["ball_boxes"] == 4
    assert train["ball_by_visibility"] == {"visible": 2, "partly hidden": 0, "mostly hidden": 2}
    assert train["ball_visibility_lt_0_5_share"] == 0.5
    assert train["clips_by_knob"]["lighting"] == {"day": 1, "night": 1}
    assert train["clips_by_knob"]["weather"] == {"clear": 1, "rain": 1}
    assert train["seeds"] == [1, 2]


def test_ball_size_scales_to_the_training_input(tmp_path):
    write_clip(tmp_path, 1, "train")  # ball box 12 x 8 in a 1280 x 720 frame
    clips = find_clips([tmp_path])
    native = dataset_stats(clips)["splits"]["train"]
    half = dataset_stats(clips, input_size=(640, 360))["splits"]["train"]
    square = dataset_stats(clips, input_size=(512, 512))["splits"]["train"]
    assert native["ball_size_px"]["median"] == 12.0
    assert half["ball_size_px"]["median"] == 6.0
    # squeezed to a square: width x0.4 gives 4.8, height x0.711 gives 5.69; the larger side wins
    assert square["ball_size_px"]["median"] == pytest.approx(8 * 512 / 720)


def test_splits_are_reported_apart(tmp_path):
    write_clip(tmp_path, 1, "train")
    write_clip(tmp_path, 900001, "test")
    report = dataset_stats(find_clips([tmp_path]))
    assert set(report["splits"]) == {"train", "test"}
    assert report["splits"]["test"]["seeds"] == [900001]


def test_bad_stride_is_refused(tmp_path):
    with pytest.raises(ValueError):
        dataset_stats([], stride=0)


def test_repeated_seed_is_refused_not_deduped(tmp_path):
    write_clip(tmp_path, 7, "train")
    copy = tmp_path / "seed7.rerender"  # what ninety-render-check --determinism leaves behind
    copy.mkdir()
    for name in ("clip.json", "frames.jsonl"):
        (copy / name).write_text((tmp_path / "seed7" / name).read_text())
    assert len(find_clips([tmp_path])) == 2
    with pytest.raises(ValueError, match=r"seed counted more than once.*\[7\]"):
        dataset_stats(find_clips([tmp_path]))


def test_distinct_seeds_reported(tmp_path):
    write_clip(tmp_path, 1, "train")
    write_clip(tmp_path, 2, "train")
    assert dataset_stats(find_clips([tmp_path]))["splits"]["train"]["distinct_seeds"] == 2


def test_lt_half_share_matches_render_check_with_a_fully_hidden_ball(tmp_path):
    from ninety.render.checks import occlusion

    clip = write_clip(tmp_path, 1, "train", n_frames=4)
    rows = [json.loads(line) for line in (clip / "frames.jsonl").read_text().splitlines()]
    for row, vis in zip(rows, (0.0, 0.3, 0.7, 1.0), strict=True):
        row["ball"]["visibility"] = vis
    (clip / "frames.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    train = dataset_stats(find_clips([tmp_path]), stride=1)["splits"]["train"]
    assert train["ball_visibility_lt_0_5_share"] == occlusion(rows)["ball_visibility_lt_0_5_share"] == 0.5
    assert train["ball_in_frame"] == 4
    assert train["ball_boxes"] == 3  # a fully hidden ball is not a training label
    assert train["ball_boxes_mostly_hidden_excluding_fully_hidden"] == 1


def test_lt_half_share_counts_every_frame_whatever_the_stride(tmp_path):
    # The render check counts every frame; a share under the same name must not move with the
    # training stride. Hidden ball only on frames the stride skips: 4 of 10 frames.
    from ninety.render.checks import occlusion

    clip = write_clip(tmp_path, 1, "test", n_frames=10)
    rows = [json.loads(line) for line in (clip / "frames.jsonl").read_text().splitlines()]
    for row in rows:
        if row["frame"] in (1, 2, 3, 4):
            row["ball"]["visibility"] = 0.2
    (clip / "frames.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    want = occlusion(rows)["ball_visibility_lt_0_5_share"]
    assert want == 0.4
    for stride in (1, 5):
        test = dataset_stats(find_clips([tmp_path]), stride=stride)["splits"]["test"]
        assert test["ball_visibility_lt_0_5_share"] == want
        assert test["ball_in_frame"] == 10


def test_floors_loop_over_the_values_the_renderer_allows(monkeypatch):
    from ninety.render import params

    monkeypatch.setitem(params.PLANNED, "lighting", ("day",))
    monkeypatch.setitem(params.PLANNED, "weather", ("clear",))
    splits = at_every_floor()
    splits["train"]["clips_by_knob"]["lighting"] = {"day": 15}
    splits["train"]["clips_by_knob"]["weather"] = {"clear": 15}
    assert floor_failures(splits) == []
    splits["train"]["clips_by_knob"]["weather"] = {"clear": 14}
    assert [f.split(" clips")[0] for f in floor_failures(splits)] == ["train weather=clear"]


def test_cli_writes_strict_json(tmp_path):
    write_clip(tmp_path / "clips", 1, "train")
    out = tmp_path / "stats.json"
    stats_main([str(tmp_path / "clips"), "--out", str(out)])  # without --floors it only reports
    report = json.loads(out.read_text())
    assert report["splits"]["train"]["clips"] == 1
    assert report["floor_failures"]


def test_cli_exits_nonzero_under_the_floors(tmp_path):
    write_clip(tmp_path / "clips", 1, "train")
    with pytest.raises(SystemExit) as exit_:
        stats_main([str(tmp_path / "clips"), "--floors", "--out", str(tmp_path / "stats.json")])
    assert exit_.value.code == 1


def test_input_size_parsing():
    assert parse_input("512x384") == (512, 384)
    for bad in ("512", "0x512", "ax5", "512x"):
        with pytest.raises(argparse.ArgumentTypeError):
            parse_input(bad)


def at_every_floor():
    """Split summaries exactly at every floor, so each test below moves one value under it."""
    balls = TRAIN_FLOORS["ball_boxes"]
    hidden_key = "ball_boxes_mostly_hidden_excluding_fully_hidden"
    hidden = max(TRAIN_FLOORS[hidden_key], round(balls * TRAIN_FLOORS["ball_visibility_lt_0_5_share"]))
    train = {
        "distinct_seeds": TRAIN_FLOORS["distinct_seeds"],
        "frames": TRAIN_FLOORS["frames"],
        "player_boxes": TRAIN_FLOORS["player_boxes"],
        "ball_boxes": balls,
        hidden_key: hidden,
        "ball_visibility_lt_0_5_share": hidden / balls,
        "clips_by_knob": {
            "lighting": {v: TRAIN_FLOORS["clips_per_lighting"] for v in LIGHTING},
            "weather": {v: TRAIN_FLOORS["clips_per_weather"] for v in WEATHER},
        },
        "kit_contrast_low_share": TRAIN_FLOORS["kit_contrast_low_share"],
        "occlusion_crowded_share": TRAIN_FLOORS["occlusion_crowded_share"],
    }
    test = {"ball_visibility_lt_0_5_share": TEST_FLOORS["ball_visibility_lt_0_5_share"]}
    return {"train": train, "test": test}


def test_splits_at_every_floor_pass():
    assert floor_failures(at_every_floor()) == []


@pytest.mark.parametrize(
    "miss, expect",
    [
        (lambda s: s["train"].update(distinct_seeds=149), "train distinct_seeds"),
        (lambda s: s["train"].update(frames=TRAIN_FLOORS["frames"] - 1), "train frames"),
        (lambda s: s["train"].update(player_boxes=TRAIN_FLOORS["player_boxes"] - 1), "train player_boxes"),
        (lambda s: s["train"].update(ball_boxes=TRAIN_FLOORS["ball_boxes"] - 1), "train ball_boxes"),
        (lambda s: s["train"].update(ball_boxes_mostly_hidden_excluding_fully_hidden=10),
         "train ball_boxes_mostly_hidden_excluding_fully_hidden:"),
        (lambda s: s["train"].update(ball_visibility_lt_0_5_share=0.01),
         "train ball_visibility_lt_0_5_share"),
        (lambda s: s["train"]["clips_by_knob"]["lighting"].pop("night"), "train lighting=night"),
        (lambda s: s["train"]["clips_by_knob"]["weather"].update(rain=3), "train weather=rain"),
        (lambda s: s["train"].update(kit_contrast_low_share=None), "train kit_contrast_low_share"),
        (lambda s: s["train"].update(occlusion_crowded_share=0.1), "train occlusion_crowded_share"),
        (lambda s: s["test"].update(ball_visibility_lt_0_5_share=0.049), "test ball_visibility_lt_0_5_share"),
        (lambda s: s.pop("train"), "train: no clips"),
        (lambda s: s.pop("test"), "test: no clips"),
    ],
)
def test_each_missed_floor_is_reported(miss, expect):
    splits = at_every_floor()
    miss(splits)
    fails = floor_failures(splits)
    assert len(fails) == 1 and fails[0].startswith(expect), fails
