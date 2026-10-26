"""Tracks per side per frame after fusing the tactical camera's two views: the score of the tactical
re-measurement of the fuse gate (docs/eval/fuse-gate.md), its two arms on the same observations.

    uv run python -m ninety.eval.fuse_tracks --runs runs/tactical1/join/runs --clips runs/tactical1/val \\
        --seeds 108 109 110 112 113 114 115 116 --out docs/eval/fuse-gate/tracks-validation.json

Each seed's `views/views/<lens>/observations.jsonl` (the live run's per-view observations) is fused
twice: *baseline*, fuse with `USE_LENS_BIAS` off (each view's pixel as drawn, the broadcast
precision), and *candidate*, with it on (each lens's measured bias and the precision it leaves).
Each is tracked by the live path (ninety.vision.tracked_frames).
Grading data, read offline: the union of the views' and the broadcast's `frames.jsonl` players. A
frozen test seed is refused.

Per tracked frame, tracks and true players are matched one to one, nearest first, within
track.GATE_M (the tracker's own gate). The measures were fixed in fuse-gate.md before this ran.
"""

from __future__ import annotations

import argparse
import json
import math
from contextlib import contextmanager
from pathlib import Path

from ninety.eval.attribution_derive import refused
from ninety.vision import fuse, track, tracked_frames
from ninety.vision.track import GATE_M, MAX_PER_SIDE

Z95 = 1.96


@contextmanager
def lens_bias(on: bool):
    """fuse with the tactical lens correction on or off, restored after."""
    saved = fuse.USE_LENS_BIAS
    fuse.USE_LENS_BIAS = on
    try:
        yield
    finally:
        fuse.USE_LENS_BIAS = saved


def truth(clip: Path) -> dict[int, dict[str, tuple[str, float, float]]]:
    """frame -> player id -> (team, x, y), from every picture's answer key."""
    out: dict[int, dict] = {}
    files = [clip / "frames.jsonl", *sorted((clip / "views").glob("*/frames.jsonl"))]
    for f in files:
        for line in f.read_text().splitlines():
            r = json.loads(line)
            for p in r["players"]:
                out.setdefault(int(r["frame"]), {})[p["id"]] = (p["team"], float(p["x"]), float(p["y"]))
    return out


def match(tracks: list[dict], people: dict[str, tuple]) -> list[tuple[str, dict]]:
    pairs = sorted((math.dist((t["x"], t["y"]), (x, y)), pid, k)
                   for k, t in enumerate(tracks) for pid, (_, x, y) in people.items())
    used_p, used_t, out = set(), set(), []
    for d, pid, k in pairs:
        if d > GATE_M:
            break
        if pid in used_p or k in used_t:
            continue
        used_p.add(pid)
        used_t.add(k)
        out.append((pid, tracks[k]))
    return out


def grade(tracked: dict, key: dict[int, dict]) -> dict:
    n_side = diff = over = 0
    counts = []
    true_frames = found = matched = right_side = switches = 0
    last: dict[str, str] = {}
    for fr in tracked["frames"]:
        people = key.get(int(fr["frame"]), {})
        tracks = [p for p in fr["players"] if p.get("team") in ("home", "away")]
        for side in ("home", "away"):
            n = sum(p["team"] == side for p in tracks)
            n_true = sum(t == side for t, _, _ in people.values())
            counts.append(n)
            n_side += 1
            diff += abs(n - n_true)
            over += n > MAX_PER_SIDE
        pairs = match(tracks, people)
        true_frames += len(people)
        found += len(pairs)
        for pid, t in pairs:
            matched += 1
            right_side += t["team"] == people[pid][0]
            if pid in last and last[pid] != t["id"]:
                switches += 1
            last[pid] = t["id"]
    return {"side_frames": n_side, "tracks": sum(counts), "over": over, "abs_diff": diff,
            "true_frames": true_frames, "found": found, "matched": matched, "right_side": right_side,
            "id_switches": switches}


def wilson(k: int, n: int) -> list[float]:
    if n == 0:
        return [0.0, 1.0]
    # event_score.wilson's formula, to 4 places (the rule compares 0.6547 with 0.6552); no ** in
    # evaluation code: it is C's pow (tests/test_fmath.py)
    p, z2 = k / n, Z95 * Z95
    c = (p + z2 / (2 * n)) / (1 + z2 / n)
    h = Z95 * math.sqrt(p * (1 - p) / n + z2 / (4 * n * n)) / (1 + z2 / n)
    return [round(c - h, 4), round(c + h, 4)]


def summary(g: dict) -> dict:
    return dict(g) | {
        "tracks_per_side_frame": round(g["tracks"] / g["side_frames"], 3),
        "mean_abs_count_diff": round(g["abs_diff"] / g["side_frames"], 4),
        "over_11_share": round(g["over"] / g["side_frames"], 4),
        "id_switches": g["id_switches"],
        "player_recall": round(g["found"] / g["true_frames"], 4),
        "player_recall_95": wilson(g["found"], g["true_frames"]),
        "side_accuracy": round(g["right_side"] / g["matched"], 4) if g["matched"] else None,
        "side_accuracy_95": wilson(g["right_side"], g["matched"]),
    }


def arm(view_dir: Path) -> dict:
    views = {v.name: track.read_observations(v / "observations.jsonl")
             for v in sorted(view_dir.iterdir()) if (v / "observations.jsonl").exists()}
    obs = fuse.fuse(views)
    return tracked_frames.build(obs, "graded")


def adopted(b: dict, c: dict) -> dict:
    rule = {
        "over_11_lower": c["over_11_share"] < b["over_11_share"],
        "count_diff_lower": c["mean_abs_count_diff"] < b["mean_abs_count_diff"],
        "id_switches_no_more": c["id_switches"] <= b["id_switches"],
        "recall_not_below_baseline_lower_bound": c["player_recall"] >= b["player_recall_95"][0],
        "side_not_below_baseline_lower_bound": c["side_accuracy"] >= b["side_accuracy_95"][0],
    }
    return rule | {"adopt": all(rule.values())}


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Score the fuse gate's two arms on tracks per side.")
    ap.add_argument("--runs", type=Path, required=True, help="folder of seed<N>/views/views/<lens>/")
    ap.add_argument("--clips", type=Path, required=True, help="folder of seed<N>/ clips (the answer key)")
    ap.add_argument("--seeds", type=int, nargs="+", required=True)
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args(argv)
    totals: dict[str, dict] = {"baseline": {}, "candidate": {}}
    per_seed = {}
    for seed in a.seeds:
        if refused(seed):
            raise SystemExit(f"test seed {seed}: the test clips are for the final score only")
        key = truth(a.clips / f"seed{seed}")
        view_dir = a.runs / f"seed{seed}" / "views" / "views"
        with lens_bias(False):
            b = grade(arm(view_dir), key)
        with lens_bias(True):
            c = grade(arm(view_dir), key)
        per_seed[seed] = {"baseline": summary(b), "candidate": summary(c)}
        for name, g in (("baseline", b), ("candidate", c)):
            for k, v in g.items():
                totals[name][k] = totals[name].get(k, 0) + v
    report = {"seeds": a.seeds, "gate_m": GATE_M,
              "baseline": summary(totals["baseline"]), "candidate": summary(totals["candidate"])}
    report["rule"] = adopted(report["baseline"], report["candidate"])
    report["per_seed"] = per_seed
    a.out.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({k: report[k] for k in ("baseline", "candidate", "rule")}, indent=1))


if __name__ == "__main__":
    main()
