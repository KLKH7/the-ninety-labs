"""The shot map: where each detected shot was struck from, how far from goal and at what angle
(GROUNDING I19). Arithmetic on the shot's own position; no model of how likely it was to score.

A shot's distance is to the centre of the goal its team attacks (home toward x = PITCH_X), and its
angle the one the two posts make at the spot (Law 1: the goal is 7.32 m wide). Which goal a team
attacks follows from its side; when the side did not pass the fact-checker's side gate
(factcheck.side_known), the shot is measured to the nearer goal (a shot is struck at the goal it is
near) and said without its club, and a club's count of shots has bounds. The outcome
(goal, saved, blocked, off target) is added when the line-crossing events of #271 exist; until then
a shot says nothing of how it ended.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping

from ninety.agents.factcheck import side_known
from ninety.intel.scene import PITCH_X, PITCH_Y, POSITION_ERROR_M, minute_of

GOAL_W = 7.32  # Law 1: the distance between the posts (GROUNDING L1)
# Law 1: the penalty area reaches 16.5 m into the field from the goal line, and 16.5 m out from each
# post along it, so 16.5 + 7.32 / 2 = 20.16 m either side of the goal's centre.
BOX_DEPTH_M = 16.5
BOX_HALF_W = 16.5 + GOAL_W / 2
# "and took 3 shots from inside the penalty area": the inside count is the number after "took".
INSIDE_CONTEXT = r"\btook\s+$"
OUTCOMES = ("goal", "saved", "blocked", "off_target")  # the words of #271's shot outcomes


def geometry(x: float, y: float, team: str | None) -> tuple[float, float]:
    """Metres to the goal's centre, and the angle in degrees the posts make at the spot: the goal
    `team` attacks, or the nearer goal when the side is not known (None)."""
    if team is None:
        team = "home" if x > PITCH_X / 2 else "away"
    gx = PITCH_X if team == "home" else 0.0
    dx, dy = abs(gx - x), y - PITCH_Y / 2
    a = math.atan2(GOAL_W / 2 - dy, dx) + math.atan2(GOAL_W / 2 + dy, dx)  # to each post, summed
    return math.hypot(dx, dy), math.degrees(a)


def near_box_line(x: float, y: float, team: str | None) -> bool:
    """Whether the spot is within the players' position error of the penalty area's line, so the
    shot could have been inside it or outside (I1's 1.26 m, the spot being a ball and player's)."""
    if team is None:
        team = "home" if x > PITCH_X / 2 else "away"
    depth = PITCH_X - x if team == "home" else x
    dy = abs(y - PITCH_Y / 2)
    e = POSITION_ERROR_M
    return (abs(depth - BOX_DEPTH_M) <= e and dy <= BOX_HALF_W + e) or (
        abs(dy - BOX_HALF_W) <= e and depth <= BOX_DEPTH_M + e
    )


def inside_box(x: float, y: float, team: str | None) -> bool:
    if team is None:
        team = "home" if x > PITCH_X / 2 else "away"
    depth = PITCH_X - x if team == "home" else x  # metres from the goal line the team attacks
    return depth <= BOX_DEPTH_M and abs(y - PITCH_Y / 2) <= BOX_HALF_W


def shots(events: Iterable[Mapping]) -> list[dict]:
    out = []
    for e in events:
        if e.get("type") != "shot" or e.get("team") not in ("home", "away"):
            continue
        known = side_known(e)
        dist, angle = geometry(float(e["x"]), float(e["y"]), e["team"] if known else None)
        out.append(
            {
                "id": f"shot:{e['id']}",
                "kind": "shot",
                "metric": "shot_distance_m",
                "team": e["team"] if known else None,  # a side the gate did not pass names no club
                "minute": minute_of(float(e["t"])),
                "t": round(float(e["t"]), 2),
                "passer": e.get("player"),  # named as a passer is: the role gate decides (I6)
                "inside_box": inside_box(float(e["x"]), float(e["y"]), e["team"] if known else None),
                "near_box_line": near_box_line(float(e["x"]), float(e["y"]), e["team"] if known else None),
                "x": round(float(e["x"]), 1),
                "y": round(float(e["y"]), 1),
                "value": round(dist),
                "unit": "m",
                "angle_deg": round(angle),
                "also": [[round(angle), "degrees"]],
                "outcome": e.get("outcome") if e.get("outcome") in OUTCOMES else None,
                "confident": True,  # where it was struck from: the video saw it
                "side_known": known,
                "event": e["id"],
                "event_confidence": e.get("confidence"),
            }
        )
    return out


def _inside(rows: Iterable[Mapping]) -> dict:
    """The shots from inside the penalty area, with bounds from those within the error of its line:
    the count is said only when no shot is that close (`inside_exact`)."""
    rows = list(rows)
    lo = sum(r["inside_box"] and not r["near_box_line"] for r in rows)
    hi = sum(r["inside_box"] or r["near_box_line"] for r in rows)
    return {
        "inside_box": lo,
        "inside_lo": lo,
        "inside_hi": hi,
        "inside_exact": lo == hi,
        # Unsure, the inside count is still bound to its words, to a count no shot can have, so no
        # number said after "took" passes (merge-queue review of #318); code then leaves it unsaid.
        "also": [[lo if lo == hi else -1, "shots", INSIDE_CONTEXT]],
    }


def summary(rows: Iterable[Mapping], minute_from: int, minute_to: int) -> dict[str, dict]:
    """Each team's shots in the window and those from inside the penalty area, with bounds from the shots
    whose side the video could not tell (they could be either team's)."""
    window = [r for r in rows if minute_from <= r["minute"] <= minute_to]
    unknown = [r for r in window if not r["side_known"]]
    out = {
        "all": {
            "id": f"shots:all:m{minute_from}-{minute_to}",
            "kind": "shots",
            "metric": "shots_all",
            "team": None,
            "minute_from": minute_from,
            "minute_to": minute_to,
            "value": len(window),
            "unit": "shots",
            **_inside(window),
            "confident": True,
        }
    }
    for team in ("home", "away"):
        known = [r for r in window if r["side_known"] and r["team"] == team]
        out[team] = {
            "id": f"shots:{team}:m{minute_from}-{minute_to}",
            "kind": "shots",
            "metric": "shots",
            "team": team,
            "minute_from": minute_from,
            "minute_to": minute_to,
            "value": len(known),
            "unit": "shots",
            "lo": len(known),
            "hi": len(known) + len(unknown),
            **_inside(known),
            "confident": not unknown,
        }
    return out
