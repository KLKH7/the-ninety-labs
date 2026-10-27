"""Grades the Foundry event check (ninety/vision/foundry_check.py) against the answer key, offline.

The rules were stated before the scored run (docs/eval/foundry-event-check-plan.md). Ground truth is
read here only, for grading.

    uv run python -m ninety.eval.foundry_event_score <checked.json> --run <run> --truth <events.jsonl>
        [--baseline <detected.jsonl>] [--out <report.json>]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ninety.eval.event_score import WINDOW_S, wilson
from ninety.eval.set_piece_set import restarts

FPS = 25
TYPES = ("corner", "goal_kick", "throw_in", "shot")
BEFORE_STOP_S, AFTER_RESTART_S = 2.0, 3.0
MIN_TRUE = 5
MIN_PRECISION = 0.8


def shown_frames(run: Path) -> set[int]:
    out = set()
    with (run / "observations.jsonl").open() as fh:
        for line in fh:
            out.add(int(json.loads(line)["frame"]))
    return out


def truth_events(events: list[dict], shown: set[int]) -> dict[str, list[dict]]:
    """Per type, the true events the video shows: a restart whose restart or stoppage frame is shown,
    a shot whose frame is shown. Each with the match-frame window a detection must fall in."""
    out: dict[str, list[dict]] = {t: [] for t in TYPES}
    for r in restarts(events):
        if r["kind"] not in out:
            continue
        if r["frame"] in shown or (r["stop"] is not None and r["stop"] in shown):
            lo = (r["stop"] if r["stop"] is not None else r["frame"]) - BEFORE_STOP_S * FPS
            out[r["kind"]].append({"frame": r["frame"], "stop": r["stop"], "lo": lo,
                                   "hi": r["frame"] + AFTER_RESTART_S * FPS})
    for e in events:
        if e["type"] == "shot" and e["frame"] in shown:
            out["shot"].append({"frame": e["frame"], "stop": None, "lo": e["frame"] - WINDOW_S * FPS,
                                "hi": e["frame"] + WINDOW_S * FPS})
    return out


def kind_of(e: dict) -> str | None:
    if e.get("type") == "shot":
        return "shot"
    if e.get("type") == "set_piece" and e.get("restart") in TYPES:
        return e["restart"]
    return None


def match(truths: list[dict], dets: list[dict]) -> tuple[list[tuple[dict, dict]], list[dict], list[dict]]:
    """One to one, nearest first (distance to the true event's frame)."""
    pairs = sorted(((abs(d["frame"] - t["frame"]), ti, di) for ti, t in enumerate(truths)
                    for di, d in enumerate(dets) if t["lo"] <= d["frame"] <= t["hi"]), key=lambda p: p[0])
    used_t, used_d, matched = set(), set(), []
    for _, ti, di in pairs:
        if ti in used_t or di in used_d:
            continue
        used_t.add(ti)
        used_d.add(di)
        matched.append((truths[ti], dets[di]))
    return (matched, [t for i, t in enumerate(truths) if i not in used_t],
            [d for i, d in enumerate(dets) if i not in used_d])


def grade(truth: dict[str, list[dict]], detected: list[dict]) -> dict:
    out = {}
    for typ in TYPES:
        dets = [d for d in detected if kind_of(d) == typ]
        m, miss, fp = match(truth[typ], dets)
        n, k, p = len(truth[typ]), len(m), len(dets)
        out[typ] = {
            "true": n, "detected": p, "hits": k,
            "recall": round(k / n, 3) if n else None, "recall_ci95": wilson(k, n),
            "precision": round(k / p, 3) if p else None, "precision_ci95": wilson(k, p),
            "misses": [{"frame": t["frame"], "stop": t["stop"], "t": round(t["frame"] / FPS, 2)}
                       for t in miss],
            "false_positives": [{"frame": d["frame"], "t": d.get("t"), "confidence": d.get("confidence"),
                                 "candidate": d.get("candidate"), "team": d.get("team")} for d in fp],
            "hit_frames": [{"truth": t["frame"], "detected": d["frame"]} for t, d in m],
        }
    return out


def verdict(checker: dict, baseline: dict) -> dict:
    out = {}
    for typ in TYPES:
        c, b = checker[typ], baseline[typ]
        reasons = []
        if c["true"] < MIN_TRUE:
            reasons.append(f"only {c['true']} true shown (needs {MIN_TRUE}): counts only")
        if c["precision"] is None or c["precision"] < MIN_PRECISION:
            reasons.append(f"precision {c['precision']} < {MIN_PRECISION}")
        if (c["recall"] or 0) <= (b["recall"] or 0):
            reasons.append(f"recall {c['recall']} not above the baseline's {b['recall']}")
        out[typ] = {"pass": not reasons, "reasons": reasons}
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("checked", type=Path)
    ap.add_argument("--run", type=Path, required=True)
    ap.add_argument("--truth", type=Path, required=True)
    ap.add_argument("--baseline", type=Path)
    ap.add_argument("--out", type=Path)
    a = ap.parse_args(argv)
    shown = shown_frames(a.run)
    truth = truth_events([json.loads(x) for x in a.truth.open()], shown)
    checked = json.loads(a.checked.read_text())
    base_path = a.baseline or a.run / "detected.jsonl"
    baseline = [json.loads(x) for x in base_path.open()]
    report = {"checker": grade(truth, checked["events"]), "baseline": grade(truth, baseline),
              "spend": checked["spend"]}
    report["bar"] = verdict(report["checker"], report["baseline"])
    text = json.dumps(report, indent=1) + "\n"
    if a.out:
        a.out.write_text(text)
    for typ in TYPES:
        c, b = report["checker"][typ], report["baseline"][typ]
        print(f"{typ:10s} true {c['true']:3d} | checker {c['hits']}/{c['detected']} R {c['recall']} "
              f"{c['recall_ci95']} P {c['precision']} {c['precision_ci95']} | baseline "
              f"{b['hits']}/{b['detected']} R {b['recall']} | pass {report['bar'][typ]['pass']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
