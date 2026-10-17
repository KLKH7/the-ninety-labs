"""Fine-tune RF-DETR Small on an exported COCO dataset (ninety/vision/coco_export.py).

    uv sync --group vision
    uv run python -m ninety.vision.train --data runs/coco/v1 --out runs/train/v1 \
        --config ninety/vision/finetune.json --name ours-v1

Every training setting comes from the committed config, so a run is described by the config, the
exported dataset and the commit. The run writes `train-manifest.json` next to the checkpoints:
config, dataset summary, rfdetr version, commit, and the sha256 of the best checkpoint. The
checkpoint stays out of git; `--name` is the `checkpoint` field written to detections.jsonl.

Runs on whatever rfdetr finds (CUDA, Apple MPS or CPU). Use our own Azure GPU if we have quota,
never a hosted third-party service: the renders do not leave our resources.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import importlib.metadata
import json
import os
import subprocess
from pathlib import Path

from ninety.vision.coco_export import ANNOTATIONS
from ninety.vision.model import load

BEST = "checkpoint_best_total.pth"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def check_dataset(data: Path) -> dict:
    """The exported folders exist and carry the export summary; returns it."""
    for split in ("train", "valid"):
        if not (data / split / ANNOTATIONS).exists():
            raise FileNotFoundError(
                f"{data / split / ANNOTATIONS} is missing: run ninety.vision.coco_export first"
            )
    return json.loads((data / "export.json").read_text())


def train_kwargs(cfg: dict, data: Path, out: Path) -> dict:
    return {
        "dataset_dir": str(data),
        "output_dir": str(out),
        "resolution": cfg["resolution"],
        "tensorboard": False,
        **cfg["train"],
    }


def _git_commit() -> str | None:
    """The commit being trained: from git, or NINETY_COMMIT when the code was copied without .git."""
    if os.environ.get("NINETY_COMMIT"):
        return os.environ["NINETY_COMMIT"]
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Fine-tune RF-DETR Small on our renders.")
    ap.add_argument("--data", type=Path, required=True, help="exported COCO dataset (train/, valid/)")
    ap.add_argument("--out", type=Path, required=True, help="output directory for checkpoints")
    ap.add_argument("--config", type=Path, default=Path(__file__).with_name("finetune.json"))
    ap.add_argument("--name", required=True, help="checkpoint name for detections.jsonl, e.g. ours-v1")
    ap.add_argument("--epochs", type=int, default=None, help="override for a smoke run only")
    a = ap.parse_args(argv)
    cfg = json.loads(a.config.read_text())
    if a.epochs is not None:
        cfg["train"]["epochs"] = a.epochs
    dataset = check_dataset(a.data)
    a.out.mkdir(parents=True, exist_ok=True)
    started = dt.datetime.now(dt.UTC)
    model = load()
    model.train(**train_kwargs(cfg, a.data, a.out))
    best = a.out / BEST
    manifest = {
        "name": a.name,
        "started": started.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "finished": dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "commit": _git_commit(),
        "rfdetr": importlib.metadata.version("rfdetr"),
        "config": cfg,
        "epochs_override": a.epochs,
        "dataset": {
            k: {kk: vv for kk, vv in v.items() if kk != "seeds"} if isinstance(v, dict) else v
            for k, v in dataset.items()
        },
        "checkpoint": BEST if best.exists() else None,
        "checkpoint_sha256": sha256(best) if best.exists() else None,
    }
    (a.out / "train-manifest.json").write_text(json.dumps(manifest, indent=2))
    print(json.dumps({k: manifest[k] for k in ("name", "checkpoint", "checkpoint_sha256")}, indent=2))


if __name__ == "__main__":
    main()
