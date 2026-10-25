"""Each named player's running (GROUNDING I22): distance, top speed, sprints and where he spent his
time, from the tracked positions alone.

Each track is read a step a second, as team distance is (I16), so its measured label holds for the
distance, and a frame's jitter cannot make a top speed: the top speed is the fastest second. A
sprint is a run above SPRINT_KMH, the most common absolute sprint threshold in match analysis
(I22), held for at least MIN_SPRINT_S (*design*: one step). Where he spent his time is the zone of the
pitch's nine (thirds by channels, as the overloads read them, I3) he was in most, as his team
attacks.

Rows are kept per track and minute, so a window sums them; a named player's pieces of track are one
player (lesson 241), and a track with no name is left out: a fan asks about a player by his name.
Distance is the tracked distance of the footage shown, with team distance's measured label (I16).
"""

from __future__ import annotations

import json
import math
from collections import defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path

from ninety.intel import overloads
from ninety.intel.scene import FPS, minute_of
from ninety.intel.stats import SPRINT_THRESHOLD_KMH

SPRINT_KMH = SPRINT_THRESHOLD_KMH  # one source, one constant (stats.py, GROUNDING I22)
# The labels the phone says with each figure, measured on held-out simulated matches against the
# truth (ninety/eval/physical_eval.py --calibrate, docs/eval/physical.md).
CALIBRATION = Path(__file__).with_name("physical_calibration.json")


def labels() -> dict:
    return json.loads(CALIBRATION.read_text()) if CALIBRATION.exists() else {}


# The phone card's worst measured top-speed error on tracked footage (docs/eval/companion-tracked.md:
# 1.5 km/h median, 4.2 worst): the bar a named player's top speed must meet to be said.
TOP_SPEED_BAR_KMH = 4.2


def held(lb: dict, bar: int | None) -> dict[str, str]:
    """Which figures are held, and why: each against its own label and bar."""
    out = {}
    if not lb or bar is None or lb.get("distance_pct", 1e9) > bar:
        out["player_km"] = f"his distance is measured to ±{lb.get('distance_pct')}%, worse than ±{bar}%"
    if not lb or bar is None or lb.get("sprints_pct", 1e9) > bar:
        out["player_sprints"] = f"his sprints are measured to ±{lb.get('sprints_pct')}%, worse than ±{bar}%"
    if not lb or lb.get("top_kmh", 1e9) > TOP_SPEED_BAR_KMH:
        out["player_top_kmh"] = (
            f"his top speed is measured to ±{lb.get('top_kmh')} km/h, worse than ±{TOP_SPEED_BAR_KMH}"
        )
    return out
MIN_SPRINT_S = 1.0
STEP_S = 1.0  # a step a second: the tracked frames' smoothing, team distance's step (team_stats.STEP_S)
MAX_STEP_KMH = 12.0 * 3.6  # a step past this is a track jumping, not a player (team_stats.MAX_STEP_MPS)


def _zone(x: float, y: float, team: str) -> str:
    i = min(2, max(0, int(x // overloads.THIRD_M)))
    j = min(2, max(0, int(y // overloads.CHANNEL_M)))
    third, channel = overloads.zone_name(team, i, j)
    return f"{third}-{channel}"


def rows(frames: Sequence[Mapping]) -> list[dict]:
    """One row per track and minute: metres, top speed, sprints begun, seconds in each zone. Each
    track is read a step a second (STEP_S), as team distance is (I16): the label measured for it then
    holds, and a frame's jitter cannot make a top speed or a sprint."""
    every = round(STEP_S * FPS)
    last: dict[str, tuple[float, float, float]] = {}
    run: dict[str, float] = defaultdict(float)
    by: dict[tuple[str, int], dict] = {}
    for fr in frames:
        if int(fr["frame"]) % every:
            continue
        t = float(fr["t"])
        for pl in fr["players"]:
            track, x, y = pl["id"], float(pl["x"]), float(pl["y"])
            prev = last.get(track)
            last[track] = (t, x, y)
            if prev is None or t - prev[0] > STEP_S * 1.5:
                run[track] = 0.0
                continue
            dt = t - prev[0]
            kmh = math.hypot(x - prev[1], y - prev[2]) / dt * 3.6
            m = minute_of(t)
            r = by.setdefault(
                (track, m),
                {"id": f"run:{track}:m{m}", "kind": "running_minute", "track": track, "team": pl["team"],
                 "minute": m, "m": 0.0, "top_kmh": 0.0, "sprints": 0, "zones": defaultdict(float)},
            )
            if kmh > MAX_STEP_KMH:
                run[track] = 0.0
                continue
            r["m"] += kmh / 3.6 * dt
            r["top_kmh"] = max(r["top_kmh"], kmh)
            r["zones"][_zone(x, y, pl["team"])] += dt
            before = run[track]
            run[track] = before + dt if kmh >= SPRINT_KMH else 0.0
            if before < MIN_SPRINT_S <= run[track]:
                r["sprints"] += 1  # counted once, in the minute it reached a second
    return [
        {**r, "m": round(r["m"], 1), "top_kmh": round(r["top_kmh"], 1), "zones": dict(r["zones"])}
        for r in by.values()
    ]


def players(
    running: Sequence[Mapping], people: Mapping[str, Mapping], minute_from: int, minute_to: int
) -> list[dict]:
    """Each named player's distance, top speed, sprints and main zone over the minutes."""
    by: dict[tuple[str, str], dict] = {}
    for r in running:
        if not minute_from <= r["minute"] <= minute_to:
            continue
        who = people.get(r["track"], {})
        if not who.get("name"):
            continue
        p = by.setdefault(
            (who["team"], who["name"]),
            {"m": 0.0, "top_kmh": 0.0, "sprints": 0, "zones": defaultdict(float), "track": r["track"]},
        )
        p["m"] += r["m"]
        p["top_kmh"] = max(p["top_kmh"], r["top_kmh"])
        p["sprints"] += r["sprints"]
        for z, sec in r["zones"].items():
            p["zones"][z] += sec
    out = []
    for (team, name), p in sorted(by.items(), key=lambda kv: (-kv[1]["m"], kv[0])):
        zone = max(p["zones"], key=p["zones"].get) if p["zones"] else None
        base = {"team": team, "player": p["track"], "player_is": name, "minute_from": minute_from,
                "minute_to": minute_to, "confident": True}
        key = f"{team}:{name}:m{minute_from}-{minute_to}".replace(" ", "_")
        out += [
            {**base, "id": f"dist:{key}", "kind": "running", "metric": "player_km",
             "value": round(p["m"] / 1000, 1), "unit": "km"},
            {**base, "id": f"top:{key}", "kind": "running", "metric": "player_top_kmh",
             "value": round(p["top_kmh"], 1), "unit": "km/h"},
            {**base, "id": f"sprint:{key}", "kind": "running", "metric": "player_sprints",
             # the threshold has its own unit, so it is never taken for the count
             "value": p["sprints"], "unit": "times", "also": [[SPRINT_KMH, "km/h"]]},
        ]
        if zone:
            third, channel = zone.split("-")
            out.append({**base, "id": f"zone:{key}", "kind": "running", "metric": "player_zone",
                        "value": None, "unit": None, "third": third, "channel": channel})
    return out


__all__ = ["MIN_SPRINT_S", "SPRINT_KMH", "players", "rows"]
