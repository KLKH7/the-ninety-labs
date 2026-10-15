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

from ninety.sim import ball, decisions, offball, perception, profiles, setpieces
from ninety.sim import team as team_mod
from ninety.sim.body import (
    BODY_HEIGHT,
    BODY_RADIUS,
    BRAKE_MAX,
    CONTROL_M,
    CS_MEAN,
    D0,
    F0_MEAN,
    HAND_REACH_Z,
    V0_MEAN,
    Body,
    can_get_to,
    relative_speed,
)
from ninety.sim.body import move as move_body
from ninety.sim.decisions import PENALTY_DEPTH
from ninety.sim.offball import KEEPER_DIVE_TRAVEL_M
from ninety.sim.profiles import Profile
from ninety.sim.team import TeamBrain

PITCH_X, PITCH_Y = 105.0, 68.0
FPS = 25
DT = 1.0 / FPS
# How fast a player chooses to go. Off the ball he goes as fast as he needs to be in place before
# the ball could get there (in_time, O8), no faster; a few jobs are flat out. What he can reach is
# limited by his own body (ninety/sim/body.py): acceleration, top speed, energy.
SPRINT = 99.0  # as fast as their body allows
RECOVER = 6.0  # a restart taker or the keeper getting into position (design)
SHAPE = 3.0  # getting up after being beaten (design)
DRIBBLE = 2.5
DECIDE_EVERY = 6  # frames between the ball carrier's decisions (about 4 a second)
PERCEIVE_EVERY = 6  # frames between a player's looks at the pitch (about 4 a second, staggered)
BRAIN_EVERY = 12  # frames between a team brain's reads of the game (about 2 a second)
COVER_M = 8.0  # design: the covering player stays this far behind the presser, goal-side
PERCEPTION_ERR = 0.03  # verify: m/s of misjudged ball velocity per metre between player and ball
PRESS_GAP_M = 2.0  # design, verify: how close a presser stands (jockeys), goal-side of the ball carrier
PERSONAL_SPACE_M = 1.2  # players steer to keep about this far from each other
SHOULDER_TO_SHOULDER_M = 0.52  # P11: centres of two players in contact, shoulder to shoulder
ANTICIPATE_S = 0.4  # verify: how far ahead players judge where others will be
BODY_RESTITUTION = 0.3  # verify: share of the ball's speed into a body that it keeps
MISCONTROL_KEEP = 0.4  # verify: share of speed a ball keeps off a failed touch or a parry
POST_RADIUS = 0.06  # Law 1: posts and crossbar at most 12 cm wide
WOODWORK_RESTITUTION = 0.6  # verify
BALL_TO_FEET = 12.0  # m/s: how fast the ball settles at a new carrier's feet
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
COMMIT_COVER_M = 10.0  # a team-mate goal-side within this distance is cover to commit with
LAST_DITCH_M = 18.0  # this near his own goal a defender commits without cover
COMMIT_P = 0.6  # a defender commits only when he expects to win the race this often (aggression shifts it)
SHIELD_M = 3.0  # holding with an opponent this close, the carrier puts his body between them
EVADE_MPS = 3.0  # how fast a carrier pushes the ball away from a lunge, plus up to 2 m/s with dribbling
JOCKEY_LOOKAHEAD_S = 0.5  # a jockeying defender matches where the carrier is going, not where he is
POKE_MPS = 5.0  # how fast a tackled ball comes away
THROW_WAIT_S = 6.0  # design: with nobody free, a thrower waits this long, then throws down the line
CHASE_EVERY = 4  # frames between re-planning who chases a free ball
GOAL_HALF_WIDTH, CROSSBAR = 3.66, 2.44  # Law 1
GOAL_AREA_X = 5.5  # Law 1
# Laws 15 to 17: opponents keep this far from a restart until the ball is in play.
RESTART_DISTANCE_M = {"throw_in": 2.0, "corner": 9.15, "goal_kick": PENALTY_DEPTH - GOAL_AREA_X + 1.0,
                      "free_kick": 9.15, "kick_off": 9.15}  # Laws 8 and 13: 9.15 m (the centre circle)
BOARDS_M = 4.0  # verify: advertising boards behind the lines stop a ball (and players) that go out
# R1: seconds from the ball going out to the restart. Means from Opta timing of the Premier League
# (The Analyst): throw-ins about 16 s (2022-23; 17.9 in 2025-26), goal kicks 29 to 30 s, free kicks
# 31.3 to 40.9 s by team (2022-23; mean taken as the middle), corners about half a minute (only a
# combined figure is published). The spread around each mean is design. Kickoff: design, long
# enough to see (a goal's celebration, about 72 s in the same data, is not modelled).
RESTART_DELAY_S = {"throw_in": (12, 20), "goal_kick": (24, 34), "corner": (24, 36),
                   "free_kick": (29, 41),
                   "kick_off": (1, 2)}
# A corner is not taken on a timer here: it is taken when both teams are set (setpieces.advance), so
# its range above is unused; the corner report compares the time that emerges with it.
# S9 (design): the corner scenario opens with a home winger on the ball this far from the goal
# line he attacks and from his touchline, plays the attack out, and keeps the first one that play
# turns into a home corner within CORNER_WITHIN_S; it gives up on an attack once the away side has
# the ball ATTACK_OVER_M or more from that goal line.
WIDE_FROM_GOAL_LINE_M = (13.0, 25.0)
WIDE_FROM_TOUCHLINE_M = (3.0, 15.0)
WINGER_TURN_DEG = 90.0  # he faces anywhere from straight at the goal line to straight infield
CORNER_WITHIN_S = 20.0
ATTACK_OVER_M = 40.0
CORNER_ATTEMPTS = 200  # far above the most any seed has needed (73)
CORNER_SEED_BASE = 1_000_000_000  # scenario engine seeds: base + seed * 1000 + attempt, apart from
# the seeds of full matches
NO_OFFSIDE_FROM = ("throw_in", "goal_kick", "corner")  # Law 11: no offside offence direct from these
INTERCEPT_SHARE = 0.85  # design: taken before this share of the way to its target, a pass is intercepted

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


AVERAGE = 0.5  # an average player's attribute, for estimates about whoever ends up on the ball


