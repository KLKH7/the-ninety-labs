"""Seeded football match engine.

Produces the ground-truth data The Ninety Labs is scored against: every event, plus every
player's and the ball's position at every frame, in pitch metres (x 0..105 toward the away goal,
y 0..68). The home team attacks toward x=105 in both halves; the renderer can mirror if it
wants a side switch.

The football is deliberately simple (possession, dribble, pass, shot, tackle, interception,
pressure, goal kick) but tuned to realistic rates, and the motion is physical: players have a
velocity and a limited acceleration, and the ball flies under gravity. Every limit cites its
source in docs/GROUNDING.md, and `ninety-validate` checks the output independently.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

PITCH_X, PITCH_Y = 105.0, 68.0
FPS = 25
DT = 1.0 / FPS
GRAVITY = 9.81
MAX_ACCEL = 5.0  # P2: elite maximal acceleration is about 6.2 m/s²; most efforts are well below
SPRINT = 7.0  # running onto a pass
JOG = 5.5  # holding team shape
PRESS = 4.5  # closing down the ball carrier
DRIBBLE = 2.5
CONTROL_M = 1.0  # a player within this distance of a loose ball takes it
BALL_TO_FEET = 12.0  # m/s: how fast the ball settles at a new carrier's feet
LOFT_OVER_M = 25.0  # passes longer than this go through the air
GOAL_KICK_DELAY_S = 6.0  # stoppage after the ball goes out before the goal kick
GOAL_AREA_X = 5.5  # Law 1: goal area depth

# 4-3-3 anchors for a team attacking toward x=105, as (x, y) fractions of the pitch.
FORMATION = [
    ("GK", 0.05, 0.50),
    ("RB", 0.25, 0.15), ("RCB", 0.20, 0.38), ("LCB", 0.20, 0.62), ("LB", 0.25, 0.85),
    ("RCM", 0.42, 0.30), ("CM", 0.38, 0.50), ("LCM", 0.42, 0.70),
    ("RW", 0.62, 0.15), ("ST", 0.66, 0.50), ("LW", 0.62, 0.85),
]


@dataclass
class Player:
    id: str
    team: str
    role: str
    ax: float
    ay: float
    x: float
    y: float
    vx: float = 0.0
    vy: float = 0.0


@dataclass
class Flight:
    kind: str  # "pass" | "shot"
    sx: float
    sy: float
    ex: float
    ey: float
    t0: float
    dur: float
    vz: float  # launch speed upward; 0 for a ball along the ground
    speed_kmh: float
    passer: str
    receiver: str | None
    event_id: str
    outcome: str


@dataclass
class Loose:
    """A ball that has arrived and waits for a player to reach it."""
    taker: str
    kind: str  # "pass" | "pass_cut" | "save"


@dataclass
class Match:
    seed: int
    events: list[dict] = field(default_factory=list)
    frames: list[dict] = field(default_factory=list)
    score: dict = field(default_factory=lambda: {"home": 0, "away": 0})


def attack_dir(team: str) -> float:
    return 1.0 if team == "home" else -1.0


def goal_x(team: str) -> float:
    """x of the goal this team attacks."""
    return PITCH_X if team == "home" else 0.0


def clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def steer(p: Player, tx: float, ty: float, top_speed: float) -> None:
    """Move toward a target with limited acceleration, slowing in time to stop on it."""
    dx, dy = tx - p.x, ty - p.y
    d = math.hypot(dx, dy)
    want = min(top_speed, math.sqrt(2 * MAX_ACCEL * 0.8 * d))
    wx, wy = (dx / d * want, dy / d * want) if d > 1e-6 else (0.0, 0.0)
    ax, ay = wx - p.vx, wy - p.vy
    change = math.hypot(ax, ay)
    limit = MAX_ACCEL * DT
    if change > limit:
        ax, ay = ax / change * limit, ay / change * limit
    p.vx, p.vy = p.vx + ax, p.vy + ay
    nx, ny = clamp(p.x + p.vx * DT, 0.5, PITCH_X - 0.5), clamp(p.y + p.vy * DT, 0.5, PITCH_Y - 0.5)
    if nx != p.x + p.vx * DT:
        p.vx = 0.0
    if ny != p.y + p.vy * DT:
        p.vy = 0.0
    p.x, p.y = nx, ny


class Engine:
    def __init__(self, seed: int):
        self.rng = random.Random(seed)
        self.match = Match(seed=seed)
        self.players: list[Player] = []
        for team in ("home", "away"):
            for n, (role, fx, fy) in enumerate(FORMATION):
                ax = fx * PITCH_X if team == "home" else (1 - fx) * PITCH_X
                ay = fy * PITCH_Y if team == "home" else (1 - fy) * PITCH_Y
                self.players.append(Player(f"{team[0]}{n + 1}", team, role, ax, ay, ax, ay))
        self.by_id = {p.id: p for p in self.players}
        self.ball = [PITCH_X / 2, PITCH_Y / 2, 0.0]
        self.possessor: str | None = None
        self.flight: Flight | None = None
        self.loose: Loose | None = None
        self.goal_kick: tuple[str, float] | None = None  # (keeper, earliest restart time)
        self.hold_until = 0.0
        self.pressed: dict[str, float] = {}
        self.poss_team: str | None = None
        self.t = 0.0
        self.frame = 0
        self._eid = 0

    # ---- events -------------------------------------------------------------

    def emit(self, type_: str, team: str, x: float, y: float, **kw) -> str:
        self._eid += 1
        eid = f"e{self._eid:05d}"
        ev = {
            "id": eid, "t": round(self.t, 2), "frame": self.frame, "type": type_, "team": team,
            "player": None, "receiver": None, "x": round(clamp(x, 0, PITCH_X), 2),
            "y": round(clamp(y, 0, PITCH_Y), 2), "end_x": None, "end_y": None, "outcome": None,
            "ball_speed_kmh": None, "source": "truth", "confidence": None,
        }
        ev.update(kw)
        self.match.events.append(ev)
        return eid

    # ---- helpers ------------------------------------------------------------

    def team_of(self, pid: str) -> str:
        return self.by_id[pid].team

    def keeper(self, team: str) -> Player:
        return next(p for p in self.players if p.team == team and p.role == "GK")

    def nearest(self, x: float, y: float, team: str, exclude: str | None = None) -> Player:
        cands = [p for p in self.players if p.team == team and p.id != exclude]
        return min(cands, key=lambda p: math.hypot(p.x - x, p.y - y))

    def give(self, pid: str) -> None:
        if self.team_of(pid) != self.poss_team:
            self.pressed.clear()
            self.poss_team = self.team_of(pid)
        self.possessor = pid
        self.flight = None
        self.loose = None
        self.hold_until = self.t + self.rng.uniform(3.5, 7.5)

    def kickoff(self, team: str) -> None:
        # A restart after a goal: the broadcast cuts here, so positions reset (validator allows it).
        for p in self.players:
            p.x, p.y, p.vx, p.vy = p.ax, p.ay, 0.0, 0.0
        self.ball = [PITCH_X / 2, PITCH_Y / 2, 0.0]
        taker = next(p for p in self.players if p.team == team and p.role == "ST")
        taker.x, taker.y = PITCH_X / 2, PITCH_Y / 2
        self.emit("kickoff", team, taker.x, taker.y, player=taker.id)
        self.give(taker.id)

    # ---- decisions ----------------------------------------------------------

    def start_flight(self, kind: str, ex: float, ey: float, speed_kmh: float, lofted: bool,
                     passer: str, receiver: str | None, outcome: str, event_id: str) -> None:
        sx, sy = self.ball[0], self.ball[1]
        dur = max(math.hypot(ex - sx, ey - sy) / (speed_kmh / 3.6), 0.2)
        # Launched upward just fast enough for gravity to bring it down at the target.
        vz = GRAVITY * dur / 2 if lofted else 0.0
        self.flight = Flight(kind, sx, sy, ex, ey, self.t, dur, vz, speed_kmh, passer, receiver,
                             event_id, outcome)
        self.possessor = None

    def decide(self, carrier: Player) -> None:
        team = carrier.team
        opp = "away" if team == "home" else "home"
        gx = goal_x(team)
        d_goal = math.hypot(gx - carrier.x, PITCH_Y / 2 - carrier.y)

        if d_goal < 30 and self.rng.random() < 0.05 + (30 - d_goal) / 80:
            speed = self.rng.uniform(70, 120)
            on_target = self.rng.random() < 0.34
            goal = on_target and self.rng.random() < clamp(0.45 - d_goal / 50, 0.06, 0.4)
            if goal:
                ex, ey = gx, PITCH_Y / 2 + self.rng.uniform(-3.4, 3.4)
            elif on_target:  # saved: the ball flies to the keeper's hands
                gk = self.keeper(opp)
                ex, ey = gk.x, clamp(gk.y + self.rng.uniform(-1.0, 1.0), 0, PITCH_Y)
            else:
                ex, ey = gx, PITCH_Y / 2 + self.rng.choice([-1, 1]) * self.rng.uniform(4.5, 12)
            outcome = "goal" if goal else ("on_target" if on_target else "off_target")
            eid = self.emit("shot", team, self.ball[0], self.ball[1], player=carrier.id, end_x=round(ex, 2),
                            end_y=round(ey, 2), outcome=outcome, ball_speed_kmh=round(speed, 1))
            receiver = self.keeper(opp).id if outcome == "on_target" else None
            self.start_flight("shot", ex, ey, speed, d_goal > 18, carrier.id, receiver, outcome, eid)
            return

        mates = [p for p in self.players if p.team == team and p.id != carrier.id]
        weights = []
        for m in mates:
            fwd = (m.x - carrier.x) * attack_dir(team)
            dist = math.hypot(m.x - carrier.x, m.y - carrier.y)
            if dist < 4 or dist > 45:
                weights.append(0.0)
                continue
            marker = self.nearest(m.x, m.y, opp)
            space = math.hypot(marker.x - m.x, marker.y - m.y)
            weights.append(max(0.2, 1 + fwd / 18) * min(space, 8) / (1 + dist / 25))
        if not any(weights):
            self.hold_until = self.t + 0.5
            return
        target = self.rng.choices(mates, weights=weights)[0]
        lead = self.rng.uniform(0, 3) * attack_dir(team)
        ex, ey = clamp(target.x + lead, 1, PITCH_X - 1), target.y
        speed = self.rng.uniform(45, 85)

        # Interception: an opponent close to the pass line can cut it out where they meet it.
        receiver, outcome = target.id, "success"
        mx, my = (self.ball[0] + ex) / 2, (self.ball[1] + ey) / 2
        cutter = self.nearest(mx, my, opp)
        gap = math.hypot(cutter.x - mx, cutter.y - my)
        length = math.hypot(ex - self.ball[0], ey - self.ball[1])
        if gap < 5 and self.rng.random() < 0.35 + length / 90:
            receiver, outcome = cutter.id, "fail"
            ex, ey = mx, my
        eid = self.emit("pass", team, self.ball[0], self.ball[1], player=carrier.id, receiver=receiver,
                        end_x=round(ex, 2), end_y=round(ey, 2), outcome=outcome,
                        ball_speed_kmh=round(speed, 1))
        lofted = outcome == "success" and length > LOFT_OVER_M
        self.start_flight("pass", ex, ey, speed, lofted, carrier.id, receiver, outcome, eid)

    # ---- tick ---------------------------------------------------------------

    def shape_target(self, p: Player) -> tuple[float, float, float]:
        """Where a player off the ball wants to be, and how fast they go there."""
        bx, by = self.ball[0], self.ball[1]
        if self.flight and p.id == self.flight.receiver:
            return self.flight.ex, self.flight.ey, SPRINT
        if self.loose and p.id == self.loose.taker:
            return bx, by, SPRINT
        if self.goal_kick and p.id == self.goal_kick[0]:
            return self.goal_kick_spot(p.team) + (JOG,)
        poss_team = self.team_of(self.possessor) if self.possessor else None
        shift = (bx - PITCH_X / 2) * 0.45
        push = 6 * attack_dir(p.team) if poss_team == p.team else -4 * attack_dir(p.team)
        tx = clamp(p.ax + shift + push, 2, PITCH_X - 2) if p.role != "GK" else p.ax
        ty = p.ay + (by - p.ay) * 0.25
        carrier = self.by_id.get(self.possessor) if self.possessor else None
        if carrier and p.team != carrier.team and p.role != "GK":
            closest = self.nearest(carrier.x, carrier.y, p.team)
            in_zone = math.hypot(carrier.x - p.ax, carrier.y - p.ay) < 18
            if closest.id == p.id and in_zone:
                return carrier.x, carrier.y, PRESS
        return tx, ty, JOG

    def goal_kick_spot(self, team: str) -> tuple[float, float]:
        own_line = PITCH_X - goal_x(team)
        return abs(own_line - GOAL_AREA_X), PITCH_Y / 2

    def move_players(self) -> None:
        for p in self.players:
            if p.id == self.possessor:
                continue
            tx, ty, top = self.shape_target(p)
            steer(p, tx, ty, top)

    def tick_carrier(self) -> None:
        carrier = self.by_id[self.possessor]
        team, opp = carrier.team, ("away" if carrier.team == "home" else "home")
        gx = goal_x(team)
        presser = self.nearest(carrier.x, carrier.y, opp)
        gap = math.hypot(presser.x - carrier.x, presser.y - carrier.y)
        if gap > 6:
            steer(carrier, gx, carrier.y + (PITCH_Y / 2 - carrier.y) * 0.3, DRIBBLE)
        else:
            steer(carrier, carrier.x, carrier.y, DRIBBLE)
        # The ball settles at the carrier's feet rather than jumping there.
        dx, dy = carrier.x - self.ball[0], carrier.y - self.ball[1]
        d = math.hypot(dx, dy)
        step = min(d, BALL_TO_FEET * DT)
        if d > 1e-6:
            self.ball = [self.ball[0] + dx / d * step, self.ball[1] + dy / d * step, 0.0]
        if gap < 2.0 and self.t - self.pressed.get(opp, -99) > 8:
            self.pressed[opp] = self.t
            self.emit("pressure", opp, presser.x, presser.y, player=presser.id, receiver=carrier.id)
        if gap < 1.5 and self.rng.random() < 0.07 * DT:
            self.emit("tackle", opp, self.ball[0], self.ball[1], player=presser.id, receiver=carrier.id,
                      outcome="success")
            self.emit("possession_change", opp, self.ball[0], self.ball[1], player=presser.id)
            self.give(presser.id)
            return
        if gap < 3:
            self.hold_until = min(self.hold_until, self.t + 2.4)
        if self.t >= self.hold_until:
            self.decide(carrier)

    def tick_flight(self) -> None:
        f = self.flight
        s = clamp(self.t - f.t0, 0, f.dur)
        u = s / f.dur
        z = max(f.vz * s - GRAVITY * s * s / 2, 0.0)
        self.ball = [f.sx + (f.ex - f.sx) * u, f.sy + (f.ey - f.sy) * u, z]
        if u < 1:
            return
        self.flight = None
        self.ball[2] = 0.0
        if f.kind == "pass":
            self.loose = Loose(f.receiver, "pass" if f.outcome == "success" else "pass_cut")
            return
        shooter_team = self.team_of(f.passer)
        defending = "away" if shooter_team == "home" else "home"
        if f.outcome == "goal":
            self.match.score[shooter_team] += 1
            self.emit("goal", shooter_team, f.ex, f.ey, player=f.passer,
                      ball_speed_kmh=round(f.speed_kmh, 1))
            self.kickoff(defending)
            return
        if f.outcome == "on_target":
            self.loose = Loose(f.receiver, "save")
            return
        self.emit("out_of_play", shooter_team, f.ex, clamp(f.ey, 0, PITCH_Y))
        self.goal_kick = (self.keeper(defending).id, self.t + GOAL_KICK_DELAY_S)

    def tick_loose(self) -> None:
        """The ball waits where it landed until its taker reaches it."""
        taker = self.by_id[self.loose.taker]
        if math.hypot(taker.x - self.ball[0], taker.y - self.ball[1]) > CONTROL_M:
            return
        team = taker.team
        if self.loose.kind in ("pass_cut", "save"):
            if self.loose.kind == "pass_cut":
                self.emit("interception", team, self.ball[0], self.ball[1], player=taker.id)
            self.emit("possession_change", team, self.ball[0], self.ball[1], player=taker.id)
        self.give(taker.id)

    def tick_goal_kick(self) -> None:
        """Law 16: after the stoppage the keeper restarts from inside the goal area."""
        keeper_id, ready_at = self.goal_kick
        gk = self.by_id[keeper_id]
        sx, sy = self.goal_kick_spot(gk.team)
        if self.t < ready_at or math.hypot(gk.x - sx, gk.y - sy) > CONTROL_M:
            return
        # While the ball is out of play a new one is placed: the only time the ball may jump.
        self.ball = [gk.x, gk.y, 0.0]
        self.goal_kick = None
        self.emit("set_piece", gk.team, gk.x, gk.y, player=gk.id, outcome=None)
        self.emit("possession_change", gk.team, gk.x, gk.y, player=gk.id)
        self.give(gk.id)

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
        self.kickoff("home")
        total = int(minutes * 60 * FPS)
        for _ in range(total):
            if self.possessor:
                self.tick_carrier()
            elif self.flight:
                self.tick_flight()
            elif self.loose:
                self.tick_loose()
            elif self.goal_kick:
                self.tick_goal_kick()
            self.move_players()
            self.snapshot()
            self.t += DT
            self.frame += 1
        return self.match


def simulate(seed: int, minutes: float) -> Match:
    return Engine(seed).run(minutes)
