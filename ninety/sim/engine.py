"""Seeded football match engine.

Produces the ground-truth data The Ninety Labs is scored against: every event, plus every
player's and the ball's position at every frame, in pitch metres (x 0..105, y 0..68 from the near
touchline). Home attacks toward x=105 in the first half and the teams change ends at half-time.

The ball is always in one of four phases:

- carry: a player has it, dribbles, then passes, crosses or shoots;
- flight: a pass, cross, clearance or shot is travelling; teammates can control it, opponents can
  intercept or block it, the keeper can save it;
- loose: nobody controls it (a misplaced pass, a parry, a block, a tackle that knocks it free);
  the nearest players race for it;
- dead: it went out or the referee stopped play; players walk to their set-piece positions, the
  ball is carried to the spot, and the restart (throw-in, goal kick, corner, free kick, penalty,
  kickoff) is taken.

Players move with a speed cap and an acceleration limit, so nothing teleports, and runners,
pressers and chasers sprint above SPRINT_MS. Rates are tuned to published Premier League averages;
see docs/eval/sim-realism.md for the measured values and their sources.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

PITCH_X, PITCH_Y = 105.0, 68.0
FPS = 25
DT = 1.0 / FPS
HALF_S = 45 * 60

GOAL_HALF_W = 3.66  # half the goal mouth (7.32 m)
GOAL_H = 2.44
BOX_DEPTH, BOX_HALF_W = 16.5, 20.16
SPRINT_MS = 7.0  # 25.2 km/h, the usual sprint threshold
ACCEL = 4.5  # m/s^2
CONTROL_R = 1.2  # a player within this distance of a low ball can control it
CATCH_R = 1.5  # a keeper's reach
ARRIVE = 2 * ACCEL * 0.6  # players brake in time to stop at their target
ACCEL_STEP = ACCEL * DT
MAX_PULL = 0.8  # metres per frame the ball moves onto a player who just controlled it

# 4-3-3 anchors for a team attacking toward x=105, as (x, y) fractions of the pitch.
FORMATION = [
    ("GK", 0.05, 0.50),
    ("RB", 0.25, 0.15), ("RCB", 0.20, 0.38), ("LCB", 0.20, 0.62), ("LB", 0.25, 0.85),
    ("RCM", 0.42, 0.30), ("CM", 0.38, 0.50), ("LCM", 0.42, 0.70),
    ("RW", 0.62, 0.15), ("ST", 0.66, 0.50), ("LW", 0.62, 0.85),
]
RUN_RATE = {"RW": 0.10, "ST": 0.10, "LW": 0.10, "RCM": 0.04, "LCM": 0.04, "RB": 0.03, "LB": 0.03}
BOX_ROLES = ("ST", "RCB", "LCB", "CM", "LW", "RW", "LCM", "RCM")
PASS_KINDS = ("pass", "cross")


@dataclass
class Player:
    id: str
    team: str
    role: str
    fx: float
    fy: float
    top: float
    x: float = 0.0
    y: float = 0.0
    vx: float = 0.0
    vy: float = 0.0
    run_until: float = -1.0
    run_x: float = 0.0
    run_y: float = 0.0
    busy_until: float = -1.0


@dataclass
class Flight:
    kind: str  # "pass" | "cross" | "clearance" | "shot"
    sx: float
    sy: float
    ex: float
    ey: float
    t0: float
    dur: float
    peak: float
    speed: float  # m/s along the ground
    passer: str
    team: str
    target: str | None = None
    plan: str | None = None  # shots: goal | save | off_target | blocked
    block_u: float = 1.0
    end_z: float = 0.0
    ix: float | None = None  # where the passer meant it to go; the receiver reads the ball late
    iy: float | None = None


@dataclass
class Restart:
    kind: str  # kickoff | throw_in | goal_kick | corner | free_kick | penalty
    team: str
    x: float
    y: float
    taker: str
    ready_at: float
    layout: dict = field(default_factory=dict)


@dataclass
class Match:
    seed: int
    events: list[dict] = field(default_factory=list)
    frames: list[dict] = field(default_factory=list)
    score: dict = field(default_factory=lambda: {"home": 0, "away": 0})
    in_play_s: float = 0.0  # seconds the ball was in play


def clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def other(team: str) -> str:
    return "away" if team == "home" else "home"


class Engine:
    def __init__(self, seed: int):
        self.rng = random.Random(seed)
        self.match = Match(seed=seed)
        self.players: list[Player] = []
        for team in ("home", "away"):
            for n, (role, fx, fy) in enumerate(FORMATION):
                top = self.rng.uniform(7.0, 7.6) if role == "GK" else self.rng.uniform(8.2, 9.4)
                self.players.append(Player(f"{team[0]}{n + 1}", team, role, fx, fy, top))
        self.by_id = {p.id: p for p in self.players}
        self.squad = {t: [p for p in self.players if p.team == t] for t in ("home", "away")}
        self.gk = {t: next(p for p in self.squad[t] if p.role == "GK") for t in ("home", "away")}
        self.set_period(1)
        self.t = 0.0
        self.frame = 0
        self._eid = 0
        self.ball = [PITCH_X / 2, PITCH_Y / 2, 0.0]
        self.ball_v = [0.0, 0.0]
        self.phase = "dead"
        self.possessor: str | None = None
        self.poss_team: str | None = None
        self.last_touch = "home"
        self.flight: Flight | None = None
        self.restart: Restart | None = None
        self.pending: dict | None = None  # the pass whose outcome is not known yet
        self.hold_until = 0.0
        self.pressed: dict[str, float] = {}
        self.shot_ev: dict | None = None
        self.ignore: tuple[str | None, float] = (None, 0.0)  # a player who just touched a loose ball
        self.moved: str | None = None  # the carrier already moved this tick
        for p in self.players:
            p.x, p.y = self.kickoff_spot(p)

    # ---- geometry -----------------------------------------------------------

    def dir(self, team: str) -> float:
        """+1 when the team attacks toward x=105."""
        return self.dirs[team]

    def set_period(self, period: int) -> None:
        self.period = period
        sign = 1.0 if period == 1 else -1.0
        self.dirs = {"home": sign, "away": -sign}
        self.anchors = {}
        for p in self.players:
            if self.dirs[p.team] > 0:
                self.anchors[p.id] = (p.fx * PITCH_X, p.fy * PITCH_Y)
            else:
                self.anchors[p.id] = ((1 - p.fx) * PITCH_X, (1 - p.fy) * PITCH_Y)

    def goal_x(self, team: str) -> float:
        """x of the goal this team attacks."""
        return PITCH_X if self.dir(team) > 0 else 0.0

    def anchor(self, p: Player) -> tuple[float, float]:
        return self.anchors[p.id]

    def kickoff_spot(self, p: Player) -> tuple[float, float]:
        d = self.dir(p.team)
        own = 0.0 if d > 0 else PITCH_X
        y = p.fy * PITCH_Y if d > 0 else (1 - p.fy) * PITCH_Y
        return own + d * p.fx * 0.72 * PITCH_X, y

    def in_box(self, x: float, y: float, attacking: str) -> bool:
        gx = self.goal_x(attacking)
        return abs(gx - x) < BOX_DEPTH and abs(y - PITCH_Y / 2) < BOX_HALF_W

    def nearest(self, x: float, y: float, team: str, exclude: str | None = None,
                outfield: bool = False) -> Player:
        best, bd = None, 1e18
        for p in self.squad[team]:
            if p.id == exclude or (outfield and p.role == "GK"):
                continue
            d = (p.x - x) ** 2 + (p.y - y) ** 2
            if d < bd:
                best, bd = p, d
        return best

    # ---- events -------------------------------------------------------------

    def emit(self, type_: str, team: str, x: float, y: float, **kw) -> dict:
        self._eid += 1
        ev = {
            "id": f"e{self._eid:05d}", "t": round(self.t, 2), "frame": self.frame,
            "period": self.period, "type": type_, "team": team, "player": None, "receiver": None,
            "x": round(clamp(x, 0, PITCH_X), 2), "y": round(clamp(y, 0, PITCH_Y), 2),
            "end_x": None, "end_y": None, "outcome": None, "kind": None, "ball_speed_kmh": None,
            "source": "truth", "confidence": None,
        }
        ev.update(kw)
        self.match.events.append(ev)
        return ev

    def resolve_pending(self, outcome: str, x: float, y: float, receiver: str | None = None) -> None:
        if self.pending is None:
            return
        ev, self.pending = self.pending, None
        ev["outcome"] = outcome
        ev["receiver"] = receiver
        ev["end_x"], ev["end_y"] = round(clamp(x, 0, PITCH_X), 2), round(clamp(y, 0, PITCH_Y), 2)

    # ---- possession ---------------------------------------------------------

    def gain(self, pid: str, hold: tuple[float, float] = (1.0, 3.6)) -> None:
        p = self.by_id[pid]
        if self.pending is not None:
            passer = self.pending["player"]
            if p.team == self.pending["team"] and pid != passer:
                self.resolve_pending("success", p.x, p.y, receiver=pid)
            else:
                self.resolve_pending("fail", p.x, p.y)
        if self.poss_team is not None and p.team != self.poss_team:
            self.emit("possession_change", p.team, p.x, p.y, player=pid)
            self.pressed.clear()
        self.poss_team = p.team
        self.last_touch = p.team
        self.possessor = pid
        self.flight = None
        self.phase = "carry"
        lo, hi = (2.5, 6.0) if p.role == "GK" else hold
        self.hold_until = self.t + self.rng.uniform(lo, hi)

    def follow(self, c: Player) -> None:
        """The ball sits at the carrier's feet; just after a first touch it is pulled in, not snapped."""
        bx, by, bz = self.ball
        dx, dy = c.x - bx, c.y - by
        d = math.hypot(dx, dy)
        if d > MAX_PULL:
            self.ball = [bx + dx / d * MAX_PULL, by + dy / d * MAX_PULL, max(0.0, bz - 0.5)]
        else:
            self.ball = [c.x, c.y, 0.0]

    def go_loose(self, vx: float, vy: float, z: float = 0.0, toucher: str | None = None) -> None:
        self.ignore = (toucher, self.t + 0.4)
        self.phase = "loose"
        self.possessor = None
        self.flight = None
        self.ball_v = [vx, vy]
        self.ball[2] = z

    # ---- kicking ------------------------------------------------------------

    def kick(self, kind: str, p: Player, ex: float, ey: float, speed: float, peak: float,
             target: str | None = None, plan: str | None = None, end_z: float = 0.0) -> None:
        sx, sy = self.ball[0], self.ball[1]  # from the ball, which may still be settling at the feet
        dist = math.hypot(ex - sx, ey - sy)
        self.flight = Flight(kind, sx, sy, ex, ey, self.t, max(dist / speed, 0.25), peak, speed,
                             p.id, p.team, target, plan, end_z=end_z)
        self.phase = "flight"
        self.possessor = None
        self.last_touch = p.team

    def pass_to(self, p: Player, m: Player, kind: str = "pass", setp: str | None = None,
                loft: bool | None = None) -> None:
        """Play a pass toward where the mate will be, with an error that grows with length and pressure."""
        dist0 = math.hypot(m.x - p.x, m.y - p.y)
        lofted = dist0 > 32 if loft is None else loft
        speed = clamp(10 + dist0 * 0.35 + self.rng.uniform(-2, 2), 9, 26)
        dur = dist0 / speed
        ex, ey = m.x + m.vx * dur * 0.8, m.y + m.vy * dur * 0.8
        presser = self.nearest(p.x, p.y, other(p.team))
        pressured = math.hypot(presser.x - p.x, presser.y - p.y) < 3
        sd = 0.5 + 0.07 * dist0 + (1.5 if pressured else 0) + (1.0 if lofted else 0)
        ix, iy = ex, ey
        ex += self.rng.gauss(0, sd)
        ey += self.rng.gauss(0, sd)
        if setp is None and self.rng.random() < 0.05 + dist0 / 400 + (0.08 if pressured else 0):
            # misplaced: overhit or skewed, often out of play on the wings
            ux, uy = (ex - p.x) / (dist0 or 1), (ey - p.y) / (dist0 or 1)
            over = self.rng.uniform(3, 14)
            side = self.rng.gauss(0, 5)
            ex, ey = ex + ux * over - uy * side, ey + uy * over + ux * side
        peak = (2.0 + dist0 * 0.08) if lofted else 0.0
        if setp == "throw_in":
            peak = 1.2
        self.pending = self.emit(
            "pass", p.team, p.x, p.y, player=p.id, kind=setp or (kind if kind != "pass" else None),
            ball_speed_kmh=round(speed * 3.6 * (1.15 if lofted else 1.0), 1))
        self.kick(kind, p, ex, ey, speed, peak, target=m.id)
        self.flight.ix, self.flight.iy = ix, iy

    def shoot(self, p: Player, kind: str | None = None) -> None:
        team = p.team
        d = self.dir(team)
        gx = self.goal_x(team)
        cy = PITCH_Y / 2
        dist = math.hypot(gx - p.x, cy - p.y)
        speed = self.rng.uniform(55, 115) if kind != "header" else self.rng.uniform(35, 65)
        # Shots through a crowd get blocked: count defenders near the line.
        blocker, block_u, block_off = None, 1.0, 9.0
        if kind != "penalty":
            for q in self.squad[other(team)]:
                if q.role == "GK":
                    continue
                u, off = self.project(p.x, p.y, gx, cy, q.x, q.y)
                if 0.05 < u < 0.8 and off < 4 and (blocker is None or off < block_off):
                    blocker, block_u, block_off = q, u, off
        on_p, goal_p = 0.45, clamp(0.62 - dist / 40, 0.1, 0.55)
        if kind == "header":
            on_p, goal_p = 0.38, clamp(0.5 - dist / 30, 0.1, 0.4)
        elif kind == "free_kick":
            on_p, goal_p = 0.35, 0.22
        elif kind == "penalty":
            on_p, goal_p = 0.86, 0.9
        if blocker is not None and self.rng.random() < 0.6 - block_off * 0.1:
            plan = "blocked"
        elif self.rng.random() < on_p:
            plan = "goal" if self.rng.random() < goal_p else "save"
        else:
            plan = "off_target"
        if plan in ("goal", "save"):
            ey = cy + self.rng.uniform(-GOAL_HALF_W + 0.3, GOAL_HALF_W - 0.3)
            ez = self.rng.uniform(0.1, GOAL_H - 0.2)
        else:
            ey = cy + self.rng.choice([-1, 1]) * self.rng.uniform(0.0, 10.0)
            ez = self.rng.uniform(0.2, 1.5) if abs(ey - cy) > GOAL_HALF_W + 0.3 else self.rng.uniform(2.7, 5)
        ex = gx + d * (1.5 if plan == "goal" else 0.0)
        outcome = {"goal": "goal", "save": "on_target"}.get(plan, plan)
        self.pending = None
        self.shot_ev = self.emit(
            "shot", team, p.x, p.y, player=p.id, end_x=round(clamp(ex, 0, PITCH_X), 2),
            end_y=round(ey, 2), outcome=outcome, kind=kind, ball_speed_kmh=round(speed, 1))
        if plan == "blocked":
            self.shot_ev["end_x"] = round(p.x + (gx - p.x) * block_u, 2)
            self.shot_ev["end_y"] = round(p.y + (cy - p.y) * block_u, 2)
        self.kick("shot", p, ex, ey, speed / 3.6, 0.0, plan=plan, end_z=ez)
        self.flight.block_u = block_u
        self.flight.target = blocker.id if plan == "blocked" else None

    @staticmethod
    def project(sx: float, sy: float, ex: float, ey: float, px: float, py: float) -> tuple[float, float]:
        """Where along the segment s->e the point p falls (0..1), and how far off the line it is."""
        dx, dy = ex - sx, ey - sy
        L2 = dx * dx + dy * dy or 1e-9
        u = ((px - sx) * dx + (py - sy) * dy) / L2
        cx, cy = sx + dx * u, sy + dy * u
        return u, math.hypot(px - cx, py - cy)

    # ---- decisions ----------------------------------------------------------

    def decide(self, c: Player) -> None:
        team = c.team
        d = self.dir(team)
        gx = self.goal_x(team)
        cy = PITCH_Y / 2
        dist = math.hypot(gx - c.x, cy - c.y)
        if c.role != "GK" and dist < 32:
            p_shot = 0.21 if dist < 12 else 0.092 if dist < 18 else 0.029 if dist < 25 else 0.008
            p_shot *= 1 - min(0.85, abs(c.y - cy) / 28)
            if self.rng.random() < p_shot:
                self.shoot(c)
                return
        to_line = (gx - c.x) * d
        if c.role != "GK" and to_line < 26 and abs(c.y - cy) > 15 and self.rng.random() < 0.4:
            if self.cross(c):
                return
        own = PITCH_X - gx
        if c.role != "GK" and abs(c.x - own) < 25 and self.rng.random() < 0.5:
            presser = self.nearest(c.x, c.y, other(team))
            if math.hypot(presser.x - c.x, presser.y - c.y) < 4:
                self.clear(c, c.x, c.y)
                return
        mates = [m for m in self.squad[team] if m.id != c.id]
        maxlen = 65 if c.role in ("GK", "RCB", "LCB") else 45
        opp = other(team)
        weights = []
        for m in mates:
            md = math.hypot(m.x - c.x, m.y - c.y)
            if md < 5 or md > maxlen or (m.role == "GK" and (c.x - m.x) * d > 0 and md > 30):
                weights.append(0.0)
                continue
            fwd = (m.x - c.x) * d
            marker = self.nearest(m.x, m.y, opp)
            space = math.hypot(marker.x - m.x, marker.y - m.y)
            w = max(0.15, 1 + fwd / 20) * min(space, 8) * math.exp(-md / 8)
            if m.run_until > self.t:
                w *= 1.8
            if c.role == "GK" and md > 35:
                w *= 6  # keepers go long often
            weights.append(w)
        if not any(weights):
            self.hold_until = self.t + 0.5
            return
        target = self.rng.choices(mates, weights=weights)[0]
        self.pass_to(c, target)

    def cross(self, c: Player, setp: str | None = None) -> bool:
        team = c.team
        d = self.dir(team)
        gx = self.goal_x(team)
        cands = [m for m in self.squad[team] if m.id != c.id and m.role != "GK"
                 and 3 < (gx - m.x) * d < 18 and abs(m.y - PITCH_Y / 2) < 12]
        if not cands and setp is None:
            return False
        if cands:
            m = self.rng.choice(cands)
            ex, ey, tid = m.x + self.rng.gauss(0, 1.8), m.y + self.rng.gauss(0, 1.8), m.id
        else:
            ex, ey, tid = gx - d * self.rng.uniform(5, 12), PITCH_Y / 2 + self.rng.uniform(-6, 6), None
        speed = self.rng.uniform(18, 25)
        self.pending = self.emit("pass", team, c.x, c.y, player=c.id, kind=setp or "cross",
                                 ball_speed_kmh=round(speed * 3.6, 1))
        self.kick("cross", c, ex, ey, speed, self.rng.uniform(3.0, 5.0), target=tid)
        return True

    # ---- carry --------------------------------------------------------------

    def tick_carrier(self) -> None:
        c = self.by_id[self.possessor]
        team, opp = c.team, other(c.team)
        gx = self.goal_x(team)
        presser = self.nearest(c.x, c.y, opp)
        gap = math.hypot(presser.x - c.x, presser.y - c.y)

        # dribble toward goal, away from the presser
        if c.role == "GK":
            tx, ty, vmax = c.x, c.y, 0.5
        else:
            dx, dy = gx - c.x, PITCH_Y / 2 - c.y
            n = math.hypot(dx, dy) or 1
            dx, dy = dx / n, dy / n * 0.35
            if gap < 5 and gap > 1e-6:
                dx += (c.x - presser.x) / gap * 0.8
                dy += (c.y - presser.y) / gap * 0.8
            vmax = 5.5 if gap > 6 else (3.5 if gap > 3 else 1.8)
            if math.hypot(gx - c.x, PITCH_Y / 2 - c.y) < 28:
                vmax = min(vmax, 3.0)  # the final third is crowded
            tx, ty = c.x + dx * 5, c.y + dy * 5
        self.step(c, clamp(tx, 1, PITCH_X - 1), clamp(ty, 1, PITCH_Y - 1), vmax)
        self.moved = c.id
        # a carrier who took the ball on the line steps back onto the pitch
        c.x = clamp(c.x, min(0.3, c.x + 0.1), max(PITCH_X - 0.3, c.x - 0.1))
        c.y = clamp(c.y, min(0.3, c.y + 0.1), max(PITCH_Y - 0.3, c.y - 0.1))
        self.follow(c)

        if gap < 2.0 and self.t - self.pressed.get(opp, -99) > 8:
            self.pressed[opp] = self.t
            self.emit("pressure", opp, presser.x, presser.y, player=presser.id, receiver=c.id)
        if gap < 1.6 and self.t >= presser.busy_until and c.role != "GK" and self.rng.random() < 0.6 * DT:
            r = self.rng.random()
            foul_p = 0.02 if self.in_box(c.x, c.y, team) else 0.4
            if r < foul_p:
                self.emit("foul", opp, c.x, c.y, player=presser.id, receiver=c.id)
                self.award_foul(c)
                return
            if r < foul_p + 0.40:
                self.emit("tackle", opp, c.x, c.y, player=presser.id, receiver=c.id, outcome="success")
                self.last_touch = opp
                if self.rng.random() < 0.6:
                    self.gain(presser.id)
                else:
                    a = self.rng.uniform(0, 2 * math.pi)
                    if min(c.y, PITCH_Y - c.y) < 12 and self.rng.random() < 0.5:
                        a = -math.pi / 2 if c.y < PITCH_Y / 2 else math.pi / 2  # knocked toward the line
                    s = self.rng.uniform(3, 8)
                    self.go_loose(math.cos(a) * s, math.sin(a) * s, toucher=presser.id)
                return
            self.emit("tackle", opp, c.x, c.y, player=presser.id, receiver=c.id, outcome="fail")
            presser.busy_until = self.t + 1.5
        if gap < 3:
            self.hold_until = min(self.hold_until, self.t + self.rng.uniform(0.3, 1.2))
        if self.t >= self.hold_until:
            self.decide(c)

    # ---- flight -------------------------------------------------------------

    def tick_flight(self) -> None:
        f = self.flight
        u = (self.t - f.t0) / f.dur
        if f.kind == "shot" and f.plan == "blocked" and u >= f.block_u:
            u = f.block_u
            self.ball = [f.sx + (f.ex - f.sx) * u, f.sy + (f.ey - f.sy) * u, 0.3]
            self.last_touch = other(f.team)
            a = math.atan2(f.ey - f.sy, f.ex - f.sx) + math.pi + self.rng.uniform(-1.4, 1.4)
            if self.rng.random() < 0.35:  # deflected behind
                a = math.atan2(f.ey - f.sy, f.ex - f.sx) + self.rng.uniform(-0.6, 0.6)
            s = self.rng.uniform(4, 12)
            self.go_loose(math.cos(a) * s, math.sin(a) * s, toucher=f.target)
            return
        uu = min(u, 1.0)
        x = f.sx + (f.ex - f.sx) * uu
        y = f.sy + (f.ey - f.sy) * uu
        z = f.peak * 4 * uu * (1 - uu) + f.end_z * uu
        self.ball = [x, y, z]

        if f.kind == "shot":
            if u < 1:
                return
            self.end_shot(f)
            return

        # A low ball can be controlled by a teammate or cut out by an opponent on the way.
        if z < 1.8 and self.t - f.t0 > 0.3:
            for p in self.players:
                if p.id == f.passer:
                    continue
                if abs(p.x - x) > CONTROL_R or abs(p.y - y) > CONTROL_R:
                    continue
                if math.hypot(p.x - x, p.y - y) > CONTROL_R:
                    continue
                if p.team != f.team:
                    if self.rng.random() < (0.05 if f.kind != "cross" else 0.4):
                        if f.kind in PASS_KINDS:
                            self.emit("interception", p.team, x, y, player=p.id)
                            self.resolve_pending("fail", x, y, receiver=p.id)
                        self.gain(p.id)
                        return
                elif uu > 0.5 or p.id == f.target:
                    self.gain(p.id)
                    return
            if f.target and uu > 0.7:  # the receiver stretches for it
                m = self.by_id[f.target]
                if math.hypot(m.x - x, m.y - y) < 1.6:
                    self.gain(m.id)
                    return
        if self.out_of_play(x, y):
            return
        if f.kind == "cross" and uu > 0.8 and z < 3.2:
            if self.contest(f, x, y):
                return
        if u >= 1:
            d = math.hypot(f.ex - f.sx, f.ey - f.sy) or 1
            k = 0.3 if f.peak < 1 else 0.2
            self.go_loose((f.ex - f.sx) / d * f.speed * k, (f.ey - f.sy) / d * f.speed * k, z)

    def contest(self, f: Flight, x: float, y: float) -> bool:
        """A cross arrives: the keeper claims it, an attacker heads at goal, or a defender clears."""
        att = f.team
        dfn = other(att)
        gk = self.gk[dfn]
        if self.in_box(x, y, att) and math.hypot(gk.x - x, gk.y - y) < 2.5 and self.rng.random() < 0.6:
            self.gain(gk.id)
            return True
        near = [p for p in self.players if p.role != "GK" and math.hypot(p.x - x, p.y - y) < 1.8]
        if not near:
            return False
        w = [1.0 if p.team == att else 1.4 for p in near]
        win = self.rng.choices(near, weights=w)[0]
        if win.team == att:
            self.resolve_pending("success", x, y, receiver=win.id)
            dist = math.hypot(self.goal_x(att) - x, PITCH_Y / 2 - y)
            if dist < 15 and self.rng.random() < 0.45:
                self.shoot_from(win, x, y, "header")
            else:
                self.knock_on(win, x, y)
            return True
        self.resolve_pending("fail", x, y)
        self.clear(win, x, y)
        return True

    def shoot_from(self, p: Player, x: float, y: float, kind: str) -> None:
        px, py = p.x, p.y
        p.x, p.y = x, y  # the shot starts from the ball, which is within reach
        self.shoot(p, kind)
        p.x, p.y = px, py

    def knock_on(self, p: Player, x: float, y: float) -> None:
        self.last_touch = p.team
        self.ball = [x, y, self.ball[2]]
        a = self.rng.uniform(0, 2 * math.pi)
        s = self.rng.uniform(3, 7)
        self.go_loose(math.cos(a) * s, math.sin(a) * s, self.ball[2], toucher=p.id)

    def clear(self, p: Player, x: float, y: float) -> None:
        d = self.dir(p.team)
        L = self.rng.uniform(18, 38)
        a = self.rng.uniform(-1.3, 1.3)
        ex, ey = x + d * L * math.cos(a), y + L * math.sin(a)
        if self.rng.random() < 0.2:  # hooked behind for a corner
            ex = (0.0 if d > 0 else PITCH_X) - d * 1.0
            ey = y + self.rng.choice([-1, 1]) * self.rng.uniform(3, 15)
            L = math.hypot(ex - x, ey - y)
        self.emit("clearance", p.team, x, y, player=p.id, end_x=round(clamp(ex, 0, PITCH_X), 2),
                  end_y=round(clamp(ey, 0, PITCH_Y), 2))
        self.flight = Flight("clearance", x, y, ex, ey, self.t, max(L / 20, 0.4), self.rng.uniform(4, 10), 20,
                             p.id, p.team)
        self.phase = "flight"
        self.possessor = None
        self.last_touch = p.team

    def end_shot(self, f: Flight) -> None:
        att, dfn = f.team, other(f.team)
        d = self.dir(att)
        gx = self.goal_x(att)
        if f.plan == "goal":
            self.match.score[att] += 1
            self.emit("goal", att, f.ex, f.ey, player=f.passer, ball_speed_kmh=round(f.speed * 3.6, 1))
            self.ball = [f.ex, f.ey, 0.0]
            self.set_restart("kickoff", dfn, PITCH_X / 2, PITCH_Y / 2, self.rng.uniform(55, 75))
            return
        if f.plan == "off_target":
            self.out_of_play(gx + d * 0.05, f.ey)  # just over the line
            return
        # save: the keeper catches it or parries it
        gk = self.gk[dfn]
        catch = f.speed * 3.6 < 95 and f.end_z < 1.9 and self.rng.random() < 0.55
        if catch and math.hypot(gk.x - f.ex, gk.y - f.ey) < CATCH_R + 1.0:
            self.emit("save", dfn, f.ex, f.ey, player=gk.id, outcome="success", kind="catch")
            self.gain(gk.id)
            return
        self.emit("save", dfn, f.ex, f.ey, player=gk.id, outcome="success", kind="parry")
        self.last_touch = dfn
        self.ball = [gx - d * 0.3, f.ey, f.end_z]
        if self.rng.random() < 0.45:  # turned behind for a corner
            self.go_loose(d * self.rng.uniform(2, 5), self.rng.uniform(-3, 3), f.end_z, toucher=gk.id)
        else:
            self.go_loose(-d * self.rng.uniform(4, 10), self.rng.uniform(-7, 7), f.end_z, toucher=gk.id)

    # ---- loose --------------------------------------------------------------

    def tick_loose(self) -> None:
        vx, vy = self.ball_v
        s = math.hypot(vx, vy)
        if s > 0:
            ns = max(0.0, s - 3.5 * DT)
            vx, vy = vx / s * ns, vy / s * ns
            self.ball_v = [vx, vy]
        x, y = self.ball[0] + vx * DT, self.ball[1] + vy * DT
        z = max(0.0, self.ball[2] - 4 * DT)
        self.ball = [x, y, z]
        if self.out_of_play(x, y):
            return
        if z > 1.8:
            return
        best, bd = None, 0.0
        skip = self.ignore[0] if self.t < self.ignore[1] else None
        for p in self.players:
            if p.id == skip or abs(p.x - x) > CATCH_R or abs(p.y - y) > CATCH_R:
                continue
            reach = CATCH_R if p.role == "GK" and self.in_box(x, y, other(p.team)) else CONTROL_R
            margin = math.hypot(p.x - x, p.y - y) - reach
            if margin < bd:
                best, bd = p, margin
        if best is not None:
            self.gain(best.id)

    # ---- out of play and restarts -------------------------------------------

    def out_of_play(self, x: float, y: float) -> bool:
        if 0 <= x <= PITCH_X and 0 <= y <= PITCH_Y:
            return False
        last = self.last_touch
        ox, oy = clamp(x, 0, PITCH_X), clamp(y, 0, PITCH_Y)
        self.resolve_pending("fail", ox, oy)
        self.emit("out_of_play", last, ox, oy)
        self.ball = [clamp(x, -2.5, PITCH_X + 2.5), clamp(y, -2.5, PITCH_Y + 2.5), 0.0]
        if y < 0 or y > PITCH_Y:
            team = other(last)
            ty = 0.0 if y < 0 else PITCH_Y
            self.set_restart("throw_in", team, clamp(ox, 1, PITCH_X - 1), ty, self.rng.uniform(12, 22))
            return True
        end_team = "home" if (x < 0) == (self.dir("home") > 0) else "away"  # whose goal line
        if last != end_team:
            gx = 0.0 if x < 0 else PITCH_X
            d = 1.0 if x < 0 else -1.0
            gy = PITCH_Y / 2 + self.rng.uniform(-8, 8)
            self.set_restart("goal_kick", end_team, gx + d * 5.5, gy, self.rng.uniform(22, 34))
        else:
            cx = 0.5 if x < 0 else PITCH_X - 0.5
            cy = 0.5 if y < PITCH_Y / 2 else PITCH_Y - 0.5
            self.set_restart("corner", other(end_team), cx, cy, self.rng.uniform(30, 45))
        return True

    def award_foul(self, fouled: Player) -> None:
        team = fouled.team
        x, y = fouled.x, fouled.y
        if self.in_box(x, y, team):
            gx = self.goal_x(team)
            self.set_restart("penalty", team, gx - self.dir(team) * 11, PITCH_Y / 2, self.rng.uniform(35, 50))
            return
        dist = math.hypot(self.goal_x(team) - x, PITCH_Y / 2 - y)
        wait = self.rng.uniform(30, 45) if dist < 35 else self.rng.uniform(14, 26)
        self.set_restart("free_kick", team, x, y, wait)

    def set_restart(self, kind: str, team: str, x: float, y: float, wait: float) -> None:
        self.pending = None
        self.possessor = None
        self.flight = None
        self.phase = "dead"
        self.ball_v = [0.0, 0.0]
        squad = self.squad[team]
        if kind == "kickoff":
            taker = next(p for p in squad if p.role == "ST")
        elif kind == "goal_kick":
            taker = self.gk[team]
        elif kind == "penalty":
            taker = next(p for p in squad if p.role == "ST")
        elif kind == "corner":
            taker = min((p for p in squad if p.role in ("RW", "LW", "RCM", "LCM")),
                        key=lambda p: math.hypot(p.x - x, p.y - y))
        else:
            taker = self.nearest(x, y, team, outfield=True)
        r = Restart(kind, team, x, y, taker.id, self.t + wait)
        r.layout = self.layout(r)
        self.restart = r

    def layout(self, r: Restart) -> dict:
        """Where every player goes for the restart. Players not listed keep their shape."""
        lay: dict[str, tuple[float, float]] = {}
        team, opp = r.team, other(r.team)
        d = self.dir(team)
        gx = self.goal_x(team)
        cy = PITCH_Y / 2
        taker = self.by_id[r.taker]
        side = -1 if r.y < cy else 1
        lay[taker.id] = (r.x - d * 0.4 if r.kind != "throw_in" else r.x,
                         r.y if r.kind != "throw_in" else r.y + side * 0.3)
        if r.kind == "kickoff":
            for p in self.players:
                if p.id != taker.id:
                    lay[p.id] = self.kickoff_spot(p)
            mate = next(p for p in self.squad[team] if p.role == "CM")
            lay[mate.id] = (PITCH_X / 2 - self.dir(team) * 1.5, cy + 3)
            return lay
        if r.kind == "penalty":
            for p in (q for q in self.players if q.id != taker.id and q.role != "GK"):
                lay[p.id] = (gx - d * self.rng.uniform(18, 24), cy + self.rng.uniform(-18, 18))
            lay[self.gk[opp].id] = (gx - d * 0.3, cy)
            return lay
        dist = math.hypot(gx - r.x, cy - r.y)
        if r.kind == "corner" or (r.kind == "free_kick" and dist < 35):
            spots = [(6, -3), (5, 3), (9, 0), (11, -5), (11, 5), (13, 0), (8, -7), (8, 7)]
            attackers = [p for p in self.squad[team] if p.id != taker.id and p.role in BOX_ROLES][:6]
            for p, (u, v) in zip(attackers, self.rng.sample(spots, len(attackers)), strict=True):
                lay[p.id] = (gx - d * (u + self.rng.uniform(-1, 1)), cy + v + self.rng.uniform(-1, 1))
            edge = [p for p in self.squad[team] if p.id != taker.id and p.role != "GK" and p.id not in lay]
            for i, p in enumerate(edge):
                lay[p.id] = (gx - d * (22 if i == 0 else 45), cy + self.rng.uniform(-15, 15))
            defenders = [p for p in self.squad[opp] if p.role not in ("GK", "ST")]
            if r.kind == "free_kick":  # a wall of three, 9.15 m toward goal
                wx, wy = gx - r.x, cy - r.y
                n = math.hypot(wx, wy) or 1
                for i, p in enumerate(defenders[:3]):
                    lay[p.id] = (r.x + wx / n * 9.15 - wy / n * (i - 1) * 0.6,
                                 r.y + wy / n * 9.15 + wx / n * (i - 1) * 0.6)
                defenders = defenders[3:]
            for p, a in zip(defenders, attackers, strict=False):
                ax, ay = lay[a.id]
                lay[p.id] = (ax + d * 0.8, ay + self.rng.uniform(-0.6, 0.6))
            for i, p in enumerate(defenders[len(attackers):]):
                lay[p.id] = (gx - d * (4 + 4 * i), cy + (i - 1) * 4)
            lay[self.gk[opp].id] = (gx - d * 0.6, cy + side * 0.5)
            st = next(p for p in self.squad[opp] if p.role == "ST")
            lay[st.id] = (gx - d * 38, cy)
        return lay

    def tick_dead(self) -> None:
        r = self.restart
        bx, by = self.ball[0], self.ball[1]
        dx, dy = r.x - bx, r.y - by
        dd = math.hypot(dx, dy)
        step = min(dd, 7.0 * DT)
        if dd > 1e-6:
            bx, by = bx + dx / dd * step, by + dy / dd * step
        self.ball = [bx, by, max(0.0, self.ball[2] - 4 * DT)]
        taker = self.by_id[r.taker]
        if self.t < r.ready_at or dd > 0.05 or math.hypot(taker.x - r.x, taker.y - r.y) > 1.0:
            if self.t < r.ready_at + 20:
                return
        self.ball = [r.x, r.y, 0.0]
        self.execute(r)

    def execute(self, r: Restart) -> None:
        self.restart = None
        taker = self.by_id[r.taker]
        team = r.team
        if r.kind == "kickoff":
            self.emit("kickoff", team, r.x, r.y, player=taker.id)
        else:
            self.emit("set_piece", team, r.x, r.y, player=taker.id, kind=r.kind)
        self.gain(taker.id, hold=(0.2, 0.6))
        self.ball = [r.x, r.y, 0.0]
        if r.kind == "kickoff":
            return
        tx, ty = taker.x, taker.y
        taker.x, taker.y = r.x, r.y  # the kick is taken from the spot
        if r.kind == "penalty":
            self.shoot(taker, "penalty")
        elif r.kind == "corner":
            self.cross(taker, "corner")
        elif r.kind == "free_kick" and self.box_free_kick(taker):
            pass
        else:
            mates = [m for m in self.squad[team] if m.id != taker.id and m.role != "GK"]
            if r.kind == "throw_in":
                mates = [m for m in mates if 4 < math.hypot(m.x - r.x, m.y - r.y) < 25] or mates
                m = min(mates, key=lambda m: math.hypot(m.x - r.x, m.y - r.y) + self.rng.uniform(0, 8))
            elif r.kind == "goal_kick" and self.rng.random() < 0.45:
                fwd = [m for m in mates if m.role in ("ST", "RW", "LW", "RCM", "LCM")]
                m = self.rng.choice(fwd)
            else:
                m = min(mates, key=lambda m: math.hypot(m.x - r.x, m.y - r.y) + self.rng.uniform(0, 15))
            self.pass_to(taker, m, setp=r.kind, loft=None if r.kind != "throw_in" else False)
        taker.x, taker.y = tx, ty

    def box_free_kick(self, taker: Player) -> bool:
        team = taker.team
        dist = math.hypot(self.goal_x(team) - taker.x, PITCH_Y / 2 - taker.y)
        if dist >= 35:
            return False
        if dist < 28 and abs(taker.y - PITCH_Y / 2) < 14 and self.rng.random() < 0.35:
            self.shoot(taker, "free_kick")
        else:
            self.cross(taker, "free_kick")
        return True

    def half_time(self) -> None:
        self.set_period(2)
        self.pressed.clear()
        for p in self.players:
            p.run_until = -1
        self.set_restart("kickoff", "away", PITCH_X / 2, PITCH_Y / 2, 30.0)

    # ---- movement -----------------------------------------------------------

    def step(self, p: Player, tx: float, ty: float, vmax: float, slack: float = 0.0) -> None:
        """Move toward (tx, ty): speed capped, acceleration limited, slowing to arrive."""
        dx, dy = tx - p.x, ty - p.y
        dist = math.hypot(dx, dy)
        gap = dist - slack
        vx, vy = p.vx, p.vy
        if gap <= 0 and vx == 0.0 and vy == 0.0:
            return
        if gap > 0:
            want = min(vmax, p.top, math.sqrt(ARRIVE * gap), 3 * gap)
            k = want / dist
            ax, ay = dx * k - vx, dy * k - vy
        else:
            ax, ay = -vx, -vy
        a = math.hypot(ax, ay)
        if a > ACCEL_STEP:
            ax, ay = ax / a * ACCEL_STEP, ay / a * ACCEL_STEP
        vx, vy = vx + ax, vy + ay
        if -1e-3 < vx < 1e-3 and -1e-3 < vy < 1e-3:
            vx = vy = 0.0
        s = math.hypot(vx, vy)
        if s > p.top:
            vx, vy = vx / s * p.top, vy / s * p.top
        p.vx, p.vy = vx, vy
        x, y = p.x + vx * DT, p.y + vy * DT
        p.x = -1.5 if x < -1.5 else (PITCH_X + 1.5 if x > PITCH_X + 1.5 else x)
        p.y = -1.5 if y < -1.5 else (PITCH_Y + 1.5 if y > PITCH_Y + 1.5 else y)

    def offside_line(self, team: str) -> float:
        """x of the second-last opponent, the furthest a runner of `team` should go."""
        d = self.dir(team)
        xs = sorted((q.x * d for q in self.squad[other(team)]), reverse=True)
        return xs[1] * d

    def move_players(self) -> None:
        bx, by = self.ball[0], self.ball[1]
        phase = self.phase
        r = self.restart if phase == "dead" else None
        poss = r.team if r else self.poss_team
        carrier = self.by_id[self.possessor] if self.possessor else None
        chasers: dict[str, float] = {}
        press: dict[str, str] = {}
        f = self.flight
        if carrier:
            opp = other(carrier.team)
            ranked = sorted((q for q in self.squad[opp] if q.role != "GK"),
                            key=lambda q: (q.x - carrier.x) ** 2 + (q.y - carrier.y) ** 2)
            if ranked:
                a1 = self.anchor(ranked[0])
                if math.hypot(carrier.x - a1[0], carrier.y - a1[1]) < 22:
                    press[ranked[0].id] = "press"
                if len(ranked) > 1:
                    press[ranked[1].id] = "cover"
        elif phase == "loose" or (phase == "flight" and f.kind in ("clearance",)):
            if phase == "loose":
                tx, ty = bx + self.ball_v[0] * 0.3, by + self.ball_v[1] * 0.3
            else:
                tx, ty = f.ex, f.ey
            for team in ("home", "away"):
                ranked = sorted(self.squad[team], key=lambda q: (q.x - tx) ** 2 + (q.y - ty) ** 2)
                for q in ranked[:2]:
                    if q.role != "GK" or self.in_box(tx, ty, other(team)):
                        chasers[q.id] = 1
        elif phase == "flight" and f.kind != "shot":
            if f.target:
                chasers[f.target] = 1
            opp = other(f.team)
            best, bo = None, 6.0
            for q in self.squad[opp]:
                if q.role == "GK" and not self.in_box(f.ex, f.ey, f.team):
                    continue
                u, off = self.project(f.sx, f.sy, f.ex, f.ey, q.x, q.y)
                if 0.2 < u < 1.05 and off < bo:
                    best, bo = q, off
            if best:
                chasers[best.id] = 2
            if f.kind == "cross":
                for q in self.players:
                    if q.role != "GK" and math.hypot(q.x - f.ex, q.y - f.ey) < 6:
                        chasers[q.id] = 1
        for p in self.players:
            if p is carrier or p.id == self.moved:
                continue
            d = self.dir(p.team)
            ax, ay = self.anchor(p)
            vmax = 5.2
            if r is not None:
                if p.id in r.layout:
                    tx, ty = r.layout[p.id]
                    vmax = 4.0 if r.kind == "kickoff" else 5.5
                    if p.id == r.taker:
                        vmax = 6.5
                    self.step(p, tx, ty, vmax)
                    continue
            if p.role == "GK":
                own = 0.0 if d > 0 else PITCH_X
                depth = 3 + max(0.0, abs(bx - own) - 30) * 0.12
                tx, ty = own + d * depth, PITCH_Y / 2 + (by - PITCH_Y / 2) * 0.18
                if phase == "flight" and f.kind == "shot" and f.team != p.team:
                    tx, ty, vmax = f.ex - d * 0.5, f.ey, p.top
                elif p.id in chasers:
                    tx, ty, vmax = bx, by, p.top
                self.step(p, tx, ty, vmax)
                continue
            shift = (bx - PITCH_X / 2) * 0.45
            push = 6 * d if poss == p.team else -4 * d
            tx = clamp(ax + shift + push, 2, PITCH_X - 2)
            ty = ay + (by - ay) * 0.25
            if poss == p.team and p.role in ("RB", "LB", "RW", "LW"):
                ty = 6.0 if ay < PITCH_Y / 2 else PITCH_Y - 6.0  # stretch the pitch in possession
            role = press.get(p.id)
            if role == "press":
                tx, ty, vmax = carrier.x, carrier.y, p.top
                if self.t < p.busy_until:
                    vmax = 2.0
            elif role == "cover":
                gx_own = 0.0 if d > 0 else PITCH_X
                tx = carrier.x + (gx_own - carrier.x) * 0.15
                ty = carrier.y + (PITCH_Y / 2 - carrier.y) * 0.15
                vmax = 6.5
            elif p.id in chasers:
                if phase == "loose":
                    tx, ty = bx + self.ball_v[0] * 0.3, by + self.ball_v[1] * 0.3
                elif p.id == f.target and f.ix is not None and self.t - f.t0 < 0.35 * f.dur:
                    tx, ty = f.ix, f.iy
                elif chasers[p.id] == 2:
                    u, _ = self.project(f.sx, f.sy, f.ex, f.ey, p.x, p.y)
                    u = clamp(u, 0, 1)
                    tx, ty = f.sx + (f.ex - f.sx) * u, f.sy + (f.ey - f.sy) * u
                else:
                    tx, ty = f.ex, f.ey
                vmax = p.top
            elif carrier and poss == p.team and phase == "carry":
                if p.run_until > self.t:
                    tx, ty, vmax = p.run_x, p.run_y, p.top
                    if math.hypot(p.x - tx, p.y - ty) < 1.5:
                        p.run_until = -1
                elif self.rng.random() < RUN_RATE.get(p.role, 0) * DT:
                    line = self.offside_line(p.team)
                    rx = p.x + d * self.rng.uniform(10, 20)
                    rx = min(rx * d, line * d + 1.0, (self.goal_x(p.team) - d * 6) * d) * d
                    p.run_x = clamp(rx, 2, PITCH_X - 2)
                    p.run_y = clamp(p.y + self.rng.uniform(-8, 8), 3, PITCH_Y - 3)
                    p.run_until = self.t + 3.5
            self.step(p, tx, ty, vmax, slack=1.2 if vmax < 5.5 else 0.0)

    # ---- frames -------------------------------------------------------------

    def snapshot(self) -> None:
        self.match.frames.append({
            "frame": self.frame,
            "t": round(self.t, 3),
            "ball": {"x": round(self.ball[0], 3), "y": round(self.ball[1], 3), "z": round(self.ball[2], 3)},
            "possessor": self.possessor,
            "players": [{"id": p.id, "team": p.team, "x": round(p.x, 3), "y": round(p.y, 3)}
                        for p in self.players],
        })

    def run(self, minutes: float) -> Match:
        self.set_restart("kickoff", "home", PITCH_X / 2, PITCH_Y / 2, 0.0)
        total = int(round(minutes * 60 * FPS))
        half_frame = HALF_S * FPS
        for _ in range(total):
            if self.frame == half_frame:
                self.half_time()
            phase = self.phase
            self.moved = None
            if phase != "dead":
                self.match.in_play_s += DT
            if phase == "carry":
                self.tick_carrier()
            elif phase == "flight":
                self.tick_flight()
            elif phase == "loose":
                self.tick_loose()
            else:
                self.tick_dead()
            self.move_players()
            self.snapshot()
            self.t += DT
            self.frame += 1
        return self.match


def simulate(seed: int, minutes: float) -> Match:
    return Engine(seed).run(minutes)