def settle_s(first_touch: float) -> float:
    """The first touch settles the ball before he can decide: quicker with a good first touch
    (design)."""
    return 0.3 + 0.3 * (1 - first_touch)


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
                self.players.append(Player(f"{team[0]}{n + 1}", team, role, ax, ay, ax, ay,
                                           physique=profile.physique(), profile=profile,
                                           heading=0.0 if team == "home" else math.pi))
        self.by_id = {p.id: p for p in self.players}
        self.match.roster = [{"id": p.id, "team": p.team, "role": p.role, "name": p.profile.name,
                              "foot": p.profile.foot, "traits": p.profile.traits,
                              "archetype": p.profile.archetype,
                              "ratings": {a: p.profile.rating(a) for a in p.profile.attributes}}
                             for p in self.players]
        self.beliefs = {p.id: perception.Belief(next_scan=self.rng.uniform(0, 3)) for p in self.players}
        # T2, T3: each side plays a block of its own (design: equally likely), drawn from its own
        # stream so the rest of the match's random draws do not shift with it.
        style = random.Random(f"{seed}-style")
        self.brains = {team: TeamBrain(team, block=style.choice(sorted(team_mod.BLOCKS)))
                       for team in ("home", "away")}
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
        self.lunge_at: dict[str, str] = {}  # defender -> the man he lunged at
        self.penalties = 0  # fouls in the offender's own box (Law 14 not yet modelled: a free kick)
        self.evade_at: dict[str, float] = {}  # defender -> when the carrier reacts to his lunge
        self.off_balance: dict[str, float] = {}  # defender -> when he has recovered from a miss
        self.tackle: dict | None = None  # the tackle event whose outcome the next control decides
        self.dribbler: str | None = None  # a carrier who pushed the ball ahead and is running onto it
        self.last_deflection: dict | None = None  # the most recent deflection event
        self.seen_going: tuple[float, float] = (PITCH_X / 2, PITCH_Y / 2)  # where a struck ball is seen going
        self.pass_target: tuple[float, float] | None = None  # where the pass in flight was aimed
        self.offside: set[str] = set()  # L10: team-mates in an offside position when the ball was played
        self.from_restart: str | None = None  # the restart the next kick is taken from
        self.read: tuple[str, float] | None = None  # (keeper, y): where he reads a shot is going
        # (keeper, start t, start y, signed travel, when his arms began to stretch)
        # keeper, start, y at the start, travel, when he reacted, the longest the push can need
        self.dive: tuple[str, float, float, float, float, float] | None = None
        self.landed: tuple[str, float] | None = None  # (keeper, his arms' stretch start) while he is down
        self.shot_touched_by: str | None = None  # "keeper" or "defender": who got to the shot
        self.shot_was_on_target: bool | None = None  # was it going in when they first touched it?
        self.free_since = -99.0
        self.touched_since_kick = False
        self.chase: dict[str, tuple[str, float, float]] = {}  # team -> (player, x, y)
        self.restart: Restart | None = None
        self.set_play: setpieces.Corner | None = None  # a corner routine being set up or played
        self.throw_by: str | None = None  # a throw-in taker holding the ball until he throws it
        self.throw_ready = 0.0
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
        return decisions.in_box(x, y, PITCH_X - goal_x(team))

    def hands(self, p: Player, x: float, y: float) -> bool:
        """Law 12 (offball.may_handle) for this keeper and this ball."""
        k = self.kicked
        back_pass = bool(k) and k["type"] == "pass" and k["team"] == p.team and self.last_touch == k["player"]
        return offball.may_handle(p.role == "GK", self.in_own_box(p.team, x, y), self.released_by == p.id,
                                  back_pass)

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
        """How far and how high this player can reach for a ball at (x, y), at time `at`
        (offball.reach_for). His arms stretch from the moment he reacts to the last touch, whether
        or not his body launches; a deflection does not un-stretch a dive already under way."""
        hands = self.hands(p, x, y)
        at = self.t if at is None else at
        return offball.reach_for(hands, at - self.stretch_from(p) if hands else 0.0)

    def give(self, pid: str) -> None:
        if self.team_of(pid) != self.poss_team:
            self.pressed.clear()
            self.poss_team = self.team_of(pid)
        self.possessor = pid
        self.last_touch = pid
        if pid != self.released_by:
            self.released_by = None
        self.new_phase()
        self.hold_until = self.t + settle_s(self.by_id[pid].profile["first_touch"])

    def new_phase(self) -> None:
        """Forget the last phase of play: a new carrier, or a kickoff."""
        self.dribbler = None
        self.last_deflection = None
        self.offside = set()
        self.windup = None
        self.read = None
        self.intended = None
        self.runs = {}
        self.touched_since_kick = False
        self.chase = {}
        self.dribble_to = None
        self.dive = None

    def kickoff_spot(self, p: Player, kicking: str) -> tuple[float, float]:
        """Law 8: his formation spot, but in his own half, and outside the centre circle if his
        team is not taking the kick."""
        half = PITCH_X / 2
        x = min(p.ax, half - 1.0) if attack_dir(p.team) > 0 else max(p.ax, half + 1.0)
        y = p.ay
        d = math.hypot(x - half, y - PITCH_Y / 2)
        circle = RESTART_DISTANCE_M["kick_off"] + 0.5
        if p.team != kicking and d < circle:
            scale = circle / (d or 1.0)
            x, y = half + (x - half) * scale, PITCH_Y / 2 + (y - PITCH_Y / 2) * scale
        return x, y

    def kickoff(self, team: str) -> None:
        """Law 8. After a goal the broadcast cuts, so positions reset (the validator allows it).
        Then the teams set up, each in its own half and the opponents outside the centre circle,
        and the kick is taken after a short pause rather than at once."""
        for p in self.players:
            p.x, p.y = self.kickoff_spot(p, team)
            p.vx = p.vy = 0.0
        self.ball = (PITCH_X / 2, PITCH_Y / 2, 0.0, 0.0, 0.0, 0.0)
        self.set_play = None
        taker = next(p for p in self.players if p.team == team and p.role == "ST")
        taker.x, taker.y = PITCH_X / 2, PITCH_Y / 2
        self.emit("kickoff", team, taker.x, taker.y, player=taker.id)
        self.possessor = None
        self.poss_team = team
        self.kicked = None
        self.new_phase()
        self.stop("kick_off", team, (PITCH_X / 2, PITCH_Y / 2), taker.id)

    # ---- decisions: players choose, the kick gives the ball a velocity -------

    def in_the_lane(self, kicked: dict, x: float, y: float) -> bool:
        """Was the pass taken on its way, short of where it was aimed (by INTERCEPT_SHARE)?"""
        tx, ty = self.pass_target or (x, y)
        sx, sy = kicked["x"], kicked["y"]
        length = math.hypot(tx - sx, ty - sy)
        if length < 1e-6:
            return True
        along = ((x - sx) * (tx - sx) + (y - sy) * (ty - sy)) / length
        return along < INTERCEPT_SHARE * length

    def offside_offence(self, p: Player, x: float, y: float) -> None:
        """L10: an indirect free kick to the defending side where the offside player played it."""
        kicked = self.kicked
        if kicked and kicked["type"] == "pass":
            kicked.update(receiver=p.id, end_x=round(x, 2), end_y=round(y, 2), outcome="fail")
        elif kicked and kicked["type"] == "shot":
            self.close_shot(kicked, x, y)
        self.kicked = None
        self.offside = set()
        self.emit("offside", p.team, x, y, player=p.id)
        self.possessor = None  # the ball is dead and rolls on until the free kick is taken
        self.chase = {}
        self.stop("free_kick", other(p.team), (clamp(x, 0.5, PITCH_X - 0.5), clamp(y, 0.5, PITCH_Y - 0.5)))

    def onside_limit(self, team: str, positions: list[tuple[float, float]], ball_x: float) -> float:
        """Law 11: how far toward the opponents' goal a player of `team` may stand and be onside:
        level with the second-last opponent or the ball, whichever is further, and anywhere in
        his own half. `positions` are the opponents' x positions as seen (or the truth, for the
        referee)."""
        fwd = attack_dir(team)
        ahead = sorted((x for x, _ in positions), key=lambda x: -fwd * x)
        second_last = ahead[1] if len(ahead) > 1 else goal_x(team)
        limit = max(fwd * second_last, fwd * ball_x, fwd * PITCH_X / 2)
        return fwd * limit

    def offside_positions(self, passer: Player) -> set[str]:
        """L10: the passer's team-mates in an offside position as the ball is played (the truth:
        this is the referee's judgement)."""
        opp = [(q.x, q.y) for q in self.players if q.team != passer.team]
        limit = self.onside_limit(passer.team, opp, self.ball[0])
        fwd = attack_dir(passer.team)
        return {q.id for q in self.players
                if q.team == passer.team and q is not passer and fwd * (q.x - limit) > 0}

    def can_strike(self, carrier: Player, tx: float, ty: float) -> bool:
        """The ball is on the side of his body facing the target, so he can strike it there
        without the ball passing through him."""
        return decisions.can_strike(self.ball[0] - carrier.x, self.ball[1] - carrier.y,
                                    tx - self.ball[0], ty - self.ball[1])

    def turn_to(self, carrier: Player, tx: float, ty: float, strike) -> None:
        """He turns, taking the ball round to his kicking side; the strike waits until it is there."""
        carrier.heading = math.atan2(ty - carrier.y, tx - carrier.x)
        self.windup = (tx, ty, strike)

    def kick(self, carrier: Player, vx: float, vy: float, vz: float) -> None:
        # Struck from where the ball is, at the carrier's feet on the side he faces. A ball moving
        # away from a body never meets it (contact checks approach), so no placement is needed.
        self.ball = (self.ball[0], self.ball[1], self.ball[2], vx, vy, vz)
        self.released_by = carrier.id
        self.last_deflection = None
        exempt = self.from_restart in NO_OFFSIDE_FROM
        self.from_restart = None
        self.offside = set() if exempt else self.offside_positions(carrier)
        self.throw_by = None  # a throw-in ends when the ball is thrown
        self.dribbler = None
        self.possessor = None
        self.last_touch = carrier.id
        self.kicked_at = self.t
        self.free_since = self.t  # the ball left a player's control: dives are timed from here
        self.landed = None  # a new strike: a keeper still down reacts to it afresh
        self.seen_going = self.ball_destination()
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
        # Which foot: the kick's direction against the way he faces (a state; P13).
        turn = decisions.turn_deg(math.atan2(vy, vx), p.heading)
        dir_sd, speed_sd, loft_sd, foot = p.profile.strike_error(skill, speed, nearest, self.fresh(p), turn)
        angle = math.atan2(vy, vx) + math.radians(self.rng.gauss(0, dir_sd))
        loft = math.atan2(vz, ground) + (math.radians(self.rng.gauss(0, loft_sd)) if vz > 0 else 0.0)
        speed = decisions.struck_speed(speed, self.rng.gauss(0, speed_sd), foot)
        ground, up = speed * math.cos(loft), speed * math.sin(loft)  # a low drive may go into the turf
        return ground * math.cos(angle), ground * math.sin(angle), up

    @staticmethod
    def fresh(p: Player) -> float:
        """The slow store's share left (P10): fatigue over the match, not one sprint."""
        return p.physique.ceiling / D0

    def aim(self, sx: float, sy: float, tx: float, ty: float, ground: float, up: float):
        d = math.hypot(tx - sx, ty - sy) or 1.0
        return (tx - sx) / d * ground, (ty - sy) / d * ground, up

    def keeper_read(self, keeper: Player, kicker: Player, aim_y: float) -> float | None:
        """Where a keeper thinks a shot is going, read from the kicker's body: only if he can
        see the kicker, centred on the intended aim, with his anticipation's error (A2)."""
        if not perception.visible(keeper.heading, keeper.x, keeper.y, kicker.x, kicker.y,
                                  keeper.profile.view_half_angle()):
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
        speed = self.rng.uniform(*offball.SHOT_SPEEDS_KMH) / 3.6
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

    def pass_to(self, carrier: Player, tx: float, ty: float, lofted: bool, throw: bool = False,
                pace: float = decisions.ARRIVE_MPS, receiver: str | None = None) -> None:
        """Kick toward a point the carrier chose (where he believes a team-mate will be, or space),
        meant for `receiver` if he chose one."""
        if not self.can_strike(carrier, tx, ty):
            self.turn_to(carrier, tx, ty,
                         lambda: self.pass_to(carrier, tx, ty, lofted, throw, pace, receiver))
            return
        bx, by = self.ball[0], self.ball[1]
        dist = math.hypot(tx - bx, ty - by)
        # Struck as the decision estimated it (decisions.py); execution error is added on top.
        if throw or lofted:
            ground, up = decisions.loft_launch(dist)
        else:
            ground, up = decisions.launch_speed(dist, pace), 0.0
        skill = decisions.pass_skill(bx, tx, ty, lofted or throw, goal_x(carrier.team))
        vx, vy, vz = self.execute(carrier, *self.aim(bx, by, tx, ty, ground, up), skill)
        # Receiver, end point and outcome are filled in when someone takes the ball or it goes out.
        self.pass_target = (tx, ty)
        self.kicked = self.emit("pass", carrier.team, bx, by, player=carrier.id,
                                ball_speed_kmh=round(math.sqrt(vx * vx + vy * vy + vz * vz) * 3.6, 1))
        self.kick(carrier, vx, vy, vz)
        self.intended = receiver  # he expects it

    def scene_for(self, carrier: Player) -> decisions.Scene:
        """The carrier's picture of the game, built only from what he believes."""
        team, opp = carrier.team, other(carrier.team)
        belief = self.beliefs[carrier.id]
        mates = []
        for q in self.players:
            if q.team == team and q.id != carrier.id:
                at = belief.where(q.id, self.t)
                if at:  # a team-mate he has not seen cannot be picked
                    mates.append((q.id, at[0], at[1], belief.age(q.id, self.t), *belief.velocity(q.id)))
        seen_opps = [w for w in (belief.where(q.id, self.t) for q in self.players if q.team == opp) if w]
        if self.from_restart not in NO_OFFSIDE_FROM:  # L10: he does not pick a man he sees offside
            limit = self.onside_limit(team, seen_opps, self.ball[0])
            mates = [m for m in mates if attack_dir(team) * (m[1] - limit) <= 0]
        # The keeper is an opponent like any other for lanes, carries and pressure; the shot
        # estimate counts him once, as the keeper, not also as a blocker.
        # Opponents as they will be a moment from now (their seen velocity): a carrier reads a
        # defender closing in, not only where he stands.
        # The pass race runs from where he sees them now, at the velocity he saw (decisions.pass_confidence).
        their_keeper = self.keeper(opp).id
        opps, moving = [], []
        for q in self.players:
            at = belief.where(q.id, self.t)
            if at and q.team == opp:
                qvx, qvy = belief.velocity(q.id)
                opps.append((at[0] + qvx * ANTICIPATE_S, at[1] + qvy * ANTICIPATE_S))
                moving.append((at[0], at[1], qvx, qvy, q.id == their_keeper))
        keeper = belief.where(their_keeper, self.t)
        if keeper:  # the same anticipated spot as in `opps`, so the shot estimate counts him once
            kvx, kvy = belief.velocity(their_keeper)
            keeper = (keeper[0] + kvx * ANTICIPATE_S, keeper[1] + kvy * ANTICIPATE_S)
        diff = self.match.score[team] - self.match.score[opp]
        risk = clamp(-diff * self.t / 5400, -1.0, 1.0)  # chase the game when behind late, protect when ahead
        prof = carrier.profile
        scene = decisions.Scene(self.ball[0], self.ball[1], goal_x(team), mates, opps, keeper,
                                prof["decisions"], prof["composure"], prof["dribbling"],
                                tuple(prof.traits), risk,
                                current="dribble" if self.dribble_to else None, moving=moving,
                                absorb={m[0]: self.by_id[m[0]].profile.absorb_mps(False) for m in mates},
                                passer=prof, heading=carrier.heading, fresh=self.fresh(carrier),
                                ball_offset=(self.ball[0] - carrier.x, self.ball[1] - carrier.y))
        return scene

    def decide(self, carrier: Player, throw: bool = False) -> None:
        """The carrier chooses from what he believes (ninety/sim/decisions.py)."""
        scene = self.scene_for(carrier)
        if throw:  # Law 15: a throw goes to a team-mate, not at goal, and is never dribbled
            scene.throw = True
            scene.mates = [m for m in scene.mates if math.hypot(m[1] - scene.x, m[2] - scene.y) <= 25]
            choice = max(decisions.options(scene), key=lambda o: o.value, default=None)
            if choice:
                self.pass_to(carrier, *choice.target, lofted=True, throw=True, receiver=choice.receiver)
            elif self.t - self.throw_ready > THROW_WAIT_S:  # nobody free: into space down the line
                line = 3.0 if scene.y < PITCH_Y / 2 else PITCH_Y - 3.0
                self.pass_to(carrier, clamp(scene.x + attack_dir(carrier.team) * 15, 1, PITCH_X - 1), line,
                             lofted=True, throw=True)
            else:
                self.hold_until = self.t + 0.5  # he looks again
            return
        choice = decisions.choose(scene, self.rng)
        if choice.kind == "pass" or choice.kind == "clear":
            self.pass_to(carrier, *choice.target, lofted=choice.lofted, pace=choice.pace,
                         receiver=choice.receiver)
        elif choice.kind == "shoot":
            self.shoot(carrier)
        elif choice.kind == "dribble":
            self.dribble_to = choice.target
        else:
            self.dribble_to = None  # hold: keep the ball, shield it

    # ---- the free ball: who can get there first ------------------------------

    def can_reach(self, p: Player, bx: float, by: float, bz: float, t: float,
                  delay: float = 0.0) -> tuple[bool, float | None, float]:
        """Can he get to the ball at (bx, by, bz) `t` seconds from now, starting after `delay`?
        (reachable, gap still to close, his speed along the way); gap None if it is over his reach.
        His reach (a keeper's hands in his box), his speed along the way, and braking first if he
        is running away from it: one test for chasing a ball and for judging where play goes."""
        reach_m, reach_z = self.reach(p, bx, by, at=self.t + t)
        if bz > reach_z:
            return False, None, 0.0
        return can_get_to(p.physique, bx - p.x, by - p.y, reach_m, p.vx, p.vy, t - delay)

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
                reachable, gap, along = self.can_reach(p, bx, by, bz, t)
                if gap is None:
                    continue  # over his reach
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
        back_on = self.t - self.free_since >= TOUCH_GAP_S
        for p in self.players:
            if p is kicker and not self.kicker_clear:
                continue
            if p.id == self.dribbler and not back_on:  # D6: mid-stride after his touch, not on it yet
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
            if since >= self.reaction(p) and d <= reach_m and cz <= reach_z:  # a deliberate touch
                hits.append((s, "touch", p, cx, cy, cz))
            elif d <= BODY_RADIUS + ball.RADIUS and cz <= BODY_HEIGHT and closing > 0:
                hits.append((s, "body", p, cx, cy, cz))
        if not hits:
            return
        s, kind, p, cx, cy, cz = min(hits, key=lambda h: h[0])
        vx, vy, vz = self.ball[3], self.ball[4], self.ball[5]
        rel = relative_speed(vx, vy, vz, p.vx, p.vy)
        absorb = p.profile.absorb_mps(self.hands(p, cx, cy))
        controls = kind == "touch" and rel <= absorb
        if self.touched(p, cx, cy, controls):  # judged on the ball as it arrived
            return
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
        self.last_deflection = self.emit("deflection", p.team, cx, cy, player=p.id)  # a touch is truth too
        self.last_touch = p.id
        if p.id != self.dribbler:  # it came off someone else: no longer his touch to run onto
            self.dribbler = None
        self.kicker_clear = False
        self.kicked_at = self.t  # a new strike of the ball: everyone reacts to it again
        self.chase = {}

    def touched(self, p: Player, x: float, y: float, controls: bool) -> bool:
        """Resolve the pass or shot in flight from who touched it, and how: observed, never
        intended. Called with the ball as it arrived, before the touch changes it. Returns True
        if the touch stopped play (an offside offence)."""
        if p.id in self.offside:  # L10: he was offside when it was played, and now plays it
            self.offside_offence(p, x, y)
            return True
        if p.team != (self.team_of(self.last_touch) if self.last_touch else p.team) and controls:
            self.offside = set()  # an opponent's deliberate play: a new phase
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
                kicked.update(receiver=p.id if done else None, end_x=round(x, 2), end_y=round(y, 2),
                              outcome="success" if done else "fail")
                self.kicked = None
            elif not same_team:  # an opponent got to it: the pass has failed
                kicked.update(receiver=p.id, end_x=round(x, 2), end_y=round(y, 2), outcome="fail")
                if controls and self.in_the_lane(kicked, x, y):
                    # Cut out on its way: an interception. Collected where it was going (a long
                    # ball dropping to a defender) is a recovery: the possession change says it.
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
        if controls or (same_team and p.id != kicked["player"]):
            # Controlled, or touched by a team-mate: the shot is over, and if the ball now goes
            # in, it is the goal of whoever touched it last (C8).
            self.close_shot(kicked, x, y)
        # A defender's block or a keeper's parry leaves the shot in flight: it may still go in.

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
        """Law 1: the ball rebounds off the goal frame (both posts and the crossbar, corners
        included) wherever its path this frame first comes within touching distance (ball radius
        plus post radius) of it, from any direction, including a ball moving along the goal line.
        Posts stand on the goal lines with their inner edges 7.32 m apart, so their axes are a post
        radius further out; the bar's axis is a radius above 2.44 m. At the touch, the velocity the
        ball had at that moment is reflected about the line from the frame's axis to the ball's
        centre, keeping WOODWORK_RESTITUTION of the speed into it (a glancing touch only nudges the
        ball), and the ball rebounds from where it touched. A ball that starts the frame already
        overlapping (resting on the bar) is first moved out to touching distance."""
        r, touching = ball.RADIUS, ball.RADIUS + POST_RADIUS
        p0 = (before[0], before[1], before[2] + r)  # ball centres
        p1 = (self.ball[0], self.ball[1], self.ball[2] + r)
        def at(s: float) -> tuple[float, float, float]:
            return tuple(a + s * (b - a) for a, b in zip(p0, p1, strict=True))

        for line in (0.0, PITCH_X):
            if min(abs(p0[0] - line), abs(p1[0] - line)) > touching + abs(p1[0] - p0[0]):
                continue
            s = first_contact(lambda s, line=line: frame_gap(at(s), line), touching)
            if s is None:
                continue
            centre = at(s)
            gap, axis_point = frame_gap(centre, line)
            n = unit(*(c - a for c, a in zip(centre, axis_point, strict=True)))
            if gap < touching:  # overlapping from the start: out to touching distance
                centre = tuple(a + touching * k for a, k in zip(axis_point, n, strict=True))
            v = tuple(a + s * (b - a) for a, b in zip(before[3:6], self.ball[3:6], strict=True))
            into = v[0] * n[0] + v[1] * n[1] + v[2] * n[2]
            if into >= 0:
                return  # touching but moving away: nothing to do
            k = (1 + WOODWORK_RESTITUTION) * into
            vx, vy, vz = (a - k * b for a, b in zip(v, n, strict=True))
            self.ball = (centre[0], centre[1], max(centre[2] - r, 0.0), vx, vy, vz)
            self.kicked_at = self.t
            self.chase = {}
            return

    def went_out(self, before: ball.State) -> bool:
        """Law 9: out once the whole ball has crossed a goal line or touchline. Where and how high
        it crossed is taken at the line, not wherever the ball is a frame later."""
        bx, by, bz = self.ball[0], self.ball[1], self.ball[2]
        if not decisions.out_of_play(bx, by):
            return False
        r = ball.RADIUS
        over_goal_line = bx < -r or bx > PITCH_X + r
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
            touch = self.last_deflection  # only a touch since the last kick or control (reset there)
            struck = kicked if kicked and kicked["type"] == "pass" and kicked["player"] == scorer else None
            if scorer and not shot and not touch and struck:
                # His own pass went straight in: that strike was his attempt.
                struck.update(type="shot", outcome="goal", receiver=None,
                              end_x=round(x, 2), end_y=round(y, 2))
            if scorer and not shot and touch and touch["player"] == scorer:
                # It went in off him: the touch that sent it in is his attempt, as event data records it,
                # and a team-mate's pass he turned in reached him there.
                touch.update(type="shot", outcome="goal", end_x=round(x, 2), end_y=round(y, 2))
                turned_in = kicked and kicked["type"] == "pass" and kicked["team"] == team
                if turned_in and kicked["frame"] < touch["frame"]:
                    own = kicked["player"] == scorer  # his own pass back off himself: not received
                    kicked.update(receiver=None if own else scorer, end_x=touch["x"], end_y=touch["y"],
                                  outcome="fail" if own else "success")
        self.emit("goal", team, x, y, player=scorer)
        self.kickoff(other(team))

    def stop(self, kind: str, team: str, spot: tuple[float, float], taker: str | None = None) -> None:
        if kind == "corner":  # both teams set up; it is taken when they are ready (setpieces.py)
            self.set_play = setpieces.plan(self, team, spot)
            self.restart = Restart(kind, team, spot[0], spot[1], self.set_play.taker, math.inf)
            return
        self.set_play = None
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
        if r.kind == "corner":  # placed, then struck on the taker's run-up (setpieces.py)
            if setpieces.advance(self):
                self.restart = None
                self.from_restart = "corner"
                setpieces.deliver(self, taker)
            return
        if self.t < r.ready_at or math.hypot(taker.x - r.x, taker.y - r.y) > CONTROL_M:
            return
        # While the ball is out of play a new one is placed: the only time the ball may jump.
        self.ball = (taker.x, taker.y, 0.0, 0.0, 0.0, 0.0)
        self.restart = None
        if r.kind != "kick_off":  # a kickoff was recorded when the teams set up
            self.emit("set_piece", r.team, taker.x, taker.y, player=taker.id, outcome=None)
        if r.team != self.poss_team:
            self.emit("possession_change", r.team, taker.x, taker.y, player=taker.id)
        self.give(taker.id)
        self.hold_until = self.t + self.rng.uniform(0.5, 1.5)
        self.throw_by = taker.id if r.kind == "throw_in" else None
        self.throw_ready = self.t
        self.from_restart = r.kind

    def corner_ready(self) -> None:
        """The corner is ready: the ball placed (setpieces.advance), everyone set and the Law's
        distance kept, and the taker starts his run-up. From here the ball stays still until he
        strikes it, and opponents keep 9.15 m (L9 checks every frame from this event)."""
        c, r = self.set_play, self.restart
        px, py = c.ball_spot
        self.emit("set_piece", r.team, px, py, player=c.taker, outcome=None)
        if r.team != self.poss_team:
            self.emit("possession_change", r.team, px, py, player=c.taker)
            self.pressed.clear()
            self.poss_team = r.team

    # ---- tick ---------------------------------------------------------------

    def play_point(self, p: Player | None = None, team: str | None = None) -> tuple[float, float]:
        """Where play is, for setting shape (O8): once a pass is struck, players set up for where
        it is going rather than chasing the ball's every metre in flight. Only the passer and the
        team-mate he played it to know where he meant it; everyone else must first react to the
        struck ball (until then play is where it was struck), then goes by where they see it going
        (its own path). A team brain (`team`) of the passing side knows where it was meant; the
        other side's reacts like an average player."""
        bx, by = self.ball[0], self.ball[1]
        if self.kicked and self.kicked["type"] == "pass" and self.pass_target and not self.last_deflection:
            sx, sy = self.kicked["x"], self.kicked["y"]
            tx, ty = self.pass_target
            if (bx - sx) * (tx - sx) + (by - sy) * (ty - sy) < (tx - sx) ** 2 + (ty - sy) ** 2:
                if p is not None:
                    knows = p.id in (self.intended, self.released_by)
                else:
                    knows = team == self.kicked["team"]
                if knows:
                    return self.pass_target  # he knows where it was meant to go
                react = self.reaction(p) if p is not None else decisions.GENERIC_REACTION_S
                if self.t - self.kicked_at < react:
                    return sx, sy  # not yet reacted to the strike
                return self.seen_going
        return bx, by

    def ball_destination(self) -> tuple[float, float]:
        """Where players who see a ball struck can tell play is going: the first point of its own
        flight that somebody other than the kicker can get to in time after a choice reaction, by
        the chase's own test (can_reach), else where it leaves the pitch or comes to rest. Judged
        from where players really are (*design*: their misjudgement is not modelled here)."""
        path = ball.predict(self.ball, DT, ball.FLIGHT_BOUND_S)  # the path ends when the ball rests
        others = [p for p in self.players if p.id != self.released_by]
        for k in range(0, len(path), 2):  # every other frame, as the chase plans
            s = path[k]
            if not (0.0 <= s[0] <= PITCH_X and 0.0 <= s[1] <= PITCH_Y):
                return clamp(s[0], 0.0, PITCH_X), clamp(s[1], 0.0, PITCH_Y)
            if k * DT <= perception.CHOICE_REACTION_S:
                continue  # nobody has reacted to the strike yet
            for p in others:  # the same test the chase uses, after he reacts to the strike
                if self.can_reach(p, s[0], s[1], s[2], k * DT, perception.CHOICE_REACTION_S)[0]:
                    return s[0], s[1]
        return path[-1][0], path[-1][1]

    def ball_eta(self, x: float, y: float) -> float:
        """How soon the ball could next be played to (x, y) (O8): first it has to be somewhere a
        player can play it from, then a pass covers the distance at about a pass's average speed.
        A restart waits until it is taken; a pass in flight first reaches where it was aimed and is
        settled there; a carrier must first be ready."""
        bx, by, _, vx, vy, _ = self.ball
        if self.restart:
            wait = max(0.0, self.restart.ready_at - self.t)
            bx, by = self.restart.x, self.restart.y
        elif self.possessor:
            wait = max(0.0, self.hold_until - self.t)
        elif self.kicked and self.pass_target:
            ax, ay = self.pass_target
            wait = math.hypot(ax - bx, ay - by) / max(math.hypot(vx, vy), 1.0) + settle_s(AVERAGE)
            bx, by = ax, ay
        else:  # loose: whoever gets to it first has to settle it before he can play it
            wait = settle_s(AVERAGE)
        return wait + math.hypot(x - bx, y - by) / decisions.PASS_SPEED_EST_MPS

    def in_time(self, p: Player, tx: float, ty: float) -> float:
        """O8: the speed he chooses to get to (tx, ty): just enough to be there before the ball could
        be, so far from the ball he walks and near it he bursts; his body caps it."""
        return math.hypot(tx - p.x, ty - p.y) / max(self.ball_eta(tx, ty), DT)

    def shape_target(self, p: Player) -> tuple[float, float, float]:
        """Where a player off the ball wants to be, and how fast they go there."""
        chase = self.chase.get(p.team)
        if p.id in self.lunges:  # committed: straight at the ball
            return self.ball[0], self.ball[1], SPRINT
        if self.off_balance.get(p.id, -1.0) > self.t:  # beaten: getting up, out of the play
            return p.x, p.y, SHAPE
        if p.id == self.dribbler:  # running onto his own touch, a little faster than the ball
            # He runs along its path toward where it would stop, not at a point just ahead of it:
            # steering stops on its target, so a target beside the ball keeps him behind it.
            rest = ball.predict(self.ball, DT, 6.0)[-1]
            onto = math.hypot(self.ball[3], self.ball[4]) + 1.0  # design: he closes on it at about 1 m/s
            return clamp(rest[0], 0.5, PITCH_X - 0.5), clamp(rest[1], 0.5, PITCH_Y - 0.5), onto
        # Targets stay on the pitch so players brake for the line instead of stopping dead at it.
        if chase and chase[0] == p.id:
            return clamp(chase[1], 0.5, PITCH_X - 0.5), clamp(chase[2], 0.5, PITCH_Y - 0.5), SPRINT
        if self.read and self.read[0] == p.id and self.possessor is None and self.kicked:
            # Sideways at the depth he has set, not back toward his line: a keeper who has come out
            # to narrow the angle stays there.
            post = PITCH_Y / 2 - GOAL_HALF_WIDTH, PITCH_Y / 2 + GOAL_HALF_WIDTH
            return p.x, clamp(self.read[1], *post), SPRINT
        if self.set_play and setpieces.over(self):  # S3: the routine has had its say
            self.set_play = None
        if self.set_play:  # a corner: his spot in the routine (setpieces.py)
            spot = setpieces.target(self, p)
            if spot:
                if p.id == self.set_play.taker:  # behind the ball: off the pitch, by the flag
                    return spot[0], spot[1], RECOVER
                sx, sy = clamp(spot[0], 0.5, PITCH_X - 0.5), clamp(spot[1], 0.5, PITCH_Y - 0.5)
                if setpieces.running(self, p):
                    return sx, sy, SPRINT
                far = math.hypot(sx - p.x, sy - p.y) > setpieces.SET_UP_FAR_M
                return sx, sy, RECOVER if far else SHAPE
        if self.restart and self.restart.kind == "kick_off" and p.id != self.restart.taker:
            return *self.kickoff_spot(p, self.restart.team), SHAPE  # Law 8: until the ball is kicked
        if self.restart and p.id == self.restart.taker:
            r = self.restart
            return clamp(r.x, 0.5, PITCH_X - 0.5), clamp(r.y, 0.5, PITCH_Y - 0.5), RECOVER
        bx, by = self.play_point(p)  # O8: where the ball is going, once a pass is struck
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
                mates = [w for w in (view.where(q.id, self.t) for q in self.players
                                     if q.team == p.team and q.id != p.id) if w]
                if offball.through_on_goal(seen, own_goal, mates):  # O1: come out and narrow it
                    return *offball.close_down_spot(seen, own_goal), SPRINT
            # He sets himself from where the ball is, not where a pass is going: a shot can come
            # from wherever the ball is now.
            kx, ky = clamp(self.ball[0], 0, PITCH_X), clamp(self.ball[1], 0, PITCH_Y)
            return *offball.keeper_spot(kx, ky, own_goal), RECOVER
        if not brain.in_possession and p.id in brain.markers:
            mx, my = brain.markers[p.id]
            mx, my = clamp(mx, 0.5, PITCH_X - 0.5), clamp(my, 0.5, PITCH_Y - 0.5)
            seen = self.beliefs[p.id].seen
            man = min((q for q in self.players if q.team != p.team and q.id in seen),
                      key=lambda q: math.hypot(seen[q.id].x - mx, seen[q.id].y - my), default=None)
            # His spot moves with his man: he matches the man's velocity and closes the gap on top,
            # and never goes slower than in time for the spot itself (he steers at the spot, so a
            # man running toward him does not make a late arrival on time).
            mvx, mvy = (seen[man.id].vx, seen[man.id].vy) if man else (0.0, 0.0)
            gap = math.hypot(mx - p.x, my - p.y)
            need = self.in_time(p, mx, my)
            close = need / gap if gap > 1e-6 else 0.0
            return mx, my, max(need, math.hypot(mvx + (mx - p.x) * close, mvy + (my - p.y) * close))
        carrier = self.by_id.get(self.possessor) if self.possessor else None
        if brain.in_possession and carrier and carrier.team == p.team and p.role != "GK":
            run = self.run_target(p, carrier, brain)
            if run:
                return *run, SPRINT
            mates = sorted((q for q in self.players if q.team == p.team and q.id not in (carrier.id,)
                            and q.role != "GK"), key=lambda q: math.hypot(q.x - carrier.x, q.y - carrier.y))
            if p in mates[:2]:  # O3: the nearest two offer a diagonal option
                presser = self.nearest(carrier.x, carrier.y, other(p.team))
                sx, sy = offball.support_spot((p.x, p.y), (carrier.x, carrier.y), goal_x(p.team),
                                              (presser.x, presser.y))
                return sx, sy, self.in_time(p, sx, sy)
        if brain.in_possession and p.role != "GK":  # O6: the team's shape with the ball (also in flight)
            seen = [w for w in (self.beliefs[p.id].where(q.id, self.t) for q in self.players
                                if q.team != p.team) if w]
            onside = self.onside_limit(p.team, seen, bx)  # L10: as far as he sees he may go
            spot = offball.attacking_slot(p.role, PITCH_X - goal_x(p.team), clamp(bx, 0, PITCH_X),
                                          clamp(by, 0, PITCH_Y), onside)
            if spot:
                return *spot, self.in_time(p, *spot)
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
            engaged = presser is not None and brain.presses(self.t, bx)
            if presser is p and engaged:
                # Press goal-side, a step away, matching where the carrier is going (D8: a defender
                # keeps his speed relative to the attacker small rather than holding a spot).
                carrier = self.by_id.get(self.possessor) if self.possessor else None
                lead_x = carrier.vx * JOCKEY_LOOKAHEAD_S if carrier else 0.0
                lead_y = carrier.vy * JOCKEY_LOOKAHEAD_S if carrier else 0.0
                return *on_pitch(bx + lead_x + gx * gap, by + lead_y + gy * gap), work
            if engaged and brain.pressers[1:2] == [p.id]:  # cover: behind the presser, goal-side
                cx, cy = on_pitch(bx + gx * max(COVER_M, gap + 2), by + gy * max(COVER_M, gap + 2))
                return cx, cy, self.in_time(p, cx, cy)
            slot = brain.slot(p.role, p.ay, clamp(by, 0, PITCH_Y))
            if slot:
                tx, ty = slot
        tx, ty = clamp(tx, 0.5, PITCH_X - 0.5), clamp(ty, 0.5, PITCH_Y - 0.5)
        return tx, ty, self.in_time(p, tx, ty)

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
            bx, by = self.play_point(team=team)
            for p in self.players:
                if p.team != team or p.role == "GK":
                    continue
                dx, dy = bx - p.x, by - p.y
                d = math.hypot(dx, dy)
                along = (p.vx * dx + p.vy * dy) / (d or 1.0)
                reach[p.id] = p.physique.time_to_cover(d, along)
            brain.update(self.t, holder == team, bx, reach)
            if holder != team:  # O2: pick up the attackers who threaten our goal
                free = {p.id: (p.x, p.y) for p in self.players
                        if p.team == team and p.role != "GK" and p.id not in brain.pressers}
                brain.markers = offball.marking(free, self.shared_view(team, other(team)),
                                                PITCH_X - goal_x(team))
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
        defenders = sorted((w[0] for w in (view.where(q.id, self.t) for q in self.players
                                           if q.team != p.team) if w), key=lambda x: -attack_dir(p.team) * x)
        second_last = defenders[1] if len(defenders) > 1 else PITCH_X - goal_x(p.team)
        onside = (second_last - p.x) * attack_dir(p.team) >= 0
        their_line = self.brains[other(p.team)].line_x
        spot = offball.run_in_behind((p.x, p.y), their_line, goal_x(p.team), can_play, onside)
        if spot:
            self.runs[p.id] = (*spot, self.t)
        return spot

    def stretch_from(self, p: Player) -> float:
        """When the keeper's arms began to stretch: when his dive began to be prepared (his reaction
        to the touch that set it off), or his reaction to the last touch."""
        if self.dive and self.dive[0] == p.id:
            return self.dive[4]
        if self.landed and self.landed[0] == p.id and self.off_balance.get(p.id, -1.0) > self.t:
            return self.landed[1]  # down after a dive: stretched out as he landed
        return self.kicked_at + self.reaction(p)

    def ball_at_x(self, x: float, seconds: float = 10.0) -> tuple[float, float, float] | None:
        # `seconds`: only a bound; the ball's own path stops when it comes to rest
        """(seconds from now, y, height) when the ball, in its own flight (drag and gravity),
        reaches x; None if it does not within `seconds`."""
        bx, vx = self.ball[0], self.ball[3]
        if abs(vx) < 1e-6 or (x - bx) * vx <= 0:
            return None
        path = ball.predict(self.ball, DT, seconds)
        for k in range(1, len(path)):
            a, b = path[k - 1], path[k]
            if (b[0] - x) * vx >= 0:  # crossed between these two steps: interpolate
                f = (x - a[0]) / (b[0] - a[0]) if b[0] != a[0] else 1.0
                return (k - 1 + f) * DT, a[1] + f * (b[1] - a[1]), a[2] + f * (b[2] - a[2])
        return None

    def keeper_dive(self, p: Player) -> bool:
        """P15: once the keeper has reacted to a shot, he dives toward where it will cross his line:
        his body travels sideways (up to KEEPER_DIVE_TRAVEL_M, only as far as he needs beyond his
        standing reach) with the one push of every dive (offball.dive_distance), and he is down for a
        moment afterwards. True while the dive moves him."""
        k = self.kicked
        shot_at_him = k and k["type"] == "shot" and k["team"] != p.team and self.possessor is None
        reacted = self.t - self.kicked_at >= self.reaction(p)  # to the last touch, a deflection too
        if self.dive is None and shot_at_him and reacted and self.off_balance.get(p.id, -1.0) <= self.t:
            arrival = self.ball_at_x(p.x)  # where the ball's own flight takes it past him
            if arrival and arrival[2] <= HAND_REACH_Z:  # not one going over him
                when, cross = arrival[0], arrival[1]
                # only as far as his body must go beyond what his arms will reach by then; his arms
                # began to stretch when he reacted, whenever the dive itself starts
                stretched = self.t - self.stretch_from(p) + when
                need = abs(cross - p.y) - offball.arm_reach_m(stretched)
                if need > 0:
                    travel = math.copysign(min(need, KEEPER_DIVE_TRAVEL_M), cross - p.y)
                    bound = offball.dive_time_from(travel, p.vy * math.copysign(1.0, travel), abs(p.vx))
                    self.dive = (p.id, self.t, p.y, travel, self.kicked_at + self.reaction(p), bound)
        if not self.dive or self.dive[0] != p.id:
            return False
        _, start, y0, travel, _, bound = self.dive
        elapsed = self.t + DT - start
        # The push (P15) is one force: it turns his velocity, however he was moving, toward the
        # dive's (straight along his line at the peak speed, or faster if he already was) at no
        # more than DIVE_ACCEL, so a keeper moving the other way, or off his line, is first stopped
        # by it. A shorter dive is the same push ended sooner, never the full dive played faster.
        # It ends once he has covered the travel, with the body still moving: he lands and brakes
        # like any player (P2), rather than stopping dead in the air. `bound` is the longest that
        # can take (it guards only against something stopping him).
        side = math.copysign(1.0, travel)
        dvx, dvy = -p.vx, side * max(offball.DIVE_PEAK_MPS, side * p.vy) - p.vy
        need = math.hypot(dvx, dvy)
        step = min(need, offball.DIVE_ACCEL * DT)
        vx = p.vx + (dvx / need * step if need > 1e-9 else 0.0)
        vy = p.vy + (dvy / need * step if need > 1e-9 else 0.0)
        p.x, p.y = p.x + (p.vx + vx) / 2 * DT, p.y + (p.vy + vy) / 2 * DT  # even push over the frame
        p.vx, p.vy = vx, vy
        p.physique.grip_used = step  # the push is his grip this frame: nothing else adds to it
        if side * (p.y - y0) >= abs(travel) or elapsed >= bound:
            self.landed = (p.id, self.dive[4])
            self.dive = None
            self.off_balance[p.id] = self.t + offball.KEEPER_DOWN_S  # on the ground: getting up
        return True

    def move_players(self) -> None:
        for p in self.players:
            if p.id == self.moved:
                continue
            if p.role == "GK" and self.keeper_dive(p):
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
            pace = decisions.dribble_speed(carrier.profile["dribbling"])
            if self.closest_opponent(carrier) < CLOSE_CONTROL_M:
                pace *= CLOSE_CONTROL_PACE  # close control: slower, the ball never leaves his feet
            steer(carrier, tx, ty, pace)
            if math.hypot(tx - carrier.x, ty - carrier.y) < 1.0:
                self.dribble_to = None
        elif self.t < self.hold_until and carrier.role != "GK":
            # A4: settling the ball he does not stop dead: he takes it in his stride and carries on
            # the way he was going, no faster than he can dribble, slower in close control.
            pace = min(math.hypot(carrier.vx, carrier.vy),
                       decisions.dribble_speed(carrier.profile["dribbling"]))
            if self.closest_opponent(carrier) < CLOSE_CONTROL_M:
                pace *= CLOSE_CONTROL_PACE
            steer(carrier, clamp(carrier.x + carrier.vx, 1.0, PITCH_X - 1.0),
                  clamp(carrier.y + carrier.vy, 1.0, PITCH_Y - 1.0), pace)
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
        side = carrier.heading
        if not self.dribble_to and not self.windup:  # D8: holding, he keeps his body between ball and man
            near = min((q for q in self.players if q.team != carrier.team),
                       key=lambda q: math.hypot(q.x - carrier.x, q.y - carrier.y))
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
            if self.touch_ahead(carrier):
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
        return any(q.team == p.team and q is not p and abs(q.x - own) < abs(p.x - own)
                   and math.hypot(q.x - p.x, q.y - p.y) < COMMIT_COVER_M for q in self.players)

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
            victim = self.by_id.get(self.lunge_at.pop(pid, ""))
            if holder and holder.team != p.team and math.hypot(p.x - bx, p.y - by) <= CONTROL_M:
                self.poke(p, holder)
                holder = None
            elif victim and not self.restart and self.leg_meets(p, victim, bx, by):
                self.foul(p, victim)
                return
            else:
                self.off_balance[pid] = self.t + OFF_BALANCE_S
        if not holder or self.restart or self.hands(holder, holder.x, holder.y):  # Law 12: not his hands
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
                self.lunge_at[p.id] = holder.id
                self.evade_at[p.id] = self.t + holder.profile.reaction()

    @staticmethod
    def leg_meets(p: Player, victim: Player, bx: float, by: float) -> bool:
        """Law 12: a lunge that arrives with the ball gone still sweeps his leg toward it, a foot's
        reach (CONTROL_M) from his body. If that leg passes through the man he went for, he has
        made contact with the opponent, not the ball."""
        dx, dy = bx - p.x, by - p.y
        d = math.hypot(dx, dy)
        if d < 1e-6:
            return False
        fx, fy = p.x + dx / d * min(d, CONTROL_M), p.y + dy / d * min(d, CONTROL_M)
        sx, sy = fx - p.x, fy - p.y
        k = clamp(((victim.x - p.x) * sx + (victim.y - p.y) * sy) / (sx * sx + sy * sy), 0.0, 1.0)
        return math.hypot(p.x + k * sx - victim.x, p.y + k * sy - victim.y) <= BODY_RADIUS

    def foul(self, p: Player, victim: Player) -> None:
        """Law 12: a careless challenge that hits the man: a direct free kick to his side where it
        happened (Law 13); in the offender's own penalty area, a penalty kick (Law 14)."""
        kicked, (bx, by) = self.kicked, self.ball[:2]
        if kicked and kicked["type"] == "pass":  # the whistle stops a pass that had not arrived
            kicked.update(end_x=round(bx, 2), end_y=round(by, 2), outcome="fail")
        elif kicked and kicked["type"] == "shot":
            self.close_shot(kicked, bx, by)
        self.kicked = None
        self.emit("foul", p.team, victim.x, victim.y, player=p.id, receiver=victim.id)
        self.off_balance[p.id] = self.t + OFF_BALANCE_S
        self.lunges.clear(), self.lunge_at.clear(), self.evade_at.clear()
        self.possessor = self.dribbler = self.dribble_to = self.windup = None
        self.chase = {}
        own_goal_x = PITCH_X if attack_dir(p.team) < 0 else 0.0
        if decisions.in_box(victim.x, victim.y, own_goal_x):
            self.penalties += 1
        self.stop("free_kick", victim.team, (clamp(victim.x, 0.5, PITCH_X - 0.5),
                                             clamp(victim.y, 0.5, PITCH_Y - 0.5)))

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
        heading = math.atan2(p.vy, p.vx) if math.hypot(p.vx, p.vy) > 0.5 else \
            math.atan2(self.ball[1] - p.y, self.ball[0] - p.x)
        angle = heading + math.radians(self.rng.gauss(0.0, 40.0))
        self.ball = (self.ball[0], self.ball[1], 0.0, holder.vx * 0.3 + POKE_MPS * math.cos(angle),
                     holder.vy * 0.3 + POKE_MPS * math.sin(angle), 0.0)
        self.tackle = self.emit("tackle", p.team, self.ball[0], self.ball[1], player=p.id, receiver=holder.id,
                                outcome=None)
        self.possessor, self.dribbler, self.dribble_to, self.windup = None, None, None, None
        self.last_touch = p.id
        self.kicked_at = self.free_since = self.t
        self.kicker_clear, self.touched_since_kick = False, True
        self.plan_chase()

    def touch_speed(self, carrier: Player, ux: float, uy: float, lo: float, hi: float) -> float | None:
        """D6: the hardest push up to `hi` that is his whatever his own kick error does to it (A3:
        the strikes decisions.strike_nodes weighs, the centre and root-3 SDs of direction and
        speed): his body runs onto it within TOUCH_GAP_S (the engine's race, can_reach, on the
        ball's own path) and no opponent, where he believes them to be and going, gets to it first
        (the passer's race: an average body, a foot's reach; a touch along his line needs no
        reaction from them, P12). None if even the softest is not his: he keeps it at his feet. A
        rolling ball keeps most of its speed, so a push sized only by how far ahead it should go
        would run away from him."""
        bx, by = self.ball[0], self.ball[1]
        view = self.beliefs[carrier.id]
        near, felt = [], math.inf
        for q in self.players:
            w = view.where(q.id, self.t) if q.team != carrier.team else None
            if w:
                felt = min(felt, math.hypot(w[0] - carrier.x, w[1] - carrier.y))
                v = view.velocity(q.id)
                # Beyond what he could cover while the ball is free (the race's own body, or faster
                # if he is seen going faster), there is no race: pruning only.
                reach = max(decisions.AVERAGE_BODY.top_speed(), math.hypot(*v)) * TOUCH_GAP_S
                if math.hypot(w[0] - bx, w[1] - by) < hi * TOUCH_GAP_S + reach + CONTROL_M:
                    near.append((w, v))
        heading = math.atan2(uy, ux)
        turn = decisions.turn_deg(heading, carrier.heading)

        def lands(v: float, angle: float) -> bool:
            path = ball.predict((bx, by, 0.0, math.cos(angle) * v, math.sin(angle) * v, 0.0), DT, TOUCH_GAP_S)
            x, y, z = path[-1][:3]
            if not self.can_reach(carrier, x, y, z, TOUCH_GAP_S)[0]:
                return False
            for k in range(3, len(path), 3):
                x, y = path[k][0], path[k][1]
                for (wx, wy), (vx, vy) in near:
                    if can_get_to(decisions.AVERAGE_BODY, x - wx, y - wy, CONTROL_M, vx, vy, k * DT)[0]:
                        return False
            return True

        def his(v: float) -> bool:
            dir_sd, speed_sd, _, foot = carrier.profile.strike_error("dribbling", v, felt,
                                                                     self.fresh(carrier), turn)
            n = decisions.NODE_SD
            strikes = [(decisions.struck_speed(v, 0.0, foot), heading)]
            strikes += [(decisions.struck_speed(v, k * n * speed_sd, foot), heading) for k in (-1, 1)]
            strikes += [(strikes[0][0], heading + math.radians(k * n * dir_sd)) for k in (-1, 1)]
            return all(lands(sv, a) for sv, a in strikes)

        if not his(lo):
            return None
        if his(hi):
            return hi
        for _ in range(8):
            mid = (lo + hi) / 2
            lo, hi = (mid, hi) if his(mid) else (lo, mid)
        return lo

    def touch_ahead(self, carrier: Player) -> bool:
        """D6: a dribbling touch. The ball goes ahead of him toward where he is carrying it, further
        with space, struck with his own error; he runs onto it, and it is free until he gets there."""
        tx, ty = self.dribble_to
        bx, by = self.ball[0], self.ball[1]
        d = math.hypot(tx - bx, ty - by)
        if d < 0.5:
            self.dribble_to = None
            return False
        view = self.beliefs[carrier.id]
        felt = min((math.hypot(w[0] - carrier.x, w[1] - carrier.y) for w in
                    (view.where(q.id, self.t) for q in self.players if q.team != carrier.team) if w),
                   default=99.0)
        space = clamp((felt - 2.0) / 8.0, 0.0, 1.0)
        ahead = TOUCH_CLOSE_M + TOUCH_SPACE_M * space
        run = max(decisions.dribble_speed(carrier.profile["dribbling"]), math.hypot(carrier.vx, carrier.vy))
        speed = self.touch_speed(carrier, (tx - bx) / d, (ty - by) / d, run, run + ahead / TOUCH_GAP_S)
        if speed is None:  # no push is his: close control, the ball stays at his feet
            return False
        vx, vy, vz = self.execute(carrier, (tx - bx) / d * speed, (ty - by) / d * speed, 0.0, "dribbling")
        self.ball = (bx, by, self.ball[2], vx, vy, vz)
        self.possessor = None
        self.last_touch = carrier.id
        self.dribbler = carrier.id
        # A touch that carries on the way he was running is what everyone watching expects; only
        # a sharp change of direction is a new event they must react to (P12).
        moving = math.hypot(carrier.vx, carrier.vy) > 1.0
        turn = abs((math.atan2(vy, vx) - math.atan2(carrier.vy, carrier.vx) + math.pi)
                   % (2 * math.pi) - math.pi)
        if not moving or turn > math.radians(TOUCH_EXPECTED_DEG):
            self.kicked_at = self.t
        self.free_since = self.t
        self.kicker_clear = False
        self.touched_since_kick = True
        # Who goes for the loose ball is judged at once: a defender who has been watching the carry
        # and can get there first commits to it, rather than keep shadowing.
        self.plan_chase()
        return True

    def open_with_wide_attack(self) -> None:
        """Scenario mode: the clip opens in play with a home winger on the ball in the final third
        near his touchline, and everyone where the open-play shape rules put them for that ball
        (S9). The wing, how far from the goal line and the touchline, and which way he faces are
        drawn from the seed; the ball is at his feet where the carry rule keeps it. Nothing more
        is set: whatever happens next is played."""
        winger = self.rng.choice([p for p in self.players if p.team == "home" and p.role in ("RW", "LW")])
        near_side = winger.ay < PITCH_Y / 2
        wide = self.rng.uniform(*WIDE_FROM_TOUCHLINE_M)
        y = wide if near_side else PITCH_Y - wide
        x = PITCH_X - self.rng.uniform(*WIDE_FROM_GOAL_LINE_M)
        # He faces anywhere from straight at the goal line to straight infield.
        infield = math.radians(self.rng.uniform(0.0, WINGER_TURN_DEG))
        heading = infield if near_side else -infield
        self.ball = (x, y, 0.0, 0.0, 0.0, 0.0)
        self.poss_team = "home"
        for _ in range(2):  # shape, then re-read the game from where that shape put everyone
            for team, brain in self.brains.items():
                reach = {p.id: p.physique.time_to_cover(math.hypot(p.x - x, p.y - y), 0.0)
                         for p in self.players if p.team == team and p.role != "GK"}
                brain.update(self.t, team == "home", x, reach)
            for p in self.players:
                p.x, p.y, _ = self.shape_target(p)
        # The ball at his feet where the carry rule keeps it: on the side he faces, or shielded
        # from an opponent within SHIELD_M (D8), never inside his body.
        winger.heading = heading
        near = min((q for q in self.players if q.team == "away"), key=lambda q: math.hypot(q.x - x, q.y - y))
        shielded = math.hypot(near.x - x, near.y - y) < SHIELD_M
        side = math.atan2(y - near.y, x - near.x) if shielded else heading
        feet = BODY_RADIUS + ball.RADIUS
        winger.x, winger.y = x - math.cos(side) * feet, y - math.sin(side) * feet
        self.give(winger.id)

    def play_until_corner(self) -> bool:
        """Play on from the opening until the home side is given a corner (True), or the attack is
        over (False): a goal, a goal kick, a corner the other way, the away side on the ball 40 m
        or more from the goal being attacked, or CORNER_WITHIN_S gone (S9)."""
        while self.t < CORNER_WITHIN_S:
            self.step()
            r = self.restart
            if r and r.kind == "corner":
                return r.team == "home"
            if r and r.kind in ("goal_kick", "kick_off"):
                return False
            if self.possessor and self.team_of(self.possessor) == "away" and \
                    PITCH_X - self.ball[0] >= ATTACK_OVER_M:
                return False
        return False

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

    def step(self) -> None:
        """One frame of the match."""
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

    def run(self, minutes: float) -> Match:
        self.kickoff("home")
        for _ in range(int(minutes * 60 * FPS)):
            self.step()
        return self.match


