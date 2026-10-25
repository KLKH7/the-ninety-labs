"""Automatic restart detection: the ball set still at its spot, then played.

    uv run python -m ninety.vision.restarts <observations.jsonl> --out restarts.jsonl

Reads only the observations file (`ninety.vision.observe`), as `ninety.vision.events` does, and
writes match_event lines with `source: "vision"`. Nothing here reads ground truth: this is the live
path (tests/test_vision_live_path.py watches it run). The rules are the Laws' (docs/GROUNDING.md);
every tolerance is the measured position error, set before any restart was scored
(docs/eval/restarts-vision-plan.md).

**Still.** A restart is taken with the ball stationary on its spot (Laws 8, 13, 15 to 17). A still
spell is a run of ball sightings, none more than KICK_GAP_FRAMES apart and none across a cut of
the broadcast's edit, each within STILL_M of the run's median place, lasting MIN_STILL_S or more.
The restart is taken at its last frame: the next sighting is off the spot, so the ball was kicked
and clearly moved (Law 8). A still spell the clip ends in has not been taken yet: nothing is said.

**Kick-off** (Law 8, GROUNDING L4). The still spell is on the centre mark, within SPOT_M. At its
last frame, with the position error allowed: every player seen is in his own half (home defends
x = 0 in both halves, as the engine plays it, ninety/vision/events.py), and only the kicking side
is inside the centre circle (opponents stay 9.15 m from the ball, Law 8). So the side taking it is
the side of the nearest player inside the circle; nobody of the other side may be that near. The
detector asks for more players consistent with Law 8 than not, at least one of each side seen,
because a single player's kit can be misread (`track.assign_teams`); the share is part of the
confidence. A ball held still on the centre mark with the sides mixed is not a kick-off.

What follows a kick-off is for the readers of the events: after a goal the side that conceded kicks
off (Law 8), so a shot toward one goal followed by a kick-off by the defending side, with no
possession between, is a goal (the goal rule of automatic event detection, PR #271).

`confidence` is a score from 0 to 1 (the ball detection's median score over the still spell, times
the share of players where Law 8 puts them), not a calibrated probability.

**Set pieces** (Laws 13 to 17): where the still ball lies says which restart it can be
(`place_kind`: a corner arc, a goal area, a penalty mark, a touchline, elsewhere on the field), and
the players' arrangement at the kick must fit that Law (`set_piece_arrangement`), which also names
the side. A set piece restarts a stopped game, so the still must open the picture after a cut (which
leaves the wait out) or last MIN_STOPPAGE_S: a ball held still for a second in open play is not set,
nor is one the clip happens to start on. They are written `type: "set_piece"` with `restart` naming the kind.
"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from pathlib import Path
from statistics import median

from ninety.vision import events as ev
from ninety.vision.track import (
    FPS,
    MAX_GAP_FRAMES,
    BallPoint,
    Track,
    assign_teams,
    ball_path,
    read_observations,
    track_players,
)

# Law 1 (GROUNDING L1): the centre mark and the centre circle's 9.15 m.
CENTRE = (ev.PITCH_X / 2, ev.PITCH_Y / 2)
CIRCLE_M = 9.15
# The position error of a point on the ground through the broadcast camera: the players' measured
# 90th percentile on validation clips (events.RIVAL_M, docs/eval/attribution-derive.json). A ball
# set on the grass is projected the same way, through the same fitted camera, so the same error
# bounds where a still ball is seen to lie: its sightings within STILL_M of their median, that
# median within SPOT_M of its spot, and a player within it of a line he must stand behind.
POSITION_ERROR_M = ev.RIVAL_M
STILL_M = POSITION_ERROR_M
SPOT_M = POSITION_ERROR_M
# Law 1 (GROUNDING L1): the areas, from the goal's centre on its line; the posts are 3.66 m either
# side of it, the goal area reaches 5.5 m and the penalty area 16.5 m from each post and into the
# field; the penalty mark is 11 m out; the corner arc's radius is 1 m.
GOAL_AREA_X, GOAL_AREA_HALF_Y = 5.5, 3.66 + 5.5
PENALTY_AREA_X, PENALTY_AREA_HALF_Y = 16.5, 3.66 + 16.5
PENALTY_MARK_M = 11.0
CORNER_ARC_M = 1.0
THROW_KEEP_OFF_M = 2.0  # Law 15 (GROUNDING L7): opponents 2 m from the thrower
# A still spell lasts at least this long (design, set before measuring: the broadcast comes back
# from its cut 2 s before a restart, ninety/render/edit.py SHOW_BEFORE_RESTART_S, so a set ball is
# on screen at least that long; half of it leaves room for the ball hidden by the taker).
MIN_STILL_S = 1.0
# A still ball, and the kick, may be hidden by players (the taker's body as he strikes it: a free
# kick on the demo, frames 17336 to 17345) for up to the tracker's own wait for a hidden player,
# track.MAX_GAP_FRAMES (a second), never across a cut.
KICK_GAP_FRAMES = MAX_GAP_FRAMES
# A still spell opens a picture when its first sighting comes within events.SPELL_GAP_FRAMES (a
# quarter of a second) of the picture's first frame, with nothing seen before it.
SPELL_GAP_FRAMES = ev.SPELL_GAP_FRAMES
# A set piece restarts a stopped game (Laws 13 to 17), and its wait is long (GROUNDING R1: 16 s or
# more on average). A broadcast leaves out any dead ball's wait longer than MIN_STOPPAGE_S and comes
# back to the set ball (ninety/render/edit.py MIN_CUT_S, design), so a set ball is seen either just
# after a cut (or as the clip opens on it), or still for at least that long. A ball held still for
# a second or so in open play is neither (development check on the demo: 13 such, 1.0 to 1.6 s).
MIN_STOPPAGE_S = 4.0


@dataclass(frozen=True)
class Still:
    first: int  # frame
    last: int
    x: float  # the median place of its sightings
    y: float
    score: float  # the ball detection's median score over it
    sightings: int
    opens: bool = False  # it is what a picture opens on, just after a cut
    held: float = 0.0  # the share of its sightings drawn over a player (track.BallPoint.on_player)


def _clip(v: float, hi: float) -> float:
    return round(min(max(v, 0.0), hi), 2)


def cut_frames(rows: list[dict]) -> list[int]:
    """The last frame shown before each cut: where the frame numbers jump."""
    return [p["frame"] for p, q in zip(rows, rows[1:], strict=False) if q["frame"] != p["frame"] + 1]


def stills(path: list[BallPoint], cuts: list[int], shots: tuple[int, ...] = ()) -> list[Still]:
    """The still spells of the ball that end with it played: two sightings in a row off its spot,
    the first within KICK_GAP_FRAMES of the spell and none across a cut. `shots` are the first frames
    of each picture after a cut, so a spell a picture opens on is marked as one.
    One sighting off the spot with the next back on it is the detector's error, not the ball's, and
    is passed over."""

    def joined(p: BallPoint, q: BallPoint) -> bool:
        return q.frame - p.frame <= KICK_GAP_FRAMES and not any(p.frame <= c < q.frame for c in cuts)

    def opens(i: int) -> bool:
        return any(0 <= path[i].frame - f <= SPELL_GAP_FRAMES and (i == 0 or path[i - 1].frame < f)
                   for f in shots)

    def fits(run: list[BallPoint], q: BallPoint) -> bool:
        pts = run + [q]
        mx, my = median(b.x for b in pts), median(b.y for b in pts)
        return all(math.hypot(b.x - mx, b.y - my) <= STILL_M for b in pts)

    out: list[Still] = []
    i = 0
    while i < len(path):
        run, j, played = [path[i]], i + 1, False
        while j < len(path) and joined(run[-1], path[j]):
            if fits(run, path[j]):
                run.append(path[j])
                j += 1
                continue
            nxt = path[j + 1] if j + 1 < len(path) else None
            if nxt is None or not joined(path[j], nxt):
                break  # the clip or the picture ends on it: whether it was played is not seen
            if not fits(run, nxt):
                played = True
                break
            j += 1  # a lone sighting off the spot
        if played and (run[-1].frame - run[0].frame + 1) / FPS >= MIN_STILL_S:
            out.append(Still(run[0].frame, run[-1].frame, median(b.x for b in run),
                             median(b.y for b in run), median(b.score for b in run), len(run), opens(i),
                             sum(b.on_player for b in run) / len(run)))
        i = max(j, i + 1)
    return out


def _own_half(team: str, x: float) -> bool:
    """Whether a player of `team` at x is in his own half, the position error allowed."""
    half = CENTRE[0]
    return x <= half + POSITION_ERROR_M if team == "home" else x >= half - POSITION_ERROR_M


def kick_off_arrangement(s: Still, tracks: list[Track]) -> dict | None:
    """Law 8 at the still spell's last frame: who is seen where, the side taking it and the share
    of players where the Law puts them. None when the arrangement is not a kick-off's."""
    seen = [(t, t.at(s.last)) for t in tracks if t.team is not None and not t.keeper]
    seen = [(t, q) for t, q in seen if q is not None]
    if not {t.team for t, _ in seen} >= {"home", "away"}:
        return None  # each side must be seen to be in its own half
    near = sorted(((math.hypot(q[0] - s.x, q[1] - s.y), t) for t, q in seen), key=lambda d: d[0])
    inside = [(d, t) for d, t in near if d <= CIRCLE_M - POSITION_ERROR_M]
    if not inside:
        return None
    taker = inside[0][1]
    team = taker.team
    ok = 0
    for t, q in seen:
        in_circle = math.hypot(q[0] - s.x, q[1] - s.y) <= CIRCLE_M - POSITION_ERROR_M
        ok += _own_half(t.team, q[0]) and not (in_circle and t.team != team)
    share = ok / len(seen)
    if share <= 0.5:
        return None
    return {"team": team, "taker": taker, "share": share, "seen": len(seen)}


