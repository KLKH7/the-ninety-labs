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

import dataclasses
import itertools
import math
from dataclasses import asdict, dataclass, field

from ninety.sim import ball, decisions, firsttouch, fmath, offball, pacing, perception, profiles, shape
from ninety.sim import team as team_mod
from ninety.sim.body import (
    BODY_HEIGHT,
    BRAKE_MAX,
    CONTROL_M,
    CS_MEAN,
    D0,
    F0_MEAN,
    STRIKE_FACING,
    TURN_RATE,
    V0_MEAN,
    Body,
    can_get_to,
    relative_speed,
    stopping_distance,
    stopping_speed,
)
from ninety.sim.body import move as move_body
from ninety.sim.decisions import PENALTY_DEPTH, PENALTY_HALF_WIDTH
from ninety.sim.firsttouch import BODY_TOUCH_Z, TOUCH_GAP_S  # A4, P14, D6
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
SPRINT = 99.0  # as fast as their body allows (a keeper's dash, P17 does not price his)
RECOVER = 6.0  # a restart taker or the keeper getting into position, a goal's celebration runs (design)
SHAPE = 3.0  # getting up after being beaten (design)
DRIBBLE = 2.5
DECIDE_EVERY = 6  # frames between the ball carrier's decisions (about 4 a second)
PERCEIVE_EVERY = 6  # frames between a player's looks at the pitch (about 4 a second, staggered)
BRAIN_EVERY = 12  # frames between a team brain's reads of the game (about 2 a second)
BLOCK_DIAL = {"low": LOW, "mid": MID, "high": HIGH}  # a drawn block as a style dial (T4)
COVER_BEHIND_M = 8.0  # design: the covering player stands this far goal-side of the ball, behind the presser
PERCEPTION_ERR = 0.03  # verify: m/s of misjudged ball velocity per metre between player and ball
PERSONAL_SPACE_M = 1.2  # players steer to keep about this far from each other
ANTICIPATE_S = 0.4  # verify: how far ahead players judge where others will be
BODY_RESTITUTION = 0.3  # verify: share of the ball's speed into a body that it keeps
TOUCH_POSE_S = 0.30  # design (P14): how long the body shows the part that met the ball
MISCONTROL_KEEP = 0.4  # verify: share of speed a ball keeps off a touch it beats, or a parry
POST_RADIUS = 0.06  # Law 1: posts and crossbar at most 12 cm wide
WOODWORK_RESTITUTION = 0.6  # verify
BALL_TO_FEET = 12.0  # P6 (design): how fast a carried ball settles to his feet, m/s
# Dribbling is a run of touches (D6): the ball is pushed ahead and the dribbler runs onto it, so
# between touches it is free and a defender who gets there first wins it. All *design*, *verify*.
TOUCH_CLOSE_M = 0.8  # how far ahead a touch puts the ball with an opponent close
TOUCH_SPACE_M = 3.0  # how much further when he has space (nearest opponent 10 m or more)
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
GOAL_HALF_WIDTH, CROSSBAR = 3.66, 2.44  # Law 1
GOAL_AREA_X = 5.5  # Law 1
# Laws 15 to 17: opponents keep this far from a restart until the ball is in play.
RESTART_DISTANCE_M = {"throw_in": 2.0, "corner": 9.15, "goal_kick": PENALTY_DEPTH - GOAL_AREA_X + 1.0,
                      "free_kick": 9.15, "kick_off": 9.15,
                      "penalty_kick": 9.15}  # Laws 8, 13 and 14: 9.15 m (the centre circle, the arc)
PENALTY_MARK_M = 11.0  # Law 1: the penalty mark, 11 m from the goal line
CORNER_ARC_M = 1.0  # Law 1: the corner arc's radius; Law 17 measures the 9.15 m from the arc
KEEP_OFF_MARGIN_M = 0.5  # design: opponents aim this far outside a restart's distance, as at a kickoff
# Law 13 and Bray (Plus Maths, 2014): at a direct free kick the defending side builds a wall at the
# restart's distance that hides the goal from the near post to this far past its centre (Bray: two
# thirds of the goal line, q = p / 3); the keeper covers the rest
WALL_COVER_PAST_CENTRE_M = GOAL_HALF_WIDTH / 3
WALL_ATTACKER_GAP_M = 1.0  # Law 13: with three or more defenders in a wall, attackers stay 1 m from it
# design: a wall player first stands behind his place to within this much across the line (a few times
# the 1 to 2 cm by which steering stops on a target), then steps forward into it
WALL_LANE_M = 0.1
ON_CIRCLE_M = 1e-6  # a target this close to a keep-off circle's edge is on it (rounding), not inside
# design: the taker stands this far from a set ball's centre, so it is clear of him whichever way he
# is turned (his shoulder's reach, P11) with a ball's width to spare for his steering
SET_BALL_CLEAR_M = shape.surface(math.pi / 2, 0.0, pad=2 * ball.RADIUS)
# design: going round a restart's circle he aims this far round at a time; the chord between two
# points on it dips inside by at most 1 - cos(15°), under 4% of the radius (0.35 m at 9.65 m)
KEEP_OFF_STEP_DEG = 30.0
BOARDS_M = 4.0  # verify: advertising boards behind the lines stop a ball (and players) that go out
# design, verify: a goal's net, as the renderer draws it (web/render/render.js, buildNet): NET_DEPTH_M
# behind the goal line at the top and the bottom, its back NET_BACK_M high, its roof sloping down to
# it from the crossbar. Law 1 sets the posts and crossbar, not the net; nets for a full-size goal
# (7.32 x 2.44 m) are sold 1.8 to 2.6 m deep (UEFA- and Premier-League-grade stadium nets listed at
# 6 ft, 1.83 m; box nets at 2 m). Players keep NET_CLEAR_M from it going round, a stride (design).
NET_DEPTH_M = 2.0
NET_BACK_M = 2.0
NET_CLEAR_M = 1.0
# R1: seconds from the ball going out to the restart. Means from Opta timing of the Premier League
# (The Analyst): throw-ins about 16 s (2022-23; 17.9 in 2025-26), goal kicks 29 to 30 s, free kicks
# 31.3 to 40.9 s by team (2022-23; mean taken as the middle), corners about half a minute (only a
# combined figure is published). The spread around each mean is design. The kick-off that starts the
# match: design, long enough to see. After a goal (L4): FIFA's referees' chief, on added time at the
# 2022 World Cup, put a goal's celebration at "one, one and a half minutes" (Collina, November 2022);
# Opta's guide gives 72 s for the celebration after a penalty goal (The Analyst, May 2023).
RESTART_DELAY_S = {"throw_in": (12, 20), "goal_kick": (24, 34), "corner": (24, 36),
                   "free_kick": (29, 41),
                   # about two minutes from the foul to the spot kick (same source, 2022-23)
                   "penalty_kick": (100, 140),
                   "kick_off": (1, 2),
                   "kick_off_after_goal": (60, 90)}
# design: a fouled player goes down and gets up. A standing body topples over its feet in about
# half a second; he lies short of flat, so his head stays off the grass, stays there a moment,
# and gets up in about a second. He is upright this long before the restart is due. The lie
# shortens first when the restart is sooner than the whole pose; the topple and the get-up then
# scale together. The validator's floor is 1 s (ninety/validate.py, P18).
FALL_S = 0.5
FALL_LIE_S = 1.5
FALL_RISE_S = 1.0
FALL_DOWN_DEG = 85.0
FALL_UP_BEFORE_S = 1.5


def foul_fall_deg(elapsed: float, span: float) -> float:
    """Degrees the body is over. 0 at the contact and once `span` has run. Design: half the
    topple at a steady rate and half gathering pace; the get-up eases in and out; the lie is
    whatever the span leaves after the topple and the get-up."""
    if span <= 0.0 or elapsed <= 0.0 or elapsed >= span:
        return 0.0
    fall_s, rise_s = FALL_S, FALL_RISE_S
    if span < fall_s + rise_s:
        scale = span / (fall_s + rise_s)
        fall_s, rise_s = fall_s * scale, rise_s * scale
        lie_s = 0.0
    else:
        lie_s = span - fall_s - rise_s
    if elapsed < fall_s:
        u = elapsed / fall_s
        return FALL_DOWN_DEG * 0.5 * (u + u * u)  # *design*: half steady, half gathering pace
    if elapsed < fall_s + lie_s:
        return FALL_DOWN_DEG
    u = (elapsed - fall_s - lie_s) / rise_s
    return FALL_DOWN_DEG * (1.0 - u * u * (3.0 - 2.0 * u))  # *design*: the get-up eases in and out
# design: how long each of the scorer's team-mates celebrates with him (the run to him, the huddle);
# the scorer stays until the last has gone; the rest of the minute or more before the kick-off is
# the walk back (L4)
CELEBRATION_S = (15.0, 25.0)
# design: team-mates round a scorer stand a shoulder's breadth apart (P11) with a little to spare
HUDDLE_SPACING_M = 0.55
# design: from where a team-mate running at RECOVER must start braking for his place (round a
# scorer, in a wall; stopping as body.stopping_speed has him, with P2's grip), he is joining the
# others, and stands as close to them as bodies allow; the switch at that distance is design, about
# 3.2 m
GATHER_REACH_M = stopping_distance(RECOVER)
# L4: after a goal players walk back at least at a normal walking pace: men aged 20 to 29 walk at
# about 1.36 m/s (Bohannon & Andrews 2011, Physiotherapy 97:182, a meta-analysis of 23,111 adults,
# as tabulated by the University of Toronto's iWalk guide)
WALK_MPS = 1.36
# design: about a stride. While a restart waits, a player standing at his place settles to a shift
# of it smaller than this at his own pace, rather than walking to it and back (lesson 174)
SETTLE_M = 1.0
# design: a few strides. Settled at his place, a player makes a later shift of it within this at his
# own pace; further, as when the restart's shape forms after the whistle or his man walks off, he
# walks to it again (L4) and settles there. Longer than the 1 to 3.5 m by which places jumped with
# noisy sightings, which settling is there to absorb (lesson 174)
SHUFFLE_M = 4.0
NO_OFFSIDE_FROM = ("throw_in", "goal_kick", "corner")  # Law 11: no offside offence direct from these
INTERCEPT_SHARE = 0.85  # design: taken before this share of the way to its target, a pass is intercepted
THROW_BEHIND_M = 0.55  # Law 15: his body stands outside the touchline, feet on or behind it (design)
THROW_SPOT_M = 0.25  # design: within this of his spot he throws from where he stands, still behind the line
THROW_SETTLED_MPS = BRAKE_MAX * DT  # a taker takes it once one frame of braking would stop him (P2)
# design: closing on his place faster than one frame of braking would stop him (P2), a player is still
# walking in to it, and keeps a walking pace (lesson 174)
CLOSING_MPS = BRAKE_MAX * DT
THROW_REACH_M = 0.28  # design: both hands reach toward the pitch and still stay short of the line
THROW_HAND_Z = 1.85  # design: bottom of the ball just over an average head (no stature per player)
# Law 12: a keeper who has the ball in his hands releases it within six seconds, and nobody may
# challenge him for it while he holds it. He holds it at his chest (design) and lets it go at
# KEEPER_RELEASE_S, a second inside the limit (design), not on the first look (L15).
KEEPER_HOLD_S = 6.0
KEEPER_RELEASE_S = KEEPER_HOLD_S - 1.0
KEEPER_HOLD_Z = 1.1  # design: the ball at an average chest
KEEPER_HOLD_AHEAD_M = 0.3  # design: held out in front of his body

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
    kind: str  # "throw_in" | "goal_kick" | "corner" | "free_kick" | "penalty_kick" | "kick_off"
    team: str
    x: float
    y: float
    taker: str
    ready_at: float
    fetcher: str | None = None  # who of the restarting side goes to get the dead ball
    carried_by: str | None = None  # who has the dead ball at his feet (or in his hands)
    passed_by: str | None = None  # who knocked it on toward the spot, while it is still rolling
    gathered_at: float = 0.0  # when the one who has it took it
    direct: bool = True  # a free kick that may be scored from directly (Law 13); offside's is indirect
    wall: dict[str, tuple[float, float]] = field(default_factory=dict)  # defender -> his spot in it
    pressers: list[str] | None = None  # the other side's presser and cover, set once (lesson 174)
    settled: set[str] = field(default_factory=set)  # at their places with the ball set (lesson 174)
    marks: dict[str, str] | None = None  # the other side's markers and their men (lesson 174)


@dataclass
class Celebration:
    team: str  # the side that scored
    focus: str  # the scorer (or, for an own goal, the scoring side's player nearest the ball)
    spot: tuple[float, float]  # where he goes: the corner flag nearest him at that end, a keeper stays
    until: float  # when the last of them stops celebrating
    ring: list[str] = field(default_factory=list)  # the team-mates who run to him
    leave: dict[str, float] = field(default_factory=dict)  # when each, the focus too, stops celebrating
    places: dict[str, tuple[float, float]] = field(default_factory=dict)  # this frame's places round him


@dataclass
class Match:
    seed: int
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


def segment_distance(px: float, py: float, ax: float, ay: float, bx: float, by: float) -> float:
    """How close the straight way from (ax, ay) to (bx, by) comes to (px, py)."""
    dx, dy = bx - ax, by - ay
    length_sq = dx * dx + dy * dy
    s = 0.0 if length_sq < 1e-12 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / length_sq))
    return math.hypot(ax + s * dx - px, ay + s * dy - py)


def crosses(a: tuple[float, float], b: tuple[float, float], c: tuple[float, float],
            d: tuple[float, float]) -> bool:
    """Whether the straight way from a to b crosses the segment from c to d (touching it counts)."""
    def side(p: tuple[float, float], q: tuple[float, float], r: tuple[float, float]) -> float:
        return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])
    d1, d2, d3, d4 = side(c, d, a), side(c, d, b), side(a, b, c), side(a, b, d)
    return d1 * d2 <= 0 and d3 * d4 <= 0 and (d1, d2) != (0.0, 0.0)


def goal_net(line: float) -> list[tuple[tuple[float, float], tuple[float, float]]]:
    """The net of the goal on this goal line, seen from above: its two sides and its back,
    NET_DEPTH_M behind the line, from post to post (Law 1)."""
    out = 1.0 if line > 0 else -1.0
    lo, hi, back = PITCH_Y / 2 - GOAL_HALF_WIDTH, PITCH_Y / 2 + GOAL_HALF_WIDTH, line + out * NET_DEPTH_M
    return [((line, lo), (back, lo)), ((line, hi), (back, hi)), ((back, lo), (back, hi))]


NETS = [side for line in (0.0, PITCH_X) for side in goal_net(line)]


def net_stop(px: float, py: float, x: float, y: float, vx: float,
             vy: float) -> tuple[float, float, float, float]:
    """A goal's net stops a player as the advertising boards do (steer): the part of his step from
    (px, py) to (x, y) that would take him through it, along the axis it crosses, is not made."""
    if 0.0 < min(px, x) and max(px, x) < PITCH_X:  # both ends in front of both goal lines
        return x, y, vx, vy
    for _ in range(2):  # a step through a corner of the net meets its side and its back
        hit = False
        for c, d in NETS:
            if crosses((px, py), (x, y), c, d):
                hit = True
                if c[0] == d[0]:  # the back of the net
                    x, vx = px, 0.0
                else:  # a side of it
                    y, vy = py, 0.0
        if not hit:
            break
    return x, y, vx, vy


