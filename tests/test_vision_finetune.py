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


def test_short_fine_tune_validates_only_on_clips_dataset_v1_has():
    # coco_export refuses a val seed that is not among the clips: seed 111 is excluded from
    # dataset v1 and so left validation (finetune.json notes)
    listing = Path(vision_model.__file__).parents[2] / "docs" / "eval" / "dataset-v1.json"
    seeds = {c["seed"] for c in json.loads(listing.read_text())["clips_list"]}
    short = json.loads((Path(vision_model.__file__).parent / "finetune-short.json").read_text())
    assert set(short["val_seeds"]) <= seeds
    assert short["val_seeds"] == CONFIG["val_seeds"]


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


def test_the_frame_index_holds_no_labels_and_detection_reads_only_it(tmp_path):
    from ninety.vision.frame_index import write_index

    d = write_clip(tmp_path, 1, n=6)
    want = detect.frame_rows(d)
    index = write_index(d)
    rows = [json.loads(line) for line in index.read_text().splitlines()]
    assert all(set(r) == {"clip", "frame", "t", "image"} for r in rows)
    # On a machine without the answer key: only the images and the index.
    for name in ("frames.jsonl", "clip.json"):
        (d / name).unlink()
    assert detect.frame_rows(d) == want
    assert detect.frame_rows(d, stride=2) == want[::2]


class FakeModel:
    """Stands in for rfdetr: writes a best checkpoint, then finishes or is stopped from outside."""

    def __init__(self, stopped=False):
        self.stopped = stopped

    def train(self, output_dir, **kwargs):
        (Path(output_dir) / train.BEST).write_bytes(b"best so far")
        if self.stopped:
            raise SystemExit(1)  # what pytorch_lightning does on SIGINT, after a graceful shutdown


def run_training(tmp_path, monkeypatch, model):
    coco_export.export([write_clip(tmp_path, s) for s in (1, 2)], tmp_path / "coco", val_seeds={2}, stride=1)
    monkeypatch.setattr(train, "load", lambda init=None: model)
    monkeypatch.setattr(train.importlib.metadata, "version", lambda name: "1.11.2")
    out = tmp_path / "run"
    train.main(["--data", str(tmp_path / "coco"), "--out", str(out), "--name", "ours-test"])
    return out


def test_a_finished_run_records_its_best_checkpoint(tmp_path, monkeypatch):
    out = run_training(tmp_path, monkeypatch, FakeModel())
    m = json.loads((out / "train-manifest.json").read_text())
    assert m["finished"] and m["stopped"] is None
    assert m["checkpoint_sha256"] == train.sha256(out / train.BEST)
    with pytest.raises(ValueError, match="already complete"):
        train.record_only(out, "time cap")


def test_a_run_stopped_at_its_time_cap_is_recorded_with_the_reason(tmp_path, monkeypatch):
    with pytest.raises(SystemExit):
        run_training(tmp_path, monkeypatch, FakeModel(stopped=True))
    out = tmp_path / "run"
    m = json.loads((out / "train-manifest.json").read_text())
    assert m["started"] and m["finished"] is None and m["checkpoint_sha256"] is None
    with pytest.raises(ValueError, match="does not match"):  # an unrecorded run cannot seed another
        train.init_from(out / train.BEST)
    train.main(["--out", str(out), "--record-only", "time cap of 110 minutes"])
    m = json.loads((out / "train-manifest.json").read_text())
    assert m["stopped"] == "time cap of 110 minutes" and m["finished"]
    assert m["checkpoint_sha256"] == train.sha256(out / train.BEST) and m["name"] == "ours-test"


def test_record_only_needs_a_started_run_and_a_reason(tmp_path):
    with pytest.raises(FileNotFoundError, match="never started"):
        train.record_only(tmp_path, "time cap")
    (tmp_path / "train-manifest.json").write_text(json.dumps({"name": "x", "finished": None}))
    with pytest.raises(ValueError, match="reason"):
        train.record_only(tmp_path, " ")