def place_kind(x: float, y: float) -> str | None:
    """Which restart a ball set still at (x, y) can be, from where it lies alone, the position error
    allowed (Laws 1, 8, 13 to 17): None for a ball outside the field. A ball on a touchline, held
    or placed, is a throw-in's (Law 15: thrown from where it crossed)."""
    e = POSITION_ERROR_M
    if x < -e or x > ev.PITCH_X + e or y < -e or y > ev.PITCH_Y + e:
        return None
    if math.hypot(x - CENTRE[0], y - CENTRE[1]) <= SPOT_M:
        return "kick_off"
    corners = [(cx, cy) for cx in (0.0, ev.PITCH_X) for cy in (0.0, ev.PITCH_Y)]
    if min(math.hypot(x - cx, y - cy) for cx, cy in corners) <= CORNER_ARC_M + e:
        return "corner"
    if y <= e or y >= ev.PITCH_Y - e:
        return "throw_in"
    from_line, across = min(x, ev.PITCH_X - x), abs(y - CENTRE[1])
    if from_line <= GOAL_AREA_X + e and across <= GOAL_AREA_HALF_Y + e:
        return "goal_kick"
    if math.hypot(from_line - PENALTY_MARK_M, across) <= e:
        return "penalty_kick"
    return "free_kick"


