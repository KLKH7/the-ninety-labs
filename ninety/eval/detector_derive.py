"""Re-derive the M1 event detector's constants on validation clips (docs/eval/detector-plan.md).

    uv run python -m ninety.eval.detector_derive --clips <render run v1>/train --observations <dir> \\
        --seeds <the validation seeds> --out docs/eval/detector-derive

Grading data, read offline: the clips' frames.jsonl and events.jsonl. A frozen test seed is refused.
Each step of the plan is a function here, so its numbers can be regenerated:

- `sides`: step A's side accuracy, per track (weighted by frames) and on matched passes;
- `camera_errors`: step B's truth measure, each trusted frame's ground mapping error;
- the gates and the grid for steps B and C.
"""

from __future__ import annotations

import json
import math
from collections import Counter
from pathlib import Path

import numpy as np

from ninety.eval.attribution_derive import refused
from ninety.eval.pitch_score import PLAYER_IOU, SCORE_MIN, _iou
from ninety.vision import track as tr
from ninety.vision.tracked_frames import MIN_TRACK_FRAMES

ROOT = Path(__file__).resolve().parents[2]


def read(seed: int, clips: Path, observations: Path) -> tuple[list[dict], dict[int, dict], list[dict]] | None:
    """The clip's observations, truth frames by number, and truth events; None when the camera
    could not be placed (no observations)."""
    if refused(seed):
        raise SystemExit(f"test seed {seed}: the test clips are for the final score only")
    obs = observations / f"observations-seed{seed}.jsonl"
    if not obs.exists():
        return None
    root = clips / f"seed{seed}"
    frames = {f["frame"]: f for f in map(json.loads, (root / "frames.jsonl").read_text().splitlines())}
    events = [json.loads(x) for x in (root / "events.jsonl").read_text().splitlines() if x.strip()]
    return tr.read_observations(obs), frames, events


def true_player(det: dict, frame: dict) -> dict | None:
    labelled = [p for p in frame["players"] if p.get("bbox") and p.get("visibility", 0) > 0]
    best = max(labelled, key=lambda p: _iou(p["bbox"], det["bbox"]), default=None)
    return best if best is not None and _iou(best["bbox"], det["bbox"]) >= PLAYER_IOU else None


def track_truth(t: tr.Track, obs: dict[int, dict], frames: dict[int, dict]) -> Counter:
    """How many of the track's frames pair with a true player of each side (and which ids)."""
    sides: Counter = Counter()
    for f, xy in zip(t.frames, t.xy, strict=True):
        dets = [d for d in obs[f]["players"] if d["score"] >= SCORE_MIN and (d["x"], d["y"]) == xy]
        p = true_player(dets[0], frames[f]) if len(dets) == 1 else None
        if p is not None:
            sides[p["team"]] += 1
    return sides


def sides(rows: list[dict], frames: dict[int, dict]) -> dict:
    """Step A's side accuracy: every track with a side and at least MIN_TRACK_FRAMES frames, its
    detected side against the side its detections mostly overlap; and the clip's naming."""
    tracks = tr.track_players(rows)
    naming = tr.assign_teams(tracks)
    obs = {r["frame"]: r for r in rows}
    out = []
    for t in tracks:
        if len(t.frames) < MIN_TRACK_FRAMES:
            continue
        truth = track_truth(t, obs, frames)
        side = truth.most_common(1)[0][0] if truth else None
        out.append({"track": t.id, "frames": len(t.frames), "team": t.team, "truth": side, "keeper": t.keeper,
                    "confidence": t.side_confidence, "paired": sum(truth.values())})
    # Accuracy over the tracks given a side; coverage, the share of true players' track frames that
    # got any side, so leaving players unassigned cannot pass for accuracy.
    known = [x for x in out if x["truth"] is not None]
    checked = [x for x in known if x["team"] is not None]
    right = sum(x["frames"] for x in checked if x["team"] == x["truth"])
    total = sum(x["frames"] for x in checked)
    every = sum(x["frames"] for x in known)
    return {"naming": naming, "tracks": out, "right_frames": right, "frames": total, "all_frames": every,
            "accuracy": right / total if total else None, "coverage": total / every if every else None}


