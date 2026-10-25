"""Automatic event detection of restarts: set pieces and kick-offs, and their kind.

    uv run python -m ninety.vision.restarts <observations.jsonl> --events detected.jsonl \\
        --out restart-events.jsonl --report restarts.json

Reads only the observations (`ninety.vision.observe`) and the events `ninety.vision.events` found
in them. Writes match_event lines (`set_piece` or `kickoff`, `source: "vision"`), and a side report
with each one's kind (throw-in, goal kick, corner, free kick, penalty kick, kick-off): the event
schema has no field for it. The rule is docs/eval/set-piece-detection-plan.md's, fixed before it
ran on any clip; nothing reads ground truth.

1. A dead ball first (a cue): an out of play `events.py` found, a cut (the frame numbers jump, as
   events.py reads a cut, or `camera.shot` changes), or the clip's first frame (a kick-off only).
   Only the fact of a cut is read, never how long it is: that length is the wait the edit left out.
2. Then a set ball: the ball seen on at least STILL_FRAMES frames in a row, slower than
   events.CARRY_MPS, every position within BALL_TOL_M of the run's median (a set ball stays put),
   the median on the field (within BALL_TOL_M of its lines), not held up in a player's hands.
3. Then the restart: the ball moves off faster than CARRY_MPS with a player within CONTROL_M: the
   taker. Its time is the strike (Laws 8, 13 to 17: in play when kicked and it clearly moves), its
   spot the run's median, its team the taker's side.
A throw-in has no set ball on the ground: the ball is in the thrower's hands over his head (Law 15),
drawn over his body above his hips, so its place on the ground is metres wrong. After a cue, the
ball held so on HELD_FRAMES frames in a row by one player whose feet are within LINE_TOL_M of a
touchline, or beyond it, then off his body, is a throw-in at his place on that line.

One cue admits one restart: the first after it, and the latest cue before a restart is its cue.
The kind comes from the spot alone (Law 1's markings, nearest zone first); the stoppage before it
only halves the confidence when it contradicts the kind. `confidence` is a score from 0 to 1 (the
ball detection's mean score over the run, scaled down for a short run), not a probability.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
from dataclasses import dataclass
from pathlib import Path

from ninety.vision import events as ev
from ninety.vision.track import (
    SCORE_MIN,
    BallPoint,
    Track,
    assign_teams,
    ball_path,
    read_observations,
    track_players,
)
from ninety.vision.tracked_frames import player_id

# Law 1 (GROUNDING L1): the pitch, the centre spot, the penalty marks 11 m out on the goal's centre
# line, the corner arcs of radius 1 m, the goal areas 5.5 m deep and 18.32 m wide (5.5 m either side
# of the 7.32 m goal), centred on y = 34.
PITCH_X, PITCH_Y = ev.PITCH_X, ev.PITCH_Y
CENTRE = (PITCH_X / 2, PITCH_Y / 2)
MARKS = ((11.0, PITCH_Y / 2), (PITCH_X - 11.0, PITCH_Y / 2))
CORNERS = ((0.0, 0.0), (0.0, PITCH_Y), (PITCH_X, 0.0), (PITCH_X, PITCH_Y))
CORNER_ARC_M = 1.0
GOAL_AREA_X, GOAL_AREA_HALF_Y = 5.5, 9.16
# The ball's measured ground position error: its 90th percentile on the ball on the ground, on the
# possession set's validation sample (seed 920101 from 1410 s, renderer 0.5.17, the drawn labels as
# detections), rounded up to the cm; the players' foot points the same way. The live camera fit
# trusts no frame of that look, so both are measured through the true camera
# (docs/eval/set-pieces/tolerance.json; docs/eval/set-piece-detection-plan.md, amendment 2): the
# error of the boxes alone. They hold only for observations placed that well, and are re-measured on
# the live fit's reading once it places this look, before any live restart number is read.
BALL_TOL_M = 0.06
LINE_TOL_M = 0.48
# A set ball is still on this many frames in a row (design, set before any run: 0.4 s; a pass rolls
# past at pass speed for none, and the engine's shortest wait over a placed ball is longer).
STILL_FRAMES = 10
# The ball in his hands on this many frames in a row (design: as events.OUT_FRAMES, one frame is as
# likely a ball passing in front of him).
HELD_FRAMES = ev.OUT_FRAMES
# Above his hips is held, not at his feet: the hip (greater trochanter) is at 0.530 of standing
# height (Winter, Biomechanics and Motor Control of Human Movement, segment proportions; GROUNDING VR4),
# so from the box's top it is 0.47 of the box down.
HIP_FROM_TOP = 1.0 - 0.530
# Missing ball frames inside a run that do not end it (as events.SPELL_GAP_FRAMES).
GAP_FRAMES = ev.SPELL_GAP_FRAMES
CONTRADICTED = 0.5  # design: a kind the detector's own last stoppage contradicts keeps half its score
KINDS = ("throw_in", "goal_kick", "corner", "free_kick", "penalty_kick", "kick_off")


@dataclass(frozen=True)
class Candidate:
    frame: int  # the strike or the throw
    first: int  # the run's first frame
    frames: int  # ball points in the run
    x: float
    y: float
    track: Track
    kind: str
    zone_m: float | None  # how far the spot is from its zone (0 inside it); None for a free kick
    score: float  # the ball detection's mean score over the run


def _cuts(rows: list[dict]) -> list[int]:
    """The first frame after each cut: the frame numbers jump, or the camera's shot changes."""
    out = []
    for p, q in zip(rows, rows[1:], strict=False):
        if q["frame"] != p["frame"] + 1 or q["camera"].get("shot", 0) != p["camera"].get("shot", 0):
            out.append(q["frame"])
    return out


