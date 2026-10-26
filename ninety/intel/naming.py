"""Which name a tracked player is given: the whole-pitch tracks matched to the team sheet, one to one.

The tactical camera sees all 22 players, so its tracks (ninety.vision.join's tracked.json) carry the
team's whole shape. Their roles come from it as in ninety/intel/roles.py (docs/GROUNDING.md I6),
with three changes that each make a wrong name less likely, measured in docs/eval/roles.md:

1. **Every frame counts.** roles.assign skips a frame where the tracker holds more than eleven
   tracks of a team (a duplicate or a misread kit); here the eleven roles are matched to the
   tracks instead, so each role is still given one track and the extra ones get no vote.
2. **One slot, one track, in each window.** Within each window of WINDOW_S seconds of a segment,
   the team's tracks are matched one to one to the team sheet's eleven slots (the Hungarian
   method), a track's gain for a slot being its net votes for it there (frames that voted for it
   minus frames that did not). An empty slot gains nothing, so a track takes a slot only when most
   of its frames in the window voted for it, and two tracks never share one: a fragment that
   another track beats to its slot stays unnamed instead of taking a near one.
3. **A segment whose sides are in doubt names nobody.** Each team defends one goal all match
   (Law 1; our engine does not change ends, ninety/intel/scene.py), so its keeper, its deepest
   player, stands in its own penalty area, within 16.5 m of its goal line (Law 1), for most of
   the play. A segment in which either team's deepest player is further out than that in more
   than half its sampled frames holds tracks on the wrong side (a misread kit, a keeper read as
   the other team), and a wrong side is a wrong name: nobody in it is named.
4. **One man per slot at a time.** Tracks of a segment that won the same slot in different
   windows and overlap in time cannot all be him: of each slot's tracks, the set that never
   overlap and together won the most frames keeps the slot (weighted interval scheduling); the
   others are left unnamed (roles.one_track_per_name unnamed all of them).
5. **Names cross the camera join.** The events come from the broadcast, whose tracks are other
   ids (ninety.vision.join pairs them). A broadcast track is given the name of its tactical track
   only when the association is at least the measured gate and both cameras read the same side.

A track's `share` is the share of its sampled frames that voted for the slot it was matched to.
A name is said only at or above the measured share and length gates (naming_calibration.json);
with no calibration nothing is named, and every unnamed player is said by club ("a London
Athletic player"), never by track id. Nothing here reads ground truth.
"""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path

from ninety.intel import roles, scene
from ninety.intel.scene import depth
from ninety.intel.teamsheet import LABEL, LINE, ROLES, Fixture
from ninety.vision import match_join

FPS = scene.FPS
WINDOW_S = 10.0  # design: a window short enough that a player's two fragments rarely fall in one
PER_SEGMENT = match_join.PER_SEGMENT  # a joined match's track ids per segment
PENALTY_AREA_M = 16.5  # Law 1: the penalty area reaches 16.5 m from the goal line
TRACK = re.compile(r"^([ha])-t(\d+)$")
CALIBRATION = Path(__file__).resolve().parent / "naming_calibration.json"


def segment(track: str) -> int:
    """The segment of a joined match a track id belongs to (0 for a single clip)."""
    m = TRACK.match(track)
    return int(m.group(2)) // PER_SEGMENT if m else 0


def votes(frames: Sequence[Mapping], team: str, refs: Mapping[str, tuple[float, float]]):
    """Per sampled frame of `team`: (frame, t, {track: role voted}). Up to eleven tracks are matched
    to the roles; with more, the roles are matched to the tracks and the extras get no vote."""
    out = []
    for f in frames:
        if int(f["frame"]) % roles.STEP_FRAMES:
            continue
        own = [p for p in f["players"] if p["team"] == team]
        if len(own) < 2:
            continue
        pts = roles._centred([roles._team_frame(team, p) for p in own])
        cost = [[(x - refs[r][0]) ** 2 + (y - refs[r][1]) ** 2 for r in ROLES] for x, y in pts]
        if len(own) <= len(ROLES):
            got = {own[k]["id"]: ROLES[c] for k, c in enumerate(roles.hungarian(cost))}
        else:
            t_cost = [[cost[k][j] for k in range(len(own))] for j in range(len(ROLES))]
            got = {own[k]["id"]: ROLES[j] for j, k in enumerate(roles.hungarian(t_cost))}
        out.append((int(f["frame"]), float(f["t"]), got))
    return out


