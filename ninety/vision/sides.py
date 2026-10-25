"""A track's side from its kit and where it stands, combined (variant S of
docs/eval/sides-tactical/SPATIAL-PLAN.md, adopted by its pre-registered rule).

After `track.assign_teams` has found the two kits and named them (home defends x = 0, the engine's
convention), each outfield track has three pieces of evidence that it is home, read from the
observations only:

- **kit:** how much nearer its median kit is to the home kit than to the away kit, -1 to 1;
- **depth:** how much deeper toward x = 0 it stands than the mean of every tracked outfield player in
  the same frames, as a share of half the pitch (a team stands nearer its own goal, in and out of
  possession: GROUNDING T2, O6);
- **kick-off:** in frames where the ball sits on the centre spot (Law 8: everyone in his own half),
  the share of its frames in the home half minus the share in the other; 0 when none is seen.

`P(home) = logistic(w0 + w1 kit + w2 depth + w3 kickoff)`, the weights fitted on validation tracks
(ninety/eval/sides_spatial.py). The side is home when P >= 0.5, and `side_confidence` is max(P, 1 - P):
on validation (leave one clip out) that confidence was within 0.037 of the accuracy it claims,
frame-weighted over the plan's bins. Keepers keep `assign_teams`' side (the half they stand in).

Not handled: a change of ends. The depth and kick-off evidence, like `assign_teams`' naming, take
home to defend x = 0 for the whole clip, as our engine plays it (it never changes ends). The Laws
have the teams change ends for the second half (Law 8): a clip spanning half-time would name its
second half backwards, and would have to be split there and the second half's naming turned round.
"""

from __future__ import annotations

import math

from ninety.vision import track as tr

CENTRE = (52.5, 34.0)
HALF_X = 52.5
KICKOFF_M = 1.0  # the ball within the strict radius of the spot (event_score.STRICT_M)
KICKOFF_FRAMES = 3  # running, as the out-of-play count (events.OUT_FRAMES)
# Fitted on tactical1's 23 validation clips (docs/eval/sides-tactical/S-validation.json,
# `weights_all`): intercept, kit, depth, kick-off.
WEIGHTS = (-0.1263, 1.497, 2.2492, 1.4687)


def kickoff_frames(rows: list[dict]) -> set[int]:
    """Frames inside a run of KICKOFF_FRAMES or more consecutive frames with the ball within
    KICKOFF_M of the centre spot."""
    out, run = set(), []
    for p in tr.ball_path(rows):
        on = math.dist((p.x, p.y), CENTRE) <= KICKOFF_M
        if on and run and p.frame == run[-1] + 1:
            run.append(p.frame)
            continue
        if len(run) >= KICKOFF_FRAMES:
            out |= set(run)
        run = [p.frame] if on else []
    if len(run) >= KICKOFF_FRAMES:
        out |= set(run)
    return out


def features(tracks: list[tr.Track], info: dict, rows: list[dict]) -> dict[int, list[float]]:
    """{track id: [kit, depth, kickoff]} for every outfield track `assign_teams` gave a side."""
    if not info.get("kits"):
        return {}
    feature = info["feature"]
    home, away = tuple(info["kits"]["home"]), tuple(info["kits"]["away"])
    outfield = [t for t in tracks if not t.keeper and t.team is not None]
    xs: dict[int, list[float]] = {}
    for t in outfield:
        for f, (x, _) in zip(t.frames, t.xy, strict=True):
            xs.setdefault(f, []).append(x)
    centre_x = {f: sum(v) / len(v) for f, v in xs.items()}
    ko = kickoff_frames(rows)
    out = {}
    for t in outfield:
        c = tr.kit(t, feature)
        if c is None:
            continue
        dh, da = tr._dist(c, home), tr._dist(c, away)
        kit = (da - dh) / (da + dh) if da + dh else 0.0
        seen = list(zip(t.frames, t.xy, strict=True))
        depth = -sum(x - centre_x[f] for f, (x, _) in seen) / (len(seen) * HALF_X)
        at_ko = [x for f, (x, _) in seen if f in ko]
        kick = ((sum(x < HALF_X for x in at_ko) - sum(x >= HALF_X for x in at_ko)) / len(at_ko)
                if at_ko else 0.0)
        out[t.id] = [kit, depth, kick]
    return out


def whole_pitch(rows: list[dict]) -> bool:
    """Whether the observations are the tactical views merged (ninety/vision/fuse.py names each box's
    view): the only input S was fitted and measured on. The broadcast keeps `assign_teams`' sides."""
    return any("views" in d or "view" in d for r in rows for d in r["players"])


def assign(tracks: list[tr.Track], rows: list[dict]) -> dict:
    """Every live stage's sides (events, the radar's tracked frames, restarts): `assign_teams`, then
    on the tactical views S on top. One function, so no two stages can name a track differently."""
    teams = tr.assign_teams(tracks)
    if whole_pitch(rows):
        teams["spatial_changed"] = apply(tracks, teams, rows)
    return teams


def p_home(x: list[float], weights=WEIGHTS) -> float:
    z = weights[0] + sum(w * v for w, v in zip(weights[1:], x, strict=True))
    return 1 / (1 + math.exp(-z))


def apply(tracks: list[tr.Track], info: dict, rows: list[dict], weights=WEIGHTS) -> int:
    """Re-side every outfield track with a side by the combined evidence; returns how many changed."""
    changed = 0
    feats = features(tracks, info, rows)
    for t in tracks:
        x = feats.get(t.id)
        if x is None:
            continue
        p = p_home(x, weights)
        team = "home" if p >= 0.5 else "away"
        changed += team != t.team
        t.team, t.side_confidence = team, round(max(p, 1 - p), 3)
    # Law 3 judges the sides S gives too: more than 11 of one side in a frame and none is sure.
    info["law3"] = tr.law3(tracks)
    return changed


def transfers(spells: list, cuts: list[int]) -> list[tuple[int, int]]:
    """(track id, track id) for each time the ball goes from one player's spell to the next player's
    (`events.spells`, consecutive spells of two tracks, no cut between them): mostly completed passes
    (GROUNDING R3: completion 75 to 88%), so evidence the two are team-mates, whatever their kits."""
    out = []
    for a, b in zip(spells, spells[1:], strict=False):
        if a.track is b.track or any(a.last <= c < b.first for c in cuts):
            continue
        out.append((a.track.id, b.track.id))
    return out


def graph_evidence(links: list[tuple[int, int]], p: dict[int, float]) -> dict[int, float]:
    """{track id: the mean over its transfers of 2 p_other - 1}: how home its passing partners are."""
    acc: dict[int, list[float]] = {}
    for a, b in links:
        if b in p:
            acc.setdefault(a, []).append(2 * p[b] - 1)
        if a in p:
            acc.setdefault(b, []).append(2 * p[a] - 1)
    return {k: sum(v) / len(v) for k, v in acc.items()}
