"""Match terrain: the data behind the 3D momentum view in web/terrain.

For one clip it computes, all in code:
- `grid`: per minute and per 5 m strip along the pitch, the threat of where the ball was, signed
  by the team that had it (home positive, away negative), in threat-seconds per minute;
- `momentum`: home threat minus away threat per minute, averaged over five minutes;
- `turning_points`: the minutes where the side on top changes and holds it, each with how long it
  held, its peak, and counts from the events of the build-up with the ids of those events;
- `players`: each player's mean position per minute and involvement (passes, shots, tackles,
  interceptions, pressures).

Threat comes from the engine's possession-value table (`ninety/sim/value.py`). That table is not
committed while it is still being measured, so without it this reads the latest published round
from docs/eval/possession-value.md and says so.

    uv run python -m ninety.intel.terrain runs/seed7 web/terrain/seed7.json
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
from collections import defaultdict
from collections.abc import Iterable, Mapping
from pathlib import Path

from ninety.intel.stats import control_vs_chaos
from ninety.sim import value
from ninety.sim.value import PITCH_X, Table

ZONES = 21  # 5 m strips, the threat table's own resolution along the pitch
SAMPLE_EVERY = 5  # frames: 5 samples a second at 25 fps
SMOOTH_MINUTES = 5
# Turning points (design values, tuned by eye on seed 7, not measured): a side is on top in a
# minute when momentum is outside a dead band of a quarter of the match's own spread; it has
# taken over when it stays on top for five minutes before the other side is. The counts on a
# turning point come from the three minutes up to it.
DEAD_BAND = 0.25
HOLD_MINUTES = 5
BUILD_UP_MINUTES = 3
INVOLVEMENT = ("pass", "shot", "tackle", "interception", "pressure")
PUBLISHED_TABLE = value.ROOT / "docs" / "eval" / "possession-value.md"


def threat_table(path: Path = value.TABLE, published: Path = PUBLISHED_TABLE) -> Table:
    tables = value.load(path)
    if tables:
        return tables.threat
    text = published.read_text()
    block = text.split("Threat, metres")[1].split("Finishing, metres")[0]
    rows = [r for r in block.splitlines() if re.match(r"^\| \d+-\d+ \|", r)]
    values = [[float(c) / 100 for c in r.strip("|").split("|")[1:]] for r in rows]
    if len(values) != value.CELLS_X or any(len(r) != value.CELLS_Y for r in values):
        raise ValueError(f"{published}: threat table is not {value.CELLS_X} x {value.CELLS_Y}")
    print(f"terrain: {path} not found, using the threat table published in {published}", file=sys.stderr)
    return Table(values)


def _minute(t: float, minutes: int) -> int:
    return min(minutes - 1, int(t // 60))


def _team_of(player_id: str) -> str:
    return "home" if player_id.startswith("h") else "away"


def _is_recovery(event: Mapping) -> bool:
    if event["type"] == "interception":
        return True
    return event["type"] == "tackle" and event.get("outcome") == "success"


def build_terrain(events: list[Mapping], frames: Iterable[Mapping], roster: list[Mapping], minutes: int,
                  threat: Table) -> dict:
    grid = [[0.0] * ZONES for _ in range(minutes)]
    samples = [0] * minutes
    home, away = [0.0] * minutes, [0.0] * minutes
    position = defaultdict(lambda: [[0.0, 0] for _ in range(minutes)])
    team = None  # a loose ball still belongs to the team that last had it, as in value.possessions
    for frame in frames:
        if frame["frame"] % SAMPLE_EVERY:
            continue
        m = _minute(frame["t"], minutes)
        samples[m] += 1
        if frame["possessor"]:
            team = _team_of(frame["possessor"])
        if team:
            x, y = frame["ball"]["x"], frame["ball"]["y"]
            v = threat.at(x, y, PITCH_X if team == "home" else 0.0)
            zone = min(ZONES - 1, max(0, int(x / PITCH_X * ZONES)))
            grid[m][zone] += v if team == "home" else -v
            (home if team == "home" else away)[m] += v
        for p in frame["players"]:
            acc = position[p["id"]][m]
            acc[0] += p["x"]
            acc[1] += 1

    for m in range(minutes):
        per_minute = 60 / max(samples[m], 1)
        grid[m] = [round(v * per_minute, 3) for v in grid[m]]
        home[m] = round(home[m] * per_minute, 2)
        away[m] = round(away[m] * per_minute, 2)

    raw = [h - a for h, a in zip(home, away, strict=True)]
    half = SMOOTH_MINUTES // 2
    windows = (raw[max(0, i - half):i + half + 1] for i in range(minutes))
    momentum = [round(sum(w) / len(w), 2) for w in windows]

    cvc: list[dict] = [{} for _ in range(minutes)]
    for fact in control_vs_chaos(events, 60.0):
        _, side, _, window = fact.scope.split(":")
        if int(window) < minutes:
            cvc[int(window)][side] = round(fact.value, 2)

    return {
        "minutes": minutes,
        "zones": ZONES,
        "grid": grid,
        "home_threat": home,
        "away_threat": away,
        "momentum": momentum,
        "control_vs_chaos": cvc,
        "turning_points": turning_points(events, momentum, minutes),
        "players": [{
            "id": r["id"], "team": r["team"], "role": r["role"], "name": r.get("name", r["id"]),
            "x": [round(s / n, 1) if n else None for s, n in position[r["id"]]],
            "involvement": involvement(events, r["id"], minutes),
        } for r in roster],
        "shots": [{
            "id": e["id"], "minute": round(e["t"] / 60, 1), "team": e["team"], "player": e.get("player"),
            "x": e["x"], "outcome": e.get("outcome"), "speed": e.get("ball_speed_kmh"),
        } for e in events if e["type"] == "shot"],
    }


def _sides(momentum: list[float]) -> list[str | None]:
    """Who is on top each minute; None inside the dead band, where neither side clearly is."""
    band = DEAD_BAND * statistics.pstdev(momentum) if len(momentum) > 1 else 0.0
    return ["home" if v > band else "away" if v < -band else None for v in momentum]


def turning_points(events: list[Mapping], momentum: list[float], minutes: int) -> list[dict]:
    """The minutes where the side on top changes and the new side stays on top for HOLD_MINUTES
    before the other side takes over. A swing inside one side's spell is not a turning point."""
    sides = _sides(momentum)
    starts: list[tuple[int, str]] = []
    on_top = None
    for i, side in enumerate(sides):
        if side is None or side == on_top:
            continue
        other = next((j for j in range(i, minutes) if sides[j] not in (side, None)), minutes)
        if sum(s == side for s in sides[i:other]) >= HOLD_MINUTES:
            starts.append((i, side))
            on_top = side

    by_minute = defaultdict(list)
    for e in events:
        by_minute[_minute(e["t"], minutes)].append(e)
    picked: list[dict] = []
    for n, (i, side) in enumerate(starts):
        until = starts[n + 1][0] - 1 if n + 1 < len(starts) else minutes - 1
        sign = 1 if side == "home" else -1
        peak = max(range(i, until + 1), key=lambda m: sign * momentum[m])
        window = [e for m in range(max(0, i - BUILD_UP_MINUTES + 1), i + 1) for e in by_minute[m]]
        mine = [e for e in window if e.get("team") == side]
        theirs = [e for e in window if e.get("team") not in (side, None)]
        passes = [e for e in mine if e["type"] == "pass"]
        cited = passes + [e for e in mine if e["type"] == "pressure" or _is_recovery(e)] + \
            [e for e in theirs if e["type"] == "interception"] + [e for e in window if e["type"] == "shot"]
        picked.append({
            "minute": i,
            "team": side,
            "until": until,
            "held": sum(s == side for s in sides[i:until + 1]),
            "peak_minute": peak,
            "peak": abs(momentum[peak]),
            "passes": len(passes),
            "completed": sum(e.get("outcome") == "success" for e in passes),
            "pressures": sum(e["type"] == "pressure" for e in mine),
            "recoveries": sum(_is_recovery(e) for e in mine),
            "lost": sum(e["type"] == "interception" for e in theirs),
            "shots": [e["id"] for e in window if e["type"] == "shot"],
            "source_ids": sorted({e["id"] for e in cited}),
        })
    return picked


