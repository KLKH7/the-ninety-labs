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

import copy
import math
from dataclasses import asdict, dataclass, field

from ninety.sim import ball, decisions, fmath, offball, perception, profiles, roles, setpieces, shape
from ninety.sim import team as team_mod
from ninety.sim.body import (
    AERIAL_ABSORB,
    BODY_HEIGHT,
    BODY_RADIUS,
    BODY_RESTITUTION,
    BODY_TOUCH_Z,
    BRAKE_MAX,
    CHEST_TOP_Z,
    CONTROL_M,
    CS_MEAN,
    D0,
    F0_MEAN,
    FOOT_REACH_Z,
    STRIKE_FACING,
    THIGH_TOP_Z,
    TURN_RATE,
    V0_MEAN,
    Body,
    can_get_to,
    relative_speed,
    sprint_cost_m,
)
from ninety.sim.body import move as move_body
from ninety.sim.decisions import PENALTY_DEPTH
from ninety.sim.offball import KEEPER_DIVE_TRAVEL_M
from ninety.sim.profiles import Profile
from ninety.sim.style import HIGH, LOW, MID, Style, preset_name
from ninety.sim.team import ROLE_LINE, TeamBrain

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
LOOK_S = PERCEIVE_EVERY / FPS  # O10: off the ball he weighs his moves again once a look
BRAIN_EVERY = 12  # frames between a team brain's reads of the game (about 2 a second)
BLOCK_DIAL = {"low": LOW, "mid": MID, "high": HIGH}  # a drawn block as a style dial (T4)
COVER_BEHIND_M = 8.0  # design: the covering player stands this far goal-side of the ball, behind the presser
PERCEPTION_ERR = 0.03  # verify: m/s of misjudged ball velocity per metre between player and ball
PERSONAL_SPACE_M = 1.2  # players steer to keep about this far from each other
ANTICIPATE_S = 0.4  # verify: how far ahead players judge where others will be
TOUCH_POSE_S = 0.30  # design (P14): how long the body shows the part that met the ball
MISCONTROL_KEEP = 0.4  # verify: share of speed a ball keeps off a failed touch or a parry
POST_RADIUS = 0.06  # Law 1: posts and crossbar at most 12 cm wide
WOODWORK_RESTITUTION = 0.6  # verify
BALL_TO_FEET = 12.0  # P6 (design): how fast a carried ball settles to his feet, m/s
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
COVER_TO_COMMIT_M = 10.0  # design: a team-mate goal-side within this distance is cover to commit with
LAST_DITCH_M = 18.0  # this near his own goal a defender commits without cover
COMMIT_P = 0.6  # a defender commits only when he expects to win the race this often (aggression shifts it)
# What a defender expects a penalty to cost: the chance it is scored. Premier League seasons run from
# 74.8% (2022-23) to 89.6% (2023-24) (Opta via The Analyst); 0.8 is design within that range.
PENALTY_GOAL_P = 0.8
SHOT_AIM_OFF_M = (0.5, 3.2)  # design: how far from the centre of the goal a shot is aimed
# A2 at a penalty: the keeper must commit before the strike, against a kicker with time to disguise
# it. On kicks to a side, keepers went the right way 113 times in 204 (Bar-Eli et al. 2007, Table 1,
# 286 top-flight penalties): barely better than a guess. His read's spread is whatever gives that
# rate over the shots the engine aims (derived below, not chosen).
PENALTY_CORRECT_SIDE = 113 / 204


def read_spread_for(correct: float, off: tuple[float, float] = SHOT_AIM_OFF_M) -> float:
    """The spread (m) of a read centred on the aim that picks the aim's side with chance `correct`,
    over aims uniform `off` metres either side of centre."""
    def share(sd: float, n: int = 400) -> float:
        return sum(fmath.normal_cdf((off[0] + (off[1] - off[0]) * (i + 0.5) / n) / sd)
                   for i in range(n)) / n
    lo, hi = 0.01, 1000.0
    for _ in range(60):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if share(mid) > correct else (lo, mid)
    return lo


PENALTY_READ_ERROR_M = read_spread_for(PENALTY_CORRECT_SIDE)
SHIELD_M = 3.0  # holding with an opponent this close, the carrier puts his body between them
EVADE_MPS = 3.0  # how fast a carrier pushes the ball away from a lunge, plus up to 2 m/s with dribbling
JOCKEY_LOOKAHEAD_S = 0.5  # a jockeying defender matches where the carrier is going, not where he is
POKE_MPS = 5.0  # how fast a tackled ball comes away
THROW_WAIT_S = 2.0  # design: nobody free, so he throws; a longer look is dead time in a clip
CHASE_EVERY = 4  # frames between re-planning who chases a free ball
# A4, P18 (design, verify): a ball he lets come down to his foot he waits for midway between his
# body's widest edge and his foot's reach beyond where it drops to a foot's height (about 0.68 m), so
# it drops in front of him, onto his foot, not onto his body
FOOT_SPOT_M = (BODY_RADIUS + ball.RADIUS + CONTROL_M) / 2
GOAL_HALF_WIDTH, CROSSBAR = 3.66, 2.44  # Law 1
GOAL_AREA_X = 5.5  # Law 1
# Laws 15 to 17: opponents keep this far from a restart until the ball is in play.
RESTART_DISTANCE_M = {"throw_in": 2.0, "corner": 9.15, "goal_kick": PENALTY_DEPTH - GOAL_AREA_X + 1.0,
                      "free_kick": 9.15, "kick_off": 9.15,
                      "penalty_kick": 9.15}  # Laws 8, 13 and 14: 9.15 m (the centre circle, the arc)
PENALTY_MARK_M = 11.0  # Law 1: the penalty mark, 11 m from the goal line
BOARDS_M = 4.0  # verify: advertising boards behind the lines stop a ball (and players) that go out
# R1: seconds from the ball going out to the restart. Means from Opta timing of the Premier League
# (The Analyst): throw-ins about 16 s (2022-23; 17.9 in 2025-26), goal kicks 29 to 30 s, free kicks
# 31.3 to 40.9 s by team (2022-23; mean taken as the middle), corners about half a minute (only a
# combined figure is published). The spread around each mean is design. Kickoff: design, long
# enough to see (a goal's celebration, about 72 s in the same data, is not modelled).
RESTART_DELAY_S = {"throw_in": (12, 20), "goal_kick": (24, 34), "corner": (24, 36),
                   "free_kick": (29, 41),
                   # about two minutes from the foul to the spot kick (same source, 2022-23)
                   "penalty_kick": (100, 140),
                   "kick_off": (1, 2)}
# A corner is not taken on a timer here: it is taken when both teams are set (setpieces.advance), so
# its range above is unused; the corner report compares the time that emerges with it.
# S9 (design): the corner scenario opens at a moment open play reaches: from the kick-off, play
# runs until the home side brings the ball into its final third (or wins it there) in open play.
# Attempts branch from that moment (MOMENT_ATTEMPTS of them, each with its own random streams);
# the first one that play turns into a home corner within CORNER_WITHIN_S is kept; an attempt is
# given up once the away side has the ball ATTACK_OVER_M or more from that goal line. If none
# does, play runs on to the next such moment; a base match is played for at most BASE_MATCH_S,
# then a new one begins; up to CORNER_ATTEMPTS attempts in all.
FINAL_THIRD_X = PITCH_X * 2 / 3
MOMENT_ATTEMPTS = 20
BASE_MATCH_S = 90 * 60.0  # a base match is played no longer than a match
CORNER_WITHIN_S = 20.0
ATTACK_OVER_M = 40.0
CORNER_ATTEMPTS = 400  # a bound on attempts per seed
BASE_SEEDS_FROM = 500  # base match k of a seed: corner_seed(seed, BASE_SEEDS_FROM + k), apart from attempts
assert CORNER_ATTEMPTS < BASE_SEEDS_FROM < 1000  # a seed's scenario seeds stay in its block of 1000
CORNER_SEED_BASE = 1_000_000_000  # scenario engine seeds: base + seed * 1000 + attempt, apart from
# the seeds of full matches
NO_OFFSIDE_FROM = ("throw_in", "goal_kick", "corner")  # Law 11: no offside offence direct from these
INTERCEPT_SHARE = 0.85  # design: taken before this share of the way to its target, a pass is intercepted
THROW_BEHIND_M = 0.55  # Law 15: his body stands outside the touchline, feet on or behind it (design)
THROW_SPOT_M = 0.25  # design: within this of his spot he throws from where he stands, still behind the line
THROW_SETTLED_MPS = BRAKE_MAX * DT  # he throws once one frame of braking would stop him (P2)
THROW_REACH_M = 0.28  # design: both hands reach toward the pitch and still stay short of the line
THROW_HAND_Z = 1.85  # design: bottom of the ball just over an average head (no stature per player)

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
    # a scenario clip (S9): the match it branched from, and that match's clock at the opening
    base_seed: int | None = None
    opening_t: float | None = None
    events: list[dict] = field(default_factory=list)
    frames: list[dict] = field(default_factory=list)
    score: dict = field(default_factory=lambda: {"home": 0, "away": 0})
    roster: list[dict] = field(default_factory=list)
    teams: dict = field(default_factory=dict)  # each team's strength and style: the scenario's settings


def attack_dir(team: str) -> float:
    return 1.0 if team == "home" else -1.0


def evade_angle(team: str, bx: float, by: float, dx: float, dy: float) -> float:
    """D8: the way a carrier pushes the ball from a lunge by a defender at (dx, dy): across the
    challenge, to the side that keeps him going forward. One rule for the evasion and for the
    defender's picture of it."""
    away = fmath.atan2(by - dy, bx - dx)
    fwd = fmath.atan2(0.0, attack_dir(team))
    sides = (away + math.pi / 2, away - math.pi / 2)
    return min(sides, key=lambda a: abs((a - fwd + math.pi) % (2 * math.pi) - math.pi))


def goal_x(team: str) -> float:
    """x of the goal this team attacks."""
    return PITCH_X if team == "home" else 0.0


def other(team: str) -> str:
    return "away" if team == "home" else "home"


def first_low_within(x0: float, y0: float, z0: float, dx: float, dy: float, dz: float, px: float,
                     py: float, r: float, top: float) -> float | None:
    """The first share of the way along the step (x0, y0, z0) + s (dx, dy, dz), 0 to 1, at which
    the ball is within r of (px, py) across the ground and no higher than `top`; None if never."""
    fx, fy = x0 - px, y0 - py
    a, b, c = dx * dx + dy * dy, fx * dx + fy * dy, fx * fx + fy * fy - r * r
    if a < 1e-12:
        lo, hi = (0.0, 1.0) if c <= 0 else (1.0, 0.0)
    else:
        disc = b * b - a * c
        if disc < 0:
            return None
        root = math.sqrt(disc)
        lo, hi = max(0.0, (-b - root) / a), min(1.0, (-b + root) / a)
    if lo > hi:
        return None
    if z0 + lo * dz <= top:  # low enough as soon as it is in reach
        return lo
    if dz < 0:  # coming down: from when it drops below `top`, if still in reach
        s = (top - z0) / dz
        return s if s <= hi else None
    return None


