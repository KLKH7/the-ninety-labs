"""Precompute the live path on a whole match: split at the camera cuts, run the pieces in parallel.

    uv run --group vision python -m ninety.vision.precompute <clip> \\
        --checkpoint <name in its train-manifest.json> --weights <checkpoint_best_total.pth> \\
        --out <dir> [--workers N]

The demo replays events the pipeline detected beforehand (docs/TEAM.md, R3: one machine is about
150 times slower than real time, so a whole condensed match cannot run while a viewer watches).
This is the same live path as ninety.vision.live_job on the same input (a folder holding only
`index.jsonl` and `images/`, checked the same way, the checkpoint against its training record),
only spread over the machine's cores:

1. Every frame's thumbnail goes to ninety.vision.pitch.shot_starts, which finds the cuts.
2. Every shot is a piece, and a shot longer than a worker's share of the match is cut into equal
   parts, none shorter than MIN_PIECE frames. The camera fit starts afresh at those parts, as it
   does at a clip's first frame; a camera-cut piece needs no restart it would not have had anyway.
3. Each worker process loads the model once and, per piece, detects and places it on the pitch
   (detect, observe), as live_job does for a whole clip. Pieces outnumber workers when the shots
   do, and the pool hands each worker the next piece as it finishes one.
4. The pieces' observations are joined in frame order, and events (ninety.vision.events) and the
   tracked frames (ninety.vision.tracked_frames) are found once on the whole match, as live_job
   finds them on a whole clip. Tracks and possession cross the joins exactly as they cross a cut
   in an unsplit run.

Writes to `--out` what live_job writes (detections.jsonl, observations.jsonl, detected.jsonl,
tracked.json, run.json); run.json also says how the match was split and each piece's time.
"""

from __future__ import annotations

import argparse
import json
import os
import time
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict
from itertools import pairwise
from pathlib import Path

from ninety.vision import events as ev
from ninety.vision import observe, pitch, track, tracked_frames
from ninety.vision.detect import FINETUNE_CONFIG, detect_rows, labels_for
from ninety.vision.detections import FrameDetections, write_detections
from ninety.vision.live_job import _jsonl, _rgb, check_views, verify_checkpoint
from ninety.vision.model import load, model

GB = 1 << 30
WORKER_RAM = 2 * GB  # one worker's model, images in hand and results, with headroom (design)
# A long shot is split for speed, never into pieces shorter than this: the camera fit anchors its
# gantry search on every 25th frame (pitch.fit_clip), so a piece keeps at least 10 anchors (design).
MIN_PIECE = 250

Detector = Callable[[list[dict]], list[FrameDetections]]


