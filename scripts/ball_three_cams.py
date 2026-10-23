"""Run the live path's stages on rendered clips offline, for docs/eval/ball-three-cams/PLAN.md.

    # 1. the raw sources: broadcast (whole frame, per-frame fit) and the fused tactical views
    #    (tiles, fixed fit), one model load for all clips
    uv run --group vision python scripts/ball_three_cams.py raw <clip>... --checkpoint ours-freeze \\
        --weights <checkpoint_best_total.pth> \\
        [--tactical-checkpoint ours-tactical --tactical-weights <pth>] \\
        --out runs/ball3/<set>

Each stage is the live path's own module (detect, observe, fuse); this only runs them in
order. Detection reads each picture's labels-free index (ninety.vision.frame_index, written here
first), never a frame file. `raw` writes, per tactical detector name T:

    <out>/broadcast/seed<N>.jsonl         observe's broadcast lines
    <out>/view-<V>-<T>/seed<N>.jsonl      each lens's own lines (observe --fixed)
    <out>/tactical-<T>/seed<N>.jsonl      the fused views' lines (fuse.fuse of those)

The ball is scored from `broadcast/` (ninety.eval.ball_sources); the tactical folders are for the
players, and for the fixed lens's camera trust test (each lens's own lines).
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


def raw(clips: list[Path], out: Path, detectors: dict[str, tuple[str, str]], broadcast_name: str,
        tactical: bool = True) -> None:
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
        for name, (det, label, field) in loaded.items() if tactical else ():
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


def rejudge(src: Path, out: Path) -> None:
    """Every saved observations file under `src` judged again by today's trust test (observe.place
    with its camera kind's band, then observe.agree), cameras kept; the views fused again. No
    detection and no fit runs."""
    from ninety.vision import fuse, observe
    from ninety.vision.track import read_observations

    def judged(path: Path) -> list[dict]:
        rows = read_observations(path)
        band = observe.FIXED_HEIGHT_BAND if rows and rows[0].get("fixed") else observe.HEIGHT_BAND
        return observe.agree([observe.place(r, band) for r in rows])

    for f in sorted((src / "broadcast").glob("seed*.jsonl")):
        _write(out / "broadcast" / f.name, judged(f))
    for tac in sorted(src.glob("tactical-*")):
        name = tac.name.removeprefix("tactical-")
        for f in sorted(tac.glob("seed*.jsonl")):
            placed = {}
            for d in sorted(src.glob(f"view-*-{name}")):
                view = d.name.removeprefix("view-").removesuffix(f"-{name}")
                placed[view] = judged(d / f.name)
                _write(out / d.name / f.name, placed[view])
            if placed:  # a run from before each lens's lines were kept has none to fuse
                _write(out / tac.name / f.name, fuse.fuse(placed))


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="The ball from three cameras, run offline on rendered clips.")
    ap.add_argument("stage", choices=["raw", "rejudge"])
    ap.add_argument("clips", nargs="*", type=Path)
    ap.add_argument("--checkpoint", default="ours-freeze")
    ap.add_argument("--weights")
    ap.add_argument("--tactical-checkpoint", default=None,
                    help="a second tactical detector, e.g. ours-tactical")
    ap.add_argument("--tactical-weights", default=None)
    ap.add_argument("--skip-tactical", action="store_true", help="the broadcast only")
    ap.add_argument("--src", type=Path, help="rejudge: the raw run's folder")
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args(argv)
    if a.stage == "rejudge":
        rejudge(a.src, a.out)
        return
    dets = {a.checkpoint: (a.checkpoint, a.weights)}
    if a.tactical_checkpoint:
        dets[a.tactical_checkpoint] = (a.tactical_checkpoint, a.tactical_weights)
    raw(a.clips, a.out, dets, a.checkpoint, not a.skip_tactical)


if __name__ == "__main__":
    main()
