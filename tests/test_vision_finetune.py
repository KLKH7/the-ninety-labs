"""Fine-tuning plumbing on hand-built clips: export, config, loader guard and detection mapping.

None of this needs rfdetr or a GPU; the loader guard is checked against a fake rfdetr module.
"""

import json
import sys
import types
from pathlib import Path

import pytest

from ninety.render.splits import split_of
from ninety.vision import coco_export, detect, train
from ninety.vision import model as vision_model
from ninety.vision.detections import SCORE_FLOOR

CONFIG = json.loads((Path(vision_model.__file__).parent / "finetune.json").read_text())


def write_clip(root, seed, n=4, split="train", ball_vis=1.0):
    d = root / f"seed{seed}"
    (d / "images").mkdir(parents=True)
    (d / "clip.json").write_text(json.dumps({"seed": seed, "split": split, "clip_id": f"seed{seed}"}))
    rows = []
    for i in range(n):
        (d / "images" / f"{i:05d}.jpg").write_bytes(b"jpg")
        players = [
            {"bbox": [10, 20, 30, 80], "visibility": 1.0},
            {"bbox": [0, 0, 5, 40], "visibility": 0.4},  # cut by the edge: kept
            {"bbox": None, "visibility": 0.0},
        ]  # out of shot: not a label
        ball = (
            {"bbox": [100, 100, 108, 108], "visibility": ball_vis}
            if i % 2 == 0
            else {"bbox": None, "visibility": 0}
        )
        rows.append(
            {
                "frame": 1000 + i,
                "t": i / 25,
                "image": f"images/{i:05d}.jpg",
                "camera": {"width": 1280, "height": 720},
                "players": players,
                "ball": ball,
            }
        )
    (d / "frames.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    return d


def load_split(out, split):
    return json.loads((out / split / coco_export.ANNOTATIONS).read_text())


def test_export_splits_by_seed_and_converts_boxes(tmp_path):
    dirs = [write_clip(tmp_path, s) for s in (1, 2, 3)]
    summary = coco_export.export(dirs, tmp_path / "coco", val_seeds={2}, stride=1)
    assert summary["valid"]["seeds"] == [2] and sorted(summary["train"]["seeds"]) == [1, 3]
    coco = load_split(tmp_path / "coco", "train")
    assert len(coco["images"]) == 8  # every frame, with or without the ball
    first = [a for a in coco["annotations"] if a["image_id"] == 1]
    assert {a["category_id"] for a in first} == {1, 2}
    assert [10, 20, 20, 60] in [a["bbox"] for a in first]  # x0,y0,x1,y1 -> x,y,w,h
    assert len([a for a in first if a["category_id"] == 1]) == 2  # the off-screen player is skipped
    img = coco["images"][0]
    assert (tmp_path / "coco" / "train" / img["file_name"]).resolve().exists()


def test_export_keeps_one_frame_in_stride(tmp_path):
    dirs = [write_clip(tmp_path, s, n=10) for s in (1, 2)]
    coco_export.export(dirs, tmp_path / "coco", val_seeds={2}, stride=5)
    assert len(load_split(tmp_path / "coco", "train")["images"]) == 2


@pytest.mark.parametrize(
    "bad_seed, split",
    [
        (900001, "test"),
        (950000, "reserved"),
        # wrong one way only, so each half of the guard is tested on its own:
        (900001, "train"),  # a test seed whose clip.json says train: the seed check must catch it
        (5, "test"),  # a training seed whose clip.json says test: the clip.json check must catch it
    ],
)
def test_export_refuses_evaluation_seeds(tmp_path, bad_seed, split):
    dirs = [write_clip(tmp_path, 1), write_clip(tmp_path, bad_seed, split=split)]
    with pytest.raises(ValueError, match="not a training seed"):
        coco_export.export(dirs, tmp_path / "coco", val_seeds={1})


def test_export_refuses_a_duplicate_seed_and_a_missing_val_seed(tmp_path):
    a = write_clip(tmp_path / "a", 1)
    b = write_clip(tmp_path / "b", 1)
    with pytest.raises(ValueError, match="twice"):
        coco_export.export([a, b], tmp_path / "coco", val_seeds=set())
    with pytest.raises(ValueError, match="not among the clips"):
        coco_export.export([a, write_clip(tmp_path, 2)], tmp_path / "coco2", val_seeds={99})


def test_learning_curve_subsets_are_nested(tmp_path):
    dirs = [write_clip(tmp_path, s, n=1) for s in range(1, 13)]
    small = coco_export.export(dirs, tmp_path / "c3", val_seeds={12}, stride=1, train_clips=3)
    large = coco_export.export(dirs, tmp_path / "c6", val_seeds={12}, stride=1, train_clips=6)
    assert set(small["train"]["seeds"]) < set(large["train"]["seeds"])
    with pytest.raises(ValueError):
        coco_export.export(dirs, tmp_path / "c0", val_seeds={12}, stride=1, train_clips=0)


def test_config_is_fixed_and_valid():
    assert all(split_of(s) == "train" for s in CONFIG["val_seeds"])
    assert len(set(CONFIG["val_seeds"])) == len(CONFIG["val_seeds"])
    assert CONFIG["resolution"] % 32 == 0  # rfdetr Small: divisible by patch 16 x windows 2
    kw = train.train_kwargs(CONFIG, Path("data"), Path("out"))
    assert kw["resolution"] == CONFIG["resolution"] and kw["epochs"] == CONFIG["train"]["epochs"]


def test_training_needs_an_exported_dataset(tmp_path):
    with pytest.raises(FileNotFoundError):
        train.check_dataset(tmp_path)


def fake_rfdetr(monkeypatch, size):
    mod = types.ModuleType("rfdetr")

    class Small:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    Small.size = size
    mod.RFDETRSmall = Small
    monkeypatch.setitem(sys.modules, "rfdetr", mod)


def test_loader_builds_small_and_passes_weights(monkeypatch):
    fake_rfdetr(monkeypatch, "rfdetr-small")
    m = vision_model.load("runs/train/v1/checkpoint_best_total.pth", resolution=640)
    assert m.kwargs == {"pretrain_weights": "runs/train/v1/checkpoint_best_total.pth", "resolution": 640}


def test_loader_refuses_a_class_that_is_not_small(monkeypatch):
    fake_rfdetr(monkeypatch, "rfdetr-xlarge")
    with pytest.raises(RuntimeError, match="not rfdetr-small"):
        vision_model.load()


def test_coco_ids_map_by_category_id_not_list_index():
    # COCO ids are category ids: 1 person, 37 sports ball; class_names[1] would be "bicycle"
    label = detect.labels_for("coco", ["person", "bicycle"])
    assert (label(1), label(37), label(2)) == ("player", "ball", None)


def test_our_checkpoint_maps_by_index_into_class_names():
    # measured on ours-v2: id 0 player-shaped boxes (32 x 71 px), id 1 one 9 x 9 px box a frame.
    # The old mapping (1 player, 2 ball) labelled every ball a player and dropped every player.
    label = detect.labels_for("ours-v2", ["player", "ball"])
    assert (label(0), label(1), label(2), label(-1)) == ("player", "ball", None, None)


def test_frame_detections_keep_the_floor_and_drop_other_classes():
    row = {"clip": "seed1", "frame": 7, "t": 0.28}
    fd = detect.to_frame_detections(
        row,
        [[0, 0, 10, 10], [1, 1, 2, 2], [5, 5, 9, 9]],
        [0.9, SCORE_FLOOR / 2, 0.8],
        [1, 1, 3],
        detect.COCO_TO_OURS.get,
        vision_model.model("coco"),
    )
    assert [(d.cls, d.score) for d in fd.detections] == [("player", 0.9)]


def test_live_path_reads_no_labels(tmp_path):
    d = write_clip(tmp_path, 1, n=3)
    rows = detect.frame_rows(d)
    assert all(set(r) == {"clip", "frame", "t", "image"} for r in rows)


def test_inference_uses_the_resolution_the_checkpoint_was_trained_at(tmp_path):
    (tmp_path / "train-manifest.json").write_text(json.dumps({"config": {"resolution": 640}}))
    assert detect.trained_resolution(str(tmp_path / "checkpoint_best_total.pth")) == 640
    # the COCO baseline runs at the size we fine-tune at, so a gain is the training, not the input size
    assert detect.trained_resolution(None) == CONFIG["resolution"]
    with pytest.raises(FileNotFoundError):
        detect.trained_resolution(str(tmp_path / "elsewhere" / "x.pth"))


def test_resume_continues_from_the_runs_last_checkpoint(tmp_path):
    with pytest.raises(FileNotFoundError, match="nothing to resume"):
        train.resume_from(tmp_path)
    (tmp_path / train.LAST).write_bytes(b"ckpt")
    last = train.resume_from(tmp_path)
    assert train.train_kwargs(CONFIG, Path("data"), tmp_path, last)["resume"] == str(tmp_path / "last.ckpt")
    assert "resume" not in train.train_kwargs(CONFIG, Path("data"), tmp_path)


def test_export_copies_frames_where_symlinks_are_not_allowed(tmp_path, monkeypatch):
    # Windows allows symlinks only for administrators or in Developer Mode
    def no_symlinks(*args, **kwargs):
        raise OSError("symbolic link privilege not held")

    monkeypatch.setattr(coco_export.os, "symlink", no_symlinks)
    dirs = [write_clip(tmp_path, s) for s in (1, 2)]
    coco_export.export(dirs, tmp_path / "coco", val_seeds={2}, stride=1)
    img = load_split(tmp_path / "coco", "train")["images"][0]
    frame = tmp_path / "coco" / "train" / img["file_name"]
    assert not frame.is_symlink() and frame.read_bytes() == b"jpg"


def test_init_needs_our_checkpoint_with_a_matching_manifest(tmp_path):
    ckpt = tmp_path / "checkpoint_best_total.pth"
    ckpt.write_bytes(b"weights")
    with pytest.raises(FileNotFoundError, match="training record"):
        train.init_from(ckpt)
    (tmp_path / "train-manifest.json").write_text(
        json.dumps({"name": "ours-v2", "commit": "abc", "checkpoint_sha256": "0" * 64})
    )
    with pytest.raises(ValueError, match="does not match"):
        train.init_from(ckpt)
    (tmp_path / "train-manifest.json").write_text(
        json.dumps({"name": "ours-v2", "commit": "abc", "checkpoint_sha256": train.sha256(ckpt)})
    )
    assert train.init_from(ckpt) == {
        "name": "ours-v2",
        "commit": "abc",
        "checkpoint_sha256": train.sha256(ckpt),
    }


def test_the_short_config_differs_only_where_its_notes_say():
    short = json.loads((Path(vision_model.__file__).parent / "finetune-short.json").read_text())
    assert {k: v for k, v in short.items() if k not in ("train", "notes")} == {
        k: v for k, v in CONFIG.items() if k not in ("train", "notes")
    }
    changed = {k for k in CONFIG["train"] if short["train"][k] != CONFIG["train"][k]}
    assert changed == {"epochs", "lr", "lr_encoder", "early_stopping_patience"}
    assert short["train"]["lr"] < CONFIG["train"]["lr"]
