"""Rendered clips -> the COCO folders RF-DETR trains on (`train/`, `valid/`).

    RENDERS_SAS_URL=<container SAS URL> uv run python -m ninety.vision.fetch_clips v2 --out clips
    uv run python -m ninety.vision.coco_export clips/seed* --out runs/coco/v1 \
        --config ninety/vision/finetune.json [--stride 5] [--train-clips 50]

Pass training clips only: a pattern that also matches test clips is refused (see below).

Labels come from `frames.jsonl` only, the renderer's exact boxes. A box with visibility 0 has
nothing drawn and is not a label; a box cut by the image edge is kept, because the detector must
find players half out of shot. Every kept frame becomes an image, also when it has no labels, so
the model sees frames where the ball is out of shot.

The validation split is chosen by seed, never by frame: neighbouring frames of one clip are near
copies, so splitting frames would leak training images into validation. Only training seeds are
accepted; the fixed test set never enters these folders.

A clip of the fixed tactical camera holds each lens's frames under `views/<name>/`; every view is
exported, its images named with the view.

`--tiles` exports each kept frame as the 2 x 2 grid of overlapping tiles the live detector runs on
(ninety/vision/tiles.py), so training sees objects at the size detection will: each label clipped
to the tile, kept when any of it is inside (as a box cut by the image edge is kept). Most tiles
with no label (the stands, empty grass) are dropped: `--empty-tiles S` keeps a share S of them,
chosen by a hash of the clip, view, frame and tile, so the choice is fixed; the share and the
counts kept and dropped go in export.json. Tiles are written as JPEG at quality 95 without chroma
subsampling, so a 3 px ball keeps its colour.

`--train-clips N` keeps the first N training clips in a fixed order (by a hash of the seed), so the
subsets for the learning curve are nested: the 50-clip set is inside the 100-clip set.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
from pathlib import Path

from ninety.render.splits import split_of
from ninety.vision.frame_index import views
from ninety.vision.tiles import COLS, OVERLAP, ROWS, grid

CATEGORIES = [
    {"id": 1, "name": "player", "supercategory": "object"},
    {"id": 2, "name": "ball", "supercategory": "object"},
]
CATEGORY_ID = {c["name"]: c["id"] for c in CATEGORIES}
ANNOTATIONS = "_annotations.coco.json"
EMPTY_TILES = 0.1  # the default share of label-free tiles kept (design; recorded in export.json)
TILE_JPEG = {"quality": 95, "subsampling": 0}


def clip_order(seed: int) -> str:
    """A fixed, seed-only order for nested subsets, independent of how clips were rendered."""
    return hashlib.sha256(f"ninety-train-order-{seed}".encode()).hexdigest()


def _box(cls: str, obj: dict) -> dict | None:
    if obj["bbox"] is None or obj["visibility"] <= 0:
        return None
    x0, y0, x1, y1 = obj["bbox"]
    w, h = x1 - x0, y1 - y0
    if w <= 0 or h <= 0:
        return None
    return {
        "category_id": CATEGORY_ID[cls],
        "bbox": [x0, y0, w, h],
        "area": w * h,
        "iscrowd": 0,
        "visibility": obj["visibility"],
    }


def _split_clips(clip_dirs: list[Path], val_seeds: set[int]) -> dict[str, list[tuple[int, Path]]]:
    out: dict[str, list[tuple[int, Path]]] = {"train": [], "valid": []}
    seen: dict[int, Path] = {}
    for d in clip_dirs:
        clip = json.loads((d / "clip.json").read_text())
        seed = clip["seed"]
        if split_of(seed) != "train" or clip["split"] != "train":
            raise ValueError(f"{d}: seed {seed} is not a training seed; the test set never enters training")
        if seed in seen:
            raise ValueError(f"seed {seed} appears twice: {seen[seed]} and {d}")
        seen[seed] = d
        out["valid" if seed in val_seeds else "train"].append((seed, d))
    missing = val_seeds - set(seen)
    if missing:
        raise ValueError(f"validation seeds not among the clips: {sorted(missing)}")
    for k in out:
        out[k].sort(key=lambda sd: clip_order(sd[0]))
    return out


def _place(src: Path, dst: Path) -> None:
    """Link the frame into the split folder, or copy it where links are not allowed.

    Windows lets only administrators, or accounts in Developer Mode, create symlinks; there the
    frame is copied. The bytes are the same either way.
    """
    try:
        os.symlink(src, dst)
    except OSError:
        shutil.copyfile(src, dst)


def keep_empty(seed: int, view: str, frame: int, tile: int, share: float) -> bool:
    """Whether a label-free tile is kept: a fixed draw from its identity, below `share`."""
    h = hashlib.sha256(f"ninety-empty-tile-{seed}-{view}-{frame}-{tile}".encode()).digest()
    return int.from_bytes(h[:8], "big") / 2**64 < share


def _clipped(a: dict, t) -> dict | None:
    """A label (COCO, [x, y, w, h] in image pixels) as it lies in tile t, or None if none of it does."""
    x, y, w, h = a["bbox"]
    x0, y0 = max(x, t.x0), max(y, t.y0)
    x1, y1 = min(x + w, t.x1), min(y + h, t.y1)
    if x1 <= x0 or y1 <= y0:
        return None
    return a | {"bbox": [x0 - t.x0, y0 - t.y0, x1 - x0, y1 - y0], "area": (x1 - x0) * (y1 - y0)}


def write_split(clips: list[tuple[int, Path]], out: Path, stride: int, tiles: float | None = None) -> dict:
    """The split's COCO folder. With `tiles` (the share of label-free tiles kept), each frame is
    written as its tiles (module docstring)."""
    from PIL import Image

    out.mkdir(parents=True, exist_ok=True)
    images, annotations = [], []
    empty = {"kept": 0, "dropped": 0}
    for seed, d in clips:
        for view, folder in views(d).items():
            tag = f"seed{seed}_{view}_" if view else f"seed{seed}_"
            with open(folder / "frames.jsonl") as f:
                for i, line in enumerate(f):
                    if i % stride:
                        continue
                    fr = json.loads(line)
                    cam = fr["camera"]
                    objs = [("player", p) for p in fr["players"]] + [("ball", fr["ball"])]
                    labels = [a for a in (_box(cls, obj) for cls, obj in objs) if a]
                    src = (folder / fr["image"]).resolve()
                    if tiles is None:
                        name = f"{tag}{fr['frame']:06d}.jpg"
                        if not (out / name).exists():
                            _place(src, out / name)
                        parts = [(name, cam["width"], cam["height"], labels, None)]
                    else:
                        parts = []
                        for k, t in enumerate(grid(cam["width"], cam["height"])):
                            inside = [c for c in (_clipped(a, t) for a in labels) if c]
                            if not inside and not keep_empty(seed, view, fr["frame"], k, tiles):
                                empty["dropped"] += 1
                                continue
                            empty["kept"] += not inside
                            parts.append((f"{tag}{fr['frame']:06d}_t{k}.jpg", *t.size, inside, t))
                        if parts:
                            with Image.open(src) as im:
                                im = im.convert("RGB")
                                for name, _, _, _, t in parts:
                                    im.crop((t.x0, t.y0, t.x1, t.y1)).save(out / name, **TILE_JPEG)
                    for name, w, h, inside, t in parts:
                        image_id = len(images) + 1
                        images.append({"id": image_id, "file_name": name, "width": w, "height": h,
                                       "seed": seed, "frame": fr["frame"]}
                                      | ({"view": view} if view else {})
                                      | ({"tile": [t.x0, t.y0, t.x1, t.y1]} if t else {}))
                        for a in inside:
                            annotations.append({"id": len(annotations) + 1, "image_id": image_id, **a})
    coco = {"images": images, "annotations": annotations, "categories": CATEGORIES}
    (out / ANNOTATIONS).write_text(json.dumps(coco))
    return {
        "clips": len(clips),
        "images": len(images),
        "annotations": len(annotations),
        "seeds": [s for s, _ in clips],
    } | ({"empty_tiles": empty} if tiles is not None else {})


def export(
    clip_dirs: list[Path], out: Path, val_seeds: set[int], stride: int = 5, train_clips: int | None = None,
    tiles: float | None = None,
) -> dict:
    """`tiles`: export tiles, keeping this share of the label-free ones; None for whole frames."""
    if stride < 1:
        raise ValueError(f"stride must be at least 1, got {stride}")
    if tiles is not None and not 0 <= tiles <= 1:
        raise ValueError(f"the share of empty tiles kept must be from 0 to 1, got {tiles}")
    splits = _split_clips([Path(d) for d in clip_dirs], val_seeds)
    if train_clips is not None:
        if not 0 < train_clips <= len(splits["train"]):
            raise ValueError(f"--train-clips {train_clips} is not between 1 and {len(splits['train'])}")
        splits["train"] = splits["train"][:train_clips]
    if not splits["train"] or not splits["valid"]:
        raise ValueError("both the train and the valid split need at least one clip")
    summary = {k: write_split(v, out / k, stride, tiles) for k, v in splits.items()}
    tiling = None if tiles is None else {"cols": COLS, "rows": ROWS, "overlap": OVERLAP,
                                         "empty_share": tiles, "jpeg": TILE_JPEG}
    (out / "export.json").write_text(
        json.dumps({"stride": stride, "train_clips": train_clips, "tiles": tiling, **summary}, indent=2)
    )
    return summary


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Write rendered clips as COCO folders for RF-DETR training.")
    ap.add_argument("clips", nargs="+", type=Path, help="clip directories (training seeds only)")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--config", type=Path, required=True, help="training config with val_seeds")
    ap.add_argument("--stride", type=int, default=None, help="every Nth frame (default: the config's)")
    ap.add_argument(
        "--train-clips", type=int, default=None, help="first N training clips, for the learning curve"
    )
    ap.add_argument("--tiles", action="store_true", help="export each frame as the live detector's tiles")
    ap.add_argument("--empty-tiles", type=float, default=EMPTY_TILES,
                    help=f"with --tiles, the share of label-free tiles kept (default {EMPTY_TILES})")
    a = ap.parse_args(argv)
    cfg = json.loads(a.config.read_text())
    summary = export(a.clips, a.out, set(cfg["val_seeds"]), a.stride or cfg["stride"], a.train_clips,
                     a.empty_tiles if a.tiles else None)
    print(
        json.dumps(
            {k: {kk: vv for kk, vv in v.items() if kk != "seeds"} for k, v in summary.items()}, indent=2
        )
    )


if __name__ == "__main__":
    main()