def unit(x: float, y: float, z: float) -> tuple[float, float, float]:
    n = math.sqrt(x * x + y * y + z * z) or 1.0
    return x / n, y / n, z / n


def frame_gap(p: tuple[float, float, float], line: float) -> tuple[float, tuple[float, float, float]]:
    """Distance from a ball centre to the goal frame on this goal line (the axes of both posts,
    ground to bar, and of the crossbar), and the nearest point on those axes."""
    half = GOAL_HALF_WIDTH + POST_RADIUS
    lo, hi, top = PITCH_Y / 2 - half, PITCH_Y / 2 + half, CROSSBAR + POST_RADIUS
    best = None
    for a, b in (((line, lo, 0.0), (line, lo, top)), ((line, hi, 0.0), (line, hi, top)),
                 ((line, lo, top), (line, hi, top))):
        d = tuple(q - o for q, o in zip(b, a, strict=True))
        t = sum((pc - ac) * dc for pc, ac, dc in zip(p, a, d, strict=True)) / sum(dc * dc for dc in d)
        t = min(1.0, max(0.0, t))
        q = tuple(ac + t * dc for ac, dc in zip(a, d, strict=True))
        g = math.dist(p, q)
        if best is None or g < best[0]:
            best = (g, q)
    return best


def first_contact(gap_at, touching: float, samples: int = 32) -> float | None:
    """The first s (0 to 1) along a step where gap_at(s)[0] falls to `touching`, found by sampling
    the step and then halving the interval; 0 if it starts there, None if it never does."""
    if gap_at(0.0)[0] <= touching:
        return 0.0
    prev = 0.0
    for k in range(1, samples + 1):
        s = k / samples
        if gap_at(s)[0] <= touching:
            lo, hi = prev, s
            for _ in range(30):
                mid = (lo + hi) / 2
                lo, hi = (lo, mid) if gap_at(mid)[0] <= touching else (mid, hi)
            return hi
        prev = s
    return None


def corner_seed(seed: int, attempt: int) -> int:
    return CORNER_SEED_BASE + seed * 1000 + attempt


def simulate(seed: int, minutes: float, scenario: str | None = None) -> Match:
    """A match from the kick-off, or a scenario clip. `corner`: attacks from a wide opening are
    played out, each with its own engine seed (corner_seed), and the first one that play turns
    into a home corner is kept and run on for `minutes` after the corner is given (S9). The match
    records the engine seed it used. Selection among played-out attacks, never an arranged one:
    corners from this scenario say nothing about how often play produces them."""
    if scenario is None:
        return Engine(seed).run(minutes)
    if scenario != "corner":
        raise ValueError(f"unknown scenario {scenario!r}; known: corner")
    for attempt in range(CORNER_ATTEMPTS):
        e = Engine(corner_seed(seed, attempt))
        e.open_with_wide_attack()
        if e.play_until_corner():
            for _ in range(int(minutes * 60 * FPS)):
                e.step()
            return e.match
    raise RuntimeError(f"no corner in {CORNER_ATTEMPTS} wide attacks from seed {seed}")
