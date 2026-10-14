"""Command-line entry points for the broadcast renderer.

ninety-render        one seeded match and its broadcast clip, with ground truth
ninety-dataset       the training clips or the fixed test set, kept on separate seeds
ninety-render-check  the render guide's checks over rendered clips, as a JSON report
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess
import sys
import time
from pathlib import Path

from ninety.render.checks import check_clip, digest
from ninety.render.clip import ROOT, RenderUnavailable, browser_page, render_clip
from ninety.render.params import parse_override
from ninety.render.splits import TEST_SEEDS, check_seed, split_of, train_seeds


def _overrides(items: list[str]) -> dict:
    return dict(parse_override(s) for s in items)


def _add_render_args(ap: argparse.ArgumentParser) -> None:
    ap.add_argument("--seconds", type=float, default=10.0, help="clip length (default 10)")
    ap.add_argument(
        "--gpu", action="store_true", help="hardware GL: faster, but pixels are not bit-reproducible"
    )
    ap.add_argument("--mp4", action="store_true", help="also encode clip.mp4 (needs ffmpeg on PATH)")


def render_main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(
        description="Simulate a seeded match and render its broadcast clip with ground truth."
    )
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument(
        "--start", type=float, default=None, help="clip start in match seconds (default: from the seed)"
    )
    ap.add_argument(
        "--set",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="override a render parameter, e.g. lighting=night, kit_contrast=low, occlusion=crowded, "
        "camera.half_width_m=12 (repeatable)",
    )
    _add_render_args(ap)
    a = ap.parse_args(argv)
    if split_of(a.seed) == "test" and a.set:
        sys.exit("test-set seeds are rendered with their own sampled parameters only; drop --set")
    t = time.time()
    try:
        clip = render_clip(
            a.seed,
            a.out,
            seconds=a.seconds,
            start_s=a.start,
            overrides=_overrides(a.set),
            mp4=a.mp4,
            gpu=a.gpu,
        )
    except RenderUnavailable as e:
        sys.exit(str(e))
    report = check_clip(a.out)
    print(
        json.dumps(
            {
                "out": str(a.out),
                "seed": a.seed,
                "split": clip["split"],
                "frames": clip["frames"],
                "seconds_taken": round(time.time() - t, 1),
                "lighting": clip["params"]["lighting"],
                "events": clip["event_counts"],
                "checks": report["passed"],
            },
            indent=2,
        )
    )


def dataset_main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Render the training clips or the fixed test set.")
    ap.add_argument("--split", choices=("train", "test"), required=True)
    ap.add_argument("--out", type=Path, default=Path("runs/dataset"))
    ap.add_argument("--count", type=int, default=20, help="training clips (ignored for test)")
    ap.add_argument("--first-seed", type=int, default=1, help="first training seed")
    ap.add_argument(
        "--set",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="training only: render parameter override for a targeted round",
    )
    _add_render_args(ap)
    a = ap.parse_args(argv)
    if a.split == "test":
        if a.set:
            sys.exit("the test set is fixed: overrides are not allowed")
        seeds = list(TEST_SEEDS)
    else:
        seeds = train_seeds(a.count, a.first_seed)
    root = a.out / a.split
    manifest_path = a.out / "manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {"clips": []}
    try:
        with browser_page(a.gpu) as (page, _):
            for s in seeds:
                check_seed(s, a.split)
                t = time.time()
                d = root / f"seed{s}"
                clip = render_clip(s, d, seconds=a.seconds, overrides=_overrides(a.set), mp4=a.mp4, page=page)
                entry = {
                    "split": a.split,
                    "seed": s,
                    "dir": str(d),
                    "frames": clip["frames"],
                    "overrides": clip["overrides"],
                    "lighting": clip["params"]["lighting"],
                }
                manifest["clips"] = [c for c in manifest["clips"] if c["dir"] != str(d)] + [entry]
                print(json.dumps({**entry, "seconds_taken": round(time.time() - t, 1)}), flush=True)
    except RenderUnavailable as e:
        sys.exit(str(e))
    test = {c["seed"] for c in manifest["clips"] if c["split"] == "test"}
    train = {c["seed"] for c in manifest["clips"] if c["split"] == "train"}
    if test & train:  # pragma: no cover - check_seed already prevents this
        sys.exit(f"seeds in both splits: {sorted(test & train)}")
    manifest_path.write_text(json.dumps(manifest, indent=2))


def _git_commit() -> str | None:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def check_main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Run the render guide's checks over rendered clips.")
    ap.add_argument("clips", nargs="+", type=Path, help="clip directories")
    ap.add_argument(
        "--determinism",
        action="store_true",
        help="re-render the first clip and compare ground truth and image hashes",
    )
    ap.add_argument("--report", type=Path, default=None, help="write the JSON report here")
    a = ap.parse_args(argv)
    reports = [check_clip(d) for d in a.clips]
    ball_all = [r["occlusion"]["ball_visibility_lt_0_5_share"] for r in reports]
    weights = [r["occlusion"]["ball_in_frame"] for r in reports]
    hidden = sum((s or 0) * w for s, w in zip(ball_all, weights, strict=True))
    summary = {
        "clips": len(reports),
        "frames": sum(r["labels"]["frames"] for r in reports),
        "ball_projection_max_px": max((r["projection"]["ball_px"]["max"] or 0) for r in reports),
        "ball_projection_mean_px": round(
            sum((r["projection"]["ball_px"]["mean"] or 0) * r["projection"]["ball_px"]["n"] for r in reports)
            / max(1, sum(r["projection"]["ball_px"]["n"] for r in reports)),
            4,
        ),
        "keypoint_projection_max_px": max((r["projection"]["keypoint_px"]["max"] or 0) for r in reports),
        "player_feet_outside_box": sum(r["projection"]["player_foot_outside_box"] for r in reports),
        "frames_with_label_problems": sum(len(r["labels"]["problems"]) for r in reports),
        "ball_visibility_lt_0_5_share": round(hidden / max(1, sum(weights)), 4),
        "all_passed": all(all(r["passed"].values()) for r in reports),
    }
    if a.determinism:
        first = a.clips[0]
        clip = json.loads((first / "clip.json").read_text())
        again = first.parent / f"{first.name}.rerender"
        render_clip(
            clip["seed"],
            again,
            seconds=clip["frames"] / clip["fps"],
            start_s=clip["t_start"],
            overrides=clip["overrides"],
        )
        da, db = digest(first), digest(again)
        summary["determinism"] = {
            "clip": clip["clip_id"],
            "frames_jsonl_identical": da["frames_jsonl"] == db["frames_jsonl"],
            "events_identical": da["events_jsonl"] == db["events_jsonl"],
            "images_identical": da["images"] == db["images"],
            "images_compared": da["image_count"],
        }
        summary["all_passed"] = summary["all_passed"] and all(
            v for k, v in summary["determinism"].items() if k.endswith("identical")
        )
    out = {
        "generated": dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "commit": _git_commit(),
        "command": "ninety-render-check " + " ".join(sys.argv[1:] if argv is None else argv),
        "summary": summary,
        "planned": {
            "off_the_shelf_detector_recall": "needs the pretrained detector (Oct 18)",
            "side_by_side_look": "manual; see docs/decisions/0001-synthetic-data.md",
        },
        "clips": reports,
    }
    text = json.dumps(out, indent=2)
    if a.report:
        a.report.parent.mkdir(parents=True, exist_ok=True)
        a.report.write_text(text + "\n")
    print(json.dumps(summary, indent=2))
    if not summary["all_passed"]:
        sys.exit(1)
