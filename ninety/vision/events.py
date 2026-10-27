"""Automatic event detection: tracks -> possession -> passes, shots, out of play and possession changes.

    uv run python -m ninety.vision.events <observations.jsonl> --out detected.jsonl

Reads only the observations file (`ninety.vision.observe`: the camera estimated from the image
and the detector's boxes on the pitch). Writes match_event lines with `source: "vision"`, as
`ninety.eval.event_score` grades them. Every number comes from the code below; nothing reads
ground truth.

Possession. A player has the ball in a frame when it is within CONTROL_M of his foot point and
moving with him (relative speed under CARRY_MPS): a pass rolling past him at 10 m/s is near him for
several frames without being his. Consecutive frames of one player make a spell.

Events, from one spell to the next:
- the ball leaves a spell and the next spell is someone else's: a pass at the last frame of the
  first spell (when the ball was struck), from where the ball was then; `success` when the next
  player is a team-mate, `fail` otherwise;
- the same, but the ball's path after the strike heads between the posts of the goal the team
  attacks: a shot instead;
- the ball's centre goes beyond a line by more than its radius (Law 9: the whole ball over the
  line): out of play, for the team that had it last; a pass that went out first is `fail`;
- a spell of the other side from the last spell with a side, the ball in play between them: a
  possession change, at the new spell's first frame (`possession_changes`). A restart's is not
  told: after the ball went out, or across a cut, the next spell may be the taker's walk to it.
  No `interception` is written: the answer key's needs the pass's aim, which the picture does not
  show (docs/eval/possession-change-plan.md); a failed pass names its `interceptor`.

A broadcast cuts away from a long dead ball to its restart (ninety/render/edit.py): the frame
numbers jump there. Nothing seen before a cut is linked to anything after it: a spell before it and
one after it are not a pass, unless the ball was seen going out before the cut.

Who. The detector sees shirts, not names, so a player is his side and his track, `h-t12`, the id the
phone companion's minimap shows (ninety/vision/tracked_frames.py). A pass or shot names its
`player`, the spell's holder at the strike; a completed pass its `receiver` and a pass the other side
took its `interceptor`, the next spell's holder at its first frame. Each is named only when it is
unambiguous (`attribute`): no other track as near the ball, within the players' position error.
Otherwise it stays null and the event keeps only its `team`, from the holder's kit colour, so the
agents can still say what a side did. Out of play names nobody (the truth's names nobody either).
`intended` and `deflected_by` stay null: neither is visible in a spell.
`confidence` is a score from 0 to 1 (the ball detection's score at the strike, scaled down for a
short spell), not a calibrated probability.
"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from pathlib import Path

from ninety.vision import outcomes, sides
from ninety.vision.track import (
    FPS,
    MAX_GAP_FRAMES,
    BallPoint,
    Track,
    ball_path,
    read_observations,
    track_players,
)
from ninety.vision.tracked_frames import MIN_TRACK_FRAMES, player_id

# Law 1 (GROUNDING L1): goal 7.32 m wide, centred on y = 34.
PITCH_X, PITCH_Y = 105.0, 68.0
POST_Y = (34.0 - 3.66, 34.0 + 3.66)
BALL_R = 0.11  # a size-5 ball is 68 to 70 cm round (Law 2): radius about 0.11 m
# The ball at a player's feet is within 1.5 m of him (GROUNDING P6).
CONTROL_M = 1.5
# A carried ball moves with the carrier; a struck one leaves at 10 m/s or more (event-motion.md:
# about 10 m/s after a pass). Between the two, 4 m/s relative (design), above the velocity noise
# of positions over SPEED_FRAMES (about 2 m/s for a 0.2 m position error over 0.16 s).
CARRY_MPS = 4.0
SPEED_FRAMES = 2  # velocities from positions this many frames either side
# A spell needs this many frames: one frame near a player is a ball passing him (design).
MIN_SPELL_FRAMES = 2
# Missing ball frames inside a spell (the ball hidden by the player's own legs) up to this many
# do not end it (design: a quarter of a second).
SPELL_GAP_FRAMES = 6
# A shot is judged from the ball's path over the strike's first SHOT_LOOK_S: its line, carried
# on, must cross the goal line between the posts widened by SHOT_MARGIN_M (the ball's place is
# known to about a metre, design), from no farther than SHOT_MAX_M (design: beyond 35 m almost
# nothing is shot at goal).
SHOT_LOOK_S = 0.3
SHOT_MARGIN_M = 1.0
SHOT_MAX_M = 35.0
# The ball must be over a line for this many frames running before it is out: a single frame
# beyond is as likely the camera fit as the ball (design).
OUT_FRAMES = 3
# Attribution. The holder is within CONTROL_M of the ball by construction; he is named only when no
# other track is within RIVAL_M of his own distance from it: a rival that close may truly be the
# nearer one. RIVAL_M is the players' measured pitch-position error, its 90th percentile pooled over
# ours-v2's validation clips (never test clips), rounded to cm: 1.256 m on the frames the camera
# trust test passes (docs/eval/attribution-derive.json, players_position_error.p90_m). It is
# re-measured whenever that test changes: 1.89 m with the marking test (docs/eval/attribution-plan.md),
# 1.59 m with players' heights (docs/eval/detector-plan.md), 1.26 m with heights and neighbours
# (docs/eval/camera-bound-plan.md). It still includes validation seed 108, whose whole clip is a
# few metres off. tests/test_attribution_score.py holds it to the committed measurement.
RIVAL_M = 1.26
# One player in two tracks. The tracker drops a player whose position jumps past its gate (a
# sprint plus the camera fit's jitter) and starts a new track the next frame, so his dribble can
# read as a pass to himself. Two tracks never seen in the same frame, the second starting within
# the tracker's own MAX_GAP_FRAMES of the first's end and within reach of where it ended, may be
# one player: a pass between them cannot be told from his own touch, so none is recorded. Reach is
# REACH_MPS over the gap, plus RIVAL_M, the position error, for where each was seen. REACH_MPS is a
# player's top-speed capability, about 10 m/s (GROUNDING P9; match peaks are lower, 7.9 to 8.6 m/s,
# R6), so no player covers more. The rule's form was chosen on test seed 900004 (two self-passes
# there); it is kept or dropped on validation clips only (docs/eval/attribution-plan.md).
REACH_MPS = 10.0


@dataclass(frozen=True)
class Spell:
    track: Track
    first: int  # frame
    last: int
    frames: int  # frames with the ball seen at his feet


def _velocity(path: list[BallPoint], i: int) -> tuple[float, float] | None:
    a, b = max(0, i - SPEED_FRAMES), min(len(path) - 1, i + SPEED_FRAMES)
    dt = (path[b].frame - path[a].frame) / FPS
    if dt <= 0 or path[b].frame - path[a].frame > 4 * SPEED_FRAMES:
        return None
    return (path[b].x - path[a].x) / dt, (path[b].y - path[a].y) / dt


def _track_velocity(t: Track, frame: int) -> tuple[float, float] | None:
    here = t.at(frame)
    a = t.at(frame - SPEED_FRAMES) or here
    b = t.at(frame + SPEED_FRAMES) or here
    if here is None or a is None or b is None or a is b:
        return (0.0, 0.0) if here is not None else None
    fa = frame - SPEED_FRAMES if t.at(frame - SPEED_FRAMES) else frame
    fb = frame + SPEED_FRAMES if t.at(frame + SPEED_FRAMES) else frame
    dt = (fb - fa) / FPS
    return ((b[0] - a[0]) / dt, (b[1] - a[1]) / dt) if dt > 0 else (0.0, 0.0)


def holder(path: list[BallPoint], i: int, tracks: list[Track]) -> Track | None:
    """The player who has the ball at path[i], or None."""
    p = path[i]
    best, best_d = None, CONTROL_M
    for t in tracks:
        q = t.at(p.frame)
        if q is None:
            continue
        d = math.hypot(q[0] - p.x, q[1] - p.y)
        if d <= best_d:
            best, best_d = t, d
    if best is None:
        return None
    vb, vt = _velocity(path, i), _track_velocity(best, p.frame)
    if vb is None or vt is None:
        return best
    return best if math.hypot(vb[0] - vt[0], vb[1] - vt[1]) <= CARRY_MPS else None


def spells(path: list[BallPoint], tracks: list[Track]) -> list[Spell]:
    out: list[Spell] = []
    cur: list | None = None  # [track, first, last, frames]
    for i, p in enumerate(path):
        h = holder(path, i, tracks)
        if h is None:
            if cur and p.frame - cur[2] > SPELL_GAP_FRAMES:
                out.append(Spell(*cur))
                cur = None
            continue
        if cur and cur[0] is h and p.frame - cur[2] <= SPELL_GAP_FRAMES:
            cur[2], cur[3] = p.frame, cur[3] + 1
        else:
            if cur:
                out.append(Spell(*cur))
            cur = [h, p.frame, p.frame, 1]
    if cur:
        out.append(Spell(*cur))
    return [s for s in out if s.frames >= MIN_SPELL_FRAMES]


def attribute(t: Track, ball: BallPoint, tracks: list[Track]) -> str | None:
    """The track's player id (`h-t12`) when it plainly has the ball at this frame, else None: it is
    not a track the companion draws (no team, or too short), it is not seen in this frame, or
    another track (either side, or a referee) is within RIVAL_M of its distance from the ball."""
    if t.team is None or len(t.frames) < MIN_TRACK_FRAMES:
        return None
    q = t.at(ball.frame)
    if q is None:
        return None
    d = math.hypot(q[0] - ball.x, q[1] - ball.y)
    for o in tracks:
        r = o.at(ball.frame) if o is not t else None
        if r is not None and math.hypot(r[0] - ball.x, r[1] - ball.y) < d + RIVAL_M:
            return None
    return player_id(t)


def may_continue(a: Track, b: Track) -> bool:
    """Whether track b may be track a's player, picked up again after the tracker lost him."""
    gap = b.frames[0] - a.frames[-1]
    if not 0 < gap <= MAX_GAP_FRAMES:
        return False  # seen in the same frame: two players; or longer lost than the tracker waits
    return math.dist(a.xy[-1], b.xy[0]) <= REACH_MPS * gap / FPS + RIVAL_M


