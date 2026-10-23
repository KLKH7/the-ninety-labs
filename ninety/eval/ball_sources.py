"""Where each source puts the ball: the measures of docs/eval/ball-three-cams/PLAN.md.

    # the gate's precision, validation clips only
    uv run python -m ninety.eval.ball_sources precision --clips <dir> --obs <dir> --seeds ... --out <json>
    # each variant's recall and precision by zone
    uv run python -m ninety.eval.ball_sources score --clips <dir> --obs <dir> --seeds ... \\
        --variants broadcast tactical fused --out <json>

Grading data, read offline: each clip's frames.jsonl (the broadcast's, at the clip's top level) and
each view's (`views/<name>/frames.jsonl`). Observations are read from `<obs>/<variant>/seed<N>.jsonl`:
`broadcast` and `tactical` (the raw sources, for `precision`) are observe's broadcast lines and the
fused views' lines; for `score`, each variant's file holds the lines the events stage would read
(ninety.vision.ball_fuse: `broadcast_ball`, `tactical_only`, `fuse_ball`).

`precision`: each source's ball is matched to its own picture's label by the pixel scorer's rule
(vision_score.match: centre within 5 px, score 0.5); the error is the pitch distance between where
the source placed it and the true ball, for balls on the ground (true height under IN_AIR_Z).
Reports the 99th percentile and the root mean square per source. A test seed is refused.

`score`: per frame, the ball the tracker takes (track.ball_path) against the true ball's ground
position, strict 1.0 m and lenient 2.0 m (the event scorer's radii), by zone across the pitch and by
height, with Wilson 95% intervals.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np

from ninety.eval.attribution_derive import refused
from ninety.eval.event_score import LENIENT_M, STRICT_M, wilson
from ninety.eval.vision_score import DEFAULT_THRESHOLD, IN_AIR_Z, ground_truth, load_jsonl, match
from ninety.vision import track

PITCH = (105.0, 68.0)
ZONES = (("near", 0.0, 68.0 / 3), ("centre", 68.0 / 3, 2 * 68.0 / 3), ("far", 2 * 68.0 / 3, 68.0 + 1e-9))
RADII = {"strict": STRICT_M, "lenient": LENIENT_M}
PERCENTILE = 99


def zone(y: float) -> str:
    return next(name for name, lo, hi in ZONES if lo <= y < hi)


def on_pitch(ball: dict) -> bool:
    return ball.get("x") is not None and 0 <= ball["x"] <= PITCH[0] and 0 <= ball["y"] <= PITCH[1]


def _frames(path: Path) -> dict[int, dict]:
    return {int(r["frame"]): r for r in load_jsonl(path)}


def _errors(truth: dict[int, dict], balls: list[dict]) -> list[float]:
    """Pitch errors of balls matched in pixels to their picture's label. `balls` are dicts with
    frame, bbox, score, x, y."""
    frames = [truth[f] for f in sorted({b["frame"] for b in balls}) if f in truth]
    labels = [lab for lab in ground_truth(frames) if lab["cls"] == "ball"]
    dets = [{"frame": b["frame"], "cls": "ball", "bbox": b["bbox"], "score": b["score"], "x": b["x"],
             "y": b["y"]} for b in balls if b.get("x") is not None]
    out = []
    for p in match(labels, dets, DEFAULT_THRESHOLD):
        tb = truth[p["frame"]]["ball"]
        if tb.get("z", 0.0) < IN_AIR_Z:
            d = [x for x in dets if x["score"] >= DEFAULT_THRESHOLD][p["detection"]]
            out.append(math.dist((d["x"], d["y"]), (tb["x"], tb["y"])))
    return out


def precision(clips: Path, obs: Path, seeds: list[int]) -> dict:
    """Each source's error: `broadcast`, and each `tactical-<detector>` folder under `obs` (the
    fused views; `tactical` alone when it is named so)."""
    tactical = sorted(p.name for p in obs.iterdir() if p.is_dir() and p.name.startswith("tactical"))
    errs: dict[str, list[float]] = {"broadcast": []} | {t: [] for t in tactical}
    for seed in seeds:
        if refused(seed):
            raise SystemExit(f"test seed {seed}: the gate is measured on validation clips only")
        clip = clips / f"seed{seed}"
        rows = load_jsonl(obs / "broadcast" / f"seed{seed}.jsonl")
        balls = [b | {"frame": r["frame"]} for r in rows if r["camera"]["ok"] for b in r["ball"]]
        errs["broadcast"] += _errors(_frames(clip / "frames.jsonl"), balls)
        for t in tactical:
            rows = load_jsonl(obs / t / f"seed{seed}.jsonl")
            for view in sorted(p.name for p in (clip / "views").iterdir() if p.is_dir()):
                balls = [b | {"frame": r["frame"]} for r in rows if r["camera"]["ok"] for b in r["ball"]
                         if b.get("view") == view]
                errs[t] += _errors(_frames(clip / "views" / view / "frames.jsonl"), balls)
    out = {"seeds": seeds, "percentile": PERCENTILE, "in_air_z": IN_AIR_Z}
    for k, e in errs.items():
        a = np.array(e)
        out[k] = {"n": len(e)} | ({"p99_m": round(float(np.percentile(a, PERCENTILE)), 3),
                                   "rms_m": round(float(np.sqrt(np.mean(a * a))), 3),
                                   "median_m": round(float(np.median(a)), 3)} if len(e) else {})
    return out


def _rate(k: int, n: int) -> dict:
    return {"k": k, "n": n, "rate": round(k / n, 4) if n else None, "wilson95": wilson(k, n)}


def score_clip(truth: dict[int, dict], rows: list[dict]) -> dict:
    """Counts for one clip and variant: per group, frames with the true ball on the pitch, hits per
    radius, the variant's balls, and its balls within each radius."""
    picked = {p.frame: p for p in track.ball_path(rows)}
    c: dict = {}

    def add(group: str, key: str) -> None:
        c.setdefault(group, {}).setdefault(key, 0)
        c[group][key] += 1

    for f, fr in truth.items():
        tb, p = fr["ball"], picked.get(f)
        groups = ["all"]
        if on_pitch(tb):
            groups += [zone(tb["y"]), "in the air" if tb.get("z", 0.0) >= IN_AIR_Z else "on the ground"]
        d = math.dist((p.x, p.y), (tb["x"], tb["y"])) if p is not None and on_pitch(tb) else None
        for g in groups:
            if on_pitch(tb):
                add(g, "frames")
            if p is not None:
                add(g, "reported")
            for rule, r in RADII.items():
                if d is not None and d <= r:
                    add(g, f"hit_{rule}")
    return c