def _attacker_at(x: float) -> str:
    """The side attacking the goal nearer x: home attacks x = 105 (ninety/vision/events.py)."""
    return "home" if x >= CENTRE[0] else "away"


def _in_penalty_area(q: tuple[float, float], end_x: float, shrink: float) -> bool:
    return (abs(q[0] - end_x) <= PENALTY_AREA_X - shrink
            and abs(q[1] - CENTRE[1]) <= PENALTY_AREA_HALF_Y - shrink)


def set_piece_arrangement(kind: str, s: Still, tracks: list[Track]) -> dict | None:
    """The side taking a set piece and its taker, if the players stand as its Law says at the still
    spell's last frame; None if they do not. A player is held to a distance only when he is inside
    it by more than the position error.
    - corner (Law 17): the side attacking that goal; no opponent within 9.15 m of the ball;
    - goal kick (Law 16): the side defending it; no opponent inside the penalty area;
    - penalty kick (Law 14): the side attacking it; nobody else in the penalty area but its keeper;
    - free kick (Law 13): the side of the nearest player, within reach of the ball (GROUNDING P6);
      no opponent within 9.15 m;
    - throw-in (Law 15): the side of the player holding it, the same way; no opponent within 2 m.
    For either, the nearest a keeper in his own penalty area is his hold (Law 12): not a set piece.
    For any, a keeper at the ball with it drawn over him for most of the still holds it in his hands
    (more than half: *design*): his hold, not a set ball. The taker is named only when a player of
    the side is within reach of the ball."""
    e = POSITION_ERROR_M
    seen = [(t, t.at(s.last)) for t in tracks if t.team is not None]
    seen = [(t, q) for t, q in seen if q is not None]
    near = sorted(seen, key=lambda tq: math.hypot(tq[1][0] - s.x, tq[1][1] - s.y))
    at_ball = [t for t, q in near if math.hypot(q[0] - s.x, q[1] - s.y) <= ev.CONTROL_M + e]
    end_x = 0.0 if s.x < CENTRE[0] else ev.PITCH_X
    if at_ball and at_ball[0].keeper and s.held > 0.5:
        return None  # in the keeper's hands most of the time (Law 12): his hold, not a set ball
    if kind in ("corner", "penalty_kick"):
        team = _attacker_at(s.x)
    elif kind == "goal_kick":
        team = "away" if _attacker_at(s.x) == "home" else "home"
    else:  # a free kick or a throw-in: the side of the player at the ball
        if not near or math.hypot(near[0][1][0] - s.x, near[0][1][1] - s.y) > ev.CONTROL_M + e:
            return None
        t0, q0 = near[0]
        if t0.keeper and _in_penalty_area(q0, end_x, -e):
            return None
        team = t0.team
    rivals = [(t, q) for t, q in seen if t.team != team]
    if kind in ("corner", "free_kick", "throw_in"):
        keep_off = THROW_KEEP_OFF_M if kind == "throw_in" else CIRCLE_M
        if any(math.hypot(q[0] - s.x, q[1] - s.y) < keep_off - e for _, q in rivals):
            return None
    elif kind == "goal_kick":
        if any(_in_penalty_area(q, end_x, e) for _, q in rivals):
            return None
    elif kind == "penalty_kick":
        inside = [t for t, q in seen if _in_penalty_area(q, end_x, e) and not (t.keeper and t.team != team)]
        if len(inside) > 1:
            return None
    mates = [t for t in at_ball if t.team == team]
    return {"team": team, "taker": mates[0] if mates else None}


