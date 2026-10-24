"""Shot outcomes from video: what happened to each detected shot, from the ball's path after it.

The rules and the pass bar are fixed in docs/eval/shot-outcomes-plan.md before any measurement.
The outcome is written in the answer key's own words (docs/DATA_CONTRACT.md; the engine's
`close_shot`):

- `goal`: the ball goes over the goal line between the posts and under the bar, and comes to rest
  in the net (Law 10); a `goal` event is added, and a kick-off later in the clip adds evidence;
- `on_target`: a save. The shot was going in and the ball's path turns at the keeper before the
  line (he catches it, or it goes out for a corner, or it is parried back into play);
- `blocked`: the path turns at another defending player first;
- `off_target`: it goes over the goal line outside the goal, or the keeper touches a ball that
  was going wide;
- null: the clip ends, or cuts away, before anything shows where the ball went.

Reads only what the live path has: the ball's path (`track.ball_path`, the broadcast's ball), its
height where the flight fit gave one (`z` and `se` on the ball, ninety/vision/flight.py, PR #226),
and the players' tracks (the broadcast's, or the tactical views' when they are given). Nothing
reads ground truth. Every threshold is Law 1 geometry, a measured position error (E_X, E_Y, E_C:
docs/eval/shot-outcomes.json, validation clips only), or a constant the event rules already use.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from ninety.vision.track import FPS, BallPoint, Track, assign_teams, track_players

PITCH_X, PITCH_Y = 105.0, 68.0
CENTRE = (52.5, 34.0)
GOAL_HALF = 3.66  # Law 1: posts 7.32 m apart
CROSSBAR = 2.44  # Law 1
BALL_R = 0.11  # Law 2
NET_DEPTH_M = 2.0  # the net as the renderer draws it (ninety/sim/engine.py, NET_DEPTH_M)
PENALTY_AREA_X = 16.5  # Law 1
# The ball's position error, 95th percentile, measured on validation clips (shot-outcomes-plan.md):
# along the pitch (E_X) and across it (E_Y) within 25 m of a goal line, on the ground; and its
# distance error within 15 m of the centre spot (E_C). docs/eval/shot-outcomes.json: 607 frames near
# the goals, 1,010 near the centre, on 24 validation clips (the across error is larger: it is depth to
# the gantry).
E_X = 0.093
E_Y = 0.355
E_C = 0.688
# Rule 3: frames in the net running, the out-of-play rule's count (events.OUT_FRAMES).
IN_NET_FRAMES = 3
# Rule 4 (design): of the players with a side, this share in their own half at the kick-off.
OWN_HALF_SHARE = 0.9
MIN_SIDED = 4  # fewer players with a side than this, and only the ball is judged (design)
# Rule 5 (design): the ball's path turns where its direction changes by more than TURN_DEG, or its
# speed falls below SLOW_SHARE of what it was, between SPEED_FRAMES either side.
TURN_DEG = 30.0
SLOW_SHARE = 0.5
SPEED_FRAMES = 2  # as events.SPEED_FRAMES
CONTROL_M = 1.5  # events.CONTROL_M: the ball within this of a player is at his feet or hands
CARRY_MPS = 4.0  # events.CARRY_MPS
RIVAL_M = 1.26  # events.RIVAL_M: the players' measured position error
GAP_FRAMES = 6  # events.SPELL_GAP_FRAMES: path points this far apart are still one run


@dataclass(frozen=True)
class Outcome:
    outcome: str | None
    goal: dict | None = None  # the goal event's fields, for a goal
    how: str = ""  # which rule decided, for the summary


def attacks_right(team: str) -> bool:
    return team == "home"  # the engine's convention (events._attacks_right)


def goal_line(team: str) -> float:
    return PITCH_X if attacks_right(team) else 0.0


def behind(p: BallPoint, team: str) -> float:
    """How far the ball's centre is behind the goal line `team` attacks (negative: on the pitch)."""
    return (p.x - PITCH_X) if attacks_right(team) else -p.x


def _height_ok(h: tuple[float, float] | None) -> bool | None:
    """Rule 2's bar test: True or False where the height is known, None where it is not."""
    if h is None:
        return None
    z, se = h
    return z + 2 * se <= CROSSBAR - BALL_R


def in_mouth(p: BallPoint, h, team: str) -> tuple[bool, bool]:
    """(in the net's footprint, near a post): rules 1 to 3 for one frame."""
    d = behind(p, team)
    off = abs(p.y - CENTRE[1])
    inside = (BALL_R + E_X < d <= NET_DEPTH_M + E_X and off <= GOAL_HALF - BALL_R + E_Y
              and _height_ok(h) is not False)
    return inside, off >= GOAL_HALF - BALL_R - E_Y


