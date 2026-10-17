"""What a set of rendered clips holds for training the detector, and whether it is enough.

    uv run python -m ninety.vision.data_stats runs/dataset/train/* runs/dataset/test/* \
        --stride 5 --input 512x512 --report docs/eval/dataset-stats.json --floors

Reads only the saved files (`clip.json`, `frames.jsonl`), the way a training loader would. Per
split it counts clips, frames used after the stride, player and ball boxes, balls by visibility
group (the vision scorer's groups), ball size in pixels at the training input size, and clips per
render knob. `--floors` exits non-zero when the train split misses any of `FLOORS`.

Boxes with visibility 0 are not counted: nothing of the object is drawn, so it is not a label.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess
import sys
from collections import Counter
from fractions import Fraction
from pathlib import Path

from ninety.eval.vision_score import VISIBILITY_GROUPS, visibility_group

KNOBS = ("lighting", "weather", "kit_contrast", "occlusion", "camera_cut")

# Starting floors for the train split, set before any training data was counted. They are not
# proof of enough data: the learning curve (val recall against train clips) decides that.
FLOORS = {
    # domain randomization draws one camera, lighting and kit sample per clip, so variety is
    # counted in clips, not frames
    "clips": 150,
    # stride 5 at 25 fps keeps 5 frames a second; nearer frames are near-duplicates
    "frames": 7_500,
    "player_boxes": 75_000,
    # at most one ball per frame, so the ball is the scarce class
    "ball_boxes": 6_000,
    # PLAN.md: at least 5% of balls in shot less than half visible; and enough of them to learn
    "ball_mostly_hidden": 400,
    "ball_mostly_hidden_share": 0.05,
    # every lighting and weather value seen in enough distinct clips
    "clips_per_lighting": 15,
    "clips_per_weather": 15,
    # hard-case knobs, as a share of clips
    "kit_contrast_low_share": 0.20,
    "occlusion_crowded_share": 0.20,
}


def parse_input(s: str) -> tuple[int, int]:
    w, _, h = s.lower().partition("x")
    if not (w.isdigit() and h.isdigit()) or int(w) <= 0 or int(h) <= 0:
        raise argparse.ArgumentTypeError(f"input size must be WIDTHxHEIGHT, e.g. 512x512, not {s!r}")
    return int(w), int(h)


def _quantiles(xs: list[float]) -> dict:
    if not xs:
        return {"n": 0, "p05": None, "median": None, "p95": None}
    xs = sorted(xs)

    def q(p: float) -> float:
        # linear interpolation between closest ranks, so the median of an even sample is the mean
        # of the two middle values, not the upper one
        k = p * (len(xs) - 1)
        lo = int(k)
        hi = min(lo + 1, len(xs) - 1)
        return round(xs[lo] + (xs[hi] - xs[lo]) * (k - lo), 2)

    return {"n": len(xs), "p05": q(0.05), "median": q(0.5), "p95": q(0.95)}


def _empty() -> dict:
    return {
        "clips": 0,
        "seeds": set(),
        "frames": 0,
        "player_boxes": 0,
        "ball_boxes": 0,
        "ball_groups": Counter(),
        "ball_size_px": [],
        "player_height_px": [],
        "knobs": {k: Counter() for k in KNOBS},
    }


def clip_stats(clip_dir: Path, acc: dict, stride: int, input_size: tuple[int, int] | None) -> None:
    clip = json.loads((clip_dir / "clip.json").read_text())
    acc["clips"] += 1
    acc["seeds"].add(clip["seed"])
    for k in KNOBS:
        acc["knobs"][k][str(clip["params"][k])] += 1
    with open(clip_dir / "frames.jsonl") as f:
        for i, line in enumerate(f):
            if i % stride:
                continue
            fr = json.loads(line)
            cam = fr["camera"]
            sx, sy = (1.0, 1.0) if input_size is None else (
                input_size[0] / cam["width"],
                input_size[1] / cam["height"],
            )
            acc["frames"] += 1
            for p in fr["players"]:
                if p["bbox"] is not None and p["visibility"] > 0:
                    acc["player_boxes"] += 1
                    acc["player_height_px"].append((p["bbox"][3] - p["bbox"][1]) * sy)
            b = fr["ball"]
            if b["bbox"] is not None and b["visibility"] > 0:
                acc["ball_boxes"] += 1
                acc["ball_groups"][visibility_group(b["visibility"])] += 1
                x0, y0, x1, y1 = b["bbox"]
                acc["ball_size_px"].append(max((x1 - x0) * sx, (y1 - y0) * sy))


def _finish(acc: dict) -> dict:
    balls = acc["ball_boxes"]
    clips = acc["clips"]
    return {
        "clips": clips,
        "distinct_seeds": len(acc["seeds"]),
        "seeds": sorted(acc["seeds"]),
        "frames": acc["frames"],
        "player_boxes": acc["player_boxes"],
        "ball_boxes": balls,
        "ball_by_visibility": {g: acc["ball_groups"][g] for g in VISIBILITY_GROUPS},
        "ball_mostly_hidden_share": round(acc["ball_groups"]["mostly hidden"] / balls, 4) if balls else None,
        "ball_size_px": _quantiles(acc["ball_size_px"]),
        "player_height_px": _quantiles(acc["player_height_px"]),
        "clips_by": {k: dict(sorted(c.items())) for k, c in acc["knobs"].items()},
        "kit_contrast_low_share": round(acc["knobs"]["kit_contrast"]["low"] / clips, 4) if clips else None,
        "occlusion_crowded_share": round(acc["knobs"]["occlusion"]["crowded"] / clips, 4) if clips else None,
    }


def dataset_stats(clip_dirs: list[Path], stride: int = 5, input_size: tuple[int, int] | None = None) -> dict:
    if stride < 1:
        raise ValueError(f"stride must be at least 1, got {stride}")
    accs: dict[str, dict] = {}
    seen: dict[int, Path] = {}
    for d in map(Path, clip_dirs):
        clip = json.loads((d / "clip.json").read_text())
        # a seed counted twice inflates every floor: a directory passed twice, or the <seed>.rerender
        # copy that `ninety-render-check --determinism` leaves beside a clip
        if clip["seed"] in seen:
            raise ValueError(f"seed {clip['seed']} appears twice: {seen[clip['seed']]} and {d}")
        seen[clip["seed"]] = d
        clip_stats(d, accs.setdefault(clip["split"], _empty()), stride, input_size)
    return {split: _finish(acc) for split, acc in sorted(accs.items())}


def floor_failures(train: dict | None, lighting: tuple[str, ...], weather: tuple[str, ...]) -> list[str]:
    """Every floor the train split misses, as readable lines; empty when all are met."""
    if train is None:
        return ["no train clips"]
    fails = []
    for key in ("clips", "frames", "player_boxes", "ball_boxes"):
        if train[key] < FLOORS[key]:
            fails.append(f"{key}: {train[key]} < {FLOORS[key]}")
    hidden = train["ball_by_visibility"]["mostly hidden"]
    if hidden < FLOORS["ball_mostly_hidden"]:
        fails.append(f"ball_mostly_hidden: {hidden} < {FLOORS['ball_mostly_hidden']}")
    # shares are checked on the counts, never on the rounded shares in the report: 400 of 8,001 rounds
    # to 0.05 but is below it. Fraction, because 0.2 * 150 in floating point is just above 30.
    shares = {
        "ball_mostly_hidden_share": (hidden, train["ball_boxes"]),
        "kit_contrast_low_share": (train["clips_by"]["kit_contrast"].get("low", 0), train["clips"]),
        "occlusion_crowded_share": (train["clips_by"]["occlusion"].get("crowded", 0), train["clips"]),
    }
    for key, (num, den) in shares.items():
        if den == 0 or Fraction(num, den) < Fraction(str(FLOORS[key])):
            fails.append(f"{key}: {num}/{den} < {FLOORS[key]}")
    for knob, values, floor in (
        ("lighting", lighting, FLOORS["clips_per_lighting"]),
        ("weather", weather, FLOORS["clips_per_weather"]),
    ):
        for v in values:
            n = train["clips_by"][knob].get(v, 0)
            if n < floor:
                fails.append(f"{knob}={v}: {n} clips < {floor}")
    return fails


def _git_commit() -> str | None:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def main(argv: list[str] | None = None) -> None:
    from ninety.render.params import LIGHTING, WEATHER

    ap = argparse.ArgumentParser(description="Count what rendered clips hold for detector training.")
    ap.add_argument("clips", nargs="+", type=Path, help="clip directories")
    ap.add_argument("--stride", type=int, default=5, help="use every Nth frame (default 5: 5 fps)")
    ap.add_argument(
        "--input", type=parse_input, default=None, help="training input size WxH, to report ball pixels at it"
    )
    ap.add_argument("--report", type=Path, default=None, help="write the JSON report here")
    ap.add_argument("--floors", action="store_true", help="exit 1 if the train split misses a floor")
    a = ap.parse_args(argv)
    splits = dataset_stats(a.clips, a.stride, a.input)
    fails = floor_failures(splits.get("train"), LIGHTING, WEATHER)
    out = {
        "generated": dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "commit": _git_commit(),
        "stride": a.stride,
        "input": list(a.input) if a.input else None,
        "splits": splits,
        "floors": FLOORS,
        "train_floor_failures": fails,
    }
    text = json.dumps(out, indent=2, allow_nan=False)
    if a.report:
        a.report.parent.mkdir(parents=True, exist_ok=True)
        a.report.write_text(text + "\n")
    print(text)
    if a.floors and fails:
        sys.exit(1)


if __name__ == "__main__":
    main()
