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

from ninety.eval.attribution_derive import test_seeds
from ninety.eval.pitch_score import PLAYER_IOU, SCORE_MIN, _iou
from ninety.vision import track as tr
from ninety.vision.tracked_frames import MIN_TRACK_FRAMES

ROOT = Path(__file__).resolve().parents[2]


def read(seed: int, clips: Path, observations: Path) -> tuple[list[dict], dict[int, dict], list[dict]] | None:
    """The clip's observations, truth frames by number, and truth events; None when the camera
    could not be placed (no observations)."""
    if seed in test_seeds():
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
