"""Count what a set of rendered clips can teach a detector, per split, and whether it is enough.

    uv run ninety-data-stats runs/dataset --stride 5 --input 512x512 --out stats.json --floors

Reads only ``clip.json`` and ``frames.jsonl`` from each clip directory (labels, never images).
Box sizes are reported at the training input size, so a ball that shrinks below a few pixels is
visible in the numbers before any training run. ``--floors`` exits 1 when a split misses one of
``TRAIN_FLOORS`` or ``TEST_FLOORS``.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter, defaultdict
from collections.abc import Iterable
from pathlib import Path

from ninety.eval.vision_score import VISIBILITY_GROUPS, ground_truth, visibility_group
from ninety.render import params as render_params
from ninety.render.params import LIGHTING, WEATHER

KNOB_NAMES = ("lighting", "weather", "kit_contrast", "occlusion")

# Starting floors for the train split, set before any training clip was counted. Meeting them is
# not proof of enough data: the learning curve (test recall against train clips) decides that.
TRAIN_FLOORS = {
    # each seed draws one camera, lighting, kit and weather sample, so variety is counted in
    # distinct seeds, not frames
    "distinct_seeds": 150,
    # about 50 frames per 10 s clip at stride 5 (5 fps); nearer frames are near-duplicates
    "frames": 7_500,
    # 8 to 15 players in shot, so roughly 10 boxes a frame
    "player_boxes": 75_000,
    # at most one ball a frame, tiny: the scarce and hardest class
    "ball_boxes": 6_000,
    # the hard case, in number and in share (the share is PLAN.md's test-set floor)
    "ball_boxes_mostly_hidden_excluding_fully_hidden": 400,
    "ball_visibility_lt_0_5_share": 0.05,
    # every lighting and weather value drawn in enough distinct clips
    "clips_per_lighting": 15,
    "clips_per_weather": 15,
    # hard-case knobs must not be rare
    "kit_contrast_low_share": 0.20,
    "occlusion_crowded_share": 0.20,
}

# PLAN.md Goals: before the test set is frozen, at least 5% of its balls in shot are less than
# half visible. Same quantity and denominator as `ninety-render-check`: frames with the ball in
# shot (a bbox), fully hidden balls included.
TEST_FLOORS = {"ball_visibility_lt_0_5_share": 0.05}


def parse_input(text: str) -> tuple[int, int]:
    """``WIDTHxHEIGHT``, the image size the detector is trained at."""
    w, _, h = text.lower().partition("x")
    if not (w.isdigit() and h.isdigit()) or int(w) < 1 or int(h) < 1:
        raise argparse.ArgumentTypeError(f"input size must be WIDTHxHEIGHT, e.g. 512x512, not {text!r}")
    return int(w), int(h)


def percentile(values: list[float], q: float) -> float | None:
    """Linear-interpolated percentile, q in [0, 1]."""
    if not values:
        return None
    ordered = sorted(values)
    pos = q * (len(ordered) - 1)
    lo, hi = math.floor(pos), math.ceil(pos)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (pos - lo)


def _size(box: Iterable[float], sx: float, sy: float) -> float:
    """The larger side of a box after resizing to the training input; each axis has its scale."""
    x0, y0, x1, y1 = (float(v) for v in box)
    return max((x1 - x0) * sx, (y1 - y0) * sy)


def clip_stats(clip_dir: Path, *, stride: int, input_size: tuple[int, int] | None = None) -> dict:
    """Counts for one clip: frames used, boxes by class and visibility, ball sizes."""
    meta = json.loads((clip_dir / "clip.json").read_text())
    params = meta["params"]
    if input_size is None:
        sx = sy = 1.0
    else:
        sx, sy = input_size[0] / float(params["width"]), input_size[1] / float(params["height"])
    frames = [
        json.loads(line)
        for line in (clip_dir / "frames.jsonl").read_text().splitlines()
        if line.strip()
    ]
    used = [row for row in frames if int(row["frame"]) % stride == 0]
    labels = [lab for lab in ground_truth(used) if lab["visibility"] > 0]
    ball_visibility = Counter(
        visibility_group(lab["visibility"]) for lab in labels if lab["cls"] == "ball"
    )
    in_frame = [row["ball"] for row in used if (row.get("ball") or {}).get("bbox") is not None]
    return {
        "seed": meta["seed"],
        "ball_in_frame": len(in_frame),
        "ball_visibility_lt_0_5": sum(float(b.get("visibility", 1.0)) < 0.5 for b in in_frame),
        "split": meta["split"],
        "knobs": {name: params[name] for name in KNOB_NAMES},
        "frames": len(used),
        "player_boxes": sum(lab["cls"] == "player" for lab in labels),
        "ball_boxes": sum(lab["cls"] == "ball" for lab in labels),
        "ball_by_visibility": {g: ball_visibility.get(g, 0) for g in VISIBILITY_GROUPS},
        "ball_sizes_px": [_size(lab["bbox"], sx, sy) for lab in labels if lab["cls"] == "ball"],
    }


def _share(part: int, whole: int) -> float | None:
    return part / whole if whole else None


def summarise(clips: list[dict]) -> dict:
    """Merge per-clip counts into one split summary."""
    sizes = [s for clip in clips for s in clip["ball_sizes_px"]]
    ball_boxes = sum(c["ball_boxes"] for c in clips)
    by_visibility = {
        g: sum(c["ball_by_visibility"][g] for c in clips) for g in VISIBILITY_GROUPS
    }
    seeds = [c["seed"] for c in clips]
    if len(set(seeds)) != len(seeds):
        dupes = sorted(sd for sd, n in Counter(seeds).items() if n > 1)
        raise ValueError(f"seed counted more than once (a .rerender copy?): {dupes}")
    in_frame = sum(c["ball_in_frame"] for c in clips)
    lt_half = sum(c["ball_visibility_lt_0_5"] for c in clips)
    knobs: dict[str, dict[str, int]] = {}
    for name in KNOB_NAMES:
        knobs[name] = dict(sorted(Counter(str(c["knobs"][name]) for c in clips).items()))
    return {
        "clips": len(clips),
        "distinct_seeds": len(set(seeds)),
        "seeds": sorted(seeds),
        "frames": sum(c["frames"] for c in clips),
        "player_boxes": sum(c["player_boxes"] for c in clips),
        "ball_boxes": ball_boxes,
        "ball_by_visibility": by_visibility,
        "ball_in_frame": in_frame,
        # PLANNED quantity: the render check's name and denominator (ball in shot, v = 0 included)
        "ball_visibility_lt_0_5_share": round(lt_half / in_frame, 4) if in_frame else None,
        # training labels only: 0 < visibility < 0.5, a fully hidden ball has no box
        "ball_boxes_mostly_hidden_excluding_fully_hidden": by_visibility["mostly hidden"],
        "ball_size_px": {
            "p05": percentile(sizes, 0.05),
            "median": percentile(sizes, 0.5),
            "p95": percentile(sizes, 0.95),
        },
        "clips_by_knob": knobs,
        "kit_contrast_low_share": _share(knobs["kit_contrast"].get("low", 0), len(clips)),
        "occlusion_crowded_share": _share(knobs["occlusion"].get("crowded", 0), len(clips)),
    }


def dataset_stats(
    clip_dirs: Iterable[Path], *, stride: int = 5, input_size: tuple[int, int] | None = None
) -> dict:
    if stride < 1:
        raise ValueError(f"stride must be at least 1, got {stride}")
    by_split: dict[str, list[dict]] = defaultdict(list)
    for clip_dir in clip_dirs:
        stats = clip_stats(Path(clip_dir), stride=stride, input_size=input_size)
        by_split[stats["split"]].append(stats)
    return {
        "frame_stride": stride,
        "input_px": list(input_size) if input_size else None,
        "splits": {split: summarise(clips) for split, clips in sorted(by_split.items())},
    }


def _below(name: str, value: float | None, floor: float) -> list[str]:
    value = 0 if value is None else value
    return [f"{name}: {value:g} < {floor:g}"] if value < floor else []


def floor_failures(splits: dict) -> list[str]:
    """Every floor a split misses, as readable lines; empty when all are met."""
    fails = []
    train, test = splits.get("train"), splits.get("test")
    if train is None:
        fails.append("train: no clips")
    else:
        for key in ("distinct_seeds", "frames", "player_boxes", "ball_boxes"):
            fails += _below(f"train {key}", train[key], TRAIN_FLOORS[key])
        key = "ball_boxes_mostly_hidden_excluding_fully_hidden"
        fails += _below(f"train {key}", train[key], TRAIN_FLOORS[key])
        for key in ("ball_visibility_lt_0_5_share", "kit_contrast_low_share", "occlusion_crowded_share"):
            fails += _below(f"train {key}", train[key], TRAIN_FLOORS[key])
        for knob, values in (("lighting", LIGHTING), ("weather", WEATHER)):
            # only values the renderer can draw: a planned knob has no clips to count
            for v in render_params.PLANNED.get(knob, values):
                fails += _below(f"train {knob}={v} clips", train["clips_by_knob"][knob].get(v, 0),
                                TRAIN_FLOORS[f"clips_per_{knob}"])
    if test is None:
        fails.append("test: no clips")
    else:
        fails += _below("test ball_visibility_lt_0_5_share", test["ball_visibility_lt_0_5_share"],
                        TEST_FLOORS["ball_visibility_lt_0_5_share"])
    return fails


def find_clips(roots: Iterable[Path]) -> list[Path]:
    """Clip directories under the roots: any directory holding clip.json and frames.jsonl."""
    found = []
    for root in roots:
        candidates = [root, *sorted(p for p in root.rglob("*") if p.is_dir())]
        found += [d for d in candidates if (d / "clip.json").is_file() and (d / "frames.jsonl").is_file()]
    return found


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Count labelled boxes in rendered clips, per split.")
    ap.add_argument("roots", nargs="+", type=Path, help="clip directories or folders of them")
    ap.add_argument("--stride", type=int, default=5, help="keep every Nth frame (default 5, i.e. 5 fps)")
    ap.add_argument("--input", type=parse_input, default=None,
                    help="training input size WIDTHxHEIGHT for ball pixels (default: as rendered)")
    ap.add_argument("--out", type=Path, help="write the report here instead of stdout")
    ap.add_argument("--floors", action="store_true", help="exit 1 if a split misses a floor")
    args = ap.parse_args(argv)
    report = dataset_stats(find_clips(args.roots), stride=args.stride, input_size=args.input)
    report["floors"] = {"train": TRAIN_FLOORS, "test": TEST_FLOORS}
    report["floor_failures"] = fails = floor_failures(report["splits"])
    text = json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n"
    if args.out:
        args.out.write_text(text)
    else:
        print(text, end="")
    if args.floors and fails:
        print("\n".join(["floors missed:", *fails]), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
