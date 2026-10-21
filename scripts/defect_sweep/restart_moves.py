"""How outfielders move while restarts wait (docs/eval/restarts.md, "Walking to restart positions").

    uv run python scripts/defect_sweep/restart_moves.py runs/new/seed7 runs/new/seed11 ...

From each run's frames.jsonl and events.jsonl (simulated matches, ground truth), over every restart's
wait (from the stoppage to the kick, under 200 s), for each outfielder but the taker, per minute:
- speed shares: standing (under 0.2 m/s), creeping (0.2 to 1.2 m/s, slower than L4's walk) and
  walking or faster;
- starts: his speed rising from under 0.3 to over 0.9 m/s (a hysteresis, so noise does not count);
- reversals: his running direction turning by more than 120 degrees within 0.4 s, at over 0.5 m/s at
  both ends;
- the distance walked to and fro: in each second, his path less how far he got; and the share of
  seconds in which he doubled back (moved 0.3 m or more and ended under half his path from the start);
- the share of his waits in which he reversed three times or more: going out and back over and over,
  where one turn back to his place after the whistle is a single reversal.
The shuffling measures are those of the focused audit of lesson 174's change.
"""

import json
import math
import sys
from collections import Counter
from pathlib import Path

FPS = 25
STOPS = ("out_of_play", "foul", "offside", "goal")


def main() -> None:
    minutes = starts = reversals = wasted = 0.0
    seconds = doubled = player_waits = churning = 0
    speeds = Counter()
    for run in map(Path, sys.argv[1:]):
        events = [json.loads(line) for line in open(run / "events.jsonl")]
        waits = []
        for i, e in enumerate(events):
            if e["type"] not in ("set_piece", "kickoff"):
                continue
            stop = next((k for k in reversed(events[:i]) if k["type"] in STOPS), None)
            kick = next((k for k in events[i + 1:] if k["type"] in ("pass", "shot")), None)
            if stop and kick and kick["frame"] - stop["frame"] < 200 * FPS:
                waits.append((stop["frame"], kick["frame"], e["player"]))
        want = {n for a, b, _ in waits for n in range(a, b + 1)}
        frames = {}
        for line in open(run / "frames.jsonl"):
            f = json.loads(line)
            if f["frame"] in want:
                frames[f["frame"]] = {p["id"]: p for p in f["players"]}
        for a, b, taker in waits:
            if a not in frames or b not in frames:
                continue
            ids = [pid for pid, p in frames[a].items() if p["role"] != "GK" and pid != taker]
            for pid in ids:
                moving, last_turn, turns = False, -999, 0
                for n in range(a, b + 1):
                    p = frames[n][pid]
                    v = math.hypot(p["vx"], p["vy"])
                    speeds["standing" if v < 0.2 else "creeping" if v < 1.2 else "walking or faster"] += 1
                    if not moving and v > 0.9:
                        moving, starts = True, starts + 1
                    elif moving and v < 0.3:
                        moving = False
                    if n - 10 >= a and n - last_turn > 10:
                        q = frames[n - 10][pid]
                        u = math.hypot(q["vx"], q["vy"])
                        if v > 0.5 and u > 0.5 and (p["vx"] * q["vx"] + p["vy"] * q["vy"]) / (v * u) < -0.5:
                            reversals, last_turn, turns = reversals + 1, n, turns + 1
                player_waits += 1
                churning += turns >= 3
                for s0 in range(a, b - FPS + 1, FPS):
                    pts = [(frames[k][pid]["x"], frames[k][pid]["y"]) for k in range(s0, s0 + FPS + 1)]
                    path = sum(math.dist(pts[k], pts[k + 1]) for k in range(FPS))
                    net = math.dist(pts[0], pts[-1])
                    wasted += path - net
                    seconds += 1
                    doubled += path > 0.3 and net < 0.5 * path
                minutes += (b - a + 1) / FPS / 60
    total = sum(speeds.values())
    print(json.dumps({
        "outfielder_minutes": round(minutes, 1),
        "speeds": {k: round(v / total, 3) for k, v in speeds.most_common()},
        "starts_per_min": round(starts / minutes, 2),
        "reversals_per_min": round(reversals / minutes, 2),
        "to_and_fro_m_per_min": round(wasted / minutes, 2),
        "seconds_doubling_back": round(doubled / seconds, 4),
        "waits_with_3_or_more_reversals": round(churning / player_waits, 4),
    }, indent=1))


if __name__ == "__main__":
    main()
