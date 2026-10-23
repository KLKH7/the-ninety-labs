"""scripts/coco_tiles.py: the tactical views cut into a 2x2 grid of overlapping tiles for training."""

import importlib.util
import json
from pathlib import Path

from PIL import Image

SCRIPT = Path(__file__).parents[1] / "scripts" / "coco_tiles.py"
spec = importlib.util.spec_from_file_location("coco_tiles", SCRIPT)
tiles_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tiles_mod)


def test_four_tiles_cover_the_frame_and_neighbours_share_the_overlap():
    t = tiles_mod.tiles(1920, 1080)
    assert t == [(0, 0, 1056, 594), (864, 0, 1920, 594), (0, 486, 1056, 1080), (864, 486, 1920, 1080)]
    for x in range(0, 1920, 7):
        for y in range(0, 1080, 7):
            assert any(x0 <= x < x1 and y0 <= y < y1 for x0, y0, x1, y1 in t)


def test_a_box_cut_by_a_tile_edge_is_clipped_and_a_sliver_is_dropped():
    tile = (864, 0, 1920, 594)
    assert tiles_mod.clip_box([900, 100, 20, 40], tile) == [36, 100, 20, 40]  # inside: moved only
    assert tiles_mod.clip_box([854, 100, 20, 40], tile) == [0, 100, 10, 40]  # half inside: kept, clipped
    assert tiles_mod.clip_box([846, 100, 20, 40], tile) is None  # 10% inside: dropped
    assert tiles_mod.clip_box([100, 100, 20, 40], tile) is None  # outside


def _clip(root: Path, seed: int) -> Path:
    d = root / f"seed{seed}"
    for view in tiles_mod.VIEWS:
        v = d / "views" / view
        (v / "images").mkdir(parents=True)
        Image.new("RGB", (1920, 1080), (40, 120, 40)).save(v / "images" / "00000.jpg")
        (v / "clip.json").write_text(json.dumps({"seed": seed, "split": "train"}))
        row = {"frame": 100, "image": "images/00000.jpg", "camera": {"width": 1920, "height": 1080},
               "ball": {"bbox": [950, 500, 960, 510], "visibility": 1.0},
               "players": [{"bbox": [100, 100, 120, 160], "visibility": 0.8}]}
        (v / "frames.jsonl").write_text(json.dumps(row) + "\n")
    return d


def test_both_views_of_every_clip_are_tiled_and_merged_with_one_split_by_seed(tmp_path):
    clips = [_clip(tmp_path / "clips", 3), _clip(tmp_path / "clips", 108)]
    out = tmp_path / "coco"
    summary = tiles_mod.export_views(clips, out, {"val_seeds": [108], "stride": 5})
    assert summary["train"] == {"tiles": 8, "annotations": 2 * (1 + 4)}  # player once; ball in all four
    assert summary["valid"]["tiles"] == 8
    coco = json.loads((out / "train" / tiles_mod.ANNOTATIONS).read_text())
    names = [im["file_name"] for im in coco["images"]]
    assert len(set(names)) == 8 and {n.split("_")[0] for n in names} == {"tac-l", "tac-r"}
    assert all((out / "train" / n).is_file() for n in names)
    assert len({a["id"] for a in coco["annotations"]}) == len(coco["annotations"])
    assert {im["seed"] for im in coco["images"]} == {3}
    assert Image.open(out / "train" / names[1]).size == (1056, 594)
