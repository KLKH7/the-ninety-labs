"""Players walking over a set ball (lesson 207).

    uv run python scripts/defect_sweep/crossball.py runs/new/seed7 runs/new/seed11 ...

From each run's frames.jsonl and events.jsonl (simulated matches, ground truth). While a restart
waits (from the stoppage before it to its set_piece or kickoff event), once the ball rests on its spot
(under 0.05 m/s, on the ground, within 0.6 m of where the restart is taken), a moving player (over
0.3 m/s) other than the one who has it or takes it whose body passes over it: his centre within half
a shoulder and a ball's radius of it (P11: 0.25 m; Law 2: 0.11 m). The first second after the
whistle is left out: that is the fouler's own momentum, not a walk. One count per player per restart.
"""

import json
import math
import sys
from collections import Counter
from pathlib import Path

REACH_M = 0.25 + 0.11
FPS = 25


def main() -> None:
    total, by_kind, cases = 0, Counter(), []
    for run in map(Path, sys.argv[1:]):
        events = [json.loads(line) for line in open(run / "events.jsonl")]
        frames = {f["frame"]: f for f in map(json.loads, open(run / "frames.jsonl"))}
        stops = [e for e in events if e["type"] in ("out_of_play", "foul", "goal", "offside")]
        for sp in (e for e in events if e["type"] in ("set_piece", "kickoff")):
            prev = max((s for s in stops if s["frame"] < sp["frame"]), key=lambda s: s["frame"], default=None)
            if prev is None:
                continue
            seen = set()
            for n in range(prev["frame"] + FPS, sp["frame"]):
                f = frames.get(n)
                if f is None:
                    continue
                b = f["ball"]
                if math.hypot(b["vx"], b["vy"]) > 0.05 or b["z"] > 0.01:
                    continue
                if math.hypot(b["x"] - sp["x"], b["y"] - sp["y"]) > 0.6:
                    continue  # not yet set on its spot (rolling, fetched, in a net)
                for p in f["players"]:
                    if p["id"] in seen or p["id"] in (f.get("possessor"), sp["player"]):
                        continue
                    near = math.hypot(p["x"] - b["x"], p["y"] - b["y"]) < REACH_M
                    if near and math.hypot(p["vx"], p["vy"]) > 0.3:
                        seen.add(p["id"])
                        total += 1
                        by_kind["kick_off" if sp["type"] == "kickoff" else "set_piece"] += 1
                        cases.append((run.name, f["t"], p["id"], p["team"] == sp["team"]))
    print(json.dumps({"walks_over_the_set_ball": total, "by_kind": by_kind, "cases": cases[:25]}, indent=1))


if __name__ == "__main__":
    main()