def detect(rows: list[dict]) -> tuple[list[dict], dict]:
    """The detected restarts, and a summary of how they were found."""
    t_of = {r["frame"]: r["t"] for r in rows}
    tracks = track_players(rows)
    assign_teams(tracks)
    path = ball_path(rows)
    index = {p.frame: i for i, p in enumerate(path)}
    found: list[dict] = []
    # The pictures after each cut; not the clip's own start, which may fall anywhere in a wait, so
    # a set ball it opens on shows no stoppage (the demo's segments: a ball held at a player's feet).
    shots = tuple(q["frame"] for p, q in zip(rows, rows[1:], strict=False) if q["frame"] != p["frame"] + 1)
    spells = stills(path, cut_frames(rows), shots)
    kinds = {k: 0 for k in ("kick_off", "corner", "goal_kick", "penalty_kick", "free_kick", "throw_in")}

    def event(kind: str, s: Still, team: str, taker: Track | None, conf: float) -> None:
        e = {"id": "", "t": t_of[s.last], "frame": s.last,
             "type": "kickoff" if kind == "kick_off" else "set_piece", "team": team,
             "team_confidence": taker.side_confidence if taker else None,
             "player": ev.attribute(taker, path[index[s.last]], tracks) if taker else None, "receiver": None,
             "x": _clip(s.x, ev.PITCH_X), "y": _clip(s.y, ev.PITCH_Y), "end_x": None, "end_y": None,
             "outcome": None, "ball_speed_kmh": None, "source": "vision", "confidence": round(conf, 3)}
        if kind != "kick_off":
            e["restart"] = kind
        found.append(e)

    for s in spells:
        kind = place_kind(s.x, s.y)
        if kind is None:
            continue
        kinds[kind] += 1
        if kind == "kick_off":
            law8 = kick_off_arrangement(s, tracks)
            if law8 is not None:
                event(kind, s, law8["team"], law8["taker"], s.score * law8["share"])
            continue
        if not (s.opens or (s.last - s.first + 1) / FPS >= MIN_STOPPAGE_S):
            continue  # no stoppage seen before it: a ball held still in play
        law = set_piece_arrangement(kind, s, tracks)
        if law is not None:
            event(kind, s, law["team"], law["taker"], s.score)
    for n, e in enumerate(found, start=1):
        e["id"] = f"r{n:05d}"
    summary = {
        "ball_sightings": len(path),
        "still_spells": len(spells),
        "on_centre_mark": kinds["kick_off"],
        "still_at": kinds,
        "events": {k: sum(1 for e in found if (e.get("restart") or "kick_off") == k) for k in kinds},
    }
    return found, summary


def merge(events: list[dict], restarts: list[dict]) -> list[dict]:
    """One time-ordered stream of the two detectors' events, each keeping its own id."""
    return sorted(events + restarts, key=lambda e: (e["frame"], e["type"]))


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Detect restarts from observations.")
    ap.add_argument("observations", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--summary", type=Path, default=None, help="how the restarts were found, as JSON")
    a = ap.parse_args(argv)
    found, summary = detect(read_observations(a.observations))
    a.out.write_text("".join(json.dumps(e) + "\n" for e in found), encoding="utf-8")
    if a.summary:
        a.summary.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary["events"] | {"out": str(a.out)}))


if __name__ == "__main__":
    main()
