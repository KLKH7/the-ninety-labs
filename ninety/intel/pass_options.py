"""Pass options: the open teammates ahead of the ball at the moment of each pass.

For each detected pass whose frame was tracked, code counts the passer's teammates who were
(docs/GROUNDING.md I5):

- ahead: nearer the goal his team attacks, along the pitch, than the ball where it was played;
- open: no opponent within OPEN_RADIUS_M of them, the radius at which StatsBomb logs a player as
  under pressure (five yards), so an open player could take the ball without being pressed.

The count has its bounds (ninety/intel/scene.py): a teammate within the position error of either
line may be on either side of it; a teammate untracked may be an open one; and an opponent
untracked may stand next to any teammate, so with one missing no teammate is surely open. The fact
also says whether the pass went to one of the open teammates ahead (target_open), the target being
the receiver of a completed pass, else the teammate nearest where the pass ended.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping

from ninety.intel.insights import fact
from ninety.intel.scene import Count, Frames, count, depth, missing, other, players, xy

OPEN_RADIUS_M = 4.572  # five yards (docs/GROUNDING.md I5), the counter-press radius too
# Design: a tracked teammate within this of where the pass was played is the passer, when the
# event's passer is not a track in the frame: about one stride, inside the 1.5 m possession
# distance (docs/GROUNDING.md P6).
PASSER_M = 1.5


def _dist(a: Mapping, x: float, y: float) -> float:
    return math.hypot(float(a["x"]) - x, float(a["y"]) - y)


def options(e: Mapping, frame: Mapping) -> tuple[Count, list, list, Mapping | None]:
    """The open teammates ahead for pass e in `frame`, where the open and the marked ones stand,
    and the pass's target."""
    team, sx, sy = e["team"], float(e["x"]), float(e["y"])
    mates = players(frame, team)
    passer = next((p for p in mates if p["id"] == e.get("player")), None)
    if passer is None:
        near = min(mates, key=lambda p: _dist(p, sx, sy), default=None)
        passer = near if near is not None and _dist(near, sx, sy) <= PASSER_M else None
    mates = [p for p in mates if p is not passer]
    opps = players(frame, other(team))
    margins, open_at, marked_at, nominal_open = [], [], [], set()
    for p in mates:
        ahead = depth(team, p["x"]) - depth(team, sx)
        free = min((_dist(o, float(p["x"]), float(p["y"])) for o in opps), default=math.inf) - OPEN_RADIUS_M
        margin = min(ahead, free)
        margins.append(margin)
        if ahead > 0:
            (open_at if free > 0 else marked_at).append(xy(p))
            if free > 0:
                nominal_open.add(p["id"])
    n = count(margins, missing(frame, team) - (passer is None))
    if missing(frame, other(team)):  # an untracked opponent may be beside any of them
        n = Count(n.value, 0, n.hi)
    target = None
    if e.get("receiver"):
        target = next((p for p in mates if p["id"] == e["receiver"]), None)
    if target is None and e.get("end_x") is not None:
        target = min(mates, key=lambda p: _dist(p, float(e["end_x"]), float(e["end_y"])), default=None)
    return (
        n,
        open_at,
        marked_at,
        (target if target is None else {**target, "open": target["id"] in nominal_open}),
    )


def pass_options(events: Iterable[Mapping], frames: Frames) -> list[dict]:
    """A fact for every detected pass whose frame was tracked."""
    out = []
    for e in events:
        if e.get("type") != "pass":
            continue
        frame = frames.at(int(e["frame"]))
        if frame is None:
            continue
        n, open_at, marked_at, target = options(e, frame)
        visual = {
            "passer": [round(float(e["x"]), 1), round(float(e["y"]), 1)],
            "target": xy(target) if target else None,
            "open": open_at,
            "marked": marked_at,
            "radius_m": OPEN_RADIUS_M,
        }
        out.append(
            fact(
                f"po:{e['id']}",
                "pass_options",
                "open_teammates_ahead",
                e["team"],
                e["t"],
                n,
                "teammates",
                frame,
                visual,
                event=e,
                outcome=e.get("outcome"),
                target_open=target["open"] if target else None,
                passer=e.get("player"),
                also=[[1, "passes"]],
            )
        )
    return out


__all__ = ["OPEN_RADIUS_M", "options", "pass_options"]
