"""Possession value and shot value, measured from the engine's own matches (docs/GROUNDING.md D7).

Two tables, one unit: the chance that a possession ends in a goal for the team that has it.
- `threat`: for each area of the pitch, seen from the team with the ball (attacking frame, width
  mirrored for the away side), the share of possessions that passed through it and ended in a
  goal (expected threat). What keeping the ball here is worth; the opponents' value at a spot is
  what losing it there costs. A probability, so losing the ball is never a reward.
- `finishing`: for each area, the share of shots from it that went in (the engine's own expected
  goals). A shot is valued from this, on the same scale as moving the ball.

Nobody writes these numbers. They are counted from simulated matches, fed back into the decisions,
and counted again; each round moves halfway toward the new count, and the run stops when no
cell moves by more than its sampling error. Being careful near your own goal and taking risks near
theirs comes out of them.

    uv run python -m ninety.sim.value --rounds 6 --matches 16

The risk is circularity: the engine's own flaws are counted too. Every round is written to
docs/eval/possession-value.md for the audit; nothing is fitted to it.
"""

from __future__ import annotations

import argparse
import json
import math
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from pathlib import Path

PITCH_X, PITCH_Y = 105.0, 68.0
CELLS_X, CELLS_Y = 21, 10  # 5 m by 6.8 m
PRIOR_POSSESSIONS = 20.0  # design: a cell seen in few possessions leans on its neighbours
DAMPING = 0.5  # design: each round moves this share of the way to the new count
ROOT = Path(__file__).resolve().parents[2]
TABLE = Path(__file__).resolve().parent / "data" / "possession_value.json"

Grid = list[list[float]]


def zeros() -> Grid:
    return [[0.0] * CELLS_Y for _ in range(CELLS_X)]


def frame_of(x: float, y: float, goal_x: float) -> tuple[float, float]:
    """(metres from the goal attacked, width measured from the attacker's right touchline):
    the same for both teams, since the away side's shape is the home side's turned round."""
    return min(PITCH_X, max(0.0, abs(goal_x - x))), (y if goal_x > PITCH_X / 2 else PITCH_Y - y)


def cell_of(x: float, y: float, goal_x: float) -> tuple[int, int]:
    u, w = frame_of(x, y, goal_x)
    return min(CELLS_X - 1, int(u / PITCH_X * CELLS_X)), min(CELLS_Y - 1, max(0, int(w / PITCH_Y * CELLS_Y)))


@dataclass
class Table:
    values: Grid

    def at(self, x: float, y: float, goal_x: float) -> float:
        """Bilinear between cell centres, in the attacking frame of the team at goal_x."""
        u, w = frame_of(x, y, goal_x)
        a = u / PITCH_X * CELLS_X - 0.5
        b = w / PITCH_Y * CELLS_Y - 0.5
        i0, j0 = math.floor(a), math.floor(b)
        fa, fb = a - i0, b - j0

        def cell(i: int, j: int) -> float:
            return self.values[min(CELLS_X - 1, max(0, i))][min(CELLS_Y - 1, max(0, j))]
        return ((1 - fa) * (1 - fb) * cell(i0, j0) + fa * (1 - fb) * cell(i0 + 1, j0)
                + (1 - fa) * fb * cell(i0, j0 + 1) + fa * fb * cell(i0 + 1, j0 + 1))


PossessionValue = Table  # the name the decisions use for the threat table


@dataclass
class Tables:
    threat: Table
    finishing: Table


def load(path: Path = TABLE) -> Tables | None:
    if not path.exists():
        return None
    data = json.loads(path.read_text())
    if "threat" not in data:
        return None  # an older table format: measure again
    return Tables(Table(data["threat"]), Table(data["finishing"]))


def possessions(frames: list[dict], events: list[dict]) -> list[tuple[str, set[tuple[int, int]], bool]]:
    """Split a match into possessions (a team has the ball until the other team takes it, or a
    goal is scored), each with the cells the ball was in while that team had it and whether it
    ended in that team's goal. A loose ball after a team's touch still belongs to its possession."""
    goal_times = sorted((e["t"], e["team"]) for e in events if e["type"] == "goal")
    out: list[tuple[str, set[tuple[int, int]], bool]] = []
    team, cells = None, set()
    gi = 0
    for f in frames:
        while gi < len(goal_times) and goal_times[gi][0] <= f["t"]:
            if team is not None:
                out.append((team, cells, goal_times[gi][1] == team))
            team, cells = None, set()
            gi += 1
        holder = f["possessor"]
        if holder:
            now = "home" if holder.startswith("h") else "away"
            if now != team:
                if team is not None:
                    out.append((team, cells, False))
                team, cells = now, set()
        if team is not None:
            cells.add(cell_of(f["ball"]["x"], f["ball"]["y"], PITCH_X if team == "home" else 0.0))
    if team is not None:
        out.append((team, cells, False))
    return out


def count(frames: list[dict], events: list[dict]) -> tuple[Grid, Grid, Grid, Grid]:
    """Per cell: possessions through it, of those ending in a goal; shots from it, of those scored."""
    seen, scored, shots, goals = zeros(), zeros(), zeros(), zeros()
    for _, cells, goal in possessions(frames, events):
        for i, j in cells:
            seen[i][j] += 1
            scored[i][j] += goal
    for e in events:
        if e["type"] == "shot" and e.get("outcome"):
            i, j = cell_of(e["x"], e["y"], PITCH_X if e["team"] == "home" else 0.0)
            shots[i][j] += 1
            goals[i][j] += e["outcome"] == "goal"
    return seen, scored, shots, goals


