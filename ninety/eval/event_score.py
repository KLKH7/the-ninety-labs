"""Score detected events against the ground truth: precision, recall and F1 per event type.

The rule is fixed in docs/EVALUATION.md (Vision scoring) before any detector runs: a detected
event matches a true event of the same type and team within 1.0 s, one to one, nearest first.

    uv run python -m ninety.eval.event_score --truth runs/seed7/events.jsonl \\
        --detected detected.jsonl --report report.json
"""

from __future__ import annotations

import argparse
import datetime
import json
import math
import subprocess
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# 1.0 s is 25 frames at 25 fps: an event detected within a second of when it happened is the same
# event. The edge counts ("within"). EPS absorbs float rounding of times stored to 0.01 s, so
# 11.0 - 10.0 and 3.24 - 2.24 both count as exactly 1.0 s.
WINDOW_S = 1.0
EPS = 1e-9
HEADLINE_TYPE = "pass"


def match(truth: list[dict], detected: list[dict], window_s: float = WINDOW_S) -> list[dict]:
    """Pair detections with true events: same type and team, at most window_s apart, each event
    used once, the closest pair in time taken first."""
    candidates = []
    for i, t in enumerate(truth):
        for j, d in enumerate(detected):
            if (t["type"], t["team"]) != (d["type"], d["team"]):
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
        pairs.append({"truth_id": t["id"], "detected_id": d["id"], "type": t["type"], "team": t["team"],
                      "dt_s": round(d["t"] - t["t"], 6),
                      "distance_m": round(math.hypot(d["x"] - t["x"], d["y"] - t["y"]), 6)})
    return pairs


def ratio(num: int, den: int) -> float | None:
    """None when the denominator is zero: undefined, never a made-up 0 or 1."""
    return num / den if den else None


def score(truth: list[dict], detected: list[dict], window_s: float = WINDOW_S) -> dict:
    pairs = match(truth, detected, window_s)
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
            # Reported, never used to decide a match (the rule is time only).
            "time_error_s": {"mean": sum(dts) / len(dts), "max": max(dts)} if dts else None,
            "distance_m": {"mean": sum(dists) / len(dists), "max": max(dists)} if dists else None,
        }
    headline = per_type.get(HEADLINE_TYPE, {}).get("f1")
    return {
        "rules": {"time_window_s": window_s, "match": "same type and team, one to one, nearest first"},
        "per_type": per_type,
        "headline": {"pass_f1": headline},
        "pairs": pairs,
    }


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
    ap.add_argument("--detected", type=Path, required=True, help="detected events, source vision")
    ap.add_argument("--report", type=Path, required=True, help="where to write the JSON report")
    args = ap.parse_args(argv)

    report = score(load_events(args.truth, "truth"), load_events(args.detected, "vision"))
    report["inputs"] = {"truth": str(args.truth), "detected": str(args.detected),
                        "git_commit": git_commit(), "date": datetime.date.today().isoformat()}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"headline": report["headline"],
                      "per_type": {k: {m: v[m] for m in ("tp", "fp", "fn", "precision", "recall", "f1")}
                                   for k, v in report["per_type"].items()}}, indent=2))


if __name__ == "__main__":
    main()
