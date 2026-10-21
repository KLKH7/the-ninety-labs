"""How long a corner takes, and where the time goes (docs/eval/restarts.md).

    uv run python scripts/defect_sweep/corners.py runs/new/seed7 runs/new/seed11 ...

From each run's frames.jsonl and events.jsonl (simulated matches, ground truth), for each corner
(a set piece taken from a corner arc): from the ball going out (the out_of_play event before it)
- to the ball on its spot at the arc, still (within 0.6 m of the corner, under 0.2 m/s): the fetch;
- to the last time a player comes into the penalty area at that end before the kick: everyone in
  place;
- to the kick (the first pass or shot after the set piece); and the wait between the later of the
  first two and the kick.
GROUNDING R1: Opta's mean from the ball going out to a corner being taken is about 30 s.
"""

import json
import math
import sys
from pathlib import Path

FPS = 25
PX, PY = 105.0, 68.0
AREA_DEPTH_M, AREA_HALF_M = 16.5, 20.16  # Law 1: the penalty area


def quantiles(xs: list[float]) -> dict:
    xs = sorted(xs)
    q = lambda p: round(xs[int(p * (len(xs) - 1))], 1)  # noqa: E731
    return {"n": len(xs), "min": q(0.0), "p10": q(0.1), "median": q(0.5),
            "mean": round(sum(xs) / len(xs), 1), "p90": q(0.9), "max": q(1.0)}


def main() -> None:
    rows = []
    for run in map(Path, sys.argv[1:]):
        events = [json.loads(line) for line in open(run / "events.jsonl")]
        corners = []
        for i, e in enumerate(events):
            if e["type"] != "set_piece":
                continue
            if not ((e["x"] < 1.5 or e["x"] > PX - 1.5) and (e["y"] < 1.5 or e["y"] > PY - 1.5)):
                continue
            out = next((k for k in reversed(events[:i]) if k["type"] == "out_of_play"), None)
            kick = next((k for k in events[i + 1:] if k["type"] in ("pass", "shot")), None)
            if out and kick:
                corners.append((out, e, kick))
        if not corners:
            continue
        spans = [(o["frame"], k["frame"]) for o, _, k in corners]
        frames = {}
        for line in open(run / "frames.jsonl"):
            f = json.loads(line)
            if any(a <= f["frame"] <= b for a, b in spans):
                frames[f["frame"]] = f
        for out, sp, kick in corners:
            cx, cy = (0.0 if sp["x"] < PX / 2 else PX), (0.0 if sp["y"] < PY / 2 else PY)
            placed, moving, inside = None, out["frame"], None
            for n in range(out["frame"], kick["frame"] + 1):
                f = frames.get(n)
                if not f:
                    continue
                b = f["ball"]
                if placed is None and math.hypot(b["x"] - cx, b["y"] - cy) < 0.6 * math.sqrt(2) + 0.5 \
                        and math.hypot(b.get("vx", 0.0), b.get("vy", 0.0)) < 0.2 and b["z"] < 0.05:
                    placed = n
                now = {p["id"] for p in f["players"]
                       if abs(p["x"] - cx) <= AREA_DEPTH_M and abs(p["y"] - PY / 2) <= AREA_HALF_M}
                if inside is not None and now - inside:
                    moving = n  # someone has just come into the area
                inside = now
            total = (kick["frame"] - out["frame"]) / FPS
            fetch = ((placed or kick["frame"]) - out["frame"]) / FPS
            arrive = (moving - out["frame"]) / FPS
            rows.append({"run": run.name, "t": out["t"], "total": total, "fetch": fetch, "in_place": arrive,
                         "wait_after": total - max(fetch, arrive)})
    report = {k: quantiles([r[k] for r in rows]) for k in ("total", "fetch", "in_place", "wait_after")}
    report["corners"] = len(rows)
    print(json.dumps(report, indent=1))


if __name__ == "__main__":
    main()
