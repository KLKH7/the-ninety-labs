"""Seeded football match engine.

Produces the ground-truth data The Ninety Labs is scored against: every event, plus every
player's and the ball's position at every frame, in pitch metres (x 0..105 toward the away goal,
y 0..68). The home team attacks toward x=105 in both halves; the renderer can mirror if it
wants a side switch.

Players decide (where to run, whom to pass to, when to shoot); physics decides what happens.
A kick gives the ball a velocity, the ball flies, bounces and rolls (`ball.py`), each team sends
the player who can reach it first, and whoever gets there takes it. Whether a pass is completed
or intercepted, a shot saved or scored, or the ball goes out, is the result, never a dice roll
that the world is then arranged to match. Every limit cites its source in docs/GROUNDING.md, and
`ninety-validate` checks the output independently.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

from ninety.sim import ball

PITCH_X, PITCH_Y = 105.0, 68.0
FPS = 25
DT = 1.0 / FPS
MAX_ACCEL = 5.0  # P2: elite maximal acceleration is about 6.2 m/s²; most efforts are well below
SPRINT = 7.0  # chasing the ball
JOG = 5.5  # holding team shape
PRESS = 4.5  # closing down the ball carrier
DRIBBLE = 2.5
REACTION_S = 0.3  # verify: human reaction to a struck ball, before anyone can run for or touch it
CONTROL_M = 1.0  # a player this close to a ball low enough to reach takes it
FOOT_REACH_Z = 1.0  # outfield players control the ball below this height
HAND_REACH_Z = 2.6  # a keeper inside their penalty area can reach this high
KEEPER_REACH_M = 1.8  # a keeper's dive reaches further than a foot
BALL_TO_FEET = 12.0  # m/s: how fast the ball settles at a new carrier's feet
LOFT_OVER_M = 25.0  # passes longer than this go through the air
CHASE_EVERY = 4  # frames between re-planning who chases a free ball
GOAL_HALF_WIDTH, CROSSBAR = 3.66, 2.44  # Law 1
PENALTY_DEPTH, PENALTY_HALF_WIDTH = 16.5, 20.16  # Law 1
GOAL_AREA_X = 5.5  # Law 1
BOARDS_M = 4.0  # verify: advertising boards behind the lines stop a ball (and players) that go out
RESTART_DELAY_S = {"throw_in": (3, 8), "goal_kick": (6, 10), "corner": (12, 20)}  # verify (R1)

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
class Restart:
    kind: str  # "throw_in" | "goal_kick" | "corner"
    team: str
    x: float
    y: float
    taker: str
    ready_at: float


@dataclass
class Match:
    seed: int
    events: list[dict] = field(default_factory=list)
    frames: list[dict] = field(default_factory=list)
    score: dict = field(default_factory=lambda: {"home": 0, "away": 0})
    roster: list[dict] = field(default_factory=list)


def attack_dir(team: str) -> float:
    return 1.0 if team == "home" else -1.0


def goal_x(team: str) -> float:
    """x of the goal this team attacks."""
    return PITCH_X if team == "home" else 0.0


def other(team: str) -> str:
    return "away" if team == "home" else "home"


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
    # No wall at the lines: players may run past them, as in real matches. Targets stay on the
    # pitch, so they slow down and come back; only the advertising boards stop them.
    p.x = clamp(p.x + p.vx * DT, -BOARDS_M, PITCH_X + BOARDS_M)
    p.y = clamp(p.y + p.vy * DT, -BOARDS_M, PITCH_Y + BOARDS_M)


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
        self.match.roster = [{"id": p.id, "team": p.team, "role": p.role} for p in self.players]
        self.ball: ball.State = (PITCH_X / 2, PITCH_Y / 2, 0.0, 0.0, 0.0, 0.0)
        self.possessor: str | None = None
        self.last_touch: str | None = None
        self.kicked: dict | None = None  # the pass or shot event in flight, resolved when it ends
        self.kicked_at = -99.0
        self.chase: dict[str, tuple[str, float, float]] = {}  # team -> (player, x, y)
        self.restart: Restart | None = None
        self.throw_by: str | None = None  # a throw-in taker holding the ball before the throw
        self.moved: str | None = None  # the carrier, already moved this frame by tick_carrier
        self.hold_until = 0.0
        self.pressed: dict[str, float] = {}
        self.poss_team: str | None = None
        self.t = 0.0
        self.frame = 0
        self._eid = 0

    # ---- events -------------------------------------------------------------

    def emit(self, type_: str, team: str, x: float, y: float, **kw) -> dict:
        self._eid += 1
        ev = {
            "id": f"e{self._eid:05d}", "t": round(self.t, 2), "frame": self.frame, "type": type_,
            "team": team, "player": None, "receiver": None, "x": round(clamp(x, 0, PITCH_X), 2),
            "y": round(clamp(y, 0, PITCH_Y), 2), "end_x": None, "end_y": None, "outcome": None,
            "ball_speed_kmh": None, "source": "truth", "confidence": None,
        }
        ev.update(kw)
        self.match.events.append(ev)
        return ev

    # ---- helpers ------------------------------------------------------------

    def team_of(self, pid: str) -> str:
        return self.by_id[pid].team

    def keeper(self, team: str) -> Player:
        return next(p for p in self.players if p.team == team and p.role == "GK")

    def nearest(self, x: float, y: float, team: str, exclude: str | None = None) -> Player:
        cands = [p for p in self.players if p.team == team and p.id != exclude]
        return min(cands, key=lambda p: math.hypot(p.x - x, p.y - y))

    def in_own_box(self, p: Player) -> bool:
        own_line = PITCH_X - goal_x(p.team)
        return abs(p.x - own_line) <= PENALTY_DEPTH and abs(p.y - PITCH_Y / 2) <= PENALTY_HALF_WIDTH

    def reach(self, p: Player) -> tuple[float, float]:
        """How far and how high this player can reach for the ball."""
        if p.role == "GK" and self.in_own_box(p):
            return KEEPER_REACH_M, HAND_REACH_Z
        return CONTROL_M, FOOT_REACH_Z

    def give(self, pid: str) -> None:
        if self.team_of(pid) != self.poss_team:
            self.pressed.clear()
            self.poss_team = self.team_of(pid)
        self.possessor = pid
        self.last_touch = pid
        self.chase = {}
        self.hold_until = self.t + self.rng.uniform(3.5, 7.5)

    def kickoff(self, team: str) -> None:
        # A restart after a goal: the broadcast cuts here, so positions reset (validator allows it).
        for p in self.players:
            p.x, p.y, p.vx, p.vy = p.ax, p.ay, 0.0, 0.0
        self.ball = (PITCH_X / 2, PITCH_Y / 2, 0.0, 0.0, 0.0, 0.0)
        taker = next(p for p in self.players if p.team == team and p.role == "ST")
        taker.x, taker.y = PITCH_X / 2, PITCH_Y / 2
        self.emit("kickoff", team, taker.x, taker.y, player=taker.id)
        self.give(taker.id)

    # ---- decisions: players choose, the kick gives the ball a velocity -------

    def kick(self, carrier: Player, vx: float, vy: float, vz: float) -> None:
        bx, by = self.ball[0], self.ball[1]
        self.ball = (bx, by, 0.0, vx, vy, vz)
        self.possessor = None
        self.last_touch = carrier.id
        self.kicked_at = self.t
        self.plan_chase()

    def aim(self, sx: float, sy: float, tx: float, ty: float, ground: float, up: float):
        d = math.hypot(tx - sx, ty - sy) or 1.0
        return (tx - sx) / d * ground, (ty - sy) / d * ground, up

    def shoot(self, carrier: Player) -> None:
        team = carrier.team
        gx = goal_x(team)
        bx, by = self.ball[0], self.ball[1]
        # Aim inside a post and under the bar, with an error that grows with distance.
        side = self.rng.choice([-1, 1])
        d_goal = math.hypot(gx - bx, PITCH_Y / 2 - by)
        spread = 1.2 + d_goal / 12
        ty = PITCH_Y / 2 + side * self.rng.uniform(0.5, 3.2) + self.rng.gauss(0, spread)
        tz = clamp(self.rng.uniform(0.1, 2.0) + self.rng.gauss(0, spread / 3), 0.0, 4.0)
        speed = self.rng.uniform(70, 120) / 3.6
        ground, up = ball.shot(math.hypot(gx - bx, ty - by), speed, tz, DT)
        vx, vy, vz = self.aim(bx, by, gx, ty, ground, up)
        on_target = abs(ty - PITCH_Y / 2) < GOAL_HALF_WIDTH - ball.RADIUS and tz < CROSSBAR - 2 * ball.RADIUS
        # Where it ends (saved, blocked or out) is filled in when that happens.
        self.kicked = self.emit("shot", team, bx, by, player=carrier.id,
                                outcome="on_target" if on_target else "off_target",
                                ball_speed_kmh=round(speed * 3.6, 1))
        self.kick(carrier, vx, vy, vz)

    def pass_to(self, carrier: Player, target: Player, throw: bool = False) -> None:
        bx, by = self.ball[0], self.ball[1]
        lead = self.rng.uniform(0, 3) * attack_dir(carrier.team)
        tx, ty = clamp(target.x + lead, 1, PITCH_X - 1), target.y
        dist = math.hypot(tx - bx, ty - by)
        if throw or dist > LOFT_OVER_M:
            ground, up = ball.lofted_pass(dist, 30 if throw else self.rng.uniform(25, 40), DT)
        else:
            ground, up = ball.ground_pass(dist, self.rng.uniform(3, 7), DT), 0.0
        vx, vy, vz = self.aim(bx, by, tx, ty, ground, up)
        # Receiver, end point and outcome are filled in when someone takes the ball or it goes out.
        self.kicked = self.emit("pass", carrier.team, bx, by, player=carrier.id,
                                ball_speed_kmh=round(math.sqrt(vx * vx + vy * vy + vz * vz) * 3.6, 1))
        self.kick(carrier, vx, vy, vz)

    def decide(self, carrier: Player, throw: bool = False) -> None:
        team = carrier.team
        opp = other(team)
        gx = goal_x(team)
        d_goal = math.hypot(gx - carrier.x, PITCH_Y / 2 - carrier.y)
        if not throw and d_goal < 30 and self.rng.random() < 0.05 + (30 - d_goal) / 80:
            self.shoot(carrier)
            return
        mates = [p for p in self.players if p.team == team and p.id != carrier.id]
        weights = []
        for m in mates:
            fwd = (m.x - carrier.x) * attack_dir(team)
            dist = math.hypot(m.x - carrier.x, m.y - carrier.y)
            if dist < 4 or dist > (25 if throw else 45):
                weights.append(0.0)
                continue
            marker = self.nearest(m.x, m.y, opp)
            space = math.hypot(marker.x - m.x, marker.y - m.y)
            weights.append(max(0.2, 1 + fwd / 18) * min(space, 8) / (1 + dist / 25))
        if not any(weights):
            self.hold_until = self.t + 0.5
            return
        self.pass_to(carrier, self.rng.choices(mates, weights=weights)[0], throw)

    # ---- the free ball: who can get there first ------------------------------

    def plan_chase(self) -> None:
        """Each team sends the player who can reach the ball's path first."""
        path = ball.predict(self.ball, DT, 6.0)
        best: dict[str, tuple[float, str, float, float]] = {}
        for p in self.players:
            reach_m, reach_z = self.reach(p)
            for k in range(0, len(path), 2):
                bx, by, bz = path[k][0], path[k][1], path[k][2]
                if bz > reach_z:
                    continue
                t = k * DT
                gap = math.hypot(bx - p.x, by - p.y) - reach_m
                if gap <= SPRINT * max(0.0, t - REACTION_S) or k + 2 >= len(path):
                    arrive = t if gap <= SPRINT * max(0.0, t - REACTION_S) else t + gap / SPRINT
                    if p.team not in best or arrive < best[p.team][0]:
                        best[p.team] = (arrive, p.id, bx, by)
                    break
        self.chase = {team: (pid, x, y) for team, (_, pid, x, y) in best.items()}

    def tick_free(self) -> None:
        self.ball = ball.step(self.ball, DT)
        if self.went_out():
            return
        if self.frame % CHASE_EVERY == 0:
            self.plan_chase()
        if self.t - self.kicked_at < REACTION_S:
            return
        bx, by, bz = self.ball[0], self.ball[1], self.ball[2]
        takers = []
        for p in self.players:
            reach_m, reach_z = self.reach(p)
            d = math.hypot(bx - p.x, by - p.y)
            if d <= reach_m and bz <= reach_z:
                takers.append((d, p))
        if takers:
            self.taken_by(min(takers, key=lambda tp: tp[0])[1])

    def taken_by(self, p: Player) -> None:
        bx, by = self.ball[0], self.ball[1]
        kicked = self.kicked
        self.kicked = None
        if kicked and kicked["type"] == "shot":
            kicked.update(end_x=round(bx, 2), end_y=round(by, 2))
        if kicked and kicked["type"] == "pass":
            same = p.team == kicked["team"]
            kicked.update(receiver=p.id, end_x=round(bx, 2), end_y=round(by, 2),
                          outcome="success" if same else "fail")
            if not same:
                self.emit("interception", p.team, bx, by, player=p.id)
        if p.team != self.poss_team:
            self.emit("possession_change", p.team, bx, by, player=p.id)
        self.give(p.id)

    def went_out(self) -> bool:
        """Law 9: out once the whole ball has crossed a goal line or touchline."""
        bx, by, bz = self.ball[0], self.ball[1], self.ball[2]
        r = ball.RADIUS
        over_goal_line = bx < -r or bx > PITCH_X + r
        if not over_goal_line and -r <= by <= PITCH_Y + r:
            return False
        last_team = self.team_of(self.last_touch) if self.last_touch else "home"
        kicked = self.kicked
        self.kicked = None
        x, y = clamp(bx, 0, PITCH_X), clamp(by, 0, PITCH_Y)
        if kicked:
            kicked.update(end_x=round(x, 2), end_y=round(y, 2))
            if kicked["type"] == "pass":
                kicked["outcome"] = "fail"
        self.chase = {}
        if over_goal_line:
            attackers = "home" if bx > PITCH_X / 2 else "away"
            if abs(by - PITCH_Y / 2) < GOAL_HALF_WIDTH - r and bz < CROSSBAR - 2 * r:  # Law 10
                self.scored(attackers, kicked, x, y)
                return True
            self.emit("out_of_play", last_team, x, y)
            if last_team == attackers:  # Law 16
                gk = self.keeper(other(attackers))
                spot = (abs(PITCH_X - goal_x(gk.team) - GOAL_AREA_X), PITCH_Y / 2)
                self.stop("goal_kick", gk.team, spot, gk.id)
            else:  # Law 17
                spot = (PITCH_X if attackers == "home" else 0.0, PITCH_Y if by > PITCH_Y / 2 else 0.0)
                self.stop("corner", attackers, spot)
        else:  # Law 15
            self.emit("out_of_play", last_team, x, y)
            self.stop("throw_in", other(last_team), (x, PITCH_Y if by > PITCH_Y / 2 else 0.0))
        return True

    def scored(self, team: str, kicked: dict | None, x: float, y: float) -> None:
        self.match.score[team] += 1
        shooter = kicked["player"] if kicked and kicked["type"] == "shot" else self.last_touch
        if kicked and kicked["type"] == "shot":
            kicked["outcome"] = "goal"
        self.emit("goal", team, x, y, player=shooter if self.team_of(shooter) == team else None)
        self.kickoff(other(team))

    def stop(self, kind: str, team: str, spot: tuple[float, float], taker: str | None = None) -> None:
        if taker is None:
            taker = self.nearest(spot[0], spot[1], team).id
        lo, hi = RESTART_DELAY_S[kind]
        self.restart = Restart(kind, team, spot[0], spot[1], taker, self.t + self.rng.uniform(lo, hi))

    def tick_restart(self) -> None:
        # The dead ball rolls on until it stops or reaches the advertising boards.
        bx, by, bz, vx, vy, vz = ball.step(self.ball, DT)
        if not (-BOARDS_M <= bx <= PITCH_X + BOARDS_M and -BOARDS_M <= by <= PITCH_Y + BOARDS_M):
            bx, by = clamp(bx, -BOARDS_M, PITCH_X + BOARDS_M), clamp(by, -BOARDS_M, PITCH_Y + BOARDS_M)
            vx = vy = 0.0
        self.ball = (bx, by, bz, vx, vy, vz)
        r = self.restart
        taker = self.by_id[r.taker]
        if self.t < r.ready_at or math.hypot(taker.x - r.x, taker.y - r.y) > CONTROL_M:
            return
        # While the ball is out of play a new one is placed: the only time the ball may jump.
        self.ball = (taker.x, taker.y, 0.0, 0.0, 0.0, 0.0)
        self.restart = None
        self.emit("set_piece", r.team, taker.x, taker.y, player=taker.id, outcome=None)
        if r.team != self.poss_team:
            self.emit("possession_change", r.team, taker.x, taker.y, player=taker.id)
        self.give(taker.id)
        self.hold_until = self.t + self.rng.uniform(0.5, 1.5)
        self.throw_by = taker.id if r.kind == "throw_in" else None

    # ---- tick ---------------------------------------------------------------

    def shape_target(self, p: Player) -> tuple[float, float, float]:
        """Where a player off the ball wants to be, and how fast they go there."""
        chase = self.chase.get(p.team)
        # Targets stay on the pitch so players brake for the line instead of stopping dead at it.
        if chase and chase[0] == p.id:
            return clamp(chase[1], 0.5, PITCH_X - 0.5), clamp(chase[2], 0.5, PITCH_Y - 0.5), SPRINT
        if self.restart and p.id == self.restart.taker:
            return clamp(self.restart.x, 0.5, PITCH_X - 0.5), clamp(self.restart.y, 0.5, PITCH_Y - 0.5), JOG
        bx, by = self.ball[0], self.ball[1]
        poss_team = self.team_of(self.possessor) if self.possessor else None
        shift = (clamp(bx, 0, PITCH_X) - PITCH_X / 2) * 0.45
        push = 6 * attack_dir(p.team) if poss_team == p.team else -4 * attack_dir(p.team)
        tx = clamp(p.ax + shift + push, 2, PITCH_X - 2) if p.role != "GK" else p.ax
        ty = p.ay + (clamp(by, 0, PITCH_Y) - p.ay) * 0.25
        carrier = self.by_id.get(self.possessor) if self.possessor else None
        if carrier and p.team != carrier.team and p.role != "GK":
            closest = self.nearest(carrier.x, carrier.y, p.team)
            in_zone = math.hypot(carrier.x - p.ax, carrier.y - p.ay) < 18
            if closest.id == p.id and in_zone:
                return carrier.x, carrier.y, PRESS
        return tx, ty, JOG

    def move_players(self) -> None:
        for p in self.players:
            if p.id == self.moved:
                continue
            if p.id == self.possessor:  # won the ball this frame: keeps running, slowing to a dribble
                steer(p, p.x + p.vx * 0.5, p.y + p.vy * 0.5, DRIBBLE)
                continue
            tx, ty, top = self.shape_target(p)
            steer(p, tx, ty, top)

    def tick_carrier(self) -> None:
        carrier = self.by_id[self.possessor]
        self.moved = carrier.id
        if self.throw_by == carrier.id:  # Law 15: thrown from where it went out, not dribbled
            steer(carrier, carrier.x, carrier.y, DRIBBLE)
            self.ball = (carrier.x, carrier.y, 0.0, 0.0, 0.0, 0.0)
            if self.t >= self.hold_until:
                self.throw_by = None
                self.decide(carrier, throw=True)
            return
        team, opp = carrier.team, other(carrier.team)
        gx = goal_x(team)
        presser = self.nearest(carrier.x, carrier.y, opp)
        gap = math.hypot(presser.x - carrier.x, presser.y - carrier.y)
        if gap > 6:
            steer(carrier, gx, carrier.y + (PITCH_Y / 2 - carrier.y) * 0.3, DRIBBLE)
        else:
            steer(carrier, carrier.x, carrier.y, DRIBBLE)
        # The ball settles at the carrier's feet (from a keeper's hands, down to the ground)
        # rather than jumping there.
        bx, by, bz = self.ball[0], self.ball[1], self.ball[2]
        dx, dy, dz = carrier.x - bx, carrier.y - by, -bz
        d = math.sqrt(dx * dx + dy * dy + dz * dz)
        step = min(d, BALL_TO_FEET * DT)
        if d > 1e-6:
            bx, by, bz = bx + dx / d * step, by + dy / d * step, bz + dz / d * step
        self.ball = (bx, by, max(bz, 0.0), carrier.vx, carrier.vy, 0.0)
        if gap < 2.0 and self.t - self.pressed.get(opp, -99) > 8:
            self.pressed[opp] = self.t
            self.emit("pressure", opp, presser.x, presser.y, player=presser.id, receiver=carrier.id)
        if gap < 1.5 and self.rng.random() < 0.07 * DT:
            self.emit("tackle", opp, bx, by, player=presser.id, receiver=carrier.id, outcome="success")
            self.emit("possession_change", opp, bx, by, player=presser.id)
            self.give(presser.id)
            return
        if gap < 3:
            self.hold_until = min(self.hold_until, self.t + 2.4)
        if self.t >= self.hold_until:
            self.decide(carrier)

    def snapshot(self) -> None:
        bx, by, bz = self.ball[0], self.ball[1], self.ball[2]
        self.match.frames.append({
            "frame": self.frame,
            "t": round(self.t, 3),
            "ball": {"x": round(bx, 3), "y": round(by, 3), "z": round(bz, 3)},
            "possessor": self.possessor,
            "players": [{"id": p.id, "team": p.team, "x": round(p.x, 3), "y": round(p.y, 3)}
                        for p in self.players],
        })

    def run(self, minutes: float) -> Match:
        self.kickoff("home")
        total = int(minutes * 60 * FPS)
        for _ in range(total):
            self.moved = None
            if self.possessor:
                self.tick_carrier()
            elif self.restart:
                self.tick_restart()
            else:
                self.tick_free()
            self.move_players()
            self.snapshot()
            self.t += DT
            self.frame += 1
        return self.match


def simulate(seed: int, minutes: float) -> Match:
    return Engine(seed).run(minutes)
