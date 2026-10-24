"""Overloads: where one team has two or more players more than the other.

The pitch is split into nine zones, its thirds along its length by its channels across its width
(docs/GROUNDING.md I3). In each sampled tracked frame each team's players in each zone are counted
with their bounds (ninety/intel/scene.py): a player untracked may be in any zone, and a tracked
player within the position error of a zone's edge may be on either side of it. A team has an
overload in a zone when it has at least OVERLOAD_MIN more players there than the other team; an
overload moment is a run of sampled frames with the same team ahead by that much in the same zone,
lasting at least MIN_S. The moment's fact is its frame with the largest advantage (the first, on a
tie), and it is confident when the advantage holds at the bounds: the team's fewest possible
players there minus the other team's most possible is still OVERLOAD_MIN or more.

Only the zone the ball is in is read in each frame: an overload is a team's advantage where the
play is (*design*, docs/GROUNDING.md I3); a back line outnumbering nobody in its own third while the
ball is up the other end is no overload a fan would be told about.

A zone is named for the team that has the overload: its third along the direction it attacks
(own, middle, final), and its channel as it attacks (left, centre, right). Home attacks toward
x = 105 with y rising to its left, as the engine's formation has its left-back at high y.
"""

from __future__ import annotations

from collections.abc import Mapping

from ninety.intel.insights import fact, in_minutes
from ninety.intel.scene import (
    FPS,
    PITCH_X,
    PITCH_Y,
    TEAMS,
    Count,
    Frames,
    attacks_right,
    count,
    missing,
    other,
    players,
    xy,
)

THIRD_M = PITCH_X / 3  # thirds of the length (Law 1 length; the split in three as S2, docs/GROUNDING.md)
CHANNEL_M = PITCH_Y / 3  # channels: the width split in three (docs/GROUNDING.md I3, *design*)
THIRDS = ("own", "middle", "final")
CHANNELS = ("right", "centre", "left")  # as a team attacking toward x = 105 sees them, by rising y
OVERLOAD_MIN = 2  # the task's definition, "two or more players more" (docs/GROUNDING.md I3)
# Design: a sampled frame every 0.2 s, the phone's minimap step (ninety/intel/possession.STEP_S),
# and a moment lasts at least a second, so a player crossing a zone's edge for a frame is no overload.
STEP_FRAMES = round(0.2 * FPS)
MIN_S = 1.0
# The other side's count is the number written after "against" ("5 players against 2 players"):
# a sentence may state it only there (ninety/agents/insight_check.py `_pairs`).
AGAINST = r"\bagainst\s+$"


def zone_box(i: int, j: int) -> dict:
    return {"x0": i * THIRD_M, "x1": (i + 1) * THIRD_M, "y0": j * CHANNEL_M, "y1": (j + 1) * CHANNEL_M}


def zone_name(team: str, i: int, j: int) -> tuple[str, str]:
    """(third, channel) of absolute zone (i along x, j along y) as `team` attacks."""
    if attacks_right(team):
        return THIRDS[i], CHANNELS[j]
    return THIRDS[2 - i], CHANNELS[2 - j]


def _margin(p: Mapping, box: dict) -> float:
    """Signed distance from the zone's edge: positive inside, negative outside."""
    x, y = float(p["x"]), float(p["y"])
    inside = min(x - box["x0"], box["x1"] - x, y - box["y0"], box["y1"] - y)
    if inside >= 0:
        return inside
    dx = max(box["x0"] - x, 0.0, x - box["x1"])
    dy = max(box["y0"] - y, 0.0, y - box["y1"])
    return -((dx * dx + dy * dy) ** 0.5)


def zone_counts(frame: Mapping, i: int, j: int) -> dict[str, Count]:
    box = zone_box(i, j)
    return {
        team: count([_margin(p, box) for p in players(frame, team)], missing(frame, team)) for team in TEAMS
    }


def advantage(counts: dict[str, Count], team: str) -> Count:
    """How many more players `team` has than the other team, with its bounds (never below 0)."""
    own, opp = counts[team], counts[other(team)]
    return Count(max(0, own.value - opp.value), max(0, own.lo - opp.hi), max(0, own.hi - opp.lo))