def ordering(pairs: list[tuple[float, bool]]) -> float | None:
    """The share of (wrong, right) pairs in which the wrong one has the lower confidence (ties count
    half): how well a confidence orders right above wrong. None without both kinds."""
    wrong = [c for c, ok in pairs if not ok]
    right = [c for c, ok in pairs if ok]
    if not wrong or not right:
        return None
    return sum((w < r) + 0.5 * (w == r) for w in wrong for r in right) / (len(wrong) * len(right))


def pitch_points(step: float = 5.0) -> np.ndarray:
    xs, ys = np.arange(0.0, 105.0 + 1e-9, step), np.arange(0.0, 68.0 + 1e-9, step)
    return np.array([(x, y) for x in xs for y in ys])


def _project(P: np.ndarray, pts: np.ndarray) -> np.ndarray:
    h = np.c_[pts, np.zeros(len(pts)), np.ones(len(pts))] @ P.T
    return h[:, :2] / h[:, 2:3], h[:, 2]


def _to_ground(P: np.ndarray, uv: np.ndarray) -> np.ndarray:
    """Pixels back to the ground plane z = 0 through camera P (its columns 0, 1 and 3 are the
    ground homography)."""
    H = P[:, [0, 1, 3]]
    g = np.c_[uv, np.ones(len(uv))] @ np.linalg.inv(H).T
    return g[:, :2] / g[:, 2:3]


def ground_error(P_true: np.ndarray, P_est: np.ndarray, width: int, height: int) -> float | None:
    """Step B's truth measure: the median distance, over pitch points every 5 m that the true camera
    sees, between each point and its round trip through the true camera's pixel and the estimated
    camera's ground plane. None when no grid point is in the picture."""
    pts = pitch_points()
    uv, depth = _project(P_true, pts)
    inside = (depth > 0) & (uv[:, 0] >= 0) & (uv[:, 0] < width) & (uv[:, 1] >= 0) & (uv[:, 1] < height)
    if not inside.any():
        return None
    back = _to_ground(P_est, uv[inside])
    return float(np.median(np.hypot(*(back - pts[inside]).T)))


def camera_errors(rows: list[dict], frames: dict[int, dict]) -> list[dict]:
    """Every frame's camera verdict and, where an estimated camera exists, its ground error."""
    out = []
    for r in rows:
        cam, f = r["camera"], frames[r["frame"]]
        tc = f["camera"]
        err = None
        if cam.get("P") is not None:
            err = ground_error(np.array(tc["P"]), np.array(cam["P"]), tc["width"], tc["height"])
        out.append({"frame": r["frame"], "ok": cam["ok"], "median_px": cam.get("median_px"),
                    "points": cam.get("points"), "error_m": None if err is None or math.isnan(err) else err})
    return out


def height_ratio(row: dict) -> float | None:
    """The live path's own measure (ninety/vision/observe.py, `height_ratio`) on an observations
    line, trusted or not: one definition and one PLAYER_HEIGHT_M."""
    from ninety.vision.observe import height_ratio as live
    P = row["camera"].get("P")
    return None if P is None else live(row["players"], np.array(P))


GOOD_M = 1.0  # a frame is good when its ground mapping error is within the strict radius (EVALUATION)


def gates(observations: list[tuple[int, list[dict], dict[int, dict]]]) -> dict:
    """Step B: every frame with an estimated camera, its truth error, its marking verdict (B1) and
    its height ratio; the band from the good frames (1st to 99th percentile); and each candidate
    gate's count of bad frames trusted and good frames kept."""
    recs = []
    for seed, rows, frames in observations:
        for r, e in zip(rows, camera_errors(rows, frames), strict=True):
            if e["error_m"] is not None:
                recs.append({"seed": seed, "frame": r["frame"], "error_m": e["error_m"],
                             "markings_ok": r["camera"].get("markings_ok", r["camera"]["ok"]),
                             "ratio": height_ratio(r)})
    good = [x["ratio"] for x in recs if x["error_m"] <= GOOD_M and x["ratio"] is not None]
    band = (round(float(np.percentile(good, 1)), 3), round(float(np.percentile(good, 99)), 3))
    within = lambda x: x["ratio"] is not None and band[0] <= x["ratio"] <= band[1]  # noqa: E731
    candidates = {"B1 markings": lambda x: x["markings_ok"], "B2 heights": within,
                  "B3 both": lambda x: x["markings_ok"] and within(x)}
    n_good = sum(1 for x in recs if x["error_m"] <= GOOD_M)
    n_bad = len(recs) - n_good
    table = {}
    for name, trust in candidates.items():
        bad_trusted = [x for x in recs if x["error_m"] > GOOD_M and trust(x)]
        kept = sum(1 for x in recs if x["error_m"] <= GOOD_M and trust(x))
        table[name] = {"bad_rejected": n_bad - len(bad_trusted), "bad_trusted": len(bad_trusted),
                       "good_kept": kept, "good_kept_share": round(kept / n_good, 4),
                       "bad_trusted_by_seed": dict(Counter(x["seed"] for x in bad_trusted)),
                       "bad_trusted_worst_m": round(max((x["error_m"] for x in bad_trusted), default=0.0), 3)}
    return {"frames": len(recs), "good": n_good, "bad": n_bad, "band": band, "candidates": table}