def _attacks_right(team: str) -> bool:
    return team == "home"  # the engine's convention, both halves (ninety/sim/engine.py)


def heads_for_goal(path: list[BallPoint], i: int, team: str) -> bool:
    """Whether the ball's ground track from path[i] over SHOT_LOOK_S, carried on in a line,
    crosses the goal line `team` attacks between the widened posts, from within SHOT_MAX_M. A
    lofted ball's ground track bends away from the camera as it rises (planned: its flight in 3D)."""
    p = path[i]
    if not 0.0 <= p.x <= PITCH_X:
        return False  # struck from behind a goal line (out of the net, say): toward the pitch, not a goal
    later = [q for q in path[i + 1:] if q.frame - p.frame <= SHOT_LOOK_S * FPS]
    if len(later) < 2:
        return False
    q = later[-1]
    dx, dy = q.x - p.x, q.y - p.y
    gx = PITCH_X if _attacks_right(team) else 0.0
    if dx == 0 or (gx - p.x) / dx <= 0 or abs(gx - p.x) > SHOT_MAX_M:
        return False
    y = p.y + dy * (gx - p.x) / dx
    return POST_Y[0] - SHOT_MARGIN_M <= y <= POST_Y[1] + SHOT_MARGIN_M


def _other(team: str) -> str:
    return "away" if team == "home" else "home"