def smooth(hits: Grid, trials: Grid, prior: float = PRIOR_POSSESSIONS) -> Grid:
    """Each cell's rate, shrunk toward its 3x3 neighbourhood's rate in proportion to how few
    trials it has. With no data anywhere near, 0."""
    out = zeros()
    for i in range(CELLS_X):
        for j in range(CELLS_Y):
            nh = nt = 0.0
            for a in range(max(0, i - 1), min(CELLS_X, i + 2)):
                for b in range(max(0, j - 1), min(CELLS_Y, j + 2)):
                    nh, nt = nh + hits[a][b], nt + trials[a][b]
            local = nh / nt if nt else 0.0
            out[i][j] = (hits[i][j] + prior * local) / (trials[i][j] + prior)
    return out


def standard_error(rate: Grid, trials: Grid) -> Grid:
    return [[math.sqrt(max(rate[i][j] * (1 - rate[i][j]), 1e-6) / (trials[i][j] + PRIOR_POSSESSIONS))
             for j in range(CELLS_Y)] for i in range(CELLS_X)]


def _play(job: tuple[int, float, dict | None]):
    seed, minutes, data = job
    from ninety.sim import decisions
    from ninety.sim.engine import Engine
    decisions.POSSESSION = Tables(Table(data["threat"]), Table(data["finishing"])) if data else None
    match = Engine(seed).run(minutes)
    return count(match.frames, match.events), sum(e["type"] == "goal" for e in match.events)


def measure(seeds: list[int], minutes: float, data: dict | None):
    totals = [zeros() for _ in range(4)]
    goals = []
    with ProcessPoolExecutor() as pool:
        for grids, g in pool.map(_play, [(seed, minutes, data) for seed in seeds]):
            goals.append(g)
            for total, grid in zip(totals, grids, strict=True):
                for i in range(CELLS_X):
                    for j in range(CELLS_Y):
                        total[i][j] += grid[i][j]
    return totals, goals


def blend(old: Grid | None, new: Grid) -> Grid:
    if old is None:
        return new
    return [[old[i][j] + DAMPING * (new[i][j] - old[i][j]) for j in range(CELLS_Y)] for i in range(CELLS_X)]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--rounds", type=int, default=6)
    ap.add_argument("--matches", type=int, default=16)
    ap.add_argument("--minutes", type=float, default=90)
    ap.add_argument("--resume", action="store_true", help="start from the saved table, not from none")
    args = ap.parse_args()
    data = json.loads(TABLE.read_text()) if args.resume and load() else None
    report = ["# Possession value, measured from simulated matches", "",
              "Generated by `uv run python -m ninety.sim.value`. Threat = share of possessions through "
              "an area that ended in a goal; finishing = share of shots from it that went in. Each "
              f"round plays matches with the current tables and moves {DAMPING:.0%} of the way to the "
              "new count; it stops when no cell moves by more than its sampling error. Nothing is "
              "fitted to it.", "",
              "| Round | Matches | Goals a match | Largest threat change, in sampling errors | Settled |",
              "|---|---|---|---|---|"]
    settled = False
    for k in range(args.rounds):
        seeds = list(range(1000 * (k + 1), 1000 * (k + 1) + args.matches))
        (seen, scored, shots, goals), per_match = measure(seeds, args.minutes, data)
        threat, finishing = smooth(scored, seen), smooth(goals, shots)
        se = standard_error(threat, seen)
        old = data["threat"] if data else None
        cells = [(i, j) for i in range(CELLS_X) for j in range(CELLS_Y)]
        moved = max(abs(threat[i][j] - old[i][j]) / se[i][j] for i, j in cells) if old else float("inf")
        data = {"threat": blend(old, threat),
                "finishing": blend(data["finishing"] if data else None, finishing)}
        settled = moved < 2.0
        report.append(f"| {k + 1} | {len(per_match)} | {sum(per_match) / len(per_match):.1f} | {moved:.1f} | "
                      f"{'yes' if settled else 'no'} |")
        print(report[-1], flush=True)
        if settled:
            break
    TABLE.parent.mkdir(exist_ok=True)
    rounded = {name: [[round(v, 5) for v in row] for row in data[name]] for name in ("threat", "finishing")}
    TABLE.write_text(json.dumps({"cells": [CELLS_X, CELLS_Y], "settled": settled, **rounded}, indent=1))
    for name in ("threat", "finishing"):
        report += ["", f"{name.capitalize()}, metres from the goal attacked (rows) by width (columns, the "
                   "attacker's right first), in hundredths:", "",
                   "| m | " + " | ".join(str(j + 1) for j in range(CELLS_Y)) + " |",
                   "|---" * (CELLS_Y + 1) + "|"]
        for i in range(CELLS_X):
            row = " | ".join(f"{100 * v:.1f}" for v in data[name][i])
            report.append(f"| {i * 5}-{i * 5 + 5} | {row} |")
    (ROOT / "docs/eval/possession-value.md").write_text("\n".join(report) + "\n")


if __name__ == "__main__":
    main()
