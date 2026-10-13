"""Seeded football match engine.

Produces the ground-truth data The Ninety Labs is scored against: every event, plus every
player's and the ball's position at every frame, in pitch metres (x 0..105 toward the away goal,
y 0..68). The home team attacks toward x=105 in both halves; the renderer can mirror if it
wants a side switch.

The model is deliberately simple (possession, dribble, pass, shot, tackle, interception, pressure)
but tuned to football-realistic rates, because its job is to give the vision pipeline footage
whose ground truth is known exactly.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

PITCH_X, PITCH_Y = 105.0, 68.0
FPS = 25
DT = 1.0 / FPS

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


@dataclass
class Flight:
    kind: str  # "pass" | "shot"
    sx: float
    sy: float
    ex: float
    ey: float
    t0: float
    dur: float
    speed_kmh: float
    passer: str
    receiver: str | None
    event_id: str
    outcome: str


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

    def nearest(self, x: float, y: float, team: str, exclude: str | None = None) -> Player:
        cands = [p for p in self.players if p.team == team and p.id != exclude]
        return min(cands, key=lambda p: math.hypot(p.x - x, p.y - y))

    def give(self, pid: str) -> None:
        if self.team_of(pid) != self.poss_team:
            self.pressed.clear()
            self.poss_team = self.team_of(pid)
        self.possessor = pid
        self.flight = None
        self.hold_until = self.t + self.rng.uniform(3.5, 7.5)

    def kickoff(self, team: str) -> None:
        for p in self.players:
            p.x, p.y = p.ax, p.ay
        self.ball = [PITCH_X / 2, PITCH_Y / 2, 0.0]
        taker = next(p for p in self.players if p.team == team and p.role == "ST")
        taker.x, taker.y = PITCH_X / 2, PITCH_Y / 2
        self.emit("kickoff", team, taker.x, taker.y, player=taker.id)
        self.give(taker.id)

    # ---- decisions ----------------------------------------------------------

    def start_flight(self, kind: str, carrier: Player, ex: float, ey: float, speed_kmh: float,
                     receiver: str | None, outcome: str, event_id: str) -> None:
        dist = math.hypot(ex - carrier.x, ey - carrier.y)
        dur = max(dist / (speed_kmh / 3.6), 0.2)
        self.flight = Flight(kind, carrier.x, carrier.y, ex, ey, self.t, dur, speed_kmh,
                             carrier.id, receiver, event_id, outcome)
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
            if on_target:
                ey = PITCH_Y / 2 + self.rng.uniform(-3.4, 3.4)
            else:
                ey = PITCH_Y / 2 + self.rng.choice([-1, 1]) * self.rng.uniform(4.5, 12)
            outcome = "goal" if goal else ("on_target" if on_target else "off_target")
            eid = self.emit("shot", team, carrier.x, carrier.y, player=carrier.id, end_x=gx,
                            end_y=round(ey, 2), outcome=outcome, ball_speed_kmh=round(speed, 1))
            self.start_flight("shot", carrier, gx, ey, speed, None, outcome, eid)
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

        # Interception: an opponent close to the pass line can cut it out.
        receiver, outcome = target.id, "success"
        mx, my = (carrier.x + ex) / 2, (carrier.y + ey) / 2
        cutter = self.nearest(mx, my, opp)
        gap = math.hypot(cutter.x - mx, cutter.y - my)
        length = math.hypot(ex - carrier.x, ey - carrier.y)
        if gap < 5 and self.rng.random() < 0.35 + length / 90:
            receiver, outcome = cutter.id, "fail"
            ex, ey = mx, my
        eid = self.emit("pass", team, carrier.x, carrier.y, player=carrier.id, receiver=receiver,
                        end_x=round(ex, 2), end_y=round(ey, 2), outcome=outcome,
                        ball_speed_kmh=round(speed, 1))
        self.start_flight("pass", carrier, ex, ey, speed, receiver, outcome, eid)

    # ---- tick ---------------------------------------------------------------

    def move_players(self) -> None:
        bx, by = self.ball[0], self.ball[1]
        poss_team = self.team_of(self.possessor) if self.possessor else None
        for p in self.players:
            if p.id == self.possessor:
                continue
            shift = (bx - PITCH_X / 2) * 0.45
            push = 6 * attack_dir(p.team) if poss_team == p.team else -4 * attack_dir(p.team)
            tx = clamp(p.ax + shift + push, 2, PITCH_X - 2) if p.role != "GK" else p.ax
            ty = p.ay + (by - p.ay) * 0.25
            speed = 5.5
            carrier = self.by_id.get(self.possessor) if self.possessor else None
            if carrier and p.team != carrier.team and p.role != "GK":
                closest = self.nearest(carrier.x, carrier.y, p.team)
                in_zone = math.hypot(carrier.x - p.ax, carrier.y - p.ay) < 18
                if closest.id == p.id and in_zone:
                    tx, ty, speed = carrier.x, carrier.y, 4.5
            dx, dy = tx - p.x, ty - p.y
            d = math.hypot(dx, dy)
            step = min(d, speed * DT)
            if d > 1e-6:
                p.x += dx / d * step + self.rng.gauss(0, 0.02)
                p.y += dy / d * step + self.rng.gauss(0, 0.02)
            p.x, p.y = clamp(p.x, 0.5, PITCH_X - 0.5), clamp(p.y, 0.5, PITCH_Y - 0.5)

    def tick_carrier(self) -> None:
        carrier = self.by_id[self.possessor]
        team, opp = carrier.team, ("away" if carrier.team == "home" else "home")
        gx = goal_x(team)
        presser = self.nearest(carrier.x, carrier.y, opp)
        gap = math.hypot(presser.x - carrier.x, presser.y - carrier.y)
        if gap > 6:
            dx, dy = gx - carrier.x, PITCH_Y / 2 - carrier.y
            d = math.hypot(dx, dy) or 1
            carrier.x = clamp(carrier.x + dx / d * 2.0 * DT, 0.5, PITCH_X - 0.5)
            carrier.y = clamp(carrier.y + dy / d * 0.6 * DT, 0.5, PITCH_Y - 0.5)
        self.ball = [carrier.x, carrier.y, 0.0]
        if gap < 2.0 and self.t - self.pressed.get(opp, -99) > 8:
            self.pressed[opp] = self.t
            self.emit("pressure", opp, presser.x, presser.y, player=presser.id, receiver=carrier.id)
        if gap < 1.5 and self.rng.random() < 0.07 * DT:
            self.emit("tackle", opp, carrier.x, carrier.y, player=presser.id, receiver=carrier.id,
                      outcome="success")
            self.emit("possession_change", opp, carrier.x, carrier.y, player=presser.id)
            self.give(presser.id)
            return
        if gap < 3:
            self.hold_until = min(self.hold_until, self.t + 2.4)
        if self.t >= self.hold_until:
            self.decide(carrier)

    def tick_flight(self) -> None:
        f = self.flight
        u = clamp((self.t - f.t0) / f.dur, 0, 1)
        self.ball = [f.sx + (f.ex - f.sx) * u, f.sy + (f.ey - f.sy) * u,
                     (4 * u * (1 - u) * (1.5 if f.kind == "pass" else 0.8))]
        if u < 1:
            return
        if f.kind == "pass":
            if f.outcome == "fail":
                team = self.team_of(f.receiver)
                self.emit("interception", team, f.ex, f.ey, player=f.receiver)
                self.emit("possession_change", team, f.ex, f.ey, player=f.receiver)
            r = self.by_id[f.receiver]
            r.x, r.y = f.ex, f.ey
            self.give(f.receiver)
            return
        shooter_team = self.team_of(f.passer)
        defending = "away" if shooter_team == "home" else "home"
        if f.outcome == "goal":
            self.match.score[shooter_team] += 1
            self.emit("goal", shooter_team, f.ex, f.ey, player=f.passer,
                      ball_speed_kmh=round(f.speed_kmh, 1))
            self.kickoff(defending)
            return
        gk = next(p for p in self.players if p.team == defending and p.role == "GK")
        if f.outcome == "off_target":
            self.emit("out_of_play", shooter_team, f.ex, clamp(f.ey, 0, PITCH_Y))
            self.emit("set_piece", defending, gk.x, gk.y, player=gk.id, outcome=None)
        self.emit("possession_change", defending, gk.x, gk.y, player=gk.id)
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
            self.move_players()
            self.snapshot()
            self.t += DT
            self.frame += 1
        return self.match


def simulate(seed: int, minutes: float) -> Match:
    return Engine(seed).run(minutes)
