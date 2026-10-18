"""Pressing, territory and tempo in time windows, and the shifts between them.

Event-based and deterministic, like the rest of `ninety/intel`: each fact cites exactly the events
it counts. Home attacks toward x = 105 for the whole match and away toward x = 0, as the data
contract's pitch frame does (no change of ends). The zone rules here are the only copy: the
style fingerprint (`ninety/sim/fingerprint.py`) calls them (lesson 69).
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping

from ninety.intel.stats import Fact, _fact

PITCH_X = 105.0
PPDA_ZONE = 0.6  # PPDA counts the opponents' passes in their own 60% of the pitch
DEFENSIVE_ACTIONS = frozenset({"tackle", "interception"})
# Fifteen minutes, football's usual split: the shortest window in which a share has enough events
# to mean something. On seeds 7 and 11 (90 minutes) a 15-minute window held a median of 11
# attacking-third passes (a share's standard error near 0.15) and every team-window had a
# defensive action; five minutes held 3, and a third of team-windows had no defensive action.
WINDOW_S = 900.0


def other(team: str) -> str:
    return "away" if team == "home" else "home"


def own_goal_x(team: str) -> float:
    return 0.0 if team == "home" else PITCH_X


def from_own_goal(team: str, x: float) -> float:
    """How far x is from this team's own goal line, in metres."""
    return abs(float(x) - own_goal_x(team))


def ppda_events(team: str, events: Iterable[Mapping]) -> tuple[list[Mapping], list[Mapping]]:
    """PPDA's two counts for `team` pressing: the opponents' passes in their own 60% of the pitch,
    and `team`'s defensive actions (tackles and interceptions) in that same zone."""
    opp = other(team)
    events = list(events)
    passes = [e for e in events if e.get("type") == "pass" and e["team"] == opp
              and from_own_goal(opp, e["x"]) <= PPDA_ZONE * PITCH_X]
    actions = [e for e in events if e.get("type") in DEFENSIVE_ACTIONS and e["team"] == team
               and from_own_goal(opp, e["x"]) <= PPDA_ZONE * PITCH_X]
    return passes, actions


def attacking_third_passes(team: str, events: Iterable[Mapping]) -> list[Mapping]:
    """`team`'s passes played from its attacking third: field tilt's numerator."""
    return [e for e in events if e.get("type") == "pass" and e["team"] == team
            and from_own_goal(team, e["x"]) >= 2 * PITCH_X / 3]


def field_tilt(team: str, events: Iterable[Mapping]) -> tuple[float | None, list[Mapping]]:
    """`team`'s share of both teams' attacking-third passes, and the passes counted. None with no
    attacking-third pass by either side: no territory to share."""
    events = list(events)
    ours, theirs = attacking_third_passes(team, events), attacking_third_passes(other(team), events)
    total = len(ours) + len(theirs)
    return (len(ours) / total if total else None), ours + theirs


def _ids(events: Iterable[Mapping]) -> list[str]:
    return [str(e["id"]) for e in events]


def _windows(events: list[Mapping], window_s: float) -> list[list[Mapping]]:
    if window_s <= 0:
        raise ValueError("window_s must be positive")
    if not events:
        return []
    count = int(max(float(e.get("t", 0)) for e in events) // window_s) + 1
    out: list[list[Mapping]] = [[] for _ in range(count)]
    for e in events:
        out[int(float(e.get("t", 0)) // window_s)].append(e)
    return out


def window_facts(events: Iterable[Mapping], window_s: float = WINDOW_S) -> list[Fact]:
    """PPDA, field tilt and passes a minute for each team in each window. A measure with nothing
    to count in a window (no defensive action for PPDA, no attacking-third pass for field tilt) is
    left out rather than given an invented value."""
    facts: list[Fact] = []
    for index, window in enumerate(_windows(list(events), window_s)):
        for team in ("home", "away"):
            scope = f"team:{team}:window:{index}"
            passes, actions = ppda_events(team, window)
            if actions:
                facts.append(_fact("ppda", len(passes) / len(actions), "passes per action", scope,
                                   _ids(passes + actions)))
            tilt, counted = field_tilt(team, window)
            if tilt is not None:
                facts.append(_fact("field_tilt", tilt, "share", scope, _ids(counted)))
            ours = [e for e in window if e.get("type") == "pass" and e["team"] == team]
            if ours:
                facts.append(_fact("passes_per_minute", len(ours) / (window_s / 60.0), "passes/min",
                                   scope, _ids(ours)))
    return facts


def leader(window: Iterable[Mapping]) -> tuple[str | None, list[Mapping]]:
    """The side that held the territory in a window, and the passes counted. A side leads only when
    its field tilt is more than one standard error from level (0.5 / sqrt(n) for n passes counted):
    closer than that, the window cannot tell the sides apart, so nobody leads it."""
    tilt, counted = field_tilt("home", window)
    if tilt is None or abs(tilt - 0.5) <= 0.5 / math.sqrt(len(counted)):
        return None, counted
    return ("home" if tilt > 0.5 else "away"), counted


def territory_shifts(events: Iterable[Mapping], window_s: float = WINDOW_S) -> list[Fact]:
    """When a window's leader (see `leader`) is the other side from the last window that had one,
    one fact for the side that took over, scoped to that window. Its value is that side's field tilt
    there; it cites the passes counted. A window nobody leads changes nothing, and the first leader
    of the match is no shift."""
    facts: list[Fact] = []
    current: str | None = None
    for index, window in enumerate(_windows(list(events), window_s)):
        side, counted = leader(window)
        if side is None or side == current:
            continue
        if current is not None:
            facts.append(_fact("territory_shift", field_tilt(side, window)[0], "share",
                               f"team:{side}:window:{index}", _ids(counted)))
        current = side
    return facts
