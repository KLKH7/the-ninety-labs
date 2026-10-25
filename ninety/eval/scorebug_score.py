"""Grade the scorebug reader (ninety/vision/scorebug.py) against the answer key, on validation clips.

    uv run python -m ninety.eval.scorebug_score <clip> <score.jsonl> <summary.json> [...] \\
        [--match-events <the match's events.jsonl> ...] [--out report.json] [--final-test]

Ground truth is read here only, for grading (docs/eval/scorebug-plan.md). Test seeds are refused,
as by ninety/eval/restart_score.py, unless `--final-test`.

- **Score changes.** The renderer shows a goal's new score from the goal's own frame (ninety/render/
  clip.py: the score counts goals with `t` at or before the frame's). Each true goal on a frame the
  clip shows is matched to a detected `score_change` of its side within event_score.WINDOW_S (1.0 s),
  one to one, nearest first: recall, precision (95% Wilson) and every timing error.
- **Digits.** Where the whole match's events are given (`--match-events`, one per clip, in order),
  each sampled reading is compared with the true score at its frame: the share of samples read
  right on both digits, of those read at all, and the share left unread.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ninety.eval.event_score import EPS, WINDOW_S, wilson
from ninety.eval.restart_score import refuse_test


def _jsonl(path: Path) -> list[dict]:
    return [json.loads(x) for x in path.read_text().splitlines() if x.strip()]


def rate(k: int, n: int) -> dict:
    return {"k": k, "n": n, "rate": round(k / n, 3) if n else None, "wilson95": wilson(k, n)}


def true_score(goals: list[dict], t: float) -> tuple[int, int]:
    return (sum(1 for g in goals if g["team"] == "home" and g["t"] <= t + EPS),
            sum(1 for g in goals if g["team"] == "away" and g["t"] <= t + EPS))


def score(items: list[tuple[Path, Path, Path, Path | None]], final_test: bool = False) -> dict:
    refuse_test([clip for clip, *_ in items], final_test)
    n_true = n_det = hits = 0
    dts, right, read, sampled, clips = [], 0, 0, 0, []
    refused = 0  # held reads that were not one goal on one side (down, or a jump): refused, counted
    for clip, found, summary_path, match_events in items:
        shown = {r["frame"]: r["t"] for r in _jsonl(clip / "frames.jsonl")}
        goals = [e for e in _jsonl(clip / "events.jsonl") if e["type"] == "goal" and e["frame"] in shown]
        det = [e for e in _jsonl(found) if e["type"] == "score_change"]
        cands = sorted((abs(d["t"] - g["t"]), i, j) for i, g in enumerate(goals) for j, d in enumerate(det)
                       if d["team"] == g["team"] and abs(d["t"] - g["t"]) <= WINDOW_S + EPS)
        used_g, used_d, pairs = set(), set(), []
        for _, i, j in cands:
            if i not in used_g and j not in used_d:
                used_g.add(i)
                used_d.add(j)
                pairs.append((goals[i], det[j]))
        n_true, n_det, hits = n_true + len(goals), n_det + len(det), hits + len(pairs)
        dts += [round(d["t"] - g["t"], 2) for g, d in pairs]
        refused += json.loads(summary_path.read_text()).get("inconsistent", 0)
        row = {"clip": clip.name, "goals": len(goals), "changes": len(det), "matched": len(pairs),
               "missed": [g["id"] for i, g in enumerate(goals) if i not in used_g],
               "false": [d["id"] for j, d in enumerate(det) if j not in used_d]}
        if match_events is not None:
            all_goals = [e for e in _jsonl(match_events) if e["type"] == "goal"]
            readings = json.loads(summary_path.read_text())["readings"]
            ok = seen = 0
            for frame, h, a in readings:
                if frame not in shown:
                    continue
                sampled += 1
                if h is None or a is None:
                    continue
                seen += 1
                ok += (h, a) == true_score(all_goals, shown[frame])
            right, read = right + ok, read + seen
            row["digits"] = {"right": ok, "read": seen}
        clips.append(row)
    return {
        "window_s": WINDOW_S,
        "changes": {"recall": rate(hits, n_true), "precision": rate(hits, n_det),
                    "timing_error_s": sorted(dts), "refused_reads": refused},
        "digits": ({"right_of_read": rate(right, read), "unread": rate(sampled - read, sampled)}
                   if sampled else None),
        "clips": clips,
    }


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Grade the scorebug reader against the answer key.")
    ap.add_argument("triples", nargs="+", type=Path, help="clip folder, score.jsonl, summary.json; repeated")
    ap.add_argument("--match-events", type=Path, action="append", default=None,
                    help="the whole match's events.jsonl, one per clip in order, for digit accuracy")
    ap.add_argument("--out", type=Path)
    ap.add_argument("--final-test", action="store_true", help="score test seeds: the plan's one look")
    a = ap.parse_args(argv)
    if len(a.triples) % 3:
        raise SystemExit("give a score.jsonl and a summary.json after each clip folder")
    trip = list(zip(a.triples[::3], a.triples[1::3], a.triples[2::3], strict=True))
    if a.match_events and len(a.match_events) != len(trip):
        raise SystemExit("give one --match-events per clip, in order")
    items = [(*t, a.match_events[i] if a.match_events else None) for i, t in enumerate(trip)]
    report = score(items, a.final_test)
    text = json.dumps(report, indent=2) + "\n"
    if a.out:
        a.out.write_text(text, encoding="utf-8")
    print(json.dumps({"changes": report["changes"], "digits": report["digits"]}))


if __name__ == "__main__":
    main()
