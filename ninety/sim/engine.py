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

from ninety.sim import ball, decisions, offball, perception, profiles
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
PRESS_GAP_M = 2.0  # design, verify: how close a presser stands (jockeys), goal-side of the ball carrier
PERSONAL_SPACE_M = 1.2  # players steer to keep about this far from each other
SHOULDER_TO_SHOULDER_M = 0.52  # P11: centres of two players in contact, shoulder to shoulder
ANTICIPATE_S = 0.4  # verify: how far ahead players judge where others will be
BODY_RESTITUTION = 0.3  # verify: share of the ball's speed into a body that it keeps
BODY_TOUCH_Z = 0.45  # above this, a ball he is under is a thigh, chest or head, not a foot
AERIAL_ABSORB = 0.5  # design: those kill about half the pace a foot does (A4), same first touch
TOUCH_POSE_S = 0.30  # how long the body shows the part that met the ball
PRESSURE_M = 3.0  # design: an opponent this close puts the kicker under full pressure
MAX_STRIKE_MPS = 36.0  # design: the hardest a foot strikes a ball, below the 40 m/s check (P3)
WEAK_SIDE_DEG = 30.0  # design: a kick this far to the weaker foot's side is struck with it
MISCONTROL_KEEP = 0.4  # verify: share of speed a ball keeps off a failed touch or a parry
POST_RADIUS = 0.06  # Law 1: posts and crossbar at most 12 cm wide
WOODWORK_RESTITUTION = 0.6  # verify
BALL_TO_FEET = 12.0  # m/s: how fast the ball settles at a new carrier's feet
LOFT_OVER_M = 25.0  # passes longer than this go through the air
# Dribbling is a run of touches (D6): the ball is pushed ahead and the dribbler runs onto it, so
# between touches it is free and a defender who gets there first wins it. All *design*, *verify*.
TOUCH_CLOSE_M = 0.8  # how far ahead a touch puts the ball with an opponent close
TOUCH_SPACE_M = 3.0  # how much further when he has space (nearest opponent 10 m or more)
TOUCH_GAP_S = 0.6  # how long the ball runs ahead before he is back on it
TOUCH_EXPECTED_DEG = 30.0  # a touch within this of his running line needs no new reaction
# Tackles (D8): a defender near the ball decides whether to commit; the lunge takes time, and it
# wins the ball only if his foot gets there before the carrier moves it (decisions.tackle_chance
# is the shared race). All *design*, *verify*.
OFF_BALANCE_S = 0.8  # a missed lunge leaves him out of the play this long
CLOSE_CONTROL_M = 3.0  # with an opponent this close, a carrier keeps the ball at his feet
CLOSE_CONTROL_PACE = 0.6  # and carries it at this share of his dribbling speed
COVER_M = 10.0  # a team-mate goal-side within this distance is cover to commit with
LAST_DITCH_M = 18.0  # this near his own goal a defender commits without cover
COMMIT_P = 0.6  # a defender commits only when he expects to win the race this often (aggression shifts it)
SHIELD_M = 3.0  # holding with an opponent this close, the carrier puts his body between them
EVADE_MPS = 3.0  # how fast a carrier pushes the ball away from a lunge, plus up to 2 m/s with dribbling
JOCKEY_LOOKAHEAD_S = 0.5  # a jockeying defender matches where the carrier is going, not where he is
POKE_MPS = 5.0  # how fast a tackled ball comes away
THROW_WAIT_S = 2.0  # design: nobody free, so he throws; a longer look is dead time in a clip
CHASE_EVERY = 4  # frames between re-planning who chases a free ball
GOAL_HALF_WIDTH, CROSSBAR = 3.66, 2.44  # Law 1
PENALTY_DEPTH, PENALTY_HALF_WIDTH = 16.5, 20.16  # Law 1
GOAL_AREA_X = 5.5  # Law 1
PASS_SPEED_EST_MPS = 15.0  # design: the passer's rough guess of a pass's average speed, to lead a runner
LEAD_MAX_S = 2.0  # design: and he leads him by at most this long
# Laws 15 to 17: opponents keep this far from a restart until the ball is in play.
RESTART_DISTANCE_M = {"throw_in": 2.0, "corner": 9.15, "goal_kick": PENALTY_DEPTH - GOAL_AREA_X + 1.0}
BOARDS_M = 4.0  # verify: advertising boards behind the lines stop a ball (and players) that go out
# A real corner can sit for twenty seconds. A clip gains nothing from that, so every restart is
# ready in one to two seconds. He still has to reach the spot.
RESTART_DELAY_S = {"throw_in": (1.0, 2.0), "goal_kick": (1.0, 2.0), "corner": (1.0, 2.0)}
THROW_BEHIND_M = 0.55  # Law 15: his body stands outside the touchline, feet on or behind it
THROW_SPOT_M = 0.25  # design: within this of his spot he throws from where he stands, still behind the line
THROW_SETTLED_MPS = BRAKE_MAX * DT  # he throws once one frame of braking would stop him (P2)
THROW_REACH_M = 0.28  # both hands reach toward the pitch; the ball is over or behind the line
THROW_HAND_Z = 1.85  # bottom of the ball just over the head (the centre sits one radius higher)

