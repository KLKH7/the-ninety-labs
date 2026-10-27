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


def until(events: Iterable[Mapping], now: float | None) -> list[Mapping]:
    """The events before `now` (match seconds), all of them with no `now`. A stat asked for at minute
    35 (00:34:00 to 00:34:59, ninety/match/facts.minute_of) has now = 35 * 60 and counts nothing that
    happened after it (lesson 292)."""
    return [e for e in events if now is None or float(e.get("t", 0)) < now]


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


def window_span(index: int, events: list[Mapping], window_s: float = WINDOW_S,
                now: float | None = None) -> tuple[float, float]:
    """A window's start and end in seconds. The last window ends at the last event, or at `now` when
    the stat is asked for during the match: a clip or a match that stops mid-window has not played the
    rest of it, so its tempo is not diluted by minutes that never happened, and a window asked for at
    minute 35 ends at minute 35."""
    start = index * window_s
    last = now if now is not None else max((float(e.get("t", 0)) for e in events), default=start)
    end = start + window_s
    return start, (end if last >= end else max(last, start))


def window_facts(events: Iterable[Mapping], window_s: float = WINDOW_S,
                 now: float | None = None) -> list[Fact]:
    """PPDA, field tilt and passes a minute for each team in each window. A measure with nothing
    to count in a window (no defensive action for PPDA, no attacking-third pass for field tilt) is
    left out rather than given an invented value.

    The same code reads ground truth and detected events (`source: vision`): each counts the events
    it is given. A detected event's confidence is not used to drop it here: one unsure detection
    moves a window's count by one, where it would decide a single-event claim alone, which the
    fact-checker's confidence gate already holds (ninety/agents/factcheck.py). With `now`, only the
    events up to it count and the window running then ends at it (`until`, `window_span`)."""
    facts: list[Fact] = []
    events = until(events, now)
    for index, window in enumerate(_windows(events, window_s)):
        start, end = window_span(index, events, window_s, now)
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
            if ours and end > start:
                facts.append(_fact("passes_per_minute", len(ours) / ((end - start) / 60.0),
                                   "passes/min", scope, _ids(ours)))
    return facts


def leader(window: Iterable[Mapping]) -> tuple[str | None, list[Mapping]]:
    """The side that held the territory in a window, and the passes counted. A side leads only when
    its field tilt is more than one standard error from level (0.5 / sqrt(n) for n passes counted):
    closer than that, the window cannot tell the sides apart, so nobody leads it."""
    tilt, counted = field_tilt("home", window)
    if tilt is None or abs(tilt - 0.5) <= 0.5 / math.sqrt(len(counted)):
        return None, counted
    return ("home" if tilt > 0.5 else "away"), counted


def territory_shifts(events: Iterable[Mapping], window_s: float = WINDOW_S,
                     now: float | None = None) -> list[Fact]:
    """When a window's leader (see `leader`) is the other side from the last window that had one,
    one fact for the side that took over, scoped to that window. Its value is that side's field tilt
    there; it cites the passes counted. A window nobody leads changes nothing, and the first leader
    of the match is no shift."""
    facts: list[Fact] = []
    current: str | None = None
    for index, window in enumerate(_windows(until(events, now), window_s)):
        side, counted = leader(window)
        if side is None or side == current:
            continue
        if current is not None:
            facts.append(_fact("territory_shift", field_tilt(side, window)[0], "share",
                               f"team:{side}:window:{index}", _ids(counted)))
        current = side
    return facts


WINDOW_METRICS = ("ppda", "field_tilt", "passes_per_minute", "territory_shift")


def agent_rows(events: Iterable[Mapping], window_s: float = WINDOW_S, now: float | None = None) -> list[dict]:
    """The window facts as the agents read them (the MCP server's `match_info`, and what the
    fact-checker checks a claim against). Same ids and values as the Ledger's facts, plus the
    numbers a sentence about them may state: the window's first and last match minute and, for a
    share, its percentage. Nothing here is computed anew; it is the facts, re-shaped. With `now`
    (match seconds), only what had happened by then (`window_facts`)."""
    events = until(events, now)
    facts = window_facts(events, window_s, now) + territory_shifts(events, window_s)
    rows = []
    for fact in sorted(facts, key=lambda f: f.id):
        _, team, _, index = fact.scope.split(":")
        start, end = window_span(int(index), events, window_s, now)
        row = {
            "id": fact.id,
            "type": "stat",
            "metric": fact.metric,
            "team": team,
            "window": int(index),
            # Football minutes: minute 1 is 00:00 to 00:59 (ninety/match/facts.minute_of).
            "minute_from": int(start // 60) + 1,
            "minute_to": max(int(start // 60) + 1, math.ceil(end / 60)),
            "value": fact.value,
            "unit": fact.unit,
            "events": len(fact.source_ids),
        }
        if fact.unit == "share":
            row["percent"] = round(fact.value * 100)
        rows.append(row)
    return rows
