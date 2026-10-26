"""Set-piece counts (GROUNDING I25), from vision's detected restarts (ninety/vision/restarts.py, #325):
corners, goal kicks, penalties, throw-ins and free kicks, per club and in all; nothing until they
exist.

Which club took a restart is told by the Laws where they decide it, from the end the ball lies at
(each club attacks one end all match, home toward x = PITCH_X): a corner (Law 17) and a penalty kick
(Law 14) are the attacking club's at that end, a goal kick (Law 16) the defending club's. A throw-in
(Law 15) or a free kick (Law 13) can be either club's anywhere, so it counts for its detected side
only past the fact-checker's side gate (factcheck.side_known), and a club's count has bounds.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from ninety.agents.factcheck import side_known
from ninety.intel.scene import PITCH_X, TEAMS, minute_of

KINDS = ("corner", "goal_kick", "penalty_kick", "throw_in", "free_kick")
# What a fan calls each, singular and plural, and its unit in the sentences.
WORDS = {
    "corner": ("corner", "corners"),
    "goal_kick": ("goal kick", "goal kicks"),
    "penalty_kick": ("penalty", "penalties"),
    "throw_in": ("throw-in", "throw-ins"),
    "free_kick": ("free kick", "free kicks"),
}
OTHER = {"home": "away", "away": "home"}


def _attacking(x: float) -> str:
    return "home" if x > PITCH_X / 2 else "away"


def rows(events: Iterable[Mapping]) -> list[dict]:
    """One row per detected restart: its kind, the club that took it, and whether that is known."""
    out = []
    for e in events:
        kind = e.get("restart")
        if e.get("type") != "set_piece" or kind not in KINDS:
            continue
        if kind in ("corner", "penalty_kick") and e.get("x") is not None:
            team, known = _attacking(float(e["x"])), True  # Laws 17, 14: the club attacking that end
        elif kind == "goal_kick" and e.get("x") is not None:
            team, known = OTHER[_attacking(float(e["x"]))], True  # Law 16: the defending club
        else:
            team, known = e.get("team"), e.get("team") in TEAMS and side_known(e)
        out.append(
            {
                "id": f"sp:{e['id']}",
                "kind": "restart",
                "restart": kind,
                "team": team if team in TEAMS else "home",  # a placeholder when unknown: never counted
                "minute": minute_of(float(e["t"])),
                "t": round(float(e["t"]), 2),
                "side_known": bool(known),
            }
        )
    return out


def summary(restarts: Iterable[Mapping], minute_from: int, minute_to: int) -> list[dict]:
    """For each kind: the total, and each club's count with bounds from those of unknown side."""
    window = [r for r in restarts if minute_from <= r["minute"] <= minute_to]
    out = []
    for kind in KINDS:
        hit = [r for r in window if r["restart"] == kind]
        unknown = sum(not r["side_known"] for r in hit)
        unit = WORDS[kind][1]
        out.append({"id": f"sp:{kind}:all:m{minute_from}-{minute_to}", "kind": "set_pieces",
                    "metric": f"{kind}_all", "restart": kind, "team": None, "minute_from": minute_from,
                    "minute_to": minute_to, "value": len(hit), "unit": unit, "confident": True})
        for team in TEAMS:
            n = sum(r["side_known"] and r["team"] == team for r in hit)
            out.append({"id": f"sp:{kind}:{team}:m{minute_from}-{minute_to}", "kind": "set_pieces",
                        "metric": kind, "restart": kind, "team": team, "minute_from": minute_from,
                        "minute_to": minute_to, "value": n, "unit": unit, "lo": n, "hi": n + unknown,
                        "confident": unknown == 0})
    return out


__all__ = ["KINDS", "WORDS", "rows", "summary"]
