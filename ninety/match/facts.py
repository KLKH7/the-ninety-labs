"""Typed access to a match's events: the only way agents see the match.

Two sources feed `compact`: the simulator's events (`match_events`, the stand-in the agents used
before Milestone 1, kept for the committed replays) and detected events (ninety/match/detected.py,
the live path from Milestone 1). The simulator is imported only when its events are asked for, so
the live path never loads the engine that writes the answer key.
"""

from __future__ import annotations

import math
from functools import lru_cache

from ninety.match.clock import match_clock

AGENT_TYPES = ("pass", "shot", "goal", "tackle", "interception", "pressure")


@lru_cache(maxsize=8)
def match_events(seed: int, minutes: float) -> tuple[dict, ...]:
    from ninety.sim.engine import simulate  # the pre-M1 stand-in; never on the live path

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
        "player": event.get("player"),
    }
    for role in ("receiver", "intended", "interceptor", "deflected_by"):
        if event.get(role):
            out[role] = event[role]
    # Detected events may leave the nullable fields out (schemas/match_event.schema.json).
    if event.get("outcome"):
        out["outcome"] = event["outcome"]
    if event.get("ball_speed_kmh") is not None:
        out["ball_speed_kmh"] = round(event["ball_speed_kmh"])
    if event.get("lofted") is not None:
        # Whether vision saw the ball in the air over the pass: its speed is measured only on the
        # ground (factcheck.measured_speed).
        out["lofted"] = bool(event["lofted"])
    if event.get("end_x") is not None and event.get("end_y") is not None:
        out["distance_m"] = round(math.hypot(event["end_x"] - event["x"], event["end_y"] - event["y"]))
    if event.get("confidence") is not None:
        # How sure the detector is; the fact-checker holds back claims built on a low one.
        out["confidence"] = event["confidence"]
    if event.get("team_confidence") is not None:
        # How firmly the side was told from the kit; a claim naming a team waits for a sure one.
        out["team_confidence"] = event["team_confidence"]
    return out


def select(events, minute_from: int, minute_to: int, types=AGENT_TYPES) -> list[dict]:
    """The compact events of the given types between two match minutes (inclusive)."""
    return [compact(e) for e in events if minute_from <= minute_of(e) <= minute_to and e["type"] in types]


def events_in(seed: int, minutes: float, minute_from: int, minute_to: int, types=AGENT_TYPES) -> list[dict]:
    return select(match_events(seed, minutes), minute_from, minute_to, types)
