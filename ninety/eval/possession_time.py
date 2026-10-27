"""Possession as time on the ball (ninety/intel/ball_share.py) against the answer key, offline.

    uv run python -m ninety.eval.possession_time --match 8080 <tracked.json> <truth> \\
        --match 8324 <tracked.json> <truth> --out docs/eval/possession-time

Grading, so it reads the answer key; nothing on the live path imports it. The plan, fixed before
any score: docs/eval/possession-time-plan.md. `<truth>` is the simulated run's directory
(frames.jsonl and events.jsonl) or a footage-hunt compact.npz with its events.jsonl beside it.

The truth at a frame: the side of the answer key's latest possessor, carried to the next, over the
frames the footage shows; nobody's during a dead ball (from an out_of_play, goal, foul, offside or
half_time event to the next set_piece or kickoff) and while the true ball is beyond a line.
"""

from __future__ import annotations

import argparse
import datetime
import json
import statistics
from pathlib import Path

from ninety.eval.event_score import git_commit
from ninety.intel import ball_share
from ninety.intel.match_insights import HALF_MIN
from ninety.intel.scene import PITCH_X, PITCH_Y, TEAMS, minute_of
from ninety.intel.team_stats import BIN_MIN

COMMAND = "uv run python -m ninety.eval.possession_time"
GATE_MAE = 5.0  # pre-registered (docs/eval/possession-time-plan.md)
DEAD_FROM = {"out_of_play", "goal", "foul", "offside", "half_time"}
DEAD_TO = {"set_piece", "kickoff"}


def truth_frames(truth: Path) -> tuple[dict[int, tuple[str, float, float]], list[dict]]:
    """frame -> (possessor id or "", true ball x, y), and the answer key's events."""
    if truth.suffix == ".npz":
        import numpy as np

        z = np.load(truth)
        poss, ball = z["poss"], z["ball"]  # each z[...] decompresses the whole array: once
        out = {i: (str(poss[i]), float(ball[i][1]), float(ball[i][2])) for i in range(len(poss))}
        ev_path = truth.parent / "events.jsonl"
    else:
        out = {}
        with (truth / "frames.jsonl").open() as fh:
            for line in fh:
                r = json.loads(line)
                b = r["ball"]
                out[int(r["frame"])] = (r.get("possessor") or "", float(b["x"]), float(b["y"]))
        ev_path = truth / "events.jsonl"
    events = [json.loads(x) for x in ev_path.read_text().splitlines() if x.strip()]
    return out, events


def truth_sides(frames: dict[int, tuple[str, float, float]], events: list[dict]) -> dict[int, str | None]:
    """Each answer-key frame's side in possession, or None (dead ball, or nobody yet)."""
    dead = []
    evs = sorted(events, key=lambda e: e["frame"])
    for i, e in enumerate(evs):
        if e["type"] in DEAD_FROM:
            end = next((f["frame"] for f in evs[i + 1:] if f["type"] in DEAD_TO), None)
            dead.append((int(e["frame"]), int(end) if end is not None else 1_000_000_000))
    dead_at = set()
    last = max(frames)
    for a, b in dead:
        dead_at.update(range(a, min(b, last + 1)))
    out, team = {}, None
    for n in sorted(frames):
        who, x, y = frames[n]
        out_of_bounds = not (0 <= x <= PITCH_X and 0 <= y <= PITCH_Y)
        if n in dead_at or out_of_bounds:
            team = None
            out[n] = None
            continue
        if who:
            team = "home" if who.startswith("h") else "away"
        out[n] = team
    return out


def windows(minutes: int) -> list[tuple[str, int, int]]:
    return [("first half", 1, HALF_MIN), ("second half", HALF_MIN + 1, minutes), ("full match", 1, minutes)]


def grade_match(seed: str, tracked: Path, truth: Path) -> dict:
    frames = json.loads(tracked.read_text())["frames"]
    rows = ball_share.possession_rows(frames)
    tf, tev = truth_frames(truth)
    side = truth_sides(tf, tev)
    true_min: dict[int, dict] = {}
    for fr in frames:
        n = int(fr["frame"])
        m = minute_of(float(fr["t"]))
        r = true_min.setdefault(m, {k: 0 for k in TEAMS})
        s = side.get(n)
        if s:
            r[s] += 1
    minutes = max(r["minute"] for r in rows)

    def true_share(lo: int, hi: int) -> float | None:
        h = sum(v["home"] for m, v in true_min.items() if lo <= m <= hi)
        a = sum(v["away"] for m, v in true_min.items() if lo <= m <= hi)
        return 100 * h / (h + a) if h + a else None

    out = []
    for name, lo, hi in windows(minutes):
        got = ball_share.possession(rows, lo, hi)
        live = got.get("home", {}).get("value")
        truth_v = true_share(lo, hi)
        out.append({"window": name, "minute_from": lo, "minute_to": hi, "live_home": live,
                    "true_home": round(truth_v, 1) if truth_v is not None else None,
                    "seconds": got.get("home", {}).get("also", [[None]])[0][0],
                    "error": (round(abs(live - truth_v), 1)
                              if live is not None and truth_v is not None else None)})
    so_far = []
    for m in range(BIN_MIN, minutes + BIN_MIN, BIN_MIN):
        hi = min(m, minutes)
        live = ball_share.possession(rows, 1, hi).get("home", {}).get("value")
        tv = true_share(1, hi)
        if live is not None and tv is not None:
            so_far.append(abs(live - tv))
    return {"seed": seed, "windows": out, "so_far_bins": len(so_far),
            "so_far_mae": round(statistics.fmean(so_far), 2) if so_far else None,
            "so_far_max": round(max(so_far), 1) if so_far else None}


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--match", nargs=3, action="append", required=True, metavar=("SEED", "TRACKED", "TRUTH"))
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args(argv)
    matches = [grade_match(s, Path(t), Path(tr)) for s, t, tr in args.match]
    errs = [w["error"] for m in matches for w in m["windows"] if w["error"] is not None]
    mae = round(statistics.fmean(errs), 2) if errs else None
    body = {
        "plan": "docs/eval/possession-time-plan.md",
        "command": COMMAND,
        "commit": git_commit(),
        "date": datetime.date.today().isoformat(),
        "gate": {"mae_points_at_most": GATE_MAE, "mae": mae, "max_error": max(errs) if errs else None,
                 "windows": len(errs), "met": mae is not None and mae <= GATE_MAE},
        "matches": matches,
    }
    args.out.with_suffix(".json").write_text(json.dumps(body, indent=1) + "\n")
    print(json.dumps(body["gate"]))
    for m in matches:
        print(m["seed"], [(w["window"], w["live_home"], w["true_home"]) for w in m["windows"]],
              "so far MAE", m["so_far_mae"])


if __name__ == "__main__":
    main()
