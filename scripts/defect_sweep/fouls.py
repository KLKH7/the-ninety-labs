"""Every foul the engine calls, at the moment it is called (docs/eval/restarts.md).

    uv run python scripts/defect_sweep/fouls.py runs/new/seed7 runs/new/seed11 ...

From each run's frames.jsonl and events.jsonl (simulated matches, ground truth), for each foul
event: the distance between the two players' centres; the fouler's and the victim's speeds and how
fast the fouler was closing on him; where the fouler came from, seen from the victim (from in
front, from the side or from behind, by the angle between the victim's heading and the way to the
fouler: under 60, 60 to 120, over 120 degrees); and the ball: how far it was from the fouler and
the victim, how high, and whether it was playable for the fouler (within a foot's reach, 1 m,
and below the knee, 0.5 m).
"""

import json
import math
import sys
from collections import Counter
from pathlib import Path

REACH_M = 1.0  # a foot's reach (the engine's CONTROL_M)
KNEE_M = 0.5


def quantiles(xs: list[float]) -> dict:
    xs = sorted(xs)
    q = lambda p: round(xs[int(p * (len(xs) - 1))], 2)  # noqa: E731
    return {"n": len(xs), "min": q(0.0), "p10": q(0.1), "median": q(0.5), "p90": q(0.9), "max": q(1.0)}


def main() -> None:
    rows = []
    for run in map(Path, sys.argv[1:]):
        fouls = [json.loads(line) for line in open(run / "events.jsonl")]
        fouls = [e for e in fouls if e["type"] == "foul"]
        want = {e["frame"] for e in fouls}
        frames = {}
        for line in open(run / "frames.jsonl"):
            f = json.loads(line)
            if f["frame"] in want:
                frames[f["frame"]] = f
        for e in fouls:
            f = frames[e["frame"]]
            by_id = {p["id"]: p for p in f["players"]}
            a, v, b = by_id[e["player"]], by_id[e["receiver"]], f["ball"]
            dx, dy = a["x"] - v["x"], a["y"] - v["y"]
            dist = math.hypot(dx, dy)
            closing = -((a["vx"] - v["vx"]) * dx + (a["vy"] - v["vy"]) * dy) / (dist or 1.0)
            facing = math.atan2(dy, dx) - v["heading"]
            angle = abs(math.degrees((facing + math.pi) % (2 * math.pi) - math.pi))
            side = "from in front" if angle < 60 else ("from the side" if angle <= 120 else "from behind")
            ball_a = math.hypot(b["x"] - a["x"], b["y"] - a["y"])
            rows.append({"run": run.name, "t": e["t"], "dist": dist, "closing": closing,
                         "fouler_speed": math.hypot(a["vx"], a["vy"]),
                         "victim_speed": math.hypot(v["vx"], v["vy"]),
                         "side": side, "ball_from_fouler": ball_a,
                         "ball_from_victim": math.hypot(b["x"] - v["x"], b["y"] - v["y"]), "ball_z": b["z"],
                         "playable": ball_a <= REACH_M and b["z"] <= KNEE_M})
    report = {
        "fouls": len(rows),
        "distance_between_centres_m": quantiles([r["dist"] for r in rows]),
        "closing_speed_mps": quantiles([r["closing"] for r in rows]),
        "fouler_speed_mps": quantiles([r["fouler_speed"] for r in rows]),
        "victim_speed_mps": quantiles([r["victim_speed"] for r in rows]),
        "approach": dict(Counter(r["side"] for r in rows)),
        "ball_from_fouler_m": quantiles([r["ball_from_fouler"] for r in rows]),
        "ball_from_victim_m": quantiles([r["ball_from_victim"] for r in rows]),
        "ball_height_m": quantiles([r["ball_z"] for r in rows]),
        "ball_playable_for_the_fouler": sum(r["playable"] for r in rows),
        "farthest": sorted(({k: (round(v, 2) if isinstance(v, float) else v) for k, v in r.items()}
                            for r in rows), key=lambda r: -r["dist"])[:5],
    }
    print(json.dumps(report, indent=1))


if __name__ == "__main__":
    main()
