"""Creep spells through restart waits (docs/eval/restarts.md, "Walking to restart positions"; the
third audit of lesson 174 counted them first).

    uv run python scripts/defect_sweep/creep_spells.py runs/new/seed7 runs/new/seed11 ...

From each run's frames.jsonl and events.jsonl (simulated matches, ground truth), over every restart's
wait (from the stoppage to the take, under 200 s), for each outfielder but the taker: a creep spell
is a run of frames at which he moves at 0.2 to 1.2 m/s (slower than L4's walk), its length the path
walked in it. Prints the spells over 5 m and over 10 m (count and metres), the restarts of each kind
with a spell over 10 m, and the longest spells (metres, seconds, run, player, kind, side, when).
"""

import json
import math
import sys
from collections import Counter
from pathlib import Path

FPS = 25
STOPS = ("out_of_play", "foul", "offside", "goal")


def kind_of(take: dict, stop: dict) -> str:
    corner = (take["x"] < 1.5 or take["x"] > 103.5) and (take["y"] < 1.5 or take["y"] > 66.5)
    if corner:
        return "corner"
    if take["y"] < 1.0 or take["y"] > 67.0:
        return "throw-in"
    return "goal kick" if stop["type"] == "out_of_play" else "free kick"


def main() -> None:
    over5 = over10 = 0
    m5 = m10 = 0.0
    kinds, with10 = Counter(), Counter()
    longest = []
    for run in map(Path, sys.argv[1:]):
        events = [json.loads(line) for line in open(run / "events.jsonl")]
        waits = []
        for i, e in enumerate(events):
            if e["type"] != "set_piece":
                continue
            stop = next((k for k in reversed(events[:i]) if k["type"] in STOPS), None)
            if stop and e["frame"] - stop["frame"] < 200 * FPS:
                waits.append((stop["frame"], e["frame"], e, kind_of(e, stop)))
        want = {n for a, b, *_ in waits for n in range(a, b + 1)}
        frames = {}
        for line in open(run / "frames.jsonl"):
            f = json.loads(line)
            if f["frame"] in want:
                frames[f["frame"]] = {p["id"]: p for p in f["players"]}
        for a, b, e, kind in waits:
            kinds[kind] += 1
            worst = 0.0
            for pid, p0 in frames[a].items():
                if p0["role"] == "GK" or pid == e["player"]:
                    continue
                spell, start = 0.0, None
                for n in range(a, b + 1):
                    p = frames[n][pid]
                    creeping = 0.2 <= math.hypot(p["vx"], p["vy"]) < 1.2
                    if creeping and n > a:
                        q = frames[n - 1][pid]
                        spell += math.dist((q["x"], q["y"]), (p["x"], p["y"]))
                        start = n if start is None else start
                    if not creeping or n == b:
                        if spell > 5.0:
                            over5, m5 = over5 + 1, m5 + spell
                        if spell > 10.0:
                            over10, m10 = over10 + 1, m10 + spell
                            side = "kicking" if p0["team"] == e["team"] else "defending"
                            longest.append((round(spell, 1), round((n - start) / FPS, 1), run.name, pid, kind,
                                            side, round(a / FPS, 1)))
                        worst = max(worst, spell)
                        spell, start = 0.0, None
            with10[kind] += worst > 10.0
    print(json.dumps({
        "spells_over_5m": over5, "metres_over_5m": round(m5),
        "spells_over_10m": over10, "metres_over_10m": round(m10),
        "restarts_with_a_spell_over_10m": {k: f"{with10[k]} of {kinds[k]}" for k in sorted(kinds)},
        "longest": sorted(longest, reverse=True)[:8],
    }, indent=1))


if __name__ == "__main__":
    main()