def score(clips: Path, obs: Path, seeds: list[int], variants: list[str]) -> dict:
    out: dict = {"seeds": seeds, "radii_m": RADII, "zones": {n: [lo, min(hi, 68.0)] for n, lo, hi in ZONES},
                 "variants": {}}
    for v in variants:
        total: dict = {}
        for seed in seeds:
            truth = _frames(clips / f"seed{seed}" / "frames.jsonl")
            for g, cnt in score_clip(truth, track.read_observations(obs / v / f"seed{seed}.jsonl")).items():
                for k, n in cnt.items():
                    total.setdefault(g, {}).setdefault(k, 0)
                    total[g][k] += n
        res = {}
        for g, cnt in total.items():
            res[g] = {f"{m}_{rule}": _rate(cnt.get(f"hit_{rule}", 0), cnt.get(den, 0))
                      for rule in RADII for m, den in (("recall", "frames"), ("precision", "reported"))}
        out["variants"][v] = res
    return out


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Score where each source puts the ball.")
    ap.add_argument("mode", choices=["precision", "score"])
    ap.add_argument("--clips", type=Path, required=True)
    ap.add_argument("--obs", type=Path, required=True)
    ap.add_argument("--seeds", type=int, nargs="+", required=True)
    ap.add_argument("--variants", nargs="+", default=["broadcast", "tactical", "fused"])
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args(argv)
    report = precision(a.clips, a.obs, a.seeds) if a.mode == "precision" else score(
        a.clips, a.obs, a.seeds, a.variants)
    a.out.write_text(json.dumps(report, indent=2) + "\n")
    print(a.out)


if __name__ == "__main__":
    main()
