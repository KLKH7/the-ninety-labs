"""Measure how often a keeper saves isolated shots on target, by distance. A report, never a gate:
nothing in the keeper is tuned to these numbers (docs/GROUNDING.md, P15).

    uv run python -m ninety.sim.keeper_report --shots 200     # writes docs/eval/sim-keeper.md

Each shot: the away keeper on his line at the centre (standing, or moving sideways along his line
at `--moving` m/s), the outfield players out of the way, a shot struck from straight in front of
goal at 70 to 120 km/h toward a point 0.5 to 3.4 m either side of the centre and 0.1 to 1.5 m up.
A save is the keeper touching or holding the ball before it goes in or out.
"""

from __future__ import annotations

import argparse
import math
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from ninety.sim import fmath
from ninety.sim.engine import DT, Engine

ROOT = Path(__file__).resolve().parents[2]
DISTANCES_M = (8, 11, 16, 20, 25)


def shot(seed: int, distance: float, moving: float) -> str:
    rng = fmath.Random(seed)
    e = Engine(seed)
    for k, p in enumerate(e.players):
        if p.role != "GK":
            p.x, p.y, p.vx, p.vy = 40.0, 5.0 + 2.5 * k, 0.0, 0.0
    keeper = e.keeper("away")
    keeper.x, keeper.y, keeper.vx, keeper.vy = 104.0, 34.0, 0.0, moving * rng.choice((-1, 1))
    home = e.keeper("home")
    home.x, home.y = 1.0, 34.0
    bx, by = 105.0 - distance, 34.0
    ty = 34.0 + rng.choice((-1, 1)) * rng.uniform(0.5, 3.4)
    tz = rng.uniform(0.1, 1.5)
    speed = rng.uniform(70, 120) / 3.6
    dx, dy = 105.0 - bx, ty - by
    d = math.hypot(dx, dy)
    flight = d / speed
    vz = (tz - 0.11 + 0.5 * 9.81 * flight * flight) / flight if tz > 0.3 else 0.0
    e.ball = (bx, by, 0.11, speed * dx / d, speed * dy / d, vz)
    e.possessor = e.restart = None
    e.kicked = {"type": "shot", "team": "home", "x": bx, "y": by, "player": "h10"}
    e.kicked_at = e.free_since = e.t
    e.last_touch = "h10"
    start = len(e.match.events)
    for _ in range(int(4 / DT)):
        e.step()
        for ev in e.match.events[start:]:
            if ev["type"] == "goal":
                return "goal"
            if ev.get("player") == keeper.id:
                return "save"
            if ev["type"] == "out_of_play":
                return "out"
        if e.possessor == keeper.id:
            return "save"
    return "none"


def rates(shots: int, moving: float) -> dict[int, tuple[int, int]]:
    out = {}
    with ProcessPoolExecutor() as pool:
        for distance in DISTANCES_M:
            c = Counter(pool.map(shot, range(1000, 1000 + shots), [distance] * shots, [moving] * shots))
            out[distance] = (c["save"], c["save"] + c["goal"])
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--shots", type=int, default=200)
    ap.add_argument("--moving", type=float, default=2.5)
    ap.add_argument("--out", type=Path, default=ROOT / "docs" / "eval" / "sim-keeper.md")
    args = ap.parse_args()
    standing, moving = rates(args.shots, 0.0), rates(args.shots, args.moving)
    lines = ["# Keeper report", "",
             f"`uv run python -m ninety.sim.keeper_report --shots {args.shots}`: {args.shots} isolated "
             "shots per distance, seeds 1000 on. Save rate of shots on target (saved or scored). "
             "A report, never a gate (docs/GROUNDING.md, P15).", "",
             f"| Distance | Keeper standing | Keeper moving {args.moving} m/s along his line |",
             "|---|---|---|"]
    for distance in DISTANCES_M:
        cells = [f"{s / max(n, 1):.0%} ({s} of {n})" for s, n in (standing[distance], moving[distance])]
        lines.append(f"| {distance} m | {cells[0]} | {cells[1]} |")
    text = "\n".join(lines) + "\n"
    args.out.write_text(text)
    print(text)


if __name__ == "__main__":
    main()