def in_the_net(s: ball.State, line: float | None) -> tuple[ball.State, float | None]:
    """Law 1 and NET_DEPTH_M: a ball that has gone into the goal on this goal line is held by its
    net. Where it meets the back net, a side net or the roof, its speed into the net is lost
    (design: a net gives and holds it), and it drops and rolls inside the goal. Returns the ball,
    and the goal line whose net still holds it: none once it is back on the pitch, out through
    the goal mouth."""
    if line is None:
        return s, None
    bx, by, bz, vx, vy, vz = s
    out = 1.0 if line > 0 else -1.0  # from the goal line into the goal
    if (bx - line) * out <= 0:
        return s, None
    back = line + out * (NET_DEPTH_M - ball.RADIUS)
    if (bx - back) * out > 0:
        bx = back
        vx = 0.0 if vx * out > 0 else vx
    side = GOAL_HALF_WIDTH - ball.RADIUS
    if abs(by - PITCH_Y / 2) > side:
        by = PITCH_Y / 2 + math.copysign(side, by - PITCH_Y / 2)
        vy = 0.0 if vy * (by - PITCH_Y / 2) > 0 else vy
    behind = min((bx - line) * out, NET_DEPTH_M)  # the roof slopes down from the crossbar to the back
    roof = CROSSBAR + (NET_BACK_M - CROSSBAR) * behind / NET_DEPTH_M - 2 * ball.RADIUS
    if bz > roof:
        bz, vz = roof, min(vz, 0.0)
    return (bx, by, bz, vx, vy, vz), line


def goal_entered(before: ball.State, after: ball.State) -> float | None:
    """The goal line the ball went into the goal over, from `before` to `after`: its centre over
    the line, the whole ball between the posts and under the bar where it crossed (as for a goal,
    Law 10, Engine.in_goal). None if it did not go in."""
    for line in (0.0, PITCH_X):
        out = 1.0 if line > 0 else -1.0
        a, b = (before[0] - line) * out, (after[0] - line) * out
        if a <= 0 < b:
            k = a / (a - b)  # how far through the move it crosses the line
            if Engine.in_goal(before[1] + k * (after[1] - before[1]), before[2] + k * (after[2] - before[2])):
                return line
    return None


def net_step(before: ball.State, after: ball.State, line: float | None) -> tuple[ball.State, float | None]:
    """A dead ball's move from `before` to `after`, held by the net of the goal it is in (`line`),
    or has just gone into (goal_entered): a goal, or a ball played on after the whistle. A ball
    outside the goal meets no net (design, as specified for lesson 184: the net's outside, met by a
    ball wide of a post or dropping over the bar, is not modelled yet)."""
    return in_the_net(after, goal_entered(before, after) if line is None else line)


def within_lines(x: float, y: float) -> bool:
    """Half a metre or more inside the lines, as players' targets are kept: they brake for a line
    rather than stop dead at it."""
    return 0.5 <= x <= PITCH_X - 0.5 and 0.5 <= y <= PITCH_Y - 0.5


def circle_point_within_lines(cx: float, cy: float, radius: float, nx: float, ny: float,
                              then: tuple[float, float] | None = None) -> tuple[float, float] | None:
    """The point of the circle of `radius` round (cx, cy) that is within the lines (within_lines)
    nearest (nx, ny), or with `then`, on the shortest way from (nx, ny) by it to `then`; searched
    every 5 degrees (design: under 0.9 m apart at 10.15 m); None if none is."""
    round_it = [(cx + fmath.cos(math.radians(a)) * radius, cy + fmath.sin(math.radians(a)) * radius)
                for a in range(0, 360, 5)]
    on = [q for q in round_it if within_lines(*q)]

    def way(q: tuple[float, float]) -> float:
        on_to = math.hypot(q[0] - then[0], q[1] - then[1]) if then else 0.0
        return math.hypot(q[0] - nx, q[1] - ny) + on_to

    return min(on, key=way) if on else None


def round_reach(cx: float, cy: float, radius: float, a: float, m: float) -> float | None:
    """How far from (cx, cy) a player going round its circle of `radius` aims at bearing `a`: at
    his own distance m, but within the lines (within_lines) and never inside the circle; None if no
    point at that bearing is both."""
    ux, uy = fmath.cos(a), fmath.sin(a)
    lo, hi = radius, math.inf
    for c, u, length in ((cx, ux, PITCH_X), (cy, uy, PITCH_Y)):
        if abs(u) < 1e-12:
            if not 0.5 <= c <= length - 0.5:
                return None
            continue
        s, t = (0.5 - c) / u, (length - 0.5 - c) / u
        lo, hi = max(lo, min(s, t)), min(hi, max(s, t))
    return clamp(m, lo, hi) if lo <= hi else None


def way_round_within_lines(cx: float, cy: float, radius: float, here: float, turn: float,
                           m: float) -> bool:
    """Whether a player at bearing `here` from (cx, cy) can go round its circle of `radius` by
    `turn` (radians, signed), every 5 degrees of the way (as circle_point_within_lines searches)
    having a point within the lines and outside the circle to aim at (round_reach)."""
    step = math.radians(5.0)
    bearings = [here + math.copysign(k * step, turn) for k in range(1, int(abs(turn) / step) + 1)]
    return all(round_reach(cx, cy, radius, a, m) is not None for a in [*bearings, here + turn])


def round_the_circle(cx: float, cy: float, radius: float, px: float, py: float, qx: float,
                     qy: float) -> float:
    """How far a player walks from (px, py) to (qx, qy) keeping off the circle of `radius` round
    (cx, cy), estimated from above: straight on if the straight way stays outside it; otherwise
    round it at his own distance from its centre (stepping straight out past its edge first, if he
    is inside) until the straight way on just touches it, then straight on. keep_off aims him at
    most KEEP_OFF_STEP_DEG round from where he is, so he walks a spiral in toward the circle, which
    is shorter (lesson 161; measured in tests/test_restarts.py)."""
    mx, my = px - cx, py - cy
    m = math.hypot(mx, my)
    out = 0.0
    if m < radius:  # inside: straight out first, KEEP_OFF_MARGIN_M past the edge
        reach = radius + KEEP_OFF_MARGIN_M
        mx, my = (mx / m * reach, my / m * reach) if m > 1e-6 else (reach, 0.0)
        out, m, px, py = reach - m, reach, cx + mx, cy + my
    if segment_distance(cx, cy, px, py, qx, qy) >= radius - ON_CIRCLE_M:
        return out + math.hypot(qx - px, qy - py)
    q = max(math.hypot(qx - cx, qy - cy), radius)
    turn = abs((fmath.atan2(qy - cy, qx - cx) - fmath.atan2(my, mx) + math.pi) % (2 * math.pi) - math.pi)

    def touch(d: float) -> float:  # at the centre, from d away to where a line from there touches it
        return fmath.atan2(math.sqrt(d * d - radius * radius), radius)

    arc = max(0.0, turn - touch(m) - touch(q))
    return out + m * arc + math.sqrt(m * m - radius * radius) + math.sqrt(q * q - radius * radius)


def way_in(bx: float, by: float, place: tuple[float, float], at: tuple[float, float]) -> tuple[float, float]:
    """Engine.way_into_wall for a player at `at` and his place in a wall across a kick from (bx, by)."""
    wx, wy = place
    d = math.hypot(wx - bx, wy - by)
    ux, uy = (wx - bx) / d, (wy - by) / d  # from the ball through his place
    across = abs((at[0] - wx) * -uy + (at[1] - wy) * ux)
    if across <= WALL_LANE_M:
        return wx, wy
    behind = max(shape.SHOULDER_BREADTH_M, (at[0] - wx) * ux + (at[1] - wy) * uy)
    return wx + ux * behind, wy + uy * behind


def clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


AVERAGE = decisions.AVERAGE  # an average player's attribute, for estimates about whoever ends up on the ball


def settle_s(first_touch: float) -> float:
    """The first touch settles the ball before he can decide: quicker with a good first touch
    (design)."""
    return 0.3 + 0.3 * (1 - first_touch)


def steer(p: Player, tx: float, ty: float, want_speed: float) -> None:
    """Move toward a target within the player's own body: force-velocity acceleration, braking,
    a shared grip limit for braking and turning, and energy (ninety/sim/body.py)."""
    x, y, p.vx, p.vy = move_body(p.x, p.y, p.vx, p.vy, tx, ty, want_speed, p.physique, DT)
    # No wall at the lines: players may run past them, as in real matches. Targets stay on the
    # pitch, so they slow down and come back; only the advertising boards and the goals' nets stop
    # them, and then they also stop the part of the run that goes into them.
    if not -BOARDS_M <= x <= PITCH_X + BOARDS_M:
        x, p.vx = clamp(x, -BOARDS_M, PITCH_X + BOARDS_M), 0.0
    if not -BOARDS_M <= y <= PITCH_Y + BOARDS_M:
        y, p.vy = clamp(y, -BOARDS_M, PITCH_Y + BOARDS_M), 0.0
    p.x, p.y, p.vx, p.vy = net_stop(p.x, p.y, x, y, p.vx, p.vy)


