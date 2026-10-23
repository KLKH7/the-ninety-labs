"""Counter-pressing: what a team does in the seconds after it loses the ball in open play.

Possession is read from vision's detected events in time order (docs/GROUNDING.md I4): a pass or a
shot is its team's; an interception is the interceptor's; a tackle won is the tackler's and a
tackle lost his opponent's; a possession change is the side it names. A turnover is a change of the
side in possession between two such events with no dead ball between them (out of play, a goal, a
kick-off, a set piece, a foul or offside): losing it into touch is a restart, not a counter-press.
It happens at the first event of the side that won it.

For each turnover, code computes for the team that lost the ball:

- pressers: the most of its players within PRESS_RADIUS_M of the ball in any tracked frame of the
  COUNTER_S after the turnover, with its bounds (ninety/intel/scene.py);
- regain_s: the time from the turnover to its next open-play possession, if it got the ball back
  before a dead ball; null otherwise. regained is whether that was within COUNTER_S.

The ball's position is the tracked frame's (from the broadcast camera), and its own error is not in
the bounds: only the players' tracking error and the players untracked are.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from ninety.intel.insights import fact, in_minutes
from ninety.intel.scene import FPS, TEAMS, Count, Frames, count, missing, other, players

# StatsBomb's counter-press: pressure applied within five seconds of a team losing possession; its
# pressure is an opponent within five yards of the player on the ball (docs/GROUNDING.md I4).
COUNTER_S = 5.0
PRESS_RADIUS_M = 4.572  # five yards
DEAD_BALL = frozenset({"out_of_play", "goal", "kickoff", "set_piece", "foul", "offside"})


def owner(e: Mapping) -> str | None:
    """The side in possession after event e, or None if e says nothing about possession."""
    kind = e.get("type")
    if kind in ("pass", "shot", "interception", "possession_change"):
        return e["team"]
    if kind == "tackle":
        return e["team"] if e.get("outcome") == "success" else other(e["team"])
    return None


def turnovers(events: Iterable[Mapping]) -> list[dict]:
    """Each open-play turnover: the side that lost it, the event that won it, and the regain."""
    rows = sorted(events, key=lambda e: (e["t"], e["id"]))
    spells: list[tuple[str, Mapping, bool]] = []  # (side, first event, follows a dead ball)
    dead = True
    for e in rows:
        if e.get("type") in DEAD_BALL:
            dead = True
            continue
        side = owner(e)
        if side is None:
            continue
        if not spells or spells[-1][0] != side or dead:
            spells.append((side, e, dead))
        dead = False
    out = []
    for k, (_, won, after_dead) in enumerate(spells):
        if k == 0 or after_dead:
            continue
        lost_by = spells[k - 1][0]
        regain = next((s for s in spells[k + 1 :] if s[2] or s[0] == lost_by), None)
        regain_s = None
        if regain is not None and not regain[2] and regain[0] == lost_by:
            regain_s = round(
                float(regain[1]["t"]) - float(won["t"]), 1
            )  # to 0.1 s: events are timed per frame
        out.append({"team": lost_by, "won": won, "regain_s": regain_s})
    return out


def pressers(team: str, frames: Frames, frame0: int) -> tuple[Count, Mapping | None]:
    """The most of `team`'s players near the ball in any tracked frame of the COUNTER_S from
    frame0, and the frame of that count."""
    best, at = None, None
    for f in frames.between(frame0, frame0 + round(COUNTER_S * FPS)):
        bx, by = float(f["ball"]["x"]), float(f["ball"]["y"])
        margins = [
            PRESS_RADIUS_M - ((float(p["x"]) - bx) ** 2 + (float(p["y"]) - by) ** 2) ** 0.5
            for p in players(f, team)
        ]
        n = count(margins, missing(f, team))
        if best is None or (n.value, n.lo, n.hi) > (best.value, best.lo, best.hi):
            best, at = n, f
    return best or Count(0, 0, 0), at


def counter_press(events: Iterable[Mapping], frames: Frames) -> list[dict]:
    """A fact for every open-play turnover with tracked frames after it."""
    out = []
    for row in turnovers(events):
        won, team = row["won"], row["team"]
        n, at = pressers(team, frames, int(won["frame"]))
        if at is None:
            continue
        ball = [round(float(at["ball"]["x"]), 1), round(float(at["ball"]["y"]), 1)]
        near = [
            [round(float(p["x"]), 1), round(float(p["y"]), 1)]
            for p in players(at, team)
            if ((float(p["x"]) - ball[0]) ** 2 + (float(p["y"]) - ball[1]) ** 2) ** 0.5 <= PRESS_RADIUS_M
        ]
        regained = row["regain_s"] is not None and row["regain_s"] <= COUNTER_S
        out.append(
            fact(
                f"cp:{won['id']}",
                "counter_press",
                "pressers",
                team,
                won["t"],
                n,
                "players",
                at,
                {"ball": ball, "pressers": near, "radius_m": PRESS_RADIUS_M},
                event=won,
                regain_s=row["regain_s"],
                regained=regained,
                won_by=other(team),
                also=[[COUNTER_S, "s"], *([[row["regain_s"], "s"]] if row["regain_s"] is not None else [])],
            )
        )
    return out


def team_summary(facts, minute_from: int, minute_to: int) -> list[dict]:
    """Per team: its turnovers over the minutes and how many it won back within COUNTER_S."""
    out = []
    for team in TEAMS:
        rows = in_minutes(facts, minute_from, minute_to, team)
        back = sum(1 for r in rows if r["regained"])
        out.append(
            {
                "id": f"cp:{team}:m{minute_from}-{minute_to}",
                "kind": "counter_press",
                "metric": "regains_within_5s",
                "team": team,
                "minute_from": minute_from,
                "minute_to": minute_to,
                "value": back,
                "unit": "regains",
                "lo": back,
                "hi": back,
                "confident": True,
                "turnovers": len(rows),
                "also": [[len(rows), "turnovers"], [COUNTER_S, "s"]],
            }
        )
    return out


__all__ = ["COUNTER_S", "PRESS_RADIUS_M", "counter_press", "owner", "pressers", "team_summary", "turnovers"]
