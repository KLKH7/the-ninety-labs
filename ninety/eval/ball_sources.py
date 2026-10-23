"""Where the live path puts the ball on the pitch: the measures of docs/eval/ball-three-cams/PLAN.md.

    uv run python -m ninety.eval.ball_sources --clips <dir> --obs <dir> --seeds ... \\
        --variants broadcast --out <json>

Grading data, read offline: each clip's frames.jsonl (the broadcast's, at the clip's top level).
Observations are read from `<obs>/<variant>/seed<N>.jsonl`, each the lines the events stage reads
(observe's broadcast lines for the ball; another variant, such as the fused tactical views or
#226's flight heights, only as context).

Per frame, the ball the tracker takes (track.ball_path) against the true ball's ground position:
recall and precision within 1.0 m (strict) and 2.0 m (lenient), the event scorer's radii, and
coverage (a ball placed at all), by zone across the pitch and by height, with Wilson 95% intervals.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from ninety.eval.event_score import LENIENT_M, STRICT_M, wilson
from ninety.eval.vision_score import IN_AIR_Z, load_jsonl
from ninety.vision import track

PITCH = (105.0, 68.0)
ZONES = (("near", 0.0, 68.0 / 3), ("centre", 68.0 / 3, 2 * 68.0 / 3), ("far", 2 * 68.0 / 3, 68.0 + 1e-9))
RADII = {"strict": STRICT_M, "lenient": LENIENT_M}


def zone(y: float) -> str:
    return next(name for name, lo, hi in ZONES if lo <= y < hi)


def on_pitch(ball: dict) -> bool:
    return ball.get("x") is not None and 0 <= ball["x"] <= PITCH[0] and 0 <= ball["y"] <= PITCH[1]


def _frames(path: Path) -> dict[int, dict]:
    return {int(r["frame"]): r for r in load_jsonl(path)}


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
                if on_pitch(tb):
                    add(g, "placed")
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
            res[g]["coverage"] = _rate(cnt.get("placed", 0), cnt.get("frames", 0))
        out["variants"][v] = res
    return out


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Score where the live path puts the ball.")
    ap.add_argument("--clips", type=Path, required=True)
    ap.add_argument("--obs", type=Path, required=True)
    ap.add_argument("--seeds", type=int, nargs="+", required=True)
    ap.add_argument("--variants", nargs="+", default=["broadcast"])
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args(argv)
    report = score(a.clips, a.obs, a.seeds, a.variants)
    a.out.write_text(json.dumps(report, indent=2) + "\n")
    print(a.out)


if __name__ == "__main__":
    main()