# Step C: the grid, in the plan's order, the current value first (docs/eval/detector-plan.md).
GRID = [
    ("events", "CARRY_MPS", (4.0, 3.0, 5.0, 6.0)),
    ("events", "MIN_SPELL_FRAMES", (2, 1, 3)),
    ("events", "SPELL_GAP_FRAMES", (6, 3, 12)),
    ("events", "SHOT_MARGIN_M", (1.0, 0.5, 2.0)),
    ("events", "SHOT_MAX_M", (35.0, 30.0, 40.0)),
    ("events", "OUT_FRAMES", (3, 2, 5)),
    ("track", "GATE_M", (1.0, 1.5, 2.0)),
]
SCORED = ("pass", "shot", "out_of_play")


def event_counts(clips: list[tuple[list[dict], list[dict], list[dict]]]) -> tuple[int, int]:
    """Strict true and false positives (event_score's rule: type and team within 1.0 s, the spot
    within 1.0 m of the ball at the detected time), summed over pass, shot and out of play."""
    from ninety.eval import event_score
    from ninety.vision import events as ev

    tp = fp = 0
    for rows, frame_list, truth in clips:
        detected = [e for e in ev.detect(rows)[0] if e["type"] in SCORED]
        pairs = event_score.match([e for e in truth if e["type"] in SCORED], detected,
                                  frames=frame_list, radius_m=event_score.STRICT_M)
        tp += len(pairs)
        fp += len(detected) - len(pairs)
    return tp, fp


def grid(clips: list[tuple[list[dict], list[dict], list[dict]]]) -> dict:
    """Step C: each constant over its grid, one at a time, the earlier changes kept. A value changes
    only if an alternative gives at least 2 more true positives with no more false positives; the
    best such (most TP, then fewest FP) is taken. Restores every constant it touches."""
    import importlib

    modules = {"events": importlib.import_module("ninety.vision.events"), "track": tr}
    original = {(m, name): getattr(modules[m], name) for m, name, _ in GRID}
    trials = []
    try:
        for m, name, values in GRID:
            mod = modules[m]
            current = getattr(mod, name)
            base = event_counts(clips)
            scores = {}
            for v in values:
                setattr(mod, name, v)
                scores[v] = event_counts(clips)
            setattr(mod, name, current)
            better = [(tp, -fp, v) for v, (tp, fp) in scores.items()
                      if v != current and tp >= base[0] + 2 and fp <= base[1]]
            chosen = max(better)[2] if better else current
            setattr(mod, name, chosen)
            trials.append({"constant": f"{m}.{name}", "was": current, "chosen": chosen,
                           "scores": {str(v): {"tp": tp, "fp": fp} for v, (tp, fp) in scores.items()}})
        final = event_counts(clips)
        chosen = {f"{m}.{name}": getattr(modules[m], name) for m, name, _ in GRID}
    finally:
        for (m, name), v in original.items():
            setattr(modules[m], name, v)
    return {"trials": trials, "chosen": chosen, "final": {"tp": final[0], "fp": final[1]}}