def overloads(frames: Frames) -> list[dict]:
    """A fact for every overload moment in the tracked frames."""
    sampled = [f for f in frames.frames if int(f["frame"]) % STEP_FRAMES == 0] or list(frames.frames)
    out: list[dict] = []
    open_runs: dict[tuple, list] = {}

    def close(key, run):
        if not run or (run[-1][0]["t"] - run[0][0]["t"]) < MIN_S:
            return
        team, i, j = key
        peak_frame, peak = max(run, key=lambda r: (r[1].value, -r[0]["t"]))
        counts = zone_counts(peak_frame, i, j)
        third, channel = zone_name(team, i, j)
        box = zone_box(i, j)
        in_box = {t: [xy(p) for p in players(peak_frame, t) if _margin(p, box) > 0] for t in TEAMS}
        out.append(
            fact(
                f"ov:{team}:{third}-{channel}:{int(peak_frame['frame'])}",
                "overload",
                "extra_players",
                team,
                peak_frame["t"],
                peak,
                "extra players",
                peak_frame,
                {
                    "zone": {k: round(v, 2) for k, v in box.items()},
                    "home": in_box["home"],
                    "away": in_box["away"],
                    "for": counts[team].value,  # the "4v2" label: the counts at the moment
                    "against": counts[other(team)].value,
                },
                confident=peak.lo >= OVERLOAD_MIN,
                third=third,
                channel=channel,
                t_from=round(run[0][0]["t"], 2),
                t_to=round(run[-1][0]["t"], 2),
                duration_s=round(run[-1][0]["t"] - run[0][0]["t"], 1),
                own_players=counts[team].value,
                other_players=counts[other(team)].value,
                also=[
                    [counts[team].value, "players"],
                    [counts[other(team)].value, "players", AGAINST],
                    [round(run[-1][0]["t"] - run[0][0]["t"], 1), "s"],
                ],
            )
        )

    for frame in sampled:
        live = set()
        bx, by = float(frame["ball"]["x"]), float(frame["ball"]["y"])
        ball_zone = (min(2, max(0, int(bx // THIRD_M))), min(2, max(0, int(by // CHANNEL_M))))
        for i in range(3):
            for j in range(3):
                if (i, j) != ball_zone:
                    continue
                counts = zone_counts(frame, i, j)
                for team in TEAMS:
                    adv = advantage(counts, team)
                    if adv.value >= OVERLOAD_MIN:
                        key = (team, i, j)
                        live.add(key)
                        open_runs.setdefault(key, []).append((frame, adv))
        for key in [k for k in open_runs if k not in live]:
            close(key, open_runs.pop(key))
    for key, run in open_runs.items():
        close(key, run)
    return sorted(out, key=lambda f: (f["t"], f["id"]))


def team_summary(facts, minute_from: int, minute_to: int) -> list[dict]:
    """Per team, its overload moments over the minutes by zone, counting only confident ones."""
    out = []
    for team in TEAMS:
        rows = [r for r in in_minutes(facts, minute_from, minute_to, team) if r["confident"]]
        zones: dict[str, int] = {}
        for r in rows:
            zones[f"{r['third']}-{r['channel']}"] = zones.get(f"{r['third']}-{r['channel']}", 0) + 1
        top = max(zones, key=lambda z: (zones[z], z), default=None)
        out.append(
            {
                "id": f"ov:{team}:m{minute_from}-{minute_to}",
                "kind": "overload",
                "metric": "overload_moments",
                "team": team,
                "minute_from": minute_from,
                "minute_to": minute_to,
                "value": len(rows),
                "unit": "overloads",
                "lo": len(rows),
                "hi": len(rows),
                "confident": True,
                "by_zone": zones,
                "most": top,
            }
        )
    return out


__all__ = ["MIN_S", "OVERLOAD_MIN", "advantage", "overloads", "team_summary", "zone_counts", "zone_name"]
