"""Typed access to a match's events: the only way agents see the match."""

from __future__ import annotations

import math
from functools import lru_cache

from ninety.match.clock import match_clock
from ninety.sim.engine import simulate

AGENT_TYPES = ("pass", "shot", "goal", "tackle", "interception", "pressure")


@lru_cache(maxsize=8)
def match_events(seed: int, minutes: float) -> tuple[dict, ...]:
    return tuple(simulate(seed, minutes).events)


def minute_of(event: dict) -> int:
    return int(event["t"] // 60) + 1


def compact(event: dict) -> dict:
    """The fields an agent may cite, with derived values computed here so no model does arithmetic."""
    minute = minute_of(event)
    second = int(event["t"] % 60)
    out = {
        "id": event["id"],
        # `minute` is the football ordinal: minute 2 is 01:00 through 01:59, not the clock minute.
        "minute": minute,
        "second": second,
        "clock": match_clock(event["t"]),
        "type": event["type"],
        "team": event["team"],
        "player": event["player"],
    }
    for role in ("receiver", "intended", "interceptor"):
        if event.get(role):
            out[role] = event[role]
    if event["outcome"]:
        out["outcome"] = event["outcome"]
    if event["ball_speed_kmh"] is not None:
        out["ball_speed_kmh"] = round(event["ball_speed_kmh"])
    if event["end_x"] is not None:
        out["distance_m"] = round(math.hypot(event["end_x"] - event["x"], event["end_y"] - event["y"]))
    return out


def events_in(seed: int, minutes: float, minute_from: int, minute_to: int, types=AGENT_TYPES) -> list[dict]:
    return [
        compact(e)
        for e in match_events(seed, minutes)
        if minute_from <= minute_of(e) <= minute_to and e["type"] in types
    ]
