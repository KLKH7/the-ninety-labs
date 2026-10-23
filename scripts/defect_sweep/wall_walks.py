"""How close walk_to_wall's estimate of a wall player's walk comes to the walk (docs/eval/restarts.md,
"Walking to restart positions"; lesson 176).

    uv run python scripts/defect_sweep/wall_walks.py

For 15 scenarios (seeds 3, 5, 7, 11, 13; direct free kicks to home at (PITCH_X - 22, 34), (87, 24)
and (86, 44), each after a minute of play, as tests/test_restarts.py's wall_kick sets them up), every
wall player is followed frame by frame to his place, with his own bending round others (avoid)
left out, since the estimate is of his own way only. Prints the walks whose estimate minus walk is
smallest (negative: he walked further than estimated) and how many are within 5 cm.
"""

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tests"))

from test_restarts import wall_kick  # noqa: E402

from ninety.sim import ball  # noqa: E402
from ninety.sim.engine import DT, PITCH_X  # noqa: E402


def main() -> None:
    rows = []
    for seed in (3, 5, 7, 11, 13):
        for at in ((PITCH_X - 22.0, 34.0), (87.0, 24.0), (86.0, 44.0)):
            e = wall_kick(seed, at)
            r = e.restart
            wall = dict(r.wall)
            if not wall:
                continue
            bend = e.avoid
            e.avoid = lambda p, bend=bend, wall=wall: (0.0, 0.0) if p.id in wall else bend(p)
            at_ = {pid: (e.by_id[pid].x, e.by_id[pid].y) for pid in wall}
            estimate = {pid: e.walk_to_wall(r, at_[pid], wall[pid]) for pid in wall}
            walked = dict.fromkeys(wall, 0.0)
            arrived: set[str] = set()
            for _ in range(int(45 / DT)):
                e.step()
                for pid in set(wall) - arrived:
                    p = e.by_id[pid]
                    walked[pid] += math.dist(at_[pid], (p.x, p.y))
                    at_[pid] = (p.x, p.y)
                    if math.dist((p.x, p.y), wall[pid]) < ball.RADIUS:
                        arrived.add(pid)
                if arrived == set(wall):
                    break
            for pid in sorted(arrived):
                rows.append((round(estimate[pid] - walked[pid], 3), round(estimate[pid], 2), seed, at, pid))
            if arrived != set(wall):
                print("not all arrived:", seed, at, sorted(set(wall) - arrived))
    rows.sort()
    print(len(rows), "walks; the smallest margins (estimate - walked, m):", rows[:6])
    print("within 5 cm or over:", sum(m < 0.05 for m, *_ in rows), "of", len(rows))


if __name__ == "__main__":
    main()
