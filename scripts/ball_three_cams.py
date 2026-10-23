"""Run docs/eval/ball-three-cams/PLAN.md's three ball sources on rendered clips (offline, on the Mac).

    # 1. the raw sources: broadcast (whole frame, per-frame fit) and the fused tactical views
    #    (tiles, fixed fit), one model load for all clips
    uv run --group vision python scripts/ball_three_cams.py raw <clip>... --checkpoint ours-freeze \\
        --weights <checkpoint_best_total.pth> \\
        [--tactical-checkpoint ours-tactical --tactical-weights <pth>] \\
        --out runs/ball3/<set>
    # 2. the variants the scorer reads, from the raw sources and the measured gate
    uv run python scripts/ball_three_cams.py variants --out runs/ball3/<set> \\
        --precision docs/eval/ball-three-cams/precision.json  # keys broadcast, tactical-<T>

Each stage is the live path's own module (detect, observe, fuse, ball_fuse); this only runs them in
order. Detection reads each picture's labels-free index (ninety.vision.frame_index, written here
first), never a frame file. `raw` writes, per tactical detector name T:

    <out>/broadcast/seed<N>.jsonl         observe's broadcast lines
    <out>/view-<V>-<T>/seed<N>.jsonl      each lens's own lines (observe --fixed)
    <out>/tactical-<T>/seed<N>.jsonl      the fused views' lines (fuse.fuse of those)

and `variants` writes, per T, `broadcast-<T>/`, `tactical-<T>/` (as is) and `fused-<T>/`, the lines
events would read for plan sources (a), (b) and (c).
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np


def _rgb(path: Path) -> np.ndarray:
    from PIL import Image

    return np.asarray(Image.open(path).convert("RGB"))


def _write(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        for r in rows:
            f.write(json.dumps(r, separators=(",", ":")) + "\n")


def _dets(path: Path, rows) -> None:
    from ninety.vision.detections import write_detections

    path.parent.mkdir(parents=True, exist_ok=True)
    write_detections(path, rows)


def _seed(clip: Path) -> int:
    return json.loads((clip / "clip.json").read_text())["seed"]


def raw(clips: list[Path], out: Path, detectors: dict[str, tuple[str, str]], broadcast_name: str) -> None:
    from ninety.vision import frame_index, fuse, observe
    from ninety.vision.detect import detect_rows, frame_rows, labels_for, trained_resolution
    from ninety.vision.model import load, model

    loaded = {}
    for name, (checkpoint, weights) in detectors.items():
        det = load(weights, resolution=trained_resolution(weights))
        loaded[name] = (det, labels_for(checkpoint, det.class_names), model(checkpoint))
    for clip in clips:
        seed, t0 = _seed(clip), time.perf_counter()
        laps: dict[str, float] = {}
        since = [t0]

        def lap(stage: str, laps: dict = laps, since: list = since) -> None:
            now = time.perf_counter()
            laps[stage] = round(laps.get(stage, 0.0) + now - since[0], 1)
            since[0] = now

        frame_index.write_index(clip)
        frame_index.write_indexes(clip)
        det, label, field = loaded[broadcast_name]
        rows = frame_rows(clip)
        dets = detect_rows(det, rows, label, field)
        lap("detect broadcast")
        _dets(out / "detections" / "broadcast" / f"seed{seed}.jsonl", dets)
        _write(out / "broadcast" / f"seed{seed}.jsonl",
               observe.observe([r["image"] for r in rows], dets, _rgb))
        lap("observe broadcast")
        for name, (det, label, field) in loaded.items():
            placed = {}
            for view, folder in frame_index.views(clip).items():
                rows = frame_rows(folder)
                dets = detect_rows(det, rows, label, field, tiles=True)
                lap(f"detect {name} tiles")
                _dets(out / "detections" / f"{view}-{name}" / f"seed{seed}.jsonl", dets)
                placed[view] = observe.observe([r["image"] for r in rows], dets, _rgb, fixed=True)
                _write(out / f"view-{view}-{name}" / f"seed{seed}.jsonl", placed[view])
                lap("observe fixed")
            _write(out / f"tactical-{name}" / f"seed{seed}.jsonl", fuse.fuse(placed))
        print(json.dumps({"seed": seed, "seconds": round(time.perf_counter() - t0, 1), "stages": laps}),
              flush=True)


def variants(out: Path, precision: Path) -> None:
    from ninety.vision import ball_fuse as bf
    from ninety.vision.track import read_observations

    m = json.loads(precision.read_text())
    bp = bf.Precision(m["broadcast"]["p99_m"], m["broadcast"]["rms_m"])
    for tac_dir in sorted(out.glob("tactical-*")):
        name = tac_dir.name.removeprefix("tactical-")
        tp = bf.Precision(m[tac_dir.name]["p99_m"], m[tac_dir.name]["rms_m"])
        for f in sorted(tac_dir.glob("seed*.jsonl")):
            tac, bro = read_observations(f), read_observations(out / "broadcast" / f.name)
            _write(out / "variants" / f"broadcast-{name}" / f.name, bf.broadcast_ball(tac, bro))
            _write(out / "variants" / f"tactical-{name}" / f.name, bf.tactical_only(tac))
            _write(out / "variants" / f"fused-{name}" / f.name, bf.fuse_ball(tac, bro, bp, tp))


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="The ball from three cameras, run offline on rendered clips.")
    ap.add_argument("stage", choices=["raw", "variants"])
    ap.add_argument("clips", nargs="*", type=Path)
    ap.add_argument("--checkpoint", default="ours-freeze")
    ap.add_argument("--weights")
    ap.add_argument("--tactical-checkpoint", default=None,
                    help="a second tactical detector, e.g. ours-tactical")
    ap.add_argument("--tactical-weights", default=None)
    ap.add_argument("--precision", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args(argv)
    if a.stage == "raw":
        dets = {a.checkpoint: (a.checkpoint, a.weights)}
        if a.tactical_checkpoint:
            dets[a.tactical_checkpoint] = (a.tactical_checkpoint, a.tactical_weights)
        raw(a.clips, a.out, dets, a.checkpoint)
    else:
        variants(a.out, a.precision)


if __name__ == "__main__":
    main()
