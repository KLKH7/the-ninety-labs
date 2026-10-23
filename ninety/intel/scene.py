"""What the insight tools share: the pitch frame, a tracked frame's players, and how sure a count is.

The insight tools (`line_breaks`, `overloads`, `counter_press`, `pass_options`) count players in
a tracked frame: opponents between the ball and goal, players in a zone, players near the ball,
open teammates. Code computes every count; no model is asked. They read tracked frames as
`tracking.Track` holds them (each player's id, team, x and y) and vision's detected events, never
the answer key.

A count from tracking can be wrong two ways, and each fact says by how much, as bounds:

- a player of the team was not tracked in that frame (the team has 11 on the pitch, Law 3). He
  may stand anywhere, so he may or may not be counted: the upper bound adds him;
- a tracked player stands within the tracker's position error of the line that decides whether he
  is counted (a zone's edge, a radius, the ball's distance from goal). He may be on either side of
  it, so the lower bound leaves him out and the upper bound counts him.

`lo` and `hi` are the count's bounds; `value` is the count at the tracked positions. A fact is
`confident` when its bounds agree on what the fact says (a count: lo == hi), and the fact-checker
holds any claim on a fact that is not (ninety/agents/insight_check.py). The bounds are arithmetic on
the two error sources, not a fitted score (docs/GROUNDING.md, I1).

Home attacks toward x = 105 for the whole match and away toward x = 0, the convention the event
detector and the shape facts use (ninety/vision/events.py `_attacks_right`): the engine does not
change ends at half-time.
"""

from __future__ import annotations

import bisect
import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

PITCH_X = 105.0  # Law 1, the data contract's pitch (schemas/match_event.schema.json)
PITCH_Y = 68.0
TEAM_SIZE = 11  # Law 3: at most eleven players a team
TEAMS = ("home", "away")
# Tracked pitch positions are this far off at the 90th percentile, measured on validation clips
# (ninety/vision/events.RIVAL_M; tests/test_insight_scene.py holds the two equal). Restated so the
# insight tools load no vision code.
POSITION_ERROR_M = 1.26
# Design: the furthest a detected event's frame may be from the nearest tracked frame for that
# frame's positions to stand for the moment: two frames at 25 fps, 0.08 s, in which a sprinting
# player (about 9 m/s, docs/GROUNDING.md R6) moves 0.7 m, under the position error.
MAX_FRAME_GAP = 2
FPS = 25  # the engine's (ninety/match/tracking.FPS)


def other(team: str) -> str:
    return "away" if team == "home" else "home"


def attacks_right(team: str) -> bool:
    return team == "home"


def depth(team: str, x: float) -> float:
    """How far x is from this team's own goal line, in metres: further is nearer the goal it attacks."""
    return float(x) if attacks_right(team) else PITCH_X - float(x)


def goal_attacked(team: str) -> tuple[float, float]:
    """The centre of the goal this team attacks."""
    return (PITCH_X if attacks_right(team) else 0.0, PITCH_Y / 2)


def to_goal(team: str, x: float, y: float) -> float:
    """The distance from (x, y) to the centre of the goal `team` attacks."""
    gx, gy = goal_attacked(team)
    return math.hypot(gx - float(x), gy - float(y))


@dataclass(frozen=True)
class Count:
    """A count of players with its bounds (see the module docstring)."""

    value: int
    lo: int
    hi: int

    def __post_init__(self) -> None:
        if not 0 <= self.lo <= self.value <= self.hi:
            raise ValueError(f"bounds out of order: {self.lo} <= {self.value} <= {self.hi}")

    @property
    def sure(self) -> bool:
        return self.lo == self.hi

    def __add__(self, other: Count) -> Count:
        return Count(self.value + other.value, self.lo + other.lo, self.hi + other.hi)


ZERO = Count(0, 0, 0)


def count(margins: Iterable[float], missing: int = 0, error: float = POSITION_ERROR_M) -> Count:
    """A count of players from each tracked player's signed margin from the deciding line: positive
    when he is counted at his tracked position, negative when he is not, its size how far he stands
    from the line. A player within `error` of it is unsure; `missing` players may each be either."""
    value = lo = hi = 0
    for m in margins:
        if m > 0:
            value += 1
        if m > error:
            lo += 1
        if m > -error:
            hi += 1
    return Count(value, lo, hi + max(0, missing))


def players(frame: Mapping, team: str) -> list[Mapping]:
    return [p for p in frame["players"] if p["team"] == team]


def missing(frame: Mapping, team: str) -> int:
    """How many of the team's eleven the frame does not have."""
    return max(0, TEAM_SIZE - len(players(frame, team)))


def tracked_counts(frame: Mapping) -> dict[str, int]:
    return {team: len(players(frame, team)) for team in TEAMS}


class Frames:
    """A clip's tracked frames, looked up by frame number."""

    def __init__(self, frames: Sequence[Mapping]):
        self.frames = sorted(frames, key=lambda f: f["frame"])
        self.numbers = [int(f["frame"]) for f in self.frames]

    def at(self, frame: int, max_gap: int = MAX_FRAME_GAP) -> Mapping | None:
        """The tracked frame nearest `frame`, if one is within `max_gap` frames of it."""
        if not self.numbers:
            return None
        i = bisect.bisect_left(self.numbers, frame)
        near = [j for j in (i - 1, i) if 0 <= j < len(self.numbers)]
        j = min(near, key=lambda k: abs(self.numbers[k] - frame))
        return self.frames[j] if abs(self.numbers[j] - frame) <= max_gap else None

    def between(self, first: int, last: int) -> list[Mapping]:
        lo = bisect.bisect_left(self.numbers, first)
        hi = bisect.bisect_right(self.numbers, last)
        return self.frames[lo:hi]


def minute_of(t: float) -> int:
    """Football's ordinal minute: 0 to 59.99 s is minute 1 (ninety/match/facts.minute_of)."""
    return int(t // 60) + 1


def xy(p: Mapping) -> list[float]:
    return [round(float(p["x"]), 1), round(float(p["y"]), 1)]


__all__ = [
    "FPS",
    "MAX_FRAME_GAP",
    "PITCH_X",
    "PITCH_Y",
    "POSITION_ERROR_M",
    "TEAMS",
    "TEAM_SIZE",
    "ZERO",
    "Count",
    "Frames",
    "attacks_right",
    "count",
    "depth",
    "goal_attacked",
    "minute_of",
    "missing",
    "other",
    "players",
    "to_goal",
    "tracked_counts",
    "xy",
]
