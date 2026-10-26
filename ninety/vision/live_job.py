"""Live detection on one clip: frames in; detections, events and tracked positions out, timed.

    uv run --group vision python -m ninety.vision.live_job <clip> \\
        --checkpoint ours-v4 --weights <checkpoint_best_total.pth> --out <dir>

What the Container Apps job runs on the demo clip (docs/TEAM.md, Thu Oct 22; docs/ARCHITECTURE.md,
"vision on CPU"): the whole live path of event detection in one process, each stage the module that
owns it, nothing re-implemented here:

    detect (RF-DETR) -> observe (camera from the markings, boxes on the pitch)
    -> events (tracks, teams, possession, passes, shots, out of play) -> tracked_frames (minimap)

The input folder may hold only `index.jsonl` (ninety.vision.frame_index: clip id, frame, time and
image path per frame) and `images/`, or, for the fixed tactical camera, only `views/<name>/`, each
view holding only its own `index.jsonl` and `images/`. Anything else, at any depth, is refused
before a model loads, so the answer key and the render settings cannot travel with the clip, and
detect's fallback to the labelled frame file never runs. Each index must list exactly the images
in its `images/`, in order, as observe pairs them with the detection lines; the views must list the
same frames of one clip.

With views, each view is detected and placed on its own (detect, observe), and the views'
observations are merged on the pitch (ninety.vision.fuse) before events; `views/<name>/` under
`--out` holds each view's detections and observations, and observations.jsonl is the merged one.
`--tiles` detects each frame as a 2 x 2 grid of tiles (ninety.vision.tiles).

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

On Azure this runs in the Container Apps job of infra/live-job.bicep, from infra/live-job.Dockerfile,
with `--echo`: the job holds no storage role (infra/check_truth_sealed.py allows none outside the
render job and the maintainer), so run.json and the detected events go to its log.
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
from ninety.vision import fuse, observe, restarts, track, tracked_frames
from ninety.vision.detect import FINETUNE_CONFIG, detect_rows, frame_rows, labels_for
from ninety.vision.detections import FrameDetections, write_detections
from ninety.vision.frame_index import INDEX, VIEWS
from ninety.vision.model import load, model

IMAGES = "images"
ALLOWED = {INDEX, IMAGES}  # all a view folder may hold

Detector = Callable[[list[dict]], list[FrameDetections]]


def _check_view(clip: Path) -> list[dict]:
    """The view's frame rows, after refusing a folder that holds anything but the index and the
    images (at any depth), or whose index does not list exactly its images in order."""
    if not (clip / INDEX).is_file() or not (clip / IMAGES).is_dir():
        raise SystemExit(f"{clip}: needs {INDEX} (python -m ninety.vision.frame_index) and {IMAGES}/")
    extra = sorted(p.name for p in clip.iterdir() if p.name not in ALLOWED)
    extra += sorted(str(p.relative_to(clip)) for p in (clip / IMAGES).rglob("*")
                    if p.is_dir() or p.suffix != ".jpg")
    if extra:
        raise SystemExit(f"{clip}: refused: the input may hold only {INDEX} and {IMAGES}/*.jpg, not {extra}")
    rows = frame_rows(clip)
    images = sorted((clip / IMAGES).glob("*.jpg"))
    if not rows or [Path(r["image"]).resolve() for r in rows] != [p.resolve() for p in images]:
        raise SystemExit(f"{clip}: {INDEX} must list every image in {IMAGES}/, in order, and nothing else")
    if len({r["clip"] for r in rows}) != 1:
        raise SystemExit(f"{clip}: {INDEX} names more than one clip")
    return rows


def check_views(clip: Path) -> dict[str, list[dict]]:
    """Each view's frame rows ({"": rows} for a single-camera clip), after refusing a folder that
    holds anything else, at any depth (module docstring)."""
    if not clip.is_dir():
        raise SystemExit(f"{clip}: not a folder")
    if not (clip / VIEWS).exists():
        return {"": _check_view(clip)}
    extra = sorted(p.name for p in clip.iterdir() if p.name != VIEWS)
    extra += sorted(f"{VIEWS}/{p.name}" for p in (clip / VIEWS).iterdir() if not p.is_dir())
    if extra:
        raise SystemExit(f"{clip}: refused: a clip with {VIEWS}/ may hold only {VIEWS}/<name>/, not {extra}")
    views = {p.name: _check_view(p) for p in sorted((clip / VIEWS).iterdir())}
    if len(views) < 2:
        raise SystemExit(f"{clip}: {VIEWS}/ must hold two views or more, not {sorted(views)}")
    keys = {n: [(r["clip"], r["frame"], r["t"]) for r in rows] for n, rows in views.items()}
    if len({tuple(k) for k in keys.values()}) != 1:
        raise SystemExit(f"{clip}: the views' indexes do not list the same frames of one clip")
    return views


def check_input(clip: Path) -> list[dict]:
    """A single-camera clip's frame rows, or the first view's (they all list the same frames)."""
    return next(iter(check_views(clip).values()))


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
    views = check_views(clip)
    out.mkdir(parents=True, exist_ok=True)
    seconds: dict[str, float] = {}
    clock = time.perf_counter()

    def lap(stage: str) -> None:
        nonlocal clock
        now = time.perf_counter()
        seconds[stage] = seconds.get(stage, 0.0) + round(now - clock, 3)
        clock = now

    detector = load_detector()
    lap("load")
    placed, n_dets = {}, 0
    for name, rows in views.items():
        where = out / VIEWS / name if name else out
        where.mkdir(parents=True, exist_ok=True)
        dets = detector(rows)
        n_dets += sum(len(d.detections) for d in dets)
        lap("detect")
        write_detections(where / "detections.jsonl", dets)
        placed[name] = observe.observe([r["image"] for r in rows], dets, _rgb, fixed=bool(name))
        if name:
            _jsonl(where / "observations.jsonl", placed[name])
        lap("observe")
    _jsonl(out / "observations.jsonl", placed[""] if "" in placed else fuse.fuse(placed))
    if "" not in placed:
        lap("fuse")
    # Read back as the events stage always reads its input, so this run and the CLIs agree.
    obs = track.read_observations(out / "observations.jsonl")
    found, summary = ev.detect(obs)
    # Restarts from the same observations (ninety/vision/restarts.py): kick-offs and set pieces with
    # their kind, merged in time; a possession change while the ball lies set is the restart's set-up.
    set_balls, restarted = restarts.detect(obs)
    found = restarts.merge(found, set_balls, restarted["dead_balls"])
    (out / "detected.jsonl").write_text("".join(json.dumps(e) + "\n" for e in found), encoding="utf-8")
    lap("events")
    rows = next(iter(views.values()))
    clip_id = rows[0]["clip"]
    tracked = tracked_frames.build(obs, clip_id)
    (out / "tracked.json").write_text(tracked_frames.text(tracked), encoding="utf-8")
    lap("tracked")
    seconds = {k: round(v, 3) for k, v in seconds.items()}
    report = {
        "clip": clip_id,
        "frames": len(rows),
        "views": sorted(n for n in views if n),
        "camera_ok": summary["frames_camera_ok"],
        "detections": n_dets,
        "events": summary["events"],
        "restarts": restarted["events"],
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
    ap.add_argument("clip", type=Path,
                    help=f"a folder holding only {INDEX} and {IMAGES}/, or only {VIEWS}/<name>/ with those")
    ap.add_argument("--checkpoint", required=True, help='our checkpoint name, e.g. ours-v4, or "coco"')
    ap.add_argument("--weights", type=Path, default=None, help="checkpoint file (not for coco)")
    ap.add_argument("--manifest", type=Path, default=None,
                    help="its training record (default: train-manifest.json beside the weights)")
    ap.add_argument("--resolution", type=int, default=None, help="default: the trained size")
    ap.add_argument("--batch", type=int, default=8)
    ap.add_argument("--tiles", action="store_true", help="detect on a 2 x 2 grid of overlapping tiles")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--echo", action="store_true",
                    help="also print run.json and each detected event, one JSON line each (the job's log)")
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
        return lambda rows: detect_rows(det, rows, label, field, a.batch, a.tiles)

    about = {
        "model": asdict(field),
        "weights_sha256": record.get("checkpoint_sha256"),
        "resolution": resolution,
        "tiles": a.tiles,
        "commit": os.environ.get("NINETY_COMMIT", "unknown"),
    }
    report = run(a.clip, a.out, load_detector, about)
    print(json.dumps({k: report[k] for k in ("clip", "frames", "events", "seconds")}))
    if a.echo:  # the Container Apps job holds no storage role, so its log carries the result
        print(json.dumps({"run": report}, separators=(",", ":")))
        for line in (a.out / "detected.jsonl").read_text(encoding="utf-8").splitlines():
            print(json.dumps({"detected": json.loads(line)}, separators=(",", ":")))


if __name__ == "__main__":
    main()