def _runs(points: list[BallPoint], ok: list[bool]) -> list[list[int]]:
    """Index runs of consecutive ok points, a run broken by a gap over GAP_FRAMES."""
    runs, cur = [], []
    for k, (p, good) in enumerate(zip(points, ok, strict=True)):
        if good and cur and p.frame - points[cur[-1]].frame <= GAP_FRAMES:
            cur.append(k)
        elif good:
            if cur:
                runs.append(cur)
            cur = [k]
        else:
            if cur:
                runs.append(cur)
            cur = []
    if cur:
        runs.append(cur)
    return runs


def line_evidence(after: list[BallPoint], heights: dict, team: str) -> tuple[float, int, float] | None:
    """The first run of IN_NET_FRAMES frames in the net (rules 1 to 3): (score, the index of the
    frame the ball crossed the line on its way there, y where it rests), the score halved near a
    post and halved again where no frame's height is known; None if the ball never rests in the net."""
    flags = [in_mouth(p, heights.get(p.frame), team) for p in after]
    for run in _runs(after, [f[0] for f in flags]):
        if len(run) < IN_NET_FRAMES:
            continue
        score = sum(after[k].score for k in run) / len(run)
        if any(flags[k][1] for k in run):
            score /= 2
        if all(heights.get(after[k].frame) is None for k in run):
            score /= 2
        # The goal is when the whole ball crossed the line (Law 10), not when it came to rest: the
        # first frame of the unbroken stretch over the line that ends in the run.
        cross = run[0]
        while cross > 0 and behind(after[cross - 1], team) > BALL_R + E_X \
                and after[cross].frame - after[cross - 1].frame <= GAP_FRAMES:
            cross -= 1
        return score, cross, after[run[0]].y
    return None


def _velocity(path: list[BallPoint], k: int) -> tuple[float, float] | None:
    a, b = max(0, k - SPEED_FRAMES), min(len(path) - 1, k + SPEED_FRAMES)
    df = path[b].frame - path[a].frame
    if df <= 0 or df > 4 * SPEED_FRAMES:
        return None
    return (path[b].x - path[a].x) * FPS / df, (path[b].y - path[a].y) * FPS / df


def _side_velocity(path: list[BallPoint], k: int, before: bool) -> tuple[float, float] | None:
    a, b = (max(0, k - SPEED_FRAMES), k) if before else (k, min(len(path) - 1, k + SPEED_FRAMES))
    df = path[b].frame - path[a].frame
    if df <= 0 or df > 2 * SPEED_FRAMES:
        return None
    return (path[b].x - path[a].x) * FPS / df, (path[b].y - path[a].y) * FPS / df


def turns(path: list[BallPoint], k: int) -> bool:
    """Rule 5: the ball's path turns at path[k]."""
    va, vb = _side_velocity(path, k, True), _side_velocity(path, k, False)
    if va is None or vb is None:
        return False
    sa, sb = math.hypot(*va), math.hypot(*vb)
    if sa < CARRY_MPS:
        return False  # not a shot in flight here
    if sb < SLOW_SHARE * sa:
        return True
    cos = (va[0] * vb[0] + va[1] * vb[1]) / (sa * sb)
    return cos < math.cos(math.radians(TURN_DEG))


def goal_y(path: list[BallPoint], i: int, team: str, look: int) -> float | None:
    """Where the shot's opening line (path[i] to the last point within `look` frames) crosses the
    goal line, or None if it heads away from it."""
    p = path[i]
    later = [q for q in path[i + 1:] if q.frame - p.frame <= look]
    if not later:
        return None
    q = later[-1]
    gx = goal_line(team)
    dx = q.x - p.x
    if dx == 0 or (gx - p.x) / dx <= 0:
        return None
    return p.y + (q.y - p.y) * (gx - p.x) / dx


def keeper_of(tracks: list[Track], frame: int, defending: str | None) -> list[Track]:
    """The defending keeper candidates at a frame: tracks marked keeper (kit unlike either side,
    in a penalty area), and the defending side's player nearest its goal line inside its penalty
    area."""
    out = [t for t in tracks if t.keeper and t.at(frame) is not None]
    if defending is None:
        return out
    line = PITCH_X if not attacks_right(defending) else 0.0
    inside = [t for t in tracks if t.team == defending and t.at(frame) is not None
              and abs(t.at(frame)[0] - line) <= PENALTY_AREA_X]
    if inside:
        out.append(min(inside, key=lambda t: abs(t.at(frame)[0] - line)))
    return out


def toucher(tracks: list[Track], p: BallPoint, team: str) -> str | None:
    """Who the ball turned at: 'keeper', 'defender', 'mate' or None (nobody within CONTROL_M)."""
    defending = "away" if team == "home" else "home"
    near = [(math.dist(t.at(p.frame), (p.x, p.y)), t) for t in tracks
            if t.at(p.frame) is not None and math.dist(t.at(p.frame), (p.x, p.y)) <= CONTROL_M]
    if not near:
        return None
    keepers = {id(t) for t in keeper_of(tracks, p.frame, defending)}
    _, t = min(near, key=lambda n: n[0])
    if id(t) in keepers:
        return "keeper"
    if t.team == defending:
        return "defender"
    return "mate" if t.team == team else None


