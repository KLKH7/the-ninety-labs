"""Line breaks: how many opponents a completed pass took out of the game (packing).

For each completed detected pass, the opponents between the ball and the goal the passer's team
attacks are counted where the pass was played from and where it ended; the opponents it bypassed
are those nearer that goal than the ball before the pass and no longer nearer it after
(docs/GROUNDING.md I2, the packing count in our own words). "Nearer the goal" is distance to the
centre of the goal, so a wide pass is not credited for opponents it only passed in length.

Every opponent is placed where the tracker had him in the frame the pass was played: the frame of
the reception is not in the detected event, and over a pass's flight defenders run back, so the
count is the opponents the pass went past as it was played, not those still behind it when it
arrived (*design*, docs/GROUNDING.md I2). A failed pass bypasses nobody (packing credits completed passes).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from ninety.intel.insights import fact, in_minutes
from ninety.intel.scene import ZERO, Count, Frames, count, missing, other, players, to_goal, xy


def bypassed(
    team: str, frame: Mapping, start: tuple[float, float], end: tuple[float, float]
) -> tuple[Count, list]:
    """The opponents a pass by `team` from `start` to `end` bypassed in `frame`, and where the
    ones bypassed at their tracked positions stand."""
    opp = other(team)
    d_start, d_end = to_goal(team, *start), to_goal(team, *end)
    margins, where = [], []
    for p in players(frame, opp):
        d = to_goal(team, p["x"], p["y"])
        margin = min(d_start - d, d - d_end)  # nearer than the ball before, and not nearer after
        margins.append(margin)
        if margin > 0:
            where.append(xy(p))
    return count(margins, missing(frame, opp)), where


def line_breaks(events: Iterable[Mapping], frames: Frames) -> list[dict]:
    """A fact for every completed detected pass whose frame was tracked."""
    out = []
    for e in events:
        if e.get("type") != "pass" or e.get("outcome") != "success" or e.get("end_x") is None:
            continue
        frame = frames.at(int(e["frame"]))
        if frame is None:
            continue
        start, end = (float(e["x"]), float(e["y"])), (float(e["end_x"]), float(e["end_y"]))
        n, where = bypassed(e["team"], frame, start, end)
        out.append(
            fact(
                f"lb:{e['id']}",
                "line_break",
                "opponents_bypassed",
                e["team"],
                e["t"],
                n,
                "opponents",
                frame,
                {
                    "from": [round(start[0], 1), round(start[1], 1), e.get("player")],
                    "to": [round(end[0], 1), round(end[1], 1), e.get("receiver")],
                    "bypassed": where,
                },
                event=e,
                passer=e.get("player"),
                receiver=e.get("receiver"),
                also=[[1, "passes"]],  # it is one pass
            )
        )
    return out


def team_totals(facts: Iterable[Mapping], minute_from: int, minute_to: int) -> list[dict]:
    """Each team's opponents bypassed by its completed passes over the minutes, with the bounds
    summed, and its pass that bypassed most (the first, on a tie)."""
    out = []
    for team in ("home", "away"):
        rows = in_minutes(facts, minute_from, minute_to, team)
        total = sum((Count(r["value"], r["lo"], r["hi"]) for r in rows), ZERO)
        best = max(rows, key=lambda r: (r["value"], -r["t"]), default=None)
        out.append(
            {
                "id": f"lb:{team}:m{minute_from}-{minute_to}",
                "kind": "line_break",
                "metric": "opponents_bypassed_total",
                "team": team,
                "minute_from": minute_from,
                "minute_to": minute_to,
                "value": total.value,
                "unit": "opponents",
                "lo": total.lo,
                "hi": total.hi,
                "confident": total.sure,
                "passes": len(rows),
                "best": best["id"] if best else None,
                "also": [[len(rows), "passes"]],
            }
        )
    return out


__all__ = ["bypassed", "line_breaks", "team_totals"]
