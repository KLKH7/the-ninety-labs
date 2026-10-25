"""Automatic restart detection: the ball set still at its spot, then played. Kick-offs first.

    uv run python -m ninety.vision.restarts <observations.jsonl> --out restarts.jsonl

Reads only the observations file (`ninety.vision.observe`), as `ninety.vision.events` does, and
writes match_event lines with `source: "vision"`. Nothing here reads ground truth, so it may run on
the live path (tests/test_vision_live_path.py watches it run); the live job does not call it yet.
The rules are the Laws' (docs/GROUNDING.md); every tolerance is the measured position error, stated
before any validation clip was scored (docs/eval/restarts-vision-plan.md). `merge` joins its events
to `events.detect`'s, leaving out a possession change while the ball lies set for a restart.

**Still.** A restart is taken with the ball stationary on its spot (Laws 8, 13, 15 to 17). A still
spell is a run of ball sightings, none more than SPELL_GAP_FRAMES apart and none across a cut of
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

Planned, in this module, by the same rules: corner, goal kick, throw-in and free kick.
"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from pathlib import Path
from statistics import median

from ninety.vision import events as ev
from ninety.vision import sides
from ninety.vision.track import (
    FPS,
    BallPoint,
    Track,
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
# A still spell lasts at least this long (design, set before measuring: the broadcast comes back
# from its cut 2 s before a restart, ninety/render/edit.py SHOW_BEFORE_RESTART_S, so a set ball is
# on screen at least that long; half of it leaves room for the ball hidden by the taker).
MIN_STILL_S = 1.0
# Sightings of a still ball may be missing (the taker's legs) for up to events.SPELL_GAP_FRAMES.
SPELL_GAP_FRAMES = ev.SPELL_GAP_FRAMES


@dataclass(frozen=True)
class Still:
    first: int  # frame
    last: int
    x: float  # the median place of its sightings
    y: float
    score: float  # the ball detection's median score over it
    sightings: int


def _clip(v: float, hi: float) -> float:
    return round(min(max(v, 0.0), hi), 2)


def cut_frames(rows: list[dict]) -> list[int]:
    """The last frame shown before each cut: where the frame numbers jump."""
    return [p["frame"] for p, q in zip(rows, rows[1:], strict=False) if q["frame"] != p["frame"] + 1]


def stills(path: list[BallPoint], cuts: list[int]) -> list[Still]:
    """The still spells of the ball that end with it played: two sightings in a row off its spot,
    the first within SPELL_GAP_FRAMES of the spell and none across a cut. One sighting off the spot
    with the next back on it is the detector's error, not the ball's, and is passed over."""

    def joined(p: BallPoint, q: BallPoint) -> bool:
        return q.frame - p.frame <= SPELL_GAP_FRAMES and not any(p.frame <= c < q.frame for c in cuts)

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
                             median(b.y for b in run), median(b.score for b in run), len(run)))
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


def detect(rows: list[dict]) -> tuple[list[dict], dict]:
    """The detected restarts, and a summary of how they were found."""
    t_of = {r["frame"]: r["t"] for r in rows}
    tracks = track_players(rows)
    sides.assign(tracks, rows)  # the same sides events.detect gives, so a kick-off and a pass agree
    path = ball_path(rows)
    index = {p.frame: i for i, p in enumerate(path)}
    found: list[dict] = []
    spells = stills(path, cut_frames(rows))
    on_spot = [s for s in spells if math.hypot(s.x - CENTRE[0], s.y - CENTRE[1]) <= SPOT_M]
    dead: list[list[int]] = []  # each found restart's still spell: the ball dead and set
    for s in on_spot:
        law8 = kick_off_arrangement(s, tracks)
        if law8 is None:
            continue
        taker: Track = law8["taker"]
        dead.append([s.first, s.last])
        found.append({
            "id": "", "t": t_of[s.last], "frame": s.last, "type": "kickoff", "team": law8["team"],
            "team_confidence": taker.side_confidence,
            "player": ev.attribute(taker, path[index[s.last]], tracks), "receiver": None,
            "x": _clip(s.x, ev.PITCH_X), "y": _clip(s.y, ev.PITCH_Y), "end_x": None, "end_y": None,
            "outcome": None, "ball_speed_kmh": None, "source": "vision",
            "confidence": round(s.score * law8["share"], 3),
        })
    for n, e in enumerate(found, start=1):
        e["id"] = f"r{n:05d}"
    summary = {
        "ball_sightings": len(path),
        "still_spells": len(spells),
        "on_centre_mark": len(on_spot),
        "events": {"kickoff": len(found)},
        "dead_balls": dead,
    }
    return found, summary


def merge(events: list[dict], restarts: list[dict], dead_balls: list[list[int]] = ()) -> list[dict]:
    """One time-ordered stream of the two detectors' events, each keeping its own id. The ball is
    not in play while it lies set for a restart, until it is kicked and clearly moves (Laws 8 and
    13 to 17), so a possession change `events.detect` gives inside a restart's still spell
    (`dead_balls`, from `detect`'s summary) is the restart being set up (the taker's spell beginning
    at the ball), not one side winning it from the other: it is left out. events.possession_changes
    leaves out only changes across an out of play or a cut; this adds the set ball."""
    def set_up(e: dict) -> bool:
        return e["type"] == "possession_change" and any(a <= e["frame"] <= b for a, b in dead_balls)
    return sorted([e for e in events if not set_up(e)] + restarts, key=lambda e: (e["frame"], e["type"]))


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Detect restarts (kick-offs) from observations.")
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