def write_tactical_clip(root, seed, views=("tac-l", "tac-r"), n=2):
    """A tactical clip: each view's real 1920 x 1080 frames, one player on the vertical seam of
    the tile grid (whole in both top tiles), one ball in the top-left tile only."""
    from PIL import Image

    d = root / f"seed{seed}"
    (d).mkdir(parents=True)
    (d / "clip.json").write_text(json.dumps({"seed": seed, "split": "train", "clip_id": f"seed{seed}"}))
    for v in views:
        (d / "views" / v / "images").mkdir(parents=True)
        rows = []
        for i in range(n):
            Image.new("RGB", (1920, 1080), (40, 120, 40)).save(d / "views" / v / "images" / f"{i:05d}.jpg")
            rows.append({"frame": 10 + i, "t": i / 25, "image": f"images/{i:05d}.jpg",
                         "camera": {"width": 1920, "height": 1080},
                         "players": [{"bbox": [950, 200, 980, 270], "visibility": 1.0}],
                         "ball": {"bbox": [100, 100, 104, 104], "visibility": 1.0}})
        (d / "views" / v / "frames.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    return d


def test_tiled_export_writes_the_live_grid_with_labels_clipped_into_each_tile(tmp_path):
    from PIL import Image

    dirs = [write_tactical_clip(tmp_path, s) for s in (1, 2)]
    out = tmp_path / "coco"
    coco_export.export(dirs, out, val_seeds={2}, stride=1, tiles=0.0)
    coco = load_split(out, "train")
    # Per frame and view: the top-left tile (player and ball), the top-right (player); the two
    # bottom tiles hold nothing and are dropped at share 0.
    names = sorted(i["file_name"] for i in coco["images"])
    assert names == sorted(f"seed1_{v}_{f:06d}_t{k}.jpg"
                           for v in ("tac-l", "tac-r") for f in (10, 11) for k in (0, 1))
    assert all(Image.open(out / "train" / n).size == (1056, 594) for n in names)
    by_image = {}
    for a in coco["annotations"]:
        by_image.setdefault(a["image_id"], []).append((a["category_id"], a["bbox"]))
    for img in coco["images"]:
        got = sorted(by_image[img["id"]])
        if img["file_name"].endswith("_t0.jpg"):
            assert got == [(1, [950, 200, 30, 70]), (2, [100, 100, 4, 4])]
        else:  # the top-right tile starts at x = 864
            assert got == [(1, [86, 200, 30, 70])] and img["tile"] == [864, 0, 1920, 594]
    manifest = json.loads((out / "export.json").read_text())
    assert manifest["tiles"]["empty_share"] == 0.0
    assert manifest["train"]["empty_tiles"] == {"kept": 0, "dropped": 8}


def test_a_label_cut_by_a_tile_edge_is_clipped_to_the_part_inside():
    from ninety.vision.tiles import grid

    tl = grid(1920, 1080)[0]
    a = {"category_id": 1, "bbox": [1040, 100, 30, 60], "area": 1800}
    assert coco_export._clipped(a, tl)["bbox"] == [1040, 100, 16, 60]
    assert coco_export._clipped(a | {"bbox": [1100, 100, 30, 60]}, tl) is None


def test_the_share_of_empty_tiles_kept_is_the_one_asked_and_the_choice_is_fixed():
    draws = [coco_export.keep_empty(7, "tac-l", f, k, 0.1) for f in range(2000) for k in range(4)]
    assert 0.08 < sum(draws) / len(draws) < 0.12
    assert draws == [coco_export.keep_empty(7, "tac-l", f, k, 0.1) for f in range(2000) for k in range(4)]
    assert not any(coco_export.keep_empty(7, "tac-l", f, 0, 0.0) for f in range(200))
    assert all(coco_export.keep_empty(7, "tac-l", f, 0, 1.0) for f in range(200))


def test_tiled_export_refuses_a_share_outside_0_to_1(tmp_path):
    with pytest.raises(ValueError, match="share"):
        coco_export.export([write_tactical_clip(tmp_path, 1)], tmp_path / "c", {1}, tiles=1.5)
