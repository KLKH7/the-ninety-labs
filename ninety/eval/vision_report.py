"""Build a vision report: one checkpoint's detections on the frozen test set, scored by vision_score.

    uv run python -m ninety.eval.vision_report --test runs/test-frozen-cca498c/test \
        --detections docs/eval/vision-report-v1/detections --out docs/eval/vision-report-v1.json

Refuses a clip whose labels, events or images differ from docs/eval/test-set-frozen.json, so the
report is always of the frozen test set, and refuses a detections file that skips any of a clip's
frames: vision_score scores only the frames a detector ran on, which is right for a detector run
on every 25th frame, but a report of the test set claims every frame. Each clip is scored on its
own (frame numbers repeat across clips) and the counts are summed; precision, recall and F1 come
from the summed counts with vision_score's conventions. Detections are committed next to the
report, so anyone can rebuild it from the committed tree without the checkpoint or a GPU
(docs/LESSONS.md, lesson 77).

Beyond vision_score's blocks the report adds two numbers that EVALUATION.md's groups do not give:
`ball_at_least_half_visible` (the visible and partly hidden groups together) and
`hidden_ball_frames`: frames where the ball is in shot but fully hidden (visibility zero, so not
a label), how many of them still get a ball detection at or above the threshold, how many of those
land on the hidden ball (centre within the ball distance), and the median distance from the hidden
ball to the nearest such detection. Every ball detection in such a frame is a false positive; the
distance says whether the model sees through the occluder or reports a ball somewhere else.

`height` (the ball in the air or on the ground) and `blur` (each class on frames whose camera blur
streak is longer than 3 px, or not) are summed the same way as the visibility groups. Each is null
when the clips' frames do not record it (`ball.z`, `blur_px`); clips with and without are refused.

`pitch` adds up vision_score's pitch-level matching the same way: each clip scored on its own,
the strict and lenient counts (overall, by class, by visibility group, the ball by height, each
class by blur) summed, and recall and precision taken from the sums, with the at-least-half-visible
ball under each rule.
It is null when the clips have no saved camera matrices, and clips with and without are refused.

`by_clip` gives each clip's by-class counts with the render knobs it was drawn with, and `by_knob`
sums them by `occlusion` and `kit_contrast` (the hard-case knobs the test seeds were drawn with,
from the freeze file), so a weakness such as crowded scenes shows on the test set itself.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ninety.eval.vision_pitch_score import RULES, has_cameras, score_pitch
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
# vision_score's ball height and camera blur axes: null in a clip whose frames do not record them.
FRAME_AXES = ("height", "blur")


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


def build(
    test_dir: Path, det_dir: Path, freeze: dict, threshold: float = DEFAULT_THRESHOLD, stride: int = 1
) -> dict:
    """`stride` > 1 only for a validation set run on every Nth frame (as training validates); a test
    set report scores every frame."""
    totals: dict = {}
    by_frame: dict = {}  # the height and blur axes, kept apart so the existing totals are unchanged
    hidden = {"hidden_balls": 0, "with_a_ball_detection": 0, "on_the_hidden_ball": 0, "distances_px": []}
    frames_scored = 0
    checkpoints = set()
    by_clip, by_knob = [], {}
    pitch: dict = {}
    unplaced = {"labels": 0, "detections": 0}
    cameras = set()
    measured: dict[str, set[bool]] = {axis: set() for axis in FRAME_AXES}
    for clip in freeze["clips"]:
        seed = clip["seed"]
        clip_dir = test_dir / f"seed{seed}"
        check_frozen(clip_dir, clip["digest"])
        frames = load_jsonl(clip_dir / "frames.jsonl")
        rows = load_jsonl(det_dir / f"seed{seed}.jsonl")
        checkpoints |= {r["model"]["checkpoint"] for r in rows}
        run = frames_run(rows)
        wanted = {int(r["frame"]) for r in frames[::stride]}
        missing = wanted - run
        if missing:
            raise ValueError(
                f"seed{seed}: the detector did not run on {len(missing)} of {len(wanted)} frames "
                f"(first {min(missing)}); a report scores every frame of its stride ({stride})"
            )
        dets = flatten(rows)
        report = score(frames, dets, threshold, run=run)
        frames_scored += report["frames"]["scored"]
        _add(totals, {k: report[k] for k in ("overall", "by_class", "visibility", "image_boundary")})
        for axis in FRAME_AXES:
            measured[axis].add(report[axis] is not None)
            if len(measured[axis]) > 1:
                raise ValueError(f"seed{seed}: some clips record the {axis} groups and some do not")
        _add(by_frame, {axis: report[axis] for axis in FRAME_AXES if report[axis] is not None})
        knobs = {k: clip.get("params", {}).get(k) for k in KNOBS}
        by_clip.append({"seed": seed, **knobs, "by_class": report["by_class"]})
        for k, v in knobs.items():
            _add(by_knob.setdefault(k, {}), {str(v): report["by_class"]})
        cameras.add(has_cameras(frames))
        if len(cameras) > 1:
            raise ValueError(f"seed{seed}: some clips have saved camera matrices and some do not")
        if cameras == {True}:
            on_pitch = score_pitch(frames, dets, threshold, run=run)
            _add(pitch, {rule: {k: on_pitch[rule][k]
                                for k in ("overall", "by_class", "visibility", "height", "blur")}
                         for rule in RULES})
            for k in unplaced:
                unplaced[k] += on_pitch["unplaced"][k]
            pitch_rules = on_pitch["rules"]
        h = hidden_ball_frames(frames, dets, run, threshold)
        for k in hidden:
            hidden[k] += h[k]
    if len(checkpoints) != 1:
        raise ValueError(f"detections come from {sorted(checkpoints)}, not one checkpoint")
    ball = totals["visibility"]["ball"]
    half = {c: ball["visible"][c] + ball["partly hidden"][c] for c in COUNTS}
    pitch_block = None
    if pitch:
        pitch_block = {"rules": pitch_rules, "unplaced": unplaced}
        for rule in RULES:
            groups = pitch[rule]["visibility"]["ball"]
            pitch_block[rule] = {
                **_finish(pitch[rule]),
                "blur": _finish(pitch[rule]["blur"]) if "blur" in pitch[rule] else None,
                "ball_at_least_half_visible": _metrics(
                    *(groups["visible"][c] + groups["partly hidden"][c] for c in COUNTS)),
            }
    return {
        "checkpoint": checkpoints.pop(),
        "test_set": {
            "tag": freeze["tag"],
            "commit": freeze["commit"],
            "seeds": [c["seed"] for c in freeze["clips"]],
        },
        "threshold": threshold,
        "stride": stride,
        "frames_scored": frames_scored,
        **_finish(totals),
        **{axis: _finish(by_frame[axis]) if axis in by_frame else None for axis in FRAME_AXES},
        "ball_at_least_half_visible": _metrics(*(half[c] for c in COUNTS)),
        "pitch": pitch_block,
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
    ap.add_argument("--stride", type=int, default=1, help="every Nth frame: a validation set only")
    a = ap.parse_args(argv)
    report = build(a.test, a.detections, json.loads(a.freeze.read_text()), stride=a.stride)
    text = json.dumps(report, indent=2) + "\n"
    if a.out:
        a.out.write_text(text)
    print(text, end="")


if __name__ == "__main__":
    main()
