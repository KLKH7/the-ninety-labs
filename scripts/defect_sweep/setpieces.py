"""Set pieces at the kick (lesson 202).

    uv run python scripts/defect_sweep/setpieces.py runs/new/seed7 runs/new/seed11 ...

From each run's frames.jsonl and events.jsonl (simulated matches, ground truth):
- each corner: the defending and attacking outfielders in the penalty area at the kick (Law 1:
  16.5 m deep, 40.32 m wide), the share of box players standing (under 0.2 m/s) over the 5 s before
  the kick, their mean speed in the second before and the second after it, and the taker's speed at
  the kick, the distance he covered in the 2 s before it and his top speed then (his run-up);
- each free kick within 35 m of the goal it is at: the attackers in the penalty area at the kick;
- restarts of each kind per team per 90 minutes (held out: GROUNDING R1).
Prints one JSON object: totals, then a row per corner and per free kick.
"""

import json
import math
import sys
from collections import Counter
from pathlib import Path

PX, PY, FPS = 105.0, 68.0, 25
AREA_DEPTH_M, AREA_HALF_M = 16.5, 20.16  # Law 1
FK_RANGE_M = 35.0  # free kicks this close to the goal's centre are counted


def kind(e: dict) -> str:
    """Which restart a set_piece event is, from where it was taken."""
    x, y = e["x"], e["y"]
    if y <= 0 or y >= PY:
        return "throw_in"
    if (x <= 0.6 or x >= PX - 0.6) and (y <= 0.6 or y >= PY - 0.6):
        return "corner"
    if abs(y - PY / 2) < 0.01 and (abs(x - 5.5) < 0.01 or abs(x - (PX - 5.5)) < 0.01):
        return "goal_kick"
    return "free_kick"


def in_box(p: dict, line: float) -> bool:
    return abs(p["x"] - line) <= AREA_DEPTH_M and abs(p["y"] - PY / 2) <= AREA_HALF_M


def mean(xs: list) -> float | None:
    xs = [x for x in xs if x is not None]
    return round(sum(xs) / len(xs), 2) if xs else None


def corner_row(e: dict, kick: dict, by: dict, line: float) -> dict:
    taker = next(p for p in by[kick["frame"]]["players"] if p["id"] == e["player"])
    still = total = 0
    for n in range(kick["frame"] - 5 * FPS, kick["frame"]):
        for p in by[n]["players"] if n in by else []:
            if p["role"] != "GK" and in_box(p, line) and p["id"] != e["player"]:
                total += 1
                still += math.hypot(p["vx"], p["vy"]) < 0.2
    speeds = []
    for lo, hi in ((-FPS, 0), (0, FPS)):
        sp = [math.hypot(p["vx"], p["vy"]) for n in range(kick["frame"] + lo, kick["frame"] + hi)
              if n in by for p in by[n]["players"] if p["role"] != "GK" and in_box(p, line)]
        speeds.append(round(sum(sp) / max(len(sp), 1), 2))
    back = by.get(kick["frame"] - 2 * FPS)
    was = next((p for p in back["players"] if p["id"] == e["player"]), None) if back else None
    peak = max(math.hypot(q["vx"], q["vy"]) for n in range(kick["frame"] - 2 * FPS, kick["frame"] + 1)
               if n in by for q in by[n]["players"] if q["id"] == e["player"])
    run = round(math.hypot(taker["x"] - was["x"], taker["y"] - was["y"]), 2) if was else None
    return {"box_still_5s": round(still / max(total, 1), 2), "box_mps_1s_before": speeds[0],
            "box_mps_1s_after": speeds[1], "taker_mps": round(math.hypot(taker["vx"], taker["vy"]), 2),
            "taker_run_2s_m": run,
            "taker_peak_2s_mps": round(peak, 2)}


def main() -> None:
    rates, minutes, corners, fks = Counter(), 0.0, [], []
    for run in map(Path, sys.argv[1:]):
        events = [json.loads(line) for line in open(run / "events.jsonl")]
        frames = [json.loads(line) for line in open(run / "frames.jsonl")]
        by = {f["frame"]: f for f in frames}
        minutes += len(frames) / FPS / 60
        for i, e in enumerate(events):
            if e["type"] != "set_piece":
                continue
            k = kind(e)
            rates[k] += 1
            kick = next((x for x in events[i + 1:] if x["type"] in ("pass", "shot")), None)
            if k not in ("corner", "free_kick") or kick is None:
                continue
            line = PX if e["team"] == "home" else 0.0
            if k == "free_kick" and math.hypot(line - e["x"], PY / 2 - e["y"]) > FK_RANGE_M:
                continue
            out = [p for p in by[kick["frame"]]["players"] if p["role"] != "GK" and in_box(p, line)]
            attackers = sum(p["team"] == e["team"] for p in out)
            row = {"run": run.name, "t": kick["t"], "att": attackers, "def": len(out) - attackers}
            if k == "corner":
                corners.append(row | corner_row(e, kick, by, line))
            else:
                fks.append(row)
    print(json.dumps({
        "match_minutes": round(minutes),
        "per_team_per_90": {k: round(v / minutes * 90 / 2, 2) for k, v in rates.items()},
        "corners": len(corners),
        "corner_def_minus_att_mean": mean([c["def"] - c["att"] for c in corners]),
        "corners_def_gt_att": sum(c["def"] > c["att"] for c in corners),
        "corner_box_still_5s_mean": mean([c["box_still_5s"] for c in corners]),
        "corner_box_mps_1s_before": mean([c["box_mps_1s_before"] for c in corners]),
        "corner_box_mps_1s_after": mean([c["box_mps_1s_after"] for c in corners]),
        "corner_taker_mps_mean": mean([c["taker_mps"] for c in corners]),
        "corner_taker_run_2s_m_mean": mean([c["taker_run_2s_m"] for c in corners]),
        "corner_taker_peak_2s_mps_mean": mean([c["taker_peak_2s_mps"] for c in corners]),
        "attacking_fks_35m": len(fks),
        "fks_no_attacker_in_box": sum(f["att"] == 0 for f in fks),
        "fk_att_in_box_mean": mean([f["att"] for f in fks]),
        "corner_rows": corners, "fk_rows": fks}, indent=1))


if __name__ == "__main__":
    main()
