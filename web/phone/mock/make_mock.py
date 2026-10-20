"""Writes web/phone/mock/minimap.json: positions for building the phone before tracked positions exist.

The positions come from a formula, not from the simulator: two teams hold a 4-4-2 shape that slides
toward the ball, the nearest player of each team goes to it, and the ball moves from player to
player. Since nothing simulated them, they are nobody's ground truth (AGENTS.md, "Ground truth is the
answer key"). The file is labelled `source: tracked` because it stands in for what the tracker will
serve, and the phone shows "Mock data" on every screen while it reads it (web/phone/src/mock.ts).
It does not show football; it gives the UI 22 moving dots, a ball and stats that agree with the dots.

    uv run python web/phone/mock/make_mock.py      # rewrites the file; same output every run
"""

from __future__ import annotations

import json
import math
import random
from pathlib import Path

OUT = Path(__file__).with_name("minimap.json")
FPS, SECONDS = 5, 120
PITCH_X, PITCH_Y = 105.0, 68.0
MAX_SPEED = 8.0  # m/s; design: keeps the mock's speeds in a sprinter's range
PASS_SPEED = 16.0  # m/s
# A 4-4-2 for the team attacking toward x = 105, as (x, y) in metres.
SHAPE = [
    (5, 34),
    (22, 10), (20, 26), (20, 42), (22, 58),
    (38, 10), (36, 27), (36, 41), (38, 58),
    (50, 28), (50, 40),
]


def clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def anchor(team: str, i: int, ball: tuple[float, float]) -> tuple[float, float]:
    """Where player i's shape puts them, slid toward the ball."""
    x, y = SHAPE[i]
    if team == "a":
        x, y = PITCH_X - x, PITCH_Y - y
    slide = 0.0 if i == 0 else 0.35
    x += slide * (ball[0] - PITCH_X / 2) * (0.4 if i == 0 else 1)
    y += (0.1 if i == 0 else 0.3) * (ball[1] - PITCH_Y / 2)
    return clamp(x, 1, PITCH_X - 1), clamp(y, 1, PITCH_Y - 1)


def build() -> dict:
    rng = random.Random(20261020)
    ids = [f"{t}{n}" for t in "ha" for n in range(1, 12)]
    pos = {p: anchor(p[0], int(p[1:]) - 1, (52.5, 34.0)) for p in ids}
    ball = [52.5, 34.0]
    holder, target, hold_left = "h10", None, 1.0
    dt = 1 / FPS
    frames = []
    for k in range(SECONDS * FPS + 1):
        t = round(k * dt, 2)
        b = (ball[0], ball[1])
        # The ball: held and dribbled, then passed to a team-mate, now and then lost to the other team.
        if target is None:
            hold_left -= dt
            hx, hy = pos[holder]
            ball[0], ball[1] = hx + 0.8, hy
            if hold_left <= 0:
                team = holder[0]
                if rng.random() < 0.2:
                    team = "a" if team == "h" else "h"
                mates = [p for p in ids if p[0] == team and p != holder and p[1:] != "1"]
                target = min(rng.sample(mates, 3), key=lambda p: math.dist(pos[p], b) + rng.random() * 10)
        else:
            tx, ty = pos[target]
            d = math.dist((tx, ty), b)
            step = PASS_SPEED * dt
            if d <= step:
                ball[0], ball[1] = tx, ty
                holder, target, hold_left = target, None, rng.uniform(0.8, 2.5)
            else:
                ball[0] += (tx - ball[0]) / d * step
                ball[1] += (ty - ball[1]) / d * step
        # The players: each heads for their slot, the nearest of each team for the ball, at most MAX_SPEED.
        outfield = {team: [p for p in ids if p[0] == team and p[1:] != "1"] for team in "ha"}
        nearest = {team: min(outfield[team], key=lambda p: math.dist(pos[p], b)) for team in "ha"}
        for p in ids:
            i = int(p[1:]) - 1
            gx, gy = anchor(p[0], i, b)
            if p == holder and target is None:
                gx += 6 if p[0] == "h" else -6
            elif p == target or p == nearest[p[0]]:
                gx, gy = b
            wobble = 1.5 * math.sin(t * 0.7 + i * 1.3 + (0 if p[0] == "h" else 2))
            gy += wobble
            x, y = pos[p]
            d = math.dist((gx, gy), (x, y))
            chasing = p in (holder, target) or p == nearest[p[0]]
            speed = MAX_SPEED if chasing else min(MAX_SPEED, 1.2 + d * 0.6)
            step = min(d, speed * dt)
            if d > 1e-6:
                x += (gx - x) / d * step
                y += (gy - y) / d * step
            pos[p] = (clamp(x, 0.5, PITCH_X - 0.5), clamp(y, 0.5, PITCH_Y - 0.5))
        frames.append({
            "t": t,
            "ball": [round(ball[0], 1), round(ball[1], 1)],
            "players": [[p, round(pos[p][0], 1), round(pos[p][1], 1)] for p in ids],
        })
    return {"clip": "mock", "source": "tracked", "fps": FPS, "roster": sorted(ids), "frames": frames}


def text(body: dict) -> str:
    return json.dumps(body, separators=(",", ":")) + "\n"


def main() -> None:
    body = build()
    OUT.write_text(text(body))
    print(f"{OUT}: {len(body['frames'])} frames")


if __name__ == "__main__":
    main()
