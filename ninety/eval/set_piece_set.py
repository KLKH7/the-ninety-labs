"""The set-piece set's clips (docs/eval/set-piece-set.md), from its matches' answer keys.

    uv run python -m ninety.eval.set_piece_set --sims <dir of seed<N>/{events.jsonl,meta.json}> \\
        --out docs/eval/set-piece-set.json

Every restart of a match gets a window in the broadcast as a viewer sees it (the edit's cut through
the dead ball, ninety/render/edit.py): from BEFORE_S before the event that stopped play to AFTER_S
after the restart, its length the frames the render shows. A window starting inside the last joins
it, up to MAX_S shown; one that would run longer is dropped. Then a fixed subset is kept (the
render budget): matches in seed order, windows in time order, a window while any kind of restart it
holds is short of its split's target. Nothing is chosen by hand. The output lists each clip's
split, seed, start and length, and the totals per split; which clip holds which kind is not
written, so the test split's labels stay unread until it is scored.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ninety.render import edit
from ninety.sim.engine import FPS, PENALTY_MARK_M, PITCH_X, PITCH_Y

NAME = "set-piece-set"
RENDER_COMMIT = "ac21ccc76e815d308490eaf6aa73fb199324affa"
VALIDATION = tuple(range(920101, 920116))
TEST = tuple(range(920201, 920231))
MINUTES = 35  # each match is simulated this long
LAST_END_S = 32 * 60.0  # windows end by here: the render's SIM_MARGIN_S (180 s) is simulated past them
KINDS = ("throw_in", "goal_kick", "corner", "free_kick", "penalty_kick", "kick_off")
# The plan's offsets (design): 2 s of play before the stoppage; 6 s after the restart, the kick and
# its first touch. A run of restarts joins into one window of at most MAX_S shown.
BEFORE_S = 2.0
AFTER_S = 6.0
MAX_S = 30.0
# The plan's targets per split (design: the render budget; a penalty is kept wherever it comes).
TARGET = {"validation": 15, "test": 30}
EVERY = ("penalty_kick",)
# Law 1 and Law 14: the penalty mark is PENALTY_MARK_M out on the goal's centre line; the engine
# places the ball on it exactly, the files round it to the centimetre, so 0.5 m (design) is ample.
MARK_TOL_M = 0.5
# Law 15: a throw-in is given where the ball crossed a touchline; the engine writes the out_of_play
# event there, at y = 0 or 68 to the files' rounding (design: 1 cm).
LINE_TOL_M = 0.01
# Law 16: a goal kick is placed in the goal area, 5.5 m out; Law 17: a corner within the corner
# area, 1 m from the flag (the engine places it 0.5 m inside the lines). 2 m (design) tells them apart.
CORNER_X_M = 2.0
STOPS = edit.STOPS


def restart_kind(stopped_by: dict | None, restart: dict, last: tuple[str, float, float] | None) -> str:
    """The kind of a `set_piece` or `kickoff` event, from the event that stopped play since the
    last restart (None if none) and the last restart (kind, x, y). A set piece with no stoppage
    since the last, from that restart's own spot to the files' rounding, is that restart taken again
    (Law 15's retake of a foul throw)."""
    if restart["type"] == "kickoff":
        return "kick_off"
    x, y = restart["x"], restart["y"]
    if stopped_by is None and last is not None and abs(x - last[1]) <= 0.05 and abs(y - last[2]) <= 0.05:
        return last[0]
    if stopped_by is None or stopped_by["type"] in ("foul", "offside"):
        on_mark = abs(y - PITCH_Y / 2) <= MARK_TOL_M and min(abs(x - PENALTY_MARK_M),
                                                            abs(x - (PITCH_X - PENALTY_MARK_M))) <= MARK_TOL_M
        if on_mark and (stopped_by is None or stopped_by["type"] == "foul"):
            return "penalty_kick"
        return "free_kick"
    if stopped_by["y"] <= LINE_TOL_M or stopped_by["y"] >= PITCH_Y - LINE_TOL_M:
        return "throw_in"
    return "goal_kick" if min(x, PITCH_X - x) > CORNER_X_M else "corner"


def restarts(events: list[dict]) -> list[dict]:
    """[{frame, kind, stop}] for every restart in time order; `stop` is the frame of the event that
    stopped play since the last restart, None if none (the kick-off that starts the match)."""
    out: list[dict] = []
    stopped_by: dict | None = None
    last: tuple[str, float, float] | None = None
    for e in sorted(events, key=lambda e: e["frame"]):
        if e["type"] in STOPS and stopped_by is None:
            stopped_by = e
        elif e["type"] in edit.RESTARTS:
            kind = restart_kind(stopped_by, e, last)
            out.append({"frame": e["frame"], "kind": kind,
                        "stop": stopped_by["frame"] if stopped_by else None})
            last = (kind, e["x"], e["y"])
            stopped_by = None
    return out


def shown_length(start: int, end: int, cuts: list[edit.Cut], frames: int) -> int | None:
    """The fewest frames a broadcast clip from `start` shows (the render's own edit.plan) to reach
    match frame `end` or past it (past it when `end` falls in a cut), or None if the match ends
    first. More frames reach further, so the count is found by bisection, then checked."""
    def reach(n: int) -> int:
        show, _ = edit.plan(start, n, cuts, frames)
        return show[-1] if len(show) == n else -1

    lo, hi = 1, end - start + 1  # with no cut, end - start + 1 frames reach `end` exactly
    if reach(hi) < end:
        return None
    while lo < hi:
        mid = (lo + hi) // 2
        if reach(mid) >= end:
            hi = mid
        else:
            lo = mid + 1
    if hi > 1 and reach(hi - 1) >= end:  # pragma: no cover - plan reaches further with more frames
        raise AssertionError(f"edit.plan is not monotone from frame {start}")
    return hi


def windows(events: list[dict], match_s: float) -> tuple[list[dict], int]:
    """([{start, seconds, kinds}] in match seconds on whole frames, the number dropped): one window
    per restart, joined where the next starts inside the last up to MAX_S shown, inside the match
    and ending by LAST_END_S."""
    frames = int(round(match_s * FPS))
    cuts = edit.cuts(events, FPS)
    out: list[dict] = []
    dropped = 0
    for r in restarts(events):
        start = max(0, (r["stop"] if r["stop"] is not None else r["frame"]) - round(BEFORE_S * FPS))
        end = r["frame"] + round(AFTER_S * FPS)
        if end > round(LAST_END_S * FPS):
            continue
        last = out[-1] if out else None
        if last and start <= last["_end"]:
            n = shown_length(last["_start"], end, cuts, frames)
            if n is not None and n <= round(MAX_S * FPS):
                last.update(_end=end, _n=n)
                last["kinds"].append(r["kind"])
            else:
                dropped += 1
            continue
        n = shown_length(start, end, cuts, frames)
        if n is None:
            continue
        out.append({"_start": start, "_end": end, "_n": n, "kinds": [r["kind"]]})
    return [{"start": round(w["_start"] / FPS, 2), "seconds": round(w["_n"] / FPS, 2), "kinds": w["kinds"]}
            for w in out], dropped


def subset(per_seed: list[tuple[int, list[dict]]], target: int) -> list[tuple[int, dict]]:
    """Seeds in the order given, windows in time order: a window is kept while any kind it holds is
    short of `target` (every kind in EVERY is always short)."""
    have = dict.fromkeys(KINDS, 0)
    kept = []
    for seed, ws in per_seed:
        for w in ws:
            if any(k in EVERY or have[k] < target for k in w["kinds"]):
                kept.append((seed, w))
                for k in w["kinds"]:
                    have[k] += 1
    return kept


def load_match(d: Path) -> tuple[list[dict], float]:
    events = [json.loads(x) for x in (d / "events.jsonl").read_text().splitlines() if x.strip()]
    return events, json.loads((d / "meta.json").read_text())["minutes"] * 60


def build(sims: Path) -> dict:
    clips, totals, dropped = [], {}, {}
    for split, seeds in (("validation", VALIDATION), ("test", TEST)):
        per_seed, dropped[split] = [], 0
        for s in seeds:
            events, match_s = load_match(sims / f"seed{s}")
            if match_s < MINUTES * 60:
                raise ValueError(f"seed {s} was simulated for {match_s / 60} minutes, not {MINUTES}")
            ws, n = windows(events, MINUTES * 60.0)
            per_seed.append((s, ws))
            dropped[split] += n
        kept = subset(per_seed, TARGET[split])
        totals[split] = {k: sum(w["kinds"].count(k) for _, w in kept) for k in KINDS}
        clips += [{"split": split, "seed": s, "start": w["start"], "seconds": w["seconds"]} for s, w in kept]
    render = {"views": None, "set": ["stadium=broadcast", "dead_ball_cut=true"]}
    count = {k: sum(1 for c in clips if c["split"] == k) for k in ("validation", "test")}
    return {"name": NAME, "render_commit": RENDER_COMMIT, "render": render, "minutes": MINUTES,
            "last_end_s": LAST_END_S, "before_s": BEFORE_S, "after_s": AFTER_S, "max_s": MAX_S,
            "target": TARGET, "every": list(EVERY),
            "splits": {"validation": list(VALIDATION), "test": list(TEST)},
            "clips": clips, "count": count, "restarts": totals, "dropped_overlap": dropped,
            "seconds": round(sum(c["seconds"] for c in clips), 2)}


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="The set-piece set's clips, from its matches' answer keys.")
    ap.add_argument("--sims", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--check", action="store_true", help="rebuild and fail unless --out has the same bytes")
    a = ap.parse_args(argv)
    m = build(a.sims)
    text = json.dumps(m, indent=1) + "\n"
    if a.check:
        if a.out.read_text() != text:
            raise SystemExit(f"{a.out} is not what the rule gives on these matches")
    else:
        a.out.write_text(text)
    print(json.dumps({"count": m["count"], "restarts": m["restarts"], "seconds": m["seconds"]}))


if __name__ == "__main__":
    main()
