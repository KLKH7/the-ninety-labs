"""Playing style: how a team plays, from vision's detected passes and the tracked shape facts.

Model-free like the rest of `ninety/intel`: code computes every number and the Companion only
explains it ("why are they playing like this?"). It reads detected events and the shape facts of
#228 (ninety/intel/shape.py, through MatchInsights), never the answer key. Definitions are in
docs/GROUNDING.md I8 to I13:

- channels: the share of a team's passes played from each of the pitch's three channels (left,
  centre, right as that team attacks; the overloads' channels, I3);
- width: a team's median width in the window (shape fact `width`, confident minutes only), beside
  the other team's;
- crosses: passes played from a wide channel in the final third that end in the opponents' penalty
  area (Law 1's area; *design*);
- keeper distribution: the goalkeeper's passes (the track the role assignment calls the keeper,
  past the position gate, ninety/intel/roles.py), long when 32 m or more (Opta's long ball, 35 yards)
  and short otherwise, and the third each ends in;
- counter-attacks: an open-play regain (ninety/intel/counter_press.turnovers) followed by a shot by
  the side that won it before it loses the ball or the ball goes dead: the seconds between them and
  the metres the ball moved toward goal;
- one-twos: a completed pass from A to B and B's completed pass straight back to A within
  ONE_TWO_S, the next pass by A's team (the wall pass; *design* window).

Each summary states its numbers with their units, and a number that belongs to one part of a
summary (the left channel's share, the long balls) carries the words that must come before it, so a
sentence cannot give the left's share to the right (ninety/agents/insight_check.py `_pairs`).
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Iterable, Mapping

from ninety.intel import counter_press
from ninety.intel.overloads import CHANNEL_M, THIRD_M, zone_name
from ninety.intel.scene import PITCH_X, PITCH_Y, TEAMS, depth, minute_of, other

LONG_BALL_M = 32.0  # Opta's long ball: a pass of 35 yards or more (docs/GROUNDING.md I11)
ONE_TWO_S = 5.0  # design: B's return pass comes within five seconds of A's pass
PENALTY_DEPTH_M = 16.5  # Law 1
PENALTY_HALF_WIDTH_M = 20.16  # Law 1: 16.5 m each side of the goal, whose posts are 7.32 m apart
# A context's word must come before its number with no other number between (lesson 221): "long 1 time
# and short 2 times" binds 2 to short, not to long.
CHANNEL_CONTEXT = {c: rf"\b{c}\b[^.%\d]{{0,60}}$" for c in ("left", "centre", "right")}
LONG_CONTEXT = r"\blong\b[^.\d]{0,20}$"
SHORT_CONTEXT = r"\bshort\b[^.\d]{0,20}$"
AGAINST = r"\bagainst\b[^.\d]{0,30}$"


def passes(events: Iterable[Mapping]) -> list[dict]:
    """The detected passes with where they went: the atoms the style reads."""
    out = []
    for e in events:
        if e.get("type") != "pass" or e.get("end_x") is None:
            continue
        out.append(
            {
                "id": e["id"],
                "kind": "pass",
                "t": round(float(e["t"]), 2),
                "minute": minute_of(float(e["t"])),
                "team": e["team"],
                "player": e.get("player"),
                "receiver": e.get("receiver"),
                "outcome": e.get("outcome"),
                "x": float(e["x"]),
                "y": float(e["y"]),
                "end_x": float(e["end_x"]),
                "end_y": float(e["end_y"]),
                "confidence": e.get("confidence"),
            }
        )
    return out


def channel(team: str, x: float, y: float) -> str:
    i = min(2, max(0, int(x // THIRD_M)))
    j = min(2, max(0, int(y // CHANNEL_M)))
    return zone_name(team, i, j)[1]


def third(team: str, x: float) -> str:
    d = depth(team, x)
    return "own" if d < THIRD_M else "middle" if d < 2 * THIRD_M else "final"


def in_their_box(team: str, x: float, y: float) -> bool:
    return PITCH_X - depth(team, x) <= PENALTY_DEPTH_M and abs(y - PITCH_Y / 2) <= PENALTY_HALF_WIDTH_M


def _pct(n: int, total: int) -> int:
    return int(math.floor(100.0 * n / total + 0.5)) if total else 0


def channels(rows: list[dict], team: str, minute_from: int, minute_to: int, club: str) -> dict | None:
    own = [p for p in rows if p["team"] == team]
    if not own:
        return None
    shares = {
        c: _pct(sum(channel(team, p["x"], p["y"]) == c for p in own), len(own))
        for c in ("left", "centre", "right")
    }
    top = max(shares, key=lambda c: (shares[c], c))
    lanes = [
        (c, j)
        for j, c in enumerate(("right", "centre", "left") if team == "home" else ("left", "centre", "right"))
    ]
    return {
        "id": f"style:channels:{team}:m{minute_from}-{minute_to}",
        "kind": "channels",
        "metric": "pass_share_by_channel",
        "team": team,
        "club": club,
        "minute_from": minute_from,
        "minute_to": minute_to,
        "value": shares[top],
        "unit": "%",
        "lo": shares[top],
        "hi": shares[top],
        "confident": True,
        "most": top,
        "shares": shares,
        "also": [[shares[c], "%", CHANNEL_CONTEXT[c]] for c in shares] + [[len(own), "passes"]],
        "visual": {
            "kind": "channels",
            "minute_from": minute_from,
            "minute_to": minute_to,
            "bands": [
                {
                    "channel": c,
                    "y0": round(j * CHANNEL_M, 2),
                    "y1": round((j + 1) * CHANNEL_M, 2),
                    "share": shares[c],
                }
                for c, j in lanes
            ],
        },
    }


def width(
    shape_rows: list[dict], team: str, minute_from: int, minute_to: int, clubs: Mapping[str, str]
) -> dict | None:
    def median(t):
        vals = [
            r["value"]
            for r in shape_rows
            if r["metric"] == "width"
            and r["team"] == t
            and r["confident"]
            and minute_from <= r["minute"] <= minute_to
        ]
        return int(statistics.median(vals) + 0.5) if vals else None

    own, opp = median(team), median(other(team))
    if own is None or opp is None:
        return None
    return {
        "id": f"style:width:{team}:m{minute_from}-{minute_to}",
        "kind": "style_width",
        "metric": "median_width",
        "team": team,
        "club": clubs[team],
        "minute_from": minute_from,
        "minute_to": minute_to,
        "value": own,
        "unit": "m",
        "lo": own,
        "hi": own,
        "confident": True,
        "other_width": opp,
        "also": [[opp, "m", AGAINST]],
    }


def crosses(rows: list[dict], team: str, minute_from: int, minute_to: int, club: str) -> dict:
    own = [p for p in rows if p["team"] == team]
    wide = [p for p in own if third(team, p["x"]) == "final" and channel(team, p["x"], p["y"]) != "centre"]
    cross = [p for p in wide if in_their_box(team, p["end_x"], p["end_y"])]
    found = [p for p in cross if p["outcome"] == "success"]
    return {
        "id": f"style:crosses:{team}:m{minute_from}-{minute_to}",
        "kind": "crosses",
        "metric": "crosses",
        "team": team,
        "club": club,
        "minute_from": minute_from,
        "minute_to": minute_to,
        "value": len(cross),
        "unit": "crosses",
        "lo": len(cross),
        "hi": len(cross),
        "confident": True,
        "completed": len(found),
        "also": [[len(found), "crosses", r"\b(?:found|reached|completed)\b[^.]{0,30}$"]],
    }


def keeper(
    rows: list[dict], team: str, minute_from: int, minute_to: int, club: str, people: Mapping
) -> dict | None:
    keepers = {
        t for t, w in people.items() if w.get("team") == team and w.get("role") == "GK" and w.get("position")
    }
    own = [p for p in rows if p["team"] == team and p["player"] in keepers]
    if not own:
        return None
    long_ = [p for p in own if math.hypot(p["end_x"] - p["x"], p["end_y"] - p["y"]) >= LONG_BALL_M]
    who = max(keepers, key=lambda k: (sum(p["player"] == k for p in own), k))  # the keeper the passes are by
    short = len(own) - len(long_)
    lands = {t: sum(third(team, p["end_x"]) == t for p in own) for t in ("own", "middle", "final")}
    return {
        "id": f"style:keeper:{team}:m{minute_from}-{minute_to}",
        "kind": "keeper",
        "metric": "keeper_long_balls",
        "team": team,
        "club": club,
        "minute_from": minute_from,
        "minute_to": minute_to,
        "value": len(long_),
        "unit": "times",
        "lo": len(long_),
        "hi": len(long_),
        "confident": True,
        "player": who,
        "short": short,
        "passes": len(own),
        "lands": lands,
        "also": [[len(long_), "times", LONG_CONTEXT], [short, "times", SHORT_CONTEXT], [len(own), "passes"]],
    }


def counters(events: Iterable[Mapping]) -> list[dict]:
    """Each open-play regain that led to a shot by the side that won it, before it lost the ball
    or the ball went dead."""
    rows = sorted(events, key=lambda e: (e["t"], e["id"]))
    out = []
    for turn in counter_press.turnovers(rows):
        won = turn["won"]
        side = other(turn["team"])
        for e in rows:
            if e["t"] < won["t"] or e["id"] == won["id"]:
                continue
            if e.get("type") in counter_press.DEAD_BALL:
                break
            owner = counter_press.owner(e)
            if owner is not None and owner != side:
                break
            if e.get("type") == "shot" and e["team"] == side:
                seconds = round(float(e["t"]) - float(won["t"]), 1)
                metres = int(depth(side, e["x"]) - depth(side, won["x"]) + 0.5)
                out.append(
                    {
                        "id": f"counter:{won['id']}",
                        "kind": "counter",
                        "metric": "regain_to_shot_s",
                        "team": side,
                        "minute": minute_of(float(won["t"])),
                        "t": round(float(won["t"]), 2),
                        "value": seconds,
                        "unit": "s",
                        "lo": seconds,
                        "hi": seconds,
                        "confident": True,
                        "event": e["id"],
                        "event_confidence": min(
                            c for c in (won.get("confidence"), e.get("confidence")) if c is not None
                        )
                        if won.get("confidence") is not None or e.get("confidence") is not None
                        else None,
                        "player": e.get("player"),
                        "metres": metres,
                        "also": [[metres, "m"]],
                        "visual": {
                            "kind": "counter",
                            "from": [round(float(won["x"]), 1), round(float(won["y"]), 1), None],
                            "to": [round(float(e["x"]), 1), round(float(e["y"]), 1), e.get("player")],
                            "seconds": seconds,
                        },
                    }
                )
                break
    return out


def one_twos(rows: list[dict]) -> list[dict]:
    out = []
    for a, b in zip(rows, rows[1:], strict=False):
        if (
            a["team"] == b["team"]
            and a["outcome"] == "success"
            and b["outcome"] == "success"
            and a["player"]
            and a["receiver"]
            and b["player"] == a["receiver"]
            and b["receiver"] == a["player"]
            and 0 < b["t"] - a["t"] <= ONE_TWO_S
        ):
            conf = [c for c in (a["confidence"], b["confidence"]) if c is not None]
            out.append(
                {
                    "id": f"onetwo:{a['id']}",
                    "kind": "one_two",
                    "metric": "one_two",
                    "team": a["team"],
                    "minute": a["minute"],
                    "t": a["t"],
                    "value": None,
                    "unit": None,
                    "confident": True,
                    "passer": a["player"],
                    "receiver": a["receiver"],
                    "event": b["id"],
                    "event_confidence": min(conf) if conf else None,
                    "visual": {
                        "kind": "one_two",
                        "from": [round(a["x"], 1), round(a["y"], 1), a["player"]],
                        "via": [round(a["end_x"], 1), round(a["end_y"], 1), a["receiver"]],
                        "to": [round(b["end_x"], 1), round(b["end_y"], 1), a["player"]],
                    },
                }
            )
    return out


__all__ = [
    "LONG_BALL_M",
    "ONE_TWO_S",
    "TEAMS",
    "channels",
    "counters",
    "crosses",
    "keeper",
    "one_twos",
    "passes",
    "width",
]
