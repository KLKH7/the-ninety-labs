"""Build a vision report: one checkpoint's detections on the frozen test set, scored by vision_score.

    uv run python -m ninety.eval.vision_report --test runs/test-frozen-cca498c/test \
        --detections docs/eval/vision-report-v1/detections --out docs/eval/vision-report-v1.json

Refuses a clip whose labels, events or images differ from docs/eval/test-set-frozen.json, so the
report is always of the frozen test set. Each clip is scored on its own (frame numbers repeat
across clips) and the counts are summed; precision, recall and F1 come from the summed counts with
vision_score's conventions. Detections are committed next to the report, so anyone can rebuild it
from the committed tree without the checkpoint or a GPU (docs/LESSONS.md, lesson 77).

Beyond vision_score's blocks the report adds two numbers that EVALUATION.md's groups do not give:
`ball_at_least_half_visible` (the visible and partly hidden groups together) and
`hidden_ball_frames`: frames where the ball is in shot but fully hidden (visibility zero, so not
a label), how many of them still get a ball detection at or above the threshold, how many of those
land on the hidden ball (centre within the ball distance), and the median distance from the hidden
ball to the nearest such detection. Every ball detection in such a frame is a false positive; the
distance says whether the model sees through the occluder or reports a ball somewhere else.

`by_clip` gives each clip's by-class counts with the render knobs it was drawn with, and `by_knob`
sums them by `occlusion` and `kit_contrast` (the hard-case knobs the test seeds were drawn with,
from the freeze file), so a weakness such as crowded scenes shows on the test set itself.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ninety.eval.vision_score import (
    BALL_DISTANCE_PX,
    DEFAULT_THRESHOLD,
    _metrics,
    center_distance,
    flatten,
    frames_run,
    load_jsonl,
    score,
)
from ninety.render.checks import digest

KNOBS = ("occlusion", "kit_contrast")
FREEZE = Path(__file__).resolve().parents[2] / "docs" / "eval" / "test-set-frozen.json"
COUNTS = ("tp", "fp", "fn")


def check_frozen(clip_dir: Path, expected: dict) -> None:
    """The clip's labels, events and images are the frozen ones."""
    got = digest(clip_dir)
    wrong = [k for k in ("frames_jsonl", "events_jsonl", "images", "image_count") if got[k] != expected[k]]
    if wrong:
        raise ValueError(f"{clip_dir} is not the frozen test clip: {', '.join(wrong)} differ")


def _add(into: dict, block: dict) -> None:
    """Sum tp/fp/fn from a vision_score block (nested dicts of counts) into `into`."""
    for key, value in block.items():
        if isinstance(value, dict):
            if set(COUNTS) <= set(value):
                slot = into.setdefault(key, dict.fromkeys(COUNTS, 0))
                for c in COUNTS:
                    slot[c] += value[c]
            else:
                _add(into.setdefault(key, {}), value)


def _finish(block: dict) -> dict:
    out = {}
    for key, value in block.items():
        out[key] = _metrics(*(value[c] for c in COUNTS)) if set(value) == set(COUNTS) else _finish(value)
    return out


def hidden_ball_frames(frames: list[dict], detections: list[dict], run: set[int], threshold: float) -> dict:
    """Frames with the ball in shot but fully hidden, and where confident ball detections land."""
    balls = {
        int(r["frame"]): r["ball"]["bbox"]
        for r in frames
        if int(r["frame"]) in run
        and (r.get("ball") or {}).get("bbox") is not None
        and float(r["ball"].get("visibility", 1.0)) == 0
    }
    nearest: dict[int, float] = {}
    for d in detections:
        if d["cls"] == "ball" and d["score"] >= threshold and d["frame"] in balls:
            dist = center_distance(d["bbox"], balls[d["frame"]])
            nearest[d["frame"]] = min(dist, nearest.get(d["frame"], dist))
    return {
        "hidden_balls": len(balls),
        "with_a_ball_detection": len(nearest),
        "on_the_hidden_ball": sum(v <= BALL_DISTANCE_PX for v in nearest.values()),
        "distances_px": sorted(round(v, 1) for v in nearest.values()),
    }


def _median(values: list[float]) -> float | None:
    v = sorted(values)
    if not v:
        return None
    mid = len(v) // 2
    return v[mid] if len(v) % 2 else round((v[mid - 1] + v[mid]) / 2, 1)


def build(test_dir: Path, det_dir: Path, freeze: dict, threshold: float = DEFAULT_THRESHOLD) -> dict:
    totals: dict = {}
    hidden = {"hidden_balls": 0, "with_a_ball_detection": 0, "on_the_hidden_ball": 0, "distances_px": []}
    frames_scored = 0
    checkpoints = set()
    by_clip, by_knob = [], {}
    for clip in freeze["clips"]:
        seed = clip["seed"]
        clip_dir = test_dir / f"seed{seed}"
        check_frozen(clip_dir, clip["digest"])
        frames = load_jsonl(clip_dir / "frames.jsonl")
        rows = load_jsonl(det_dir / f"seed{seed}.jsonl")
        checkpoints |= {r["model"]["checkpoint"] for r in rows}
        run = frames_run(rows)
        dets = flatten(rows)
        report = score(frames, dets, threshold, run=run)
        frames_scored += report["frames"]["scored"]
        _add(totals, {k: report[k] for k in ("overall", "by_class", "visibility", "image_boundary")})
        knobs = {k: clip.get("params", {}).get(k) for k in KNOBS}
        by_clip.append({"seed": seed, **knobs, "by_class": report["by_class"]})
        for k, v in knobs.items():
            _add(by_knob.setdefault(k, {}), {str(v): report["by_class"]})
        h = hidden_ball_frames(frames, dets, run, threshold)
        for k in hidden:
            hidden[k] += h[k]
    if len(checkpoints) != 1:
        raise ValueError(f"detections come from {sorted(checkpoints)}, not one checkpoint")
    ball = totals["visibility"]["ball"]
    half = {c: ball["visible"][c] + ball["partly hidden"][c] for c in COUNTS}
    return {
        "checkpoint": checkpoints.pop(),
        "test_set": {
            "tag": freeze["tag"],
            "commit": freeze["commit"],
            "seeds": [c["seed"] for c in freeze["clips"]],
        },
        "threshold": threshold,
        "frames_scored": frames_scored,
        **_finish(totals),
        "ball_at_least_half_visible": _metrics(*(half[c] for c in COUNTS)),
        "by_knob": _finish(by_knob),
        "by_clip": by_clip,
        "hidden_ball_frames": {
            **{k: v for k, v in hidden.items() if k != "distances_px"},
            "median_distance_px": _median(hidden["distances_px"]),
        },
    }


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Score a checkpoint's detections on the frozen test set.")
    ap.add_argument("--test", type=Path, required=True, help="the frozen test clips (seed<N>/ folders)")
    ap.add_argument("--detections", type=Path, required=True, help="folder of seed<N>.jsonl detections")
    ap.add_argument("--freeze", type=Path, default=FREEZE)
    ap.add_argument("--out", type=Path)
    a = ap.parse_args(argv)
    report = build(a.test, a.detections, json.loads(a.freeze.read_text()))
    text = json.dumps(report, indent=2) + "\n"
    if a.out:
        a.out.write_text(text)
    print(text, end="")


if __name__ == "__main__":
    main()
