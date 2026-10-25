"""Possession share and territory by third, from the video alone (GROUNDING I17, I18). (The phone's
momentum strip, by half and per five minutes, is ninety/match/territory.py.)

Possession share is the pass ratio Opta publishes as possession: a team's passes over both teams' passes, as
Opta counts possession (I17), not time on the ball. A detected pass counts for its team only when
its side was told past the fact-checker's side gate (factcheck.side_known); a pass whose side is not
known could be either team's, so the share is given as bounds, and stated only when they agree (no
pass of the window has an unknown side), as every count here is (I1).

Territory is where the ball was: of the seconds of footage shown (the tracked frames hold the ball
wherever the footage does, gaps within the tracker's own limit filled, ninety/vision/tracked_frames),
the share in each third of the pitch along the direction a team attacks (the thirds of Law 1's
length, as the possession layer cuts them). A ball within the players' position error of a third's
line could be on either side of it, so those seconds are counted apart and give the share bounds,
and the share is said as them ("between 25% and 31% of the footage shown"), like team distance,
"from the footage shown" (I16).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence

from ninety.agents.factcheck import side_known
from ninety.intel.scene import PITCH_X, POSITION_ERROR_M, TEAMS, minute_of

STEP_S = 1.0  # one ball position a second: the tracked frames' own smoothing (team_stats.STEP_S)
THIRD_M = PITCH_X / 3
EDGE_M = POSITION_ERROR_M
THIRDS = ("own", "middle", "final")


def possession_rows(events: Iterable[Mapping]) -> list[dict]:
    """One row per detected pass: its minute, its detected team, and whether that side is known."""
    return [
        {
            "id": f"poss:{e['id']}",
            "kind": "possession_pass",
            "team": e["team"],
            "minute": minute_of(float(e["t"])),
            "side_known": side_known(e),
        }
        for e in events
        if e.get("type") == "pass" and e.get("team") in TEAMS
    ]


def possession(rows: Sequence[Mapping], minute_from: int, minute_to: int) -> dict[str, dict]:
    """Each team's pass share in the window, with bounds from the passes whose side is unknown."""
    window = [r for r in rows if minute_from <= r["minute"] <= minute_to]
    unknown = sum(not r["side_known"] for r in window)
    total = len(window)
    out = {}
    for team in TEAMS:
        known = sum(r["side_known"] and r["team"] == team for r in window)
        if not total:
            continue
        lo, hi = known / total, (known + unknown) / total
        out[team] = {
            "id": f"poss:{team}:m{minute_from}-{minute_to}",
            "kind": "possession",
            "metric": "possession_share",
            "team": team,
            "minute_from": minute_from,
            "minute_to": minute_to,
            "value": round(100 * known / (total - unknown)) if total > unknown else None,
            "unit": "%",
            "lo": round(100 * lo),
            "hi": round(100 * hi),
            "confident": unknown == 0,
            "passes": total,
            "also": [[total, "passes"]],
        }
    return out


def _third(x: float, team: str) -> tuple[str, bool]:
    """The third the ball is in along the direction `team` attacks, and whether it is near a line."""
    depth = x if team == "home" else PITCH_X - x  # home attacks toward x = PITCH_X (Fixture)
    k = min(int(depth // THIRD_M), 2)
    near = any(abs(depth - line) <= EDGE_M for line in (THIRD_M, 2 * THIRD_M))
    return THIRDS[k], near


def territory_rows(frames: Sequence[Mapping]) -> list[dict]:
    """One row per team and minute: the seconds sampled, the seconds the ball was seen, and of
    those, the seconds in each third along that team's attack and the seconds near a third's line."""
    step = round(STEP_S * 25)
    by: dict[tuple[str, int], dict] = {}
    for fr in frames:
        if int(fr["frame"]) % step:
            continue
        m = minute_of(float(fr["t"]))
        ball = fr.get("ball")
        for team in TEAMS:
            r = by.setdefault(
                (team, m),
                {"id": f"terr:{team}:m{m}", "kind": "territory_minute", "team": team, "minute": m,
                 "seconds": 0, "seen": 0, "near_line": 0, **{t: 0 for t in THIRDS}},
            )
            r["seconds"] += 1
            if not ball or ball.get("x") is None:
                continue
            if not 0.0 <= float(ball["x"]) <= PITCH_X:
                continue  # beyond a goal line: out of play, in no third (merge-queue review of #314)
            third, near = _third(float(ball["x"]), team)
            r["seen"] += 1
            if near:
                r["near_line"] += 1
            else:
                r[third] += 1
    return list(by.values())


def territory(rows: Sequence[Mapping], minute_from: int, minute_to: int) -> dict[str, dict]:
    """Each team's share of the seen seconds with the ball in its attacking (final) third."""
    out = {}
    for team in TEAMS:
        window = [r for r in rows if r["team"] == team and minute_from <= r["minute"] <= minute_to]
        seen = sum(r["seen"] for r in window)
        if not seen:
            continue
        near = sum(r["near_line"] for r in window)
        final = sum(r["final"] for r in window)
        out[team] = {
            "id": f"terr:{team}:m{minute_from}-{minute_to}",
            "kind": "territory",
            "metric": "final_third_share",
            "team": team,
            "minute_from": minute_from,
            "minute_to": minute_to,
            # The share is said as its bounds: the seconds near a line may be on either side of it.
            "value": round(100 * final / seen),
            "unit": "%",
            "lo": round(100 * final / seen),
            "hi": round(100 * (final + near) / seen),
            "also": [[round(100 * (final + near) / seen), "%"]],
            "seconds": seen,
            "confident": True,
            "shares": {t: round(100 * sum(r[t] for r in window) / seen) for t in THIRDS},
        }
    return out


__all__ = ["THIRDS", "possession", "possession_rows", "territory", "territory_rows"]
