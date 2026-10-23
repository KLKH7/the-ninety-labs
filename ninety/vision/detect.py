"""Run RF-DETR Small over a clip's frames and write detections.jsonl (ninety/vision/detections.py).

    uv run python -m ninety.vision.detect runs/dataset/test/seed900001 --checkpoint coco
    uv run python -m ninety.vision.detect runs/dataset/test/seed900001 \
        --checkpoint ours-v1 --weights runs/train/v1/checkpoint_best_total.pth

Reads only the images and each frame's `clip`, `frame` and `t`, never its labels: this is the live
path, and ground truth is for grading. Keeps every detection down to SCORE_FLOOR; choosing a
threshold is the scorer's job.

The two checkpoints number classes differently. The COCO checkpoint returns COCO category ids
(1 person, 37 sports ball); indexing its 80 `class_names` with them is off by one. Our fine-tuned
checkpoint returns indices into its `class_names` (["player", "ball"]): with ours-v2 on validation
frames, id 0 gave player-shaped boxes (median 32 x 71 px, about 6 a frame) and id 1 one ball-shaped
box a frame (median 9 x 9 px). Read the ids by box shape on a trained model: a barely trained one
puts out noise, which is how this was once mapped backwards (docs/LESSONS.md).

Both checkpoints run at the same input size, so the baseline comparison changes one thing: the COCO
baseline runs at finetune.json's resolution (640), not rfdetr's default (512), and our checkpoint
at the resolution in its train-manifest.json.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ninety.vision.detections import SCORE_FLOOR, Detection, FrameDetections, write_detections
from ninety.vision.frame_index import INDEX
from ninety.vision.model import load, model

FINETUNE_CONFIG = Path(__file__).with_name("finetune.json")

COCO_TO_OURS = {1: "player", 37: "ball"}  # rfdetr.assets.coco_classes: person, sports ball
OURS = {"player", "ball"}


def labels_for(checkpoint: str, class_names: list[str]):
    """class_id -> our class or None: a COCO category id for the COCO checkpoint, an index into
    `class_names` for ours."""
    if checkpoint == "coco":
        return COCO_TO_OURS.get

    def label(class_id: int) -> str | None:
        name = class_names[class_id] if 0 <= class_id < len(class_names) else None
        return name if name in OURS else None

    return label


def trained_resolution(weights: str | None) -> int:
    """The input size to run at: what our checkpoint was trained at, from the train-manifest.json
    beside it; for the COCO baseline (no weights), the size we fine-tune at, so the two compare."""
    if weights is None:
        return json.loads(FINETUNE_CONFIG.read_text())["resolution"]
    manifest = Path(weights).with_name("train-manifest.json")
    if not manifest.exists():
        raise FileNotFoundError(
            f"{manifest} is missing: pass --resolution, or keep the manifest with the weights"
        )
    return json.loads(manifest.read_text())["config"]["resolution"]


def frame_rows(clip_dir: Path, stride: int = 1) -> list[dict]:
    """The frame fields the live path may read: clip id, frame index, time, image path.

    With a labels-free index.jsonl beside the images (ninety.vision.frame_index), it is the only
    file read, so detection can run on a machine that holds no answer key.
    """
    index = clip_dir / INDEX
    if index.exists():
        rows = [json.loads(line) for line in index.read_text().splitlines() if line.strip()]
        return [{**r, "image": clip_dir / r["image"]} for i, r in enumerate(rows) if not i % stride]
    clip_id = json.loads((clip_dir / "clip.json").read_text())["clip_id"]
    rows = []
    with open(clip_dir / "frames.jsonl") as f:
        for i, line in enumerate(f):
            if i % stride:
                continue
            fr = json.loads(line)
            rows.append(
                {"clip": clip_id, "frame": fr["frame"], "t": fr["t"], "image": clip_dir / fr["image"]}
            )
    return rows


def to_frame_detections(row: dict, xyxy, scores, class_ids, label, model_field) -> FrameDetections:
    dets = []
    for box, score, cid in zip(xyxy, scores, class_ids, strict=True):
        cls = label(int(cid))
        if cls is not None and score >= SCORE_FLOOR:
            dets.append(
                Detection(cls=cls, bbox=tuple(round(float(v), 2) for v in box), score=round(float(score), 4))
            )
    return FrameDetections(
        clip=row["clip"], frame=row["frame"], t=row["t"], model=model_field, detections=tuple(dets)
    )


def detect_rows(det, rows: list[dict], label, model_field, batch: int = 8) -> list[FrameDetections]:
    """The loaded detector over `rows` (frame_rows), `batch` images at a time, in frame order."""
    from PIL import Image

    out_rows = []
    for i in range(0, len(rows), batch):
        chunk = rows[i : i + batch]
        preds = det.predict(
            [Image.open(r["image"]).convert("RGB") for r in chunk],
            threshold=SCORE_FLOOR,
            include_source_image=False,
        )
        preds = preds if isinstance(preds, list) else [preds]
        for r, p in zip(chunk, preds, strict=True):
            out_rows.append(to_frame_detections(r, p.xyxy, p.confidence, p.class_id, label, model_field))
    return out_rows


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Detect players and the ball in a clip's frames.")
    ap.add_argument("clip", type=Path)
    ap.add_argument("--checkpoint", required=True, help='"coco" or our checkpoint name, e.g. ours-v1')
    ap.add_argument("--weights", default=None, help="checkpoint file (not for coco)")
    ap.add_argument(
        "--resolution",
        type=int,
        default=None,
        help="input size; default: what the checkpoint was trained at (coco: finetune.json's)",
    )
    ap.add_argument("--stride", type=int, default=1)
    ap.add_argument("--batch", type=int, default=8)
    ap.add_argument("--out", type=Path, default=None, help="default: <clip>/detections-<checkpoint>.jsonl")
    a = ap.parse_args(argv)
    if (a.checkpoint == "coco") != (a.weights is None):
        ap.error("--weights is required for our checkpoints and not allowed for coco")
    det = load(a.weights, resolution=a.resolution or trained_resolution(a.weights))
    label = labels_for(a.checkpoint, det.class_names)
    field = model(a.checkpoint)
    out_rows = detect_rows(det, frame_rows(a.clip, a.stride), label, field, a.batch)
    out = a.out or a.clip / f"detections-{a.checkpoint}.jsonl"
    write_detections(out, out_rows)
    print(
        json.dumps(
            {"out": str(out), "frames": len(out_rows), "detections": sum(len(r.detections) for r in out_rows)}
        )
    )


if __name__ == "__main__":
    main()
