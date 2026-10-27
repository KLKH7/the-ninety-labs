"""Possession share and territory by third, from the video alone (GROUNDING I17b, I18). (The phone's
momentum strip, by half and per five minutes, is ninety/match/territory.py.)

Possession share is time in possession (GROUNDING I17b), the broadcast standard beside Opta's pass
ratio (I17): of the seconds either team had the ball, each team's share. A team has the ball from
the moment one of its players has it at his feet (the detector's own possession: within 1.5 m and
moving with him, ninety/vision/events) until the other team does, while the ball is in play and for
at most HOLD_S after its last touch; a dead ball, a cut in the footage and a loose ball are nobody's.
The side is the player's track's, as vision reads it (a track the player-ID feed names is matched
on its own side, so the feed never changes it). It is always stated once MIN_POSSESSION_S of
possession were seen in the window, with its measured error beside it (docs/eval/possession-time.md).

Territory is where the ball was: of the seconds of footage shown (the tracked frames hold the ball
wherever the footage does, gaps within the tracker's own limit filled, ninety/vision/tracked_frames),
the share in each third of the pitch along the direction a team attacks (the thirds of Law 1's
length, as the possession layer cuts them). A ball within the players' position error of a third's
line could be on either side of it, so those seconds are counted apart and give the share bounds,
and the share is said as them ("between 25% and 31% of the footage shown"), like team distance,
"from the footage shown" (I16).
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence

from ninety.intel.possession import HOLD_S
from ninety.intel.scene import PITCH_X, PITCH_Y, POSITION_ERROR_M, TEAMS, minute_of
from ninety.vision.events import (
    BALL_R,
    CARRY_MPS,
    CONTROL_M,
    MIN_SPELL_FRAMES,
    SPEED_FRAMES,
    SPELL_GAP_FRAMES,
)

STEP_S = 1.0  # one ball position a second: the tracked frames' own smoothing (team_stats.STEP_S)
THIRD_M = PITCH_X / 3
EDGE_M = POSITION_ERROR_M
THIRDS = ("own", "middle", "final")
FPS = 25  # the tracked frames' rate (ninety/intel/scene)
# Pre-registered (docs/eval/possession-time-plan.md): a share is said once either team has had the
# ball this long in the window (design: about two minutes of play, at the half of it a team is
# seen with the ball); before it, "—".
MIN_POSSESSION_S = 60.0


def _control(frames: Sequence[Mapping]) -> list[tuple[int, float, str | None, bool]]:
    """Per tracked frame: its number, its time, the side of the player with the ball at his feet
    (nearest within CONTROL_M, moving with it within CARRY_MPS), or None, and whether the ball is
    in play (seen, and not beyond a line by more than its radius, Law 9)."""
    rows = sorted(frames, key=lambda f: int(f["frame"]))
    ball = {}
    for fr in rows:
        b = fr.get("ball")
        if b and b.get("x") is not None and b.get("y") is not None:
            ball[int(fr["frame"])] = (float(b["x"]), float(b["y"]))
    where = {int(fr["frame"]): {p["id"]: (float(p["x"]), float(p["y"]), p.get("team")) for p in fr["players"]}
             for fr in rows}

    def vel(pos: Mapping[int, tuple], n: int) -> tuple[float, float] | None:
        a, b = pos.get(n - SPEED_FRAMES), pos.get(n + SPEED_FRAMES)
        if a is None or b is None:
            return None
        dt = 2 * SPEED_FRAMES / FPS
        return (b[0] - a[0]) / dt, (b[1] - a[1]) / dt

    out = []
    for fr in rows:
        n, t = int(fr["frame"]), float(fr["t"])
        at = ball.get(n)
        if at is None:
            out.append((n, t, None, False))
            continue
        x, y = at
        live = -BALL_R <= x <= PITCH_X + BALL_R and -BALL_R <= y <= PITCH_Y + BALL_R
        best, best_d = None, CONTROL_M
        for pid, (px, py, team) in where[n].items():
            d = math.hypot(px - x, py - y)
            if d <= best_d and team in TEAMS:
                best, best_d = (pid, team), d
        side = None
        if best is not None and live:
            vb = vel(ball, n)
            vp = vel({k: where[k][best[0]] for k in (n - SPEED_FRAMES, n + SPEED_FRAMES)
                      if k in where and best[0] in where[k]}, n)
            if vb is None or vp is None or math.hypot(vb[0] - vp[0], vb[1] - vp[1]) <= CARRY_MPS:
                side = best[1]
        out.append((n, t, side, live))
    return out


def possession_rows(frames: Sequence[Mapping]) -> list[dict]:
    """One row per minute: the seconds each team had the ball, time in possession (GROUNDING I17b).

    A team gains possession when one of its players has the ball at his feet for MIN_SPELL_FRAMES
    frames running, and keeps it until the other team does, while the ball is in play and for no
    more than HOLD_S after its last touch: a pass or a dribble between its players stays its time;
    a ball loose longer, or contested, is nobody's. A dead ball (over a line) and a cut in the
    footage end it: the restart's taker gains it afresh. Dead and contested seconds count for
    neither side, so the two shares are of the seconds a team had the ball."""
    by: dict[int, dict] = {}
    team, last_touch, prev_n, run_side, run = None, None, None, None, 0
    for n, t, side, live in _control(frames):
        if prev_n is not None and n - prev_n > SPELL_GAP_FRAMES:
            team, run_side, run = None, None, 0  # a cut: nothing seen before it carries over
        prev_n = n
        if not live:
            team, run_side, run = None, None, 0
        if side is not None:
            run = run + 1 if side == run_side else 1
            run_side = side
            if run >= MIN_SPELL_FRAMES:
                team, last_touch = side, n
        if team is not None and last_touch is not None and (n - last_touch) / FPS > HOLD_S:
            team = None
        m = minute_of(t)
        r = by.setdefault(m, {"id": f"poss:m{m}", "kind": "possession_minute", "minute": m,
                              "frames": 0, **{k: 0 for k in TEAMS}})
        r["frames"] += 1
        if team is not None and live:
            r[team] += 1
    return [{**r, **{k: round(r[k] / FPS, 2) for k in (*TEAMS, "frames")}} for r in by.values()]


def possession(rows: Sequence[Mapping], minute_from: int, minute_to: int) -> dict[str, dict]:
    """Each team's share of the seconds either team had the ball in the window; no share before
    MIN_POSSESSION_S of them (too early to say), and then always one."""
    window = [r for r in rows if minute_from <= r["minute"] <= minute_to]
    secs = {k: sum(float(r[k]) for r in window) for k in TEAMS}
    total = sum(secs.values())
    if not window:
        return {}
    out = {}
    for team in TEAMS:
        stated = total >= MIN_POSSESSION_S
        out[team] = {
            "id": f"poss:{team}:m{minute_from}-{minute_to}",
            "kind": "possession",
            "metric": "possession_share",
            "team": team,
            "minute_from": minute_from,
            "minute_to": minute_to,
            "value": round(100 * secs[team] / total) if stated else None,
            "unit": "%",
            "seconds": round(secs[team], 1),
            "confident": stated,
            "method": "time",
            "also": [[round(total), "seconds"]],
        }
    if all(out[t]["value"] is not None for t in TEAMS) and out["home"]["value"] + out["away"]["value"] != 100:
        out["away"]["value"] = 100 - out["home"]["value"]  # rounded halves always make 100
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
