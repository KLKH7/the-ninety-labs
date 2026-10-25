"""Grade detected restarts against the answer key: kick-offs, timed at the kick.

    uv run python -m ninety.eval.restart_score <clip> <restarts.jsonl> [<clip> <restarts.jsonl> ...] \\
        [--out report.json] [--final-test]

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

**Test seeds are refused.** A clip whose seed (meta.json's, else the digits ending its folder's
name) is a test seed, of the fixed test set (900001 to 900030), the shot-outcome set's test half or
the set-piece set's test split (920201 to 920230), or whose seed cannot be read, is refused unless
`--final-test` is given: the plan scores the test split once, at a frozen commit. Validation clips
(the set-piece set's 920101 to 920115) are graded freely.

Headline: recall and precision with the side right (type and team, as event_score grades every
event), with 95% Wilson intervals; beside them, the same with the side not asked, and the timing
error of each match.

**Set pieces** (`--set-pieces`), by the plan's rule for them: each true `set_piece` is timed at its
kick as a kick-off is (`kick_frame`), its kind read from the answer key by `restart_kind`
(ninety/eval/set_piece_set.py: the event that stopped play and where the ball was placed), and a
detection matches with the same kind (`restart`) and side within WINDOW_S of that kick. Beside the
headline: the kind not asked, the side not asked, and a confusion table of the kinds over the
detections matched on time alone.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from ninety.eval.event_score import EPS, WINDOW_S, wilson
from ninety.eval.shot_flight import clip_seed
from ninety.eval.shot_flight import sealed_seeds as _sealed

# The true ball has left its spot once it is this far from it: well under one frame of a kicked
# ball's travel (event-motion.md: about 0.4 m a frame after a pass), and above the rounding of
# positions in frames.jsonl (cm).
MOVED_M = 0.05


def sealed_seeds() -> set[int]:
    """Every test split's seeds: the shot-flight scorer's (the fixed test set and the shot-outcome
    set's test half) and the set-piece set's test split."""
    from ninety.eval.set_piece_set import TEST
    return _sealed() | set(TEST)


def refuse_test(clips: list[Path], final_test: bool) -> None:
    """Stop unless every clip is known not to be a test clip, or this is the final test look."""
    if final_test:
        return
    sealed = sealed_seeds()
    for clip in clips:
        seed = clip_seed(clip)
        if seed is None:
            raise SystemExit(f"refused: {clip} has no seed to check against the test splits")
        if seed in sealed:
            raise SystemExit(f"refused: {clip} is test seed {seed}: scored once, with --final-test")


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


def match(truth: list[dict], detected: list[dict], sided: bool,
          kinded: bool = False) -> list[tuple[dict, dict]]:
    cands = sorted((abs(d["t"] - t["t"]), i, j) for i, t in enumerate(truth) for j, d in enumerate(detected)
                   if abs(d["t"] - t["t"]) <= WINDOW_S + EPS
                   and (not sided or d["team"] == t["team"])
                   and (not kinded or d.get("restart") == t["kind"]))
    used_t, used_d, pairs = set(), set(), []
    for _, i, j in cands:
        if i not in used_t and j not in used_d:
            used_t.add(i)
            used_d.add(j)
            pairs.append((truth[i], detected[j]))
    return pairs


def score(pairs_of_files: list[tuple[Path, Path]], final_test: bool = False) -> dict:
    refuse_test([clip for clip, _ in pairs_of_files], final_test)
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


def truth_set_pieces(clip: Path) -> list[dict]:
    """Every true set piece whose kick the clip shows, timed at the kick, with its kind."""
    from ninety.eval.set_piece_set import restarts

    events = _jsonl(clip / "events.jsonl")
    frames = {r["frame"]: r for r in _jsonl(clip / "frames.jsonl")}
    kind_at = {r["frame"]: r["kind"] for r in restarts(events)}
    out = []
    for e in events:
        if e["type"] != "set_piece":
            continue
        k = kick_frame(e, frames)
        if k is not None:
            out.append({"id": e["id"], "team": e["team"], "kind": kind_at[e["frame"]],
                        "event_frame": e["frame"], "frame": k, "t": frames[k]["t"], "x": e["x"], "y": e["y"]})
    return out


def score_set_pieces(pairs_of_files: list[tuple[Path, Path]], final_test: bool = False) -> dict:
    from ninety.eval.set_piece_set import KINDS

    refuse_test([clip for clip, _ in pairs_of_files], final_test)
    kinds = [k for k in KINDS if k != "kick_off"]
    ways = {"kind_and_side": (True, True), "kind_only": (False, True), "side_only": (True, False),
            "time_only": (False, False)}
    hits = dict.fromkeys(ways, 0)
    n_true = n_det = 0
    confusion = {k: dict.fromkeys((*kinds, "missed"), 0) for k in kinds}
    per_kind = {k: {"true": 0, "found": 0} for k in kinds}
    clips, dts = [], []
    for clip, found in pairs_of_files:
        truth = truth_set_pieces(clip)
        det = [e for e in _jsonl(found) if e["type"] == "set_piece"]
        n_true, n_det = n_true + len(truth), n_det + len(det)
        pairs = {w: match(truth, det, sided, kinded) for w, (sided, kinded) in ways.items()}
        for w in ways:
            hits[w] += len(pairs[w])
        dts += [round(d["t"] - t["t"], 2) for t, d in pairs["kind_and_side"]]
        on_time = {t["id"]: d for t, d in pairs["time_only"]}
        right = {t["id"] for t, _ in pairs["kind_and_side"]}
        for t in truth:
            per_kind[t["kind"]]["true"] += 1
            per_kind[t["kind"]]["found"] += t["id"] in right
            d = on_time.get(t["id"])
            confusion[t["kind"]][(d.get("restart") or "missed") if d else "missed"] += 1
        used = {d["id"] for _, d in pairs["kind_and_side"]}
        clips.append({
            "clip": clip.name, "true": len(truth), "detected": len(det), "matched": len(right),
            "restarts": [{**t, "found": on_time[t["id"]]["restart"] if t["id"] in on_time else None,
                          "side_found": on_time[t["id"]]["team"] if t["id"] in on_time else None,
                          "dt_s": round(on_time[t["id"]]["t"] - t["t"], 2) if t["id"] in on_time else None,
                          "matched": t["id"] in right} for t in truth],
            "false": [{"id": d["id"], "frame": d["frame"], "team": d["team"], "restart": d.get("restart"),
                       "x": d["x"], "y": d["y"]} for d in det if d["id"] not in used],
        })

    def rate(k: int, n: int) -> dict:
        return {"k": k, "n": n, "rate": round(k / n, 3) if n else None, "wilson95": wilson(k, n)}

    return {
        "kind": "set_piece",
        "window_s": WINDOW_S,
        "recall": rate(hits["kind_and_side"], n_true),
        "precision": rate(hits["kind_and_side"], n_det),
        **{f"recall_{w}": rate(hits[w], n_true) for w in ("kind_only", "side_only", "time_only")},
        "per_kind": per_kind,
        "confusion": confusion,
        "timing_error_s": sorted(dts),
        "clips": clips,
    }


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Grade detected kick-offs against the answer key.")
    ap.add_argument("pairs", nargs="+", type=Path, help="clip folder, then its restarts.jsonl, repeated")
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--set-pieces", action="store_true",
                    help="grade set pieces and their kind instead of kick-offs")
    ap.add_argument("--final-test", action="store_true",
                    help="score test seeds (900001-900030, the shot-outcome and set-piece test splits): once")
    a = ap.parse_args(argv)
    if len(a.pairs) % 2:
        raise SystemExit("give a restarts file after each clip folder")
    grade = score_set_pieces if a.set_pieces else score
    report = grade(list(zip(a.pairs[::2], a.pairs[1::2], strict=True)), a.final_test)
    text = json.dumps(report, indent=2) + "\n"
    if a.out:
        a.out.write_text(text, encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("recall", "precision", "timing_error_s")}))


if __name__ == "__main__":
    main()
