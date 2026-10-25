"""Offside position at each completed pass, from the 22 tracked positions (Law 11, docs/GROUNDING.md I14).

In our own words: a player is in an offside position when, at the moment a team-mate plays the
ball, he is in the opponents' half (the halfway line itself does not count) and nearer the
opponents' goal line than both the ball and the second-last opponent. Being there is no offence on
its own; it becomes one when he becomes involved, and receiving the ball is involvement. There is
no offence from a goal kick, a throw-in or a corner kick.

Code reads it for every completed detected pass whose frame was tracked: the receiver's depth
toward the goal his team attacks against the offside line, the deepest of the halfway line, the
ball (where the pass was played) and the second-last opponent. The margin is how far beyond or
short of the line he was. A verdict is given only when the margin is larger than the error of
comparing two tracked positions (POSITION_ERROR_M for each, so sqrt(2) times it for their
difference, *design*); within it the call is `too_close` and nothing is said but that. An untracked
opponent can only move the line toward goal, so it can only turn an offside into onside: with one
missing, "onside" still stands, "offside" becomes `unsure`. Tracking sees a player's position, not
his head, feet or arms, which the Law judges: the fact says so, and the phone shows a line, not a
ruling. A pass that follows a restart within RESTART_S is `restart`: the detector does not say
whether it was a goal kick, throw-in or corner (no offence) or a free kick (an offence possible).
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping

from ninety.intel.insights import fact
from ninety.intel.scene import PITCH_X, POSITION_ERROR_M, Count, Frames, depth, missing, other, players

HALFWAY = PITCH_X / 2
CALL_M = POSITION_ERROR_M * math.sqrt(2)  # two tracked positions compared (see the docstring)
RESTART_S = 3.0  # design: a pass this soon after a restart is the restart's
RESTARTS = frozenset({"set_piece", "out_of_play", "kickoff"})


def _xy(p, pid=None) -> list:
    return [round(float(p["x"]), 1), round(float(p["y"]), 1), pid if pid is not None else p.get("id")]


def offsides(events: Iterable[Mapping], frames: Frames) -> list[dict]:
    rows = sorted(events, key=lambda e: (e["t"], e["id"]))
    out = []
    last_restart = -1e9
    for e in rows:
        if e.get("type") in RESTARTS:
            last_restart = float(e["t"])
            continue
        if e.get("type") != "pass" or e.get("outcome") != "success" or not e.get("receiver"):
            continue
        frame = frames.at(int(e["frame"]))
        if frame is None:
            continue
        team = e["team"]
        receiver = next((p for p in players(frame, team) if p["id"] == e["receiver"]), None)
        opps = players(frame, other(team))
        if receiver is None or len(opps) < 2:
            continue
        d_r = depth(team, receiver["x"])
        ranked = sorted(opps, key=lambda p: depth(team, p["x"]), reverse=True)
        second_last = ranked[1]
        d_ball = depth(team, e["x"])
        line = max(HALFWAY, d_ball, depth(team, second_last["x"]))
        margin = d_r - line
        if float(e["t"]) - last_restart <= RESTART_S:
            verdict = "restart"
        elif abs(margin) <= CALL_M:
            verdict = "too_close"
        elif margin > 0:
            verdict = "unsure" if missing(frame, other(team)) else "offside"
        else:
            verdict = "onside"
        line_x = line if team == "home" else PITCH_X - line
        metres = round(abs(margin), 1)
        sure = verdict in ("onside", "offside")
        row = fact(
            f"off:{e['id']}",
            "offside",
            "offside_margin_m",
            team,
            e["t"],
            Count(0, 0, 0),
            "m",
            frame,
            {
                "line_x": round(line_x, 2),
                "receiver": _xy(receiver),
                "second_last": _xy(second_last),
                "ball": [round(float(e["x"]), 1), round(float(e["y"]), 1), None],
                "attackers": [_xy(p) for p in players(frame, team)],
                "defenders": [_xy(p) for p in opps],
                "verdict": verdict,
                "margin_m": metres,
            },
            # The verdict is what the fact states, and it is sure whatever it is: "too close to call" is
            # as true as "offside". The margin is a number it states only with a call.
            event=e,
            confident=True,
            verdict=verdict,
            margin_m=metres,
            receiver=e["receiver"],
            passer=e.get("player"),
            also=[[metres, "m"]] if sure else [],
        )
        row["value"], row["unit"], row["lo"], row["hi"] = None, None, None, None
        out.append(row)
    return out


__all__ = ["CALL_M", "RESTART_S", "offsides"]