def ends_at_goal(p: BallPoint, end: BallPoint, holder: Track | None, side: str) -> bool:
    """Amendment 3 (docs/eval/shot-outcomes-plan.md): the move from the strike at p ends at the goal
    `side` attacks: the line from p to its end crosses that goal line between the widened posts,
    from within SHOT_MAX_M, and the move ends with a keeper's spell inside that goal's penalty area
    (Law 1) or with the ball over that goal line."""
    if not 0.0 <= p.x <= PITCH_X:
        return False
    gx = PITCH_X if _attacks_right(side) else 0.0
    if abs(gx - p.x) > SHOT_MAX_M:
        return False
    y = outcomes.line_y(p, end, side)
    if y is None or not POST_Y[0] - SHOT_MARGIN_M <= y <= POST_Y[1] + SHOT_MARGIN_M:
        return False
    if holder is None:
        return outcomes.behind(end, side) > 0
    return holder.keeper and abs(end.x - gx) <= outcomes.PENALTY_AREA_X


def shot_side(path: list[BallPoint], i: int, team: str, end: BallPoint | None,
              holder: Track | None) -> str | None:
    """The side a strike at path[i] is a shot for, or None (amendment 3): the side attacking the goal
    it heads for (the engine's convention, the one `assign_teams` names sides by), tested toward
    both goals so a side read wrong does not make a shot a pass; by its first SHOT_LOOK_S
    (`heads_for_goal`), else by where its move ends (`ends_at_goal`)."""
    for side in (team, _other(team)):
        if heads_for_goal(path, i, side):
            return side
    if end is not None:
        for side in (team, _other(team)):
            if ends_at_goal(path[i], end, holder, side):
                return side
    return None


