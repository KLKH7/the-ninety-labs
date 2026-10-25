"""Grade detected restarts against the answer key: kick-offs, timed at the kick.

    uv run python -m ninety.eval.restart_score <clip> <restarts.jsonl> [<clip> <restarts.jsonl> ...] \\
        [--out report.json]

Each clip is a rendered clip folder with its answer key (frames.jsonl, events.jsonl, meta.json);
each restarts file is what `ninety.vision.restarts` wrote for it. Ground truth is read here, for
grading only; the detector never sees it (docs/eval/restarts-vision-plan.md).

**When a kick-off happens.** The engine writes its `kickoff` event when the taker stands set at the
ball, and he plays it 0.5 to 1.5 s or more later (ninety/sim/engine.py, the restart's hold), while
Law 8 puts the ball in play when it is kicked and clearly moves, the moment the video shows. So a
true kick-off is timed at its kick: the last frame, from its event on, before the true ball first
leaves the centre mark. A detection matches a true kick-off within event_score.WINDOW_S (1.0 s) of
that kick, one to one, nearest first, as event_score matches events. A true kick-off counts only
when its kick is on a frame the clip shows.

Headline: recall and precision with the side right (type and team, as event_score grades every
event), with 95% Wilson intervals; beside them, the same with the side not asked, and the timing
error of each match.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from ninety.eval.event_score import EPS, WINDOW_S, wilson

# The true ball has left its spot once it is this far from it: well under one frame of a kicked
# ball's travel (event-motion.md: about 0.4 m a frame after a pass), and above the rounding of
# positions in frames.jsonl (cm).
MOVED_M = 0.05


def _jsonl(path: Path) -> list[dict]:
    return [json.loads(x) for x in path.read_text().splitlines() if x.strip()]


def kick_frame(event: dict, frames: dict[int, dict]) -> int | None:
    """The frame the true kick-off was kicked: the last frame from the event on before the true
    ball first leaves where it lay at the event. None when the clip does not show it."""
    f = event["frame"]
    if f not in frames:
        return None
    b0 = frames[f]["ball"]
    while f + 1 in frames:
        b = frames[f + 1]["ball"]
        if math.hypot(b["x"] - b0["x"], b["y"] - b0["y"]) > MOVED_M:
            return f
        f += 1
    return None  # the clip ends with the ball still on the mark: the kick is not shown


def truth_kickoffs(clip: Path) -> list[dict]:
    frames = {r["frame"]: r for r in _jsonl(clip / "frames.jsonl")}
    out = []
    for e in _jsonl(clip / "events.jsonl"):
        if e["type"] != "kickoff":
            continue
        k = kick_frame(e, frames)
        if k is not None:
            out.append({"id": e["id"], "team": e["team"], "frame": k, "t": frames[k]["t"]})
    return out


def match(truth: list[dict], detected: list[dict], sided: bool) -> list[tuple[dict, dict]]:
    cands = sorted((abs(d["t"] - t["t"]), i, j) for i, t in enumerate(truth) for j, d in enumerate(detected)
                   if d["type"] == "kickoff" and abs(d["t"] - t["t"]) <= WINDOW_S + EPS
                   and (not sided or d["team"] == t["team"]))
    used_t, used_d, pairs = set(), set(), []
    for _, i, j in cands:
        if i not in used_t and j not in used_d:
            used_t.add(i)
            used_d.add(j)
            pairs.append((truth[i], detected[j]))
    return pairs


def score(pairs_of_files: list[tuple[Path, Path]]) -> dict:
    clips, n_true, n_det, hits, hits_any, dts = [], 0, 0, 0, 0, []
    for clip, found in pairs_of_files:
        truth = truth_kickoffs(clip)
        det = [e for e in _jsonl(found) if e["type"] == "kickoff"]
        sided, anyside = match(truth, det, True), match(truth, det, False)
        n_true, n_det, hits, hits_any = n_true + len(truth), n_det + len(det), hits + len(sided), \
            hits_any + len(anyside)
        dts += [round(d["t"] - t["t"], 2) for t, d in sided]
        matched = {t["id"] for t, _ in sided}
        clips.append({
            "clip": clip.name, "true": len(truth), "detected": len(det), "matched": len(sided),
            "missed": [t for t in truth if t["id"] not in matched],
            "false": [d["id"] for d in det if d["id"] not in {x["id"] for _, x in sided}],
        })

    def rate(k: int, n: int) -> dict:
        return {"k": k, "n": n, "rate": round(k / n, 3) if n else None, "wilson95": wilson(k, n)}

    return {
        "kind": "kickoff",
        "window_s": WINDOW_S,
        "recall": rate(hits, n_true),
        "precision": rate(hits, n_det),
        "recall_any_side": rate(hits_any, n_true),
        "precision_any_side": rate(hits_any, n_det),
        "timing_error_s": sorted(dts),
        "clips": clips,
    }


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Grade detected kick-offs against the answer key.")
    ap.add_argument("pairs", nargs="+", type=Path, help="clip folder, then its restarts.jsonl, repeated")
    ap.add_argument("--out", type=Path, default=None)
    a = ap.parse_args(argv)
    if len(a.pairs) % 2:
        raise SystemExit("give a restarts file after each clip folder")
    report = score(list(zip(a.pairs[::2], a.pairs[1::2], strict=True)))
    text = json.dumps(report, indent=2) + "\n"
    if a.out:
        a.out.write_text(text, encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("recall", "precision", "timing_error_s")}))


if __name__ == "__main__":
    main()