def cues(rows: list[dict], found: list[dict]) -> list[tuple[int, str]]:
    """(frame, why) for every dead ball the observations and the found events show, in time order."""
    out = [(rows[0]["frame"], "start")] if rows else []
    out += [(f, "cut") for f in _cuts(rows)]
    out += [(e["frame"], e["type"]) for e in found if e["type"] in ("out_of_play", "goal")]
    return sorted(out)


def _held_by(row: dict, p: BallPoint) -> dict | None:
    """The player detection whose box the ball is drawn in above his hips (in his hands), or None."""
    if p.u is None:
        return None
    for d in row["players"]:
        x0, y0, x1, y1 = d["bbox"]
        if d["score"] >= SCORE_MIN and d.get("x") is not None and x0 <= p.u <= x1 and y0 <= p.v <= y1:
            if y1 > y0 and (p.v - y0) / (y1 - y0) < HIP_FROM_TOP:
                return d
    return None


def _track_at(tracks: list[Track], frame: int, xy: tuple[float, float]) -> Track | None:
    for t in tracks:
        q = t.at(frame)
        if q is not None and math.isclose(q[0], xy[0]) and math.isclose(q[1], xy[1]):
            return t
    return None


def _nearest(tracks: list[Track], frame: int, x: float, y: float) -> Track | None:
    best, best_d = None, ev.CONTROL_M
    for t in tracks:
        q = t.at(frame)
        if q is not None and (d := math.hypot(q[0] - x, q[1] - y)) <= best_d:
            best, best_d = t, d
    return best


def _dist_to_box(x: float, y: float, x0: float, x1: float, y0: float, y1: float) -> float:
    return math.hypot(max(x0 - x, 0.0, x - x1), max(y0 - y, 0.0, y - y1))


def kind_of(x: float, y: float) -> tuple[str, float | None]:
    """The kind of a set ball at (x, y) and its distance from that kind's zone: the nearest zone
    within BALL_TOL_M (Law 1's markings), else a free kick."""
    zones = [("kick_off", math.dist((x, y), CENTRE))]
    zones += [("penalty_kick", min(math.dist((x, y), m) for m in MARKS))]
    zones += [("corner", max(0.0, min(math.dist((x, y), c) for c in CORNERS) - CORNER_ARC_M))]
    lo, hi = PITCH_Y / 2 - GOAL_AREA_HALF_Y, PITCH_Y / 2 + GOAL_AREA_HALF_Y
    zones += [("goal_kick", min(_dist_to_box(x, y, 0.0, GOAL_AREA_X, lo, hi),
                                _dist_to_box(x, y, PITCH_X - GOAL_AREA_X, PITCH_X, lo, hi)))]
    kind, d = min(zones, key=lambda z: z[1])
    return (kind, round(d, 2)) if d <= BALL_TOL_M else ("free_kick", None)


