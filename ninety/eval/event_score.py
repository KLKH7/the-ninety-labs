"""Score detected events against the ground truth: precision, recall and F1 per event type.

The rule is fixed in docs/EVALUATION.md (Vision scoring) before any detector runs: a detected
event matches a true event of the same type and team within 1.0 s, one to one, nearest first,
and its spot is within 1.0 m (strict, the headline) or 2.0 m (lenient) of where its reference
object really was at the time vision gives. Time-only matching is reported for comparison.

    uv run python -m ninety.eval.event_score --truth runs/seed7/events.jsonl \\
        --frames runs/seed7/frames.jsonl --detected detected.jsonl --report report.json
"""

from __future__ import annotations

import argparse
import datetime
import json
import math
import subprocess
from collections import Counter
from pathlib import Path

from ninety.sim.engine import FPS

ROOT = Path(__file__).resolve().parents[2]

# 1.0 s is 25 frames at 25 fps: an event detected within a second of when it happened is the same
# event. The edge counts ("within"). EPS absorbs float rounding of times stored to 0.01 s, so
# 11.0 - 10.0 and 3.24 - 2.24 both count as exactly 1.0 s.
WINDOW_S = 1.0
EPS = 1e-9
HEADLINE_TYPE = "pass"

# The position radii of docs/EVALUATION.md: strict because two players are often about 2 m apart,
# so an error above half that can give the ball to the wrong one; lenient as commonly used.
# The place is judged at the detected time, not the true one: a ball moves about 10 m per second
# after a pass (docs/eval/event-motion.md), so judging a late detection at the true event's spot
# would turn a timing error into a place error and quietly tighten the 1.0 s window.
STRICT_M = 1.0
LENIENT_M = 2.0

# What an event's x, y is the position of (checked on simulator truth in tests/test_event_score.py):
# the ball, except a pressure event and a kick-off, which are placed at a player of the event's
# team; a substitution has no meaningful place and is graded on time only.
PLAYER_PLACED = {"pressure", "kickoff"}
FOULED_PLACED = {"foul"}  # placed where the fouled player was (engine.foul): the other side
NOT_PLACED = {"substitution"}


def reference_point(kind: str, team: str, t: float, frames: list[dict],
                    near: tuple[float, float]) -> tuple[float, float, float, float] | None:
    """Where the reference object of an event of this kind was at time t, as (x, y, vx, vy): the
    ball, or for a player-placed kind the player of `team` nearest to the spot `near` (vision's
    tracker cannot be expected to know which shirt it is). None when the kind has no place or t is
    outside the frames."""
    if kind in NOT_PLACED:
        return None
    k = round(t * FPS)
    if kind == "goal":  # the goal's own frame already shows the kickoff (engine.kickoff): the ball
        k -= 1          # as it crossed is the frame before, as the renderer reads it (clip.py)
    if not 0 <= k < len(frames):
        return None
    frame = frames[k]
    if frame["frame"] != k:
        raise ValueError(f"frames must be every frame from 0; position {k} holds frame {frame['frame']}")
    if kind in PLAYER_PLACED | FOULED_PLACED:
        side = team if kind in PLAYER_PLACED else ("away" if team == "home" else "home")
        players = [p for p in frame["players"] if p["team"] == side]
        if not players:
            return None
        p = min(players, key=lambda p: math.hypot(p["x"] - near[0], p["y"] - near[1]))
        return p["x"], p["y"], p.get("vx", 0.0), p.get("vy", 0.0)
    b = frame["ball"]
    return b["x"], b["y"], b.get("vx", 0.0), b.get("vy", 0.0)


def place_error(event: dict, frames: list[dict]) -> float | None:
    """How far the event's spot is from its reference object at the event's own time. None for a
    kind with no place; infinity when the time is outside the frames (nothing to be right about)."""
    if event["type"] in NOT_PLACED:
        return None
    point = reference_point(event["type"], event["team"], event["t"], frames, (event["x"], event["y"]))
    if point is None:
        return math.inf
    return math.hypot(point[0] - event["x"], point[1] - event["y"])


