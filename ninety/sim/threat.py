"""Expected threat: what having the ball in each area is worth, from real matches (GROUNDING D9).

A published 12 x 8 grid (columns from your own goal to the opponents', rows across the pitch):
the chance that a possession at that spot leads to a goal within its next few actions, computed
from real event data (Expected Threat, Karun Singh; file open_xt_12x8_v1). It values keeping the
ball somewhere and, seen from the other side, what losing it there costs.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

PITCH_X, PITCH_Y = 105.0, 68.0
GRID = json.loads((Path(__file__).resolve().parent / "data" / "expected_threat_12x8.json").read_text())
ROWS, COLS = len(GRID), len(GRID[0])


def at(x: float, y: float, goal_x: float) -> float:
    """Threat of having the ball at (x, y) for a team attacking the goal at goal_x, bilinear
    between cell centres."""
    along = (PITCH_X - abs(goal_x - x)) / PITCH_X * COLS - 0.5  # 0 at own goal, COLS at theirs
    across = min(PITCH_Y, max(0.0, y)) / PITCH_Y * ROWS - 0.5
    c0, r0 = math.floor(along), math.floor(across)
    fc, fr = along - c0, across - r0

    def cell(r: int, c: int) -> float:
        return GRID[min(ROWS - 1, max(0, r))][min(COLS - 1, max(0, c))]
    return ((1 - fc) * (1 - fr) * cell(r0, c0) + fc * (1 - fr) * cell(r0, c0 + 1)
            + (1 - fc) * fr * cell(r0 + 1, c0) + fc * fr * cell(r0 + 1, c0 + 1))