class Engine:
    def __init__(self, seed: int, strengths: dict[str, float] | None = None,
                 styles: dict[str, Style] | None = None):
        self.rng = fmath.Random(seed)
        # Perception draws from its own stream, so a change to what players see does not
        # reshuffle every other random draw in the match.
        self.sight_rng = fmath.Random(f"{seed}-perception")
        # So does a goal's celebration: how long each celebrates moves no other draw (lesson 90).
        self.celebration_rng = fmath.Random(f"{seed}-celebration")
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
        self.released_by: str | None = None  # Law 12: a keeper who released it may not handle it again
        # (x, y, strike): a carrier turning the ball onto his kicking side before he strikes it
        self.windup: tuple | None = None
        self.lunges: dict[str, float] = {}  # defender -> when his lunge reaches the ball
        self.lunge_at: dict[str, str] = {}  # defender -> the man he lunged at
        self.penalties = 0  # penalty kicks awarded (Law 14)
        self.evade_at: dict[str, float] = {}  # defender -> when the carrier reacts to his lunge
        self.off_balance: dict[str, float] = {}  # defender -> when he has recovered from a miss
        self.tackle: dict | None = None  # the tackle event whose outcome the next control decides
        self.dribbler: str | None = None  # a carrier who pushed the ball ahead and is running onto it
        self.loose_touch = False  # the dribbler's touch was a heavy first touch, not a carry
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
        # Each player's misjudgement of the ball's velocity, in units of his error at that distance
        # (PERCEPTION_ERR), held while the ball's flight is unchanged: from one strike, touch or push
        # (kicked_at, free_since) to the next; it shrinks as he nears the ball.
        self.misjudged: dict[str, tuple[float, float]] = {}
        self.misjudged_at: tuple[float, float] = (-99.0, -99.0)
        # D4: each carrier's misjudgement of his options, held until he next scans: player -> (the
        # scan it belongs to, as Belief.next_scan, option key -> draw).
        self.tastes: dict[str, tuple[float, dict]] = {}
        # O3: each attacker off the ball's offset from his place in the shape, to be open to a pass,
        # chosen when he last scanned and held until he next does; and who has scanned since.
        self.open_at: dict[str, tuple[float, float]] = {}
        self.open_due: set[str] = set()
        # O2 beyond the box: the attacker each defender in the block tracks in his zone, chosen when he
        # last scanned; and who has scanned since.
        self.track: dict[str, str | None] = {}
        self.track_due: set[str] = set()
        self.restart: Restart | None = None
        # Laws 13, 15 to 17: a restart that has been set but not yet kicked; the opponents keep off
        self.set_by: Restart | None = None
        self.celebration: Celebration | None = None  # a goal just scored: the scorers celebrate (L4)
        self.side_by_side: set[str] = set()  # this frame, who stands as close to team-mates as bodies allow
        # Laws 8, 13 to 17: who took the last restart, until another player has touched the ball
        self.restart_kicker: str | None = None
        self.throw_by: str | None = None  # a throw-in taker holding the ball until he throws it
        self.held_by: str | None = None  # Law 12: a keeper with the ball in his hands
        self.held_since = 0.0
        self.throw_ready = 0.0
        self.into_play = False  # released from behind the line; not a new out until it enters or falls away
        self.throw_from: tuple[float, float] | None = None  # where the last throw-in was taken
        self.netted: float | None = None  # the goal line whose net holds the dead ball after a goal
        self.touch_show: dict[str, tuple[str, float]] = {}  # player -> (part, until)
        self.dive_show: dict[str, tuple[float, float]] = {}  # keeper -> (until, side)
        # P18: a fouled player -> (contact t, upright t, the way his head goes, radians)
        self.fallen: dict[str, tuple[float, float, float]] = {}
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

    def reach(self, p: Player, x: float, y: float, z: float, at: float | None = None) -> tuple[float, float]:
        """How far (across the ground) this player can reach a ball at (x, y), height z, at time
        `at`, and how high he can reach at all (offball.reach_for). His arms stretch from the moment
        he reacts to the last touch, whether or not his body launches; a deflection does not
        un-stretch a dive already under way, nor pull him back out of his jump (rise_from)."""
        hands = self.hands(p, x, y)
        if not hands:
            return offball.reach_for(False, 0.0)
        at = self.t if at is None else at
        start = self.stretch_from(p)
        return offball.reach_for(True, at - start, z, at - self.rise_from(p))

    def give(self, pid: str) -> None:
        if pid != self.held_by:
            self.held_by = None
        if pid != self.restart_kicker:
            self.restart_kicker = None
        if self.team_of(pid) != self.poss_team:
            self.pressed.clear()
            self.poss_team = self.team_of(pid)
            self.open_at.clear()  # O3: a new possession: each attacker finds his space afresh
            self.track.clear()  # O2: and each defender looks afresh for a man in his zone
        self.possessor = pid
        self.last_touch = pid
        self.tastes.pop(pid, None)  # D4: a new possession is a new look at his options
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

    def kickoff(self, team: str, setup: bool = False) -> None:
        """Law 8. At the start of the match (`setup`) the teams walk out to their kick-off spots
        before the first frame. After a goal nobody is moved: they make their own way back to their
        spots after the celebration (celebrate), the ball is fetched to the centre mark
        (tick_restart), and the kick is taken once everyone stands where Law 8 puts them and the
        stoppage has run its time (L4: a minute or more after a goal, 1 to 2 s at the start)."""
        taker = next(p for p in self.players if p.team == team and p.role == "ST")
        if setup:
            for p in self.players:
                p.x, p.y = self.kickoff_spot(p, team)
                p.vx = p.vy = 0.0
            self.ball = (PITCH_X / 2, PITCH_Y / 2, 0.0, 0.0, 0.0, 0.0)
            taker.x, taker.y = PITCH_X / 2, PITCH_Y / 2
        self.possessor = None
        self.poss_team = team
        self.kicked = None
        self.new_phase()
        self.stop("kick_off", team, (PITCH_X / 2, PITCH_Y / 2), taker.id,
                  delay="kick_off" if setup else "kick_off_after_goal")

    def lined_up_for_kickoff(self, r: Restart) -> bool:
        """Law 8: everyone but the kicker in his own half, and the opponents outside the centre
        circle, until the ball is in play."""
        half, mid = PITCH_X / 2, PITCH_Y / 2
        for p in self.players:
            if p.id == r.taker:
                continue
            if (p.x - half) * attack_dir(p.team) > 0:
                return False
            if p.team != r.team and math.hypot(p.x - half, p.y - mid) < RESTART_DISTANCE_M["kick_off"]:
                return False
        return True

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
        self.end_kick(x, y)  # not received: the offside event names him
        self.offside = set()
        self.emit("offside", p.team, x, y, player=p.id)
        self.possessor = None  # the ball is dead and rolls on until the free kick is taken
        self.chase = {}
        self.stop("free_kick", other(p.team), (clamp(x, 0.5, PITCH_X - 0.5), clamp(y, 0.5, PITCH_Y - 0.5)),
                  direct=False)  # Law 11: an indirect free kick

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
        if carrier.id == self.throw_by:  # in his hands, thrown at once (Law 15)
            return True
        bx, by = self.ball[0], self.ball[1]
        if carrier.id == self.held_by:  # in a keeper's hands: to kick it he faces it, no side needed
            return abs(decisions.turn_deg(fmath.atan2(ty - by, tx - bx), carrier.heading)) <= math.degrees(
                decisions.STRIKE_FACING)
        if not decisions.can_strike(bx - carrier.x, by - carrier.y, carrier.heading, tx - bx, ty - by):
            return False
        if self.set_by:
            # A set ball lies where it was put, not settled at his feet: struck while it touches
            # his body (P11) it comes straight back off him, a second touch. Clear of him, its way
            # out never meets him while he faces within STRIKE_FACING of it (checked over the
            # pitch, tests/test_restarts.py).
            return shape.clearance(bx, by, carrier.x, carrier.y, carrier.heading) >= ball.RADIUS
        return True

    def turn_to(self, carrier: Player, tx: float, ty: float, strike) -> None:
        """He turns toward the target, no faster than a body turns (P16, tick_carrier), taking the
        ball round with him; the strike waits until he faces it (can_strike)."""
        self.windup = (tx, ty, strike, "turn")

    def kick(self, carrier: Player, vx: float, vy: float, vz: float) -> None:
        # Struck from where the ball is, against his body on the side he faces (can_strike: only
        # once he faces within STRIKE_FACING of the line). Until it has left his body he does not
        # meet it again (kicker_clear in contact).
        self.ball = (self.ball[0], self.ball[1], self.ball[2], vx, vy, vz)
        self.released_by = carrier.id
        self.last_deflection = None
        exempt = self.from_restart in NO_OFFSIDE_FROM
        # Laws 8, 13 to 17: having taken the restart he may not play it again until another
        # player has touched it (the woodwork is not a player)
        self.restart_kicker = carrier.id if self.from_restart else None
        self.from_restart = None
        self.set_by = None  # Laws 13, 16, 17: in play once it is kicked and clearly moves
        self.offside = set() if exempt else self.offside_positions(carrier)
        self.throw_by = None  # a throw-in ends when the ball is thrown
        self.held_by = None  # and a keeper's hold when he lets it go
        self.dribbler = None
        self.possessor = None
        self.last_touch = carrier.id
        self.kicked_at = self.t
        self.bumped = None
        self.free_since = self.t  # the ball left a player's control: dives are timed from here
        self.landed = None  # a new strike: a keeper still down reacts to it afresh
        self.seen_going = self.ball_destination()
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
        # Which foot: the kick's direction against the way he faces (a state; P13).
        turn = 0.0 if hands else decisions.turn_deg(fmath.atan2(vy, vx), p.heading)
        dir_sd, speed_sd, loft_sd, foot = p.profile.strike_error(skill, speed, nearest, self.fresh(p), turn)
        angle = fmath.atan2(vy, vx) + math.radians(self.rng.gauss(0, dir_sd))
        loft = fmath.atan2(vz, ground) + (math.radians(self.rng.gauss(0, loft_sd)) if vz > 0 else 0.0)
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

    def shoot(self, carrier: Player) -> None:
        team = carrier.team
        gx = goal_x(team)
        if not self.can_strike(carrier, gx, PITCH_Y / 2):
            self.turn_to(carrier, gx, PITCH_Y / 2, lambda: self.shoot(carrier))
            return
        bx, by = self.ball[0], self.ball[1]
        # The aim (which corner, how high, how hard) is a choice; missing it is execution error.
        side = self.rng.choice([-1, 1])
        ty = PITCH_Y / 2 + side * self.rng.uniform(*SHOT_AIM_OFF_M)
        tz = self.rng.uniform(*offball.SHOT_AIM_Z_M)
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
                pace: float = decisions.ARRIVE_MPS, receiver: str | None = None,
                hands: bool = False) -> None:
        """Kick toward a point the carrier chose (where he believes a team-mate will be, or space),
        meant for `receiver` if he chose one. `throw` is a throw-in (Law 15); `hands` a keeper's
        throw from his hands (Law 12)."""
        thrown = hands and self.held_by == carrier.id  # both hands: no kicking side, any angle (L15)
        if not thrown and not self.can_strike(carrier, tx, ty):
            self.turn_to(carrier, tx, ty,
                         lambda: self.pass_to(carrier, tx, ty, lofted, throw, pace=pace,
                                              receiver=receiver, hands=hands))
            return
        if self.held_by == carrier.id and not hands and self.ball[2] > 0.0:
            # A kick from his hands: he lets it fall (tick_carrier, under gravity) and strikes it as it
            # meets the ground (a drop kick), so it leaves from the grass as the passer's estimate
            # flies it (decisions.fly). `hands` goes by keyword: a listener's pass_to (touches.Watch)
            # must not see it as a ninth positional argument.
            self.windup = (tx, ty,
                           lambda: self.pass_to(carrier, tx, ty, lofted, throw, pace=pace,
                                                receiver=receiver, hands=hands), "drop")
            return
        if self.held_by == carrier.id and hands and not lofted and self.ball[2] > 0.0:
            # A throw along the ground is bowled: he brings the ball down in his hands to the grass
            # (tick_carrier, no faster than it came up, P6) and lets it go from there, as the passer's
            # estimate flies it (decisions.fly from the ground). Released from his chest, it dropped,
            # bounced and arrived at a third of the speed the estimate gave it.
            self.windup = (tx, ty,
                           lambda: self.pass_to(carrier, tx, ty, lofted, throw, pace=pace,
                                                receiver=receiver, hands=hands), "bowl")
            return
        bx, by = self.ball[0], self.ball[1]
        dist = math.hypot(tx - bx, ty - by)
        # Struck as the decision estimated it (decisions.py); execution error is added on top.
        if lofted:
            ground, up = decisions.loft_launch(dist)
        else:
            ground, up = decisions.launch_speed(dist, pace), 0.0
        skill = decisions.pass_skill(bx, tx, ty, lofted or throw, goal_x(carrier.team))
        vx, vy, vz = self.execute(carrier, *self.aim(bx, by, tx, ty, ground, up), skill,
                                  hands=throw or hands)
        speed = math.sqrt(vx * vx + vy * vy + vz * vz)
        # L15: his error never throws it faster than an arm can
        if hands and speed > decisions.KEEPER_THROW_MPS:
            k = decisions.KEEPER_THROW_MPS / speed
            vx, vy, vz = vx * k, vy * k, vz * k
        # Receiver, interceptor or deflector, end point and outcome are filled in when someone takes
        # the ball or it goes out; only the intended team-mate is known at the kick.
        self.pass_target = (tx, ty)
        self.kicked = self.emit("pass", carrier.team, bx, by, player=carrier.id, intended=receiver,
                                interceptor=None, deflected_by=None,
                                ball_speed_kmh=round(math.sqrt(vx * vx + vy * vy + vz * vz) * 3.6, 1))
        self.kick(carrier, vx, vy, vz)
        self.into_play = throw  # released from behind the line: not a new out while it comes in
        self.intended = receiver  # he expects it

    def release_options(self, scene: decisions.Scene):
        """L15: what a keeper with the ball in his hands can do with it, each as the passer's
        estimate values it (D1): thrown to any team-mate (rolled or lofted; how far is limited by how
        fast a ball can be thrown, decisions.KEEPER_THROW_MPS), kicked from his hands (a lofted pass
        to any team-mate, or long and away), or put down to play with his feet (the best he could do
        from them). (throw option, kick option, feet option), each None if there is none."""
        thrown = dataclasses.replace(scene, throw=True, from_hands=True)
        kicked = dataclasses.replace(scene, from_hands=True)
        throw = max((o for o in decisions.options(thrown) if o.kind == "pass"),
                    key=lambda o: o.value, default=None)
        kick = max((o for o in decisions.options(kicked) if o.kind in ("pass", "clear") and o.lofted),
                   key=lambda o: o.value, default=None)
        feet = max(decisions.options(scene), key=lambda o: o.value, default=None)
        return throw, kick, feet

    def release(self, carrier: Player, scene: decisions.Scene) -> None:
        """A keeper lets the ball go from his hands (Law 12), by whichever of release_options the
        estimate values most: a throw leaves his hands; a kick falls and is struck as it meets the
        ground; put down, it is in play at his feet. With no option at all he kicks it long up the
        middle. tick_carrier decides when (L15)."""
        throw, kick, feet = self.release_options(scene)
        best = max(((o, t) for o, t in ((throw, True), (kick, False)) if o),
                   key=lambda c: c[0].value, default=None)
        if feet and (best is None or feet.value > best[0].value):
            # Put down, it is in play at his feet: released, he may not handle it again until
            # another player has touched it (Law 12, L13), and it settles to his feet (P6).
            self.held_by = None
            self.released_by = carrier.id
            self.hold_until = self.t + settle_s(carrier.profile["first_touch"])
            return
        if best:
            o, thrown = best
            self.pass_to(carrier, *o.target, lofted=o.lofted, pace=o.pace, receiver=o.receiver,
                         hands=thrown)
        else:
            # design: long up the middle, 10 m past halfway
            self.pass_to(carrier, PITCH_X / 2 + attack_dir(carrier.team) * 10.0, PITCH_Y / 2, lofted=True)

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
        style, brain = self.styles[team], self.brains[team]
        scene = decisions.Scene(self.ball[0], self.ball[1], goal_x(team), mates, opps, keeper,
                                prof["decisions"], prof["composure"], prof["dribbling"],
                                tuple(prof.traits), risk,
                                current="dribble" if self.dribble_to else None, moving=moving,
                                absorb={m[0]: self.by_id[m[0]].profile.absorb_mps(False) for m in mates},
                                passer=prof, heading=carrier.heading, fresh=self.fresh(carrier),
                                ball_offset=(self.ball[0] - carrier.x, self.ball[1] - carrier.y),
                                progress_weight=style.progress_weight(brain.attacking_transition(self.t)),
                                loss_weight=style.loss_weight())
        return scene

    def decide(self, carrier: Player, throw: bool = False, hands: bool = False) -> None:
        """The carrier chooses from what he believes (ninety/sim/decisions.py)."""
        scene = self.scene_for(carrier)
        if hands:  # Law 12: from his hands he throws it or kicks it, never dribbles or holds past six seconds
            self.release(carrier, scene)
            return
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
        scene.set_piece = self.set_by is not None  # the set ball is played away, never carried
        scan = self.beliefs[carrier.id].next_scan  # D4: a new look at the pitch, a fresh misjudgement
        held = self.tastes.get(carrier.id)
        if held is None or held[0] != scan:
            held = self.tastes[carrier.id] = (scan, {})
        choice = decisions.choose(scene, self.rng, held[1])
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
                  delay: float = 0.0, cap: float | None = None) -> tuple[bool, float | None, float]:
        """Can he get to the ball at (bx, by, bz) `t` seconds from now, starting after `delay`?
        (reachable, gap still to close, his speed along the way); gap None if it is over his reach.
        His reach (a keeper's hands in his box), his speed along the way, and braking first if he
        is running away from it: one test for chasing a ball and for judging where play goes."""
        reach_m, reach_z = self.reach(p, bx, by, bz, at=self.t + t)
        if bz > reach_z:
            return False, None, 0.0
        return can_get_to(p.physique, bx - p.x, by - p.y, reach_m, p.vx, p.vy, t - delay, cap)

    def run_speed(self, p: Player, goals: float, x: float, y: float) -> float:
        """P17: the speed he asks for on a run to (x, y) worth `goals`, from what it costs him now."""
        return pacing.run_speed(p.physique, p.profile["stamina"], p.profile["work_rate"], self.t, goals,
                                math.hypot(x - p.x, y - p.y))

    def contest_goals(self, team: str, x: float, y: float) -> float:
        """P17: what winning (or denying them) the ball at (x, y) is worth: its threat for us there
        plus its threat for them (D9)."""
        return decisions.value(x, y, goal_x(team)) + decisions.value(x, y, goal_x(other(team)))

    def press_pace(self, p: Player) -> float:
        """T3: how hard he presses and recovers (design)."""
        return 5.0 + 2.0 * p.profile["work_rate"]

    def press_run(self, p: Player) -> tuple[float, float]:
        """P17: what pressing now is worth (goals) and the metres above critical speed it takes (the
        run to pressing distance at his pressing pace), from where play is going and when the ball is under
        control there (O8). Closing the carrier down to pressing distance while he still has it
        (his time on the ball) takes away the danger: the threat of their ball there (D9). Winning
        it needs more: reaching him before he can react to the presser and play it (D1's choice
        reaction, as a settled carrier sees him coming), then D8's race from the edge of his
        reach; that is worth the threat of ours there. So a press on a carrier near our goal is
        worth much, in midfield some, and on defenders with time and space at the back little,
        while one who has just received near his own goal with a presser on him is worth a lot."""
        tx, ty = self.play_point(p)
        controlled_at = self.ball_eta(tx, ty)  # a carrier still settling it, or a pass yet to arrive
        gap = self.brains[p.team].press_gap_m
        reach = min(gap, decisions.LUNGE_REACH_M)  # he jockeys at gap, and commits from within reach
        dx, dy = tx - p.x, ty - p.y
        d = math.hypot(dx, dy)
        along = (p.vx * dx + p.vy * dy) / (d or 1.0)
        pace = self.press_pace(p)
        closed = pacing.closes_down(p.physique.time_to_cover(max(0.0, d - gap), along, pace), controlled_at)
        in_reach = p.physique.time_to_cover(max(0.0, d - reach), along, pace)
        before_he_plays = decisions.sigmoid((controlled_at + decisions.GENERIC_REACTION_S - in_reach)
                                            / decisions.LANE_MARGIN_S)
        wins = before_he_plays * decisions.tackle_chance(reach, p.profile["tackling"])
        theirs = decisions.value(tx, ty, goal_x(other(p.team)))  # design: closing down removes all of it
        metres = pacing.metres_above(max(0.0, d - gap), pace, p.physique.cs)
        return closed * theirs + wins * decisions.value(tx, ty, goal_x(p.team)), metres

    def press_goals(self, p: Player) -> float:
        """P17: what pressing now is worth, in goals (press_run)."""
        return self.press_run(p)[0]

    def accepts_press(self, p: Player) -> bool:
        """P17: does he think pressing now is worth what it costs him?"""
        goals, metres = self.press_run(p)
        return pacing.accepts(p.physique, p.profile["stamina"], p.profile["work_rate"], self.t, goals, metres)

    def plan_chase(self) -> None:
        """Each team sends the player who thinks they can reach the ball's path first. Each player
        judges the ball's velocity with an error that grows with their distance from it. His
        misjudgement is one for each flight of the ball (drawn when the ball is struck, touched or
        pushed on, then held): it sharpens as he comes closer, because it scales with the distance,
        but it is not drawn afresh every few frames, which made two players about as near swap the
        chase back and forth and each turn away from the ball in turn (*design*: an estimate improves
        with what he sees; it does not jump at random)."""
        if all(self.t - self.reacting_since(p) < self.reaction(p) for p in self.players):
            return
        path = ball.predict(self.ball, DT, 6.0)
        # Law 9: once the whole ball is over a line it is out of play. A throw still behind the line is
        # coming in, so the chase is planned from the first point of its path on the pitch.
        start = next((k for k in range(0, len(path), 2) if not decisions.out_of_play(*path[k][:2])), None)
        if start is None:
            self.chase = {}
            return
        best: dict[str, tuple[float, str, float, float]] = {}
        for p in self.players:
            if self.kicked and p.id == self.kicked["player"] and not self.touched_since_kick:
                continue  # the kicker moves on; he does not run after his own pass or shot
            if p.id == self.restart_kicker:
                continue  # Laws 8, 13 to 17: nor after his restart until someone else has touched it
            if self.t - self.reacting_since(p) < self.reaction(p):
                continue  # has not yet reacted to this strike
            sigma = PERCEPTION_ERR * math.hypot(self.ball[0] - p.x, self.ball[1] - p.y)
            flight = (self.kicked_at, self.free_since)
            if self.misjudged_at != flight:  # a new strike, touch or push: everyone judges it afresh
                self.misjudged, self.misjudged_at = {}, flight
            if p.id not in self.misjudged:
                self.misjudged[p.id] = (self.rng.gauss(0, 1), self.rng.gauss(0, 1))
            zx, zy = self.misjudged[p.id]
            ex, ey = zx * sigma, zy * sigma
            last = None  # the last point on the pitch he could not yet reach: where he goes if none is
            for k in range(start, len(path), 2):
                t = k * DT
                bx, by, bz = path[k][0] + ex * t, path[k][1] + ey * t, path[k][2]
                if decisions.out_of_play(bx, by):
                    # Law 9: past the line, as he judges it, nobody can play it: the last point on the
                    # pitch is where he goes (it was once a point off the pitch, the path run on past it).
                    if last is not None and (p.team not in best or last[0] < best[p.team][0]):
                        best[p.team] = last
                    break
                # Judged at the speed he would chase it to there at (P17); a keeper is not priced.
                goals = self.contest_goals(p.team, bx, by)
                cap = None if p.role == "GK" else self.run_speed(p, goals, bx, by)
                reachable, gap, along = self.can_reach(p, bx, by, bz, t, cap=cap)
                if gap is None:
                    continue  # over his reach
                if reachable or k + 2 >= len(path):
                    arrive = t if reachable else p.physique.time_to_cover(gap, along, cap)
                    if p.team not in best or arrive < best[p.team][0]:
                        best[p.team] = (arrive, p.id, bx, by)
                    break
                last = (p.physique.time_to_cover(gap, along, cap), p.id, bx, by)
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
            reach_m, reach_z = self.reach(p, x0 + sc * dx, y0 + sc * dy, hz + sc * (z1 - hz))
            reacted = self.t - self.reacting_since(p) >= self.reaction(p)
            # On course into his body: its path crosses his outline (P11), not beside him or a clip.
            sl = 0.0 if rseg == 0 else ((qx - x0) * rdx + (qy - y0) * rdy) / rseg
            into = shape.clearance(x0 + sl * rdx, y0 + sl * rdy, qx, qy, p.heading) <= 0
            if reacted and p.id != self.restart_kicker:  # a deliberate touch, first chance
                st = first_low_within(x0, y0, hz, rdx, rdy, z1 - hz, qx, qy, reach_m, reach_z)
                if st is not None:
                    tx, ty, tz = x0 + st * dx, y0 + st * dy, hz + st * (z1 - hz)
                    # Into his body above a foot, it is a thigh, chest or head (A4); beside him,
                    # within his reach (P14), a raised foot at its full first touch (design,
                    # firsttouch.py).
                    high = into and tz > BODY_TOUCH_Z and not self.hands(p, tx, ty)
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
            if bz <= BODY_HEIGHT and closing > 0:
                # Above a foot, a player who has reacted gets a thigh, chest or head to it (A4); a
                # ball he has not reacted to just rebounds off him.
                # Only a ball on course into his body (its path crosses the outline), not a clip of it.
                aerial = (reacted and into and bz > BODY_TOUCH_Z and p.id != self.restart_kicker
                          and not self.hands(p, ux + sb * mx, uy + sb * my))
                hits.append((sb, "touch" if aerial else "body", p, ux + sb * mx, uy + sb * my, bz,
                             qx + sb * mx, qy + sb * my, aerial))
        if not hits:
            return
        s, kind, p, cx, cy, cz, px, py, aerial = min(hits, key=lambda h: h[0])  # whoever it meets first
        if kind == "touch":
            self._show_touch(p, cx, cy, cz, aerial)
        vx, vy, vz = self.ball[3], self.ball[4], self.ball[5]
        rel = relative_speed(vx, vy, vz, p.vx, p.vy)
        hands = self.hands(p, cx, cy)
        absorb = foot = p.profile.absorb_mps(hands)
        if aerial:  # a thigh, chest or head kills its own share of what a foot does (A4)
            absorb = firsttouch.surface_absorb(foot, cz)
        sent = None  # a cushioned touch: the ball's velocity as it leaves him (firsttouch.py, A4)
        worse = 1.0
        if kind == "touch" and not hands:  # what makes this touch worse takes from the cushion (A4)
            worse = self.touch_worse(p, rel, foot)
            absorb /= worse
        if kind == "touch" and hands:  # a keeper holds what his hands can, or it beats them
            controls = rel <= absorb
        elif kind == "touch" and not firsttouch.beaten(rel, absorb, foot):
            sent = self.cushion(p, cx, cy, firsttouch.residual(rel, absorb), cz if aerial else 0.0, worse)
            controls = firsttouch.at_feet(math.hypot(sent[0] - p.vx, sent[1] - p.vy))
        else:  # a ball he has not reacted to, or one far too fast for the surface: it rebounds
            controls = False
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
            if p.id == self.dribbler:
                self.dribbler = None
                if p.team == self.poss_team:  # back on his own touch: the dribble goes on
                    self.possessor, self.last_touch = p.id, p.id
                    self.touched_since_kick = False
                    return
                # back on a heavy first touch that won the ball from the other side: his now
            if self.dribbler and p.team != self.team_of(self.dribbler) and not self.loose_touch:  # a tackle
                self.emit("tackle", p.team, cx, cy, player=p.id, receiver=self.dribbler, outcome="success")
            if p.team != self.poss_team:
                self.emit("possession_change", p.team, cx, cy, player=p.id)
            self.give(p.id)
            if kind == "touch" and hands and self.held_by != p.id:  # Law 12: caught, in his hands
                self.held_by, self.held_since = p.id, self.t
            return
        left = (1.0 - s) * dt
        if sent is not None:  # a heavy touch: free until he is back on it (D6), the race decides
            start = self.heavy_touch(p, cx, cy, cz, sent, (px, py, left))
        else:
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

    def touch_aim(self, p: Player, bx: float, by: float) -> float:
        """Where a player sends a cushioned touch (A4): toward the goal he attacks, the way he wants
        to go next until he has chosen (design), and away from the nearest opponent he believes is
        pressing him, by how closely (D2's zone, longer in front than behind: at full pressure the
        way out counts twice the way forward, design). Radians."""
        gx = goal_x(p.team)
        fx, fy = gx - bx, PITCH_Y / 2 - by
        n = math.hypot(fx, fy) or 1.0
        dx, dy = fx / n, fy / n
        view, worst, away = self.beliefs[p.id], 0.0, (0.0, 0.0)
        for q in self.players:
            w = view.where(q.id, self.t) if q.team != p.team else None
            if not w:
                continue
            felt = perception.pressure_from(p.x, p.y, w[0], w[1], attack_dir(p.team))
            d = math.hypot(p.x - w[0], p.y - w[1])
            if felt > worst and d > 1e-6:
                worst, away = felt, ((p.x - w[0]) / d, (p.y - w[1]) / d)
        return fmath.atan2(dy + 2 * worst * away[1], dx + 2 * worst * away[0])

    def touch_worse(self, p: Player, rel: float, foot: float) -> float:
        """firsttouch.quality for the ball as it arrives at him: where it comes from against the way
        he faces, the pressure of the nearest opponent (D2's zone, where they really are: this is the
        touch, not his picture of it), his composure, his energy (the slow store's share left, P10, as
        a kick's) and its speed relative to him."""
        rvx, rvy = self.ball[3] - p.vx, self.ball[4] - p.vy
        come = fmath.atan2(-rvy, -rvx)  # where it comes from, seen from him
        approach = decisions.turn_deg(come, p.heading)
        pressure = max((perception.pressure_from(p.x, p.y, q.x, q.y, attack_dir(p.team))
                        for q in self.players if q.team != p.team), default=0.0)
        energy = self.fresh(p)
        return firsttouch.quality(approach, pressure, p.profile["composure"], energy, rel, foot)

    def cushion(self, p: Player, cx: float, cy: float, speed: float, z: float = 0.0,
                worse: float = 1.0) -> tuple[float, float]:
        """A4: a cushioned touch sends the ball on at `speed` (relative to him, what the surface did
        not kill) toward where he chose (touch_aim), struck with his first touch's own error (A3's
        rule with first touch as the skill, wider with the speed he sends it at), times what makes
        this touch worse (`worse`, firsttouch.quality) and the surface he meets it with at height z
        (firsttouch.AIM_ERROR). Never over a line
        he can see: if it would come to rest out of play he turns it back in, the least he must.
        Returns the ball's velocity on the pitch as it leaves him."""
        # He cannot play it through himself (P11): from where he meets it, it goes no further into
        # his body than across it; a way into him becomes a touch across him, on the nearer side.
        # This holds for his aim, for each way he turns it from a line, and for the ball as struck.
        out = fmath.atan2(cy - p.y, cx - p.x)

        def across(a: float) -> float:
            off = (a - out + math.pi) % (2 * math.pi) - math.pi
            return out + math.copysign(math.pi / 2, off) if abs(off) > math.pi / 2 else a

        aim = across(self.touch_aim(p, cx, cy))
        if speed > 1e-6:
            # Pressure and fatigue are in `worse` (firsttouch.quality), not counted twice here.
            dir_sd, speed_sd, _, _ = p.profile.strike_error("first_touch", speed, math.inf, 1.0, 0.0)
            dir_sd *= worse * firsttouch.AIM_ERROR[firsttouch.surface(z)]
            speed_sd *= worse
            for k in range(13):  # 0, +15, -15, +30, ... up to 90 degrees from his aim (design)
                turn = math.radians(15.0 * ((k + 1) // 2) * (1 if k % 2 else -1))
                a = across(aim + turn)
                sent = (p.vx + speed * fmath.cos(a), p.vy + speed * fmath.sin(a))
                path = ball.predict((cx, cy, 0.0, *sent, 0.0), DT, ball.FLIGHT_BOUND_S)
                if not any(decisions.out_of_play(q[0], q[1]) for q in path):
                    aim = a
                    break
            aim = across(aim + math.radians(self.rng.gauss(0, dir_sd)))
            speed = max(0.0, speed * (1 + self.rng.gauss(0, speed_sd)))
        return p.vx + speed * fmath.cos(aim), p.vy + speed * fmath.sin(aim)

    def heavy_touch(self, p: Player, cx: float, cy: float, cz: float, sent: tuple[float, float],
                    at: tuple[float, float, float]) -> ball.State:
        """A touch that leaves the ball further than he can keep it at his feet: it runs free from
        where he met it, at the velocity he sent it (it drops from a thigh, chest or head), until he
        is back on it after TOUCH_GAP_S, as a dribbling touch does (D6). Who has it then is the race.
        Everyone else reacts to it as a new touch. It is a deflection in the data (DATA_CONTRACT: a
        heavy touch that leaves the ball free). It is a play of the ball, so offside is judged afresh
        from it (Law 11). `at` is where he was and how much of the frame is left, as for deflect; it
        leaves his surface there. Returns the ball as it left him."""
        px, py, left = at
        k = self.kicked
        if k and k["type"] == "pass" and k["team"] == p.team:
            # A team-mate played it on purpose: the pass reached him there, completed (back to the
            # passer, it was not). Losing a heavy touch afterwards is a new event, not the pass's.
            done = p.id != k["player"]
            k.update(receiver=p.id if done else None, end_x=round(cx, 2), end_y=round(cy, 2),
                     outcome="success" if done else "fail")
            self.kicked = None
        self.last_deflection = self.emit("deflection", p.team, cx, cy, player=p.id)
        self.offside = self.offside_positions(p)  # Law 11: judged when a player plays the ball
        sx, sy = shape.nearest_on_spine(cx, cy, px, py, p.heading)  # from his surface, never inside him
        n, skin = math.hypot(cx - sx, cy - sy), shape.RADIUS_M + ball.RADIUS + 0.001
        if n < skin:
            ux, uy = (cx - sx, cy - sy) if n > 1e-6 else (fmath.cos(p.heading), fmath.sin(p.heading))
            k = skin / (math.hypot(ux, uy) or 1.0)
            cx, cy = sx + ux * k, sy + uy * k
        start = (cx, cy, cz, sent[0], sent[1], 0.0)
        self.ball = ball.step(start, left) if left > 1e-9 else start
        self.possessor = None
        self.last_touch = p.id
        self.dribbler = p.id
        self.free_since = self.t
        self.kicker_clear = False
        self.kicked_at = self.t
        self.bumped = None
        self.loose_touch = True  # nobody had it: winning it back off him is no tackle
        self.plan_chase()
        return start

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
        self.kicker_clear = False
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
        if p.team != (self.team_of(self.last_touch) if self.last_touch else p.team) and controls:
            self.offside = set()  # an opponent's deliberate play: a new phase
        self.touched_since_kick = True
        if p.id != self.dribbler and self.dribbler and p.team == self.team_of(self.dribbler):
            self.dribbler = None  # a team-mate took it: the dribble is over
        if p.id != self.released_by:
            self.released_by = None
        if p.id != self.restart_kicker:
            self.restart_kicker = None  # another player has touched it: the restart taker may again
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
            elif not same_team:  # an opponent got to it first: the pass has failed
                # He won it (interceptor) or only touched it (deflected_by): a touch says nothing
                # about where the ball went next, so the two are never one field.
                kicked.update(**{"interceptor" if controls else "deflected_by": p.id},
                              end_x=round(x, 2), end_y=round(y, 2), outcome="fail")
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
        if controls:
            self.close_shot(kicked, x, y)
        # A deflection (block, parry, a team-mate's touch) leaves the shot in flight: it may still go in.

    def end_kick(self, x: float, y: float) -> None:
        """The pass or shot in flight ends where the ball is when the next thing happens to it that is
        not a touch (a touch ends it in `touched`): a tackle on it, a whistle. Its end point is then a
        point of its path (data contract C7). A pass nobody received has failed; a shot is closed as
        the touches since it was struck decide (close_shot)."""
        kicked = self.kicked
        if kicked is None:
            return
        if kicked["type"] == "pass":
            kicked.update(end_x=round(x, 2), end_y=round(y, 2), outcome="fail")
        else:
            self.close_shot(kicked, x, y)
        self.kicked = None

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
                self.bumped = None
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
            beside = -r <= bx <= PITCH_X + r  # still alongside the touchline, short of its ends
            if not inside and (not inward or not beside) and self.throw_from:
                # Law 15: it never entered the field (it went away from it, or on past the end of
                # the touchline), so the same side throws it again from there.
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
                for key in ("intended", "interceptor", "deflected_by"):  # passes only
                    struck.pop(key, None)
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
        self.netted = PITCH_X if x > PITCH_X / 2 else 0.0  # in the goal: its net holds it (in_the_net),
        self.ball, self.netted = in_the_net(self.ball, self.netted)  # from this frame on
        self.celebrate(team, scorer)
        self.kickoff(other(team))

    def celebrate(self, team: str, scorer: str | None) -> None:
        """L4 (design): the scorer runs off toward the corner flag nearest him at the end he scored at,
        and his outfield team-mates run to him; after CELEBRATION_S they walk back for the kick-off.
        An own goal has no scorer: the side's outfielder nearest the ball is the one they run to. A
        keeper who scores celebrates where he is. The team-mates gather on the side they come from
        (huddle_spot), each at his own place, never on the same spot: bodies do not pass through each
        other (P11)."""
        side = [p for p in self.players if p.team == team and p.role != "GK"]
        focus = self.by_id[scorer] if scorer else min(
            side, key=lambda p: math.hypot(p.x - self.ball[0], p.y - self.ball[1]))
        if focus.role == "GK":
            spot = (focus.x, focus.y)
        else:
            flag_y = 0.5 if focus.y < PITCH_Y / 2 else PITCH_Y - 0.5
            spot = (clamp(goal_x(team), 0.5, PITCH_X - 0.5), flag_y)
        mates = [q.id for q in side if q is not focus]
        # each team-mate stops at his own moment, so they leave him one by one, not as one body;
        # the one they celebrate goes last
        leave = {pid: self.t + self.celebration_rng.uniform(*CELEBRATION_S) for pid in mates}
        leave[focus.id] = max(leave.values())
        self.celebration = Celebration(team, focus.id, spot, leave[focus.id], mates, leave)

    def celebrating(self, p: Player) -> bool:
        c = self.celebration
        return c is not None and self.t < c.leave.get(p.id, 0.0)

    def huddle_places(self, c: Celebration) -> dict[str, tuple[float, float]]:
        """The places round the focus of the team-mates still celebrating, worked out for all of
        them from where they all are now: on an arc facing the side they come from (their mean
        bearing from him), HUDDLE_SPACING_M apart, in the order of their bearings, so no two runs
        to them cross; at most a half-circle, far enough out to hold them all and clear of his body.
        As they leave, those still there close up round him."""
        f = self.by_id[c.focus]
        mates = [self.by_id[pid] for pid in c.ring if self.t < c.leave[pid]]
        if not mates:
            return {}
        bear = {q.id: fmath.atan2(q.y - f.y, q.x - f.x) for q in mates}
        # math.fsum: one exact rounding, the same on every Python (lesson 134)
        mean = fmath.atan2(math.fsum(fmath.sin(a) for a in bear.values()),
                           math.fsum(fmath.cos(a) for a in bear.values()))
        order = sorted(bear, key=lambda pid: (bear[pid] - mean + math.pi) % (2 * math.pi))
        n = len(order)
        radius = max(n * HUDDLE_SPACING_M / math.pi, shape.SHOULDER_BREADTH_M)
        step = HUDDLE_SPACING_M / radius
        places = {}
        for k, pid in enumerate(order):
            a = mean + (k - (n - 1) / 2) * step
            places[pid] = (f.x + fmath.cos(a) * radius, f.y + fmath.sin(a) * radius)
        return places

    def huddle_spot(self, c: Celebration, p: Player) -> tuple[float, float]:
        """His place round the focus this frame (huddle_places, worked out once a frame in gather)."""
        if p.id not in c.places:
            c.places = self.huddle_places(c)
        return c.places[p.id]

    def gather(self) -> None:
        """Once a frame, before anyone moves: the places round the one they celebrate, and who is
        joining the others. A team-mate within GATHER_REACH_M of his place round a scorer (the focus
        of the spot he runs to) or in a free kick's wall stands as close to them as bodies allow
        (together)."""
        self.side_by_side = set()
        r = self.restart or self.set_by
        if r is not None:
            for pid, (x, y) in r.wall.items():
                p = self.by_id[pid]
                if math.hypot(p.x - x, p.y - y) < GATHER_REACH_M:
                    self.side_by_side.add(pid)
        c = self.celebration
        if c is None:
            return
        c.places = self.huddle_places(c)
        for pid, (x, y) in [(c.focus, c.spot), *c.places.items()]:
            p = self.by_id[pid]
            if self.celebrating(p) and math.hypot(p.x - x, p.y - y) < GATHER_REACH_M:
                self.side_by_side.add(pid)

    def together(self, p: Player, q: Player) -> bool:
        """Team-mates who mean to stand side by side keep only clear of each other's bodies, not the
        usual personal space; on the way there they keep it as ever (gather)."""
        return p.team == q.team and p.id in self.side_by_side and q.id in self.side_by_side

    def looks_at(self, p: Player) -> tuple[float, float]:
        """What a still player turns to: the ball; round a scorer, the scorer, and the scorer to
        his team-mates round him."""
        c = self.celebration
        if c is not None and p.id in self.side_by_side:
            if p.id != c.focus:
                f = self.by_id[c.focus]
                return f.x, f.y
            around = [self.by_id[pid] for pid in c.places if pid in self.side_by_side]
            if around:
                n = len(around)
                return math.fsum(q.x for q in around) / n, math.fsum(q.y for q in around) / n
        return self.ball[0], self.ball[1]

    def stop(self, kind: str, team: str, spot: tuple[float, float], taker: str | None = None,
             delay: str | None = None, direct: bool = True) -> None:
        if taker is None:
            taker = self.nearest(spot[0], spot[1], team).id
        lo, hi = RESTART_DELAY_S[delay or kind]
        self.dribbler = self.dribble_to = None  # the ball is dead: nobody is running onto a touch
        self.restart_kicker = None  # a new stoppage ends the last restart's bar
        self.restart = Restart(kind, team, spot[0], spot[1], taker, self.t + self.rng.uniform(lo, hi),
                               direct=direct)
        if kind == "free_kick" and direct:
            self.restart.wall = self.form_wall(self.restart)

    def wall_spots(self, r: Restart) -> list[tuple[float, float]]:
        """Law 13, Bray (2014): where a wall stands for a direct free kick within shooting range (the
        distance from the goal's centre, straight-line, inside which the shot is an option,
        offball.SHOT_RANGE_M, measured as decisions measures it: lesson 138). Seen from the ball it
        hides the goal from one post to WALL_COVER_PAST_CENTRE_M past the centre (Bray: p + q of a
        2p goal, q = p / 3, two thirds of it), on a line across the kick at the restart's distance
        (and KEEP_OFF_MARGIN_M). The post is the near one (design). Its width over a shoulder's
        breadth (P11), rounded down (design: a wall of whole players), is how many stand in it,
        shoulder to shoulder, the outermost covering the near post; what rounding leaves short is on
        the keeper's side (Bray's model asks about 4.5 at 22 m straight on; his keeper's four is
        "half-a-defender light" of it). Spots off the pitch are left out."""
        line = goal_x(r.team)  # the goal the kick is at
        bx, by = self.restart_ball_spot(r)
        if math.hypot(line - bx, PITCH_Y / 2 - by) >= offball.SHOT_RANGE_M:
            return []
        mid_y = PITCH_Y / 2
        near = mid_y - GOAL_HALF_WIDTH if by < mid_y else mid_y + GOAL_HALF_WIDTH
        cover = mid_y + (WALL_COVER_PAST_CENTRE_M if near < mid_y else -WALL_COVER_PAST_CENTRE_M)
        a_near = fmath.atan2(near - by, line - bx)
        sweep = (fmath.atan2(cover - by, line - bx) - a_near + math.pi) % (2 * math.pi) - math.pi
        mid = a_near + sweep / 2
        d = RESTART_DISTANCE_M["free_kick"] + KEEP_OFF_MARGIN_M
        half = abs(sweep) / 2  # under a right angle: the goal is in front of the kick
        width = 2 * d * fmath.sin(half) / fmath.cos(half)
        n = int(width / shape.SHOULDER_BREADTH_M)
        cx, cy = bx + fmath.cos(mid) * d, by + fmath.sin(mid) * d
        ux, uy = -fmath.sin(mid), fmath.cos(mid)  # across the line of the kick
        toward = 1.0 if sweep > 0 else -1.0  # along it, from the near post's line to the cover edge
        start = -toward * width / 2  # where the near post's line crosses it
        along = [start + toward * (k + 0.5) * shape.SHOULDER_BREADTH_M for k in range(n)]
        spots = [(cx + ux * a, cy + uy * a) for a in along]
        return [(x, y) for x, y in spots if 0.5 <= x <= PITCH_X - 0.5 and 0.5 <= y <= PITCH_Y - 0.5]

    def way_into_wall(self, r: Restart, p: Player) -> tuple[float, float]:
        """Where he heads for his place in the wall: first a shoulder's breadth behind it, seen
        from the ball, then, once there to within WALL_LANE_M across the line, forward into it. He
        comes in behind the others and steps up between them, never walking along the line through
        them (P11; design)."""
        return way_in(*self.restart_ball_spot(r), r.wall[p.id], (p.x, p.y))

    def walk_to_wall(self, r: Restart, at: tuple[float, float], place: tuple[float, float]) -> float:
        """How far he walks from `at` to a place in the wall, the way he goes there, estimated from
        above (round_the_circle): round the restart's keep-off circle, to where he comes in behind the
        line (way_into_wall), then up into it."""
        bx, by = self.restart_ball_spot(r)
        wx, wy = way_in(bx, by, place, at)
        clear = RESTART_DISTANCE_M[r.kind] + KEEP_OFF_MARGIN_M
        return round_the_circle(bx, by, clear, *at, wx, wy) + math.hypot(place[0] - wx, place[1] - wy)

    def form_wall(self, r: Restart) -> dict[str, tuple[float, float]]:
        """The defending side's outfielders with the shortest walks to the wall's spots stand in it
        (design), the nearest pair of player and spot first, each walk estimated the way he would go
        there (walk_to_wall: round the keep-off circle, in behind the line, up into it). They then share
        the places out so that their walks add up to the least, so no two of them could swap places
        for a shorter pair of walks (lesson 143). As walked, two coming round the same side can
        still pass each other behind the wall (lesson 161; docs/eval/restarts.md)."""
        spots = self.wall_spots(r)
        free = [p for p in self.players if p.team != r.team and p.role != "GK"]
        chosen: list[Player] = []
        places: list[tuple[float, float]] = []
        while spots and free:
            p, spot = min(((q, s) for q in free for s in spots),
                          key=lambda ps: self.walk_to_wall(r, (ps[0].x, ps[0].y), ps[1]))
            chosen.append(p)
            places.append(spot)
            free.remove(p)
            spots.remove(spot)

        def walks(order: tuple[tuple[float, float], ...]) -> float:
            return math.fsum(self.walk_to_wall(r, (p.x, p.y), s) for p, s in zip(chosen, order, strict=True))

        best = min(itertools.permutations(places), key=walks)
        return {p.id: s for p, s in zip(chosen, best, strict=True)}

    def restart_ball_spot(self, r: Restart) -> tuple[float, float]:
        """Where the ball goes for this restart: the mark for a penalty (Law 14), else where the
        restart was given, half a metre inside the lines (the corner area, Law 17)."""
        if r.kind == "penalty_kick":
            return r.x, r.y
        return clamp(r.x, 0.5, PITCH_X - 0.5), clamp(r.y, 0.5, PITCH_Y - 0.5)

    def plan_fetch(self, r: Restart) -> None:
        """Nobody places a new ball: one of the restarting side goes to get the dead one (design:
        the Laws leave it open; the Premier League's ball-kids and spare balls are not modelled).
        Whoever is nearest where it will come to rest goes, re-planned as the chase is; the one who
        just knocked it on waits for it to arrive."""
        if r.carried_by:
            r.fetcher = None
            return
        rx, ry = self.dead_ball_rest()
        rolling = math.hypot(self.ball[3], self.ball[4]) > 0.0
        side = [p for p in self.players if p.team == r.team and not (rolling and p.id == r.passed_by)]
        r.fetcher = min(side, key=lambda p: math.hypot(p.x - rx, p.y - ry)).id

    def to_boards(self, p: Player, tx: float, ty: float) -> float:
        """How far he can run toward (tx, ty) before he meets the advertising boards."""
        dx, dy = tx - p.x, ty - p.y
        d = math.hypot(dx, dy)
        if d < 1e-9:
            return math.inf
        ux, uy = dx / d, dy / d
        reach = math.inf
        for u, at, lo, hi in ((ux, p.x, -BOARDS_M, PITCH_X + BOARDS_M),
                              (uy, p.y, -BOARDS_M, PITCH_Y + BOARDS_M)):
            if u > 1e-9:
                reach = min(reach, (hi - at) / u)
            elif u < -1e-9:
                reach = min(reach, (lo - at) / u)
        return max(0.0, reach)

    def dead_ball_rest(self) -> tuple[float, float]:
        """Where the dead ball will come to rest: along its own flight (ball.predict's), or where
        the advertising boards stop it, or in a goal, where its net holds it (tick_restart)."""
        s, line = self.ball, self.netted
        for i in range(int(ball.FLIGHT_BOUND_S / DT) + 1):
            if i:
                s, line = net_step(s, ball.step(s, DT), line)
            if not (-BOARDS_M <= s[0] <= PITCH_X + BOARDS_M and -BOARDS_M <= s[1] <= PITCH_Y + BOARDS_M):
                return clamp(s[0], -BOARDS_M, PITCH_X + BOARDS_M), clamp(s[1], -BOARDS_M, PITCH_Y + BOARDS_M)
            if i and s[2] == 0 and s[5] == 0 and s[3] == 0 and s[4] == 0:
                break
        return s[0], s[1]

    def carry_dead_ball(self, r: Restart, carrier: Player) -> None:
        """The dead ball goes with him, at his feet ahead of him, round his body and no faster than
        a carried ball settles (P6); once he is at the spot it goes onto the spot (in his hands
        over his head for a throw-in, Law 15). Its velocity is the move it made."""
        bx, by, bz = self.ball[0], self.ball[1], self.ball[2]
        budget = BALL_TO_FEET * DT
        sx, sy = self.restart_ball_spot(r)
        if r.kind == "throw_in" and carrier.id == r.taker:
            stand = throw_stand(r.x, r.y)
            at_spot = math.hypot(carrier.x - stand[0], carrier.y - stand[1]) <= THROW_SPOT_M
        else:
            at_spot = carrier.id == r.taker and math.hypot(carrier.x - sx, carrier.y - sy) <= CONTROL_M
        if at_spot and r.kind == "throw_in":  # at his feet below his hands; he picks it up once he has it
            tx, ty, _ = throw_hands(carrier.x, carrier.y)
            tz = 0.0
        elif at_spot:
            tx, ty, tz = sx, sy, 0.0
        else:  # at his feet, the way he faces
            r_feet = shape.surface(0.0, 0.0, pad=ball.RADIUS)
            fx = carrier.x + fmath.cos(carrier.heading) * r_feet
            fy = carrier.y + fmath.sin(carrier.heading) * r_feet
            nx, ny, _ = self.settle(carrier, bx, by, bz, fx, fy, carrier.heading, budget)
            nz = max(0.0, bz - budget)
            self.ball = (nx, ny, nz, (nx - bx) / DT, (ny - by) / DT, (nz - bz) / DT)
            return
        d = math.dist((bx, by, bz), (tx, ty, tz))
        k = 1.0 if d <= budget else budget / d
        nx, ny, nz = bx + (tx - bx) * k, by + (ty - by) * k, bz + (tz - bz) * k
        self.ball = (nx, ny, nz, (nx - bx) / DT, (ny - by) / DT, (nz - bz) / DT)

    def tick_restart(self) -> None:
        r = self.restart
        carrier = self.by_id[r.carried_by] if r.carried_by else None
        if carrier:
            before = self.ball
            self.carry_dead_ball(r, carrier)
            self.ball, self.netted = net_step(before, self.ball, self.netted)  # out of a goal, it is free
        else:
            # The dead ball rolls on until it stops or reaches the advertising boards, or, in a
            # goal, its net holds it.
            (bx, by, bz, vx, vy, vz), self.netted = net_step(self.ball, ball.step(self.ball, DT), self.netted)
            if not (-BOARDS_M <= bx <= PITCH_X + BOARDS_M and -BOARDS_M <= by <= PITCH_Y + BOARDS_M):
                bx, by = clamp(bx, -BOARDS_M, PITCH_X + BOARDS_M), clamp(by, -BOARDS_M, PITCH_Y + BOARDS_M)
                vx = vy = 0.0
            self.ball = (bx, by, bz, vx, vy, vz)
            if math.hypot(vx, vy) == 0.0:
                r.passed_by = None  # it has stopped: anyone may go for it again
            # One of his side within a foot's reach of it takes it (the taker first), once it is
            # on the ground: a dead ball still dropping is left to land. Nobody reaches it through
            # a goal's net (L1).
            bx, by, bz = self.ball[0], self.ball[1], self.ball[2]
            # His foot kills no more speed than a first touch does (A4); a faster ball runs on.
            if bz == 0.0 and self.ball[5] <= 0.0:
                near = [p for p in self.players if p.team == r.team and p.id != r.passed_by
                        and math.hypot(p.x - bx, p.y - by) <= CONTROL_M
                        and math.hypot(self.ball[3] - p.vx, self.ball[4] - p.vy)
                        <= p.profile.absorb_mps(False)
                        and not any(crosses((p.x, p.y), (bx, by), c, d) for c, d in NETS)]  # not through nets
                if near:
                    carrier = next((p for p in near if p.id == r.taker), near[0])
                    r.carried_by, r.passed_by, r.fetcher = carrier.id, None, None
                    r.gathered_at = self.t
                    self.ball = (bx, by, bz, carrier.vx, carrier.vy, 0.0)
        if (self.frame % CHASE_EVERY == 0 or r.fetcher is None) and not r.carried_by:
            self.plan_fetch(r)
        sx, sy = self.restart_ball_spot(r)
        bx, by = self.ball[0], self.ball[1]
        settled = carrier is not None and self.t - r.gathered_at >= settle_s(carrier.profile["first_touch"])
        if (settled and carrier.id != r.taker
                and decisions.can_strike(bx - carrier.x, by - carrier.y, carrier.heading, sx - bx, sy - by)):
            # Once he has settled it (A4) and faces the spot (P16) he knocks it along the ground
            # there, to arrive at the softest pace a pass is struck to arrive at (D1), with his own
            # error (A3), and leaves it to the taker.
            dist = math.hypot(sx - bx, sy - by)
            ground = ball.ground_pass(max(dist, 0.5), decisions.ARRIVE_MPS, DT)
            skill = decisions.pass_skill(bx, sx, sy, False, goal_x(carrier.team))
            vx, vy, vz = self.execute(carrier, *self.aim(bx, by, sx, sy, ground, 0.0), skill)
            self.ball = (bx, by, self.ball[2], vx, vy, vz)
            r.carried_by, r.passed_by = None, carrier.id
            return
        taker = self.by_id[r.taker]
        spot = throw_stand(r.x, r.y) if r.kind == "throw_in" else self.restart_ball_spot(r)
        # A thrower must be at his spot, behind the line, with the ball in his hands over his head;
        # anyone else is close enough when the ball is on the spot at his feet. Nobody and no ball
        # is moved there: he fetches it and runs (lesson 5).
        near = THROW_SPOT_M if r.kind == "throw_in" else CONTROL_M
        if self.t < r.ready_at or math.hypot(taker.x - spot[0], taker.y - spot[1]) > near:
            return
        if r.carried_by != taker.id:
            return
        if r.kind == "throw_in":
            placed = math.dist(self.ball[:3], (*throw_hands(taker.x, taker.y)[:2], 0.0)) <= 1e-6
        else:
            placed = math.dist(self.ball[:3], (*self.restart_ball_spot(r), 0.0)) <= 1e-6
        if not placed:
            return
        if math.hypot(taker.vx, taker.vy) > THROW_SETTLED_MPS:
            return  # he takes it standing, stopped within one frame of braking, not still walking in
        if r.kind == "kick_off" and not self.lined_up_for_kickoff(r):
            return
        if r.kind == "throw_in":  # Law 15: from behind the line, in both hands over his head
            # He stops within his own braking (lesson 5); he has moved this frame.
            # He turns to face the pitch as any body turns (P16, tick_carrier).
            steer(taker, taker.x, taker.y, 0.0)
            self.moved = taker.id
            spot = self.ball[0], self.ball[1]
            self.ball = (*self.ball[:3], 0.0, 0.0, 0.0)
            self.throw_from = (r.x, r.y)
        else:  # on the spot, the penalty on the mark (Law 14)
            spot = self.restart_ball_spot(r)
            self.ball = (*spot, 0.0, 0.0, 0.0, 0.0)
        self.restart = None
        self.celebration = None  # play restarts: any celebration is over
        self.set_by = r if r.kind not in ("throw_in", "penalty_kick") else None
        self.emit("kickoff" if r.kind == "kick_off" else "set_piece", r.team, *spot, player=taker.id,
                  **({} if r.kind == "kick_off" else {"outcome": None}))
        if r.team != self.poss_team:
            self.emit("possession_change", r.team, taker.x, taker.y, player=taker.id)
        self.held_by = None  # a restart is taken as its Law says, never from a keeper's hold
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

    # ---- tick ---------------------------------------------------------------

    def pass_arrives_in(self) -> float:
        """O8: how soon the ball in flight is level with where the pass was meant, by its own flight
        (ball.predict, the engine's physics): the first point of its path as far along the pass as
        the target, or, if it stops short, when it comes to rest."""
        sx, sy = self.kicked["x"], self.kicked["y"]
        tx, ty = self.pass_target
        ux, uy = tx - sx, ty - sy
        reach = ux * ux + uy * uy
        path = ball.predict(self.ball, DT, ball.FLIGHT_BOUND_S)
        level = (k for k, q in enumerate(path) if (q[0] - sx) * ux + (q[1] - sy) * uy >= reach)
        return next(level, len(path) - 1) * DT

    def passing_to_target(self) -> bool:
        """A pass is on its way to where it was meant: struck, not deflected, short of its target."""
        k = self.kicked
        if not (k and k["type"] == "pass" and self.pass_target and not self.last_deflection):
            return False
        sx, sy = k["x"], k["y"]
        tx, ty = self.pass_target
        bx, by = self.ball[0], self.ball[1]
        return (bx - sx) * (tx - sx) + (by - sy) * (ty - sy) < fmath.ipow(tx - sx, 2) + fmath.ipow(ty - sy, 2)

    def play_point(self, p: Player | None = None, team: str | None = None) -> tuple[float, float]:
        """Where play is, for setting shape (O8): once a pass is struck, players set up for where
        it is going rather than chasing the ball's every metre in flight. Only the passer and the
        team-mate he played it to know where he meant it; everyone else must first react to the
        struck ball (until then play is where it was struck), then goes by where they see it going
        (its own path). A team brain (`team`) of the passing side knows where it was meant; the
        other side's reacts like an average player."""
        bx, by = self.ball[0], self.ball[1]
        if self.passing_to_target():
            sx, sy = self.kicked["x"], self.kicked["y"]
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

    def open_spot(self, p: Player, slot: tuple[float, float], onside: float) -> tuple[float, float]:
        """O3: his place in the shape, moved to where a pass from the carrier is worth most, as he
        last saw it (decisions.open_spot), every opponent he believes is near counted, the keeper
        too. He looks again only when he scans (P13), so between scans he keeps his offset and moves
        with the shape; but an offset the play has made illegal (offside as he sees it, off the
        pitch, out of range, or nearer the carrier as he sees him now: decisions.open_legal) is
        dropped at once, and he goes back to his place until he next scans."""
        carrier = self.by_id.get(self.possessor) if self.possessor else None
        mates = carrier is not None and carrier.team == p.team
        view = self.beliefs[p.id]
        at = (view.where(carrier.id, self.t) or (carrier.x, carrier.y)) if mates else None
        if p.id in self.open_due and mates:
            self.open_due.discard(p.id)
            defenders = [w for w in (view.where(q.id, self.t) for q in self.players if q.team != p.team) if w]
            self.open_at[p.id] = decisions.open_spot(slot, self.open_at.get(p.id, (0.0, 0.0)), at,
                                                     defenders, onside, goal_x(p.team))
        offset = self.open_at.get(p.id, (0.0, 0.0))
        if offset != (0.0, 0.0) and not decisions.open_legal(slot, offset, at, onside, goal_x(p.team)):
            offset = self.open_at[p.id] = (0.0, 0.0)
        dx, dy = offset
        return clamp(slot[0] + dx, 0.5, PITCH_X - 0.5), clamp(slot[1] + dy, 0.5, PITCH_Y - 0.5)

    def zone_spot(self, p: Player, slot: tuple[float, float], own_goal_x: float) -> tuple[float, float]:
        """O2 beyond the box: his place in the block, moved goal-side of the attacker he tracks in his
        zone (offball.zone_spot). He picks whom to track when he scans (P13), and follows that man as
        he sees him until he scans again. Never the carrier (the press is the presser's, P17) and
        never a man a near-goal marker has (O2), when he picks and while he follows: if his man gets
        the ball or a marker, he goes back to his place."""
        view = self.beliefs[p.id]
        marked = self.brains[p.team].marked
        if p.id in self.track_due:
            self.track_due.discard(p.id)
            attackers = {q.id: w for q in self.players if q.team != p.team and q.role != "GK"
                         and q.id != self.possessor and q.id not in marked
                         and (w := view.where(q.id, self.t))}
            self.track[p.id] = offball.zone_man(slot, attackers, self.track.get(p.id))
        man = self.track.get(p.id)
        if man is None or man == self.possessor or man in marked:
            return slot
        at = view.where(man, self.t)
        return offball.zone_spot(slot, at, own_goal_x) if at else slot

    def in_time(self, p: Player, tx: float, ty: float) -> float:
        """O8: the speed he chooses to get to (tx, ty): just enough to be there before the ball could
        be, so far from the ball he walks and near it he bursts; his body caps it."""
        return math.hypot(tx - p.x, ty - p.y) / max(self.ball_eta(tx, ty), DT)

    def shape_target(self, p: Player) -> tuple[float, float, float]:
        """Where a player off the ball wants to be, and how fast they go there."""
        chase = self.chase.get(p.team)
        if p.id in self.lunges:  # committed: straight at the ball, at what winning it is worth to him (P17)
            bx, by = self.ball[0], self.ball[1]
            return bx, by, self.run_speed(p, self.contest_goals(p.team, bx, by), bx, by)
        if self.off_balance.get(p.id, -1.0) > self.t:  # beaten: getting up, out of the play
            return p.x, p.y, SHAPE
        if p.id == self.dribbler:  # running onto his own touch, a little faster than the ball
            # He runs along its path toward where it would stop, not at a point just ahead of it:
            # steering stops on its target, so a target beside the ball keeps him behind it.
            rest = ball.predict(self.ball, DT, 6.0)[-1]
            onto = math.hypot(self.ball[3], self.ball[4]) + 1.0  # design: he closes on it at about 1 m/s
            return clamp(rest[0], 0.5, PITCH_X - 0.5), clamp(rest[1], 0.5, PITCH_Y - 0.5), onto
        # Targets stay on the pitch so players brake for the line instead of stopping dead at it.
        if chase and chase[0] == p.id:  # the loose ball his team sends him to (P17; a keeper all-out)
            goals = self.contest_goals(p.team, chase[1], chase[2])
            speed = SPRINT if p.role == "GK" else self.run_speed(p, goals, chase[1], chase[2])
            return clamp(chase[1], 0.5, PITCH_X - 0.5), clamp(chase[2], 0.5, PITCH_Y - 0.5), speed
        if p.id == self.intended and self.passing_to_target():
            # O8: the team-mate a pass is played to knows where it was meant (he expects it), so he goes
            # there to meet it, as fast as he needs to be there when it is (by the ball's own flight),
            # rather than to his place in the shape around it. Once he has reacted, a ball off its line
            # is the chase's (above).
            tx, ty = self.pass_target
            tx, ty = clamp(tx, 0.5, PITCH_X - 0.5), clamp(ty, 0.5, PITCH_Y - 0.5)
            return tx, ty, math.hypot(tx - p.x, ty - p.y) / max(self.pass_arrives_in(), DT)
        if self.read and self.read[0] == p.id and self.possessor is None and self.kicked:
            # Sideways at the depth he has set, not back toward his line: a keeper who has come out
            # to narrow the angle stays there.
            post = PITCH_Y / 2 - GOAL_HALF_WIDTH, PITCH_Y / 2 + GOAL_HALF_WIDTH
            return p.x, clamp(self.read[1], *post), SPRINT
        if self.restart and p.id == self.restart.fetcher:  # going to get the dead ball (tick_restart)
            # Short of the boards, so he can stop before them and turn back with it: a ball against
            # them is still within his foot's reach on both lines at a corner (CONTROL_M).
            clear = CONTROL_M / math.sqrt(2.0) - 0.01  # a centimetre inside his reach: precision only
            rx, ry = self.dead_ball_rest()
            rx = clamp(rx, -BOARDS_M + clear, PITCH_X + BOARDS_M - clear)
            ry = clamp(ry, -BOARDS_M + clear, PITCH_Y + BOARDS_M - clear)
            # Near the boards he goes no faster than he could stop before them, as he slows to
            # stop on any target (body.move): they are a wall, not a target he may overrun.
            # where he is running and where he means to run, whichever meets them first
            room = min(self.to_boards(p, p.x + p.vx, p.y + p.vy), self.to_boards(p, rx, ry))
            return rx, ry, min(RECOVER, stopping_speed(room))
        if self.restart and p.id == self.restart.carried_by and p.id != self.restart.taker:
            # He knocks it on to the spot from about where he took it, turning to face it first.
            sx, sy = self.restart_ball_spot(self.restart)
            d = math.hypot(sx - p.x, sy - p.y) or 1.0
            return p.x + (sx - p.x) / d * CONTROL_M, p.y + (sy - p.y) / d * CONTROL_M, DRIBBLE
        if self.restart and self.restart.kind == "penalty_kick" and p.id != self.restart.taker:
            return *self.penalty_wait_spot(p), SHAPE  # Law 14: until the ball is kicked
        c = self.celebration
        if c and self.celebrating(p):
            if p.id == c.focus:  # the scorer runs off to celebrate
                return *c.spot, RECOVER
            return *self.huddle_spot(c, p), RECOVER  # his team-mates run to their places by him
        kick_off = self.restart or self.set_by
        if kick_off and kick_off.kind == "kick_off" and p.id != kick_off.taker:
            # Law 8: in his own half until the ball is kicked, walking back (L4), faster if a walk
            # would not get him there in time for it (O8)
            kx, ky = self.kickoff_spot(p, kick_off.team)
            return kx, ky, max(WALK_MPS, self.in_time(p, kx, ky))
        if self.restart and p.id == self.restart.taker:
            r = self.restart
            # With the ball at his feet he goes no faster than he can carry it (D1).
            pace = decisions.dribble_speed(p.profile["dribbling"]) if r.carried_by == p.id else RECOVER
            if r.kind == "throw_in":
                return *throw_stand(r.x, r.y), pace
            # Behind the ball on its spot as he faces up the pitch, clear of it (SET_BALL_CLEAR_M),
            # so the set ball stays where it was put until he kicks it (Law 13: stationary; Law 14:
            # on the mark).
            sx, sy = self.restart_ball_spot(r)
            behind = SET_BALL_CLEAR_M
            return sx - attack_dir(p.team) * behind, sy, pace
        wall = self.restart or self.set_by
        if wall and p.id in wall.wall:  # Law 13: in the wall until the ball is kicked
            wx, wy = self.way_into_wall(wall, p)
            # At least a walk (L4); faster if the whole way in, round the circle and by behind the
            # line, would not get him to his place by the time the kick may be taken (R1's wait). The
            # way is estimated from above (walk_to_wall), so he is early rather than late.
            way = self.walk_to_wall(wall, (p.x, p.y), wall.wall[p.id])
            return wx, wy, max(WALK_MPS, way / max(wall.ready_at - self.t, DT))
        bx, by = self.play_point(p)  # O8: where the ball is going, once a pass is struck
        poss_team = self.team_of(self.possessor) if self.possessor else None
        shift = (clamp(bx, 0, PITCH_X) - PITCH_X / 2) * 0.45
        push = 6 * attack_dir(p.team) if poss_team == p.team else -4 * attack_dir(p.team)
        tx = clamp(p.ax + shift + push, 2, PITCH_X - 2) if p.role != "GK" else p.ax
        ty = p.ay + (clamp(by, 0, PITCH_Y) - p.ay) * 0.25
        brain = self.brains[p.team]
        own_goal = PITCH_X - goal_x(p.team)
        work = self.press_pace(p)  # how hard he presses and recovers
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
            run = self.run_target(p, carrier, brain)
            if run:  # a run in behind: worth the threat it adds if the ball reaches him there (P17)
                gain = decisions.value(*run, goal_x(p.team)) - decisions.value(*self.ball[:2], goal_x(p.team))
                return *run, self.run_speed(p, gain, *run)
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
                sx, sy = offball.support_spot((p.x, p.y), (carrier.x, carrier.y), goal_x(p.team),
                                              (presser.x, presser.y))
                return sx, sy, self.in_time(p, sx, sy)
        if brain.in_possession and p.role != "GK":  # O6: the team's shape with the ball (also in flight)
            seen = [w for w in (self.beliefs[p.id].where(q.id, self.t) for q in self.players
                                if q.team != p.team) if w]
            onside = self.onside_limit(p.team, seen, bx)  # L10: as far as he sees he may go
            wide = offball.STAYS_WIDE_M if "stays_wide" in p.profile.traits else 0.0
            spot = offball.attacking_slot(p.role, PITCH_X - goal_x(p.team), clamp(bx, 0, PITCH_X),
                                          clamp(by, 0, PITCH_Y), onside, wide)
            if spot:
                spot = self.open_spot(p, spot, onside)
                return *spot, self.in_time(p, *spot)
        if not brain.in_possession and p.role != "GK":
            own = PITCH_X - goal_x(p.team), PITCH_Y / 2
            d = math.hypot(own[0] - bx, own[1] - by) or 1.0
            gx, gy = (own[0] - bx) / d, (own[1] - by) / d  # from the ball toward our goal

            def on_pitch(x: float, y: float) -> tuple[float, float]:
                return clamp(x, 0.5, PITCH_X - 0.5), clamp(y, 0.5, PITCH_Y - 0.5)

            gap = brain.press_gap_m  # how tight the style presses (pressing intensity)
            given = self.restart or self.set_by
            if given and given.team != p.team:  # Laws 13 to 17: stand off the restart until it is in play
                gap = RESTART_DISTANCE_M[given.kind]
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
                px, py = on_pitch(bx + lead_x + gx * gap, by + lead_y + gy * gap)
                # Until a restart's ball is in play there is nobody to press: standing where the Laws
                # let him (stand_off), he goes to where he stands off it in time for the kick, as the
                # cover does, not at his pressing pace; at it, knocked a few centimetres off his
                # place by a team-mate's bending round him, he sprang back and forth twice a second.
                # From inside the distance he must keep he still leaves at it: in time is for the
                # ball reaching his place, and the Laws want him out by the kick (lesson 174).
                legal = self.stand_off(p, p.x, p.y)[0] == (p.x, p.y)
                return px, py, self.in_time(p, px, py) if given and legal else work
            if engaged and brain.pressers[1:2] == [p.id]:  # cover: behind the presser, goal-side
                behind = max(COVER_BEHIND_M, gap + 2)
                cx, cy = on_pitch(bx + gx * behind, by + gy * behind)
                return cx, cy, self.in_time(p, cx, cy)
            slot = brain.slot(p.role, p.ay, clamp(by, 0, PITCH_Y))
            if slot:
                # O2: the defence and midfield track men in their zones; the forwards wait at their
                # line of engagement, never past the ball (T3).
                tx, ty = self.zone_spot(p, slot, own[0]) if ROLE_LINE.get(p.role) != "attack" else slot
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
                scanned = perception.observe(
                    self.beliefs[p.id],
                    (p.x, p.y, p.heading),
                    others,
                    self.t,
                    self.sight_rng,
                    p.profile.view_half_angle(),
                    p.profile.scan_interval(),
                )
                if scanned:
                    self.open_due.add(p.id)  # O3: he may look again for space to be open in
                    self.track_due.add(p.id)  # O2: and for a man in his zone
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
            given = self.restart or self.set_by
            if holder != team and given is not None:
                # Until a restart's ball is in play, the side keeps the presser and cover it named when
                # the restart was given (design). Asked again at every look, the order by time to the
                # ball moved with the very walks the two roles sent them on, and two players swapped
                # roles at every look, out and back through the whole wait; asked again as the taker
                # stood over the ball, the cover was named to press and ran in from his place 11 m off
                # (lesson 174). With a wall up (Law 13), the wall is the side's block and nobody else is
                # named to press until the ball is in play (design): a presser's place, goal-side at the
                # Laws' distance, is where the wall stands, and named to it he was pushed in and out of
                # the Laws' distance by the wall's players.
                if given.pressers is None:
                    given.pressers = [] if given.wall else self.who_presses(brain)
                brain.pressers = given.pressers
            elif holder != team:
                brain.pressers = self.who_presses(brain)
            if holder != team:  # O2: pick up the attackers who threaten our goal
                free = {
                    p.id: (p.x, p.y)
                    for p in self.players
                    if p.team == team and p.role != "GK" and p.id not in brain.pressers
                }
                seen, own_goal = self.shared_view(team, other(team)), PITCH_X - goal_x(team)
                if given is None:
                    pairs = offball.pick_up(free, seen, own_goal)
                    brain.markers = offball.marking(free, seen, own_goal, pairs)
                else:
                    # Until a restart's ball is in play each marker keeps his man (design). Picked up
                    # again at every look, from noisy sightings and from where the markers' own walks
                    # had taken them, men changed markers at every look, and the markers walked out
                    # and back through the wait. Those in the wall stand in it, and the taker is faced
                    # by the wall or the presser: marked goal-side, his marker's place was the wall's
                    # own (lesson 174).
                    free = {pid: at for pid, at in free.items() if pid not in given.wall}
                    seen = {pid: at for pid, at in seen.items() if pid != given.taker}
                    pairs = given.marks = offball.pick_up(free, seen, own_goal, keep=given.marks)
                    brain.markers = {did: offball.goal_side(seen[aid], own_goal)
                                     for did, aid in given.marks.items()}
                brain.marked = set(pairs.values())
            else:
                brain.markers, brain.marked = {}, set()

    def who_presses(self, brain: TeamBrain) -> list[str]:
        """T3, P17: the brain asks its players in the order they could reach the ball; the first
        who thinks pressing now is worth what it costs him goes, the next in that order covers."""
        for i, pid in enumerate(brain.ranked):
            if self.accepts_press(self.by_id[pid]):
                return brain.ranked[i:i + 2]
        return []

    def run_target(self, p: Player, carrier: Player, brain: TeamBrain) -> tuple[float, float] | None:
        """O4: forwards (and anyone who likes to) run in behind when the carrier has the ball
        under control, facing forward and not pressed, while they are onside."""
        if p.id in self.runs:
            x, y, started = self.runs[p.id]
            if self.t - started < 3.0:
                return x, y
            del self.runs[p.id]
        likes = "runs_in_behind" in p.profile.traits
        # A high counter-attacking style (T4) also sends the central midfielders forward while
        # the counter is on.
        countering = brain.style.level("counter_attacking") == "high" and brain.attacking_transition(self.t)
        midfielder = ROLE_LINE.get(p.role) == "midfield"
        if p.role not in ("ST", "RW", "LW") and not likes and not (countering and midfielder):
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
        # a goal's net stops a dive as it stops a run (net_stop)
        x, stop_y, p.vx, p.vy = net_stop(p.x, p.y, p.x + p.vx * DT, y, p.vx, (y - p.y) / DT)
        p.x, p.y = x, stop_y
        if landing:
            p.vy = carried if stop_y == y else 0.0
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
            place = self.stand_off(p, tx, ty)[0]
            kx, ky = self.keep_off(p, tx, ty)
            if (kx, ky) != (tx, ty):
                tx, ty, top = kx, ky, max(top, self.in_time(p, kx, ky))
            tx, ty = self.round_the_net(p, tx, ty)
            top = self.restart_pace(p, tx, ty, top, place)
            dist = math.hypot(tx - p.x, ty - p.y)
            if dist > 1e-6:  # bend the running direction away from anyone about to be in the way
                ax, ay = self.avoid(p)
                ux, uy = (tx - p.x) / dist + ax, (ty - p.y) / dist + ay
                u = math.hypot(ux, uy) or 1.0
                tx, ty = p.x + ux / u * dist, p.y + uy / u * dist
            steer(p, tx, ty, top)
            p.heading = turn_toward(p.heading, perception.facing(p.heading, p.vx, p.vy, p.x, p.y,
                                                                 *self.looks_at(p)))
        self.separate()

    def round_the_net(self, p: Player, tx: float, ty: float) -> tuple[float, float]:
        """Nobody walks through a goal's net (Law 1, NET_DEPTH_M): where his straight way would cross
        it, he heads for the first point of the shortest way that does not, by the goal mouth, in
        front of it NET_CLEAR_M, or round the goal, NET_CLEAR_M clear of its posts and back corners
        (design). The keeper fetching the ball from his net walks in through the mouth."""
        if 0.0 < min(p.x, tx) and max(p.x, tx) < PITCH_X:  # a way in front of both goal lines
            return tx, ty
        at, target = (p.x, p.y), (tx, ty)
        for line in (0.0, PITCH_X):
            net = goal_net(line)
            if not any(crosses(at, target, c, d) for c, d in net):
                continue
            out, mid, m = (1.0 if line > 0 else -1.0), PITCH_Y / 2, NET_CLEAR_M
            lo, hi = mid - GOAL_HALF_WIDTH + m, mid + GOAL_HALF_WIDTH - m
            behind = line + out * (NET_DEPTH_M + m)
            nodes = [at, (line - out * m, clamp(p.y, lo, hi)), (line - out * m, clamp(ty, lo, hi)),
                     (line, lo - 2 * m), (line, hi + 2 * m), (behind, lo - 2 * m), (behind, hi + 2 * m),
                     target]
            # shortest way from him (0) to his target (last) over ways that cross no net
            best, first, todo = {0: 0.0}, {}, {0}
            while todo:
                i = min(todo, key=best.get)
                todo.discard(i)
                for j in range(1, len(nodes)):
                    if j == i or any(crosses(nodes[i], nodes[j], c, d) for c, d in net):
                        continue
                    cost = best[i] + math.dist(nodes[i], nodes[j])
                    if cost < best.get(j, math.inf):
                        best[j], first[j] = cost, first.get(i, j)
                        todo.add(j)
            if len(nodes) - 1 in first:
                return nodes[first[len(nodes) - 1]]
        return tx, ty

    def restart_pace(self, p: Player, tx: float, ty: float, top: float,
                     place: tuple[float, float] | None = None) -> float:
        """How fast a player goes on his way to (tx, ty) while a restart waits to be taken. His place
        is where he will stand, kept off the restart (stand_off); by default the end of his way. If
        it is more than SETTLE_M off, or he is still walking in to it, or his way goes round or out of
        the keep-off circle (keep_off), he goes at no less than a normal walking pace (L4), so he gets
        there and stands there rather than creeping in over the whole wait (R1's). Walking in is
        closing on it: one kept off his place by another standing on it, going round him, slows to his
        own pace rather than circling him at a walk. Once he is at his place with the ball set
        (ball_set), he has settled: a later shift of his place within SHUFFLE_M, as it moves with what
        he sees and whom he marks, he makes at his own pace, rather than walking every jump of it out
        and back; further, he walks to it again and settles there. The one fetching the ball keeps
        his own pace: near the boards it is what he can stop in (lesson 174). Who has settled is kept
        on the restart."""
        r = self.restart
        if r is None or p.id == r.fetcher:
            return top
        px, py = place if place is not None else (tx, ty)
        off = math.hypot(px - p.x, py - p.y)
        if p.id in r.settled:
            if off <= SHUFFLE_M:
                return top
            r.settled.discard(p.id)
        way = math.hypot(tx - p.x, ty - p.y)
        closing = ((tx - p.x) * p.vx + (ty - p.y) * p.vy) / way if way > 0.0 else 0.0
        if off > SETTLE_M or closing > CLOSING_MPS or (px, py) != (tx, ty):
            return max(top, WALK_MPS)
        if self.ball_set(r):
            r.settled.add(p.id)
        return top

    def ball_set(self, r: Restart) -> bool:
        """A restart's ball is set: still on its spot (within a foot's reach of it, CONTROL_M), neither
        rolling there nor carried by any but the taker (tick_restart). From then on players' places
        no longer move with it (lesson 174)."""
        sx, sy = self.restart_ball_spot(r)
        return (math.hypot(*self.ball[3:6]) == 0.0 and r.carried_by in (None, r.taker)
                and math.hypot(self.ball[0] - sx, self.ball[1] - sy) <= CONTROL_M)

    def stand_off(self, p: Player, tx: float, ty: float) -> tuple[tuple[float, float],
                                                                  tuple[float, float, float] | None]:
        """Until a restart's ball is in play an opponent keeps the Laws' distance from it: 2 m at a
        throw-in (Law 15), 9.15 m at a free kick (Law 13) and from the corner arc at a corner (Law
        17), and out of the kicking side's penalty area at a goal kick (Law 16). His place is his
        target moved out by the shortest way, KEEP_OFF_MARGIN_M clear, as the kick-off and penalty
        spots are; those two restarts have their own spots (kickoff_spot, penalty_wait_spot). With
        it, the circle he keeps out of on his way there (its centre and radius), if there is one: his
        way is keep_off's."""
        r = self.restart or self.set_by
        if r is not None and p.team == r.team and p.id != r.taker and len(r.wall) >= 3:
            # Law 13: with three or more defenders in a wall, attackers keep 1 m from it
            # between bodies: a shoulder's breadth covers the two half-bodies side on (P11)
            clear = WALL_ATTACKER_GAP_M + shape.SHOULDER_BREADTH_M + KEEP_OFF_MARGIN_M
            for wx, wy in r.wall.values():
                d = math.hypot(tx - wx, ty - wy)
                if d < clear:
                    ux, uy = ((tx - wx) / d, (ty - wy) / d) if d > 1e-6 else (-attack_dir(p.team), 0.0)
                    tx, ty = wx + ux * clear, wy + uy * clear
            return (tx, ty), None
        if r is None or p.team == r.team or r.kind in ("kick_off", "penalty_kick"):
            return (tx, ty), None
        if r.kind == "goal_kick":
            return self.out_of_area(r.team, tx, ty), None
        if r.kind == "free_kick" and self.in_own_box(r.team, r.x, r.y):
            # Law 13: from inside its own penalty area, the opponents also stay out of the area
            tx, ty = self.out_of_area(r.team, tx, ty)
        bx, by = self.restart_ball_spot(r)
        clear = RESTART_DISTANCE_M[r.kind] + KEEP_OFF_MARGIN_M
        if r.kind == "throw_in":  # Law 15: from the point on the touchline where it is taken
            bx, by = r.x, r.y
        if r.kind == "corner":  # measured from the arc, so from the corner itself one arc further
            bx, by = r.x, r.y
            clear += CORNER_ARC_M
        tx, ty = clamp(tx, 0.5, PITCH_X - 0.5), clamp(ty, 0.5, PITCH_Y - 0.5)  # on the pitch, then out
        d = math.hypot(tx - bx, ty - by)
        if d < clear:  # his target is inside: the nearest point outside instead, on the pitch
            ux, uy = ((tx - bx) / d, (ty - by) / d) if d > 1e-6 else (-attack_dir(p.team), 0.0)
            ox, oy = tx, ty
            tx, ty = bx + ux * clear, by + uy * clear
            if not within_lines(tx, ty):  # off the pitch (a ball near a line): the nearest on it
                tx, ty = circle_point_within_lines(bx, by, clear, ox, oy) or (tx, ty)
        return (clamp(tx, 0.5, PITCH_X - 0.5), clamp(ty, 0.5, PITCH_Y - 0.5)), (bx, by, clear)

    def keep_off(self, p: Player, tx: float, ty: float) -> tuple[float, float]:
        """His way to his place kept off a restart (stand_off): round the keep-off circle, not across
        it. Inside the Laws' distance, he first steps straight out, to KEEP_OFF_MARGIN_M past the
        circle (aimed at its edge, he would stop on the edge, still inside); where straight out would
        leave the pitch (a ball near a line, he between it and the line), out by the point past it,
        on the pitch, on the shortest way to his place. While the straight way to his place would cut
        inside the circle, he aims along it, at most KEEP_OFF_STEP_DEG round from where he is, at his
        own distance, or from inside the circle's margin past it, but within the lines (round_reach):
        the short way round, or the long way where the short one would leave the pitch; if both
        would, hemmed in between the circle and the lines, he stays where he is. Going round at the
        circle's edge, each step dips into the margin, and straight out from there he would stop
        short every few strides (lesson 174). But one inside the circle whose place is within a
        stride (SETTLE_M), by a straight way that keeps the Laws' distance, as when he has stopped a
        hair short of his place on its edge, goes straight there: sent out past it, he would come back
        in to the same place and stop short again, out and back over and over. Going anywhere
        further, he aims past the margin, which takes up most of a bend round others or a step too
        far (lesson 174)."""
        (tx, ty), circle = self.stand_off(p, tx, ty)
        if circle is None:
            return tx, ty
        bx, by, clear = circle
        mx, my = p.x - bx, p.y - by
        m = math.hypot(mx, my)
        out = clear + KEEP_OFF_MARGIN_M
        out_x, out_y = (bx + mx / m * out, by + my / m * out) if m > 1e-6 else (tx, ty)
        laws = clear - KEEP_OFF_MARGIN_M  # the Laws' distance itself
        if 1e-6 < m < clear and math.hypot(tx - p.x, ty - p.y) <= SETTLE_M \
                and segment_distance(bx, by, p.x, p.y, tx, ty) >= laws:
            pass
        elif 1e-6 < m < laws:
            if not within_lines(out_x, out_y):
                way_out = circle_point_within_lines(bx, by, out, p.x, p.y, then=(tx, ty))
                out_x, out_y = way_out or (out_x, out_y)
            tx, ty = out_x, out_y
        elif m > 1e-6 and segment_distance(bx, by, p.x, p.y, tx, ty) < clear - ON_CIRCLE_M:
            here, there = fmath.atan2(my, mx), fmath.atan2(ty - by, tx - bx)
            turn = (there - here + math.pi) % (2 * math.pi) - math.pi
            ways = (turn, turn - math.copysign(2 * math.pi, turn))  # the short way round, then the long
            # From inside the margin, round and out past it: half as far round as a chord that would
            # leave his own distance along it (design), so he heads out as well as round; that chord's
            # angle is acos(m / out), here by fmath for the same result everywhere.
            if m >= clear:
                step = math.radians(KEEP_OFF_STEP_DEG)
            else:
                step = fmath.atan2(math.sqrt(out * out - m * m), m) / 2
            found = None
            for way in ways:
                if not way_round_within_lines(bx, by, clear, here, way, m):
                    continue
                a = here + clamp(way, -step, step)
                # The aim itself must be open too: from the margin it can fall between the 5-degree
                # checks, in an arc off the pitch narrower than them (lesson 174).
                reach = round_reach(bx, by, clear, a, m if m >= clear else out)
                if reach is not None:
                    found = a, reach
                    break
            if found is None:
                tx, ty = p.x, p.y
            else:
                a, reach = found
                tx, ty = bx + fmath.cos(a) * reach, by + fmath.sin(a) * reach
        return clamp(tx, 0.5, PITCH_X - 0.5), clamp(ty, 0.5, PITCH_Y - 0.5)

    def out_of_area(self, team: str, tx: float, ty: float) -> tuple[float, float]:
        """A target inside this side's penalty area moved out of it by the shorter way, up the
        pitch or wide, KEEP_OFF_MARGIN_M clear (Laws 13, 16)."""
        line = PITCH_X - goal_x(team)  # the side's own goal line
        up = attack_dir(team)  # from that line up the pitch
        depth, side = (tx - line) * up, abs(ty - PITCH_Y / 2)
        if depth > PENALTY_DEPTH or side > PENALTY_HALF_WIDTH:
            return tx, ty
        out_up = PENALTY_DEPTH + KEEP_OFF_MARGIN_M - depth
        out_side = PENALTY_HALF_WIDTH + KEEP_OFF_MARGIN_M - side
        if out_up <= out_side:
            return line + up * (PENALTY_DEPTH + KEEP_OFF_MARGIN_M), ty
        wide = 1.0 if ty >= PITCH_Y / 2 else -1.0
        return tx, PITCH_Y / 2 + wide * (PENALTY_HALF_WIDTH + KEEP_OFF_MARGIN_M)

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
            space = shape.SHOULDER_BREADTH_M if self.together(p, q) else PERSONAL_SPACE_M
            if 1e-6 < d < space:
                closeness = (space - d) / space  # 0 at the edge, 1 at contact
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
        if self.held_by == carrier.id and self.windup and self.windup[3] == "bowl":
            # a bowled throw: the ball comes down in his hands to the grass in front of him
            steer(carrier, carrier.x, carrier.y, 0.0)
            bx, by, bz = self.ball[:3]
            down = max(0.0, bz - BALL_TO_FEET * DT)
            self.ball = (bx + carrier.vx * DT, by + carrier.vy * DT, down, carrier.vx, carrier.vy,
                         (down - bz) / DT)
            if down == 0.0:
                strike, self.windup = self.windup[2], None
                self.ball = (*self.ball[:2], 0.0, 0.0, 0.0, 0.0)
                strike()
            return
        if self.held_by == carrier.id and self.windup and self.windup[3] == "drop":  # it falls from his hands
            steer(carrier, carrier.x, carrier.y, 0.0)
            bx, by, bz, _, _, bvz = self.ball
            bvz -= ball.GRAVITY * DT
            bz = max(0.0, bz + bvz * DT)
            self.ball = (bx + carrier.vx * DT, by + carrier.vy * DT, bz, carrier.vx, carrier.vy, bvz)
            if bz == 0.0:
                strike, self.windup = self.windup[2], None
                self.ball = (*self.ball[:2], 0.0, 0.0, 0.0, 0.0)
                strike()
            return
        if self.held_by == carrier.id:  # Law 12: in his hands until he throws or kicks it
            steer(carrier, carrier.x, carrier.y, 0.0)  # he stops, braking within his body (P2)
            up = 0.0 if attack_dir(carrier.team) > 0 else math.pi
            if self.windup:  # to kick it from his hands he first faces it (P16), as for any kick
                up = fmath.atan2(self.windup[1] - carrier.y, self.windup[0] - carrier.x)
            carrier.heading = turn_toward(carrier.heading, up)  # to face up the pitch (P16: no jump)
            # The ball comes up into his hands at his chest, in front of him, no faster than a carried
            # ball settles (P6), and moves with him.
            bx, by, bz = self.ball[:3]
            hx = carrier.x + fmath.cos(carrier.heading) * KEEPER_HOLD_AHEAD_M
            hy = carrier.y + fmath.sin(carrier.heading) * KEEPER_HOLD_AHEAD_M
            d = math.dist((bx, by, bz), (hx, hy, KEEPER_HOLD_Z))
            k = 1.0 if d <= BALL_TO_FEET * DT else BALL_TO_FEET * DT / d
            nx, ny, nz = bx + (hx - bx) * k, by + (hy - by) * k, bz + (KEEPER_HOLD_Z - bz) * k
            self.ball = (nx, ny, nz, (nx - bx) / DT, (ny - by) / DT, (nz - bz) / DT)
            if self.windup:
                if self.can_strike(carrier, self.windup[0], self.windup[1]):
                    strike, self.windup = self.windup[2], None
                    strike()
                return
            # L15: he waits out KEEPER_RELEASE_S. The pass estimate has no term for his team taking
            # up its places while he holds (tried: valued with his team-mates at their targets,
            # waiting never paid, and he let go within a second), and the published mean sits on
            # the law's own limit, so he does not throw or kick on the first look.
            if (self.t >= self.hold_until and k == 1.0
                    and self.t - self.held_since >= KEEPER_RELEASE_S):
                self.decide(carrier, hands=True)
            return
        if self.throw_by == carrier.id:  # Law 15: held behind the line and thrown, not dribbled
            steer(carrier, carrier.x, carrier.y, 0.0)  # standing still, braking within his body
            inward = 1.0 if carrier.y < PITCH_Y / 2 else -1.0
            carrier.heading = turn_toward(carrier.heading, inward * math.pi / 2)  # P16: no jump
            # He lifts it into both hands over his head, no faster than a carried ball settles (P6).
            bx, by, bz = self.ball[:3]
            hx, hy, hz = throw_hands(carrier.x, carrier.y)
            d = math.dist((bx, by, bz), (hx, hy, hz))
            k = 1.0 if d <= BALL_TO_FEET * DT else BALL_TO_FEET * DT / d
            nx, ny, nz = bx + (hx - bx) * k, by + (hy - by) * k, bz + (hz - bz) * k
            self.ball = (nx, ny, nz, (nx - bx) / DT, (ny - by) / DT, (nz - bz) / DT)
            # Law 15: he throws facing the field, once his body has turned to within STRIKE_FACING of
            # it (P16: the widest angle he strikes at, here from the line straight onto the field).
            facing = fmath.cos(carrier.heading - inward * math.pi / 2) >= fmath.cos(STRIKE_FACING)
            if self.t >= self.hold_until and facing and k == 1.0:
                self.decide(carrier, throw=True)
            return
        opp = other(carrier.team)
        presser = self.nearest(carrier.x, carrier.y, opp)  # who is physically there
        gap = math.hypot(presser.x - carrier.x, presser.y - carrier.y)
        if self.windup and self.set_by:
            # A set ball stays still (Law 13): he steps round it to behind its line to the target,
            # against his body as he faces it, instead of turning it onto his foot.
            # He goes round it, never through it, SET_BALL_CLEAR_M from it, at most KEEP_OFF_STEP_DEG
            # round at a time (the chord between dips 1.2 cm inside, within the ball's width spare).
            bx, by = self.ball[0], self.ball[1]
            behind = SET_BALL_CLEAR_M
            want = fmath.atan2(by - self.windup[1], bx - self.windup[0])  # away from the target
            here = fmath.atan2(carrier.y - by, carrier.x - bx)
            turn = (want - here + math.pi) % (2 * math.pi) - math.pi
            a = here + clamp(turn, -math.radians(KEEP_OFF_STEP_DEG), math.radians(KEEP_OFF_STEP_DEG))
            steer(carrier, bx + fmath.cos(a) * behind, by + fmath.sin(a) * behind, DRIBBLE)
        elif self.windup:  # turning the ball onto his kicking side
            steer(carrier, carrier.x, carrier.y, DRIBBLE)
        elif self.dribble_to:  # carrying the ball where he chose, as fast as his dribbling allows
            tx, ty = self.dribble_to
            pace = decisions.dribble_speed(carrier.profile["dribbling"])
            if self.closest_opponent(carrier) < CLOSE_CONTROL_M:
                pace *= CLOSE_CONTROL_PACE  # close control: slower, the ball never leaves his feet
            steer(carrier, tx, ty, pace)
            if math.hypot(tx - carrier.x, ty - carrier.y) < 1.0:
                self.dribble_to = None
        elif self.set_by:  # Laws 13, 16, 17: he stands over the set ball until he kicks it
            steer(carrier, carrier.x, carrier.y, 0.0)
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
        still_ball = self.set_by is not None and not self.dribble_to
        if still_ball:
            bx, by, bz = self.ball[:3]  # the set ball stays where it was put (Law 13: stationary)
        elif d > 1e-6:
            bx, by, bz = self.settle(carrier, bx, by, bz, fx, fy, side, step * math.hypot(dx, dy) / d)
            bz = bz + dz / d * step
        before = self.ball
        self.ball = (bx, by, max(bz, 0.0), *((0.0, 0.0) if still_ball else (carrier.vx, carrier.vy)), 0.0)
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
                # Law 12, 15: a ball in a keeper's hands or held for a throw-in is not his to push away
                if carrier and carrier.id in (self.held_by, self.throw_by):
                    carrier = None
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
            # Law 15: a ball held for a throw-in is not in play, so a lunge that arrives then finds nothing;
            # Law 12: nor may anyone challenge a keeper for the ball in his hands, a lunge on its way too.
            held = holder is not None and (self.throw_by == holder.id or self.held_by == holder.id
                                           or self.set_by is not None)
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
        if self.set_by:  # Laws 13, 16, 17: nor a set ball until it is kicked
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
        self.end_kick(*self.ball[:2])  # the whistle stops a pass or shot that had not arrived
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
        else:
            self.stop("free_kick", victim.team, (clamp(victim.x, 0.5, PITCH_X - 0.5),
                                                 clamp(victim.y, 0.5, PITCH_Y - 0.5)))
        self._go_down(p, victim)

    def _fall_span(self, t0: float) -> float:
        """How long he is down. The whole pose, or less so he is upright FALL_UP_BEFORE_S before
        the restart is due. The kick itself can be later, which only adds time on his feet."""
        total = FALL_S + FALL_LIE_S + FALL_RISE_S
        if self.restart is None:
            return total  # *design*: nothing is due, so the whole pose
        # *design*: a restart already inside the margin leaves no time down
        return max(0.0, min(total, self.restart.ready_at - FALL_UP_BEFORE_S - t0))

    def _go_down(self, fouler: Player, victim: Player) -> None:
        """P18: from the fouler toward the man he hit, the way the head goes. His feet stay."""
        dx, dy = victim.x - fouler.x, victim.y - fouler.y
        direction = fmath.atan2(dy, dx) if dx or dy else 0.0  # *design*: one place has no way
        self.fallen[victim.id] = (self.t, self.t + self._fall_span(self.t), direction)

    def player_fall(self, p: Player) -> tuple[float, float] | None:
        """(degrees over, direction in radians) while he is down, else nothing. The snapshot is
        this frame's t and the contact has happened, so the contact frame shows one frame of it."""
        rec = self.fallen.get(p.id)
        if rec is None:
            return None
        t0, t_end, direction = rec
        # *design*: the contact frame is already one frame into the fall
        deg = foul_fall_deg((self.t - t0) + DT, t_end - t0)
        if round(deg, 1) <= 0.0:  # *design*: a tenth of a degree; 0 is standing
            return None
        return deg, direction

    def evade(self, carrier: Player, defender: Player) -> None:
        """The carrier, having reacted to a lunge, pushes the ball away from the defender's foot,
        to the side that keeps him going forward; a better dribbler moves it quicker."""
        bx, by = self.ball[0], self.ball[1]
        angle = evade_angle(carrier.team, bx, by, defender.x, defender.y)
        speed = EVADE_MPS + 2.0 * carrier.profile["dribbling"]
        vx, vy, vz = self.execute(
            carrier, fmath.cos(angle) * speed, fmath.sin(angle) * speed, 0.0, "dribbling"
        )
        self.ball = (bx, by, self.ball[2], vx, vy, vz)
        self.possessor, self.dribbler, self.dribble_to = None, carrier.id, None
        self.held_by = None  # a ball pushed away is in nobody's hands
        self.last_touch = carrier.id
        self.free_since = self.t
        self.kicker_clear, self.touched_since_kick = False, True

    def poke(self, p: Player, holder: Player) -> None:
        """A tackle that reaches the ball knocks it loose; whoever then controls it decides the
        tackle (won or lost)."""
        self.held_by = None  # a ball knocked loose is in nobody's hands
        # A pass or shot still open ends at the tackle (C7), judged on its own flight, before the push.
        self.end_kick(self.ball[0], self.ball[1])
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
        self.kicker_clear, self.touched_since_kick = False, True
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
            kvx, kvy = fmath.cos(angle) * v, fmath.sin(angle) * v
            path = ball.predict((bx, by, 0.0, kvx, kvy, 0.0), DT, TOUCH_GAP_S)
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
        self.loose_touch = False
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
        self.kicker_clear = False
        self.touched_since_kick = True
        # Who goes for the loose ball is judged at once: a defender who has been watching the carry
        # and can get there first commits to it, rather than keep shadowing.
        self.plan_chase()
        return True

    def _show_touch(self, p: Player, cx: float, cy: float, cz: float, aerial: bool) -> None:
        """The part that met the ball (firsttouch.surface, the engine's own). A carry's own touch is
        the gait. Anything else is drawn."""
        if self.hands(p, cx, cy):
            part = "hands"
        elif aerial:
            part = firsttouch.surface(cz)
        elif self.dribbler == p.id and cz <= BODY_TOUCH_Z:
            return
        else:
            part = "foot"
        self.touch_show[p.id] = (part, self.t + TOUCH_POSE_S)

    def pose(self, p: Player) -> tuple[str, float]:
        """How this body should be drawn. Read off the match: a strike is a wind-up already
        chosen, a dive is the keeper's own dive, and a touch names the part that met the ball."""
        if self.player_fall(p) is not None:  # P18: down while the foul's fall is over 0
            return "down", 0.0
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

    def snapshot(self) -> None:
        bx, by, bz = self.ball[0], self.ball[1], self.ball[2]
        players = []
        for p in self.players:
            action, dive = self.pose(p)  # what the renderer draws (scene.py), read off the match
            row = {"id": p.id, "team": p.team, "role": p.role, "x": round(p.x, 3),
                   "y": round(p.y, 3), "vx": round(p.vx, 3), "vy": round(p.vy, 3),
                   "heading": round(p.heading, 4), "action": action, "dive": dive}
            fall = self.player_fall(p)  # x, y stay his feet; the tip is fall and fall_dir
            if fall is not None:
                deg, direction = fall
                row["fall"] = round(deg, 1)  # *design*: a tenth of a degree
                row["fall_dir"] = round(direction, 4)  # *design*: four decimals, as heading
            players.append(row)
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
        r = self.set_by
        if r and (self.possessor != r.taker
                  or math.dist(self.ball[:3], (*self.restart_ball_spot(r), 0.0)) > 1e-6):
            self.set_by = None  # it has moved (a touch on, turning it onto his foot): in play
        self.gather()
        self.move_players()
        self.snapshot()
        self.t += DT
        self.frame += 1

    def run(self, minutes: float) -> Match:
        self.kickoff("home", setup=True)
        for _ in range(int(minutes * 60 * FPS)):
            self.step()
        return self.match


def simulate(seed: int, minutes: float, strengths: dict[str, float] | None = None,
             styles: dict[str, Style] | None = None) -> Match:
    return Engine(seed, strengths, styles).run(minutes)
