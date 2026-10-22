"""One player's movement over a stretch of the match: the facts the phone companion shows and the
Companion agent may cite.

    speed_now    km/h   mean speed over the last second of the window
    peak_speed   km/h   fastest frame-to-frame speed in the window
    distance_run m      distance covered in the window
    heat_share   share  share of the window's frames spent in each cell of an nx by ny grid

and, per team, a flow field (`team_flow`): the mean velocity of its players' steps in each cell.

The first three are `player_movement_facts` (ninety/intel/stats.py) run on a slice of the frames,
not a second implementation: speed_now is its distance over the last second's slice divided by
that slice's time. Each fact's id names the player and the window, and it cites the frames it was
computed from as one range (lesson 31).

Values are rounded for the screen, so the number a viewer reads is the cited value exactly: speeds
to 0.1 km/h and distances to the metre. Frames store positions to 1 mm, so the rounding is coarser
than the positions; it is chosen for the screen (design), and both steps are finer than a tracker's
error on the M1 clip (top speed within 1.5 km/h of the truth, docs/eval/companion-tracked.md).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace

from ninety.intel.stats import Fact, _frame_span, player_movement_facts, player_steps

PITCH_X, PITCH_Y = 105.0, 68.0  # Law 1, the engine's pitch (docs/GROUNDING.md, L1)
SPEED_NOW_S = 1.0  # design: long enough to smooth one frame's noise, short enough to be "now"
# design: cells of 8.75 x 8.5 m, near square, about half a penalty area's depth (16.5 m, Law 1)
HEAT_NX, HEAT_NY = 12, 8
SPEED_PLACES, DISTANCE_PLACES = 1, 0  # design: 0.1 km/h and 1 m on screen (see the module docstring)
SHARE_PLACES = 4  # design: a cell's share of the window to 0.01%, finer than the heat map draws
# The flow field shares the heat map's grid, so the phone lays both over one minimap.
FLOW_NX, FLOW_NY = HEAT_NX, HEAT_NY
# No smoothing beyond the window (design): each cell is the mean of every step taken in it over the
# window, which averages out one frame's noise. A blur across cells would put flow in cells nobody
# crossed, and an empty cell must show none. So there is no smoothing constant to tune.
VELOCITY_PLACES = 2  # m/s; positions are stored to 1 mm, so a 0.04 s step resolves 0.035 m/s


@dataclass(frozen=True)
class Heat:
    """Share of the window's frames in each cell, row by row from y = 0, x = 0 first, as the
    companion_message schema's `player_card.heat` lays it out."""

    id: str
    scope: str
    nx: int
    ny: int
    cells: tuple[float, ...]
    source_ids: tuple[str, ...]
    metric: str = "heat_share"
    unit: str = "share"

    def as_dict(self) -> dict:
        return {
            "id": self.id, "metric": self.metric, "unit": self.unit, "scope": self.scope,
            "nx": self.nx, "ny": self.ny, "cells": list(self.cells), "source_ids": list(self.source_ids),
        }


@dataclass(frozen=True)
class PlayerWindow:
    player: str
    t_from: float
    t_to: float
    speed_now: Fact
    peak_speed: Fact
    distance_run: Fact
    heat: Heat

    def facts(self) -> list[Fact]:
        """The window's single-number facts, which an answer may cite."""
        return [self.speed_now, self.peak_speed, self.distance_run]

    def card(self, source: str) -> dict:
        """The companion_message `player_card` for this window. `source` is where the positions
        came from: `truth` or `tracked`."""
        return {
            "type": "player_card",
            "player": self.player,
            "t_from": self.t_from,
            "t_to": self.t_to,
            "heat": {"nx": self.heat.nx, "ny": self.heat.ny, "cells": list(self.heat.cells)},
            "speed_kmh": self.speed_now.value,
            "peak_kmh": self.peak_speed.value,
            "distance_m": self.distance_run.value,
            "source": source,
        }


def _scope(player: str, t_from: float, t_to: float) -> str:
    return f"player:{player}:window:{t_from:.2f}-{t_to:.2f}"


def _movement(frames: list[Mapping], player: str, restarts: frozenset[int]) -> dict[str, Fact]:
    facts = player_movement_facts(frames, restarts)
    return {f.metric: f for f in facts if f.scope == f"player:{player}"}


def _for_window(fact: Fact, metric: str, value: float, unit: str, places: int, scope: str) -> Fact:
    """`fact` renamed for the window, keeping its citations. `+ 0.0` turns round's -0.0 into 0.0."""
    return replace(
        fact, id=f"{metric}:{scope.replace(':', '_')}", metric=metric, unit=unit,
        value=round(float(value), places) + 0.0, scope=scope,
    )


def _cell(value: float, length: float, n: int) -> int:
    """The cell a coordinate falls in; a player just over a line counts in the edge cell."""
    return min(max(int(value / length * n), 0), n - 1)


def heat_cells(samples: list[tuple[float, float]], nx: int, ny: int) -> tuple[float, ...]:
    counts = [0] * (nx * ny)
    for x, y in samples:
        counts[_cell(y, PITCH_Y, ny) * nx + _cell(x, PITCH_X, nx)] += 1
    total = len(samples)
    return tuple(round(c / total, SHARE_PLACES) for c in counts)


