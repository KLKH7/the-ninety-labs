"""Count what a set of rendered clips can teach a detector, per split.

Reads only ``clip.json`` and ``frames.jsonl`` from each clip directory (labels, never images).
Box sizes are reported at the training resolution, so a ball that shrinks below a few pixels is
visible in the numbers before any training run.
"""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter, defaultdict
from collections.abc import Iterable
from pathlib import Path

from ninety.eval.vision_score import VISIBILITY_GROUPS, ground_truth, visibility_group

KNOB_NAMES = ("lighting", "weather", "kit_contrast", "occlusion")


def percentile(values: list[float], q: float) -> float | None:
    """Linear-interpolated percentile, q in [0, 1]."""
    if not values:
        return None
    ordered = sorted(values)
    pos = q * (len(ordered) - 1)
    lo, hi = math.floor(pos), math.ceil(pos)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (pos - lo)


def _size(box: Iterable[float], scale: float) -> float:
    x0, y0, x1, y1 = (float(v) for v in box)
    return max(x1 - x0, y1 - y0) * scale


def clip_stats(clip_dir: Path, *, stride: int, train_width: int) -> dict:
    """Counts for one clip: frames used, boxes by class and visibility, ball sizes."""
    meta = json.loads((clip_dir / "clip.json").read_text())
    params = meta["params"]
    scale = train_width / float(params["width"])
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
    return {
        "seed": meta["seed"],
        "split": meta["split"],
        "knobs": {name: params[name] for name in KNOB_NAMES},
        "frames": len(used),
        "player_boxes": sum(lab["cls"] == "player" for lab in labels),
        "ball_boxes": sum(lab["cls"] == "ball" for lab in labels),
        "ball_by_visibility": {g: ball_visibility.get(g, 0) for g in VISIBILITY_GROUPS},
        "ball_sizes_px": [_size(lab["bbox"], scale) for lab in labels if lab["cls"] == "ball"],
    }


def summarise(clips: list[dict]) -> dict:
    """Merge per-clip counts into one split summary."""
    sizes = [s for clip in clips for s in clip["ball_sizes_px"]]
    ball_boxes = sum(c["ball_boxes"] for c in clips)
    by_visibility = {
        g: sum(c["ball_by_visibility"][g] for c in clips) for g in VISIBILITY_GROUPS
    }
    below_half = by_visibility["mostly hidden"]  # 0 < visibility < 0.5; boxes at 0 are not drawn
    knobs: dict[str, dict[str, int]] = {}
    for name in KNOB_NAMES:
        knobs[name] = dict(sorted(Counter(str(c["knobs"][name]) for c in clips).items()))
    return {
        "clips": len(clips),
        "seeds": sorted(c["seed"] for c in clips),
        "frames": sum(c["frames"] for c in clips),
        "player_boxes": sum(c["player_boxes"] for c in clips),
        "ball_boxes": ball_boxes,
        "ball_by_visibility": by_visibility,
        "ball_mostly_hidden_share": below_half / ball_boxes if ball_boxes else None,
        "ball_size_px": {
            "p05": percentile(sizes, 0.05),
            "median": percentile(sizes, 0.5),
            "p95": percentile(sizes, 0.95),
        },
        "clips_by_knob": knobs,
    }


def dataset_stats(clip_dirs: Iterable[Path], *, stride: int = 5, train_width: int = 1280) -> dict:
    if stride < 1 or train_width < 1:
        raise ValueError("stride and train_width must be positive")
    by_split: dict[str, list[dict]] = defaultdict(list)
    for clip_dir in clip_dirs:
        stats = clip_stats(Path(clip_dir), stride=stride, train_width=train_width)
        by_split[stats["split"]].append(stats)
    return {
        "frame_stride": stride,
        "train_width_px": train_width,
        "splits": {split: summarise(clips) for split, clips in sorted(by_split.items())},
    }


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
    ap.add_argument("--train-width", type=int, default=1280, help="image width the detector sees")
    ap.add_argument("--out", type=Path, help="write the report here instead of stdout")
    args = ap.parse_args(argv)
    report = dataset_stats(find_clips(args.roots), stride=args.stride, train_width=args.train_width)
    text = json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n"
    if args.out:
        args.out.write_text(text)
    else:
        print(text, end="")


if __name__ == "__main__":
    main()
