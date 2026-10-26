"""Grade detected restarts against the answer key: each kind, timed at the kick, and the free kicks' causes.

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

**Set pieces** are graded the same way, per kind. The answer key's `set_piece` carries no kind, so
it is read by #299's one rule (`set_piece_set.restart_kind`: from the stoppage before it), and a
detection matches only a true restart of its own kind. A true free kick's cause is its stoppage's
type (`offside`, or `foul`; a penalty is always a foul, so not graded); each matched free kick's
detected cause (`ninety.intel.restart_cause`) is tabled against it: offside read as offside, a foul read as
`foul_likely`, and how many were left `unknown`.

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
from ninety.eval.set_piece_set import STOPS, restart_kind
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


def truth_restarts(clip: Path) -> list[dict]:
    """Every true restart the clip shows the kick of: its kind (#299's rule), side, kick frame and
    time, and for a free kick its cause (the stoppage's type)."""
    frames = {r["frame"]: r for r in _jsonl(clip / "frames.jsonl")}
    out, stopped_by, last = [], None, None
    for e in sorted(_jsonl(clip / "events.jsonl"), key=lambda e: e["frame"]):
        if e["type"] in STOPS and stopped_by is None:
            stopped_by = e
            continue
        if e["type"] not in ("set_piece", "kickoff"):
            continue
        kind = restart_kind(stopped_by, e, last)
        cause = None  # a penalty is always a foul (Law 14), so only a free kick's cause is graded
        if kind == "free_kick":
            cause = "offside" if stopped_by and stopped_by["type"] == "offside" else "foul"
        last, stopped_by = (kind, e["x"], e["y"]), None
        k = kick_frame(e, frames)
        if k is not None:
            out.append({"id": e["id"], "kind": kind, "team": e["team"], "frame": k, "t": frames[k]["t"],
                        "cause": cause})
    return out


def truth_kickoffs(clip: Path) -> list[dict]:
    return [{k: r[k] for k in ("id", "team", "frame", "t")}
            for r in truth_restarts(clip) if r["kind"] == "kick_off"]


def detected_kind(e: dict) -> str | None:
    return "kick_off" if e["type"] == "kickoff" else e.get("restart") if e["type"] == "set_piece" else None


def match(truth: list[dict], detected: list[dict], sided: bool) -> list[tuple[dict, dict]]:
    cands = sorted((abs(d["t"] - t["t"]), i, j) for i, t in enumerate(truth) for j, d in enumerate(detected)
                   if abs(d["t"] - t["t"]) <= WINDOW_S + EPS
                   and (not sided or d["team"] == t["team"]))
    used_t, used_d, pairs = set(), set(), []
    for _, i, j in cands:
        if i not in used_t and j not in used_d:
            used_t.add(i)
            used_d.add(j)
            pairs.append((truth[i], detected[j]))
    return pairs


def rate(k: int, n: int) -> dict:
    return {"k": k, "n": n, "rate": round(k / n, 3) if n else None, "wilson95": wilson(k, n)}


KINDS = ("kick_off", "corner", "goal_kick", "throw_in", "free_kick", "penalty_kick")


def score(pairs_of_files: list[tuple[Path, Path]], final_test: bool = False) -> dict:
    """The kick-off report at the top (as first graded), each kind's under `by_kind`, and the free
    kicks' causes under `cause`."""
    refuse_test([clip for clip, _ in pairs_of_files], final_test)
    tally = {k: {"true": 0, "det": 0, "hits": 0, "hits_any": 0, "dts": []} for k in KINDS}
    clips, causes = [], {}
    for clip, found in pairs_of_files:
        truth_all = truth_restarts(clip)
        det_all = [e for e in _jsonl(found) if detected_kind(e) in KINDS]
        row = {"clip": clip.name}
        for kind in KINDS:
            truth = [t for t in truth_all if t["kind"] == kind]
            det = [e for e in det_all if detected_kind(e) == kind]
            sided, anyside = match(truth, det, True), match(truth, det, False)
            n = tally[kind]
            n["true"], n["det"] = n["true"] + len(truth), n["det"] + len(det)
            n["hits"], n["hits_any"] = n["hits"] + len(sided), n["hits_any"] + len(anyside)
            n["dts"] += [round(d["t"] - t["t"], 2) for t, d in sided]
            matched = {t["id"] for t, _ in sided}
            row[kind] = {"true": len(truth), "detected": len(det), "matched": len(sided),
                         "missed": [t for t in truth if t["id"] not in matched],
                         "false": [d["id"] for d in det if d["id"] not in {x["id"] for _, x in sided}]}
            if kind == "free_kick":
                for t, d in anyside:
                    key = f"{t['cause']}->{d.get('cause')}"
                    causes[key] = causes.get(key, 0) + 1
        clips.append(row)

    def report(kind: str) -> dict:
        n = tally[kind]
        return {"recall": rate(n["hits"], n["true"]), "precision": rate(n["hits"], n["det"]),
                "recall_any_side": rate(n["hits_any"], n["true"]),
                "precision_any_side": rate(n["hits_any"], n["det"]), "timing_error_s": sorted(n["dts"])}

    right = causes.get("offside->offside", 0) + causes.get("foul->foul_likely", 0)
    judged = sum(v for k, v in causes.items() if not k.endswith("->unknown"))
    return {
        "kind": "kick_off",
        "window_s": WINDOW_S,
        **report("kick_off"),
        "by_kind": {k: report(k) for k in KINDS},
        "cause": {"table": dict(sorted(causes.items())), "right": rate(right, judged),
                  "unknown": sum(v for k, v in causes.items() if k.endswith("->unknown"))},
        "clips": [{"clip": c["clip"]} | c["kick_off"] for c in clips],
        "all_clips": clips,
    }


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Grade detected kick-offs against the answer key.")
    ap.add_argument("pairs", nargs="+", type=Path, help="clip folder, then its restarts.jsonl, repeated")
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--final-test", action="store_true",
                    help="score test seeds (900001-900030, the shot-outcome and set-piece test splits): once")
    a = ap.parse_args(argv)
    if len(a.pairs) % 2:
        raise SystemExit("give a restarts file after each clip folder")
    report = score(list(zip(a.pairs[::2], a.pairs[1::2], strict=True)), a.final_test)
    text = json.dumps(report, indent=2) + "\n"
    if a.out:
        a.out.write_text(text, encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("recall", "precision", "timing_error_s")}))


if __name__ == "__main__":
    main()
