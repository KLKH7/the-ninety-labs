"""How far the phone's numbers from tracked positions are from the same numbers on the ground truth.

Grading only (AGENTS.md: the answer key is for training labels and grading): this reads the clip's
truth frames, so nothing on the live path imports it. It pairs each track the phone shows
(ninety/vision/tracked_frames.py) with the true player nearest it over the track's frames, then
computes the companion's window facts (ninety/intel/window.py, `player_window`) on both, over the
same frames: speed now at every whole second of the track, top speed and distance over the track.
It does so with the shipped smoothing and without any, so the report shows what the smoothing does.

    uv run python -m ninety.eval.tracked_speed tests/fixtures/observations-seed900001.jsonl \\
        runs/test-frozen-cca498c/test/seed900001/frames.jsonl --clip seed900001 \\
        --out docs/eval/companion-tracked.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
from pathlib import Path

from ninety.intel.window import player_window
from ninety.vision import track as tr
from ninety.vision import tracked_frames as tf


def read_truth(path: Path, frames: set[int]) -> dict[int, dict]:
    out = {}
    for line in path.read_text().splitlines():
        if line.strip():
            row = json.loads(line)
            if row["frame"] in frames:
                out[row["frame"]] = row
    return out


def pair(tracked: list[dict], truth: dict[int, dict]) -> dict[str, tuple[str, float]]:
    """Each track's true player: the one nearest it on average over the frames it was seen."""
    sums: dict[str, dict[str, list[float]]] = {}
    for f in tracked:
        true = truth[f["frame"]]["players"]
        for p in f["players"]:
            for q in true:
                if q["team"] == p["team"]:
                    d = math.dist((p["x"], p["y"]), (q["x"], q["y"]))
                    sums.setdefault(p["id"], {}).setdefault(q["id"], []).append(d)
    out = {}
    for pid, by in sums.items():
        full = max(map(len, by.values()))  # true players on the pitch in every frame the track was seen
        means = [(qid, statistics.fmean(d)) for qid, d in by.items() if len(d) == full]
        out[pid] = min(means, key=lambda x: x[1])
    return out


def stats(errors: list[float]) -> dict:
    if not errors:
        return {"n": 0}
    s = sorted(abs(e) for e in errors)
    return {
        "n": len(s),
        "median": round(statistics.median(s), 2),
        "p90": round(s[min(len(s) - 1, int(0.9 * len(s)))], 2),
        "max": round(s[-1], 2),
        "mean_signed": round(statistics.fmean(errors), 2),
    }


def compare(tracked: list[dict], truth: dict[int, dict], pairs: dict[str, tuple[str, float]]) -> dict:
    speed_now, peak, distance, rows = [], [], [], []
    truth_frames = [truth[f["frame"]] for f in tracked]
    for pid, (qid, mean_m) in sorted(pairs.items()):
        seen = [f for f in tracked if any(p["id"] == pid for p in f["players"])]
        if len(seen) < 2:
            continue
        t0, t1 = seen[0]["t"], seen[-1]["t"]
        mine = [f for f in truth_frames if t0 <= f["t"] <= t1]
        # Speed now at every whole second from one second in (the first second has no full mean).
        for k in range(math.ceil(t0 + 1), math.floor(t1) + 1):
            a = player_window(seen, pid, t0, float(k))
            b = player_window(mine, qid, t0, float(k))
            if a and b:
                speed_now.append(a.speed_now.value - b.speed_now.value)
        a = player_window(seen, pid, t0, t1)
        b = player_window(mine, qid, t0, t1)
        if a and b:
            peak.append(a.peak_speed.value - b.peak_speed.value)
            distance.append(a.distance_run.value - b.distance_run.value)
            rows.append({
                "track": pid, "player": qid, "frames": len(seen), "mean_offset_m": round(mean_m, 2),
                "peak_kmh": [a.peak_speed.value, b.peak_speed.value],
                "distance_m": [a.distance_run.value, b.distance_run.value],
            })
    return {
        "speed_now_kmh": stats(speed_now),
        "peak_kmh": stats(peak),
        "distance_m": stats(distance),
        "tracks": rows,
    }


def run(observations: Path, truth_path: Path, clip: str) -> dict:
    rows = tr.read_observations(observations)
    out = {"clip": clip, "observations": str(observations), "truth": str(truth_path), "by_smoothing": {}}
    for width in (1, tf.SMOOTH_FRAMES):
        body = tf.build(rows, clip, width)
        truth = read_truth(truth_path, {f["frame"] for f in body["frames"]})
        pairs = pair(body["frames"], truth)
        out["by_smoothing"][str(width)] = compare(body["frames"], truth, pairs)
    out["shipped_smoothing"] = tf.SMOOTH_FRAMES
    # The tracked frames graded, as the committed fixture holds them (tests/test_tracked_frames.py
    # holds the two equal, so this report is about the file the phone is served).
    out["graded_sha256"] = hashlib.sha256(tf.text(tf.build(rows, clip)).encode()).hexdigest()
    return out


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("observations", type=Path)
    ap.add_argument("truth", type=Path, help="the clip's ground-truth frames.jsonl (grading only)")
    ap.add_argument("--clip", required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args(argv)
    report = run(args.observations, args.truth, args.clip)
    args.out.write_text(json.dumps(report, indent=1, allow_nan=False) + "\n")
    for width, r in report["by_smoothing"].items():
        print(f"smoothing {width:>2} frames: speed now {r['speed_now_kmh']}, peak {r['peak_kmh']}, "
              f"distance {r['distance_m']}")


if __name__ == "__main__":
    main()