def turn_toward(heading: float, target: float) -> float:
    """P16: a body turns toward where he wants to face, at most TURN_RATE, never in one jump."""
    step = TURN_RATE * DT
    diff = (target - heading + math.pi) % (2 * math.pi) - math.pi
    return (heading + clamp(diff, -step, step) + math.pi) % (2 * math.pi) - math.pi


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
    def __init__(self, seed: int, strengths: dict[str, float] | None = None,
                 styles: dict[str, Style] | None = None):
        self.rng = fmath.Random(seed)
        # Perception draws from its own stream, so a change to what players see does not
        # reshuffle every other random draw in the match.
        self.sight_rng = fmath.Random(f"{seed}-perception")
        self.move_rng = fmath.Random(f"{seed}-offball")  # O10: off-ball choices
        self.match = Match(seed=seed)
        self.players: list[Player] = []
        # A strength not given is drawn, home first: with none given the match is the same as before.
        given = strengths or {}
        unknown = (set(given) | set(styles or {})) - {"home", "away"}
        if unknown:
            raise ValueError(f"teams are 'home' and 'away', got {sorted(unknown)}")
        self.strength = {team: given[team] if team in given else profiles.team_strength(self.rng)
                         for team in ("home", "away")}
        # T2, T3: a side given no style plays a block of its own (design: equally likely), its
        # line and its line of engagement at the same height, the other dials mid. Drawn from its
        # own stream for both sides, so the rest of the match's random draws do not shift with it.
        draw = fmath.Random(f"{seed}-style")
        drawn = {team: Style(line_height=BLOCK_DIAL[block], pressing_height=BLOCK_DIAL[block])
                 for team, block in (("home", draw.choice(sorted(team_mod.BLOCKS))),
                                     ("away", draw.choice(sorted(team_mod.BLOCKS))))}
        self.styles = {team: (styles or {}).get(team, drawn[team]) for team in ("home", "away")}
        self.match.teams = {
            team: {"strength": self.strength[team], "preset": preset_name(self.styles[team]),
                   "style": asdict(self.styles[team])}
            for team in ("home", "away")
        }
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
        self.brains = {team: TeamBrain(team, self.styles[team]) for team in ("home", "away")}
        self.ball: ball.State = (PITCH_X / 2, PITCH_Y / 2, 0.0, 0.0, 0.0, 0.0)
        self.possessor: str | None = None
        self.last_touch: str | None = None
        self.kicked: dict | None = None  # the pass or shot event in flight, resolved when it ends
        self.kicked_at = -99.0
        self.bumped: tuple[str, float] | None = None  # who it last came off, and his own clock
        self.kicker_clear = True  # the struck ball has left the kicker's body
        self.kicker_far = True  # ... and is beyond his reach, moving away (his body is in play again)
        self.released_by: str | None = None  # Law 12: a keeper who released it may not handle it again
        # (x, y, strike): a carrier turning the ball onto his kicking side before he strikes it
        self.windup: tuple | None = None
        self.lunges: dict[str, float] = {}  # defender -> when his lunge reaches the ball
        self.lunge_at: dict[str, str] = {}  # defender -> the man he lunged at
        self.tastes: dict = {}  # D4: the carrier's misjudgement of each option, kept while he has it
        self.holds = 0  # D9: decisions in a row the carrier has spent holding
        self.taste_scan = -1.0  # the carrier's scan the tastes were drawn after
        self.penalties = 0  # penalty kicks awarded (Law 14)
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
        self.dive: tuple[float | str, ...] | None = None
        self.landed: tuple[str, float] | None = None  # (keeper, his arms' stretch start) while he is down
        self.dived_at: float | None = None  # P15: the touch (kicked_at) the last dive was at: one dive each
        self.shot_touched_by: str | None = None  # "keeper" or "defender": who got to the shot
        self.shot_was_on_target: bool | None = None  # was it going in when they first touched it?
        self.free_since = -99.0
        self.touched_since_kick = False
        self.chase: dict[str, tuple[str, float, float]] = {}  # team -> (player, x, y)
        self._to_foot: dict[tuple, bool] = {}  # (frame, player, ball) -> to_foot, once a frame
        self.restart: Restart | None = None
        self.set_play: setpieces.Corner | None = None  # a corner routine being set up or played
        self.throw_by: str | None = None  # a throw-in taker holding the ball until he throws it
        self.throw_ready = 0.0
        self.into_play = False  # released from behind the line; not a new out until it enters or falls away
        self.throw_from: tuple[float, float] | None = None  # where the last throw-in was taken
        self.touch_show: dict[str, tuple[str, float]] = {}  # player -> (part, until)
        self.dive_show: dict[str, tuple[float, float]] = {}  # keeper -> (until, side)
        self.dribble_to: tuple[float, float] | None = None  # the carrier's chosen carry, if any
        self.intended: str | None = None  # the team-mate a pass was played to: he expects it
        self.moves: dict[str, tuple[str, float, float, float]] = {}  # O10: player -> (move, x, y, chosen at)
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
        return decisions.in_box(x, y, PITCH_X - goal_x(team))

    def hands(self, p: Player, x: float, y: float) -> bool:
        """Law 12 (offball.may_handle) for this keeper and this ball."""
        k = self.kicked
        back_pass = bool(k) and k["type"] == "pass" and k["team"] == p.team and self.last_touch == k["player"]
        return offball.may_handle(p.role == "GK", self.in_own_box(p.team, x, y), self.released_by == p.id,
                                  back_pass)

    def reacting_since(self, p: Player) -> float:
        """When this player's reaction to the ball began. A ball that comes off his own body is
        no new strike to him: he was already reacting to it, so his clock runs on from before;
        everyone else reacts to it afresh (deflect)."""
        if self.bumped and self.bumped[0] == p.id:
            return self.bumped[1]
        return self.kicked_at

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

    def reach(self, p: Player, x: float, y: float, z: float, at: float | None = None,
              heads: bool = True) -> tuple[float, float]:
        """How far (across the ground) this player can reach a ball at (x, y), height z, at time
        `at`, and how high he can reach at all (offball.reach_for): a foot or, with `heads`, his head
        above it (standing, or jumping once he has had the time to rise, P18), or a keeper's hands
        in his box. His arms stretch from the moment he reacts to the last touch, whether or not his
        body launches; a deflection does not un-stretch a dive already under way, nor pull him back
        out of his jump (rise_from)."""
        hands = self.hands(p, x, y)
        at = self.t if at is None else at
        if not hands:  # a foot, or his head once he has reacted (and risen, to jump)
            return offball.reach_for(False, at - self.stretch_from(p), z, heads=heads)
        start = self.stretch_from(p)
        return offball.reach_for(True, at - start, z, at - self.rise_from(p))

    def give(self, pid: str) -> None:
        if self.team_of(pid) != self.poss_team:
            self.pressed.clear()
            self.poss_team = self.team_of(pid)
        self.possessor = pid
        self.last_touch = pid
        self.tastes = {}  # D4: a new man on the ball judges his options afresh
        self.holds = 0
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
        self.moves = {}
        self.touched_since_kick = False
        self.chase = {}
        self.dribble_to = None
        self.dive = None

    def penalty_wait_spot(self, p: Player) -> tuple[float, float]:
        """Law 14: the defending keeper on his goal line between the posts; everyone else on the
        pitch, outside the penalty area, behind the mark and 9.15 m from it: his own target pushed
        out of the area and off the arc."""
        r = self.restart
        gx = goal_x(r.team)  # the goal the kick is at
        out = -attack_dir(r.team)  # from that goal back up the pitch
        if p.role == "GK" and p.team != r.team:
            return gx, PITCH_Y / 2
        x = clamp(p.ax if p.role == "GK" else p.x, 1.0, PITCH_X - 1.0)
        y = clamp(p.y, 1.0, PITCH_Y - 1.0)
        edge = gx + out * (PENALTY_DEPTH + 1.0)  # a metre clear of the area
        if (x - edge) * out < 0:
            x = edge
        clear = RESTART_DISTANCE_M["penalty_kick"] + 0.5
        d = math.hypot(x - r.x, y - r.y)
        if d < clear:  # off the arc, radially from the mark
            ux, uy = ((x - r.x) / d, (y - r.y) / d) if d > 1e-6 else (out, 0.0)
            x, y = r.x + ux * clear, r.y + uy * clear
        return x, y

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
            # Failed: he was offside. Not its receiver (that is a completed pass's) nor an interceptor.
            kicked.update(end_x=round(x, 2), end_y=round(y, 2), outcome="fail")
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
        """P16: can he strike it toward (tx, ty) now? The rule the passer's estimate uses too
        (decisions.can_strike)."""
        if self.throw_by == carrier.id:  # Law 15: in his hands over his head, thrown at once
            return True
        bx, by = self.ball[0], self.ball[1]
        return decisions.can_strike(bx - carrier.x, by - carrier.y, carrier.heading, tx - bx, ty - by)

    def turn_to(self, carrier: Player, tx: float, ty: float, strike) -> None:
        """He turns toward the target, no faster than a body turns (P16, tick_carrier), taking the
        ball round with him; the strike waits until he faces it (can_strike)."""
        self.windup = (tx, ty, strike)

    def kick(self, carrier: Player, vx: float, vy: float, vz: float) -> None:
        # Struck from where the ball is, against his body on the side he faces (can_strike: only
        # once he faces within STRIKE_FACING of the line). Until it has left his body he does not
        # meet it again (kicker_clear in contact).
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
        self.bumped = None
        self.free_since = self.t  # the ball left a player's control: dives are timed from here
        self.landed = None  # a new strike: a keeper still down reacts to it afresh
        self.seen_going = self.ball_destination()
        self.kicker_clear = self.kicker_far = False
        self.chase = {}  # everyone reacts after their reaction time, not on the frame of the kick

    def execute(
        self, p: Player, vx: float, vy: float, vz: float, skill: str, hands: bool = False,
        header: bool = False,
    ) -> tuple[float, float, float]:
        """The kick as struck, not as intended: direction, speed and launch angle scatter by the
        player's own error, which grows with ball speed, pressure, fatigue and the weaker foot
        and shrinks with skill (profiles.Profile.kick_error, docs/GROUNDING.md A3). A throw uses
        both hands, so there is no weaker foot and no kicking side; a `header` (P18) has the
        header's error, whichever way it is struck."""
        ground = math.hypot(vx, vy)
        speed = math.sqrt(ground * ground + vz * vz)
        if speed < 1e-6:
            return vx, vy, vz
        nearest = min(math.hypot(q.x - p.x, q.y - p.y) for q in self.players if q.team != p.team)
        # Which foot: the kick's direction against the way he faces (a state; P13).
        turn = 0.0 if (hands or header) else decisions.turn_deg(fmath.atan2(vy, vx), p.heading)
        dir_sd, speed_sd, loft_sd, foot = p.profile.strike_error(skill, speed, nearest, self.fresh(p), turn,
                                                                 header=header)
        angle = fmath.atan2(vy, vx) + math.radians(self.rng.gauss(0, dir_sd))
        lofted = vz > 0 or header
        loft = fmath.atan2(vz, ground) + (math.radians(self.rng.gauss(0, loft_sd)) if lofted else 0.0)
        speed = decisions.struck_speed(speed, self.rng.gauss(0, speed_sd), foot)
        ground, up = speed * fmath.cos(loft), speed * fmath.sin(loft)  # a low drive may go into the turf
        return ground * fmath.cos(angle), ground * fmath.sin(angle), up

    @staticmethod
    def fresh(p: Player) -> float:
        """The slow store's share left (P10): fatigue over the match, not one sprint."""
        return p.physique.ceiling / D0

    def aim(self, sx: float, sy: float, tx: float, ty: float, ground: float, up: float):
        d = math.hypot(tx - sx, ty - sy) or 1.0
        return (tx - sx) / d * ground, (ty - sy) / d * ground, up

    def keeper_read(self, keeper: Player, kicker: Player, aim_y: float) -> float | None:
        """Where a keeper thinks a shot is going, read from the kicker's body: only if he can
        see the kicker, centred on the intended aim, with his anticipation's error (A2); at a
        penalty, with the measured spread of a keeper who must commit first."""
        if not perception.visible(keeper.heading, keeper.x, keeper.y, kicker.x, kicker.y,
                                  keeper.profile.view_half_angle()):
            return None
        penalty = self.from_restart == "penalty_kick"
        spread = PENALTY_READ_ERROR_M if penalty else keeper.profile.read_error_m()
        return aim_y + self.rng.gauss(0, spread)

    def shoot(self, carrier: Player, header: decisions.Scene | None = None) -> None:
        """A shot: a kick, or a `header` (P18) from where he met the ball in the air."""
        team = carrier.team
        gx = goal_x(team)
        if header is None and not self.can_strike(carrier, gx, PITCH_Y / 2):
            self.turn_to(carrier, gx, PITCH_Y / 2, lambda: self.shoot(carrier))
            return
        bx, by = self.ball[0], self.ball[1]
        # The aim (which corner, how high, how hard) is a choice; missing it is execution error.
        side = self.rng.choice([-1, 1])
        ty = PITCH_Y / 2 + side * self.rng.uniform(*SHOT_AIM_OFF_M)
        tz = self.rng.uniform(*offball.SHOT_AIM_Z_M)
        speed = self.rng.uniform(*offball.SHOT_SPEEDS_KMH) / 3.6
        if header is None:
            ground, up = ball.shot(math.hypot(gx - bx, ty - by), speed, tz, DT)
        else:  # no harder than he can head it; if that cannot reach his aim, as hard as he can, then
            # low, then at the middle of the goal (which the option to head at goal needs reachable)
            launch = (decisions.header_launch(header, gx, ty, tz, speed)
                      or decisions.header_launch(header, gx, ty, tz)
                      or decisions.header_launch(header, gx, ty, 0.1))
            if launch is None:
                ty = PITCH_Y / 2
                launch = decisions.header_launch(header, gx, ty, 1.0)
            ground, up = launch
        # The keeper reads the kicker's body and starts toward where he thinks it is going,
        # before he can react to the ball itself; the read can be wrong (A2).
        keeper = self.keeper(other(team))
        read = self.keeper_read(keeper, carrier, ty)
        self.read = None if read is None else (keeper.id, read)
        vx, vy, vz = self.execute(carrier, *self.aim(bx, by, gx, ty, ground, up), "finishing",
                                  header=header is not None)
        speed = math.sqrt(vx * vx + vy * vy + vz * vz)
        # Outcome and end point are observed: set when the ball is touched, goes out or goes in.
        self.shot_touched_by = self.shot_was_on_target = None
        self.kicked = self.emit("shot", team, bx, by, player=carrier.id, ball_speed_kmh=round(speed * 3.6, 1))
        self.kick(carrier, vx, vy, vz)

    def pass_to(self, carrier: Player, tx: float, ty: float, lofted: bool, throw: bool = False,
                pace: float = decisions.ARRIVE_MPS, receiver: str | None = None,
                header: decisions.Scene | None = None, launch: tuple[float, float] | None = None) -> None:
        """Kick toward a point the carrier chose (where he believes a team-mate will be, or space),
        meant for `receiver` if he chose one; or a `header` there (P18), from where he met the ball,
        with the `launch` the option was estimated with (a header away)."""
        if header is None and not self.can_strike(carrier, tx, ty):
            self.turn_to(carrier, tx, ty,
                         lambda: self.pass_to(carrier, tx, ty, lofted, throw, pace, receiver))
            return
        bx, by = self.ball[0], self.ball[1]
        dist = math.hypot(tx - bx, ty - by)
        # Struck as the decision estimated it (decisions.py); execution error is added on top.
        if header is not None:  # headed away as estimated, or a headed pass (the options' own)
            launch = launch or decisions.headed_pass(header, tx, ty)
            if launch is None:  # an option is only a headed pass where one can get there
                raise ValueError(f"no header from ({bx:.1f}, {by:.1f}) to ({tx:.1f}, {ty:.1f})")
            ground, up = launch
        elif throw or lofted:
            ground, up = decisions.loft_launch(dist)
        else:
            ground, up = decisions.launch_speed(dist, pace), 0.0
        skill = decisions.pass_skill(bx, tx, ty, lofted or throw, goal_x(carrier.team))
        vx, vy, vz = self.execute(carrier, *self.aim(bx, by, tx, ty, ground, up), skill, hands=throw,
                                  header=header is not None)
        # Receiver, interceptor, end point and outcome are filled in when someone takes the ball or
        # it goes out.
        self.pass_target = (tx, ty)
        # Only the intended team-mate is known at the kick (his intention, recorded as such).
        self.kicked = self.emit("pass", carrier.team, bx, by, player=carrier.id, intended=receiver,
                                interceptor=None,
                                ball_speed_kmh=round(math.sqrt(vx * vx + vy * vy + vz * vz) * 3.6, 1))
        self.kick(carrier, vx, vy, vz)
        self.into_play = throw  # released from behind the line: not a new out while it comes in
        self.intended = receiver  # he expects it

    def scene_for(self, carrier: Player) -> decisions.Scene:
        """The carrier's picture of the game, built only from what he believes."""
        team, opp = carrier.team, other(carrier.team)
        build = roles.STYLES[self.brains[team].build_up]  # T4: his team's intent and tempo
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
        style, brain = self.styles[team], self.brains[team]
        scene = decisions.Scene(self.ball[0], self.ball[1], goal_x(team), mates, opps, keeper,
                                prof["decisions"], prof["composure"], prof["dribbling"],
                                tuple(prof.traits), risk,
                                current="dribble" if self.dribble_to else None, moving=moving,
                                absorb={m[0]: self.by_id[m[0]].profile.absorb_mps(False) for m in mates},
                                passer=prof, heading=carrier.heading, fresh=self.fresh(carrier),
                                ball_offset=(self.ball[0] - carrier.x, self.ball[1] - carrier.y),
                                progress_weight=style.counter_weight(brain.attacking_transition(self.t)),
                                loss_weight=style.loss_weight(),
                                progress=build.progress_per_m * (0.5 + prof["teamwork"]),  # A8
                                hold_decay=build.hold_decay, held=self.holds,
                                flair=prof["flair"])
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
        # D4: his misjudgements last until he next looks around (P13 scans), not the whole spell.
        scan = self.beliefs[carrier.id].next_scan
        if scan != self.taste_scan:
            self.tastes, self.taste_scan = {}, scan
        choice = decisions.choose(scene, self.rng, self.tastes)
        self.holds = self.holds + 1 if choice.kind == "hold" else 0
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
                  delay: float = 0.0, heads: bool = True) -> tuple[bool, float | None, float]:
        """Can he get to the ball at (bx, by, bz) `t` seconds from now, starting after `delay`?
        (reachable, gap still to close, his speed along the way); gap None if it is over his reach.
        His reach (a keeper's hands in his box), his speed along the way, and braking first if he
        is running away from it: one test for chasing a ball and for judging where play goes."""
        reach_m, reach_z = self.reach(p, bx, by, bz, at=self.t + t, heads=heads)
        if bz > reach_z:
            return False, None, 0.0
        return can_get_to(p.physique, bx - p.x, by - p.y, reach_m, p.vx, p.vy, t - delay)

    def plan_chase(self) -> None:
        """Each team sends the player who thinks they can reach the ball's path first. Each player
        judges the ball's velocity with an error that grows with their distance from it, and the
        judgement is renewed (and sharpens) every few frames as the ball comes closer."""
        if all(self.t - self.reacting_since(p) < self.reaction(p) for p in self.players):
            return
        path = ball.predict(self.ball, DT, 6.0)
        best: dict[str, tuple[float, str, float, float]] = {}
        misjudged: dict[str, tuple[float, float]] = {}  # the velocity error each judges it with
        for p in self.players:
            if self.kicked and p.id == self.kicked["player"] and not self.touched_since_kick:
                continue  # the kicker moves on; he does not run after his own pass or shot
            if self.t - self.reacting_since(p) < self.reaction(p):
                continue  # has not yet reacted to this strike
            sigma = PERCEPTION_ERR * math.hypot(self.ball[0] - p.x, self.ball[1] - p.y)
            ex, ey = self.rng.gauss(0, sigma), self.rng.gauss(0, sigma)
            misjudged[p.id] = (ex, ey)
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
        for team, (pid, *_) in list(self.chase.items()):
            spot = self.foot_spot(self.by_id[pid], path, *misjudged[pid])
            if spot:
                self.chase[team] = (pid, *spot)

    def foot_spot(self, p: Player, path: list, ex: float, ey: float) -> tuple[float, float] | None:
        """A4, P18: where he waits for a ball he lets come down to his foot (to_foot): beyond the
        first point of its flight below BODY_TOUCH_Z that he can get to, along its line, by
        FOOT_SPOT_M, so it drops in front of him to his foot rather than onto his body; the flight as he
        judges it (`ex`, `ey`: his velocity error, as plan_chase). None if the ball is not one he lets
        come down (or is already at a foot's height)."""
        if self.ball[2] <= BODY_TOUCH_Z or self.hands(p, self.ball[0], self.ball[1]) or not self.to_foot(p):
            return None
        for k in range(1, len(path)):
            t = k * DT
            bx, by, bz = path[k][0] + ex * t, path[k][1] + ey * t, path[k][2]
            if bz <= BODY_TOUCH_Z and self.can_reach(p, bx, by, bz, t, heads=False)[0]:
                gvx, gvy = path[k][3] + ex, path[k][4] + ey
                g = math.hypot(gvx, gvy)
                if g < 1e-6:
                    return bx, by
                return bx + gvx / g * FOOT_SPOT_M, by + gvy / g * FOOT_SPOT_M
        return None

    def tick_free(self) -> None:
        before = self.ball
        self.ball = ball.step(before, DT)
        self.woodwork(before)
        if self.went_out(before):
            return
        if self.frame % CHASE_EVERY == 0:
            self.plan_chase()
        self.contact(before)

    def contact(self, before: ball.State, t0: float = 0.0, depth: int = 0, done: str | None = None) -> None:
        """The ball meets whoever is on its path this frame: a body deflects it at any time; a
        deliberate touch, after reaction time, controls it if it is slow enough to absorb.
        `before` is the ball t0 seconds into the frame (0 at its start); everyone is where they
        are by then. After a deflection the rest of the frame is resolved the same way, so a
        ball off one player can meet the next one in the same frame (up to three in a frame); the
        one it came off (`done`) has had his touch of it this frame."""
        dt = DT - t0
        x0, y0 = before[0], before[1]
        x1, y1, z1 = self.ball[0], self.ball[1], self.ball[2]
        dx, dy = x1 - x0, y1 - y0
        kicker = self.by_id.get(self.last_touch) if self.last_touch else None
        clear_of_body = kicker and shape.clearance(
            x1, y1, kicker.x + kicker.vx * DT, kicker.y + kicker.vy * DT, kicker.heading) > ball.RADIUS
        if not self.kicker_clear and clear_of_body:
            self.kicker_clear = True
        # Nor is his body in the way of his own strike until the ball is beyond where he can strike
        # it from (a foot's reach; a header is met nearer) and moving away from him: a header across
        # his line passes his shoulder, one flicked on passes over his head. (He may play it again,
        # a dribbler's next touch, once it has left his body.)
        if kicker and not self.kicker_far:
            rx, ry = x1 - kicker.x, y1 - kicker.y
            away = rx * (self.ball[3] - kicker.vx) + ry * (self.ball[4] - kicker.vy) > 0
            self.kicker_far = away and math.hypot(rx, ry) > CONTROL_M
        hits = []
        back_on = self.t - self.free_since >= TOUCH_GAP_S
        for p in self.players:
            if (p is kicker and not self.kicker_clear) or p.id == done:
                continue
            if p.id == self.dribbler and not back_on:  # D6: mid-stride after his touch, not on it yet
                continue
            # He moves this step too, at his velocity, so what meets him is the ball's path in his
            # frame: from (x0, y0) to (x0 + rdx, y0 + rdy) against his body where it starts. A point
            # s of the way along it is, on the pitch, that point plus s of his own step (mx, my).
            qx, qy = p.x + p.vx * t0, p.y + p.vy * t0  # where he is when this part of the frame starts
            mx, my = p.vx * dt, p.vy * dt
            rdx, rdy = dx - mx, dy - my
            hz = before[2]
            rseg = rdx * rdx + rdy * rdy
            sc = 0.0 if rseg == 0 else clamp(((qx - x0) * rdx + (qy - y0) * rdy) / rseg, 0.0, 1.0)
            # judged where it comes closest, at the height it is there (P11 envelope)
            ex, ey, ez = x0 + sc * dx, y0 + sc * dy, hz + sc * (z1 - hz)
            reach_m, reach_z = self.reach(p, ex, ey, ez, heads=False)
            reacted = self.t - self.reacting_since(p) >= self.reaction(p)
            if reacted:  # a deliberate touch, first chance
                st = first_low_within(x0, y0, hz, rdx, rdy, z1 - hz, qx, qy, reach_m, reach_z)
                # P18: above his feet, his head: only if the ball is contested (goes_up); otherwise he
                # lets it drop to his feet, and a ball that meets his body is controlled there (A4).
                if not self.hands(p, ex, ey):
                    head_m, head_z = self.reach(p, ex, ey, max(ez, FOOT_REACH_Z + 1e-6))
                    sh = first_low_within(x0, y0, hz, rdx, rdy, z1 - hz, qx, qy, head_m, head_z)
                    if sh is not None and (st is None or sh < st):
                        sz = hz + sh * (z1 - hz)
                        # Only a ball coming at him (not one already past him), if he goes up.
                        hx, hy = x0 + sh * dx, y0 + sh * dy
                        coming = ((self.ball[3] - p.vx) * (qx + sh * mx - hx)
                                  + (self.ball[4] - p.vy) * (qy + sh * my - hy)) > 0
                        if offball.headed(False, sz) and coming and self.goes_up(p):
                            hits.append((sh, "head", p, x0 + sh * dx, y0 + sh * dy, sz,
                                         qx + sh * mx, qy + sh * my, True))
                            st = None  # he heads it: no later touch this step
                # A4, P18: unchallenged, he lets it come down to his foot, unless it is already on
                # his body there (dropping inside his outline): then it meets him where it is.
                if st is not None and hz + st * (z1 - hz) > BODY_TOUCH_Z and not self.hands(p, ex, ey) \
                        and shape.clearance(x0 + st * rdx, y0 + st * rdy, qx, qy, p.heading) > ball.RADIUS \
                        and self.to_foot(p):
                    st = first_low_within(x0, y0, hz, rdx, rdy, z1 - hz, qx, qy, reach_m, BODY_TOUCH_Z)
                if st is not None:
                    tx, ty, tz = x0 + st * dx, y0 + st * dy, hz + st * (z1 - hz)
                    high = tz > BODY_TOUCH_Z and not self.hands(p, tx, ty)  # above a foot: thigh, chest
                    hits.append((st, "touch", p, tx, ty, tz, qx + st * mx, qy + st * my, high))
            # The body (shape.py, P11) is as wide as his shoulders and as deep as his chest, turned
            # the way he faces: the ball meets it where its path first touches that outline.
            sb = shape.first_contact(x0, y0, x0 + rdx, y0 + rdy, qx, qy, p.heading, ball.RADIUS)
            if sb is None:
                continue
            ux, uy, bz = x0 + sb * rdx, y0 + sb * rdy, hz + sb * (z1 - hz)  # in his frame
            # It meets the ball only if the ball is moving into the body there (relative to him):
            # toward the nearest point of his spine, which is along the surface normal.
            sx, sy = shape.nearest_on_spine(ux, uy, qx, qy, p.heading)
            closing = (self.ball[3] - p.vx) * (sx - ux) + (self.ball[4] - p.vy) * (sy - uy)
            # His own strike does not meet his body until it is beyond his reach and moving away.
            if bz <= BODY_HEIGHT and closing > 0 and (p is not kicker or self.kicker_far):
                # Above a foot, a player who has reacted gets a thigh, chest or head to it (A4); a
                # ball he has not reacted to just rebounds off him.
                # Only a ball on course into his body (its path crosses the outline), not a clip of it.
                sl = 0.0 if rseg == 0 else ((qx - x0) * rdx + (qy - y0) * rdy) / rseg
                into = shape.clearance(x0 + sl * rdx, y0 + sl * rdy, qx, qy, p.heading) <= 0
                aerial = (reacted and into and bz > BODY_TOUCH_Z
                          and not self.hands(p, ux + sb * mx, uy + sb * my))
                hits.append((sb, "touch" if aerial else "body", p, ux + sb * mx, uy + sb * my, bz,
                             qx + sb * mx, qy + sb * my, aerial))
        if not hits:
            return
        # A ball that meets a player's body below his head is taken on it (A4: a thigh or chest, or
        # it rebounds off him); his head plays one at head height, or going over or past him (P18).
        bodied = {h[2].id for h in hits
                  if (h[1] == "body" or (h[1] == "touch" and h[8])) and h[5] < CHEST_TOP_Z}
        hits = [h for h in hits if not (h[1] == "head" and h[2].id in bodied)]
        s, kind, p, cx, cy, cz, px, py, aerial = min(hits, key=lambda h: h[0])  # whoever it meets first
        if kind == "head":
            self._show_touch(p, cx, cy, cz, True)
            if not self.touched(p, cx, cy, True):  # a header is deliberate play (Law 11, the pass's end)
                self.header(p, cx, cy, cz)
            return
        if kind == "touch":
            self._show_touch(p, cx, cy, cz, aerial)
        vx, vy, vz = self.ball[3], self.ball[4], self.ball[5]
        rel = relative_speed(vx, vy, vz, p.vx, p.vy)
        absorb = p.profile.absorb_mps(self.hands(p, cx, cy))
        if aerial:  # a thigh, chest or head kills less pace than a foot
            absorb *= AERIAL_ABSORB
        controls = kind == "touch" and rel <= absorb
        if self.touched(p, cx, cy, controls):  # judged on the ball as it arrived
            return
        if controls:
            # Taken against his body (a chest or thigh), it is on its surface, never inside him.
            sx, sy = shape.nearest_on_spine(cx, cy, px, py, p.heading)
            gap = math.hypot(cx - sx, cy - sy)
            if 1e-6 < gap < shape.RADIUS_M + ball.RADIUS:
                k = (shape.RADIUS_M + ball.RADIUS) / gap
                cx, cy = sx + (cx - sx) * k, sy + (cy - sy) * k
            rest = (1.0 - s) * dt  # and it moves on with him for the rest of the step
            self.ball = (cx + p.vx * rest, cy + p.vy * rest, cz, p.vx, p.vy, 0.0)
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
        left = (1.0 - s) * dt
        keep = MISCONTROL_KEEP if kind == "touch" else BODY_RESTITUTION
        start = self.deflect(p, cx, cy, cz, keep, (px, py, left))
        if left <= 1e-9:
            return
        # The rest of the frame, from where it left him: the posts and the lines first, as for
        # any flight (tick_free), then whoever it meets next.
        flown = self.ball
        self.woodwork(start)
        if self.went_out(start) or self.ball != flown or depth >= 2:
            return
        self.contact(start, DT - left, depth + 1, p.id)

    def goes_up(self, p: Player) -> bool:
        """P18: does he head the ball (it is within his head's reach now) or let it drop to his feet?
        He goes up for it unless, in the ball's own flight from here, he can get to it at his feet
        before any opponent could get to it at all: an unchallenged ball is brought down, a
        contested one is headed. By the same reach and chase test as everything else
        (can_reach); the passer's race decides the same way (decisions.pass_confidence)."""
        return self.first_to_drop(p) != "feet"

    def to_foot(self, p: Player) -> bool:
        """P18, A4: a ball he has let drop (or that comes to him below his head) he lets come on down
        to his foot, below BODY_TOUCH_Z, if in its own flight he can get to it there before any
        opponent could get to it at all, rather than meeting it on his thigh or chest: the same test
        as goes_up, at a foot's height (decisions.pass_confidence decides the same way). Decided
        once a frame for the ball as it is (a deflection in the frame is a new ball)."""
        key = (self.frame, p.id, self.ball)
        if key not in self._to_foot:
            if len(self._to_foot) > 64:
                self._to_foot.clear()
            self._to_foot[key] = self.first_to_drop(p, BODY_TOUCH_Z) == "feet"
        return self._to_foot[key]

    def first_to_drop(self, p: Player, top: float = FOOT_REACH_Z) -> str | None:
        """P18: in the ball's own flight from here, who gets to it first: an opponent ("rival"), or he
        at his feet, below `top` ("feet"); None if neither within DROP_HORIZON_S, or before it is out of
        play (Law 9, as the passer's race ends it: decisions.out_of_play)."""
        path = ball.predict(self.ball, DT, decisions.DROP_HORIZON_S)
        rivals = [q for q in self.players if q.team != p.team]
        for k, (bx, by, bz, *_) in enumerate(path[1:], start=1):
            if decisions.out_of_play(bx, by):
                return None
            t = k * DT
            for q in rivals:
                wait = max(0.0, self.kicked_at + self.reaction(q) - self.t)
                if t >= wait and self.can_reach(q, bx, by, bz, t, delay=wait)[0]:
                    return "rival"  # an opponent could be there first
            if bz <= top and self.can_reach(p, bx, by, bz, t, heads=False)[0]:
                return "feet"  # at his feet first
        return None

    def header(self, p: Player, cx: float, cy: float, cz: float) -> None:
        """P18: he meets the ball in the air with his head, where its path reached him. Where it goes
        is his choice from what he believes, as any other (decisions.options with the scene's
        header: at goal, to a team-mate, or headed away), struck as a header from there
        (decisions.header_launch) with his own header error."""
        incoming = (self.ball[3], self.ball[4], self.ball[5])
        self.ball = (cx, cy, cz, *incoming)
        scene = self.scene_for(p)
        scene.header, scene.z, scene.incoming = True, cz, incoming
        choice = decisions.choose(scene, self.rng)
        if choice.kind == "shoot":
            self.shoot(p, header=scene)
        else:
            self.pass_to(p, *choice.target, lofted=True, receiver=choice.receiver, header=scene,
                         launch=choice.launch)

    def deflect(self, p: Player, cx: float, cy: float, cz: float, keep: float,
                at: tuple[float, float, float] | None = None) -> ball.State:
        """The ball bounces off a player (a block, a parry, a heavy touch) and stays free. In the
        player's frame, the part of the ball's velocity into the body reverses and keeps `keep`
        of its speed; the part along the body is unchanged. The body's surface is normal to the
        line from the nearest point of its spine (shape.py). `at` is where he was when it met him
        and how much of the frame is left (x, y, seconds); it leaves his surface there and flies
        on, under gravity, for the rest of the frame. Returns the ball as it left him."""
        px, py, left = at if at else (p.x, p.y, 0.0)
        rx, ry, vz = self.ball[3] - p.vx, self.ball[4] - p.vy, self.ball[5]
        sx, sy = shape.nearest_on_spine(cx, cy, px, py, p.heading)
        nx, ny = cx - sx, cy - sy
        n = math.hypot(nx, ny)
        if n > 1e-6:
            nx, ny = nx / n, ny / n
        else:  # dead centre: it comes straight back
            speed = math.hypot(rx, ry) or 1.0
            nx, ny = -rx / speed, -ry / speed
        into = rx * nx + ry * ny
        if into < 0:
            rx, ry = rx - (1 + keep) * into * nx, ry - (1 + keep) * into * ny
        # It leaves from where it met him, on his surface, never from inside him.
        out = max(math.hypot(cx - sx, cy - sy), shape.RADIUS_M + ball.RADIUS) + 0.001
        # Then it flies on, at its new velocity and under gravity, for the rest of the frame.
        start = (sx + nx * out, sy + ny * out, cz, rx + p.vx, ry + p.vy, vz)
        self.ball = ball.step(start, left) if left > 1e-9 else start
        self.last_deflection = self.emit("deflection", p.team, cx, cy, player=p.id)  # a touch is truth too
        self.last_touch = p.id
        if p.id != self.dribbler:  # it came off someone else: no longer his touch to run onto
            self.dribbler = None
        self.kicker_clear = self.kicker_far = False
        if not (self.bumped and self.bumped[0] == p.id):
            self.bumped = (p.id, self.reacting_since(p))
        self.kicked_at = self.t  # a new strike of the ball: everyone else reacts to it again
        self.chase = {}
        return start

    def touched(self, p: Player, x: float, y: float, controls: bool) -> bool:
        """Resolve the pass or shot in flight from who touched it, and how: observed, never
        intended. Called with the ball as it arrived, before the touch changes it. Returns True
        if the touch stopped play (an offside offence)."""
        if p.id in self.offside:  # L10: he was offside when it was played, and now plays it
            self.offside_offence(p, x, y)
            return True
        kicked = self.kicked
        # Law 11: a deliberate save (stopping a ball going into goal) is not a new phase.
        saving = bool(kicked) and kicked["type"] == "shot" and kicked["team"] != p.team and \
            self.heading_on_target(kicked["team"])
        opponent = p.team != (self.team_of(self.last_touch) if self.last_touch else p.team)
        if opponent and controls and not saving:
            self.offside = set()  # an opponent's deliberate play: a new phase
        self.touched_since_kick = True
        if p.id != self.dribbler and self.dribbler and p.team == self.team_of(self.dribbler):
            self.dribbler = None  # a team-mate took it: the dribble is over
        if p.id != self.released_by:
            self.released_by = None
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
                kicked.update(interceptor=p.id, end_x=round(x, 2), end_y=round(y, 2), outcome="fail")
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
            self.bumped = None
            self.chase = {}
            return

    def clear_of_frame(self, old: tuple[float, float, float],
                       new: tuple[float, float, float]) -> tuple[float, float, float]:
        """P17: a ball in a player's hands or at his feet does not pass through the goal frame
        either. Its move this frame stands if no point of it comes within touching distance of the
        frame (ball radius plus post radius) while getting closer to it; otherwise it first comes
        across at the height it is (a keeper pulls a ball caught over the bar back over it, or
        round the post), and only then drops; if neither move is clear it stays where it was."""
        r, touching = ball.RADIUS, ball.RADIUS + POST_RADIUS
        lines = [line for line in (0.0, PITCH_X)
                 if min(abs(old[0] - line), abs(new[0] - line)) <= touching + abs(new[0] - old[0])]
        if not lines:
            return new

        def gap(q: tuple[float, float, float]) -> float:
            return min(frame_gap((q[0], q[1], q[2] + r), line)[0] for line in lines)

        start = gap(old)

        def clear(q: tuple[float, float, float]) -> bool:
            def gap_at(t: float) -> tuple[float]:
                g = gap(tuple(a + t * (b - a) for a, b in zip(old, q, strict=True)))
                return (g if g < start else touching,)  # only coming nearer counts
            return first_contact(gap_at, touching - 1e-9) is None

        for q in (new, (new[0], new[1], old[2])):
            if clear(q):
                return q
        return old

    def went_out(self, before: ball.State) -> bool:
        """Law 9: out once the whole ball has crossed a goal line or touchline. Where and how high
        it crossed is taken at the line, not wherever the ball is a frame later."""
        if self.into_play:
            # A throw is released off the pitch. It is not a new out while it is still coming in.
            bx, by, _, _, vy, _ = self.ball
            r = ball.RADIUS
            inside = -r <= bx <= PITCH_X + r and -r <= by <= PITCH_Y + r
            inward = (by >= 0 or vy > 0) and (by <= PITCH_Y or vy < 0)
            if not inside and not inward and self.throw_from:
                # Law 15: it never entered the field, so the same side throws it again from there.
                self.into_play = False
                if self.kicked:
                    self.kicked.update(outcome="fail")
                    self.kicked = None
                self.chase = {}
                self.stop("throw_in", self.team_of(self.last_touch), self.throw_from, self.last_touch)
                return True
            if inside or not inward:
                self.into_play = False
            if self.into_play or inside:
                return False
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
        if r.kind == "corner":  # placed, then struck on the taker's run-up (setpieces.py)
            if setpieces.advance(self):
                self.restart = None
                self.from_restart = "corner"
                setpieces.deliver(self, taker)
            return
        spot = throw_stand(r.x, r.y) if r.kind == "throw_in" else (r.x, r.y)
        # A thrower must be at his spot, behind the line; anyone else is close enough when the ball
        # is at his feet. Nobody is moved there: he runs (lesson 5).
        near = THROW_SPOT_M if r.kind == "throw_in" else CONTROL_M
        if self.t < r.ready_at or math.hypot(taker.x - spot[0], taker.y - spot[1]) > near:
            return
        if r.kind == "throw_in" and math.hypot(taker.vx, taker.vy) > THROW_SETTLED_MPS:
            return
        # While the ball is out of play a new one is placed: the only time the ball may jump.
        if r.kind == "throw_in":  # Law 15: from behind the line, in both hands over his head
            # He takes the ball and stops within his own braking (lesson 5); he has moved this frame.
            # He turns to face the pitch as any body turns (P16, tick_carrier).
            steer(taker, taker.x, taker.y, 0.0)
            self.moved = taker.id
            self.ball = (*throw_hands(taker.x, taker.y), 0.0, 0.0, 0.0)
            self.throw_from = (r.x, r.y)
        else:  # a penalty is placed on the mark (Law 14)
            spot = (r.x, r.y) if r.kind == "penalty_kick" else (taker.x, taker.y)
            self.ball = (*spot, 0.0, 0.0, 0.0, 0.0)
        self.restart = None
        if r.kind != "kick_off":  # a kickoff was recorded when the teams set up
            self.emit("set_piece", r.team, *spot, player=taker.id, outcome=None)
        if r.team != self.poss_team:
            self.emit("possession_change", r.team, taker.x, taker.y, player=taker.id)
        self.give(taker.id)
        # With the ball in his hands he sets and throws (design: a longer hold reads as a freeze).
        pause = (0.2, 0.45) if r.kind == "throw_in" else (0.5, 1.5)
        self.hold_until = self.t + self.rng.uniform(*pause)
        self.throw_by = taker.id if r.kind == "throw_in" else None
        self.throw_ready = self.t
        self.from_restart = r.kind
        if r.kind == "penalty_kick":  # Law 14: kicked forward, at goal (a shot like any other)
            self.hold_until = self.t
            self.shoot(taker)

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
            if (bx - sx) * (tx - sx) + (by - sy) * (ty - sy) < (tx - sx) * (tx - sx) + (ty - sy) * (ty - sy):
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
        if self.restart and self.restart.kind == "penalty_kick" and p.id != self.restart.taker:
            return *self.penalty_wait_spot(p), SHAPE  # Law 14: until the ball is kicked
        if self.restart and self.restart.kind == "kick_off" and p.id != self.restart.taker:
            return *self.kickoff_spot(p, self.restart.team), SHAPE  # Law 8: until the ball is kicked
        if self.restart and p.id == self.restart.taker:
            r = self.restart
            if r.kind == "throw_in":
                return *throw_stand(r.x, r.y), RECOVER
            if r.kind == "penalty_kick":  # behind the ball on the mark, against his body as he faces goal
                behind = shape.surface(0.0, 0.0, pad=ball.RADIUS)
                return r.x - attack_dir(p.team) * behind, r.y, RECOVER
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
                mates = [
                    w
                    for w in (
                        view.where(q.id, self.t) for q in self.players if q.team == p.team and q.id != p.id
                    )
                    if w
                ]
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
            move = self.movement(p, carrier, brain)  # O10: hold, support, come short or run
            if move:
                return move
        if brain.in_possession and p.role != "GK":  # O6: the team's shape with the ball (also in flight)
            spot = self.hold_spot(p, brain, bx, by)
            if spot:
                return *spot, self.in_time(p, *spot)
        if not brain.in_possession and p.role != "GK":
            own = PITCH_X - goal_x(p.team), PITCH_Y / 2
            d = math.hypot(own[0] - bx, own[1] - by) or 1.0
            gx, gy = (own[0] - bx) / d, (own[1] - by) / d  # from the ball toward our goal

            def on_pitch(x: float, y: float) -> tuple[float, float]:
                return clamp(x, 0.5, PITCH_X - 0.5), clamp(y, 0.5, PITCH_Y - 0.5)

            gap = brain.press_gap_m  # how tight the style presses (pressing intensity)
            if self.restart and self.restart.team != p.team:  # Laws 15 to 17: stand off the restart
                gap = RESTART_DISTANCE_M[self.restart.kind]
            presser = self.by_id[brain.pressers[0]] if brain.pressers else None
            engaged = (
                presser is not None
                and math.hypot(bx - presser.x, by - presser.y) < brain.engage_m(self.t)
                and brain.presses(self.t, bx)
            )
            if presser is p and engaged:
                # Press goal-side, a step away, matching where the carrier is going (D8: a defender
                # keeps his speed relative to the attacker small rather than holding a spot).
                carrier = self.by_id.get(self.possessor) if self.possessor else None
                lead_x = carrier.vx * JOCKEY_LOOKAHEAD_S if carrier else 0.0
                lead_y = carrier.vy * JOCKEY_LOOKAHEAD_S if carrier else 0.0
                # Goal-side of where the carrier is going, on the line from there to the goal: the
                # lane a shot from there would take (not the lane from where the ball is now).
                fx, fy = bx + lead_x, by + lead_y
                fd = math.hypot(own[0] - fx, own[1] - fy) or 1.0
                ux, uy = (own[0] - fx) / fd, (own[1] - fy) / fd
                return *on_pitch(*self.press_path(p, fx, fy, ux, uy, gap)), work
            if not engaged and not self.restart and self.presses_high(p, brain, bx, by):
                # O9: a pressing role goes to the carrier beyond the block's engagement line,
                # goal-side and a step away, as the first presser does; the rest hold the block.
                return *on_pitch(bx + gx * gap, by + gy * gap), work
            if engaged and brain.pressers[1:2] == [p.id]:  # cover: behind the presser, goal-side
                behind = max(COVER_BEHIND_M, gap + 2)
                cx, cy = on_pitch(bx + gx * behind, by + gy * behind)
                # A shot can come from wherever the ball is now (as the keeper sets himself): within
                # shooting range the cover gets into the lane at his work rate, not in time for a pass.
                shooting = math.hypot(own[0] - bx, own[1] - by) < offball.SHOT_RANGE_M
                return cx, cy, work if shooting else self.in_time(p, cx, cy)
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

    def hold_spot(self, p: Player, brain: TeamBrain, bx: float, by: float) -> tuple[float, float] | None:
        """O6: his spot in the team's shape with the ball, for his role and his team's build-up style,
        never beyond the onside line as he sees it (L10)."""
        seen = [w for w in (self.beliefs[p.id].where(q.id, self.t) for q in self.players
                            if q.team != p.team) if w]
        onside = self.onside_limit(p.team, seen, bx)
        role, style = roles.role_of(p.profile.archetype), roles.STYLES[brain.build_up]
        return offball.attacking_slot(p.role, PITCH_X - goal_x(p.team), clamp(bx, 0, PITCH_X),
                                      clamp(by, 0, PITCH_Y), onside, role.forward_m + style.forward_m,
                                      role.inside_m - style.width_m)

    def movement(self, p: Player, carrier: Player, brain: TeamBrain) -> tuple[float, float, float] | None:
        """O10: what he does while a team-mate has the ball. At each look he weighs the moves open
        to him (offball.MOVES) by what each is worth to his team: the chance the carrier could find
        him there, times the chance he would be first to the ball there, times what the ball is
        worth there (an off-ball scoring opportunity, Spearman 2018), each times his role's, his
        habits' and his team's prior on that move; then picks one as he picks on the ball (D4). A
        forward run is a sprint to the spot he chose, kept while he carries on with it; the other
        moves follow the ball. None: he holds his spot in the shape (O6)."""
        made = self.moves.get(p.id)
        if made and self.t - made[3] < LOOK_S:  # between looks he carries on
            kind, spot = made[0], made[1:3]
        else:
            spots = {k: s for k in offball.MOVES if (s := self.move_spot(p, carrier, brain, k))}
            if made and made[0] in offball.FORWARD_RUNS and made[0] in spots:
                spots[made[0]] = made[1:3]  # carrying on with his run: the spot he is running to
            if not spots:
                self.moves.pop(p.id, None)
                return None
            worth = {k: self.move_prior(p, brain, k) * self.move_worth(p, carrier, s)
                     for k, s in spots.items()}
            heat = decisions.choice_temperature(p.profile["decisions"], 0.0, p.profile["composure"])
            kind = offball.pick_move(worth, heat, made[0] if made else None, self.move_rng, decisions.STICKY)
            spot = spots[kind]
            self.moves[p.id] = (kind, *spot, self.t)
        if kind in offball.FORWARD_RUNS:
            return *spot, SPRINT
        if kind == "hold":
            return None
        spot = self.move_spot(p, carrier, brain, kind)  # support and coming short follow the ball
        return (*spot, self.in_time(p, *spot)) if spot else None

    def move_prior(self, p: Player, brain: TeamBrain, kind: str) -> float:
        """O10: how much his role, his habits and his team's build-up style lean toward a move."""
        if kind in ("hold", "support"):
            return 1.0
        prior = roles.role_of(p.profile.archetype).prior(kind)
        # T4: with a high counter-attacking dial the central midfielders also run in behind while
        # the counter is on (an ordinary run for them, prior 1).
        if kind == "in_behind" and ROLE_LINE.get(p.role) == "midfield" \
                and brain.style.level("counter_attacking") == "high" and brain.attacking_transition(self.t):
            prior = max(prior, 1.0)
        for trait in p.profile.traits:  # a habit strengthens a move of his role; it never adds one
            prior *= roles.TRAIT_MOVES.get(trait, {}).get(kind, 1.0)
        # A8: his team's instruction weighs as much as his teamwork makes it (as at average, squared at
        # the most, not at all at the least).
        lean = roles.STYLE_MOVES[brain.build_up].get(kind, 1.0)  # its strength grows with teamwork (A8)
        return prior * fmath.exp(fmath.log(lean) * 2 * p.profile["teamwork"])

    def move_worth(self, p: Player, carrier: Player, spot: tuple[float, float]) -> float:
        """O10: what being at `spot` is worth to his team, as he sees the pitch: the chance the
        carrier finds him there (the passer's lane race, D1), times the chance he gets there and to
        the ball first (offball.receive_chance), times what the ball is worth there (D7, D9)."""
        view = self.beliefs[p.id]
        opps = [w for w in (view.where(q.id, self.t) for q in self.players if q.team != p.team) if w]
        sx, sy = spot
        gap = math.hypot(sx - p.x, sy - p.y)
        along = (p.vx * (sx - p.x) + p.vy * (sy - p.y)) / (gap or 1.0)
        mine = p.physique.time_to_cover(gap, along)
        ball_s = max(0.0, self.hold_until - self.t) + math.hypot(sx - carrier.x, sy - carrier.y) / \
            decisions.PASS_SPEED_EST_MPS
        theirs = min((decisions.generic_time(max(0.0, math.hypot(ox - sx, oy - sy) - CONTROL_M))
                      for ox, oy in opps), default=math.inf)
        first = offball.receive_chance(mine, ball_s, theirs, decisions.LANE_MARGIN_S)
        found = decisions.lane_chance(carrier.x, carrier.y, sx, sy, opps)
        return found * first * decisions.value(sx, sy, goal_x(p.team))

    def move_spot(self, p: Player, carrier: Player, brain: TeamBrain,
                  kind: str) -> tuple[float, float] | None:
        """O3, O4, O6, O9, O10: where a move takes him, or None if it is not open to him now. Every
        gate reads his own picture of the pitch (his beliefs), as his choice does."""
        fwd, gx = attack_dir(p.team), goal_x(p.team)
        if kind == "hold":
            return self.hold_spot(p, brain, *self.play_point(p))
        if kind == "support":  # O3: the nearest two offer a diagonal option
            mates = sorted((q for q in self.players
                            if q.team == p.team and q.id != carrier.id and q.role != "GK"),
                           key=lambda q: math.hypot(q.x - carrier.x, q.y - carrier.y))
            if p not in mates[:2]:
                return None
            presser = self.nearest(carrier.x, carrier.y, other(p.team))
            return offball.support_spot((p.x, p.y), (carrier.x, carrier.y), gx, (presser.x, presser.y))
        if self.move_prior(p, brain, kind) <= 0.0:
            return None
        view = self.beliefs[p.id]
        seen = [w for w in (view.where(q.id, self.t) for q in self.players if q.team != p.team) if w]
        if kind == "short":  # O9: back toward the ball, to receive in front of the block
            spot_x = carrier.x + fwd * roles.DROP_AHEAD_M
            if (p.x - spot_x) * fwd <= 0:  # he is not ahead of that spot: nothing to come short to
                return None
            limit = self.onside_limit(p.team, seen, carrier.x)  # L10: never into an offside spot
            spot_x = spot_x if (limit - spot_x) * fwd >= 0 else limit
            return clamp(spot_x, 1.0, PITCH_X - 1.0), (carrier.y + PITCH_Y / 2) / 2
        # The forward runs: only for the duties his team's style sends forward (or his habit of
        # running in behind), only while he is onside, and only when the carrier can play one (O4):
        # not pressed, and the ball under control or about to be (he reads it coming, sooner the
        # better his anticipation).
        role, style = roles.role_of(p.profile.archetype), roles.STYLES[brain.build_up]
        habit = kind == "in_behind" and "runs_in_behind" in p.profile.traits
        countering = (ROLE_LINE.get(p.role) == "midfield" and brain.style.level("counter_attacking") == "high"
                      and brain.attacking_transition(self.t))
        if role.duty not in style.run_duties and not habit and not (countering and kind == "in_behind"):
            return None
        settles = self.hold_until - self.t <= offball.RUN_READ_S * p.profile["anticipation"]
        nearest = min((math.hypot(x - carrier.x, y - carrier.y) for x, y in seen), default=math.inf)
        can_play = settles and nearest > decisions.PRESSURE_FRONT_M / 2
        defenders = sorted((x for x, _ in seen), key=lambda x: -fwd * x)
        second_last = defenders[1] if len(defenders) > 1 else PITCH_X - gx
        onside = (second_last - p.x) * fwd >= 0
        if not (can_play and onside):
            return None
        ball_u = (carrier.x - (PITCH_X - gx)) * fwd  # metres from his own goal line
        spot = None
        if kind == "overlap":
            if abs(carrier.y - p.ay) < roles.OVERLAP_FLANK_M and (carrier.x - p.x) * fwd > 0 \
                    and ball_u > PITCH_X / 3:
                side = 1.0 if p.ay > PITCH_Y / 2 else -1.0
                spot = (clamp(carrier.x + fwd * roles.OVERLAP_AHEAD_M, 1.0, PITCH_X - 1.0),
                        PITCH_Y / 2 + side * (PITCH_Y / 2 - roles.OVERLAP_TOUCHLINE_M))
        elif kind == "late":
            if ball_u > offball.FINAL_THIRD_M:
                spot = gx - fwd * roles.LATE_RUN_DEPTH_M, clamp(carrier.y, PITCH_Y / 2 - 4, PITCH_Y / 2 + 4)
        else:  # in behind their last line as he sees it
            behind = offball.run_in_behind((p.x, p.y), second_last, gx, can_play, onside)
            if behind and kind == "channel":
                side = 1.0 if p.y > PITCH_Y / 2 else -1.0
                spot = behind[0], PITCH_Y / 2 + side * roles.DIAGONAL_HALF_SPACE_M
            elif behind:
                spot = behind
        if spot is None:
            return None
        # Two runners do not attack the same space: a team-mate already running there takes it.
        for q, (k, x, y, _) in self.moves.items():
            if q != p.id and k in offball.FORWARD_RUNS \
                    and math.hypot(x - spot[0], y - spot[1]) < offball.SAME_POCKET_M:
                return None
        # P10: a run is a sprint, paid for from his reserve above critical speed: he makes it only
        # if what is left would pay for sprinting it flat out (the body's own rule, body.sprint_cost_m),
        # so a spent player cannot keep making them.
        body = p.physique
        gap = round(math.hypot(spot[0] - p.x, spot[1] - p.y))
        return spot if sprint_cost_m(body.f0, body.v0, body.cs, gap, DT) <= body.reserve else None

    @staticmethod
    def press_path(p: Player, fx: float, fy: float, ux: float, uy: float, gap: float) -> tuple[float, float]:
        """D8: the way a presser closes the carrier down. His spot is `gap` goal-side of where the
        carrier is going, (fx, fy), on the line from there to the goal (direction (ux, uy)). Goal-side
        of that spot, he aims at the point of that line as far beyond the spot as he is off the line
        (never nearer the carrier than the spot): on the line he steps straight up it; far off it he
        first gets into it at about his own depth; in between he cuts in at 45 degrees, so a shot
        meets him on the way. Level with the ball, behind it, or nearer the carrier than his spot,
        he runs for the spot itself."""
        along = (p.x - fx) * ux + (p.y - fy) * uy  # how far goal-side of the carrier he is
        if along <= gap:
            return fx + ux * gap, fy + uy * gap
        lateral = abs((p.x - fx) * uy - (p.y - fy) * ux)  # how far off the line
        aim = gap + min(along - gap, lateral)
        return fx + ux * aim, fy + uy * aim

    def presses_high(self, p: Player, brain: TeamBrain, bx: float, by: float) -> bool:
        """O9: is he the one of his side's pressing roles (roles.py) nearest the ball, while they
        are out of possession? One goes; the block's own pressers take over inside its line."""
        if brain.in_possession or not roles.role_of(p.profile.archetype).high_press:
            return False
        mine = [q for q in self.players if q.team == p.team and roles.role_of(q.profile.archetype).high_press
                and self.off_balance.get(q.id, -1.0) <= self.t]
        return min(mine, key=lambda q: math.hypot(q.x - bx, q.y - by)) is p

    def stretch_from(self, p: Player) -> float:
        """When the keeper's arms began to stretch: when his dive began to be prepared (his reaction
        to the touch that set it off), or his reaction to the last touch."""
        if self.dive and self.dive[0] == p.id:
            return self.dive[4]
        if self.landed and self.landed[0] == p.id and self.off_balance.get(p.id, -1.0) > self.t:
            return self.landed[1]  # down after a dive: stretched out as he landed
        return self.kicked_at + self.reaction(p)

    def rise_from(self, p: Player) -> float:
        """P15: when the keeper's centre of mass can begin to rise: when his save began, but no
        sooner than UP_AFTER_CONTACT_S after the kick it answers (only a save begun before he could
        react to the ball, as at a penalty, waits for that). During a dive, or down after one, that
        is the touch he dived at: a deflection does not pull him back out of his jump."""
        kick = self.kicked_at
        diving = self.dive and self.dive[0] == p.id
        down = self.landed and self.landed[0] == p.id and self.off_balance.get(p.id, -1.0) > self.t
        if (diving or down) and self.dived_at is not None:
            kick = self.dived_at
        return max(self.stretch_from(p), kick + offball.UP_AFTER_CONTACT_S)

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
        standing reach) with the full dive's push, and he is down for a moment afterwards. One dive
        per touch of the ball: once he is up again he does not dive a second time at the same shot;
        only a new touch (a deflection restarts it) can set off another. True while the dive moves
        him."""
        k = self.kicked
        shot_at_him = k and k["type"] == "shot" and k["team"] != p.team and self.possessor is None
        reacted = self.t - self.kicked_at >= self.reaction(p)  # to the last touch, a deflection too
        fresh = self.dived_at != self.kicked_at  # P15: one dive per touch; a deflection is a new touch
        up = self.off_balance.get(p.id, -1.0) <= self.t
        if self.dive is None and shot_at_him and reacted and fresh and up:
            arrival = self.ball_at_x(p.x)  # where the ball's own flight takes it past him
            if arrival:
                when, cross, height = arrival
                # only as far as his body must go beyond what his hands will reach, at that height,
                # by then (P11 envelope: his arms began to stretch when he reacted, whenever the dive
                # itself starts); no dive at one going over the top of it
                at, start = self.t + when, self.stretch_from(p)
                arms, top = offball.reach_for(True, at - start, height, at - self.rise_from(p))
                need = abs(cross - p.y) - arms
                if height <= top and need > 0:
                    travel = math.copysign(min(need, KEEPER_DIVE_TRAVEL_M), cross - p.y)
                    self.dive = (p.id, self.t, p.y, travel, self.kicked_at + self.reaction(p),
                                 math.copysign(1.0, travel) * p.vy)  # his sideways run toward it
                    self.dived_at = self.kicked_at
        if not self.dive or self.dive[0] != p.id:
            return False
        _, start, y0, travel = self.dive[:4]
        v0 = self.dive[5] if len(self.dive) > 5 else 0.0
        elapsed = self.t + DT - start
        # A shorter dive is the same push, stopped once he has gone far enough: as hard as the full
        # dive's, not harder. It starts from the sideways run he was already making (P2).
        done, _ = offball.dive_motion(elapsed, v0)
        landing = done >= abs(travel)
        y = y0 + math.copysign(1.0, travel) * min(done, abs(travel))  # done < 0 while braking a run away
        if landing:
            # He lands carrying the speed the push gave him, for what is left of the frame, and
            # slows on the ground from there (he is down: braking as any body does, P2), not in
            # one frame.
            reached = offball.dive_time_to(abs(travel), v0)
            carried = math.copysign(offball.dive_motion(reached, v0)[1], travel)
            y += carried * min(max(elapsed - reached, 0.0), DT)
        # P2: the run he was making when he launched brakes with the grip the dive's push leaves
        # (braking and pushing share one grip, BRAKE_MAX: while the push takes it all he carries his
        # run), never stopping dead.
        vy = carried if landing else (y - p.y) / DT
        pushing = abs(vy - p.vy) / DT
        grip = math.sqrt(max(BRAKE_MAX * BRAKE_MAX - pushing * pushing, 0.0))
        brake = min(abs(p.vx), grip * DT)
        p.vx -= math.copysign(brake, p.vx)
        p.x += p.vx * DT
        p.vy = (y - p.y) / DT
        p.y = y
        if landing:
            p.vy = carried
            self.landed = (p.id, self.dive[4])
            self.dive = None
            self.off_balance[p.id] = self.t + offball.KEEPER_DOWN_S  # on the ground: getting up
            self.dive_show[p.id] = (self.off_balance[p.id], travel)  # drawn down until he is up
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
            p.heading = turn_toward(p.heading, perception.facing(p.heading, p.vx, p.vy, p.x, p.y,
                                                                 self.ball[0], self.ball[1]))
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
        """Bodies in contact (their shapes touch, shape.py: shoulder to shoulder at a shoulder
        breadth between centres, chest to chest at a chest depth) brace: each stops closing on
        the other as fast as their own legs allow, never faster."""
        grip = BRAKE_MAX * DT
        reach = shape.SHOULDER_BREADTH_M  # no two bodies further apart than this can touch
        for i, a in enumerate(self.players):
            for b in self.players[i + 1:]:
                if abs(b.x - a.x) >= reach or abs(b.y - a.y) >= reach:
                    continue
                d, ax, ay, bx, by = shape.between(a.x, a.y, a.heading, b.x, b.y, b.heading)
                if d >= shape.CHEST_DEPTH_M:
                    continue
                if d > 1e-6:  # pushed apart along the line between their nearest surfaces
                    nx, ny = (bx - ax) / d, (by - ay) / d
                else:  # spines crossing: along the line between centres
                    c = math.hypot(b.x - a.x, b.y - a.y)
                    if c < 1e-6:
                        continue
                    nx, ny = (b.x - a.x) / c, (b.y - a.y) / c
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
            inward = 1.0 if carrier.y < PITCH_Y / 2 else -1.0
            carrier.heading = turn_toward(carrier.heading, inward * math.pi / 2)  # P16: no jump
            self.ball = (*throw_hands(carrier.x, carrier.y), 0.0, 0.0, 0.0)
            # Law 15: he throws facing the field, once his body has turned to within STRIKE_FACING of
            # it (P16: the widest angle he strikes at, here from the line straight onto the field).
            facing = fmath.cos(carrier.heading - inward * math.pi / 2) >= fmath.cos(STRIKE_FACING)
            if self.t >= self.hold_until and facing:
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
        if self.windup:  # turning to strike, he turns to face the target, not where he drifts
            want = fmath.atan2(self.windup[1] - carrier.y, self.windup[0] - carrier.x)
        else:
            want = perception.facing(carrier.heading, carrier.vx, carrier.vy, carrier.x, carrier.y,
                                     carrier.x, carrier.y)
        carrier.heading = turn_toward(carrier.heading, want)
        side = carrier.heading
        if not self.dribble_to and not self.windup:  # D8: holding, he keeps his body between ball and man
            near = min(
                (q for q in self.players if q.team != carrier.team),
                key=lambda q: math.hypot(q.x - carrier.x, q.y - carrier.y),
            )
            if math.hypot(near.x - carrier.x, near.y - carrier.y) < SHIELD_M:
                side = fmath.atan2(carrier.y - near.y, carrier.x - near.x)
        feet = shape.surface(side, carrier.heading, pad=ball.RADIUS)  # against his body on that side
        fx, fy = carrier.x + fmath.cos(side) * feet, carrier.y + fmath.sin(side) * feet
        bx, by, bz = self.ball[0] + carrier.vx * DT, self.ball[1] + carrier.vy * DT, self.ball[2]
        dx, dy, dz = fx - bx, fy - by, -bz
        d = math.sqrt(dx * dx + dy * dy + dz * dz)
        step = min(d, BALL_TO_FEET * DT)
        if d > 1e-6:
            bx, by, bz = self.settle(carrier, bx, by, bz, fx, fy, side, step * math.hypot(dx, dy) / d)
            bz = bz + dz / d * step
        before = self.ball
        bx, by, bz = self.clear_of_frame(before[:3], (bx, by, max(bz, 0.0)))
        self.ball = (bx, by, bz, carrier.vx, carrier.vy, 0.0)
        if self.went_out(before):  # Law 9 applies to a ball at a player's feet too
            self.possessor = None
            return
        if gap < 2.0 and self.t - self.pressed.get(opp, -99) > 8:
            self.pressed[opp] = self.t
            self.emit("pressure", opp, presser.x, presser.y, player=presser.id, receiver=carrier.id)
        close = self.closest_opponent(carrier) < CLOSE_CONTROL_M
        if (self.dribble_to and not self.windup and not close and math.hypot(fx - bx, fy - by) < 0.15
                and self.can_strike(carrier, *self.dribble_to)):  # a touch is a kick: he faces it (P16)
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
                   and math.hypot(q.x - p.x, q.y - p.y) < COVER_TO_COMMIT_M for q in self.players)

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
            # Law 15: a ball held for a throw-in is not in play, so a lunge that arrives then finds nothing.
            held = holder is not None and self.throw_by == holder.id
            if holder and holder.team != p.team and not held and math.hypot(p.x - bx, p.y - by) <= CONTROL_M:
                self.poke(p, holder)
                holder = None
            # `not held`: defence in depth; a lunge cannot start during a held throw-in (below).
            elif victim and not self.restart and not held and self.leg_meets(
                    p.x, p.y, victim.x, victim.y, bx, by, victim.heading):
                self.foul(p, victim)
                return
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
            line = max(line, self.foul_line(p, holder, bx, by))
            sharp = 0.02 + 0.08 * (1 - p.profile["decisions"])
            if self.rng.random() < decisions.sigmoid((p_win - line) / sharp):
                self.lunges[p.id] = self.t + lunge
                self.lunge_at[p.id] = holder.id
                self.evade_at[p.id] = self.t + holder.profile.reaction()

    def foul_line(self, p: Player, holder: Player, bx: float, by: float) -> float:
        """Law 14 in his head: in his own box, with the man across the line of his lunge, a miss is
        a penalty. Against standing off (their threat here, the engine's own value of the ball),
        committing pays only if p_win * threat >= (1 - p_win) * (PENALTY_GOAL_P - threat), so he
        needs p_win of at least 1 - threat / PENALTY_GOAL_P. Elsewhere a miss through the man is a
        free kick where they already had the ball: no extra line."""
        own = PITCH_X - goal_x(p.team)
        if not decisions.in_box(holder.x, holder.y, own):
            return 0.0
        # Where the man and the ball at his feet will be when his foot gets there: carried on at
        # the man's speed, and pushed across him (evade, an average dribbler) if the man reacts in
        # time. He lunges along the same distance toward where it will be: does his leg then
        # sweep through the man?
        d = math.hypot(bx - p.x, by - p.y)
        lunge = decisions.lunge_time(d, p.profile["tackling"])
        push = max(0.0, lunge - decisions.GENERIC_REACTION_S) * (EVADE_MPS + 2.0 * 0.5)
        a = evade_angle(holder.team, bx, by, p.x, p.y)
        mx, my = holder.x + holder.vx * lunge, holder.y + holder.vy * lunge
        ex = bx + holder.vx * lunge + fmath.cos(a) * push
        ey = by + holder.vy * lunge + fmath.sin(a) * push
        far = math.hypot(ex - p.x, ey - p.y) or 1.0
        step = max(0.0, d - CONTROL_M) / far  # he covers what he would have to the ball now
        ax, ay = p.x + (ex - p.x) * step, p.y + (ey - p.y) * step
        now = self.leg_meets(p.x, p.y, holder.x, holder.y, bx, by, holder.heading)
        ahead = self.leg_meets(ax, ay, mx, my, ex, ey, holder.heading)
        # A carrier holding the ball with him this close shields it (tick_carrier, D8): the ball
        # goes to the far side of the man, so a lunge for it goes through him.
        shielded = False
        if not self.dribble_to and math.hypot(mx - ax, my - ay) < SHIELD_M:
            side = fmath.atan2(my - ay, mx - ax)  # away from the defender, as tick_carrier puts it
            feet = shape.surface(side, holder.heading, pad=ball.RADIUS)
            far_side = mx + fmath.cos(side) * feet, my + fmath.sin(side) * feet
            shielded = self.leg_meets(ax, ay, mx, my, *far_side, holder.heading)
        if not (now or ahead or shielded):
            return 0.0
        threat = decisions.value(bx, by, own)  # their chance of scoring from having it here
        return clamp(1.0 - threat / PENALTY_GOAL_P, 0.0, 1.0)

    @staticmethod
    def leg_meets(px: float, py: float, vx: float, vy: float, bx: float, by: float, heading: float) -> bool:
        """Law 12: a lunge that arrives with the ball gone still sweeps his leg toward it, a foot's
        reach (CONTROL_M) from his body. If that leg passes through the man he went for, at
        (vx, vy) and facing `heading` (his body's outline: shape.py, P11), he has made contact with
        the opponent, not the ball."""
        dx, dy = bx - px, by - py
        d = math.hypot(dx, dy)
        if d < 1e-6:
            return False
        fx, fy = px + dx / d * min(d, CONTROL_M), py + dy / d * min(d, CONTROL_M)
        a0x, a0y, a1x, a1y = shape.spine(vx, vy, heading)
        return shape.segments_closest(px, py, fx, fy, a0x, a0y, a1x, a1y)[1] <= shape.RADIUS_M

    def foul(self, p: Player, victim: Player) -> None:
        """Law 12: a careless challenge that hits the man: a direct free kick to his side where it
        happened (Law 13); in the offender's own penalty area, a penalty kick (Law 14), taken by
        his side's best finisher."""
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
        gx = goal_x(victim.team)  # the offender's own goal
        if decisions.in_box(victim.x, victim.y, gx):
            self.penalties += 1
            taker = max((q for q in self.players if q.team == victim.team and q.role != "GK"),
                        key=lambda q: q.profile["finishing"])  # the side's designated taker (design)
            self.stop("penalty_kick", victim.team, (gx - attack_dir(victim.team) * PENALTY_MARK_M,
                                                    PITCH_Y / 2), taker.id)
            return
        self.stop("free_kick", victim.team, (clamp(victim.x, 0.5, PITCH_X - 0.5),
                                             clamp(victim.y, 0.5, PITCH_Y - 0.5)))

    def evade(self, carrier: Player, defender: Player) -> None:
        """The carrier, having reacted to a lunge, pushes the ball away from the defender's foot,
        to the side that keeps him going forward; a better dribbler moves it quicker."""
        bx, by = self.ball[0], self.ball[1]
        angle = evade_angle(carrier.team, bx, by, defender.x, defender.y)
        speed = EVADE_MPS + 2.0 * carrier.profile["dribbling"]
        vx, vy, vz = self.execute(carrier, fmath.cos(angle) * speed, fmath.sin(angle) * speed, 0.0,
                                  "dribbling")
        self.ball = (bx, by, self.ball[2], vx, vy, vz)
        self.possessor, self.dribbler, self.dribble_to = None, carrier.id, None
        self.last_touch = carrier.id
        self.free_since = self.t
        self.kicker_clear, self.kicker_far, self.touched_since_kick = False, False, True

    def poke(self, p: Player, holder: Player) -> None:
        """A tackle that reaches the ball knocks it loose; whoever then controls it decides the
        tackle (won or lost)."""
        heading = (
            fmath.atan2(p.vy, p.vx)
            if math.hypot(p.vx, p.vy) > 0.5
            else fmath.atan2(self.ball[1] - p.y, self.ball[0] - p.x)
        )
        angle = heading + math.radians(self.rng.gauss(0.0, 40.0))
        self.ball = (
            self.ball[0],
            self.ball[1],
            0.0,
            holder.vx * 0.3 + POKE_MPS * fmath.cos(angle),
            holder.vy * 0.3 + POKE_MPS * fmath.sin(angle),
            0.0,
        )
        self.tackle = self.emit(
            "tackle", p.team, self.ball[0], self.ball[1], player=p.id, receiver=holder.id, outcome=None
        )
        self.possessor, self.dribbler, self.dribble_to, self.windup = None, None, None, None
        self.last_touch = p.id
        self.kicked_at = self.free_since = self.t
        self.bumped = None
        self.kicker_clear, self.kicker_far, self.touched_since_kick = False, False, True
        self.plan_chase()

    def settle(self, carrier: Player, bx: float, by: float, bz: float, fx: float, fy: float,
               side: float, budget: float) -> tuple[float, float, float]:
        """Move a carried ball `budget` metres across the ground toward his feet at (fx, fy):
        straight, until its way would meet his body, then round the outline of his body (P11)
        for the rest of the distance, never through him and never further than `budget`."""
        hx, hy = fx - bx, fy - by
        h = math.hypot(hx, hy)
        if h < 1e-9:
            return bx, by, bz
        if shape.clearance(bx, by, carrier.x, carrier.y, carrier.heading) < ball.RADIUS - 1e-3:
            # Overlapping him (after he turns, or placed on him for a restart): first out to his
            # outline the way it lies from him (toward his feet if it sits on his centre), no
            # further than the budget; then round, as below.
            ox, oy = bx - carrier.x, by - carrier.y
            out_a = fmath.atan2(oy, ox) if math.hypot(ox, oy) > 1e-6 else side
            r = shape.surface(out_a, carrier.heading, pad=ball.RADIUS)
            tx, ty = carrier.x + fmath.cos(out_a) * r, carrier.y + fmath.sin(out_a) * r
            out = math.hypot(tx - bx, ty - by)
            if out >= budget:
                return bx + (tx - bx) / out * budget, by + (ty - by) / out * budget, bz
            bx, by, budget = tx, ty, budget - out
        else:
            s = shape.first_contact(bx, by, fx, fy, carrier.x, carrier.y, carrier.heading, ball.RADIUS - 1e-3)
            straight = h if s is None else s * h
            if budget <= straight:
                return bx + hx / h * budget, by + hy / h * budget, bz
            bx, by, budget = bx + hx / h * straight, by + hy / h * straight, budget - straight
        # Round his outline toward the side the feet are on, the short way, in small arcs whose
        # chords add up to no more than what is left of the budget.
        around = fmath.atan2(by - carrier.y, bx - carrier.x)
        r = shape.surface(around, carrier.heading, pad=ball.RADIUS)
        px, py = carrier.x + fmath.cos(around) * r, carrier.y + fmath.sin(around) * r
        budget -= math.hypot(px - bx, py - by)  # onto the outline (at most a millimetre)
        turn = (side - around + math.pi) % (2 * math.pi) - math.pi
        sign, left = (1.0 if turn > 0 else -1.0), abs(turn)
        while budget > 0 and left > 1e-9:
            da = min(0.02, left)
            a = around + sign * da
            r = shape.surface(a, carrier.heading, pad=ball.RADIUS)
            nx, ny = carrier.x + fmath.cos(a) * r, carrier.y + fmath.sin(a) * r
            piece = math.hypot(nx - px, ny - py)
            if piece > budget:
                k = budget / piece
                a = around + sign * da * k
                r = shape.surface(a, carrier.heading, pad=ball.RADIUS)
                nx, ny = carrier.x + fmath.cos(a) * r, carrier.y + fmath.sin(a) * r
                piece = budget
                da *= k
            px, py, around, left, budget = nx, ny, a, left - da, budget - piece
        return px, py, bz

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
        heading = fmath.atan2(uy, ux)
        turn = decisions.turn_deg(heading, carrier.heading)

        def lands(v: float, angle: float) -> bool:
            path = ball.predict((bx, by, 0.0, fmath.cos(angle) * v, fmath.sin(angle) * v, 0.0), DT,
                                TOUCH_GAP_S)
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
        turn = abs(
            (fmath.atan2(vy, vx) - fmath.atan2(carrier.vy, carrier.vx) + math.pi) % (2 * math.pi) - math.pi
        )
        if not moving or turn > math.radians(TOUCH_EXPECTED_DEG):
            self.kicked_at = self.t
            self.bumped = None
        self.free_since = self.t
        self.kicker_clear = self.kicker_far = False
        self.touched_since_kick = True
        # Who goes for the loose ball is judged at once: a defender who has been watching the carry
        # and can get there first commits to it, rather than keep shadowing.
        self.plan_chase()
        return True

    def _show_touch(self, p: Player, cx: float, cy: float, cz: float, aerial: bool) -> None:
        """The part that met the ball. A carry's own touch is the gait. Anything else is drawn."""
        if self.hands(p, cx, cy):
            part = "hands"
        elif aerial:
            if cz < THIGH_TOP_Z:  # design (P14): the part by height
                part = "thigh"
            elif cz < CHEST_TOP_Z:
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
        chosen, a dive is the keeper's own dive, and a touch names the part that met the ball."""
        if self.throw_by == p.id:
            return "throw", 0.0
        if self.possessor == p.id and self.windup:
            return "strike", 0.0
        # A dive is drawn from the engine's own dive (keeper_dive): how far along it he is and
        # which way; down after it, at full stretch until he is up.
        gone = side = None
        if self.dive and self.dive[0] == p.id:
            _, _, y0, travel = self.dive[:4]
            gone, side = clamp(abs(p.y - y0) / max(abs(travel), 1e-6), 0.0, 1.0), travel
        elif p.id in self.dive_show and self.t < self.dive_show[p.id][0]:
            gone, side = 1.0, self.dive_show[p.id][1]
        if gone is not None:
            left = fmath.sin(math.copysign(math.pi / 2, side) - p.heading) >= 0  # to his left
            return "dive", round(gone if left else -gone, 3)
        touch = self.touch_show.get(p.id)
        if touch and self.t < touch[1]:
            return touch[0], 0.0
        speed = math.hypot(p.vx, p.vy)
        if speed > 4:
            return "run", 0.0
        if speed > 0.5:
            return "walk", 0.0
        return "stand", 0.0

    def reseed(self, seed: int) -> None:
        """New random streams from here on (a scenario attempt branched from a played moment)."""
        self.rng = fmath.Random(seed)
        self.sight_rng = fmath.Random(f"{seed}-perception")

    def attacking(self) -> bool:
        """S9: the home side's play (its possession, through its passes) in the final third it
        attacks, in open play: no restart pending or being taken (a throw-in or free kick held, or
        the ball just restarted and not yet played on)."""
        return self.poss_team == "home" and self.ball[0] >= FINAL_THIRD_X and self.restart is None \
            and self.from_restart is None and self.throw_by is None

    def next_attacking_moment(self, until: float) -> bool:
        """S9: play on to the next moment the home side brings the ball into its final third, or
        wins it there, in open play, with one of its players on it and nothing struck or contested
        in flight (after this moment, if this is one); False if none comes before the clock reaches
        `until`."""
        armed = not self.attacking()
        while self.t < until:
            self.step()
            if not self.attacking():
                armed = True
            elif armed and self.possessor and self.team_of(self.possessor) == "home" and \
                    self.kicked is None and self.tackle is None and self.last_deflection is None:
                return True  # nothing struck or contested is in flight: the clip starts clean
        return False

    def play_until_corner(self) -> bool:
        """Play on from the opening until the home side is given a corner (True), or the attack is
        over (False): a goal, a goal kick, a corner the other way, the away side on the ball 40 m
        or more from the goal being attacked, or CORNER_WITHIN_S gone (S9)."""
        opened = self.t
        while self.t - opened < CORNER_WITHIN_S:
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
        players = []
        for p in self.players:
            action, dive = self.pose(p)  # what the renderer draws (scene.py), read off the match
            players.append({"id": p.id, "team": p.team, "role": p.role, "x": round(p.x, 3),
                            "y": round(p.y, 3), "vx": round(p.vx, 3), "vy": round(p.vy, 3),
                            "heading": round(p.heading, 4), "action": action, "dive": dive})
        self.match.frames.append({
            "frame": self.frame,
            "t": round(self.t, 3),
            "ball": {"x": round(bx, 3), "y": round(by, 3), "z": round(bz, 3), "vx": round(self.ball[3], 3),
                     "vy": round(self.ball[4], 3), "vz": round(self.ball[5], 3)},
            "possessor": self.possessor,
            "players": players,
        })

    def step(self) -> None:
        """One frame: everyone perceives and decides, the ball is played, everyone moves."""
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


def entry(ax: float, ay: float, dx: float, dy: float, r: float) -> float:
    """The first s (0 to 1) along a step from (ax, ay) by (dx, dy), relative to a player, where the
    ball comes within `r` of him (0 if it starts within it); the step's closest point if it never
    does."""
    a2, ad, d2 = ax * ax + ay * ay, ax * dx + ay * dy, dx * dx + dy * dy
    if a2 <= r * r or d2 == 0:
        return 0.0
    disc = ad * ad - d2 * (a2 - r * r)
    if disc < 0:
        return clamp(-ad / d2, 0.0, 1.0)
    return clamp((-ad - math.sqrt(disc)) / d2, 0.0, 1.0)


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


def corner_attempts(seed: int):
    """S9: the attempts the corner scenario plays, in order, each an engine at a played moment of
    the home side bringing the ball into its final third, with its own random streams
    (corner_seed). A base match is played no longer than BASE_MATCH_S; then a new one begins."""
    attempt = 0
    for k in range(CORNER_ATTEMPTS):
        base_seed = corner_seed(seed, BASE_SEEDS_FROM + k)
        base = Engine(base_seed)
        base.kickoff("home")
        while attempt < CORNER_ATTEMPTS and base.next_attacking_moment(BASE_MATCH_S):
            base.match.frames, base.match.events = [], []  # the clip's record starts at the moment
            for _ in range(min(MOMENT_ATTEMPTS, CORNER_ATTEMPTS - attempt)):
                attempt += 1
                e = copy.deepcopy(base)
                e.reseed(corner_seed(seed, attempt))
                e.match.seed = corner_seed(seed, attempt)
                e.match.base_seed, e.match.opening_t = base_seed, round(base.t, 3)
                yield e
        if attempt >= CORNER_ATTEMPTS:
            return


def rebased(m: Match) -> Match:
    """The clip's record from its first frame: frames and events from 0 (as a clip from the kick-off
    is), the score its own goals. The engine's clock and score ran on from the kick-off."""
    f0, t0 = m.frames[0]["frame"], m.frames[0]["t"]
    for f in m.frames:
        f["frame"] -= f0
        f["t"] = round(f["t"] - t0, 3)
    for e in m.events:
        e["frame"] -= f0
        e["t"] = round(e["t"] - t0, 2)
    goals = [e["team"] for e in m.events if e["type"] == "goal"]
    m.score = {"home": goals.count("home"), "away": goals.count("away")}
    return m


def simulate(seed: int, minutes: float, strengths: dict[str, float] | None = None,
             styles: dict[str, Style] | None = None, scenario: str | None = None) -> Match:
    """A match from the kick-off, or a scenario clip. `corner`: attacks from a moment open play
    reaches (the home side on the ball in its final third) are played out, each with its own random
    streams (corner_attempts), and the first one that play turns into a home corner is kept and run
    on for `minutes` after the corner is given (S9). The match records the attempt's seed. Selection
    among played-out attacks, never an arranged one: corners from this scenario say nothing about
    how often play produces them."""
    if scenario is None:
        return Engine(seed, strengths, styles).run(minutes)
    if scenario != "corner":
        raise ValueError(f"unknown scenario {scenario!r}; known: corner")
    for e in corner_attempts(seed):
        if e.play_until_corner():
            for _ in range(int(minutes * 60 * FPS)):
                e.step()
            return rebased(e.match)
    raise RuntimeError(f"no corner in {CORNER_ATTEMPTS} attacks from seed {seed}")
