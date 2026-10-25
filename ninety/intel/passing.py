"""What the detected passes did (GROUNDING I20, I21): progressive passes, entries into the final third,
long balls and interceptions, per club and in all; and the pass network, who passed to whom.

Each is arithmetic on a detected pass's start and end (ninety/vision/events.py):
- **progressive** (a published definition, I20, in our own words): a completed pass that ends at
  least 30 m closer to the opponents' goal when it starts and ends in the team's own half, 15 m when
  it crosses halfway, and 10 m when it starts and ends in the opponents' half;
- **into the final third**: a completed pass that starts outside the third of the pitch nearest the
  opponents' goal and ends inside it (a published definition too, I20);
- **long**: a pass of 32 m or more, the 35 yards of Opta's long ball (I11), for every passer;
- **intercepted**: a pass the other side's player took (the detector names him when unambiguous).

Which goal a team attacks follows from its side, so a pass counts for its club only when its side
passed the fact-checker's side gate (factcheck.side_known); the others could be either club's, so a
club's count has bounds, and the totals of both clubs do not need the side.

The pass network counts completed passes between two named players (the role gate names them, I6;
one player's pieces of track are one name, lesson 241); passes whose passer or receiver is not named
are left out, so it is the network of the passes the video could put names to, never all of them.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Iterable, Mapping

from ninety.agents.factcheck import side_known
from ninety.intel.scene import PITCH_X, PITCH_Y, TEAMS, minute_of
from ninety.intel.style import LONG_BALL_M

KINDS = ("progressive", "final_third_entry", "long", "intercepted")
UNIT = {
    "progressive": "progressive passes",
    "final_third_entry": "passes",
    "long": "long passes",
    "intercepted": "passes",
}
# The published progressive pass (GROUNDING I20): metres closer to the opponents' goal, by where it
# starts and ends.
PROGRESSIVE_M = {"own": 30.0, "across": 15.0, "theirs": 10.0}


def _to_goal(x: float, y: float, team: str) -> float:
    gx = PITCH_X if team == "home" else 0.0  # home attacks toward x = PITCH_X
    return math.hypot(gx - x, PITCH_Y / 2 - y)


def _depth(x: float, team: str) -> float:
    """Metres along the pitch from the team's own goal line."""
    return x if team == "home" else PITCH_X - x


def progressive(x: float, y: float, ex: float, ey: float, team: str) -> bool:
    a, b = _depth(x, team) >= PITCH_X / 2, _depth(ex, team) >= PITCH_X / 2
    need = PROGRESSIVE_M["theirs" if a and b else "own" if not a and not b else "across"]
    return _to_goal(x, y, team) - _to_goal(ex, ey, team) >= need


def into_final_third(x: float, ex: float, team: str) -> bool:
    line = 2 * PITCH_X / 3
    return _depth(x, team) < line <= _depth(ex, team)


def rows(events: Iterable[Mapping]) -> list[dict]:
    """One row per detected pass with an end: what it did, and whether its side is known."""
    out = []
    for e in events:
        if e.get("type") != "pass" or e.get("end_x") is None or e.get("team") not in TEAMS:
            continue
        x, y, ex, ey, team = float(e["x"]), float(e["y"]), float(e["end_x"]), float(e["end_y"]), e["team"]
        done = e.get("outcome") == "success"
        out.append(
            {
                "id": f"pt:{e['id']}",
                "kind": "pass_type",
                "team": team,
                "minute": minute_of(float(e["t"])),
                "side_known": side_known(e),
                "progressive": done and progressive(x, y, ex, ey, team),
                "final_third_entry": done and into_final_third(x, ex, team),
                "long": math.hypot(ex - x, ey - y) >= LONG_BALL_M,
                "intercepted": e.get("outcome") == "fail" and e.get("interceptor") is not None,
                "passer": e.get("player"),
                "receiver": e.get("receiver") if done else None,
            }
        )
    return out


def summary(passes: Iterable[Mapping], minute_from: int, minute_to: int) -> list[dict]:
    """For each kind: each club's count with bounds from the passes of unknown side, and the total."""
    window = [r for r in passes if minute_from <= r["minute"] <= minute_to]
    out = []
    for kind in KINDS:
        hit = [r for r in window if r[kind]]
        unknown = sum(not r["side_known"] for r in hit)
        out.append(
            {
                "id": f"pt:{kind}:all:m{minute_from}-{minute_to}",
                "kind": "pass_types",
                "metric": f"{kind}_all",
                "team": None,
                "minute_from": minute_from,
                "minute_to": minute_to,
                "value": len(hit),
                "unit": UNIT[kind],
                "confident": True,
            }
        )
        for team in TEAMS:
            # An interception is the other club's: the passer lost it.
            mine = [r for r in hit if r["side_known"] and r["team"] == team]
            out.append(
                {
                    "id": f"pt:{kind}:{team}:m{minute_from}-{minute_to}",
                    "kind": "pass_types",
                    "metric": kind,
                    "team": team,
                    "minute_from": minute_from,
                    "minute_to": minute_to,
                    "value": len(mine),
                    "unit": UNIT[kind],
                    "lo": len(mine),
                    "hi": len(mine) + unknown,
                    "confident": unknown == 0,
                }
            )
    return out


def network(
    passes: Iterable[Mapping], people: Mapping[str, Mapping], minute_from: int, minute_to: int, top: int = 5
) -> list[dict]:
    """The pairs of named players with the most completed passes between them, passer to receiver."""
    count: Counter = Counter()
    tracks: dict[tuple, tuple[str, str]] = {}
    for r in passes:
        if not (minute_from <= r["minute"] <= minute_to) or not r.get("receiver"):
            continue
        a, b = people.get(r["passer"], {}), people.get(r["receiver"], {})
        if a.get("name") and b.get("name") and a["name"] != b["name"] and a.get("team") == b.get("team"):
            key = (a["team"], a["name"], b["name"])
            count[key] += 1
            tracks.setdefault(key, (r["passer"], r["receiver"]))  # one of each player's tracks
    out = []
    for (team, a, b), n in sorted(count.items(), key=lambda kv: (-kv[1], kv[0]))[:top]:
        out.append(
            {
                "id": f"net:{team}:{a}>{b}:m{minute_from}-{minute_to}".replace(" ", "_"),
                "kind": "pass_pair",
                "metric": "pair_passes",
                "team": team,
                "minute_from": minute_from,
                "minute_to": minute_to,
                "passer": tracks[(team, a, b)][0],
                "receiver": tracks[(team, a, b)][1],
                "passer_is": a,
                "receiver_is": b,
                "value": n,
                "unit": "times",
                "confident": True,
            }
        )
    return out


__all__ = ["KINDS", "PROGRESSIVE_M", "into_final_third", "network", "progressive", "rows", "summary"]