def _runs(path: list[BallPoint], cut_frames: set[int], keep) -> list[list[int]]:
    """Runs of path indices that `keep` accepts, broken by a cut or a gap over GAP_FRAMES."""
    out: list[list[int]] = []
    cur: list[int] = []
    for i, p in enumerate(path):
        if cur:
            prev = path[cur[-1]].frame
            broken = p.frame - prev > GAP_FRAMES + 1 or any(prev < c <= p.frame for c in cut_frames)
            if broken or not keep(i, cur):
                if len(cur) > 0:
                    out.append(cur)
                cur = []
        if keep(i, cur):
            cur.append(i)
    if cur:
        out.append(cur)
    return out


def set_balls(path: list[BallPoint], rows_at: dict[int, dict], tracks: list[Track],
              cut_frames: set[int]) -> list[Candidate]:
    """Each set ball that is then struck, as a candidate restart."""
    held = {i for i, p in enumerate(path) if _held_by(rows_at[p.frame], p) is not None}

    def still(i: int, cur: list[int]) -> bool:
        if i in held:
            return False
        v = ev._velocity(path, i)
        if v is not None and math.hypot(*v) >= ev.CARRY_MPS:
            return False
        pts = [path[j] for j in cur] + [path[i]]
        mx, my = statistics.median(q.x for q in pts), statistics.median(q.y for q in pts)
        return all(math.hypot(q.x - mx, q.y - my) <= BALL_TOL_M for q in pts)

    out = []
    for run in _runs(path, cut_frames, still):
        if len(run) < STILL_FRAMES or run[-1] + 1 >= len(path):
            continue
        nxt = run[-1] + 1
        last = path[run[-1]]
        # No speed across a cut or a long gap (events._velocity): nobody was seen striking it.
        v = ev._velocity(path, nxt)
        if v is None or math.hypot(*v) < ev.CARRY_MPS:
            continue
        pts = [path[j] for j in run]
        mx, my = statistics.median(q.x for q in pts), statistics.median(q.y for q in pts)
        if not (-BALL_TOL_M <= mx <= PITCH_X + BALL_TOL_M and -BALL_TOL_M <= my <= PITCH_Y + BALL_TOL_M):
            continue  # a dead ball stopped off the field is not set
        taker = _nearest(tracks, last.frame, mx, my)
        if taker is None:
            continue
        kind, zone = kind_of(mx, my)
        out.append(Candidate(last.frame, pts[0].frame, len(pts), mx, my, taker, kind, zone,
                             statistics.fmean(q.score for q in pts)))
    return out


def throws(path: list[BallPoint], rows_at: dict[int, dict], tracks: list[Track],
           cut_frames: set[int]) -> list[Candidate]:
    """Each ball held up by one player at a touchline and then let go, as a candidate throw-in."""
    by: dict[int, Track | None] = {}
    for i, p in enumerate(path):
        d = _held_by(rows_at[p.frame], p)
        by[i] = _track_at(tracks, p.frame, (d["x"], d["y"])) if d is not None else None

    def held(i: int, cur: list[int]) -> bool:
        return by[i] is not None and (not cur or by[cur[0]] is by[i])

    out = []
    for run in _runs(path, cut_frames, held):
        if len(run) < HELD_FRAMES or run[-1] + 1 >= len(path):
            continue
        thrower, last = by[run[0]], path[run[-1]]
        nxt = path[run[-1] + 1]
        if nxt.frame - last.frame > GAP_FRAMES + 1 or any(last.frame < c <= nxt.frame for c in cut_frames):
            continue
        feet = [thrower.at(path[j].frame) for j in run]
        fx, fy = statistics.median(f[0] for f in feet), statistics.median(f[1] for f in feet)
        line = 0.0 if fy < PITCH_Y / 2 else PITCH_Y
        if abs(fy - line) > LINE_TOL_M and (0.0 < fy < PITCH_Y):
            continue  # not at a touchline: a keeper's catch, or a ball drawn over a head
        out.append(Candidate(last.frame, path[run[0]].frame, len(run), min(max(fx, 0.0), PITCH_X), line,
                             thrower, "throw_in", round(abs(fy - line) if 0 < fy < PITCH_Y else 0.0, 2),
                             statistics.fmean(path[j].score for j in run)))
    return out