def kickoff_evidence(path: list[BallPoint], start: int, player_tracks: list[Track]) -> float:
    """Rule 4: the ball still on the centre spot on IN_NET_FRAMES frames running after path[start],
    with the players who have a side in their own halves; the mean ball score there, else 0."""
    after = path[start:]
    still = []
    for k, p in enumerate(after):
        v = _velocity(after, k)
        still.append(math.dist((p.x, p.y), CENTRE) <= E_C and (v is None or math.hypot(*v) < CARRY_MPS))
    for run in _runs(after, still):
        if len(run) < IN_NET_FRAMES:
            continue
        frames = [after[k].frame for k in run]
        if not own_halves(player_tracks, frames):
            continue
        return sum(after[k].score for k in run) / len(run)
    return 0.0


def own_halves(tracks: list[Track], frames: list[int]) -> bool:
    """Law 8: at the kick-off every player is in his own half. Home defends x = 0. True when too
    few players with a side are seen to judge (MIN_SIDED)."""
    sided = ok = 0
    for f in frames:
        for t in tracks:
            q = t.at(f)
            if q is None or t.team is None:
                continue
            sided += 1
            ok += q[0] <= CENTRE[0] + RIVAL_M if t.team == "home" else q[0] >= CENTRE[0] - RIVAL_M
    if sided < MIN_SIDED * len(frames):
        return True
    return ok >= OWN_HALF_SHARE * sided


def _index(path: list[BallPoint], frame: int | None) -> int:
    if frame is None:
        return len(path)
    return next((k for k, p in enumerate(path) if p.frame >= frame), len(path))


def judge(path: list[BallPoint], i: int, stop: int | None, goal_stop: int | None, team: str,
          tracks: list[Track], heights: dict, look: int, next_holder: Track | None,
          out_frame: int | None, player_tracks: list[Track] | None = None) -> Outcome:
    """One shot struck at path[i]. `stop` is the frame where its run ends (the next spell's first
    frame, or a cut), None at the clip's end; `next_holder` that spell's player; `out_frame` the
    frame the ball was seen out of play before `stop`, if any. The net is searched up to
    `goal_stop` (the next cut or shot), past any spell: a keeper standing by a ball at rest in his
    net reads as having it at his feet."""
    end = _index(path, stop)
    after = path[i + 1:_index(path, goal_stop)]
    gy = goal_y(path, i, team, look)
    on_target = gy is not None and abs(gy - CENTRE[1]) <= GOAL_HALF - BALL_R + E_Y
    # A touch first: the first turn of the path before it reaches the line.
    touched = None
    for k in range(i + 1, min(end, len(path))):
        if behind(path[k], team) > 0:
            break
        if turns(path, k):
            touched = toucher(tracks, path[k], team)
            if touched is not None and touched != "mate":
                break
            touched = None
    line = line_evidence(after, heights, team)
    if line is not None:
        score, k, y = line
        p = after[k]
        kick = kickoff_evidence(path, i + 1 + k, player_tracks if player_tracks is not None else tracks)
        conf = 1 - (1 - score) * (1 - kick)
        goal = {"frame": p.frame, "x": goal_line(team), "y": round(y, 2), "confidence": round(conf, 3),
                "line": round(score, 3), "kickoff": round(kick, 3)}
        return Outcome("goal", goal, "kickoff" if kick else "line")
    if touched == "keeper":
        return Outcome("on_target" if on_target else "off_target", how="keeper")
    if touched == "defender":
        return Outcome("blocked", how="defender")
    if out_frame is not None:
        return Outcome("off_target", how="out")
    if next_holder is not None and next_holder.team is not None and next_holder.team != team:
        return Outcome(None, how="taken")  # the other side has it, by no turn the path showed
    return Outcome(None, how="unseen")


def heights_by_frame(rows: list[dict], path: list[BallPoint]) -> dict:
    """{frame: (z, se)} for path points whose ball carries a fitted height (flight.py's `z`, `se`
    and a `flight` number: a ball the fit left on the ground has `flight` null and is not counted
    as known)."""
    out = {}
    by_frame = {r["frame"]: r for r in rows}
    for p in path:
        r = by_frame.get(p.frame)
        if r is None or p.u is None:
            continue
        for b in r["ball"]:
            cx, cy = (b["bbox"][0] + b["bbox"][2]) / 2, (b["bbox"][1] + b["bbox"][3]) / 2
            if (cx, cy) == (p.u, p.v) and b.get("flight") is not None and b.get("z") is not None:
                out[p.frame] = (float(b["z"]), float(b.get("se") or 0.0))
                break
    return out


def context_tracks(rows: list[dict] | None) -> list[Track] | None:
    """Players from other views (the tactical camera's fused rows), tracked and given sides."""
    if not rows:
        return None
    tracks = track_players(rows)
    assign_teams(tracks)
    return tracks
