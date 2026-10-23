"""Tile the tactical views of rendered clips into COCO folders (docs/eval/finetune-tactical/PLAN.md).

    uv run python scripts/coco_tiles.py <clip dirs> --out runs/coco/tactical-tiles \
        --config docs/eval/finetune-tactical/config.json

Each view (views/tac-l, views/tac-r) is exported by ninety.vision.coco_export on its own (it refuses
a seed twice, and the two views share one), with the config's validation seeds and stride, then
every image is tiled and the views are merged, each tile named by its view.

A 1920x1080 tactical view resized to the detector's 640 px leaves a far-side player about 12 px tall
and the ball under 3 px. So each image is cut into a 2x2 grid of tiles, each half the frame plus an
overlap with its neighbour, as the live path cuts them, and each tile is an image of its own.

A box cut by a tile's edge is clipped to the tile. It is kept when at least MIN_KEPT of its area is
inside, since the detector must find players half out of shot, as coco_export keeps boxes cut by
the frame's edge; a sliver under that is dropped, not labelled. A tile with no labels is kept, as
coco_export keeps frames without the ball. The split (train/valid by seed) is coco_export's, unchanged:
tiles of one frame never straddle it.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from PIL import Image

ANNOTATIONS = "_annotations.coco.json"
# The tile grid (*design*; must equal the live path's tiling): 2 columns and 2 rows, each tile half
# the frame plus OVERLAP of a half on its inner side, so neighbours share OVERLAP x 2 of a half.
GRID = (2, 2)
OVERLAP = 0.10
MIN_KEPT = 0.3  # *design*: the share of a box's area that must be inside a tile to be its label
JPEG_QUALITY = 95  # the tile is re-encoded once; high, so the crop adds next to nothing to the render's


def tiles(width: int, height: int, grid=GRID, overlap=OVERLAP) -> list[tuple[int, int, int, int]]:
    """(x0, y0, x1, y1) of each tile, row by row, in whole pixels, covering the frame."""
    cols, rows = grid
    tw, th = round(width / cols * (1 + overlap)), round(height / rows * (1 + overlap))
    xs = [round(i * (width - tw) / (cols - 1)) for i in range(cols)] if cols > 1 else [0]
    ys = [round(j * (height - th) / (rows - 1)) for j in range(rows)] if rows > 1 else [0]
    return [(x, y, x + tw, y + th) for y in ys for x in xs]


def clip_box(bbox: list[float], tile: tuple[int, int, int, int]) -> list[float] | None:
    """The COCO box [x, y, w, h] in tile pixels, or None when under MIN_KEPT of it is inside."""
    x, y, w, h = bbox
    tx0, ty0, tx1, ty1 = tile
    x0, y0, x1, y1 = max(x, tx0), max(y, ty0), min(x + w, tx1), min(y + h, ty1)
    if x1 <= x0 or y1 <= y0 or (x1 - x0) * (y1 - y0) < MIN_KEPT * w * h:
        return None
    return [x0 - tx0, y0 - ty0, x1 - x0, y1 - y0]


def tile_split(src: Path, dst: Path, prefix: str = "") -> dict:
    coco = json.loads((src / ANNOTATIONS).read_text())
    by_image: dict[int, list[dict]] = {}
    for a in coco["annotations"]:
        by_image.setdefault(a["image_id"], []).append(a)
    dst.mkdir(parents=True, exist_ok=True)
    images, annotations = [], []
    for im in coco["images"]:
        picture = Image.open(src / im["file_name"])
        for k, tile in enumerate(tiles(im["width"], im["height"])):
            image_id = len(images) + 1
            name = f"{prefix}{Path(im['file_name']).stem}_t{k}.jpg"
            picture.crop(tile).save(dst / name, quality=JPEG_QUALITY)
            images.append({**im, "id": image_id, "file_name": name, "width": tile[2] - tile[0],
                           "height": tile[3] - tile[1], "tile": list(tile), "source": im["file_name"]})
            for a in by_image.get(im["id"], []):
                box = clip_box(a["bbox"], tile)
                if box:
                    annotations.append({**a, "id": len(annotations) + 1, "image_id": image_id, "bbox": box,
                                        "area": box[2] * box[3]})
    return {"images": images, "annotations": annotations, "categories": coco["categories"]}


VIEWS = ("tac-l", "tac-r")


def export_views(clip_dirs: list[Path], out: Path, config: dict) -> dict:
    """Export each view with coco_export, tile it, and merge the views into out/train and out/valid."""
    from ninety.vision.coco_export import export

    summary: dict = {"grid": list(GRID), "overlap": OVERLAP, "min_kept": MIN_KEPT, "views": {}}
    merged: dict[str, dict] = {}
    for view in VIEWS:
        whole = out / f"whole-{view}"
        summary["views"][view] = export([Path(d) / "views" / view for d in clip_dirs], whole,
                                        set(config["val_seeds"]), config["stride"])
        for split in ("train", "valid"):
            part = tile_split(whole / split, out / split, prefix=f"{view}_")
            m = merged.setdefault(split, {"images": [], "annotations": [], "categories": part["categories"]})
            offset_i, offset_a = len(m["images"]), len(m["annotations"])
            m["images"] += [{**im, "id": im["id"] + offset_i, "view": view} for im in part["images"]]
            m["annotations"] += [{**a, "id": a["id"] + offset_a, "image_id": a["image_id"] + offset_i}
                                 for a in part["annotations"]]
    for split, m in merged.items():
        (out / split / ANNOTATIONS).write_text(json.dumps(m))
        summary[split] = {"tiles": len(m["images"]), "annotations": len(m["annotations"])}
    (out / "tiles.json").write_text(json.dumps(summary, indent=2))
    return summary


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("clips", nargs="+", type=Path, help="clip directories rendered with --views tactical")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--config", type=Path, required=True, help="training config with val_seeds and stride")
    a = ap.parse_args(argv)
    summary = export_views(a.clips, a.out, json.loads(a.config.read_text()))
    print(json.dumps({k: v for k, v in summary.items() if k != "views"}))


if __name__ == "__main__":
    main()
