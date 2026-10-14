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

from ninety.sim import ball, decisions, perception
from ninety.sim.body import BRAKE_MAX, CS_MEAN, D0, F0_MEAN, V0_MEAN, Body
from ninety.sim.body import move as move_body
from ninety.sim.profiles import Profile
from ninety.sim.team import TeamBrain

PITCH_X, PITCH_Y = 105.0, 68.0
FPS = 25
DT = 1.0 / FPS
# How fast a player chooses to go (design; step 3 turns these into decisions). What they can
# reach is limited by their own body (ninety/sim/body.py): acceleration, top speed, energy.
SPRINT = 99.0  # as fast as their body allows
RECOVER = 6.0  # running back into position from far away
PRESS = 6.0  # closing down the ball carrier
SHAPE = 3.0  # adjusting position, below critical speed so it can be sustained
FAR_OUT_OF_POSITION_M = 10.0
DRIBBLE = 2.5
DECIDE_EVERY = 6  # frames between the ball carrier's decisions (about 4 a second)
PERCEIVE_EVERY = 6  # frames between a player's looks at the pitch (about 4 a second, staggered)
BRAIN_EVERY = 12  # frames between a team brain's reads of the game (about 2 a second)
ENGAGE_M = 20.0  # design: the first presser goes to the ball when it is this close
COVER_M = 8.0  # design: the covering player stays this far behind the presser, goal-side
PERCEPTION_ERR = 0.03  # verify: m/s of misjudged ball velocity per metre between player and ball
CONTROL_M = 1.0  # a foot reaches this far from the body's centre
FOOT_REACH_Z = 1.0  # outfield players can play the ball below this height
HAND_REACH_Z = 2.8  # P11: a jumping keeper's hand reach (standing about 2.35 m plus the jump)
KEEPER_STAND_REACH_M = 1.0  # P11: a keeper's sideways arm reach from the body's centre
KEEPER_DIVE_EXTRA_M = 0.8  # P11: added as the dive stretches out, hips to fingertips about 1.8 m
DIVE_TIME_S = 0.5  # P11: design; a full dive to the post takes about 1 s including body travel
BODY_RADIUS = 0.26  # P11: half a footballer's shoulder width (about 0.53 m over the deltoids)
BODY_HEIGHT = 1.8
PRESS_GAP_M = 1.0  # verify: how close a presser stands, goal-side of the ball carrier
PERSONAL_SPACE_M = 1.2  # players steer to keep about this far from each other
SHOULDER_TO_SHOULDER_M = 0.52  # P11: centres of two players in contact, shoulder to shoulder
ANTICIPATE_S = 0.4  # verify: how far ahead players judge where others will be
BODY_RESTITUTION = 0.3  # verify: share of the ball's speed into a body that it keeps
PRESSURE_M = 3.0  # design: an opponent this close puts the kicker under full pressure
MAX_STRIKE_MPS = 36.0  # design: the hardest a foot strikes a ball, below the 40 m/s check (P3)
WEAK_SIDE_DEG = 30.0  # design: a kick this far to the weaker foot's side is struck with it
MISCONTROL_KEEP = 0.4  # verify: share of speed a ball keeps off a failed touch or a parry
POST_RADIUS = 0.06  # Law 1: posts and crossbar at most 12 cm wide
WOODWORK_RESTITUTION = 0.6  # verify
BALL_TO_FEET = 12.0  # m/s: how fast the ball settles at a new carrier's feet
LOFT_OVER_M = 25.0  # passes longer than this go through the air
THROW_WAIT_S = 6.0  # design: with nobody free, a thrower waits this long, then throws down the line
CHASE_EVERY = 4  # frames between re-planning who chases a free ball
GOAL_HALF_WIDTH, CROSSBAR = 3.66, 2.44  # Law 1
PENALTY_DEPTH, PENALTY_HALF_WIDTH = 16.5, 20.16  # Law 1
GOAL_AREA_X = 5.5  # Law 1
PASS_SPEED_EST_MPS = 15.0  # design: the passer's rough guess of a pass's average speed, to lead a runner
LEAD_MAX_S = 2.0  # design: and he leads him by at most this long
# Laws 15 to 17: opponents keep this far from a restart until the ball is in play.
RESTART_DISTANCE_M = {"throw_in": 2.0, "corner": 9.15, "goal_kick": PENALTY_DEPTH - GOAL_AREA_X + 1.0}
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
    physique: Body = field(default_factory=lambda: Body(F0_MEAN, V0_MEAN, CS_MEAN))
    heading: float = 0.0  # radians: which way he faces (and so what he can see)
    profile: Profile | None = None


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


def steer(p: Player, tx: float, ty: float, want_speed: float) -> None:
    """Move toward a target within the player's own body: force-velocity acceleration, braking,
    a shared grip limit for braking and turning, and energy (ninety/sim/body.py)."""
    x, y, p.vx, p.vy = move_body(p.x, p.y, p.vx, p.vy, tx, ty, want_speed, p.physique, DT)
    # No wall at the lines: players may run past them, as in real matches. Targets stay on the
    # pitch, so they slow down and come back; only the advertising boards stop them, and then
    # the boards also stop the part of the run that goes into them.
    if not -BOARDS_M <= x <= PITCH_X + BOARDS_M:
        x, p.vx = clamp(x, -BOARDS_M, PITCH_X + BOARDS_M), 0.0
    if not -BOARDS_M <= y <= PITCH_Y + BOARDS_M:
        y, p.vy = clamp(y, -BOARDS_M, PITCH_Y + BOARDS_M), 0.0
    p.x, p.y = x, y


