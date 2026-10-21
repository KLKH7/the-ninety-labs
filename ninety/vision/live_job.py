"""Live detection on one clip: frames in; detections, events and tracked positions out, timed.

    uv run --group vision python -m ninety.vision.live_job <clip> \\
        --checkpoint ours-v4 --weights <checkpoint_best_total.pth> --out <dir>

What the Container Apps job runs on the demo clip (docs/TEAM.md, Thu Oct 22; docs/ARCHITECTURE.md,
"vision on CPU"): the whole live path of event detection in one process, each stage the module that
owns it, nothing re-implemented here:

    detect (RF-DETR) -> observe (camera from the markings, boxes on the pitch)
    -> events (tracks, teams, possession, passes, shots, out of play) -> tracked_frames (minimap)

The input folder may hold only `index.jsonl` (ninety.vision.frame_index: clip id, frame, time and
image path per frame) and `images/`. Anything else is refused before a model loads, so the answer
key and the render settings cannot travel with the clip, and detect's fallback to the labelled
frame file never runs. The index must list exactly the images in `images/`, in order, as observe
pairs them with the detection lines.

Writes to `--out`:

    detections.jsonl    one line per frame (ninety/vision/detections.py)
    observations.jsonl  one line per frame (ninety.vision.observe)
    detected.jsonl      match_event lines, `source: "vision"`, as ninety/match/detected.py loads them;
                        not named after the answer key's event file, so the two are never confused
    tracked.json        the phone companion's tracked frames (ninety.vision.tracked_frames)
    run.json            what ran and how long each stage took, for the claim that it runs live

`seconds` in run.json are wall-clock times on the machine that ran it, with its CPU count beside
them: they say what this machine did, not what another would.

The clip and the checkpoint are both inputs, so a new demo clip or a new checkpoint is a change of
arguments, not of code. Our checkpoint must come with its training record (`train-manifest.json`
beside the weights, as ninety/vision/train.py writes it, or `--manifest`): the run refuses weights
whose sha256 is not the record's `checkpoint_sha256`, or a record whose `name` is not
`--checkpoint`, before a model loads. It runs at the record's resolution unless `--resolution`
says otherwise. The model runs here, in this process: no hosted inference service (AGENTS.md).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path

import numpy as np

from ninety.vision import events as ev
from ninety.vision import observe, track, tracked_frames
from ninety.vision.detect import FINETUNE_CONFIG, detect_rows, frame_rows, labels_for
from ninety.vision.detections import FrameDetections, write_detections
from ninety.vision.frame_index import INDEX
from ninety.vision.model import load, model

IMAGES = "images"
ALLOWED = {INDEX, IMAGES}  # all the input folder may hold

Detector = Callable[[list[dict]], list[FrameDetections]]


def check_input(clip: Path) -> list[dict]:
    """The clip's frame rows, after refusing a folder that holds anything but the index and the
    images, or whose index does not list exactly its images in order."""
    if not (clip / INDEX).is_file() or not (clip / IMAGES).is_dir():
        raise SystemExit(f"{clip}: needs {INDEX} (python -m ninety.vision.frame_index) and {IMAGES}/")
    extra = sorted(p.name for p in clip.iterdir() if p.name not in ALLOWED)
    if extra:
        raise SystemExit(f"{clip}: refused: the input may hold only {INDEX} and {IMAGES}/, not {extra}")
    rows = frame_rows(clip)
    images = sorted((clip / IMAGES).glob("*.jpg"))
    if not rows or [Path(r["image"]).resolve() for r in rows] != [p.resolve() for p in images]:
        raise SystemExit(f"{clip}: {INDEX} must list every image in {IMAGES}/, in order, and nothing else")
    if len({r["clip"] for r in rows}) != 1:
        raise SystemExit(f"{clip}: {INDEX} names more than one clip")
    return rows


def _rgb(path: Path) -> np.ndarray:
    from PIL import Image

    return np.asarray(Image.open(path).convert("RGB"))


def _jsonl(path: Path, rows: list[dict]) -> None:
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        for r in rows:
            f.write(json.dumps(r, separators=(",", ":")) + "\n")


def run(clip: Path, out: Path, load_detector: Callable[[], Detector], about: dict | None = None) -> dict:
    """Run the live path on `clip` into `out` and return run.json's contents. `load_detector()`
    loads the model and returns a function from frame rows to detections; it is passed in so the
    tests run the real stages after it without rfdetr installed."""
    rows = check_input(clip)
    out.mkdir(parents=True, exist_ok=True)
    seconds: dict[str, float] = {}
    clock = time.perf_counter()

    def lap(stage: str) -> None:
        nonlocal clock
        now = time.perf_counter()
        seconds[stage] = round(now - clock, 3)
        clock = now

    detector = load_detector()
    lap("load")
    dets = detector(rows)
    lap("detect")
    write_detections(out / "detections.jsonl", dets)
    _jsonl(out / "observations.jsonl", observe.observe([r["image"] for r in rows], dets, _rgb))
    lap("observe")
    # Read back as the events stage always reads its input, so this run and the CLIs agree.
    obs = track.read_observations(out / "observations.jsonl")
    found, summary = ev.detect(obs)
    (out / "detected.jsonl").write_text("".join(json.dumps(e) + "\n" for e in found), encoding="utf-8")
    lap("events")
    clip_id = rows[0]["clip"]
    tracked = tracked_frames.build(obs, clip_id)
    (out / "tracked.json").write_text(tracked_frames.text(tracked), encoding="utf-8")
    lap("tracked")
    report = {
        "clip": clip_id,
        "frames": len(rows),
        "camera_ok": summary["frames_camera_ok"],
        "detections": sum(len(d.detections) for d in dets),
        "events": summary["events"],
        "named": summary["named"],
        "seconds": seconds | {"total": round(sum(seconds.values()), 3)},
        "detect_seconds_per_frame": round(seconds["detect"] / len(rows), 4),
        "cpus": os.cpu_count(),
        **(about or {}),
    }
    (out / "run.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def verify_checkpoint(weights: Path, checkpoint: str, manifest: Path | None = None) -> dict:
    """The training record of `weights`, after checking it is this checkpoint's and these weights':
    its `name` is `checkpoint` and its `checkpoint_sha256` is the file's. Refuses otherwise."""
    manifest = manifest or weights.with_name("train-manifest.json")
    if not manifest.is_file():
        raise SystemExit(f"{manifest} is missing: our checkpoint must come with its training record")
    if not weights.is_file():
        raise SystemExit(f"{weights} is missing")
    record = json.loads(manifest.read_text())
    if record.get("name") != checkpoint:
        raise SystemExit(f"{manifest} records {record.get('name')!r}, not --checkpoint {checkpoint!r}")
    actual, recorded = sha256(weights), record.get("checkpoint_sha256")
    if recorded != actual:
        raise SystemExit(f"{weights} has sha256 {actual}, not the {recorded} in {manifest}")
    return record


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Run the live path of event detection on one clip, timed.")
    ap.add_argument("clip", type=Path, help=f"a folder holding only {INDEX} and {IMAGES}/")
    ap.add_argument("--checkpoint", required=True, help='our checkpoint name, e.g. ours-v4, or "coco"')
    ap.add_argument("--weights", type=Path, default=None, help="checkpoint file (not for coco)")
    ap.add_argument("--manifest", type=Path, default=None,
                    help="its training record (default: train-manifest.json beside the weights)")
    ap.add_argument("--resolution", type=int, default=None, help="default: the trained size")
    ap.add_argument("--batch", type=int, default=8)
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args(argv)
    if (a.checkpoint == "coco") != (a.weights is None):
        ap.error("--weights is required for our checkpoints and not allowed for coco")
    check_input(a.clip)  # before hashing or loading anything
    if a.weights:
        record = verify_checkpoint(a.weights, a.checkpoint, a.manifest)
        resolution = a.resolution or record["config"]["resolution"]
    else:  # the COCO baseline, at the size we fine-tune at, as detect runs it
        record, resolution = {}, a.resolution or json.loads(FINETUNE_CONFIG.read_text())["resolution"]
    weights = str(a.weights) if a.weights else None
    field = model(a.checkpoint)

    def load_detector() -> Detector:
        det = load(weights, resolution=resolution)
        label = labels_for(a.checkpoint, det.class_names)
        return lambda rows: detect_rows(det, rows, label, field, a.batch)

    about = {
        "model": asdict(field),
        "weights_sha256": record.get("checkpoint_sha256"),
        "resolution": resolution,
        "commit": os.environ.get("NINETY_COMMIT", "unknown"),
    }
    report = run(a.clip, a.out, load_detector, about)
    print(json.dumps({k: report[k] for k in ("clip", "frames", "events", "seconds")}))


if __name__ == "__main__":
    main()