def _contradicts(kind: str, stop: dict | None) -> bool:
    """Whether the detector's own last stoppage contradicts the kind: out over a touchline before a
    corner or goal kick, or over a goal line before a throw-in. A stoppage at a corner says neither."""
    if stop is None or stop["type"] != "out_of_play":
        return False
    touch = stop["y"] in (0.0, PITCH_Y) and stop["x"] not in (0.0, PITCH_X)
    goal_line = stop["x"] in (0.0, PITCH_X) and stop["y"] not in (0.0, PITCH_Y)
    return (kind in ("corner", "goal_kick") and touch) or (kind == "throw_in" and goal_line)


def detect(rows: list[dict], found: list[dict]) -> tuple[list[dict], dict]:
    """The restart events and the side report (each restart's kind and how it was found)."""
    t_of = {r["frame"]: r["t"] for r in rows}
    rows_at = {r["frame"]: r for r in rows}
    tracks = track_players(rows)
    assign_teams(tracks)
    path = ball_path(rows)
    cut_frames = set(_cuts(rows))
    found_cues = cues(rows, found)
    cands = sorted(set_balls(path, rows_at, tracks, cut_frames) + throws(path, rows_at, tracks, cut_frames),
                   key=lambda c: (c.frame, c.first))
    used: set[int] = set()
    events, report = [], []
    for c in cands:
        before = [k for k, cue in enumerate(found_cues) if cue[0] <= c.first]
        if not before:
            continue
        k = before[-1]
        frame, why = found_cues[k]
        if k in used or (why == "start" and c.kind != "kick_off") or c.track.team is None:
            continue
        used.add(k)
        stops = [e for e in found if e["type"] in ("out_of_play", "goal") and e["frame"] <= c.first]
        stop = stops[-1] if stops and (not events or stops[-1]["frame"] > events[-1]["frame"]) else None
        conf = c.score * min(1.0, c.frames / (2 * (HELD_FRAMES if c.kind == "throw_in" else STILL_FRAMES)))
        if _contradicts(c.kind, stop):
            conf *= CONTRADICTED
        x, y = (c.track.at(c.frame) or (c.x, c.y)) if c.kind == "kick_off" else (c.x, c.y)
        ball = next((p for p in path if p.frame == c.frame), None)
        e = {"id": f"r{len(events) + 1:05d}", "t": t_of[c.frame], "frame": c.frame,
             "type": "kickoff" if c.kind == "kick_off" else "set_piece", "team": c.track.team,
             "team_confidence": c.track.side_confidence,
             "player": ev.attribute(c.track, ball, tracks) if ball is not None else None,
             "receiver": None, "x": ev._clip(x, PITCH_X), "y": ev._clip(y, PITCH_Y), "end_x": None,
             "end_y": None, "outcome": None, "ball_speed_kmh": None, "source": "vision",
             "confidence": round(conf, 3)}
        events.append(e)
        report.append({"id": e["id"], "frame": c.frame, "kind": c.kind, "zone_m": c.zone_m,
                       "spot": [round(c.x, 2), round(c.y, 2)], "run_from": c.first, "run_frames": c.frames,
                       "cue": why, "cue_frame": frame, "contradicted": _contradicts(c.kind, stop),
                       "taker": player_id(c.track) if c.track.team else None})
    summary = {"cues": len(found_cues), "candidates": len(cands), "restarts": len(events),
               "kinds": {k: sum(1 for r in report if r["kind"] == k) for k in KINDS},
               "ball_tol_m": BALL_TOL_M, "line_tol_m": LINE_TOL_M}
    return events, {"summary": summary, "restarts": report}


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Detect set pieces and kick-offs, and their kind.")
    ap.add_argument("observations", type=Path)
    ap.add_argument("--events", type=Path, required=True, help="the events ninety.vision.events found")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--report", type=Path, default=None, help="each restart's kind, as JSON")
    a = ap.parse_args(argv)
    found = [json.loads(x) for x in a.events.read_text().splitlines() if x.strip()]
    events, report = detect(read_observations(a.observations), found)
    a.out.write_text("".join(json.dumps(e) + "\n" for e in events), encoding="utf-8")
    if a.report:
        a.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report["summary"] | {"out": str(a.out)}))


if __name__ == "__main__":
    main()
