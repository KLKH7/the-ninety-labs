"""Team shape from tracked positions, per team per match minute.

Model-free, like the rest of `ninety/intel`: code computes every number and the agents only explain
it. It reads frames as `tracking.Track` holds them (each player's id, team, x and y, and the ball's
x and y), so the broadcast camera's tracked frames and the tactical camera's fused output, which keep
the same `tracked.json` schema, go through it unchanged. The live path hands it tracked frames only
(`ninety.match.tracking.tracked`, which refuses anything not `source: tracked`); it never reads the
answer key.

What it computes (docs/GROUNDING.md, S6 to S12), each for one team's players in one frame, then the
median over the minute's frames:

- width: the distance across the pitch between the team's two widest outfield players;
- length: the distance along the pitch between its deepest and most advanced outfield players;
- line height: how far its deepest outfield player stands from its own goal line, the line the
  opponents' offside position is judged against while the keeper is behind it (Law 11);
- area: the convex hull of its outfield players, the usual measure of how compact a team is;
- the gaps between its lines: the outfield players split into three lines along the pitch at the
  two largest gaps between them, and the distance from each line's mean depth to the next;
- behind and ahead of the ball: how many of its players are nearer their own goal line than the
  ball is, and how many are further from it.

Home attacks toward x = 105 for the whole match and away toward x = 0, as the data contract's pitch
frame does (ninety/intel/windows.py), so a player's depth is x for home and 105 - x for away.

Every fact says how many of the team's 11 were tracked, and is `confident` only when enough were
for its value to be within the tracker's own position error of the value all 11 would give: below
that, the fact-checker holds any claim that cites it (ninety/agents/factcheck.confidence_gate).
"""

from __future__ import annotations

import math
import statistics
from collections import defaultdict
from collections.abc import Iterable, Mapping

PITCH_X = 105.0  # Law 1, the data contract's pitch (schemas/match_event.schema.json)
PITCH_Y = 68.0
# Law 1: the penalty area reaches 16.5 m into the pitch from the goal line, and 16.5 m to each side
# of the goalposts, whose inside edges are 7.32 m apart: 3.66 + 16.5 = 20.16 m from the centre line.
PENALTY_DEPTH_M = 16.5
PENALTY_HALF_WIDTH_M = 20.16
TEAM_SIZE = 11  # Law 3: at most eleven players a team, one of them the goalkeeper
# Tracked pitch positions are this far off at the 90th percentile (ninety/vision/events.RIVAL_M,
# measured on validation clips; tests/test_shape.py holds the two equal). Restated here so the
# window facts load no vision code. It sets both the rounding and the coverage rule below.
POSITION_ERROR_M = 1.26
# Measured (docs/eval/shape-coverage.md, plan committed first in docs/eval/shape-coverage-plan.md):
# the fewest tracked players of 11 at which every distance and area fact was within
# POSITION_ERROR_M (area: within its hull's perimeter times POSITION_ERROR_M) of the value from all
# 11, at the 90th percentile, on simulated matches of seeds 7 and 11, for players missing at random
# and for the players furthest from the ball missing.
MIN_TRACKED = 11
# A count of players behind the ball is wrong by every player missing on that side, and a missing
# player may be on either side: a count is only stated when all 11 were tracked (by definition).
COUNT_TRACKED = TEAM_SIZE
# Design: at least a second of frames (25 at the engine's 25 fps) before a minute's median is read;
# fewer is a glimpse, not a shape.
MIN_FRAMES = 25
WINDOW_S = 60.0  # one match minute, the workflow's unit (ninety/agents/workflow.py)

DISTANCES = ("width", "length", "line_height", "back_to_mid", "mid_to_front")
COUNTS = ("behind_ball", "ahead_of_ball")
METRICS = (*DISTANCES, "area", *COUNTS)
UNITS = {**{m: "m" for m in DISTANCES}, "area": "m²", **{m: "players" for m in COUNTS}}
# Rounding, from the position error: a distance is stated to the metre (a decimal would claim a
# precision the tracker does not have, 1.26 m), an area to 10 m² (a few percent of the reference
# team area of about 900 m², docs/GROUNDING.md S9).
AREA_STEP_M2 = 10


def depth(team: str, x: float) -> float:
    """How far x is from this team's own goal line, in metres."""
    return float(x) if team == "home" else PITCH_X - float(x)


def in_own_penalty_area(d: float, y: float) -> bool:
    return d <= PENALTY_DEPTH_M and abs(float(y) - PITCH_Y / 2) <= PENALTY_HALF_WIDTH_M