def pieces(n_frames: int, starts: list[int], workers: int,
           min_frames: int = MIN_PIECE) -> list[tuple[int, int]]:
    """Frame index ranges [first, last) covering 0..n_frames: every shot (`starts`, which holds 0)
    is a piece, and a shot longer than a worker's share (n_frames / workers) is cut into equal
    parts of that share or more, never shorter than `min_frames`."""
    if n_frames == 0:
        return []
    starts = sorted(set(starts) | {0})
    share = n_frames / max(1, workers)
    out = []
    for a, b in pairwise([*starts, n_frames]):
        k = max(1, min(round((b - a) / share), (b - a) // min_frames))
        cuts = [a + round(i * (b - a) / k) for i in range(k)] + [b]
        out += list(pairwise(cuts))
    return out


def worker_count(n_pieces: int, cores: int | None = None, free_ram: int | None = None) -> int:
    """As many workers as pieces, physical cores less two (the camera fit runs on one core each)
    and free memory at WORKER_RAM each allow, and at least one."""
    cores = cores if cores is not None else max(1, (os.cpu_count() or 2) // 2)
    by_ram = free_ram // WORKER_RAM if free_ram is not None else n_pieces
    return max(1, min(n_pieces, max(1, cores - 2), by_ram))


def free_memory() -> int | None:
    """Bytes of free physical memory, or None where it cannot be read."""
    try:
        import psutil

        return int(psutil.virtual_memory().available)
    except ImportError:
        return None


def thumbnails(rows: list[dict]) -> list:
    return [pitch.thumbnail(_rgb(r["image"])) for r in rows]


def place_piece(rows: list[dict], detector: Detector) -> tuple[list[FrameDetections], list[dict], dict]:
    """Detect and place one piece on the pitch; returns its detections, observations and times."""
    t0 = time.perf_counter()
    dets = detector(rows)
    t1 = time.perf_counter()
    obs = observe.observe([r["image"] for r in rows], dets, _rgb)
    t2 = time.perf_counter()
    return dets, obs, {"frames": len(rows), "detect": round(t1 - t0, 3), "observe": round(t2 - t1, 3)}


# The worker processes: each loads the model once (its initializer), then places pieces.
_DETECTOR: Detector | None = None


def _init_worker(weights: str | None, checkpoint: str, resolution: int, batch: int, threads: int) -> None:
    global _DETECTOR
    import torch

    torch.set_num_threads(threads)
    det = load(weights, resolution=resolution)
    label = labels_for(checkpoint, det.class_names)
    field = model(checkpoint)
    _DETECTOR = lambda rows: detect_rows(det, rows, label, field, batch)  # noqa: E731


def _place_in_worker(rows: list[dict]):
    return place_piece(rows, _DETECTOR)


def run(clip: Path, out: Path, place: Callable[[list[list[dict]]], list], workers: int,
        about: dict | None = None) -> dict:
    """Split `clip` at its cuts (and long shots into parts) for `workers` workers, place the pieces
    with `place` (a list of pieces in, a list of place_piece results out, in order), join them and
    find the events once.
    `place` is passed in so tests run in one process with a stand-in detector."""
    views = check_views(clip)
    if "" not in views:
        raise SystemExit(f"{clip}: precompute takes a single-camera clip; run live_job on views")
    rows = views[""]
    out.mkdir(parents=True, exist_ok=True)
    wall = time.perf_counter()
    starts = pitch.shot_starts(thumbnails(rows))
    split = pieces(len(rows), starts, workers)
    t_split = time.perf_counter() - wall
    placed = place([rows[a:b] for a, b in split])
    dets = [d for p in placed for d in p[0]]
    obs = [o for p in placed for o in p[1]]
    write_detections(out / "detections.jsonl", dets)
    _jsonl(out / "observations.jsonl", obs)
    t_events = time.perf_counter()
    merged = track.read_observations(out / "observations.jsonl")  # as the events stage reads it
    found, summary = ev.detect(merged)
    (out / "detected.jsonl").write_text("".join(json.dumps(e) + "\n" for e in found), encoding="utf-8")
    clip_id = rows[0]["clip"]
    tracked = tracked_frames.build(merged, clip_id)
    (out / "tracked.json").write_text(tracked_frames.text(tracked), encoding="utf-8")
    now = time.perf_counter()
    report = {
        "clip": clip_id,
        "frames": len(rows),
        "shots": len(starts),
        "pieces": [{"first": rows[a]["frame"], "last": rows[b - 1]["frame"], **p[2]}
                   for (a, b), p in zip(split, placed, strict=True)],
        "workers": workers,
        "camera_ok": summary["frames_camera_ok"],
        "detections": sum(len(d.detections) for d in dets),
        "events": summary["events"],
        "named": summary["named"],
        "seconds": {"split": round(t_split, 3), "events_and_tracked": round(now - t_events, 3),
                    "wall": round(now - wall, 3)},
        "cpus": os.cpu_count(),
        **(about or {}),
    }
    (out / "run.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Precompute the live path on a whole match, in parallel.")
    ap.add_argument("clip", type=Path, help="a folder holding only index.jsonl and images/")
    ap.add_argument("--checkpoint", required=True, help='its name in its training record, or "coco"')
    ap.add_argument("--weights", type=Path, default=None, help="checkpoint file (not for coco)")
    ap.add_argument("--manifest", type=Path, default=None,
                    help="its training record (default: train-manifest.json beside the weights)")
    ap.add_argument("--resolution", type=int, default=None, help="default: the trained size")
    ap.add_argument("--batch", type=int, default=8)
    ap.add_argument("--workers", type=int, default=None,
                    help="default: physical cores less two, and what free memory allows")
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args(argv)
    if (a.checkpoint == "coco") != (a.weights is None):
        ap.error("--weights is required for our checkpoints and not allowed for coco")
    check_views(a.clip)  # before hashing or loading anything
    if a.weights:
        record = verify_checkpoint(a.weights, a.checkpoint, a.manifest)
        resolution = a.resolution or record["config"]["resolution"]
    else:
        record, resolution = {}, a.resolution or json.loads(FINETUNE_CONFIG.read_text())["resolution"]
    cap = a.workers or worker_count(10**9, free_ram=free_memory())
    threads = max(1, (os.cpu_count() or 2) // cap)

    def place(chunks: list[list[dict]]) -> list:
        args = (str(a.weights) if a.weights else None, a.checkpoint, resolution, a.batch, threads)
        with ProcessPoolExecutor(max_workers=min(cap, len(chunks)), initializer=_init_worker,
                                 initargs=args) as pool:
            return list(pool.map(_place_in_worker, chunks))

    about = {"model": asdict(model(a.checkpoint)), "weights_sha256": record.get("checkpoint_sha256"),
             "resolution": resolution, "threads_per_worker": threads,
             "commit": os.environ.get("NINETY_COMMIT", "unknown")}
    report = run(a.clip, a.out, place, cap, about)
    print(json.dumps({k: report[k] for k in ("clip", "frames", "shots", "workers", "camera_ok",
                                              "events", "seconds")}))


if __name__ == "__main__":
    main()
