"""Which position each tracked player plays, from where he stands in his team's shape.

The tracker reads no shirt numbers, so a track (h-t12) has no name. Its position does follow from
the team's shape: a left-back stands deep and to the left of his team-mates, a striker furthest
forward and central. This is formation role assignment as Bialkowski et al. do it on tracking
data (docs/GROUNDING.md I6): in every sampled frame each tracked player of the team, placed
relative to the team's centre, is assigned to one role of the formation by the assignment of least
total squared distance (the Hungarian method), and each role's reference place is then moved to
the mean of the places assigned to it; a few rounds of the two. The starting places are the
team sheet's 4-3-3 drawn as a coach's diagram (*design*).

A track's role is the one it was assigned most often, and its `share` is how often: a track
assigned left-back in 90% of its frames is surer than one at 50%. The share is a score, not a
probability; what it is worth is measured on simulated matches with fragmented, noisy tracks
(ninety/eval/roles_eval.py, docs/eval/roles.md), which sets the shares at which a name, a role
and a line may be said (ninety/intel/roles_calibration.json). With no calibration nothing is named.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path

from ninety.intel.scene import PITCH_Y, depth
from ninety.intel.teamsheet import LABEL, LINE, ROLES, Fixture

# The 4-3-3 as a coach draws it, for a team attacking toward x = 105, in metres: depth from its own
# goal line and distance across from its right touchline (*design*, a starting point that the
# rounds then fit to the team's own shape).
TEMPLATE = {
    "GK": (5.0, 34.0),
    "RB": (28.0, 8.0),
    "RCB": (20.0, 24.0),
    "LCB": (20.0, 44.0),
    "LB": (28.0, 60.0),
    "RCM": (44.0, 20.0),
    "CM": (38.0, 34.0),
    "LCM": (44.0, 48.0),
    "RW": (64.0, 8.0),
    "ST": (68.0, 34.0),
    "LW": (64.0, 60.0),
}
ROUNDS = (
    3  # design: the reference places settle within a few rounds (Bialkowski et al. iterate to convergence)
)
STEP_FRAMES = 5  # design: a sampled frame every 0.2 s, as the overloads (ninety/intel/overloads.py)
MIN_FRAMES = 25  # design: a track seen in under 5 s of sampled frames (25 at 0.2 s) is given no role
# In the package, not docs/: the image copies ninety/ only (Dockerfile; docs/LESSONS.md, lesson 100).
CALIBRATION = Path(__file__).resolve().parent / "roles_calibration.json"


def hungarian(cost: Sequence[Sequence[float]]) -> list[int]:
    """For an n x m cost matrix with n <= m, the column assigned to each row, minimising the total
    (Kuhn-Munkres with potentials, O(n^2 m))."""
    n, m = len(cost), len(cost[0]) if cost else 0
    if n > m:
        raise ValueError("more rows than columns")
    inf = float("inf")
    u, v = [0.0] * (n + 1), [0.0] * (m + 1)
    p, way = [0] * (m + 1), [0] * (m + 1)
    for i in range(1, n + 1):
        p[0], j0 = i, 0
        minv, used = [inf] * (m + 1), [False] * (m + 1)
        while True:
            used[j0] = True
            i0, delta, j1 = p[j0], inf, 0
            for j in range(1, m + 1):
                if not used[j]:
                    cur = cost[i0 - 1][j - 1] - u[i0] - v[j]
                    if cur < minv[j]:
                        minv[j], way[j] = cur, j0
                    if minv[j] < delta:
                        delta, j1 = minv[j], j
            for j in range(m + 1):
                if used[j]:
                    u[p[j]] += delta
                    v[j] -= delta
                else:
                    minv[j] -= delta
            j0 = j1
            if p[j0] == 0:
                break
        while j0:
            j1 = way[j0]
            p[j0] = p[j1]
            j0 = j1
    out = [0] * n
    for j in range(1, m + 1):
        if p[j]:
            out[p[j] - 1] = j - 1
    return out


def _team_frame(team: str, p: Mapping) -> tuple[float, float]:
    """(depth, distance across from the team's right touchline) for a team attacking either way."""
    across = float(p["y"]) if team == "home" else PITCH_Y - float(p["y"])
    return depth(team, p["x"]), across


def _centred(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    cx = sum(x for x, _ in points) / len(points)
    cy = sum(y for _, y in points) / len(points)
    return [(x - cx, y - cy) for x, y in points]


def assign(frames: Sequence[Mapping], team: str) -> dict[str, dict]:
    """Each track of `team` seen in at least MIN_FRAMES sampled frames: its role, its share, and
    in how many sampled frames it was seen."""
    sampled = [f for f in frames if int(f["frame"]) % STEP_FRAMES == 0] or list(frames)
    rows = []
    for f in sampled:
        own = [p for p in f["players"] if p["team"] == team]
        if 2 <= len(own) <= len(ROLES):
            rows.append(([p["id"] for p in own], _centred([_team_frame(team, p) for p in own])))
    refs = dict(zip(ROLES, _centred([TEMPLATE[r] for r in ROLES]), strict=True))
    votes: dict[str, Counter] = defaultdict(Counter)
    for rnd in range(ROUNDS + 1):
        sums: dict[str, list[float]] = {r: [0.0, 0.0, 0.0] for r in ROLES}
        last = rnd == ROUNDS
        for ids, pts in rows:
            cost = [[(x - refs[r][0]) ** 2 + (y - refs[r][1]) ** 2 for r in ROLES] for x, y in pts]
            for k, col in enumerate(hungarian(cost)):
                role = ROLES[col]
                s = sums[role]
                s[0] += pts[k][0]
                s[1] += pts[k][1]
                s[2] += 1
                if last:
                    votes[ids[k]][role] += 1
        if not last:
            refs = {r: (s[0] / s[2], s[1] / s[2]) if s[2] else refs[r] for r, s in sums.items()}
    out = {}
    for track, c in votes.items():
        seen = sum(c.values())
        if seen < MIN_FRAMES:
            continue
        role, n = max(c.items(), key=lambda kv: (kv[1], -ROLES.index(kv[0])))
        out[track] = {"role": role, "share": round(n / seen, 3), "frames": seen}
    return out


def gates(path: Path = CALIBRATION) -> dict[str, float | None]:
    """The least share at which a name, a role and a line may be said, as measured
    (docs/eval/roles.md); None where no share reached its target, which never says it."""
    try:
        body = json.loads(path.read_text())
    except FileNotFoundError:
        return {"name": None, "role": None, "line": None}
    return {k: body.get(k) for k in ("name", "role", "line")}


def who(
    track: str,
    team: str,
    roles: Mapping[str, Mapping],
    fixture: Fixture | None,
    gate: Mapping[str, float | None],
) -> dict:
    """What a fan may be told a track is: a name, the club's position, its line, or just the club,
    each only at or above its measured share."""
    club = fixture.clubs[team] if fixture else None
    r = roles.get(track)
    out = {
        "track": track,
        "team": team,
        "club": club,
        "role": None,
        "share": None,
        "name": None,
        "number": None,
        "position": None,
        "line": None,
        "sheet_name": None,
    }
    if r is not None:
        out.update(role=r["role"], share=r["share"])
        starter = next(s for s in fixture.sheet(team) if s.role == r["role"]) if fixture else None

        def ok(k):
            return gate.get(k) is not None and r["share"] >= gate[k]

        if starter:
            out["sheet_name"] = starter.name  # whom the role is on the sheet; said only past the name gate
        if ok("name") and starter:
            out.update(name=starter.name, number=starter.number)
        if ok("role"):
            out["position"] = LABEL[r["role"]]
        if ok("line"):
            out["line"] = LINE[r["role"]]
    out["say"] = say(out)
    return out


def say(w: Mapping) -> str:
    """How a sentence names the player: "Tomas Varick", "Oakfield's left-back", "an Oakfield
    defender", or "an Oakfield player"."""
    club = w.get("club") or "the team"
    if w.get("name"):
        return w["name"]
    if w.get("position"):
        return f"{club}'s {w['position']}"
    article = "an" if club[:1].lower() in "aeiou" else "a"
    if w.get("line") == "goalkeeper":
        return f"{club}'s goalkeeper"
    if w.get("line"):
        return f"{article} {club} {w['line']}"
    return f"{article} {club} player"


__all__ = ["CALIBRATION", "TEMPLATE", "assign", "gates", "hungarian", "say", "who"]