class Engine:
    def __init__(self, seed: int):
        self.rng = random.Random(seed)
        # Perception draws from its own stream, so a change to what players see does not
        # reshuffle every other random draw in the match.
        self.sight_rng = random.Random(f"{seed}-perception")
        self.match = Match(seed=seed)
        self.players: list[Player] = []
        for team in ("home", "away"):
            for n, (role, fx, fy) in enumerate(FORMATION):
                ax = fx * PITCH_X if team == "home" else (1 - fx) * PITCH_X
                ay = fy * PITCH_Y if team == "home" else (1 - fy) * PITCH_Y
                profile = Profile.generate(role, self.rng)
                self.players.append(Player(f"{team[0]}{n + 1}", team, role, ax, ay, ax, ay,
                                           physique=profile.physique(), profile=profile,
                                           heading=0.0 if team == "home" else math.pi))
        self.by_id = {p.id: p for p in self.players}
        self.match.roster = [{"id": p.id, "team": p.team, "role": p.role, "name": p.profile.name,
                              "foot": p.profile.foot, "traits": p.profile.traits,
                              "ratings": {a: p.profile.rating(a) for a in p.profile.attributes}}
                             for p in self.players]
        self.beliefs = {p.id: perception.Belief(next_scan=self.rng.uniform(0, 3)) for p in self.players}
        self.brains = {team: TeamBrain(team) for team in ("home", "away")}
        self.ball: ball.State = (PITCH_X / 2, PITCH_Y / 2, 0.0, 0.0, 0.0, 0.0)
        self.possessor: str | None = None
        self.last_touch: str | None = None
        self.kicked: dict | None = None  # the pass or shot event in flight, resolved when it ends
        self.kicked_at = -99.0
        self.kicker_clear = True  # the struck ball has left the kicker's body
        self.released_by: str | None = None  # Law 12: a keeper who released it may not handle it again
        # (x, y, strike): a carrier turning the ball onto his kicking side before he strikes it
        self.windup: tuple | None = None
        self.read: tuple[str, float] | None = None  # (keeper, y): where he reads a shot is going
        self.free_since = -99.0
        self.touched_since_kick = False
        self.chase: dict[str, tuple[str, float, float]] = {}  # team -> (player, x, y)
        self.restart: Restart | None = None
        self.throw_by: str | None = None  # a throw-in taker holding the ball until he throws it
        self.throw_ready = 0.0
        self.dribble_to: tuple[float, float] | None = None  # the carrier's chosen carry, if any
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

    def in_own_box(self, team: str, x: float, y: float) -> bool:
        own_line = PITCH_X - goal_x(team)
        return abs(x - own_line) <= PENALTY_DEPTH and abs(y - PITCH_Y / 2) <= PENALTY_HALF_WIDTH

    def hands(self, p: Player, x: float, y: float) -> bool:
        """Law 12: a keeper may handle the ball only inside his own penalty area; not again after
        releasing it until another player has touched it; and not from a team-mate's deliberate
        pass (a kick or a throw-in) that nobody else has touched."""
        k = self.kicked
        back_pass = bool(k) and k["type"] == "pass" and k["team"] == p.team and self.last_touch == k["player"]
        return (p.role == "GK" and self.in_own_box(p.team, x, y) and self.released_by != p.id
                and not back_pass)

    def reaction(self, p: Player) -> float:
        """Seconds before a player responds to the struck ball itself: a choice reaction (he must
        also pick a direction). A keeper's head start is a read of the kicker (`read`), which can
        be wrong; his reaction to the real ball still takes this long."""
        return p.profile.reaction()

    def reach(self, p: Player, x: float, y: float, at: float | None = None) -> tuple[float, float]:
        """How far and how high this player can reach for a ball at (x, y), at time `at`."""
        if self.hands(p, x, y):
            # A dive stretches the keeper's reach over time: standing arm's length at first, the
            # full stretch only once the dive has had time to unfold after he reacts to the
            # strike. A deflection does not un-stretch a dive already under way.
            at = self.t if at is None else at
            diving = clamp((at - self.free_since - self.reaction(p)) / DIVE_TIME_S, 0.0, 1.0)
            return KEEPER_STAND_REACH_M + KEEPER_DIVE_EXTRA_M * diving, HAND_REACH_Z
        return CONTROL_M, FOOT_REACH_Z

    def give(self, pid: str) -> None:
        if self.team_of(pid) != self.poss_team:
            self.pressed.clear()
            self.poss_team = self.team_of(pid)
        self.possessor = pid
        self.last_touch = pid
        if pid != self.released_by:
            self.released_by = None
        self.windup = None
        self.read = None
        self.touched_since_kick = False
        self.chase = {}
        # The first touch settles the ball before he can decide: quicker with a good first touch.
        self.hold_until = self.t + 0.3 + 0.3 * (1 - self.by_id[pid].profile["first_touch"])
        self.dribble_to = None

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

    def can_strike(self, carrier: Player, tx: float, ty: float) -> bool:
        """The ball is on the side of his body facing the target, so he can strike it there
        without the ball passing through him."""
        ox, oy = self.ball[0] - carrier.x, self.ball[1] - carrier.y
        if math.hypot(ox, oy) < 0.1:
            return True
        return ox * (tx - self.ball[0]) + oy * (ty - self.ball[1]) >= 0

    def turn_to(self, carrier: Player, tx: float, ty: float, strike) -> None:
        """He turns, taking the ball round to his kicking side; the strike waits until it is there."""
        carrier.heading = math.atan2(ty - carrier.y, tx - carrier.x)
        self.windup = (tx, ty, strike)

    def kick(self, carrier: Player, vx: float, vy: float, vz: float) -> None:
        # Struck from where the ball is, at the carrier's feet on the side he faces. A ball moving
        # away from a body never meets it (contact checks approach), so no placement is needed.
        self.ball = (self.ball[0], self.ball[1], self.ball[2], vx, vy, vz)
        self.released_by = carrier.id
        self.throw_by = None  # a throw-in ends when the ball is thrown
        self.possessor = None
        self.last_touch = carrier.id
        self.kicked_at = self.t
        self.free_since = self.t  # the ball left a player's control: dives are timed from here
        self.kicker_clear = False
        self.chase = {}  # everyone reacts after their reaction time, not on the frame of the kick

    def execute(self, p: Player, vx: float, vy: float, vz: float, skill: str) -> tuple[float, float, float]:
        """The kick as struck, not as intended: direction, speed and launch angle scatter by the
        player's own error, which grows with ball speed, pressure, fatigue and the weaker foot
        and shrinks with skill (profiles.Profile.kick_error, docs/GROUNDING.md A3)."""
        ground = math.hypot(vx, vy)
        speed = math.sqrt(ground * ground + vz * vz)
        if speed < 1e-6:
            return vx, vy, vz
        nearest = min(math.hypot(q.x - p.x, q.y - p.y) for q in self.players if q.team != p.team)
        pressure = clamp((PRESSURE_M - nearest) / PRESSURE_M, 0.0, 1.0)
        # Which foot: the kick's direction against the way he faces (a state; P13).
        turn = math.degrees((math.atan2(vy, vx) - p.heading + math.pi) % (2 * math.pi) - math.pi)
        weak = (turn > WEAK_SIDE_DEG) if p.profile.foot == "right" else (turn < -WEAK_SIDE_DEG)
        fresh = p.physique.ceiling / D0  # the slow store: fatigue over the match, not one sprint
        dir_sd, speed_sd, loft_sd = p.profile.kick_error(skill, speed, pressure, fresh, weak)
        angle = math.atan2(vy, vx) + math.radians(self.rng.gauss(0, dir_sd))
        loft = math.atan2(vz, ground) + (math.radians(self.rng.gauss(0, loft_sd)) if vz > 0 else 0.0)
        # A mishit can carry almost nothing (floor: design); no strike exceeds a foot's limit.
        speed *= max(0.3, 1 + self.rng.gauss(0, speed_sd)) * (p.profile.weak_foot_speed() if weak else 1.0)
        speed = min(speed, MAX_STRIKE_MPS)
        ground, up = speed * math.cos(loft), speed * math.sin(loft)  # a low drive may go into the turf
        return ground * math.cos(angle), ground * math.sin(angle), up

    def aim(self, sx: float, sy: float, tx: float, ty: float, ground: float, up: float):
        d = math.hypot(tx - sx, ty - sy) or 1.0
        return (tx - sx) / d * ground, (ty - sy) / d * ground, up

    def shoot(self, carrier: Player) -> None:
        team = carrier.team
        gx = goal_x(team)
        if not self.can_strike(carrier, gx, PITCH_Y / 2):
            self.turn_to(carrier, gx, PITCH_Y / 2, lambda: self.shoot(carrier))
            return
        bx, by = self.ball[0], self.ball[1]
        # The aim (which corner, how high, how hard) is a choice; missing it is execution error.
        side = self.rng.choice([-1, 1])
        ty = PITCH_Y / 2 + side * self.rng.uniform(0.5, 3.2)
        tz = self.rng.uniform(0.1, 2.0)
        speed = self.rng.uniform(70, 120) / 3.6
        ground, up = ball.shot(math.hypot(gx - bx, ty - by), speed, tz, DT)
        # The keeper reads the kicker's body and starts toward where he thinks it is going,
        # before he can react to the ball itself; the read can be wrong (A2).
        keeper = self.keeper(other(team))
        self.read = (keeper.id, ty + self.rng.gauss(0, keeper.profile.read_error_m()))
        vx, vy, vz = self.execute(carrier, *self.aim(bx, by, gx, ty, ground, up), "finishing")
        speed = math.sqrt(vx * vx + vy * vy + vz * vz)
        # Outcome and end point are observed: set when the ball is touched, goes out or goes in.
        self.kicked = self.emit("shot", team, bx, by, player=carrier.id, ball_speed_kmh=round(speed * 3.6, 1))
        self.kick(carrier, vx, vy, vz)

    def pass_to(self, carrier: Player, tx: float, ty: float, lofted: bool, throw: bool = False) -> None:
        """Kick toward a point the carrier chose (where he believes a team-mate will be, or space)."""
        if not self.can_strike(carrier, tx, ty):
            self.turn_to(carrier, tx, ty, lambda: self.pass_to(carrier, tx, ty, lofted, throw))
            return
        bx, by = self.ball[0], self.ball[1]
        dist = math.hypot(tx - bx, ty - by)
        # Struck as the decision estimated it (decisions.py); execution error is added on top.
        if throw or lofted:
            ground, up = decisions.loft_launch(dist)
        else:
            ground, up = decisions.launch_speed(dist), 0.0
        wide = abs(ty - PITCH_Y / 2) > 20 and (tx - bx) * attack_dir(carrier.team) > 0
        skill = "crossing" if (dist > LOFT_OVER_M and wide) else "passing"
        vx, vy, vz = self.execute(carrier, *self.aim(bx, by, tx, ty, ground, up), skill)
        # Receiver, end point and outcome are filled in when someone takes the ball or it goes out.
        self.kicked = self.emit("pass", carrier.team, bx, by, player=carrier.id,
                                ball_speed_kmh=round(math.sqrt(vx * vx + vy * vy + vz * vz) * 3.6, 1))
        self.kick(carrier, vx, vy, vz)

    def scene_for(self, carrier: Player) -> decisions.Scene:
        """The carrier's picture of the game, built only from what he believes."""
        team, opp = carrier.team, other(carrier.team)
        belief = self.beliefs[carrier.id]
        mates = []
        for q in self.players:
            if q.team == team and q.id != carrier.id:
                at = belief.where(q.id, self.t)
                if at:  # a team-mate he has not seen cannot be picked
                    mates.append((q.id, at[0], at[1], belief.age(q.id, self.t)))
        their_keeper = self.keeper(opp).id
        opps = [w for w in (belief.where(q.id, self.t) for q in self.players
                            if q.team == opp and q.id != their_keeper) if w]  # the keeper counts once
        keeper = belief.where(their_keeper, self.t)
        diff = self.match.score[team] - self.match.score[opp]
        risk = clamp(-diff * self.t / 5400, -1.0, 1.0)  # chase the game when behind late, protect when ahead
        prof = carrier.profile
        scene = decisions.Scene(self.ball[0], self.ball[1], goal_x(team), mates, opps, keeper,
                                prof["decisions"], prof["composure"], prof["dribbling"],
                                tuple(prof.traits), risk,
                                current="dribble" if self.dribble_to else "hold")
        return scene

    def decide(self, carrier: Player, throw: bool = False) -> None:
        """The carrier chooses from what he believes (ninety/sim/decisions.py)."""
        scene = self.scene_for(carrier)
        if throw:  # Law 15: a throw goes to a team-mate, not at goal, and is never dribbled
            scene.throw = True
            scene.mates = [m for m in scene.mates if math.hypot(m[1] - scene.x, m[2] - scene.y) <= 25]
            choice = max(decisions.options(scene), key=lambda o: o.value, default=None)
            if choice:
                self.pass_to(carrier, *choice.target, lofted=True, throw=True)
            elif self.t - self.throw_ready > THROW_WAIT_S:  # nobody free: into space down the line
                line = 3.0 if scene.y < PITCH_Y / 2 else PITCH_Y - 3.0
                self.pass_to(carrier, clamp(scene.x + attack_dir(carrier.team) * 15, 1, PITCH_X - 1), line,
                             lofted=True, throw=True)
            else:
                self.hold_until = self.t + 0.5  # he looks again
            return
        choice = decisions.choose(scene, self.rng)
        if choice.kind == "pass" or choice.kind == "clear":
            self.pass_to(carrier, *choice.target, lofted=choice.lofted)
        elif choice.kind == "shoot":
            self.shoot(carrier)
        elif choice.kind == "dribble":
            self.dribble_to = choice.target
        else:
            self.dribble_to = None  # hold: keep the ball, shield it

    # ---- the free ball: who can get there first ------------------------------

    def plan_chase(self) -> None:
        """Each team sends the player who thinks they can reach the ball's path first. Each player
        judges the ball's velocity with an error that grows with their distance from it, and the
        judgement is renewed (and sharpens) every few frames as the ball comes closer."""
        if self.t - self.kicked_at < min(self.reaction(p) for p in self.players):
            return
        path = ball.predict(self.ball, DT, 6.0)
        best: dict[str, tuple[float, str, float, float]] = {}
        for p in self.players:
            if self.kicked and p.id == self.kicked["player"] and not self.touched_since_kick:
                continue  # the kicker moves on; he does not run after his own pass or shot
            if self.t - self.kicked_at < self.reaction(p):
                continue  # has not yet reacted to this strike
            sigma = PERCEPTION_ERR * math.hypot(self.ball[0] - p.x, self.ball[1] - p.y)
            ex, ey = self.rng.gauss(0, sigma), self.rng.gauss(0, sigma)
            for k in range(0, len(path), 2):
                t = k * DT
                bx, by, bz = path[k][0] + ex * t, path[k][1] + ey * t, path[k][2]
                reach_m, reach_z = self.reach(p, bx, by, at=self.t + t)
                if bz > reach_z:
                    continue
                dx, dy = bx - p.x, by - p.y
                gap = math.hypot(dx, dy) - reach_m
                along = (p.vx * dx + p.vy * dy) / (math.hypot(dx, dy) or 1.0)
                # Running away from the point, he must first brake to a stop (time and distance).
                brake_t = max(0.0, -along) / BRAKE_MAX
                extra = min(0.0, along) ** 2 / (2 * BRAKE_MAX)
                reachable = gap + extra <= p.physique.distance_in(t - brake_t, max(0.0, along))
                if reachable or k + 2 >= len(path):
                    arrive = t if reachable else p.physique.time_to_cover(gap, along)
                    if p.team not in best or arrive < best[p.team][0]:
                        best[p.team] = (arrive, p.id, bx, by)
                    break
        self.chase = {team: (pid, x, y) for team, (_, pid, x, y) in best.items()}

    def tick_free(self) -> None:
        before = self.ball
        self.ball = ball.step(before, DT)
        self.woodwork(before)
        if self.went_out(before):
            return
        if self.frame % CHASE_EVERY == 0:
            self.plan_chase()
        self.contact(before)

    def contact(self, before: ball.State) -> None:
        """The ball meets whoever is on its path this frame: a body deflects it at any time; a
        deliberate touch, after reaction time, controls it if it is slow enough to absorb."""
        x0, y0 = before[0], before[1]
        x1, y1, z1 = self.ball[0], self.ball[1], self.ball[2]
        dx, dy = x1 - x0, y1 - y0
        seg = dx * dx + dy * dy
        kicker = self.by_id.get(self.last_touch) if self.last_touch else None
        clear_of_body = kicker and math.hypot(x1 - kicker.x, y1 - kicker.y) > BODY_RADIUS + ball.RADIUS
        if not self.kicker_clear and clear_of_body:
            self.kicker_clear = True
        since = self.t - self.kicked_at
        hits = []
        for p in self.players:
            if p is kicker and not self.kicker_clear:
                continue
            s = 0.0 if seg == 0 else clamp(((p.x - x0) * dx + (p.y - y0) * dy) / seg, 0.0, 1.0)
            cx, cy = x0 + s * dx, y0 + s * dy
            cz = before[2] + s * (z1 - before[2])
            d = math.hypot(cx - p.x, cy - p.y)
            # The ball meets a body only if it is moving toward it, relative to the player.
            closing = (self.ball[3] - p.vx) * (p.x - cx) + (self.ball[4] - p.vy) * (p.y - cy)
            slow = math.hypot(self.ball[3] - p.vx, self.ball[4] - p.vy) < 1.0
            reach_m, reach_z = self.reach(p, cx, cy)
            if since >= self.reaction(p) and d <= reach_m and cz <= reach_z and (closing > 0 or slow):
                hits.append((s, "touch", p, cx, cy, cz))
            elif d <= BODY_RADIUS + ball.RADIUS and cz <= BODY_HEIGHT and closing > 0:
                hits.append((s, "body", p, cx, cy, cz))
        if not hits:
            return
        s, kind, p, cx, cy, cz = min(hits, key=lambda h: h[0])
        vx, vy, vz = self.ball[3], self.ball[4], self.ball[5]
        rel = math.sqrt((vx - p.vx) ** 2 + (vy - p.vy) ** 2 + vz * vz)
        absorb = p.profile.absorb_mps(self.hands(p, cx, cy))
        controls = kind == "touch" and rel <= absorb
        self.touched(p, cx, cy, controls)  # judged on the ball as it arrived
        if controls:
            self.ball = (cx, cy, cz, p.vx, p.vy, 0.0)
            if p.team != self.poss_team:
                self.emit("possession_change", p.team, cx, cy, player=p.id)
            self.give(p.id)
            return
        self.deflect(p, cx, cy, cz, MISCONTROL_KEEP if kind == "touch" else BODY_RESTITUTION)

    def deflect(self, p: Player, cx: float, cy: float, cz: float, keep: float) -> None:
        """The ball bounces off a player (a block, a parry, a heavy touch) and stays free. In the
        player's frame, the part of the ball's velocity into the body reverses and keeps `keep`
        of its speed; the part along the body is unchanged."""
        rx, ry, vz = self.ball[3] - p.vx, self.ball[4] - p.vy, self.ball[5]
        nx, ny = cx - p.x, cy - p.y
        n = math.hypot(nx, ny)
        if n > 1e-6:
            nx, ny = nx / n, ny / n
        else:  # dead centre: it comes straight back
            speed = math.hypot(rx, ry) or 1.0
            nx, ny = -rx / speed, -ry / speed
        into = rx * nx + ry * ny
        if into < 0:
            rx, ry = rx - (1 + keep) * into * nx, ry - (1 + keep) * into * ny
        # It leaves from outside the body, never from inside it (the swept contact can overlap).
        out = max(math.hypot(cx - p.x, cy - p.y), BODY_RADIUS + ball.RADIUS) + 0.05
        self.ball = (p.x + nx * out, p.y + ny * out, cz, rx + p.vx, ry + p.vy, vz)
        self.emit("deflection", p.team, cx, cy, player=p.id)  # a touch is ground truth too
        self.last_touch = p.id
        self.kicker_clear = False
        self.kicked_at = self.t  # a new strike of the ball: everyone reacts to it again
        self.chase = {}

    def touched(self, p: Player, x: float, y: float, controls: bool) -> None:
        """Resolve the pass or shot in flight from who touched it, and how: observed, never
        intended. Called with the ball as it arrived, before the touch changes it."""
        self.touched_since_kick = True
        if p.id != self.released_by:
            self.released_by = None
        kicked = self.kicked
        if not kicked:
            return
        same_team = p.team == kicked["team"]
        if kicked["type"] == "pass":
            if same_team and controls:
                kicked.update(receiver=p.id, end_x=round(x, 2), end_y=round(y, 2), outcome="success")
                self.kicked = None
            elif not same_team and controls:
                kicked.update(receiver=p.id, end_x=round(x, 2), end_y=round(y, 2), outcome="fail")
                self.emit("interception", p.team, x, y, player=p.id)
                self.kicked = None
            return  # a deflection by anyone leaves the pass in flight until someone controls it
        if same_team and not controls:
            return  # a team-mate's deflection leaves the shot in flight
        on_target = self.heading_on_target(kicked["team"])
        if not same_team and p.role != "GK":
            outcome = "blocked"
        else:
            outcome = "on_target" if on_target else "off_target"
        kicked.update(end_x=round(x, 2), end_y=round(y, 2), outcome=outcome)
        self.kicked = None

    @staticmethod
    def in_goal(y: float, z: float) -> bool:
        """Law 10: the whole ball between the posts and under the bar (z is its lowest point)."""
        return abs(y - PITCH_Y / 2) < GOAL_HALF_WIDTH - ball.RADIUS and z + 2 * ball.RADIUS < CROSSBAR

    def heading_on_target(self, team: str) -> bool:
        """Law 10: would the ball, untouched from here, have crossed between the posts and under
        the bar of the goal this team attacks?"""
        line = goal_x(team)
        path = ball.predict(self.ball, DT, 4.0)
        for a, b in zip(path, path[1:], strict=False):
            if (a[0] - line) * (b[0] - line) <= 0 and a[0] != b[0]:
                s = (line - a[0]) / (b[0] - a[0])
                return self.in_goal(a[1] + s * (b[1] - a[1]), a[2] + s * (b[2] - a[2]))
        return False

    def woodwork(self, before: ball.State) -> None:
        """Law 1: the ball rebounds off a post or the crossbar where it meets the goal line."""
        for line in (0.0, PITCH_X):
            x0, x1 = before[0], self.ball[0]
            if (x0 - line) * (x1 - line) > 0 or x0 == x1:
                continue
            s = (line - x0) / (x1 - x0)
            y = before[1] + s * (self.ball[1] - before[1])
            zc = before[2] + s * (self.ball[2] - before[2]) + ball.RADIUS  # the ball's centre
            off_centre = abs(y - PITCH_Y / 2)
            touching = ball.RADIUS + POST_RADIUS
            hits_post = abs(off_centre - GOAL_HALF_WIDTH) <= touching and zc <= CROSSBAR
            hits_bar = off_centre <= GOAL_HALF_WIDTH and abs(zc - CROSSBAR) <= touching
            if hits_post or hits_bar:
                vx, vy, vz = self.ball[3], self.ball[4], self.ball[5]
                vx = -vx * WOODWORK_RESTITUTION
                if hits_bar:
                    vz = -vz * WOODWORK_RESTITUTION if zc < CROSSBAR else abs(vz) * WOODWORK_RESTITUTION
                bx = line + (0.15 if line == 0.0 else -0.15)
                self.ball = (bx, y, max(zc - ball.RADIUS, 0.0), vx, vy, vz)
                self.kicked_at = self.t
                self.chase = {}
                return

    def went_out(self, before: ball.State) -> bool:
        """Law 9: out once the whole ball has crossed a goal line or touchline. Where and how high
        it crossed is taken at the line, not wherever the ball is a frame later."""
        bx, by, bz = self.ball[0], self.ball[1], self.ball[2]
        r = ball.RADIUS
        over_goal_line = bx < -r or bx > PITCH_X + r
        if not over_goal_line and -r <= by <= PITCH_Y + r:
            return False
        if over_goal_line and before[0] != bx:
            line = -r if bx < 0 else PITCH_X + r
            s = clamp((line - before[0]) / (bx - before[0]), 0.0, 1.0)
            by, bz = before[1] + s * (by - before[1]), before[2] + s * (bz - before[2])
        last_team = self.team_of(self.last_touch) if self.last_touch else "home"
        kicked = self.kicked
        self.kicked = None
        x, y = clamp(bx, 0, PITCH_X), clamp(by, 0, PITCH_Y)
        if kicked:
            kicked.update(end_x=round(x, 2), end_y=round(y, 2))
            if kicked["type"] == "pass":
                kicked["outcome"] = "fail"
            elif not (over_goal_line and self.in_goal(by, bz)):
                kicked["outcome"] = "off_target"
        self.chase = {}
        if over_goal_line:
            attackers = "home" if bx > PITCH_X / 2 else "away"
            if self.in_goal(by, bz):
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
        self.throw_ready = self.t

    # ---- tick ---------------------------------------------------------------

    def shape_target(self, p: Player) -> tuple[float, float, float]:
        """Where a player off the ball wants to be, and how fast they go there."""
        chase = self.chase.get(p.team)
        # Targets stay on the pitch so players brake for the line instead of stopping dead at it.
        if chase and chase[0] == p.id:
            return clamp(chase[1], 0.5, PITCH_X - 0.5), clamp(chase[2], 0.5, PITCH_Y - 0.5), SPRINT
        if self.read and self.read[0] == p.id and self.possessor is None and self.kicked:
            line = PITCH_X - goal_x(p.team)
            x = line + attack_dir(p.team) * min(abs(p.x - line), 1.0)  # across his line, not off it
            post = PITCH_Y / 2 - GOAL_HALF_WIDTH, PITCH_Y / 2 + GOAL_HALF_WIDTH
            return x, clamp(self.read[1], *post), SPRINT
        if self.restart and p.id == self.restart.taker:
            r = self.restart
            return clamp(r.x, 0.5, PITCH_X - 0.5), clamp(r.y, 0.5, PITCH_Y - 0.5), RECOVER
        bx, by = self.ball[0], self.ball[1]
        poss_team = self.team_of(self.possessor) if self.possessor else None
        shift = (clamp(bx, 0, PITCH_X) - PITCH_X / 2) * 0.45
        push = 6 * attack_dir(p.team) if poss_team == p.team else -4 * attack_dir(p.team)
        tx = clamp(p.ax + shift + push, 2, PITCH_X - 2) if p.role != "GK" else p.ax
        ty = p.ay + (clamp(by, 0, PITCH_Y) - p.ay) * 0.25
        brain = self.brains[p.team]
        if not brain.in_possession and p.role != "GK":
            own = PITCH_X - goal_x(p.team), PITCH_Y / 2
            d = math.hypot(own[0] - bx, own[1] - by) or 1.0
            gx, gy = (own[0] - bx) / d, (own[1] - by) / d  # from the ball toward our goal
            def on_pitch(x: float, y: float) -> tuple[float, float]:
                return clamp(x, 0.5, PITCH_X - 0.5), clamp(y, 0.5, PITCH_Y - 0.5)
            gap = PRESS_GAP_M
            if self.restart and self.restart.team != p.team:  # Laws 15 to 17: stand off the restart
                gap = RESTART_DISTANCE_M[self.restart.kind]
            presser = self.by_id[brain.pressers[0]] if brain.pressers else None
            engaged = presser is not None and math.hypot(bx - presser.x, by - presser.y) < ENGAGE_M
            if presser is p and engaged:
                # Press goal-side: between the ball and the goal being defended, a step away.
                return *on_pitch(bx + gx * gap, by + gy * gap), PRESS
            if engaged and brain.pressers[1:2] == [p.id]:  # cover: behind the presser, goal-side
                return *on_pitch(bx + gx * max(COVER_M, gap + 2), by + gy * max(COVER_M, gap + 2)), RECOVER
            slot = brain.slot(p.role, p.ay, clamp(by, 0, PITCH_Y))
            if slot:
                tx, ty = slot
        far = math.hypot(tx - p.x, ty - p.y) > FAR_OUT_OF_POSITION_M
        return tx, ty, RECOVER if far else SHAPE

    def perceive_and_think(self) -> None:
        """Players look at the pitch about four times a second, staggered so they do not all look
        on the same frame; each team brain reads the game about twice a second."""
        bx, by = self.ball[0], self.ball[1]
        states = [(p.id, p.x, p.y, p.vx, p.vy) for p in self.players]
        for i, p in enumerate(self.players):
            if (self.frame + i) % PERCEIVE_EVERY == 0:
                others = [st for st in states if st[0] != p.id]
                perception.observe(self.beliefs[p.id], (p.x, p.y, p.heading), others, self.t,
                                   self.sight_rng, p.profile.view_half_angle(), p.profile.scan_interval())
        holder = self.restart.team if self.restart else self.poss_team
        for k, (team, brain) in enumerate(self.brains.items()):
            if (self.frame + k * BRAIN_EVERY // 2) % BRAIN_EVERY:
                continue
            reach = {}
            for p in self.players:
                if p.team != team or p.role == "GK":
                    continue
                dx, dy = bx - p.x, by - p.y
                d = math.hypot(dx, dy)
                along = (p.vx * dx + p.vy * dy) / (d or 1.0)
                reach[p.id] = p.physique.time_to_cover(d, along)
            brain.update(self.t, holder == team, bx, reach)

    def move_players(self) -> None:
        for p in self.players:
            if p.id == self.moved:
                continue
            if p.id == self.possessor:  # won the ball this frame: keeps running, slowing to a dribble
                steer(p, p.x + p.vx * 0.5, p.y + p.vy * 0.5, DRIBBLE)
                continue
            tx, ty, top = self.shape_target(p)
            dist = math.hypot(tx - p.x, ty - p.y)
            if dist > 1e-6:  # bend the running direction away from anyone about to be in the way
                ax, ay = self.avoid(p)
                ux, uy = (tx - p.x) / dist + ax, (ty - p.y) / dist + ay
                u = math.hypot(ux, uy) or 1.0
                tx, ty = p.x + ux / u * dist, p.y + uy / u * dist
            steer(p, tx, ty, top)
            p.heading = perception.facing(p.heading, p.vx, p.vy, p.x, p.y, self.ball[0], self.ball[1])
        self.separate()

    def avoid(self, p: Player) -> tuple[float, float]:
        """Players see each other coming: where two will be close a moment from now, each bends
        away, by more the closer they will be. Returned as a direction to add to the run."""
        px, py = p.x + p.vx * ANTICIPATE_S, p.y + p.vy * ANTICIPATE_S
        nx = ny = 0.0
        for q in self.players:
            if q is p:
                continue
            dx, dy = px - (q.x + q.vx * ANTICIPATE_S), py - (q.y + q.vy * ANTICIPATE_S)
            d = math.hypot(dx, dy)
            if 1e-6 < d < PERSONAL_SPACE_M:
                closeness = (PERSONAL_SPACE_M - d) / PERSONAL_SPACE_M  # 0 at the edge, 1 at contact
                w = 4 * closeness * closeness / d  # urgency grows sharply as contact nears
                nx, ny = nx + dx * w, ny + dy * w
        return nx, ny

    def separate(self) -> None:
        """Bodies in contact (shoulder to shoulder, SHOULDER_TO_SHOULDER_M between centres) brace:
        each stops closing on the other as fast as their own legs allow, never faster."""
        grip = BRAKE_MAX * DT
        for i, a in enumerate(self.players):
            for b in self.players[i + 1:]:
                dx, dy = b.x - a.x, b.y - a.y
                d = math.hypot(dx, dy)
                if d >= SHOULDER_TO_SHOULDER_M or d < 1e-6:
                    continue
                nx, ny = dx / d, dy / d
                closing = (a.vx - b.vx) * nx + (a.vy - b.vy) * ny
                if closing <= 0:
                    continue
                # Bracing shares each player's grip with the steering already done this frame.
                ea = min(closing / 2, max(0.0, grip - a.physique.grip_used))
                eb = min(closing / 2, max(0.0, grip - b.physique.grip_used))
                a.vx, a.vy = a.vx - nx * ea, a.vy - ny * ea
                b.vx, b.vy = b.vx + nx * eb, b.vy + ny * eb
                a.physique.grip_used += ea
                b.physique.grip_used += eb

    def tick_carrier(self) -> None:
        carrier = self.by_id[self.possessor]
        self.moved = carrier.id
        if self.throw_by == carrier.id:  # Law 15: thrown from where it went out, not dribbled
            steer(carrier, carrier.x, carrier.y, DRIBBLE)
            self.ball = (carrier.x, carrier.y, 0.0, 0.0, 0.0, 0.0)
            if self.t >= self.hold_until:
                self.decide(carrier, throw=True)
            return
        opp = other(carrier.team)
        presser = self.nearest(carrier.x, carrier.y, opp)  # who is physically there
        gap = math.hypot(presser.x - carrier.x, presser.y - carrier.y)
        if self.windup:  # turning the ball onto his kicking side
            steer(carrier, carrier.x, carrier.y, DRIBBLE)
        elif self.dribble_to:  # carrying the ball where he chose, as fast as his dribbling allows
            tx, ty = self.dribble_to
            steer(carrier, tx, ty, decisions.dribble_speed(carrier.profile["dribbling"]))
            if math.hypot(tx - carrier.x, ty - carrier.y) < 1.0:
                self.dribble_to = None
        else:  # holding: keeps the ball, shielding it
            steer(carrier, carrier.x, carrier.y, DRIBBLE)
        # The ball settles at the carrier's feet (from a keeper's hands, down to the ground)
        # rather than jumping there.
        # A controlled ball travels with the carrier, then closes the remaining gap relative to
        # them, to his feet on the side he faces.
        if not self.windup:  # turning to strike, he faces the target, not where he drifts
            carrier.heading = perception.facing(carrier.heading, carrier.vx, carrier.vy, carrier.x,
                                                carrier.y, carrier.x, carrier.y)
        feet = BODY_RADIUS + ball.RADIUS
        fx, fy = carrier.x + math.cos(carrier.heading) * feet, carrier.y + math.sin(carrier.heading) * feet
        bx, by, bz = self.ball[0] + carrier.vx * DT, self.ball[1] + carrier.vy * DT, self.ball[2]
        dx, dy, dz = fx - bx, fy - by, -bz
        d = math.sqrt(dx * dx + dy * dy + dz * dz)
        step = min(d, BALL_TO_FEET * DT)
        if d > 1e-6:
            bx, by, bz = bx + dx / d * step, by + dy / d * step, bz + dz / d * step
        before = self.ball
        self.ball = (bx, by, max(bz, 0.0), carrier.vx, carrier.vy, 0.0)
        if self.went_out(before):  # Law 9 applies to a ball at a player's feet too
            self.possessor = None
            return
        if gap < 2.0 and self.t - self.pressed.get(opp, -99) > 8:
            self.pressed[opp] = self.t
            self.emit("pressure", opp, presser.x, presser.y, player=presser.id, receiver=carrier.id)
        # A tackle needs the ball within the tackler's reach (the chance itself is step 4's duel).
        within_reach = math.hypot(presser.x - bx, presser.y - by) <= CONTROL_M
        if within_reach and self.rng.random() < 0.07 * DT:
            self.emit("tackle", opp, bx, by, player=presser.id, receiver=carrier.id, outcome="success")
            self.emit("possession_change", opp, bx, by, player=presser.id)
            self.give(presser.id)
            return
        if self.windup:
            if self.can_strike(carrier, self.windup[0], self.windup[1]):
                strike, self.windup = self.windup[2], None
                strike()
            return
        if self.t >= self.hold_until and (self.frame + int(carrier.id[1:])) % DECIDE_EVERY == 0:
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
            self.perceive_and_think()
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