def main(argv: list[str] | None = None) -> None:
    import argparse
    import datetime

    from ninety.eval.attribution_score import write_or_check
    from ninety.eval.event_score import git_commit

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--clips", type=Path, required=True)
    ap.add_argument("--observations", type=Path, required=True,
                    help="validation observations, judged by today's observe.place (--regate)")
    ap.add_argument("--seeds", required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args(argv)
    seeds = [int(s) for s in a.seeds.split(",")]
    got = {s: read(s, a.clips, a.observations) for s in seeds}
    placed = [s for s in seeds if got[s] is not None]
    side = {s: sides(got[s][0], got[s][1]) for s in placed}
    right = sum(v["right_frames"] for v in side.values())
    frames_ = sum(v["frames"] for v in side.values())
    every = sum(v["all_frames"] for v in side.values())
    body = {
        "command": "uv run python -m ninety.eval.detector_derive --clips <render run v1>/train "
                   "--observations <validation observations, regated> --seeds <the validation seeds> "
                   "--out docs/eval/detector-derive",
        "commit": git_commit(), "date": datetime.date.today().isoformat(),
        "seeds": placed, "unplaced": [s for s in seeds if got[s] is None],
        "sides": {"accuracy": round(right / frames_, 4), "coverage": round(frames_ / every, 4),
                  "per_clip": {s: {"feature": v["naming"].get("feature"),
                                   "accuracy": None if v["accuracy"] is None else round(v["accuracy"], 4),
                                   "coverage": None if v["coverage"] is None else round(v["coverage"], 4)}
                               for s, v in side.items()}},
        "gates": gates([(s, got[s][0], got[s][1]) for s in placed]),
        "grid": grid([(got[s][0], [got[s][1][f] for f in sorted(got[s][1])], got[s][2]) for s in placed]),
    }
    write_or_check(a.out, body, report_md, a.check)
    print(json.dumps({"sides": {k: body["sides"][k] for k in ("accuracy", "coverage")},
                      "band": body["gates"]["band"]}, indent=1))


def report_md(body: dict) -> str:
    g = body["gates"]
    lines = [
        "# The event detector, re-derived on validation clips: measurements",
        "",
        f"Generated by `{body['command']}` at commit `{body['commit']}`, {body['date']}. Plan and reading:",
        "[detector-plan.md](detector-plan.md). Seeds " + ", ".join(map(str, body["seeds"]))
        + "; not placed: " + (", ".join(map(str, body["unplaced"])) or "none") + ".",
        "",
        "## Step A: sides (code at this commit)",
        "",
        f"Side accuracy per track, by frames: **{body['sides']['accuracy']}**; coverage "
        f"{body['sides']['coverage']}.",
        "",
        "| Seed | Feature | Accuracy | Coverage |",
        "|---|---|---|---|",
        *[f"| {s} | {v['feature']} | {v['accuracy']} | {v['coverage']} |"
          for s, v in body["sides"]["per_clip"].items()],
        "",
        "## Step B: the camera trust gate",
        "",
        f"{g['frames']} frames with an estimated camera: {g['good']} good (ground mapping within "
        f"{GOOD_M} m), {g['bad']} bad. Height band from the good frames (1st to 99th percentile): "
        f"**{g['band'][0]} to {g['band'][1]}**.",
        "",
        "| Gate | Bad frames trusted | Worst trusted (m) | Good frames kept | Bad trusted by seed |",
        "|---|---|---|---|---|",
        *[f"| {k} | {v['bad_trusted']} | {v['bad_trusted_worst_m']} | {v['good_kept']} "
          f"({v['good_kept_share']}) "
          f"| {v['bad_trusted_by_seed']} |" for k, v in g["candidates"].items()],
        "",
        "## Step C: the event and tracker constants",
        "",
        "Strict true / false positives over pass, shot and out of play, each value with the earlier "
        "choices kept.",
        "",
        "| Constant | Was | Chosen | Each value: TP / FP |",
        "|---|---|---|---|",
        *[f"| {t['constant']} | {t['was']} | {t['chosen']} | "
          + "; ".join(f"{v}: {c['tp']} / {c['fp']}" for v, c in t["scores"].items()) + " |"
          for t in body["grid"]["trials"]],
        "",
        f"With the chosen values: {body['grid']['final']['tp']} true and {body['grid']['final']['fp']} "
        "false positives.",
    ]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    main()