def match(truth: list[dict], detected: list[dict], window_s: float = WINDOW_S,
          frames: list[dict] | None = None, radius_m: float | None = None) -> list[dict]:
    """Pair detections with true events: same type and team, at most window_s apart, each event
    used once, the closest pair in time taken first. With radius_m, a detection must also be within
    radius_m of where its reference object was at the detection's own time."""
    candidates = []
    for i, t in enumerate(truth):
        for j, d in enumerate(detected):
            if (t["type"], t["team"]) != (d["type"], d["team"]):
                continue
            if radius_m is not None:
                err = place_error(d, frames)  # at the time vision gives, d["t"]
                if err is not None and err > radius_m + EPS:
                    continue
            dt = abs(d["t"] - t["t"])
            if dt <= window_s + EPS:
                # Ties broken by list order, so the same input always gives the same pairs.
                candidates.append((dt, i, j))
    candidates.sort()
    used_truth, used_detected, pairs = set(), set(), []
    for _dt, i, j in candidates:
        if i in used_truth or j in used_detected:
            continue
        used_truth.add(i)
        used_detected.add(j)
        t, d = truth[i], detected[j]
        err = place_error(d, frames) if frames is not None else None
        pairs.append({"truth_id": t["id"], "detected_id": d["id"], "type": t["type"], "team": t["team"],
                      "dt_s": round(d["t"] - t["t"], 6),
                      "place_error_m": round(err, 6) if err is not None else None,
                      "distance_m": round(math.hypot(d["x"] - t["x"], d["y"] - t["y"]), 6)})
    return pairs


def ratio(num: int, den: int) -> float | None:
    """None when the denominator is zero: undefined, never a made-up 0 or 1."""
    return num / den if den else None


def grade(truth: list[dict], detected: list[dict], pairs: list[dict]) -> dict:
    n_true = Counter(e["type"] for e in truth)
    n_detected = Counter(e["type"] for e in detected)
    per_type = {}
    for kind in sorted(n_true.keys() | n_detected.keys()):
        matched = [p for p in pairs if p["type"] == kind]
        tp = len(matched)
        precision, recall = ratio(tp, n_detected[kind]), ratio(tp, n_true[kind])
        if precision is None or recall is None:
            f1 = None
        else:
            f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        dts = [abs(p["dt_s"]) for p in matched]
        dists = [p["distance_m"] for p in matched]
        per_type[kind] = {
            "true": n_true[kind], "detected": n_detected[kind],
            "tp": tp, "fp": n_detected[kind] - tp, "fn": n_true[kind] - tp,
            "precision": precision, "recall": recall, "f1": f1,
            # Reported, never used to decide a match: distance_m is to the true event's spot.
            "time_error_s": {"mean": sum(dts) / len(dts), "max": max(dts)} if dts else None,
            "distance_m": {"mean": sum(dists) / len(dists), "max": max(dists)} if dists else None,
        }
    return {"per_type": per_type, "pairs": pairs}


def score(truth: list[dict], detected: list[dict], frames: list[dict] | None = None,
          window_s: float = WINDOW_S) -> dict:
    """Grade under time only and, given the truth frames, under the strict and lenient place rules.
    The headline (pass F1, strict) needs the frames; without them it is None."""
    report = {
        "rules": {"time_window_s": window_s, "strict_m": STRICT_M, "lenient_m": LENIENT_M,
                  "match": "same type and team, one to one, nearest first; spot judged at the detected time"},
        "time_only": grade(truth, detected, match(truth, detected, window_s, frames)),
    }
    if frames is not None:
        for rule, radius in (("strict", STRICT_M), ("lenient", LENIENT_M)):
            report[rule] = grade(truth, detected, match(truth, detected, window_s, frames, radius))
    strict = report.get("strict", {}).get("per_type", {})
    report["headline"] = {"rule": "strict", "pass_f1": strict.get(HEADLINE_TYPE, {}).get("f1")}
    return report


def load_events(path: Path, source: str) -> list[dict]:
    events = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    wrong = [e["id"] for e in events if e.get("source") != source]
    if wrong:
        raise ValueError(f"{path}: expected source {source!r}, found other sources on {wrong[:5]}")
    return events


def git_commit() -> str | None:
    try:
        out = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True)
    except OSError:
        return None
    return out.stdout.strip() or None


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Score detected events against the ground truth.")
    ap.add_argument("--truth", type=Path, required=True, help="events.jsonl from the simulator")
    ap.add_argument("--frames", type=Path, required=True, help="frames.jsonl from the simulator")
    ap.add_argument("--detected", type=Path, required=True, help="detected events, source vision")
    ap.add_argument("--report", type=Path, required=True, help="where to write the JSON report")
    args = ap.parse_args(argv)

    frames = [json.loads(line) for line in args.frames.read_text().splitlines() if line.strip()]
    report = score(load_events(args.truth, "truth"), load_events(args.detected, "vision"), frames)
    report["inputs"] = {"truth": str(args.truth), "frames": str(args.frames), "detected": str(args.detected),
                        "git_commit": git_commit(), "date": datetime.date.today().isoformat()}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n")
    summary = {rule: {k: {m: v[m] for m in ("tp", "fp", "fn", "precision", "recall", "f1")}
                      for k, v in report[rule]["per_type"].items()}
               for rule in ("strict", "lenient", "time_only")}
    print(json.dumps({"headline": report["headline"], **summary}, indent=2))


if __name__ == "__main__":
    main()
