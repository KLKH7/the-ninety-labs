"""How far a detected box's ground point lies from the true one, in pixels: the precision that sets
the merge gate of ninety/vision/fuse.py (docs/eval/fuse-gate.md).

    uv run python -m ninety.eval.foot_precision --clips <render run>/train --detections <dir> \\
        --seeds 108 109 110 --out docs/eval/fuse-gate.json

Grading data, read offline: each clip's frames.jsonl. A frozen test seed is refused.

Detections are matched to labels by the scorer's own rule (ninety.eval.vision_score.match, score
0.5). For each matched player, the error is the box's bottom centre (where observe puts his feet)
minus the label's `foot_px` (where the renderer projects his ground point), across and down, each
over the label box's height, so one number serves a 27 px far player and a 78 px near one. For each
matched ball, the box centre minus the label's `center_px`, over the label box's width.

The statistic was chosen before the numbers were read: the 99th percentile of the absolute error,
per axis and class (fuse.py's gate is the two detections' 99th-percentile ellipses, side by side).

A view of the tactical camera (`--view tac-l`) reads `seed<N>/views/<view>/frames.jsonl` and
`seed<N>-<view>.jsonl`, and adds the signed bias: per class and axis, the least-squares line
`a + b*c` through the signed errors, where `c` is the ground pixel's column from the image centre as
a share of half the width, and the 99th percentile of what that line leaves (docs/eval/fuse-gate.md,
the tactical re-measurement, which fixed this form before measuring).

    uv run python -m ninety.eval.foot_precision --clips runs/tactical1/val \
        --detections runs/tactical1/score/validation/ours-tactical --view tac-l --seeds 117 119 ...
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from ninety.eval.attribution_derive import refused
from ninety.eval.vision_score import DEFAULT_THRESHOLD, flatten, ground_truth, load_jsonl, match

PERCENTILE = 99


def errors(frames: list[dict], detections: list[dict], width: float | None = None
           ) -> dict[str, list[tuple[float, ...]]]:
    """Each matched detection's (across, down) error, as a share of its label's size; with the
    image `width`, a third value: the ground pixel's column from the centre, as a share of half."""
    labels = ground_truth(frames)
    by_frame = {int(f["frame"]): f for f in frames}
    dets = [d for d in flatten(detections) if float(d.get("score", 0)) >= DEFAULT_THRESHOLD]
    out: dict[str, list[tuple[float, float]]] = {"player": [], "ball": []}
    for p in match(labels, dets):
        lab, d = labels[p["truth"]], dets[p["detection"]]
        x0, y0, x1, y1 = d["bbox"]
        lx0, ly0, lx1, ly1 = lab["bbox"]
        row = by_frame[lab["frame"]]
        if p["cls"] == "player":
            truth = next((q for q in row["players"] if q.get("bbox") == lab["bbox"]), None)
            if truth is None or truth.get("foot_px") is None or ly1 <= ly0:
                continue
            fu, fv = truth["foot_px"]
            h = ly1 - ly0
            out["player"].append((((x0 + x1) / 2 - fu) / h, (y1 - fv) / h)
                                 + _column((x0 + x1) / 2, width))
        else:
            cu, cv = row["ball"].get("center_px") or ((lx0 + lx1) / 2, (ly0 + ly1) / 2)
            w = lx1 - lx0
            if w > 0:
                out["ball"].append((((x0 + x1) / 2 - cu) / w, ((y0 + y1) / 2 - cv) / w)
                                   + _column((x0 + x1) / 2, width))
    return out


def _column(u: float, width: float | None) -> tuple[float, ...]:
    return () if width is None else ((u - width / 2) / (width / 2),)


def bias(errs: list[tuple[float, float, float]]) -> dict:
    """Per axis, the least-squares line a + b*c through the signed errors, and the 99th percentile
    of the absolute error left after it."""
    e = np.array(errs, dtype=float).reshape(-1, 3)
    A = np.c_[np.ones(len(e)), e[:, 2]]
    out = {}
    for k, axis in enumerate(("across", "down")):
        (a, b), *_ = np.linalg.lstsq(A, e[:, k], rcond=None)
        left = np.abs(e[:, k] - A @ (a, b))
        out[axis] = {"a": round(float(a), 4), "b": round(float(b), 4),
                     "mean_signed": round(float(e[:, k].mean()), 4),
                     f"p{PERCENTILE}_after": round(float(np.percentile(left, PERCENTILE)), 4)}
    return out


def summarise(errs: dict[str, list[tuple[float, float]]]) -> dict:
    out = {}
    for cls, e in errs.items():
        a = np.abs(np.array([r[:2] for r in e], dtype=float).reshape(-1, 2))
        out[cls] = {"n": len(e)} | ({
            f"p{PERCENTILE}_across": round(float(np.percentile(a[:, 0], PERCENTILE)), 4),
            f"p{PERCENTILE}_down": round(float(np.percentile(a[:, 1], PERCENTILE)), 4),
            "median_across": round(float(np.median(a[:, 0])), 4),
            "median_down": round(float(np.median(a[:, 1])), 4),
        } if len(e) else {}) | ({"bias": bias(e)} if len(e) and len(e[0]) == 3 else {})
    return out


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Measure detected ground points against the labels.")
    ap.add_argument("--clips", type=Path, required=True, help="folder of seed<N>/ clips")
    ap.add_argument("--detections", type=Path, required=True, help="folder of seed<N>.jsonl")
    ap.add_argument("--seeds", type=int, nargs="+", required=True)
    ap.add_argument("--view", help="a tactical lens (tac-l, tac-r): its frames and detections, and the bias")
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args(argv)
    errs: dict[str, list] = {"player": [], "ball": []}
    for seed in a.seeds:
        if refused(seed):
            raise SystemExit(f"test seed {seed}: the test clips are for the final score only")
        clip = a.clips / f"seed{seed}" / ("views/" + a.view if a.view else "")
        frames = load_jsonl(clip / "frames.jsonl")
        dets = load_jsonl(a.detections / (f"seed{seed}-{a.view}.jsonl" if a.view else f"seed{seed}.jsonl"))
        width = json.loads((clip / "clip.json").read_text())["params"]["width"] if a.view else None
        run = {int(r["frame"]) for r in dets}
        for cls, e in errors([f for f in frames if int(f["frame"]) in run], dets, width).items():
            errs[cls] += e
    report = {"seeds": a.seeds, **({"view": a.view} if a.view else {}),
              "percentile": PERCENTILE, "threshold": DEFAULT_THRESHOLD,
              "detections": a.detections.name, **summarise(errs)}
    a.out.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