def match_windows(voted, window_s: float = WINDOW_S) -> dict[str, Counter]:
    """For each track, how many of its sampled frames fall in windows where it won each slot."""
    windows: dict[tuple[int, int], list] = defaultdict(list)
    for _frame, t, got in voted:
        for track, role in got.items():
            windows[(segment(track), int(t // window_s))].append((track, role))
    won: dict[str, Counter] = defaultdict(Counter)
    for pairs in windows.values():
        seen, by = Counter(), defaultdict(Counter)
        for track, role in pairs:
            seen[track] += 1
            by[track][role] += 1
        tracks = sorted(seen)
        # gain = net votes; the eleven dummy slots after the roles gain 0 (cost 0)
        cost = [[-(2 * by[tr][r] - seen[tr]) for r in ROLES] + [0.0] * len(tracks) for tr in tracks]
        for k, col in enumerate(roles.hungarian(cost)):
            if col < len(ROLES) and 2 * by[tracks[k]][ROLES[col]] > seen[tracks[k]]:
                won[tracks[k]][ROLES[col]] += seen[tracks[k]]
    return won


def assign(frames: Sequence[Mapping], team: str, window_s: float = WINDOW_S) -> dict[str, dict]:
    """Each track of `team`: the slot it won for most of its frames, its share (frames that voted
    for that slot over all its sampled frames), and how long it was seen in seconds."""
    refs = roles.places(frames, team)
    voted = votes(frames, team, refs)
    seen, agree = Counter(), defaultdict(Counter)
    for _, _, got in voted:
        for track, role in got.items():
            agree[track][role] += 1
    for f in frames:
        if int(f["frame"]) % roles.STEP_FRAMES == 0:
            for p in f["players"]:
                if p["team"] == team:
                    seen[p["id"]] += 1
    out = {}
    for track, w in match_windows(voted, window_s).items():
        role, n = max(w.items(), key=lambda kv: (kv[1], -ROLES.index(kv[0])))
        if 2 * n <= seen[track]:
            continue  # it won no slot for most of its frames
        out[track] = {
            "role": role,
            "share": round(agree[track][role] / seen[track], 3),
            "seconds": round(seen[track] * roles.STEP_FRAMES / FPS, 1),
        }
    return out


def keep_apart(claims: Sequence[tuple[str, float, float, int]]) -> set[str]:
    """Of tracks (id, start, end, weight) claiming one slot, the set that never overlap in time and
    has the greatest total weight (weighted interval scheduling; on a tie, the set found first in
    order of end time is kept)."""
    items = sorted(claims, key=lambda c: (c[2], c[1], c[0]))
    best: list[tuple[int, list[str]]] = [(0, [])]
    ends = [c[2] for c in items]
    for i, (track, t0, _t1, w) in enumerate(items):
        lo, hi = 0, i  # items[:j] end before this one starts
        while lo < hi:
            mid = (lo + hi) // 2
            if ends[mid] < t0:
                lo = mid + 1
            else:
                hi = mid
        j = lo
        take = (best[j][0] + w, [*best[j][1], track])
        best.append(take if take[0] > best[i][0] else best[i])
    return set(best[-1][1])


def side_doubt(frames: Sequence[Mapping]) -> set[int]:
    """The segments in which a team's deepest player is outside its own penalty area in more than
    half the sampled frames: their sides are in doubt."""
    deepest: dict[tuple[int, str], list[float]] = defaultdict(list)
    for f in frames:
        if int(f["frame"]) % roles.STEP_FRAMES:
            continue
        for team in ("home", "away"):
            own = [p for p in f["players"] if p["team"] == team]
            if own:
                deepest[(segment(own[0]["id"]), team)].append(min(depth(team, p["x"]) for p in own))
    return {k for (k, _), d in deepest.items() if 2 * sum(x > PENALTY_AREA_M for x in d) > len(d)}


def gates(path: Path = CALIBRATION) -> dict:
    """The measured gates (docs/eval/roles.md): the least share and seconds at which a tactical
    track is named, and the least association confidence that carries its name to a broadcast
    track. None where no setting met its target: then nothing is named."""
    try:
        body = json.loads(path.read_text())
    except FileNotFoundError:
        return {"share": None, "seconds": None, "association": None}
    return {k: body.get(k) for k in ("share", "seconds", "association")}


def _blank(track: str, team: str, club: str | None) -> dict:
    return {"track": track, "team": team, "club": club, "role": None, "share": None, "name": None,
            "number": None, "position": None, "line": None, "sheet_name": None}


def people(
    frames: Sequence[Mapping], fixture: Fixture | None, gate: Mapping, window_s: float = WINDOW_S,
    assigned: Mapping[str, Mapping] | None = None,
) -> dict[str, dict]:
    """Every tactical track: what a fan may be told it is (roles.who's record), a name only past
    both gates, a role and a line with it; one name per player at a time (roles.one_track_per_name)."""
    out: dict[str, dict] = {}
    spans: dict[str, tuple[float, float]] = {}
    for f in frames:
        for p in f["players"]:
            t0, t1 = spans.get(p["id"], (f["t"], f["t"]))
            spans[p["id"]] = (min(t0, f["t"]), max(t1, f["t"]))
    doubt = side_doubt(frames)
    for team in ("home", "away"):
        club = fixture.clubs[team] if fixture else None
        sheet = {s.role: s for s in fixture.sheet(team)} if fixture else {}
        got = assigned[team] if assigned is not None else assign(frames, team, window_s)
        for track in sorted({p["id"] for f in frames for p in f["players"] if p["team"] == team}):
            w = _blank(track, team, club)
            r = got.get(track)
            if r is not None:
                w.update(role=r["role"], share=r["share"])
                starter = sheet.get(r["role"])
                if starter:
                    w["sheet_name"] = starter.name
                ok = (segment(track) not in doubt
                      and gate.get("share") is not None and gate.get("seconds") is not None
                      and r["share"] >= gate["share"] and r["seconds"] >= gate["seconds"])
                if ok and starter:
                    w.update(name=starter.name, number=starter.number, position=LABEL[r["role"]],
                             line=LINE[r["role"]])
            w["say"] = roles.say(w)
            out[track] = w
        claims: dict[tuple[int, str], list] = defaultdict(list)
        for track, w in out.items():
            if w["team"] == team and w["name"]:
                claims[(segment(track), w["role"])].append(
                    (track, *spans[track], got[track]["share"] * got[track]["seconds"]))  # frames for it
        for group in claims.values():
            keep = keep_apart(group)
            for track, *_ in group:
                if track not in keep:
                    out[track].update(name=None, number=None, position=None, line=None)
                    out[track]["say"] = roles.say(out[track])
    return roles.one_track_per_name(out, spans)


def broadcast_people(
    association: Mapping[str, Mapping], tactical: Mapping[str, Mapping], fixture: Fixture | None,
    gate: Mapping,
) -> dict[str, dict]:
    """Every broadcast track of the join: its tactical track's record when the association is at
    least the gate and both cameras read the same side, else only its club (by its own side)."""
    out = {}
    for track, a in association.items():
        team = "home" if track.startswith("h") else "away"
        w = _blank(track, team, fixture.clubs[team] if fixture else None)
        tv = tactical.get(a.get("track") or "")
        g = gate.get("association")
        if tv and g is not None and a.get("confidence", 0) >= g and tv["team"] == team:
            w.update({k: tv[k] for k in ("role", "share", "name", "number", "position", "line",
                                         "sheet_name")})
            w["via"] = tv["track"]
        w["say"] = roles.say(w)
        out[track] = w
    return out


PEOPLE = ("player", "receiver", "intended", "interceptor", "deflected_by")  # ninety/e2e.PEOPLE


def tactical(association: Mapping[str, Mapping], gate: Mapping) -> dict[str, str]:
    """Broadcast track -> its tactical track, where the association is at least the gate (only a
    pairing every paired frame agreed on, confidence 1.0, when no gate was measured) and both
    cameras read the same side."""
    g = gate.get("association")
    out = {}
    for track, a in association.items():
        tv = a.get("track")
        if tv and a.get("confidence", 0) >= (g if g is not None else 1.0) and tv[0] == track[0]:
            out[track] = tv
    return out


def tactical_events(events: Sequence[Mapping], association: Mapping[str, Mapping], gate: Mapping):
    """The events with every person they name moved to his tactical track, or to None where the
    join gives none: an event's broadcast id names another man among the tactical tracks."""
    to = tactical(association, gate)
    return [{**e, **{k: to.get(e[k]) for k in PEOPLE if e.get(k)}} for e in events]


def lineup(broadcast: Mapping[str, Mapping]) -> list[dict]:
    """The bundle's line-up rows (ninety/e2e.read_lineup): each broadcast track (the ids events
    name) a name passed both gates; `confident` is always true, since nothing else is listed."""
    return [
        {"id": t, "name": w["name"], "number": w["number"], "position": w["position"],
         "confident": True}
        for t, w in sorted(broadcast.items()) if w.get("name")
    ]


__all__ = ["CALIBRATION", "PEOPLE", "WINDOW_S", "assign", "broadcast_people", "gates", "keep_apart", "lineup",
           "match_windows", "people", "segment", "side_doubt", "tactical", "tactical_events", "votes"]
