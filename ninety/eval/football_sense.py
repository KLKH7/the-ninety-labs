"""Football sense: count what a fan would call dumb play in a simulated match.

Outcome numbers (goals, shots, saves, pass completion) can look right while the play looks
wrong: passes into touch with nobody near the passer, a chaser running away from a loose ball,
ten players standing in a clump. This reads a match the simulator wrote (`frames.jsonl`,
`events.jsonl`, `meta.json`) and counts each kind of nonsense per 90 minutes, with timestamps
so a person can watch every one. It measures; it never changes the engine.

    uv run ninety-football-sense runs/seed7            # table, examples per type
    uv run ninety-football-sense runs/seed7 --json out.json

Every definition and threshold is registered in docs/GROUNDING.md (FS1 to FS9) and described in
docs/EVALUATION.md (Football sense). The logic is written here, independently of the engine
(`ninety/sim`): nothing is imported from it, so a check cannot inherit the engine's mistake.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from array import array
from dataclasses import dataclass, field
from pathlib import Path

# Law 1: the field and the penalty area.
PITCH_X, PITCH_Y = 105.0, 68.0
PENALTY_DEPTH, PENALTY_HALF_WIDTH = 16.5, 20.16

# FS2, FS7: an opponent within 3 m is inside the pressure zone in every direction (D2: the zone
# reaches about 9 m in front of a player and 3 m behind, Andrienko et al. 2017).
PRESSURE_M = 3.0
# FS1: the chaser is the nearest player and within this distance of the ball (task definition).
CHASER_M = 3.0
WINDOW_S = 0.5  # FS1: judged over half a second (task definition)
AWAY_M = 0.5  # FS1, design: 1 m/s away from the ball, a walk, well clear of a stop or a side-step
KICK_GRACE_S = 1.0  # FS1, design: a player who has just kicked the ball is leaving it, not chasing it
# FS1: a player already running away cannot stop at once. Peak braking is about 8.5 m/s2 (P2,
# Harper 2020), so the least he can still drift away is what that braking leaves; only movement
# beyond it is his choice.
BRAKE_MS2 = 8.5
PLAYABLE_Z = 2.0  # FS1, design: about head height; a ball above it flies over, it is not a loose ball

# FS3: a ball moving toward a keeper's goal that he would reach first.
RACE_SPEED_MS = 7.0  # design: everyone at one speed, under the 7.9 to 8.6 m/s match peaks (R6)
RACE_HORIZON_S = 3.0  # design: the ball's next 3 s, while it stays free
RACE_MARGIN_S = 0.3  # design: he gets there 0.3 s (about 2 m at a sprint) before any attacker
REACH_M = 1.0  # design: within a stride of the ball he can play it
KEEPER_ZONE_M = 30.0  # design: through balls into the last 30 m (the defending third is 35 m)
COME_OUT_S = 1.0  # design: time for a keeper to start coming
COME_OUT_M = 1.0  # design: under 1 m toward the ball in that second is staying home
GROUND_Z = 1.0  # design: the ball is on or near the ground (a keeper's dive or slide reaches it)

# FS4: still means under 0.5 m/s (task definition; Bradley et al. 2009 call 0 to 0.6 km/h,
# 0.17 m/s, standing, so this also counts the slowest shuffle as still).
STILL_MS = 0.5
# FS4, FS5: right after a restart players are still taking up positions (a corner, a free kick).
RESTART_GRACE_S = 3.0  # design

# FS5: the most compact published team (length 31 m x width 35 m, Rico-Gonzalez, GROUNDING
# R8) spreads its 10 outfield players over about 1,085 m2. A circle of 10 m radius is 314 m2,
# under a third of that. More than half of all 20 outfield players inside it is a clump that no
# published team shape allows.
BUNCH_RADIUS_M = 10.0
BUNCH_SHARE = 0.5
BUNCH_MIN_S = 1.0  # design: a clump that lasts, not a crossing of paths

# FS7: a pass is not forward when its forward part is under half its length (more than 60
# degrees off the line to goal; design). The open option is at least 5 m further forward than the
# ball, within 40 m of it (a long pass, about the 75th percentile of length; design), onside, with
# no opponent within PRESSURE_M of him and none within LANE_M of the line the ball would travel.
FORWARD_SHARE = 0.5
OPTION_AHEAD_M = 5.0
OPTION_RANGE_M = 40.0
LANE_M = 2.0  # design: about a stride and a reach either side of the ball's path

# FS8: a ball at rest nobody goes to.
REST_MS = 1.0  # design: rolling slower than a walk
IGNORED_S = 2.0  # design: at a sprint, about 7 m/s, any player covers 14 m in that time
ARRIVE_M = 1.0  # design: within a stride of it, someone has got there
CLOSING_M = 1.0  # design: nearest of each team gets at least this much closer in the time

# FS9: more than half of a team's outfield players inside their own penalty area while that team
# has the ball, for 2 s of open play (design; the shape a fan reads as camping in the box).
CAMP_SHARE = 0.5
CAMP_MIN_S = 2.0

STOPS = {"out_of_play", "goal", "foul", "offside"}  # the ball is dead from these ...
KICKS = {"pass", "shot"}  # ... until the restart is played
TOUCHES = {"pass", "shot", "tackle", "interception", "deflection", "possession_change", "foul", "offside"}


@dataclass
class Finding:
    type: str
    frame: int
    t: float
    player: str | None = None
    detail: str = ""

    def clock(self) -> str:
        return f"{int(self.t // 60):02d}:{self.t % 60:04.1f}"


@dataclass
class Match:
    fps: float
    t: array
    bx: array
    by: array
    bz: array
    bvx: array
    bvy: array
    possessor: list  # player index or -1
    ids: list[str]
    team: list[str]
    keeper: list[bool]
    px: list[array]  # per player, per frame; nan when not on the pitch
    py: list[array]
    pvx: list[array]
    pvy: list[array]
    events: list[dict]
    attack: dict[str, float] = field(default_factory=dict)  # +1 attacks x = 105, -1 attacks x = 0
    in_play: bytearray = field(default_factory=bytearray)
    restart: bytearray = field(default_factory=bytearray)  # 1 within RESTART_GRACE_S of a restart
    last_pass: list = field(default_factory=list)  # per frame, the last pass event at or before it
    loose: bytearray = field(default_factory=bytearray)  # 1 when the ball is free, not a pass in flight

    @property
    def frames(self) -> int:
        return len(self.t)

    def minutes(self) -> float:
        return self.frames / self.fps / 60.0

    def index(self, pid: str) -> int:
        return self.ids.index(pid)

    def speed(self, i: int, f: int) -> float:
        return math.hypot(self.pvx[i][f], self.pvy[i][f])

    def on(self, i: int, f: int) -> bool:
        return not math.isnan(self.px[i][f])

    def dist_ball(self, i: int, f: int, bx: float | None = None, by: float | None = None) -> float:
        bx = self.bx[f] if bx is None else bx
        by = self.by[f] if by is None else by
        return math.hypot(self.px[i][f] - bx, self.py[i][f] - by)

    def players(self, f: int, team: str | None = None, outfield: bool = False) -> list[int]:
        return [i for i in range(len(self.ids)) if self.on(i, f)
                and (team is None or self.team[i] == team) and not (outfield and self.keeper[i])]

    def frame_of(self, e: dict) -> int:
        f = e.get("frame")
        return int(f) if f is not None else int(round(e["t"] * self.fps))


def other(team: str) -> str:
    return "away" if team == "home" else "home"


def in_own_box(x: float, y: float, attack: float) -> bool:
    own_line = 0.0 if attack > 0 else PITCH_X
    return abs(x - own_line) <= PENALTY_DEPTH and abs(y - PITCH_Y / 2) <= PENALTY_HALF_WIDTH


def seg_dist(px: float, py: float, ax: float, ay: float, bx: float, by: float) -> float:
    dx, dy = bx - ax, by - ay
    n = dx * dx + dy * dy
    s = 0.0 if n == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / n))
    return math.hypot(px - ax - s * dx, py - ay - s * dy)


# --- loading -------------------------------------------------------------------------------------

def build(frames, events: list[dict], meta: dict) -> Match:
    """A Match from frame and event records (an iterable of frame dicts, as frames.jsonl holds)."""
    fps = float(meta.get("fps", 25))
    roster = {r["id"]: r for r in meta.get("roster", [])}
    ids: list[str] = []
    slot: dict[str, int] = {}
    cols: dict[str, list[array]] = {k: [] for k in ("x", "y", "vx", "vy")}
    t, bx, by, bz, bvx, bvy = (array("d") for _ in range(6))
    poss: list[int] = []
    team: list[str] = []
    keeper: list[bool] = []
    nan = float("nan")
    prev: dict[str, tuple[float, float]] = {}
    n = 0
    for fr in frames:
        b = fr["ball"]
        t.append(fr["t"])
        bx.append(b["x"])
        by.append(b["y"])
        bz.append(b.get("z", 0.0))
        bvx.append(b.get("vx", nan))
        bvy.append(b.get("vy", nan))
        for p in fr["players"]:
            pid = p["id"]
            if pid not in slot:
                slot[pid] = len(ids)
                ids.append(pid)
                team.append(p["team"])
                role = p.get("role") or roster.get(pid, {}).get("role")
                keeper.append(role == "GK")
                for k in cols:
                    cols[k].append(array("d", [nan]) * n)
            i = slot[pid]
            for k in cols:
                col = cols[k][i]
                while len(col) < n:
                    col.append(nan)
            cols["x"][i].append(p["x"])
            cols["y"][i].append(p["y"])
            if "vx" in p:
                vx, vy = p["vx"], p.get("vy", 0.0)
            elif pid in prev:  # a frame without velocities: the step from the last frame
                vx, vy = (p["x"] - prev[pid][0]) * fps, (p["y"] - prev[pid][1]) * fps
            else:
                vx = vy = 0.0
            prev[pid] = (p["x"], p["y"])
            cols["vx"][i].append(vx)
            cols["vy"][i].append(vy)
        n += 1
        for k in cols:
            for col in cols[k]:
                while len(col) < n:
                    col.append(nan)
        poss.append(slot.get(fr.get("possessor"), -1) if fr.get("possessor") else -1)
    # A ball without velocities: the step from the last frame.
    for f in range(n):
        if math.isnan(bvx[f]):
            g = max(f - 1, 0)
            bvx[f] = (bx[f] - bx[g]) * fps
            bvy[f] = (by[f] - by[g]) * fps
    m = Match(fps, t, bx, by, bz, bvx, bvy, poss, ids, team, keeper,
              cols["x"], cols["y"], cols["vx"], cols["vy"], sorted(events, key=lambda e: e["t"]))
    m.attack = attack_directions(m)
    m.in_play, m.restart = play_mask(m)
    m.last_pass = last_passes(m)
    m.loose = loose_mask(m)
    return m


def attack_directions(m: Match) -> dict[str, float]:
    """Which way each team attacks, from where its keeper stands (he guards the goal behind him)."""
    out = {}
    for team in ("home", "away"):
        xs = [m.px[i][f] for i in range(len(m.ids)) if m.keeper[i] and m.team[i] == team
              for f in range(0, m.frames, max(1, int(m.fps))) if m.on(i, f)]
        if xs:
            out[team] = 1.0 if sum(xs) / len(xs) < PITCH_X / 2 else -1.0
        else:
            out[team] = 1.0 if team == "home" else -1.0
    return out


def play_mask(m: Match) -> tuple[bytearray, bytearray]:
    """The ball is dead from a stoppage (and before the kick-off) until the restart is kicked."""
    live = bytearray(m.frames)
    fresh = bytearray(m.frames)
    alive, since = False, 0
    restarts: list[int] = []
    for e in m.events:
        f = min(m.frame_of(e), m.frames)
        if e["type"] in STOPS and alive:
            live[since:f] = b"\x01" * (f - since)
            alive = False
        elif e["type"] in KICKS and not alive:
            alive, since = True, f
            restarts.append(f)
    if alive:
        live[since:] = b"\x01" * (m.frames - since)
    grace = int(round(RESTART_GRACE_S * m.fps))
    for f in restarts:
        end = min(m.frames, f + grace)
        fresh[f:end] = b"\x01" * (end - f)
    return live, fresh


def load(path: Path) -> Match:
    meta = json.loads((path / "meta.json").read_text()) if (path / "meta.json").exists() else {}
    events = [json.loads(line) for line in open(path / "events.jsonl") if line.strip()]

    def frames():
        with open(path / "frames.jsonl") as fh:
            for line in fh:
                if line.strip():
                    yield json.loads(line)

    return build(frames(), events, meta)


# --- helpers -------------------------------------------------------------------------------------

def last_passes(m: Match) -> list[dict | None]:
    """For each frame, the last pass played at or before it."""
    out: list[dict | None] = [None] * m.frames
    passes = [(m.frame_of(e), e) for e in m.events if e["type"] == "pass"]
    k, cur = 0, None
    for f in range(m.frames):
        while k < len(passes) and passes[k][0] <= f:
            cur = passes[k][1]
            k += 1
        out[f] = cur
    return out


def loose_mask(m: Match) -> bytearray:
    """A loose ball: in play, nobody has it, and it is not on its way to anyone. It came off a player
    without being controlled (a deflection or tackle: the event schema's 'comes off a player and stays
    free'), or it is a failed pass nobody took. A pass or shot still in flight is not loose."""
    out = bytearray(m.frames)
    ons = [(m.frame_of(e), e) for e in m.events if e["type"] in TOUCHES | STOPS]
    k, free = 0, False
    for f in range(m.frames):
        while k < len(ons) and ons[k][0] <= f:
            e = ons[k][1]
            free = e["type"] in ("deflection", "tackle") or (
                e["type"] == "pass" and e.get("outcome") == "fail" and not e.get("interceptor"))
            k += 1
        out[f] = free and m.in_play[f] and m.possessor[f] < 0
    return out


def offside_position(m: Match, i: int, f: int) -> bool:
    """Law 11: in the opponents' half, nearer their goal line than the ball and the second-last opponent."""
    d = m.attack[m.team[i]]
    x = m.px[i][f]
    if (x - PITCH_X / 2) * d <= 0 or (x - m.bx[f]) * d <= 0:
        return False
    opp = sorted((m.px[j][f] * d for j in m.players(f, other(m.team[i]))), reverse=True)
    second_last = opp[1] if len(opp) > 1 else (PITCH_X if d > 0 else 0.0) * d
    return x * d > second_last


def spells(mask, min_len: int):
    """Runs of truthy entries at least min_len long, as (start, end) with end exclusive."""
    start = None
    for f, v in enumerate(mask):
        if v and start is None:
            start = f
        elif not v and start is not None:
            if f - start >= min_len:
                yield start, f
            start = None
    if start is not None and len(mask) - start >= min_len:
        yield start, len(mask)


# --- the checks ----------------------------------------------------------------------------------

def chaser_moves_away(m: Match) -> list[Finding]:
    """FS1: the nearest player to a loose ball, within 3 m of it, runs away from where it is going."""
    w = max(1, int(round(WINDOW_S * m.fps)))
    grace = int(round(KICK_GRACE_S * m.fps))
    kicked = {}  # frame -> player index of a kick at that frame
    for e in m.events:
        if e["type"] in KICKS and e.get("player") in m.ids:
            kicked[m.frame_of(e)] = m.index(e["player"])
    out: list[Finding] = []
    flagged: set[int] = set()  # players flagged in the current loose spell
    last_kick: tuple[int, int] = (-10**9, -1)
    for f in range(m.frames - w):
        if f in kicked:
            last_kick = (f, kicked[f])
        if not m.loose[f]:
            flagged.clear()
            continue
        if not all(m.loose[g] for g in range(f, f + w + 1)):
            continue
        if m.bz[f + w] > PLAYABLE_Z:
            continue
        near = m.players(f)
        if not near:
            continue
        i = min(near, key=lambda j: m.dist_ball(j, f))
        if i in flagged or m.dist_ball(i, f) > CHASER_M or not m.on(i, f + w):
            continue
        if i == last_kick[1] and f - last_kick[0] <= grace:
            continue
        g = f + w
        b1 = (m.bx[g], m.by[g])
        before = math.hypot(m.px[i][f] - b1[0], m.py[i][f] - b1[1])
        after = math.hypot(m.px[i][g] - b1[0], m.py[i][g] - b1[1])
        if after - before < AWAY_M + least_drift(m, i, f, b1, WINDOW_S):
            continue
        lp = m.last_pass[f]
        if lp and lp["team"] == m.team[i] and offside_position(m, i, f):
            continue  # Law 11: an offside player keeps away from the ball on purpose
        flagged.add(i)
        out.append(Finding("chaser_moves_away", f, m.t[f], m.ids[i],
                           f"{m.dist_ball(i, f):.1f} m from the ball, {after - before:.1f} m further "
                           f"from where it went in {WINDOW_S} s"))
    return out


def least_drift(m: Match, i: int, f: int, target: tuple[float, float], window: float) -> float:
    """How much further from a point a moving player must end up, braking as hard as he can in a
    straight line: what his momentum alone carries him away from it."""
    vx, vy = m.pvx[i][f], m.pvy[i][f]
    v = math.hypot(vx, vy)
    if v == 0:
        return 0.0
    s = v * window - BRAKE_MS2 * window * window / 2 if v > BRAKE_MS2 * window else v * v / (2 * BRAKE_MS2)
    x0, y0 = m.px[i][f], m.py[i][f]
    braked = math.hypot(x0 + vx / v * s - target[0], y0 + vy / v * s - target[1])
    return max(0.0, braked - math.hypot(x0 - target[0], y0 - target[1]))


def pass_out_unpressed(m: Match) -> list[Finding]:
    """FS2: a pass that leaves the field before anyone touches it, nobody within 3 m of the passer."""
    out = []
    for k, e in enumerate(m.events):
        if e["type"] != "pass" or e.get("player") not in m.ids:
            continue
        nxt = next((n for n in m.events[k + 1:] if n["type"] in TOUCHES | {"out_of_play", "goal"}), None)
        if nxt is None or nxt["type"] != "out_of_play":
            continue
        f0, f1 = m.frame_of(e), min(m.frame_of(nxt), m.frames - 1)
        if any(m.possessor[g] >= 0 for g in range(f0 + 1, f1)):
            continue  # somebody had it on the way
        i = m.index(e["player"])
        opp = [math.hypot(m.px[j][f0] - m.px[i][f0], m.py[j][f0] - m.py[i][f0])
               for j in m.players(f0, other(m.team[i]))]
        if opp and min(opp) <= PRESSURE_M:
            continue
        length = math.hypot((e.get("end_x") or e["x"]) - e["x"], (e.get("end_y") or e["y"]) - e["y"])
        line = "goal line" if 0 < nxt["y"] < PITCH_Y and not 0 < nxt["x"] < PITCH_X else "touchline"
        out.append(Finding("pass_out_unpressed", f0, e["t"], e["player"],
                           f"{length:.0f} m pass over the {line}, nearest opponent "
                           f"{min(opp) if opp else float('inf'):.1f} m"))
    return out


def arrival(m: Match, i: int, f: int, horizon: int) -> float:
    """When player i, running straight at RACE_SPEED_MS from where he is at frame f, could first meet
    the ball on the path it actually took (frames f to f + horizon); inf if never."""
    for g in range(f, min(f + horizon, m.frames)):
        need = max(0.0, math.hypot(m.px[i][f] - m.bx[g], m.py[i][f] - m.by[g]) - REACH_M) / RACE_SPEED_MS
        if m.t[g] - m.t[f] >= need:
            return m.t[g] - m.t[f]
    return math.inf


def keeper_stays_home(m: Match) -> list[Finding]:
    """FS3: an opponent's pass toward the keeper's goal that he would reach first, and he stays put."""
    w = int(round(COME_OUT_S * m.fps))
    horizon = int(round(RACE_HORIZON_S * m.fps))
    step = max(1, int(round(m.fps / 5)))
    out = []
    done: set[int] = set()  # passes already judged a defect
    for f in range(0, m.frames - w, step):
        lp = m.last_pass[f]
        if lp is None or id(lp) in done or m.possessor[f] >= 0 or not m.in_play[f] or m.bz[f] > GROUND_Z:
            continue
        defending = other(lp["team"])
        d = m.attack[defending]
        own_line = 0.0 if d > 0 else PITCH_X
        if abs(m.bx[f] - own_line) > KEEPER_ZONE_M or m.bvx[f] * d >= 0:
            continue  # not in the last 30 m, or not moving toward his goal
        gk = [i for i in m.players(f, defending) if m.keeper[i]]
        if not gk:
            continue
        k = gk[0]
        free = 0  # how long the ball stays free: the race is only over that stretch
        while f + free < m.frames and free < horizon and m.possessor[f + free] < 0 and m.in_play[f + free]:
            free += 1
        if m.dist_ball(k, f) <= REACH_M:
            continue
        tk = arrival(m, k, f, free)
        ta = min((arrival(m, j, f, free) for j in m.players(f, lp["team"])), default=math.inf)
        td = min((arrival(m, j, f, free) for j in m.players(f, defending, outfield=True)), default=math.inf)
        if math.isinf(ta) or math.isinf(tk) or tk + RACE_MARGIN_S > ta or td <= tk:
            continue  # no attacker in the race, not clearly his, or a defender gets there first
        if any(m.possessor[g] == k for g in range(f, min(f + free + 1, m.frames))):
            continue  # it came to him and he took it
        # Toward the ball's path: how much closer he got to where the ball was at his arrival time.
        g = min(f + int(round(tk * m.fps)), m.frames - 1)
        came = m.dist_ball(k, f, m.bx[g], m.by[g]) - m.dist_ball(k, f + w, m.bx[g], m.by[g])
        if came >= COME_OUT_M:
            continue
        done.add(id(lp))
        out.append(Finding("keeper_stays_home", f, m.t[f], m.ids[k],
                           f"keeper could meet it in {tk:.1f} s, first attacker {ta:.1f} s; "
                           f"came {came:.1f} m in {COME_OUT_S} s"))
    return out


def possession_team(m: Match, f: int, last: str | None) -> str | None:
    p = m.possessor[f]
    return m.team[p] if p >= 0 else last


def static_team(m: Match) -> tuple[list[int], list[int], int]:
    """FS4: how many outfield players stand still in open play, frame by frame: of the team with the
    ball and of the team without it."""
    with_ball, without = [0] * 11, [0] * 11
    frames = 0
    last = None
    for f in range(m.frames):
        last = possession_team(m, f, last)
        if not m.in_play[f] or m.restart[f] or last is None:
            continue
        for team, hist in ((last, with_ball), (other(last), without)):
            still = sum(1 for i in m.players(f, team, outfield=True) if m.speed(i, f) < STILL_MS)
            hist[min(still, 10)] += 1
        frames += 1
    return with_ball, without, frames


def bunching(m: Match) -> list[Finding]:
    """FS5: more than half of all outfield players within 10 m of the ball, for at least a second."""
    mask = []
    counts = []
    for f in range(m.frames):
        if not m.in_play[f] or m.restart[f]:
            mask.append(False)
            counts.append(0)
            continue
        field_players = m.players(f, outfield=True)
        near = sum(1 for i in field_players if m.dist_ball(i, f) <= BUNCH_RADIUS_M)
        counts.append(near)
        mask.append(bool(field_players) and near > BUNCH_SHARE * len(field_players))
    out = []
    for a, b in spells(mask, int(round(BUNCH_MIN_S * m.fps))):
        peak = max(range(a, b), key=lambda g: counts[g])
        still = sum(1 for i in m.players(peak, outfield=True)
                    if m.dist_ball(i, peak) <= BUNCH_RADIUS_M and m.speed(i, peak) < STILL_MS)
        out.append(Finding("bunching", a, m.t[a], None,
                           f"{counts[peak]} outfield players within {BUNCH_RADIUS_M:.0f} m of the ball "
                           f"({still} still) for {(b - a) / m.fps:.1f} s"))
    return out


def possessions(m: Match) -> int:
    return sum(1 for e in m.events if e["type"] in ("possession_change", "kickoff")) or 1


def own_box_passes(m: Match) -> list[Finding]:
    """FS6: passes that start and end inside the passer's own penalty area."""
    out = []
    restart_frames = {m.frame_of(e) for e in m.events if e["type"] == "set_piece"}
    for e in m.events:
        if e["type"] != "pass" or e.get("end_x") is None:
            continue
        d = m.attack.get(e["team"], 1.0)
        if in_own_box(e["x"], e["y"], d) and in_own_box(e["end_x"], e["end_y"], d):
            f = m.frame_of(e)
            restart = any(f - int(m.fps) <= r <= f for r in restart_frames) and not m.in_play[max(f - 1, 0)]
            out.append(Finding("own_box_pass", f, e["t"], e.get("player"),
                               ("restart, " if restart else "") + f"to {e.get('receiver') or 'nobody'}"))
    return out


def own_box_recycling(m: Match, passes: list[Finding]) -> list[Finding]:
    """FS6: possessions with three or more passes inside the team's own penalty area."""
    starts = sorted(m.frame_of(e) for e in m.events if e["type"] in ("possession_change", "kickoff"))
    groups: dict[int, list[Finding]] = {}
    for p in passes:
        s = max((x for x in starts if x <= p.frame), default=0)
        groups.setdefault(s, []).append(p)
    return [Finding("own_box_recycling", g[0].frame, g[0].t, g[0].player, f"{len(g)} passes in own box")
            for g in groups.values() if len(g) >= 3]


def camped_in_own_box(m: Match) -> list[Finding]:
    """FS9: the team with the ball keeps more than half its outfield players in its own penalty area."""
    mask = []
    count = []
    last = None
    for f in range(m.frames):
        last = possession_team(m, f, last)
        if not m.in_play[f] or m.restart[f] or last is None:
            mask.append(False)
            count.append(0)
            continue
        mates = m.players(f, last, outfield=True)
        inside = sum(1 for i in mates if in_own_box(m.px[i][f], m.py[i][f], m.attack[last]))
        count.append(inside)
        mask.append(bool(mates) and inside > CAMP_SHARE * len(mates))
    out = []
    for a, b in spells(mask, int(round(CAMP_MIN_S * m.fps))):
        team = possession_team(m, a, None) or (m.last_pass[a] or {}).get("team", "?")
        out.append(Finding("camped_in_own_box", a, m.t[a], None,
                           f"{team}: {max(count[a:b])} outfield players in their own box with the ball "
                           f"for {(b - a) / m.fps:.1f} s"))
    return out


def safe_pass_with_forward_option(m: Match) -> list[Finding]:
    """FS7: a pass that is not forward while a team-mate further forward is free and reachable."""
    out = []
    for e in m.events:
        if e["type"] != "pass" or e.get("end_x") is None or e.get("player") not in m.ids:
            continue
        f = m.frame_of(e)
        if f >= m.frames or not m.in_play[f]:
            continue
        team, d = e["team"], m.attack[e["team"]]
        dx, dy = e["end_x"] - e["x"], e["end_y"] - e["y"]
        length = math.hypot(dx, dy)
        if length == 0 or dx * d >= FORWARD_SHARE * length:
            continue
        passer = m.index(e["player"])
        chosen = {e.get("receiver"), e.get("intended")}
        bx, by = m.bx[f], m.by[f]
        opps = m.players(f, other(team))
        for j in m.players(f, team, outfield=True):
            if j == passer or m.ids[j] in chosen or (m.px[j][f] - bx) * d < OPTION_AHEAD_M:
                continue
            if math.hypot(m.px[j][f] - bx, m.py[j][f] - by) > OPTION_RANGE_M or offside_position(m, j, f):
                continue
            jx, jy = m.px[j][f], m.py[j][f]
            if any(math.hypot(m.px[o][f] - jx, m.py[o][f] - jy) <= PRESSURE_M for o in opps):
                continue
            if any(seg_dist(m.px[o][f], m.py[o][f], bx, by, jx, jy) <= LANE_M for o in opps):
                continue
            ahead = (jx - bx) * d
            out.append(Finding("safe_pass_forward_open", f, e["t"], e["player"],
                               f"played {'back' if dx * d < 0 else 'square'} to "
                               f"{e.get('receiver') or e.get('intended') or 'space'}; {m.ids[j]} free "
                               f"{ahead:.0f} m ahead"))
            break
    return out


def loose_ball_ignored(m: Match) -> list[Finding]:
    """FS8: a ball at rest in play that nobody owns, nobody reaches and nobody goes to, for 2 s."""
    mask = []
    for f in range(m.frames):
        ok = m.in_play[f] and m.possessor[f] < 0 and math.hypot(m.bvx[f], m.bvy[f]) < REST_MS
        mask.append(bool(ok) and all(m.dist_ball(i, f) > ARRIVE_M for i in m.players(f)))
    n = int(round(IGNORED_S * m.fps))
    out = []
    for a, b in spells(mask, n):
        g = a + n - 1
        closing = []
        for team in ("home", "away"):
            ps = m.players(a, team)
            if ps:
                d0 = min(m.dist_ball(i, a) for i in ps)
                d1 = min(m.dist_ball(i, g) for i in m.players(g, team))
                closing.append(d0 - d1)
        if all(c < CLOSING_M for c in closing):
            near = min(m.dist_ball(i, a) for i in m.players(a))
            out.append(Finding("loose_ball_ignored", a, m.t[a], None,
                               f"nearest player {near:.1f} m, ball loose for {(b - a) / m.fps:.1f} s"))
    return out


TYPES = {
    "chaser_moves_away": "FS1 chaser runs away from a loose ball",
    "pass_out_unpressed": "FS2 unpressed pass straight out of play",
    "keeper_stays_home": "FS3 keeper stays home for a ball he would win",
    "bunching": "FS5 more than half the outfield within 10 m of the ball",
    "own_box_pass": "FS6 pass from own box to own box",
    "own_box_recycling": "FS6 possession with 3+ own-box passes",
    "safe_pass_forward_open": "FS7 square or back pass with a free option ahead",
    "loose_ball_ignored": "FS8 loose ball at rest that nobody goes to",
    "camped_in_own_box": "FS9 team on the ball with most outfielders in own box",
}


def check(m: Match) -> dict:
    """Every check on one match: findings by type and the still-players distribution."""
    found: dict[str, list[Finding]] = {
        "chaser_moves_away": chaser_moves_away(m),
        "pass_out_unpressed": pass_out_unpressed(m),
        "keeper_stays_home": keeper_stays_home(m),
        "bunching": bunching(m),
    }
    box = own_box_passes(m)
    found["own_box_pass"] = box
    found["own_box_recycling"] = own_box_recycling(m, box)
    found["safe_pass_forward_open"] = safe_pass_with_forward_option(m)
    found["loose_ball_ignored"] = loose_ball_ignored(m)
    found["camped_in_own_box"] = camped_in_own_box(m)
    with_ball, without, n = static_team(m)
    return {"minutes": m.minutes(), "possessions": possessions(m),
            "passes": sum(1 for e in m.events if e["type"] == "pass"),
            "findings": found, "still_with_ball": with_ball, "still_without_ball": without, "still_frames": n}


def per90(count: int, minutes: float) -> float:
    return count * 90.0 / minutes if minutes else 0.0


def report(results: dict[str, dict], examples: int = 3) -> str:
    """A markdown table, per 90 minutes, over one or more matches, with examples to watch."""
    minutes = sum(r["minutes"] for r in results.values())
    poss = sum(r["possessions"] for r in results.values())
    passes = sum(r["passes"] for r in results.values())
    lines = [f"Football sense over {len(results)} match(es), {minutes:.0f} minutes, "
             f"{passes} passes, {poss} possessions.", "",
             "| Defect | Count | Per 90 | Examples (match, clock, player) |", "|---|---:|---:|---|"]
    for key, label in TYPES.items():
        n = sum(len(r["findings"][key]) for r in results.values())
        ex = []
        for name, r in results.items():
            for fd in r["findings"][key][:examples]:
                ex.append(f"{name} {fd.clock()} {fd.player or ''}".strip())
        lines.append(f"| {label} | {n} | {per90(n, minutes):.1f} | {'; '.join(ex[:examples * 2])} |")
    lines += ["", "FS4 static team (report only, no pass line): outfield players moving under "
              f"{STILL_MS} m/s in open play, as a share of open-play time.", "",
              "| Still players, at least | mean | " + " | ".join(str(k) for k in range(1, 11)) + " |",
              "|---|---:|" + "---:|" * 10]
    for key, label in (("still_with_ball", "team with the ball"), ("still_without_ball", "team without it")):
        hist = [sum(r[key][k] for r in results.values()) for k in range(11)]
        total = sum(hist) or 1
        mean = sum(k * h for k, h in enumerate(hist)) / total
        shares = " | ".join(f"{100 * sum(hist[k:]) / total:.0f}%" for k in range(1, 11))
        lines.append(f"| {label} | {mean:.1f} | {shares} |")
    return "\n".join(lines)


def to_json(results: dict[str, dict]) -> dict:
    return {name: {**{k: v for k, v in r.items() if k != "findings"},
                   "findings": {k: [vars(f) | {"clock": f.clock()} for f in fs]
                                for k, fs in r["findings"].items()}}
            for name, r in results.items()}


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(
        description="Count football-sense defects in simulated matches, per 90 minutes.")
    ap.add_argument("matches", nargs="+", type=Path, help="match directories written by ninety-sim")
    ap.add_argument("--examples", type=int, default=3, help="example timestamps per type and match")
    ap.add_argument("--json", type=Path, help="also write every finding to this JSON file")
    args = ap.parse_args(argv)
    results = {}
    for path in args.matches:
        if not (path / "frames.jsonl").exists():
            ap.error(f"{path}: no frames.jsonl")
        results[path.name] = check(load(path))
    print(report(results, args.examples))
    if args.json:
        args.json.write_text(json.dumps(to_json(results), indent=1))
        print(f"\nwrote {args.json}", file=sys.stderr)


if __name__ == "__main__":
    main()
