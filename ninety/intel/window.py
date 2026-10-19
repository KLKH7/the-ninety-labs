"""One player's movement over a stretch of the match: the facts the phone companion shows and the
Companion agent may cite.

    speed_now    km/h   mean speed over the last second of the window
    peak_speed   km/h   fastest frame-to-frame speed in the window
    distance_run m      distance covered in the window
    heat_share   share  share of the window's frames spent in each cell of an nx by ny grid

The first three are `player_movement_facts` (ninety/intel/stats.py) run on a slice of the frames,
not a second implementation: speed_now is its distance over the last second's slice divided by
that slice's time. Each fact's id names the player and the window, and it cites the frames it was
computed from as one range (lesson 31).

Values are rounded for the screen, so the number a viewer reads is the cited value exactly: speeds
to 0.1 km/h and distances to the metre (frames store positions to 1 mm, so neither rounding hides
anything the positions resolve, and a tracker's error is larger than both).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace

from ninety.intel.stats import Fact, _frame_span, player_movement_facts

PITCH_X, PITCH_Y = 105.0, 68.0  # Law 1, the engine's pitch (docs/GROUNDING.md, L1)
SPEED_NOW_S = 1.0  # design: long enough to smooth one frame's noise, short enough to be "now"
HEAT_NX, HEAT_NY = 12, 8  # design: cells of 8.75 x 8.5 m, about a penalty area's depth
SPEED_PLACES, DISTANCE_PLACES, SHARE_PLACES = 1, 0, 4


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