def out_of_play(path: list[BallPoint]) -> list[int]:
    """Indices into path where the ball has gone over a line: the first of OUT_FRAMES frames in a
    row with its centre beyond a line by more than BALL_R. A ball drawn over a player is not
    judged: placed on the ground it lands beyond him by its height times the camera's slope (a
    keeper's catch at 1.5 m from a 15 m gantry 50 m away lands 5 m back), so it says nothing
    about the line."""
    beyond = [not p.on_player and (p.x < -BALL_R or p.x > PITCH_X + BALL_R or p.y < -BALL_R
                                   or p.y > PITCH_Y + BALL_R)
              for p in path]
    out, i = [], 0
    while i < len(path):
        if beyond[i] and all(beyond[i:i + OUT_FRAMES]) and len(beyond[i:i + OUT_FRAMES]) == OUT_FRAMES:
            out.append(i)
            while i < len(path) and beyond[i]:
                i += 1
        else:
            i += 1
    return out


def _clip(v: float, hi: float) -> float:
    return round(min(max(v, 0.0), hi), 2)


def _speed_kmh(path: list[BallPoint], i: int) -> float | None:
    """The ball's speed just after the strike: the median of its frame-to-frame speeds over
    SHOT_LOOK_S, so the frame or two it may still lie at his feet (the spell's end can come up to
    SPEED_FRAMES early) does not pull it down."""
    p = path[i]
    seg = [p] + [q for q in path[i + 1:] if q.frame - p.frame <= SHOT_LOOK_S * FPS]
    steps = sorted(math.hypot(b.x - a.x, b.y - a.y) / ((b.frame - a.frame) / FPS)
                   for a, b in zip(seg, seg[1:], strict=False))
    if not steps:
        return None
    return round(steps[len(steps) // 2] * 3.6, 1)


def _credit_shot(events: list[dict], spell: Spell, team: str, who, p: BallPoint, event) -> None:
    """The strike a goal came from: the event already at that spell's end becomes a shot with outcome
    goal (a pass whose ground track bent wide), or a shot is added there."""
    for e in events:
        if e["frame"] == spell.last and e["team"] == team and e["type"] in ("pass", "shot"):
            for k in ("intended", "interceptor", "deflected_by", "receiver"):
                e.pop(k, None)
            e.update(type="shot", outcome="goal", receiver=None, end_x=None, end_y=None)
            return
    event("shot", spell.last, team, p.x, p.y, p.score, spell.track.side_confidence, player=who,
          outcome="goal")


def plausible(start: BallPoint, end: BallPoint, speed_kmh: float | None) -> bool:
    """Whether a pass from `start` to `end` is one the ball could have made. It must go further than
    the ball at a player's feet (CONTROL_M, GROUNDING P6), and a struck ball only slows (rolling and
    air drag), so it cannot cover the distance faster on average than it left the foot: its speed
    at the strike must be at least the distance over the time, less what each end's position may be
    wrong by (RIVAL_M, the players' measured position error) over that time."""
    d = math.hypot(end.x - start.x, end.y - start.y)
    if d <= CONTROL_M:
        return False
    dt = (end.frame - start.frame) / FPS
    if speed_kmh is None or dt <= 0:
        return True  # nothing to compare: the pass stands on its own evidence
    return speed_kmh / 3.6 >= (d - 2 * RIVAL_M) / dt


def possession_changes(sp: list[Spell], out_frames: list[int], cut_at: list[int],
                       join_breaks: bool = True) -> list[tuple[Spell, Spell]]:
    """(before, after) for each spell `after` whose side is not that of the last spell with a side
    before it, with the ball in play between them as far as the picture shows: no detected out of
    play and no cut between the two (docs/eval/possession-change-plan.md). With `join_breaks`, none
    where `after` may be `before`'s player in a new track (`may_continue`)."""
    out, last = [], None
    for s in sp:
        if s.track.team is None:
            continue
        a, last = last, s
        if a is None or s.track.team == a.track.team:
            continue
        if any(a.last < f < s.first for f in out_frames) or any(a.last <= c < s.first for c in cut_at):
            continue  # the ball was dead, or out of sight, between them: a restart is not told
        if join_breaks and may_continue(a.track, s.track):
            continue  # perhaps one player whose kit was read two ways
        out.append((a, s))
    return out


# Saves do not work from video yet: on the shot-outcome set's test split 2 of 49 were found
# (docs/eval/shot-outcomes/RESULT.md; a ball in the keeper's hands, placed on the ground, lands 2 to
# 7 m from him). So the live path does not say a shot was saved: a detected save is written as a
# shot with no outcome (lesson 258). `saves=True` keeps it, for measuring the rule only.
SAVES_AIR = False


def detect(rows: list[dict], join_breaks: bool = True,
           context_rows: list[dict] | None = None, saves: bool = SAVES_AIR) -> tuple[list[dict], dict]:
    """The detected events, and a summary of how they were found (teams, spells, counts).
    `join_breaks=False` turns off the one-player-in-two-tracks rule (`may_continue`), for measuring
    what it does (ninety/eval/attribution_derive.py); the live path always runs with it.
    `context_rows` are other views' observations of the same frames (the tactical camera's, fused):
    their players say where everyone stands at a kick-off (ninety/vision/outcomes.py); the ball is
    always the one in `rows`."""
    t_of = {r["frame"]: r["t"] for r in rows}
    tracks = track_players(rows)
    teams = sides.assign(tracks, rows)  # on the tactical views, kit and position combined (sides.py)
    path = ball_path(rows)
    index = {p.frame: i for i, p in enumerate(path)}
    sp = spells(path, tracks)
    outs = out_of_play(path)
    events: list[dict] = []

    def event(kind, frame, team, x, y, conf, side=None, **kw):
        e = {"id": "", "t": t_of[frame], "frame": frame, "type": kind, "team": team, "team_confidence": side,
             "player": None,
             "receiver": None, "x": _clip(x, PITCH_X), "y": _clip(y, PITCH_Y), "end_x": None, "end_y": None,
             "outcome": None, "ball_speed_kmh": None, "source": "vision", "confidence": round(conf, 3)}
        if kind == "pass":
            e |= {"intended": None, "interceptor": None, "deflected_by": None}
        e.update(kw)
        events.append(e)

    out_frames = [path[i].frame for i in outs]
    # The last frame before each cut: where the frame numbers jump.
    cut_at = [p["frame"] for p, q in zip(rows, rows[1:], strict=False) if q["frame"] != p["frame"] + 1]
    heights = outcomes.heights_by_frame(rows, path)
    others = outcomes.context_tracks(context_rows)
    strikes = [s.last for s in sp if s.track.team
               and any(heads_for_goal(path, index[s.last], side) for side in ("home", "away"))]
    goals: list[tuple[int, int, str]] = []  # (strike frame, last frame searched, team): no out of play there
    for a, b in zip(sp, sp[1:] + [None] if sp else [], strict=True):
        team = a.track.team
        if team is None:
            continue
        i = index[a.last]
        gone = next((f for f in out_frames if a.last < f and (b is None or f < b.first)), None)
        cut = next((c for c in cut_at if a.last <= c and (b is None or c < b.first)), None)
        if b is not None and b.track is a.track:
            continue  # he got it back himself: a touch, not a pass
        if join_breaks and b is not None and may_continue(a.track, b.track):
            continue  # perhaps him again in a new track: no pass can be told
        # Where his move ended: over a line first, else at the next spell.
        end = path[index[gone]] if gone is not None else path[index[b.first]] if b is not None else None
        holder = b.track if gone is None and b is not None else None
        shooter = shot_side(path, i, team, end, holder)
        shot = shooter is not None
        # The kit's side stands where the goal agrees with it; where it does not, the side is unsure.
        side_conf = a.track.side_confidence if shooter == team else None
        result = None
        if shot:
            # The net is searched up to the next cut or the next shot, past any spell (outcomes.judge).
            next_cut = next((c for c in cut_at if c >= a.last), None)
            bounds = [f for f in strikes if f > a.last] + ([next_cut + 1] if next_cut is not None else [])
            goal_stop = min(bounds, default=None)
            stop = b.first if b is not None else (cut + 1 if cut is not None else None)
            result = outcomes.judge(path, i, stop, goal_stop, shooter, tracks, heights,
                                    int(SHOT_LOOK_S * FPS), b.track if b is not None else None, gone, others,
                                    restart_stop=min((f for f in strikes if f > a.last), default=None),
                                    end_point=end)
        is_goal = result is not None and result.outcome == "goal"
        # A restart seen later (a kick-off, goal kick or corner) says where his ball went, even when
        # the picture lost it or cut away first (outcomes.first_restart).
        decided = is_goal or (result is not None and result.how.startswith("restart"))
        if b is None and gone is None and not decided:
            continue  # the clip ends with the ball still in play after him: nothing to judge yet
        if cut is not None and (gone is None or gone > cut) and not decided:
            continue  # the picture cut away before anything showed where his ball went
        conf = path[i].score * min(1.0, a.frames / (2 * MIN_SPELL_FRAMES))
        speed = _speed_kmh(path, i)
        who = attribute(a.track, path[i], tracks)
        if shot:
            # The shot's side is the end it goes toward; a track read on the other side names nobody,
            # never the wrong side (lesson 292, ninety/match/detected.attributed).
            who = who if a.track.team == shooter else None
            event("shot", a.last, shooter, path[i].x, path[i].y, conf, side_conf,
                  ball_speed_kmh=speed, player=who,
                  outcome=None if result.outcome == "on_target" and not saves else result.outcome)
            if is_goal:
                g = result.goal
                event("goal", g["frame"], shooter, g["x"], g["y"], g["confidence"], side_conf, player=who)
                goals.append((a.last, goal_stop if goal_stop is not None else rows[-1]["frame"] + 1, shooter))
            continue
        if gone is not None:
            g = path[index[gone]]
            if not plausible(path[i], g, speed):
                conf = 0.0  # held: no pass the ball's own path could have made (`plausible`)
            event("pass", a.last, team, path[i].x, path[i].y, conf, a.track.side_confidence, outcome="fail",
                  ball_speed_kmh=speed,
                  end_x=_clip(g.x, PITCH_X), end_y=_clip(g.y, PITCH_Y), player=who)
            continue
        j = index[b.first]
        mate = b.track.team == team
        next_who = attribute(b.track, path[j], tracks)
        if not plausible(path[i], path[j], speed):
            conf = 0.0  # held: no pass the ball's own path could have made (`plausible`)
        event("pass", a.last, team, path[i].x, path[i].y, conf, a.track.side_confidence, ball_speed_kmh=speed,
              outcome="success" if mate else "fail", player=who,
              receiver=next_who if mate else None, interceptor=None if mate else next_who,
              end_x=_clip(path[j].x, PITCH_X), end_y=_clip(path[j].y, PITCH_Y))
    for _, b in possession_changes(sp, out_frames, cut_at, join_breaks):
        j = index[b.first]
        event("possession_change", b.first, b.track.team, path[j].x, path[j].y,
              path[j].score * min(1.0, b.frames / (2 * MIN_SPELL_FRAMES)), b.track.side_confidence,
              player=attribute(b.track, path[j], tracks))
    for i in outs:
        f = path[i].frame
        if any(s < f < e and outcomes.behind(path[i], t) > 0 for s, e, t in goals):
            continue  # the ball in the net: a goal, not out of play (Law 9 against Law 10)
        # A goal no detected shot led to (a lofted strike's ground track bends wide of the posts): the
        # ball over a goal line and at rest in the net is a goal on its own evidence, for the side
        # attacking that goal (an own goal counts for it too, Law 10), up to the next cut or strike.
        scorer = "home" if path[i].x > PITCH_X else "away" if path[i].x < 0 else None
        if scorer is not None:
            nxt = [c + 1 for c in cut_at if c >= f] + [k for k in strikes if k > f]
            end = outcomes._index(path, min(nxt, default=None))
            line = outcomes.line_evidence(path[i:end], heights, scorer)
            restart = None
            if line is None:
                # Amendment 4: unseen in the net (a high ball lands beyond it), a kick-off first after it
                # is a goal (Law 8), as amendment 2 has it after a detected shot.
                restart = outcomes.first_restart(path, i, min((k for k in strikes if k > f), default=None),
                                                 scorer, others if others is not None else tracks)
                if restart is not None and restart[0] != "kickoff":
                    restart = None
            if line is not None or restart is not None:
                if line is not None:
                    score, k, y = line
                    g = path[i + k]
                    kick = outcomes.kickoff_evidence(path, i + k, others if others is not None else tracks,
                                                     scorer)
                    conf = round(1 - (1 - score) * (1 - kick), 3)
                else:
                    g, y = path[i], _clip(path[i].y, PITCH_Y)
                    conf = round(restart[2], 3)
                last = [s for s in sp if s.last < f and s.track.team == scorer]
                who = attribute(last[-1].track, path[index[last[-1].last]], tracks) if last else None
                if last:
                    _credit_shot(events, last[-1], scorer, who, path[index[last[-1].last]], event)
                event("goal", g.frame, scorer, outcomes.goal_line(scorer), y, conf,
                      last[-1].track.side_confidence if last else None, player=who)
                until = path[end].frame if end < len(path) else rows[-1]["frame"] + 1
                goals.append((f - 1, until, scorer))
                continue
        last = [s for s in sp if s.last < f and s.track.team]
        if not last:
            continue
        event("out_of_play", f, last[-1].track.team, path[i].x, path[i].y, path[i].score,
              last[-1].track.side_confidence)
    events.sort(key=lambda e: (e["frame"], e["type"]))
    for n, e in enumerate(events, start=1):
        e["id"] = f"v{n:05d}"
    summary = {
        "frames": len(rows),
        "frames_camera_ok": sum(1 for r in rows if r["camera"]["ok"]),
        "ball_frames": len(path),
        "tracks": len(tracks),
        "teams": teams,
        "spells": len(sp),
        "events": {k: sum(1 for e in events if e["type"] == k)
                   for k in ("pass", "shot", "goal", "out_of_play", "possession_change")},
        "shot_outcomes": {str(k): sum(1 for e in events if e["type"] == "shot" and e["outcome"] == k)
                          for k in (None, "goal", "on_target", "blocked", "off_target")},
        "named": {k: sum(1 for e in events if e.get(k)) for k in ("player", "receiver", "interceptor")},
    }
    return events, summary


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Detect passes, shots, out of play and possession changes.")
    ap.add_argument("observations", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--summary", type=Path, default=None, help="how the events were found, as JSON")
    ap.add_argument("--keep-saves", action="store_true",
                    help="write a detected save as one (for measuring the save rule; the live path does not)")
    a = ap.parse_args(argv)
    events, summary = detect(read_observations(a.observations), saves=a.keep_saves)
    a.out.write_text("".join(json.dumps(e) + "\n" for e in events), encoding="utf-8")
    if a.summary:
        a.summary.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary["events"] | {"out": str(a.out)}))


if __name__ == "__main__":
    main()