# 4-3-3 anchors for a team attacking toward x=105, as (x, y) fractions of the pitch.
FORMATION = [
    ("GK", 0.05, 0.50),
    ("RB", 0.25, 0.15),
    ("RCB", 0.20, 0.38),
    ("LCB", 0.20, 0.62),
    ("LB", 0.25, 0.85),
    ("RCM", 0.42, 0.30),
    ("CM", 0.38, 0.50),
    ("LCM", 0.42, 0.70),
    ("RW", 0.62, 0.15),
    ("ST", 0.66, 0.50),
    ("LW", 0.62, 0.85),
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


def throw_stand(x: float, line_y: float) -> tuple[float, float]:
    """Where the thrower stands: where the ball crossed, just outside that touchline."""
    outside = -THROW_BEHIND_M if line_y < PITCH_Y / 2 else PITCH_Y + THROW_BEHIND_M
    return clamp(x, 1.0, PITCH_X - 1.0), outside


def throw_hands(x: float, y: float) -> tuple[float, float, float]:
    """The ball in both hands, over the head, over or behind the touchline."""
    inward = 1.0 if y < PITCH_Y / 2 else -1.0
    return x, y + inward * THROW_REACH_M, THROW_HAND_Z


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
    def __init__(self, seed: int, strengths: dict[str, float] | None = None):
        self.rng = random.Random(seed)
        # Perception draws from its own stream, so a change to what players see does not
        # reshuffle every other random draw in the match.
        self.sight_rng = random.Random(f"{seed}-perception")
        self.match = Match(seed=seed)
        self.players: list[Player] = []
        self.strength = strengths or {team: profiles.team_strength(self.rng) for team in ("home", "away")}
        for team in ("home", "away"):
            for n, (role, fx, fy) in enumerate(FORMATION):
                ax = fx * PITCH_X if team == "home" else (1 - fx) * PITCH_X
                ay = fy * PITCH_Y if team == "home" else (1 - fy) * PITCH_Y
                profile = Profile.generate(role, self.rng, self.strength[team])
                self.players.append(
                    Player(
                        f"{team[0]}{n + 1}",
                        team,
                        role,
                        ax,
                        ay,
                        ax,
                        ay,
                        physique=profile.physique(),
                        profile=profile,
                        heading=0.0 if team == "home" else math.pi,
                    )
                )
        self.by_id = {p.id: p for p in self.players}
        self.match.roster = [
            {
                "id": p.id,
                "team": p.team,
                "role": p.role,
                "name": p.profile.name,
                "foot": p.profile.foot,
                "traits": p.profile.traits,
                "archetype": p.profile.archetype,
                "ratings": {a: p.profile.rating(a) for a in p.profile.attributes},
            }
            for p in self.players
        ]
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
        self.lunges: dict[str, float] = {}  # defender -> when his lunge reaches the ball
        self.evade_at: dict[str, float] = {}  # defender -> when the carrier reacts to his lunge
        self.off_balance: dict[str, float] = {}  # defender -> when he has recovered from a miss
        self.tackle: dict | None = None  # the tackle event whose outcome the next control decides
        self.dribbler: str | None = None  # a carrier who pushed the ball ahead and is running onto it
        self.read: tuple[str, float] | None = None  # (keeper, y): where he reads a shot is going
        self.shot_touched_by: str | None = None  # "keeper" or "defender": who got to the shot
        self.shot_was_on_target: bool | None = None  # was it going in when they first touched it?
        self.free_since = -99.0
        self.touched_since_kick = False
        self.chase: dict[str, tuple[str, float, float]] = {}  # team -> (player, x, y)
        self.restart: Restart | None = None
        self.throw_by: str | None = None  # a throw-in taker holding the ball until he throws it
        self.throw_ready = 0.0
        self.into_play = False  # released from behind the line; not a new out until it enters or falls away
        self.touch_show: dict[str, tuple[str, float]] = {}  # player -> (part, until)
        self.dive_show: dict[str, tuple[float, float]] = {}  # keeper -> (until, side)
        self.dribble_to: tuple[float, float] | None = None  # the carrier's chosen carry, if any
        self.intended: str | None = None  # the team-mate a pass was played to: he expects it
        self.runs: dict[str, tuple[float, float, float]] = {}  # runner -> (x, y, started at)
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
            "id": f"e{self._eid:05d}",
            "t": round(self.t, 2),
            "frame": self.frame,
            "type": type_,
            "team": team,
            "player": None,
            "receiver": None,
            "x": round(clamp(x, 0, PITCH_X), 2),
            "y": round(clamp(y, 0, PITCH_Y), 2),
            "end_x": None,
            "end_y": None,
            "outcome": None,
            "ball_speed_kmh": None,
            "source": "truth",
            "confidence": None,
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
        return p.role == "GK" and self.in_own_box(p.team, x, y) and self.released_by != p.id and not back_pass

    def reaction(self, p: Player) -> float:
        """Seconds before a player responds to the struck ball itself: a choice reaction (he must
        also pick a direction), or a simple one for the team-mate a pass was played to, who was
        expecting it (O5). A keeper's head start is a read of the kicker (`read`), which can be
        wrong; his reaction to the real ball still takes this long."""
        if p.id == self.dribbler:  # he pushed it there himself: nothing to react to
            return 0.0
        if p.id == self.intended:
            return perception.SIMPLE_REACTION_S
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
        self.dribbler = None
        self.windup = None
        self.read = None
        self.intended = None
        self.runs = {}
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
        self.dribbler = None
        self.possessor = None
        self.last_touch = carrier.id
        self.kicked_at = self.t
        self.free_since = self.t  # the ball left a player's control: dives are timed from here
        self.dive_show.clear()  # a new strike; the last dive has finished
        self.kicker_clear = False
        self.chase = {}  # everyone reacts after their reaction time, not on the frame of the kick

    def execute(
        self, p: Player, vx: float, vy: float, vz: float, skill: str, hands: bool = False
    ) -> tuple[float, float, float]:
        """The kick as struck, not as intended: direction, speed and launch angle scatter by the
        player's own error, which grows with ball speed, pressure, fatigue and the weaker foot
        and shrinks with skill (profiles.Profile.kick_error, docs/GROUNDING.md A3). A throw uses
        both hands, so there is no weaker foot and no kicking side."""
        ground = math.hypot(vx, vy)
        speed = math.sqrt(ground * ground + vz * vz)
        if speed < 1e-6:
            return vx, vy, vz
        nearest = min(math.hypot(q.x - p.x, q.y - p.y) for q in self.players if q.team != p.team)
        pressure = clamp((PRESSURE_M - nearest) / PRESSURE_M, 0.0, 1.0)
        # Which foot: the kick's direction against the way he faces (a state; P13).
        if hands:
            turn, weak = 0.0, False
        else:
            turn = math.degrees((math.atan2(vy, vx) - p.heading + math.pi) % (2 * math.pi) - math.pi)
            weak = (turn > WEAK_SIDE_DEG) if p.profile.foot == "right" else (turn < -WEAK_SIDE_DEG)
        fresh = p.physique.ceiling / D0  # the slow store: fatigue over the match, not one sprint
        dir_sd, speed_sd, loft_sd = p.profile.kick_error(skill, speed, pressure, fresh, weak, turn)
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

    def keeper_read(self, keeper: Player, kicker: Player, aim_y: float) -> float | None:
        """Where a keeper thinks a shot is going, read from the kicker's body: only if he can
        see the kicker, centred on the intended aim, with his anticipation's error (A2)."""
        if not perception.visible(
            keeper.heading, keeper.x, keeper.y, kicker.x, kicker.y, keeper.profile.view_half_angle()
        ):
            return None
        return aim_y + self.rng.gauss(0, keeper.profile.read_error_m())

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
        read = self.keeper_read(keeper, carrier, ty)
        self.read = None if read is None else (keeper.id, read)
        vx, vy, vz = self.execute(carrier, *self.aim(bx, by, gx, ty, ground, up), "finishing")
        speed = math.sqrt(vx * vx + vy * vy + vz * vz)
        # Outcome and end point are observed: set when the ball is touched, goes out or goes in.
        self.shot_touched_by = self.shot_was_on_target = None
        self.kicked = self.emit("shot", team, bx, by, player=carrier.id, ball_speed_kmh=round(speed * 3.6, 1))
        self.kick(carrier, vx, vy, vz)

    def pass_to(self, carrier: Player, tx: float, ty: float, lofted: bool, throw: bool = False) -> None:
        """Kick toward a point the carrier chose (where he believes a team-mate will be, or space)."""
        if throw:
            # Law 15: both hands, from behind and over the head. The feet never touch it.
            bx, by, bz = throw_hands(carrier.x, carrier.y)
            self.ball = (bx, by, bz, 0.0, 0.0, 0.0)
            dist = math.hypot(tx - bx, ty - by)
            ground, up = decisions.loft_launch(max(dist, 1.0))
            vx, vy, vz = self.execute(
                carrier, *self.aim(bx, by, tx, ty, ground, up), "passing", hands=True
            )
            self.into_play = True
            self.kicked = self.emit(
                "pass",
                carrier.team,
                bx,
                by,
                player=carrier.id,
                ball_speed_kmh=round(math.sqrt(vx * vx + vy * vy + vz * vz) * 3.6, 1),
            )
            self.kick(carrier, vx, vy, vz)
            return
        if not self.can_strike(carrier, tx, ty):
            self.turn_to(carrier, tx, ty, lambda: self.pass_to(carrier, tx, ty, lofted, throw))
            return
        bx, by = self.ball[0], self.ball[1]
        dist = math.hypot(tx - bx, ty - by)
        # Struck as the decision estimated it (decisions.py); execution error is added on top.
        if lofted:
            ground, up = decisions.loft_launch(dist)
        else:
            ground, up = decisions.launch_speed(dist), 0.0
        wide = abs(ty - PITCH_Y / 2) > 20 and (tx - bx) * attack_dir(carrier.team) > 0
        skill = "crossing" if (dist > LOFT_OVER_M and wide) else "passing"
        vx, vy, vz = self.execute(carrier, *self.aim(bx, by, tx, ty, ground, up), skill)
        # Receiver, end point and outcome are filled in when someone takes the ball or it goes out.
        self.kicked = self.emit(
            "pass",
            carrier.team,
            bx,
            by,
            player=carrier.id,
            ball_speed_kmh=round(math.sqrt(vx * vx + vy * vy + vz * vz) * 3.6, 1),
        )
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
        # The keeper is an opponent like any other for lanes, carries and pressure; the shot
        # estimate counts him once, as the keeper, not also as a blocker.
        # Opponents as they will be a moment from now (their seen velocity): a carrier reads a
        # defender closing in, not only where he stands.
        opps = []
        for q in self.players:
            at = belief.where(q.id, self.t)
            if at and q.team == opp:
                qvx, qvy = belief.velocity(q.id)
                opps.append((at[0] + qvx * ANTICIPATE_S, at[1] + qvy * ANTICIPATE_S))
        their_keeper = self.keeper(opp).id
        keeper = belief.where(their_keeper, self.t)
        if keeper:  # the same anticipated spot as in `opps`, so the shot estimate counts him once
            kvx, kvy = belief.velocity(their_keeper)
            keeper = (keeper[0] + kvx * ANTICIPATE_S, keeper[1] + kvy * ANTICIPATE_S)
        diff = self.match.score[team] - self.match.score[opp]
        risk = clamp(-diff * self.t / 5400, -1.0, 1.0)  # chase the game when behind late, protect when ahead
        prof = carrier.profile
        scene = decisions.Scene(
            self.ball[0],
            self.ball[1],
            goal_x(team),
            mates,
            opps,
            keeper,
            prof["decisions"],
            prof["composure"],
            prof["dribbling"],
            tuple(prof.traits),
            risk,
            current="dribble" if self.dribble_to else "hold",
        )
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
                self.pass_to(
                    carrier,
                    clamp(scene.x + attack_dir(carrier.team) * 15, 1, PITCH_X - 1),
                    line,
                    lofted=True,
                    throw=True,
                )
            else:
                self.hold_until = self.t + 0.5  # he looks again
            return
        choice = decisions.choose(scene, self.rng)
        if choice.kind == "pass" or choice.kind == "clear":
            self.pass_to(carrier, *choice.target, lofted=choice.lofted)
            self.intended = choice.receiver
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
        deliberate touch, after reaction time, controls it if it is slow enough to absorb.
        A ball he is under, above the foot, can be taken on the thigh, chest or head, which
        kills less pace than a foot. A clip of the body, or a ball he has not reacted to, rebounds."""
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
            # A body meets the ball only if, at the start of this step, the ball was moving toward
            # it (relative to the player). Measured from the step's start, not the closest point,
            # where the relative direction is sideways by construction.
            closing = (self.ball[3] - p.vx) * (p.x - x0) + (self.ball[4] - p.vy) * (p.y - y0)
            reach_m, reach_z = self.reach(p, cx, cy)
            reacted = since >= self.reaction(p)
            on_body = d <= BODY_RADIUS + ball.RADIUS and cz <= BODY_HEIGHT
            # Inside the body, not a graze of the outside: he can get a thigh, chest or head to it.
            under = d <= BODY_RADIUS and BODY_TOUCH_Z < cz <= BODY_HEIGHT
            hands = self.hands(p, cx, cy)
            if reacted and hands and d <= reach_m and cz <= reach_z:
                hits.append((s, "touch", p, cx, cy, cz, False))
            elif reacted and under and not hands and closing >= 0:
                hits.append((s, "touch", p, cx, cy, cz, True))
            elif reacted and d <= reach_m and cz <= reach_z:  # a foot
                hits.append((s, "touch", p, cx, cy, cz, False))
            elif on_body and closing > 0:
                hits.append((s, "body", p, cx, cy, cz, False))
        if not hits:
            return
        s, kind, p, cx, cy, cz, aerial = min(hits, key=lambda h: h[0])
        if kind == "touch":
            self._show_touch(p, cx, cy, cz, aerial)
        vx, vy, vz = self.ball[3], self.ball[4], self.ball[5]
        rel = math.sqrt((vx - p.vx) ** 2 + (vy - p.vy) ** 2 + vz * vz)
        absorb = p.profile.absorb_mps(hands=self.hands(p, cx, cy))
        if aerial:
            absorb *= AERIAL_ABSORB
        controls = kind == "touch" and rel <= absorb
        self.touched(p, cx, cy, controls)  # judged on the ball as it arrived
        if controls:
            self.ball = (cx, cy, cz, p.vx, p.vy, 0.0)
            if self.tackle:  # who came away with the ball decides the tackle
                self.tackle["outcome"] = "success" if p.team == self.tackle["team"] else "fail"
                self.tackle = None
            if p.id == self.dribbler:  # back on his own touch: the dribble goes on
                self.possessor, self.last_touch, self.dribbler = p.id, p.id, None
                self.touched_since_kick = False
                return
            if self.dribbler and p.team != self.team_of(self.dribbler):  # won off the dribbler: a tackle
                self.emit("tackle", p.team, cx, cy, player=p.id, receiver=self.dribbler, outcome="success")
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
        if p.id != self.dribbler and self.dribbler and p.team == self.team_of(self.dribbler):
            self.dribbler = None  # a team-mate took it: the dribble is over
        if p.id != self.released_by:
            self.released_by = None
        kicked = self.kicked
        if not kicked:
            return
        same_team = p.team == kicked["team"]
        if kicked["type"] == "pass":
            if same_team and controls:  # completed, unless it only came back to the passer
                done = p.id != kicked["player"]
                kicked.update(
                    receiver=p.id if done else None,
                    end_x=round(x, 2),
                    end_y=round(y, 2),
                    outcome="success" if done else "fail",
                )
                self.kicked = None
            elif not same_team:  # an opponent got to it: the pass has failed
                kicked.update(receiver=p.id, end_x=round(x, 2), end_y=round(y, 2), outcome="fail")
                if controls:
                    self.emit("interception", p.team, x, y, player=p.id)
                self.kicked = None
            return  # a team-mate's deflection leaves the pass in flight
        if not same_team:
            if self.shot_was_on_target is None:  # the first opponent touch: was it going in?
                self.shot_was_on_target = self.heading_on_target(kicked["team"])
            if p.role != "GK":
                self.shot_touched_by = "defender"
            elif self.shot_touched_by is None:
                self.shot_touched_by = "keeper"
        if controls:
            self.close_shot(kicked, x, y)
        # A deflection (block, parry, a team-mate's touch) leaves the shot in flight: it may still go in.

    def close_shot(self, kicked: dict, x: float, y: float) -> None:
        """A shot ends without a goal: blocked if a defender got to it, saved or tipped if only the
        keeper did (on or off target as it was going), otherwise on or off target as it went."""
        touched_by, was = self.shot_touched_by, self.shot_was_on_target
        if touched_by == "defender":
            outcome = "blocked"
        elif touched_by == "keeper":
            outcome = "on_target" if was else "off_target"
        else:
            outcome = "on_target" if self.heading_on_target(kicked["team"]) else "off_target"
        kicked.update(end_x=round(x, 2), end_y=round(y, 2), outcome=outcome)
        if self.kicked is kicked:
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
        if self.into_play:
            # A throw is released off the pitch. It is not a new out while it is still coming in.
            bx, by, _, _, vy, _ = self.ball
            r = ball.RADIUS
            inside = -r <= bx <= PITCH_X + r and -r <= by <= PITCH_Y + r
            inward = (by >= 0 or vy > 0) and (by <= PITCH_Y or vy < 0)
            if inside or not inward:
                self.into_play = False
            if self.into_play or inside:
                return False
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
                touched = self.shot_touched_by
                self.close_shot(kicked, x, y)
                if not touched:
                    kicked["outcome"] = "off_target"  # it went out untouched: it missed
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
        """Credit as the game does: a shot that goes in is the shooter's goal, including after a
        deflection or a parry, if it was on target before the opponents touched it; otherwise
        the last touch decides, and a defender's last touch is an own goal."""
        self.match.score[team] += 1
        shot = kicked if kicked and kicked["type"] == "shot" and kicked["team"] == team else None
        if shot and self.shot_was_on_target is not False:
            shot["outcome"] = "goal"
            scorer = shot["player"]
        else:
            if shot:
                self.close_shot(shot, x, y)
            scorer = self.last_touch if self.last_touch and self.team_of(self.last_touch) == team else None
        self.emit("goal", team, x, y, player=scorer)
        self.kickoff(other(team))

    def stop(self, kind: str, team: str, spot: tuple[float, float], taker: str | None = None) -> None:
        if taker is None:
            taker = self.nearest(spot[0], spot[1], team).id
        lo, hi = RESTART_DELAY_S[kind]
        self.dribbler = self.dribble_to = None  # the ball is dead: nobody is running onto a touch
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
        spot = throw_stand(r.x, r.y) if r.kind == "throw_in" else (r.x, r.y)
        # A thrower must be at his spot, behind the line; anyone else is close enough when the ball
        # is at his feet. Nobody is moved there: he runs (lesson 5).
        near = THROW_SPOT_M if r.kind == "throw_in" else CONTROL_M
        if self.t < r.ready_at or math.hypot(taker.x - spot[0], taker.y - spot[1]) > near:
            return
        if r.kind == "throw_in" and math.hypot(taker.vx, taker.vy) > THROW_SETTLED_MPS:
            return
        # While the ball is out of play a new one is placed: the only time the ball may jump.
        if r.kind == "throw_in":
            # He takes the ball and stops within his own braking (lesson 5); he has moved this frame.
            steer(taker, taker.x, taker.y, 0.0)
            self.moved = taker.id
            taker.heading = math.pi / 2 if spot[1] < PITCH_Y / 2 else -math.pi / 2
            self.ball = (*throw_hands(taker.x, taker.y), 0.0, 0.0, 0.0)
        else:
            self.ball = (taker.x, taker.y, 0.0, 0.0, 0.0, 0.0)
        self.restart = None
        self.emit("set_piece", r.team, taker.x, taker.y, player=taker.id, outcome=None)
        if r.team != self.poss_team:
            self.emit("possession_change", r.team, taker.x, taker.y, player=taker.id)
        self.give(taker.id)
        # With the ball in his hands he sets and throws. A longer hold reads as a freeze.
        pause = (0.2, 0.45) if r.kind == "throw_in" else (0.5, 1.5)
        self.hold_until = self.t + self.rng.uniform(*pause)
        self.throw_by = taker.id if r.kind == "throw_in" else None
        self.throw_ready = self.t

    # ---- tick ---------------------------------------------------------------

    def shape_target(self, p: Player) -> tuple[float, float, float]:
        """Where a player off the ball wants to be, and how fast they go there."""
        chase = self.chase.get(p.team)
        if p.id in self.lunges:  # committed: straight at the ball
            return self.ball[0], self.ball[1], SPRINT
        if self.off_balance.get(p.id, -1.0) > self.t:  # beaten: getting up, out of the play
            return p.x, p.y, SHAPE
        if p.id == self.dribbler:  # running onto his own touch, a little faster than the ball
            bx, by, _, bvx, bvy, _ = self.ball
            onto = math.hypot(bvx, bvy) + 1.0  # design: he closes on it at about 1 m/s
            return clamp(bx + bvx * 0.2, 0.5, PITCH_X - 0.5), clamp(by + bvy * 0.2, 0.5, PITCH_Y - 0.5), onto
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
            if r.kind == "throw_in":
                return *throw_stand(r.x, r.y), RECOVER
            return clamp(r.x, 0.5, PITCH_X - 0.5), clamp(r.y, 0.5, PITCH_Y - 0.5), RECOVER
        bx, by = self.ball[0], self.ball[1]
        poss_team = self.team_of(self.possessor) if self.possessor else None
        shift = (clamp(bx, 0, PITCH_X) - PITCH_X / 2) * 0.45
        push = 6 * attack_dir(p.team) if poss_team == p.team else -4 * attack_dir(p.team)
        tx = clamp(p.ax + shift + push, 2, PITCH_X - 2) if p.role != "GK" else p.ax
        ty = p.ay + (clamp(by, 0, PITCH_Y) - p.ay) * 0.25
        brain = self.brains[p.team]
        own_goal = PITCH_X - goal_x(p.team)
        work = 5.0 + 2.0 * p.profile["work_rate"]  # how hard he presses and recovers
        if p.role == "GK" and not brain.in_possession:
            carrier = self.by_id.get(self.possessor) if self.possessor else None
            if carrier and carrier.team != p.team:
                view = self.beliefs[p.id]
                seen = view.where(carrier.id, self.t) or (bx, by)
                mates = [
                    w
                    for w in (
                        view.where(q.id, self.t) for q in self.players if q.team == p.team and q.id != p.id
                    )
                    if w
                ]
                if offball.through_on_goal(seen, own_goal, mates):  # O1: come out and narrow it
                    return *offball.close_down_spot(seen, own_goal), SPRINT
            return *offball.keeper_spot(clamp(bx, 0, PITCH_X), clamp(by, 0, PITCH_Y), own_goal), RECOVER
        if not brain.in_possession and p.id in brain.markers:
            mx, my = brain.markers[p.id]
            return clamp(mx, 0.5, PITCH_X - 0.5), clamp(my, 0.5, PITCH_Y - 0.5), work
        carrier = self.by_id.get(self.possessor) if self.possessor else None
        if brain.in_possession and carrier and carrier.team == p.team and p.role != "GK":
            run = self.run_target(p, carrier, brain)
            if run:
                return *run, SPRINT
            mates = sorted(
                (
                    q
                    for q in self.players
                    if q.team == p.team and q.id not in (carrier.id,) and q.role != "GK"
                ),
                key=lambda q: math.hypot(q.x - carrier.x, q.y - carrier.y),
            )
            if p in mates[:2]:  # O3: the nearest two offer a diagonal option
                presser = self.nearest(carrier.x, carrier.y, other(p.team))
                return *offball.support_spot(
                    (p.x, p.y), (carrier.x, carrier.y), goal_x(p.team), (presser.x, presser.y)
                ), RECOVER
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
            engaged = (
                presser is not None
                and math.hypot(bx - presser.x, by - presser.y) < ENGAGE_M
                and brain.presses(self.t, bx)
            )
            if presser is p and engaged:
                # Press goal-side, a step away, matching where the carrier is going (D8: a defender
                # keeps his speed relative to the attacker small rather than holding a spot).
                carrier = self.by_id.get(self.possessor) if self.possessor else None
                lead_x = carrier.vx * JOCKEY_LOOKAHEAD_S if carrier else 0.0
                lead_y = carrier.vy * JOCKEY_LOOKAHEAD_S if carrier else 0.0
                return *on_pitch(bx + lead_x + gx * gap, by + lead_y + gy * gap), work
            if engaged and brain.pressers[1:2] == [p.id]:  # cover: behind the presser, goal-side
                return *on_pitch(bx + gx * max(COVER_M, gap + 2), by + gy * max(COVER_M, gap + 2)), RECOVER
            slot = brain.slot(p.role, p.ay, clamp(by, 0, PITCH_Y))
            if slot:
                tx, ty = slot
        far = math.hypot(tx - p.x, ty - p.y) > FAR_OUT_OF_POSITION_M
        return tx, ty, RECOVER if far else SHAPE

    def shared_view(self, team: str, of_team: str) -> dict[str, tuple[float, float]]:
        """What a team's players know between them about another team's positions: for each
        player, the freshest sighting any of them has (they talk). Never the truth."""
        best: dict[str, tuple[float, tuple[float, float]]] = {}
        for p in self.players:
            if p.team != team:
                continue
            belief = self.beliefs[p.id]
            for q in self.players:
                if q.team == of_team and q.id in belief.seen:
                    age = belief.age(q.id, self.t)
                    if q.id not in best or age < best[q.id][0]:
                        best[q.id] = (age, belief.where(q.id, self.t))
        return {pid: at for pid, (_, at) in best.items()}

    def perceive_and_think(self) -> None:
        """Players look at the pitch about four times a second, staggered so they do not all look
        on the same frame; each team brain reads the game about twice a second."""
        bx, by = self.ball[0], self.ball[1]
        states = [(p.id, p.x, p.y, p.vx, p.vy) for p in self.players]
        for i, p in enumerate(self.players):
            if (self.frame + i) % PERCEIVE_EVERY == 0:
                others = [st for st in states if st[0] != p.id]
                perception.observe(
                    self.beliefs[p.id],
                    (p.x, p.y, p.heading),
                    others,
                    self.t,
                    self.sight_rng,
                    p.profile.view_half_angle(),
                    p.profile.scan_interval(),
                )
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
            if holder != team:  # O2: pick up the attackers who threaten our goal
                free = {
                    p.id: (p.x, p.y)
                    for p in self.players
                    if p.team == team and p.role != "GK" and p.id not in brain.pressers
                }
                brain.markers = offball.marking(
                    free, self.shared_view(team, other(team)), PITCH_X - goal_x(team)
                )
            else:
                brain.markers = {}

    def run_target(self, p: Player, carrier: Player, brain: TeamBrain) -> tuple[float, float] | None:
        """O4: forwards (and anyone who likes to) run in behind when the carrier has the ball
        under control, facing forward and not pressed, while they are onside."""
        if p.id in self.runs:
            x, y, started = self.runs[p.id]
            if self.t - started < 3.0:
                return x, y
            del self.runs[p.id]
        likes = "runs_in_behind" in p.profile.traits
        if p.role not in ("ST", "RW", "LW") and not likes:
            return None
        settled = self.t >= self.hold_until
        nearest = min(math.hypot(q.x - carrier.x, q.y - carrier.y) for q in self.players if q.team != p.team)
        can_play = settled and nearest > decisions.PRESSURE_FRONT_M / 2
        view = self.beliefs[p.id]
        defenders = sorted(
            (w[0] for w in (view.where(q.id, self.t) for q in self.players if q.team != p.team) if w),
            key=lambda x: -attack_dir(p.team) * x,
        )
        second_last = defenders[1] if len(defenders) > 1 else PITCH_X - goal_x(p.team)
        onside = (second_last - p.x) * attack_dir(p.team) >= 0
        their_line = self.brains[other(p.team)].line_x
        spot = offball.run_in_behind((p.x, p.y), their_line, goal_x(p.team), can_play, onside)
        if spot:
            self.runs[p.id] = (*spot, self.t)
        return spot

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
            for b in self.players[i + 1 :]:
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
        if self.throw_by == carrier.id:  # Law 15: held behind the line and thrown, not dribbled
            steer(carrier, carrier.x, carrier.y, 0.0)  # standing still, braking within his body
            carrier.heading = math.pi / 2 if carrier.y < PITCH_Y / 2 else -math.pi / 2
            self.ball = (*throw_hands(carrier.x, carrier.y), 0.0, 0.0, 0.0)
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
            pace = decisions.dribble_speed(carrier.profile["dribbling"])
            if self.closest_opponent(carrier) < CLOSE_CONTROL_M:
                pace *= CLOSE_CONTROL_PACE  # close control: slower, the ball never leaves his feet
            steer(carrier, tx, ty, pace)
            if math.hypot(tx - carrier.x, ty - carrier.y) < 1.0:
                self.dribble_to = None
        else:  # holding: keeps the ball, shielding it
            steer(carrier, carrier.x, carrier.y, DRIBBLE)
        # The ball settles at the carrier's feet (from a keeper's hands, down to the ground)
        # rather than jumping there.
        # A controlled ball travels with the carrier, then closes the remaining gap relative to
        # them, to his feet on the side he faces.
        if not self.windup:  # turning to strike, he faces the target, not where he drifts
            carrier.heading = perception.facing(
                carrier.heading, carrier.vx, carrier.vy, carrier.x, carrier.y, carrier.x, carrier.y
            )
        feet = BODY_RADIUS + ball.RADIUS
        side = carrier.heading
        if not self.dribble_to and not self.windup:  # D8: holding, he keeps his body between ball and man
            near = min(
                (q for q in self.players if q.team != carrier.team),
                key=lambda q: math.hypot(q.x - carrier.x, q.y - carrier.y),
            )
            if math.hypot(near.x - carrier.x, near.y - carrier.y) < SHIELD_M:
                side = math.atan2(carrier.y - near.y, carrier.x - near.x)
        fx, fy = carrier.x + math.cos(side) * feet, carrier.y + math.sin(side) * feet
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
        close = self.closest_opponent(carrier) < CLOSE_CONTROL_M
        if self.dribble_to and not self.windup and not close and math.hypot(fx - bx, fy - by) < 0.15:
            self.touch_ahead(carrier)
            return
        if self.windup:
            if self.can_strike(carrier, self.windup[0], self.windup[1]):
                strike, self.windup = self.windup[2], None
                strike()
            return
        if self.t >= self.hold_until and (self.frame + int(carrier.id[1:])) % DECIDE_EVERY == 0:
            self.decide(carrier)

    def closest_opponent(self, p: Player) -> float:
        return min(math.hypot(q.x - p.x, q.y - p.y) for q in self.players if q.team != p.team)

    def may_commit(self, p: Player, holder: Player, bx: float, by: float) -> bool:
        """D8: delay, deny, then commit. A defender goes in only with a team-mate covering behind
        him, when the ball has run loose from the carrier, or as a last resort near his own goal;
        otherwise he jockeys and waits."""
        own = PITCH_X - goal_x(p.team)
        if abs(bx - own) < LAST_DITCH_M:
            return True
        if math.hypot(bx - holder.x, by - holder.y) > CONTROL_M:  # a heavy touch: the ball is there
            return True
        return any(
            q.team == p.team
            and q is not p
            and abs(q.x - own) < abs(p.x - own)
            and math.hypot(q.x - p.x, q.y - p.y) < COVER_M
            for q in self.players
        )

    def duels(self) -> None:
        """D8: defenders near the ball decide whether to tackle, and lunges that have arrived are
        resolved. The decision weighs the threat removed if he wins it against the threat added
        if the carrier gets past him; whether he wins it is the race between his foot and the
        carrier moving the ball."""
        holder = self.by_id.get(self.possessor) if self.possessor else self.by_id.get(self.dribbler or "")
        bx, by = self.ball[0], self.ball[1]
        for pid, reach_at in list(self.lunges.items()):
            if self.t < reach_at:
                carrier = self.by_id.get(self.possessor) if self.possessor else None
                if carrier and self.t >= self.evade_at.get(pid, math.inf):
                    self.evade(carrier, self.by_id[pid])  # he saw it coming in time
                    self.evade_at.pop(pid, None)
                continue
            self.evade_at.pop(pid, None)
            del self.lunges[pid]
            p = self.by_id[pid]
            holder = self.by_id.get(self.possessor) if self.possessor else self.by_id.get(self.dribbler or "")
            bx, by = self.ball[0], self.ball[1]
            # Law 15: a ball held for a throw-in is not in play, so a lunge that arrives then finds nothing.
            held = holder is not None and self.throw_by == holder.id
            if holder and holder.team != p.team and not held and math.hypot(p.x - bx, p.y - by) <= CONTROL_M:
                self.poke(p, holder)
                holder = None
            else:
                self.off_balance[pid] = self.t + OFF_BALANCE_S
        if not holder or self.restart or self.hands(holder, holder.x, holder.y):  # Law 12: not his hands
            return
        if self.throw_by == holder.id:  # Law 15: not in play until it is thrown, so nobody challenges
            return
        for i, p in enumerate(self.players):
            if p.team == holder.team or p.role == "GK" or p.id in self.lunges:
                continue
            if self.off_balance.get(p.id, -1.0) > self.t or (self.frame + i) % DECIDE_EVERY:
                continue
            d = math.hypot(p.x - bx, p.y - by)
            if d > decisions.LUNGE_REACH_M or not self.may_commit(p, holder, bx, by):
                continue
            lunge = decisions.lunge_time(d, p.profile["tackling"])
            # His estimate of winning the race: an average carrier needs a choice reaction to react.
            p_win = decisions.tackle_chance(d, p.profile["tackling"])
            # He stays on his feet unless he expects to win it (aggressive players gamble sooner);
            # a better decision-maker judges that line more sharply.
            line = COMMIT_P - 0.2 * (p.profile["aggression"] - 0.5)
            sharp = 0.02 + 0.08 * (1 - p.profile["decisions"])
            if self.rng.random() < decisions.sigmoid((p_win - line) / sharp):
                self.lunges[p.id] = self.t + lunge
                self.evade_at[p.id] = self.t + holder.profile.reaction()

    def evade(self, carrier: Player, defender: Player) -> None:
        """The carrier, having reacted to a lunge, pushes the ball away from the defender's foot,
        to the side that keeps him going forward; a better dribbler moves it quicker."""
        bx, by = self.ball[0], self.ball[1]
        away = math.atan2(by - defender.y, bx - defender.x)
        fwd = math.atan2(0.0, attack_dir(carrier.team))
        sides = (away + math.pi / 2, away - math.pi / 2)
        angle = min(sides, key=lambda a: abs((a - fwd + math.pi) % (2 * math.pi) - math.pi))
        speed = EVADE_MPS + 2.0 * carrier.profile["dribbling"]
        vx, vy, vz = self.execute(carrier, math.cos(angle) * speed, math.sin(angle) * speed, 0.0, "dribbling")
        self.ball = (bx, by, self.ball[2], vx, vy, vz)
        self.possessor, self.dribbler, self.dribble_to = None, carrier.id, None
        self.last_touch = carrier.id
        self.free_since = self.t
        self.kicker_clear, self.touched_since_kick = False, True

    def poke(self, p: Player, holder: Player) -> None:
        """A tackle that reaches the ball knocks it loose; whoever then controls it decides the
        tackle (won or lost)."""
        heading = (
            math.atan2(p.vy, p.vx)
            if math.hypot(p.vx, p.vy) > 0.5
            else math.atan2(self.ball[1] - p.y, self.ball[0] - p.x)
        )
        angle = heading + math.radians(self.rng.gauss(0.0, 40.0))
        self.ball = (
            self.ball[0],
            self.ball[1],
            0.0,
            holder.vx * 0.3 + POKE_MPS * math.cos(angle),
            holder.vy * 0.3 + POKE_MPS * math.sin(angle),
            0.0,
        )
        self.tackle = self.emit(
            "tackle", p.team, self.ball[0], self.ball[1], player=p.id, receiver=holder.id, outcome=None
        )
        self.possessor, self.dribbler, self.dribble_to, self.windup = None, None, None, None
        self.last_touch = p.id
        self.kicked_at = self.free_since = self.t
        self.kicker_clear, self.touched_since_kick = False, True
        self.plan_chase()

    def touch_ahead(self, carrier: Player) -> None:
        """D6: a dribbling touch. The ball goes ahead of him toward where he is carrying it, further
        with space, struck with his own error; he runs onto it, and it is free until he gets there."""
        tx, ty = self.dribble_to
        bx, by = self.ball[0], self.ball[1]
        d = math.hypot(tx - bx, ty - by)
        if d < 0.5:
            self.dribble_to = None
            return
        view = self.beliefs[carrier.id]
        felt = min(
            (
                math.hypot(w[0] - carrier.x, w[1] - carrier.y)
                for w in (view.where(q.id, self.t) for q in self.players if q.team != carrier.team)
                if w
            ),
            default=99.0,
        )
        space = clamp((felt - 2.0) / 8.0, 0.0, 1.0)
        ahead = TOUCH_CLOSE_M + TOUCH_SPACE_M * space
        run = max(decisions.dribble_speed(carrier.profile["dribbling"]), math.hypot(carrier.vx, carrier.vy))
        speed = run + ahead / TOUCH_GAP_S
        vx, vy, vz = self.execute(carrier, (tx - bx) / d * speed, (ty - by) / d * speed, 0.0, "dribbling")
        self.ball = (bx, by, self.ball[2], vx, vy, vz)
        self.possessor = None
        self.last_touch = carrier.id
        self.dribbler = carrier.id
        # A touch that carries on the way he was running is what everyone watching expects; only
        # a sharp change of direction is a new event they must react to (P12).
        moving = math.hypot(carrier.vx, carrier.vy) > 1.0
        turn = abs(
            (math.atan2(vy, vx) - math.atan2(carrier.vy, carrier.vx) + math.pi) % (2 * math.pi) - math.pi
        )
        if not moving or turn > math.radians(TOUCH_EXPECTED_DEG):
            self.kicked_at = self.t
        self.free_since = self.t
        self.kicker_clear = False
        self.touched_since_kick = True
        # Who goes for the loose ball is judged at once: a defender who has been watching the carry
        # and can get there first commits to it, rather than keep shadowing.
        self.plan_chase()

    def _show_touch(self, p: Player, cx: float, cy: float, cz: float, aerial: bool) -> None:
        """The part that met the ball. A carry's own touch is the gait. Anything else is drawn."""
        if self.hands(p, cx, cy):
            part = "hands"
        elif aerial:
            if cz < 0.95:
                part = "thigh"
            elif cz < 1.50:
                part = "chest"
            else:
                part = "head"
        elif self.dribbler == p.id and cz <= BODY_TOUCH_Z:
            return
        else:
            part = "foot"
        self.touch_show[p.id] = (part, self.t + TOUCH_POSE_S)

    def pose(self, p: Player) -> tuple[str, float]:
        """How this body should be drawn. Read off the match: a strike is a wind-up already
        chosen, a dive is the keeper's reach stretching for a ball he cannot get standing,
        and a touch names the part that met the ball."""
        if self.throw_by == p.id:
            return "throw", 0.0
        if self.possessor == p.id and self.windup:
            return "strike", 0.0
        diving = clamp((self.t - self.free_since - self.reaction(p)) / DIVE_TIME_S, 0.0, 1.0)
        if p.role == "GK" and self.possessor != p.id and self.hands(p, self.ball[0], self.ball[1]):
            dist = math.hypot(self.ball[0] - p.x, self.ball[1] - p.y)
            reach = KEEPER_STAND_REACH_M + KEEPER_DIVE_EXTRA_M * diving
            if (
                diving > 0.15
                and KEEPER_STAND_REACH_M < dist <= reach + 0.5
                and math.hypot(self.ball[3], self.ball[4]) > 3
            ):
                side = math.sin(math.atan2(self.ball[1] - p.y, self.ball[0] - p.x) - p.heading)
                end = self.free_since + self.reaction(p) + DIVE_TIME_S
                self.dive_show[p.id] = (end, 1.0 if side >= 0 else -1.0)
                return "dive", round(diving if side >= 0 else -diving, 3)
        shown = self.dive_show.get(p.id)
        if shown and p.role == "GK" and self.possessor != p.id and self.t < shown[0]:
            return "dive", round(min(max(diving, 0.0), 1.0) * shown[1], 3)
        touch = self.touch_show.get(p.id)
        if touch and self.t < touch[1]:
            return touch[0], 0.0
        speed = math.hypot(p.vx, p.vy)
        if speed > 4:
            return "run", 0.0
        if speed > 0.5:
            return "walk", 0.0
        return "stand", 0.0

    def snapshot(self) -> None:
        bx, by, bz = self.ball[0], self.ball[1], self.ball[2]
        players = []
        for p in self.players:
            action, dive = self.pose(p)
            players.append(
                {
                    "id": p.id,
                    "team": p.team,
                    "role": p.role,
                    "x": round(p.x, 3),
                    "y": round(p.y, 3),
                    "vx": round(p.vx, 3),
                    "vy": round(p.vy, 3),
                    "heading": round(p.heading, 4),
                    "action": action,
                    "dive": dive,
                }
            )
        self.match.frames.append(
            {
                "frame": self.frame,
                "t": round(self.t, 3),
                "ball": {
                    "x": round(bx, 3),
                    "y": round(by, 3),
                    "z": round(bz, 3),
                    "vx": round(self.ball[3], 3),
                    "vy": round(self.ball[4], 3),
                    "vz": round(self.ball[5], 3),
                },
                "possessor": self.possessor,
                "players": players,
            }
        )

    def run(self, minutes: float) -> Match:
        self.kickoff("home")
        total = int(minutes * 60 * FPS)
        for _ in range(total):
            self.moved = None
            self.perceive_and_think()
            self.duels()
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