def involvement(events: list[Mapping], player_id: str, minutes: int) -> list[int]:
    out = [0] * minutes
    for e in events:
        if e.get("player") == player_id and e["type"] in INVOLVEMENT:
            out[_minute(e["t"], minutes)] += 1
    return out


def _frames(path: Path) -> Iterable[dict]:
    with open(path) as f:
        for n, line in enumerate(f):
            if n % SAMPLE_EVERY == 0:
                yield json.loads(line)


def main() -> None:
    ap = argparse.ArgumentParser(description="Compute the momentum terrain for one clip.")
    ap.add_argument("clip", type=Path, help="clip directory with events.jsonl, frames.jsonl and meta.json")
    ap.add_argument("out", type=Path)
    args = ap.parse_args()
    meta = json.loads((args.clip / "meta.json").read_text())
    events = [json.loads(line) for line in open(args.clip / "events.jsonl")]
    minutes = max(1, int(-(-meta["minutes"] // 1)))
    frames = _frames(args.clip / "frames.jsonl")
    terrain = build_terrain(events, frames, meta["roster"], minutes, threat_table())
    terrain.update(seed=meta.get("seed"), score=meta["score"])
    args.out.write_text(json.dumps(terrain, separators=(",", ":")))
    print(f"terrain: {minutes} minutes, {len(terrain['turning_points'])} turning points -> {args.out}")


if __name__ == "__main__":
    main()