def player_window(
    frames: Iterable[Mapping],
    player: str,
    t_from: float,
    t_to: float,
    restarts: Iterable[int] = (),
    nx: int = HEAT_NX,
    ny: int = HEAT_NY,
) -> PlayerWindow | None:
    """The player's facts from t_from to t_to (both included), or None when the frames hold fewer
    than two positions of him in that window, so no speed or distance can be computed. `restarts`
    are the kickoff frames, whose reset is not movement (as `player_movement_facts`)."""
    if not 0 <= t_from <= t_to:
        raise ValueError(f"window {t_from}..{t_to}: t_from must be from 0 to t_to")
    if nx < 1 or ny < 1:
        raise ValueError("the heat grid needs at least one cell each way")
    # Each frame cut to this player, so the movement facts are not computed for all 22.
    window = sorted(
        (
            {"frame": f["frame"], "t": f["t"], "players": mine}
            for f in frames
            if t_from <= float(f["t"]) <= t_to and (mine := [p for p in f["players"] if p["id"] == player])
        ),
        key=lambda f: (float(f["t"]), int(f["frame"])),
    )
    if len(window) < 2:
        return None
    scope = _scope(player, t_from, t_to)
    reset = frozenset(int(f) for f in restarts)
    whole = _movement(window, player, reset)
    last_t = float(window[-1]["t"])
    recent = [f for f in window if float(f["t"]) >= last_t - SPEED_NOW_S]
    recent_distance = _movement(recent, player, reset)["distance_run"]
    elapsed = last_t - float(recent[0]["t"])
    speed_now = recent_distance.value / elapsed * 3.6 if elapsed > 0 else 0.0
    samples = [(float(p["x"]), float(p["y"])) for f in window for p in f["players"] if p["id"] == player]
    return PlayerWindow(
        player=player,
        t_from=t_from,
        t_to=t_to,
        speed_now=_for_window(recent_distance, "speed_now", speed_now, "km/h", SPEED_PLACES, scope),
        peak_speed=_for_window(
            whole["peak_speed"], "peak_speed", whole["peak_speed"].value, "km/h", SPEED_PLACES, scope
        ),
        distance_run=_for_window(
            whole["distance_run"], "distance_run", whole["distance_run"].value, "m", DISTANCE_PLACES, scope
        ),
        heat=Heat(
            id=f"heat_share:{scope.replace(':', '_')}", scope=scope, nx=nx, ny=ny,
            cells=heat_cells(samples, nx, ny), source_ids=_frame_span(int(f["frame"]) for f in window),
        ),
    )


@dataclass(frozen=True)
class Flow:
    """A team's mean velocity per cell over a window: the "wind" of a wind map of play.

    Built from `player_steps`, the steps the movement facts read (so a kickoff reset is not
    movement). A step counts in the cell its midpoint is in; a cell's (vx, vy) is the mean of its
    steps' velocities in m/s, and `count` is how many steps that is. A cell with no steps has
    count 0 and no velocity (None). Cells are laid out as the heat map's, row by row from y = 0."""

    team: str
    t_from: float
    t_to: float
    nx: int
    ny: int
    vx: tuple[float | None, ...]
    vy: tuple[float | None, ...]
    count: tuple[int, ...]

    def message(self, source: str) -> dict:
        """The companion_message `flow` for this field. `source` is `truth` or `tracked`."""
        return {
            "type": "flow", "team": self.team, "t_from": self.t_from, "t_to": self.t_to,
            "nx": self.nx, "ny": self.ny, "vx": list(self.vx), "vy": list(self.vy),
            "count": list(self.count), "source": source,
        }


def team_flow(
    frames: Iterable[Mapping],
    team: str,
    t_from: float,
    t_to: float,
    restarts: Iterable[int] = (),
    nx: int = FLOW_NX,
    ny: int = FLOW_NY,
) -> Flow:
    """The team's flow field from t_from to t_to (steps ending in the window, both ends included)."""
    if not 0 <= t_from <= t_to:
        raise ValueError(f"window {t_from}..{t_to}: t_from must be from 0 to t_to")
    if nx < 1 or ny < 1:
        raise ValueError("the flow grid needs at least one cell each way")
    window = [
        {"frame": f["frame"], "t": f["t"], "players": mine}
        for f in frames
        if t_from <= float(f["t"]) <= t_to and (mine := [p for p in f["players"] if p.get("team") == team])
    ]
    sum_vx, sum_vy, count = [0.0] * (nx * ny), [0.0] * (nx * ny), [0] * (nx * ny)
    for steps in player_steps(window, restarts).values():
        for step in steps:
            mid_x, mid_y = (step.x0 + step.x1) / 2, (step.y0 + step.y1) / 2
            cell = _cell(mid_y, PITCH_Y, ny) * nx + _cell(mid_x, PITCH_X, nx)
            sum_vx[cell] += (step.x1 - step.x0) / step.dt
            sum_vy[cell] += (step.y1 - step.y0) / step.dt
            count[cell] += 1
    mean = [
        (round(sx / n, VELOCITY_PLACES) + 0.0, round(sy / n, VELOCITY_PLACES) + 0.0) if n else (None, None)
        for sx, sy, n in zip(sum_vx, sum_vy, count, strict=True)
    ]
    vx, vy = tuple(m[0] for m in mean), tuple(m[1] for m in mean)
    return Flow(team, t_from, t_to, nx, ny, vx, vy, tuple(count))