def hull(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """The convex hull, counter-clockwise (Andrew's monotone chain)."""
    pts = sorted(set(points))
    if len(pts) < 3:
        return pts

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower: list[tuple[float, float]] = []
    upper: list[tuple[float, float]] = []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return lower[:-1] + upper[:-1]


def area_and_perimeter(points: list[tuple[float, float]]) -> tuple[float, float]:
    ring = hull(points)
    if len(ring) < 3:
        return 0.0, 0.0
    pairs = list(zip(ring, ring[1:] + ring[:1], strict=True))
    area = abs(sum(a[0] * b[1] - b[0] * a[1] for a, b in pairs)) / 2
    return area, sum(math.dist(a, b) for a, b in pairs)


def lines(depths: list[float]) -> list[list[float]] | None:
    """Outfield depths split into back, middle and front lines at the two largest gaps between
    neighbours (design: how a formation's lines read from positions alone). None with fewer than 3."""
    ds = sorted(depths)
    if len(ds) < 3:
        return None
    gaps = sorted(range(1, len(ds)), key=lambda i: (ds[i] - ds[i - 1], -i), reverse=True)[:2]
    a, b = sorted(gaps)
    return [ds[:a], ds[a:b], ds[b:]]


def frame_shape(team: str, players: Iterable[Mapping], ball: Mapping) -> dict:
    """One team's shape in one frame: every metric it can be measured for, the area's hull perimeter
    (what the coverage rule compares an area error with), and how many of the team were tracked."""
    own = [(depth(team, p["x"]), float(p["y"])) for p in players if p["team"] == team]
    out: dict = {"tracked": len(own)}
    if not own:
        return out
    ball_d = depth(team, ball["x"])
    out["behind_ball"] = sum(d < ball_d for d, _ in own)
    out["ahead_of_ball"] = sum(d > ball_d for d, _ in own)
    deepest = min(own)
    # The keeper is the deepest player when he is inside his own penalty area. Tracking reads no
    # shirt or role, so a defender in the box with the keeper untracked is taken for him: the
    # coverage rule (11 tracked) is what keeps that case off the air.
    outfield = [p for p in own if p is not deepest] if in_own_penalty_area(*deepest) else own
    if len(outfield) >= 2:
        ds, ys = [d for d, _ in outfield], [y for _, y in outfield]
        out["width"] = max(ys) - min(ys)
        out["length"] = max(ds) - min(ds)
        out["line_height"] = min(ds)
    if len(outfield) >= 3:
        out["area"], out["perimeter"] = area_and_perimeter(outfield)
        split = lines([d for d, _ in outfield])
        if split:
            back, mid, front = (statistics.fmean(line) for line in split)
            out["back_to_mid"], out["mid_to_front"] = mid - back, front - mid
    return out


def _half_up(value: float, step: float = 1.0) -> int:
    """Rounded half up to a multiple of step, the same on every Python (lesson 134)."""
    return int(math.floor(value / step + 0.5) * step)


def stated(metric: str, value: float) -> int:
    """A metric's value as a fact states it (see the rounding note at AREA_STEP_M2)."""
    return _half_up(value, AREA_STEP_M2 if metric == "area" else 1.0)


def need(metric: str) -> int:
    return COUNT_TRACKED if metric in COUNTS else MIN_TRACKED


def minute_of(t: float) -> int:
    """Football minutes: minute 1 is 00:00 to 00:59 (ninety/match/facts.minute_of)."""
    return int(float(t) // WINDOW_S) + 1


def side_confidence(frames: list[Mapping], team: str) -> float | None:
    """How surely this team's players were told to be this team, over the frames a fact reads: 1.0
    for ground-truth frames (the simulator knows its sides); for tracked frames the least sure of its
    players' `side_confidence`, or None when any player carries none (today's tracked frames carry
    none). The fact-checker gates a side named from it as it gates a detection's
    (factcheck.side_known)."""
    if frames and all(f.get("source") == "truth" for f in frames):
        return 1.0
    sides = [p.get("side_confidence") for f in frames for p in f["players"] if p["team"] == team]
    return None if not sides or any(s is None for s in sides) else min(sides)


def window_shape(frames: Iterable[Mapping], team: str) -> dict:
    """One team's per-frame shapes over some frames, summarised: each metric's median, the median
    number tracked, the most tracked in any frame and the frames read."""
    frames = list(frames)
    shapes = [frame_shape(team, f["players"], f["ball"]) for f in frames]
    out = {"frames": len(shapes),
           "tracked": _half_up(statistics.median([s["tracked"] for s in shapes])) if shapes else 0,
           "most": max((s["tracked"] for s in shapes), default=0),
           "team_confidence": side_confidence(frames, team)}
    for metric in (*METRICS, "perimeter"):
        values = [s[metric] for s in shapes if metric in s]
        if values:
            out[metric] = statistics.median(values)
    return out


def shape_rows(frames: Iterable[Mapping]) -> list[dict]:
    """The shape facts the agents read and the fact-checker checks: one row per metric per team per
    match minute, oldest first. `change` is the value less the same team's value the minute before,
    given only when both are confident. A team with more than 11 players in a frame has a false
    track among them (Law 3), so none of its facts that minute is confident."""
    by_minute: dict[int, list[Mapping]] = defaultdict(list)
    for f in frames:
        by_minute[minute_of(f["t"])].append(f)
    rows: list[dict] = []
    last: dict[tuple[str, str], dict] = {}
    for minute in sorted(by_minute):
        for team in ("home", "away"):
            w = window_shape(by_minute[minute], team)
            for metric in METRICS:
                if metric not in w:
                    continue
                value = stated(metric, w[metric])
                confident = (w["tracked"] >= need(metric) and w["most"] <= TEAM_SIZE
                             and w["frames"] >= MIN_FRAMES)
                before = last.get((team, metric))
                change = (value - before["value"]
                          if confident and before and before["confident"] and before["minute"] == minute - 1
                          else None)
                row = {
                    "id": f"shape:{metric}:{team}:m{minute}", "type": "shape", "metric": metric,
                    "team": team, "minute": minute, "value": value, "unit": UNITS[metric],
                    "change": change, "tracked": w["tracked"], "of": TEAM_SIZE, "need": need(metric),
                    "frames": w["frames"], "confident": confident,
                    "team_confidence": w["team_confidence"],
                }
                rows.append(row)
                last[(team, metric)] = row
    return rows


__all__ = [
    "COUNTS", "DISTANCES", "METRICS", "MIN_TRACKED", "POSITION_ERROR_M", "TEAM_SIZE", "UNITS",
    "frame_shape", "lines", "shape_rows", "window_shape",
]
