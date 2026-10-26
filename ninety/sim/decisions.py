"""On-ball decisions: what the player with the ball chooses to do, from what he believes.

Each option (pass to each team-mate he has seen, shoot, dribble, hold, clear) is scored as
expected value: the chance it works, as the player judges it from his own picture of the
pitch, times the value of what follows, minus the chance it fails times the cost of losing the
ball there. A softmax picks, so better decision-makers usually take the best option and
pressured ones sometimes do not. These chances are the player's estimates for choosing; what
actually happens is decided by physics and execution error (docs/ENGINE.md, layer 6;
docs/GROUNDING.md, D rows).
"""

from __future__ import annotations

import math
import random
from bisect import bisect_left, bisect_right
from dataclasses import dataclass

from ninety.sim import ball, firsttouch, fmath, offball, perception, shape, threat
from ninety.sim import value as possession
from ninety.sim.body import (
    BODY_HEIGHT,
    BODY_RADIUS,
    CONTROL_M,
    CS_MEAN,
    F0_MEAN,
    FOOT_REACH_Z,
    STRIKE_FACING,
    TURN_RATE,
    V0_MEAN,
    Body,
    can_get_to,
    relative_speed,
)
from ninety.sim.profiles import FOOT_ABSORB_MPS, MAX_STRIKE_MPS, Profile

PITCH_X, PITCH_Y = 105.0, 68.0
GOAL_HALF_WIDTH = 3.66
PENALTY_DEPTH, PENALTY_HALF_WIDTH = 16.5, 20.16  # Law 1
DT = 1 / 25
GENERIC_REACTION_S = 0.365  # D1: how quickly the passer assumes an opponent reacts (P12)
LANE_MARGIN_S = 0.25  # D1: design: how sharply the passer's confidence falls as a lane closes
RECEIVE_MARGIN_S = 0.3  # design: how sharply a carrier's confidence falls as a defender closes on his carry
PRESSURE_FRONT_M, PRESSURE_BEHIND_M = perception.PRESSURE_FRONT_M, perception.PRESSURE_BEHIND_M  # D2
# D3: how often a shot goes in by distance from the goal's centre, for a central shot: the
# share of real shots that scored by zone (six-yard box 31%, the rest of the central box 17.7%,
# central outside the box 5.3%, long range 2.3%; American Soccer Analysis, 8,291 MLS shots, 2013).
# Distances are the zones' approximate middles (*verify*); 40 m, the end of shooting range
# (offball.SHOT_RANGE_M), is *design*, and no shot is offered beyond it, so the table ends there. A
# check, not a fit: shots from about 32 m to halfway scored 2.5% (Premier League, 929 shots) and 1.9%
# (Bundesliga, 880) in 2012-13, direct free kicks included (Rathke 2017, Table 1, zone 8). A player's
# sense of a good chance comes from what goes in, not from the open goal he sees.
SHOT_ANCHORS = ((0.0, 0.31), (3.0, 0.31), (11.0, 0.177), (20.0, 0.053), (30.0, 0.023),
                (offball.SHOT_RANGE_M, 0.01))  # the 1% at the end of range: *design*
BLOCKER_FACTOR = 0.5  # design, verify: each defender in the shooting cone blocks the shot half the time
# D3: the zone rates are averages over real shots, which usually face a defender. Relative to that
# average, a shot with no outfield defender in the triangle between the ball and the posts (the
# source's "goal-side", tested point-in-polygon) scores more and one with any a little less:
# 11.59% against 7.49%, with 23.18% of shots unscreened (Lucey et al. 2015, 9,732 shots, tracking
# data). The effect does not compound per defender (it flattens; Anzer and Bauer 2021).
_UNSCREENED, _SCREENED, _UNSCREENED_SHARE = 0.1159, 0.0749, 0.2318
_AVERAGE = _UNSCREENED_SHARE * _UNSCREENED + (1 - _UNSCREENED_SHARE) * _SCREENED
CLEAR_SHOT, SCREENED_SHOT = _UNSCREENED / _AVERAGE, _SCREENED / _AVERAGE
# D3: keepers save about 76.5% of on-target shots: 826 of 1,079 (Perez-Arroniz et al. 2025, 2,238
# La Liga shots); the typical shot behind the zone rates faces that keeper.
KEEPER_SAVES = 826 / 1079
# D4: the scale of the choice's randomness, in goals (design, verify): options much closer than this
# are a near coin-flip, options further apart than it are told apart; the decision maker's own
# factors (temperature) scale it.
CHOICE_NOISE_GOALS = 0.005
HOLD_DECAY = 0.1  # design, verify: share of the ball's worth lost per decision spent holding
STALE_S = 2.0  # design: a team-mate not seen for this long is a less certain option
# D8: the tackle race, shared by the defender deciding to commit (engine.duels) and the carrier
# judging a dribble. All *design*, *verify*.
LUNGE_REACH_M = 1.8  # a foot (1 m) plus a step
LUNGE_S = 0.3  # time for an average tackler's foot to reach the ball from the edge of that reach
DRIBBLE_STEP_M = 6.0
MAX_PASS_M = 45.0
PASS_SPEED_EST_MPS = 14.0  # design: a passer's rough guess of a pass's average speed, to lead a runner
LEAD_MAX_S = 2.0  # design: and he leads him by at most this long
LOFT_FROM_M = 15.0  # design: shorter than this, a pass is played along the ground
LOFT_DEG = 30.0  # design: the launch angle of a lofted pass or a throw, as estimated and as struck
# L15: the fastest a keeper throws the ball. Experienced handball players' overarm throw, as fast as
# they could, of a 0.409 kg ball 0.3 m round (a football weighs about 0.43 kg): 21.5 m/s (van den
# Tillaar and Ettema 2004, J Sports Sci Med 3:211-219). *verify*: a football does not fit a hand, so a
# keeper's throw is taken as no faster; no keeper-specific figure was found.
KEEPER_THROW_MPS = 21.5
# A4: the passer's guess of what a first touch can kill: an average player's (one definition, profiles).
CONTROL_EST_MPS = FOOT_ABSORB_MPS[0] + FOOT_ABSORB_MPS[1] * 0.5
CONTROL_MARGIN_MPS = 2.0  # design: how sharply that guess falls off
AVERAGE = 0.5  # an average player's attribute, for estimates about someone the passer cannot judge
GOAL_KICK_M = 5.5  # Law 16: a goal kick is taken from the goal area
# D4, A5 (design): a habit or carrying on with the current dribble is a pull toward that option of
# this many units of the player's own misjudgement (his odds of it times e^0.5, about 1.6, whoever he
# is and wherever he is): a close call, never a command and never a second rating of the option.
# Once a bonus in goals (dribbling with takes_players_on +0.01, carrying on +0.003, a short pass with
# plays_short +0.008), which a choice made in goals at his own temperature turned into an 85-fold
# preference. The pull is the one A8 creativity was given on the forward-play branch (#103).
HABIT_PULL = 0.5
SHORT_PASS_M, LONG_PASS_M = 15.0, 25.0  # plays_short: drawn to passes under this, away from those over
CLEAR_FROM = 2 / 3  # a clear is an option in his own third: this share of the pitch from the goal he attacks
CLEAR_AHEAD_M = 45.0  # design: a clearance is aimed this far up the pitch
# Design: and this far in from the touchline on his side, away from goal but far enough in to stay in
# play with his kick error (Law 9). An aim 4 m in once sent a third of clearances out; weighed by
# clear_value, the contest where it lands differs by under 0.0001 goals across the width, so only
# staying in play tells aims apart, and a search over aims would be a coin toss on a flat value.
CLEAR_IN_FROM_LINE_M = 20.0
# Demo engine v2 (design): a clearance may be aimed at a team-mate at least this far up the pitch
# from the ball (nearer, it is a pass), and no further away than the lofted strikes he can estimate
# (MAX_PASS_M, the end of the LOFT table).
CLEAR_MATE_FROM_M = 20.0
MAX_CLEAR_M = MAX_PASS_M
CLEAR_MATES = 3  # design: and only at the furthest up of them (each aim is a race to weigh)


# D7: what having the ball is worth by area, measured from the engine's own matches
# (ninety/sim/value.py). Until a table has been measured, the hand-written estimate below is used.
POSSESSION: possession.Tables | None = possession.load()


ARRIVE_MPS = 6.0  # the softest pace a ground pass is struck to arrive at
# D1: the paces a ground pass can be struck to arrive at (design); passes leave the foot at about
# 16 m/s in professional matches (tracking data, arXiv 2210.16474), so 10 to 14 m/s arrivals are normal.
PASS_PACES = (6.0, 10.0, 14.0)
# The launch speed for a ground pass to arrive at each pace, per 0.5 m of distance (0 to 45 m),
# solved once by ball physics rather than on every decision.
LAUNCH = {pace: [ball.ground_pass(max(d * 0.5, 0.5), pace, DT) for d in range(91)] for pace in PASS_PACES}


# The same for a lofted pass at LOFT_DEG: (ground speed, vertical speed) per 0.5 m.
LOFT = [ball.lofted_pass(max(d * 0.5, 0.5), LOFT_DEG, DT) for d in range(91)]


def launch_speed(distance: float, pace: float = ARRIVE_MPS) -> float:
    table = LAUNCH[pace]
    return table[min(len(table) - 1, max(0, round(distance / 0.5)))]


def loft_launch(distance: float) -> tuple[float, float]:
    return LOFT[min(len(LOFT) - 1, max(0, round(distance / 0.5)))]


def dribble_speed(dribbling: float) -> float:
    """How fast a player walks a dead ball to its spot, m/s (design)."""
    return 2.5 + 2.0 * dribbling


# D6 (demo engine v2): sprinting with the ball, professional players averaged 91% of their speed
# without it over 20 m from standing (20.37 against 22.39 km/h; Preissler et al. 2023, Sci Rep
# 13:22, doi 10.1038/s41598-022-27255-y, 33 professional female players). Here the ball caps how
# fast he runs: the cap is whatever makes an average body (P2, P9) take 20 m from standing that
# much longer with it (derived below by bisection, about 6.2 m/s, 62% of his top speed; not
# chosen). A carry once went at 2.5 to 4.5 m/s whoever carried it, so it was caught and rarely
# chosen, and looked like jogging.
WITH_BALL_SHARE = 20.37 / 22.39


def _carry_share() -> float:
    body = Body(F0_MEAN, V0_MEAN, CS_MEAN)
    target = body.time_to_cover(20.0) / WITH_BALL_SHARE
    lo, hi = 0.5, V0_MEAN
    for _ in range(50):
        mid = (lo + hi) / 2
        if body.time_to_cover(20.0, 0.0, cap=mid) > target:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2 / V0_MEAN


CARRY_SHARE = _carry_share()


def carry_speed(top: float = V0_MEAN) -> float:
    """How fast a player can carry the ball in open play, m/s, from his own top speed now (P10):
    one definition for choosing and doing."""
    return CARRY_SHARE * top


def _generic_time(distance: float) -> float:
    tau = 9.9 / 5.2
    if distance <= 0:
        return GENERIC_REACTION_S
    t = distance / 9.9 + tau
    for _ in range(8):
        f = 9.9 * t - 9.9 * tau * (1 - fmath.exp(-t / tau)) - distance
        t -= f / max(9.9 * (1 - fmath.exp(-t / tau)), 1e-6)
    return GENERIC_REACTION_S + max(t, 0.0)


GENERIC = [_generic_time(d * 0.25) for d in range(481)]  # 0 to 120 m, every 0.25 m


def generic_time(distance: float) -> float:
    """How long the passer assumes any player takes to cover a distance from standing, after
    reacting: an average body (acceleration about 5.2 m/s², top speed about 9.9 m/s)."""
    return GENERIC[min(len(GENERIC) - 1, max(0, round(distance / 0.25)))]


def sigmoid(x: float) -> float:
    return 1 / (1 + fmath.exp(-max(-30.0, min(30.0, x))))


def lunge_time(distance: float, tackling: float = 0.5) -> float:
    return LUNGE_S * (distance / LUNGE_REACH_M) * (1.4 - 0.8 * tackling)


def tackle_chance(distance: float, tackling: float = 0.5) -> float:
    """D8: the chance a defender this far from the ball wins the race to it: his lunge against an
    average carrier's choice reaction. 0 beyond his reach."""
    if distance > LUNGE_REACH_M:
        return 0.0
    return sigmoid((GENERIC_REACTION_S - lunge_time(distance, tackling)) / LANE_MARGIN_S)


@dataclass
class Scene:
    """What the player on the ball believes, in the frame of the team he plays for."""
    x: float
    y: float
    goal_x: float  # the goal he attacks
    mates: list[tuple]  # (id, x, y, seconds since seen) or with (vx, vy) as seen appended
    opponents: list[tuple[float, float]]  # believed positions
    keeper: tuple[float, float] | None  # believed opposition keeper
    decisions: float
    composure: float
    dribbling: float
    traits: tuple[str, ...]
    risk: float  # -1 protect a lead ... +1 chase the game
    # For the pass race (pass_confidence). Opponents where he believes they are now, with the
    # velocity he saw and whether he is their keeper: (x, y, vx, vy, keeper).
    moving: list[tuple[float, float, float, float, bool]]
    absorb: dict[str, float]  # team-mates' first touch (A4), by id
    passer: Profile  # who he is, for his own kick error (A3)
    throw: bool = False  # Law 15: a throw-in, so every pass is thrown (lofted) and nothing else
    # Law 12: the ball is in the keeper's hands, so he releases it without turning to a kicking
    # side (engine.release, can_strike). With throw as well, it is his throw and may roll (L15).
    # Alone, it is a drop kick.
    from_hands: bool = False
    set_piece: bool = False  # Laws 8, 13, 16, 17: a set ball, played away, never carried off
    committed: bool = False  # lesson 202: off his run-up he plays it; holding is no option (design)
    # The team's style (T4): how much ground gained from here is worth, and how much losing the
    # ball costs, against the defaults. Both 1 for a mid style.
    progress_weight: float = 1.0
    loss_weight: float = 1.0
    current: str | None = None  # what he is doing now (a dribble), for the pull of carrying on
    heading: float = 0.0  # the way he faces, radians
    fresh: float = 1.0  # his slow store's share left (P10)
    ball_offset: tuple[float, float] = (0.0, 0.0)  # the ball relative to his body
    carry_mps: float = 0.0  # how fast he can carry the ball (carry_speed); 0: an average fresh body's
    velocity: tuple[float, float] = (0.0, 0.0)  # his own, m/s

    def __post_init__(self) -> None:
        if not self.carry_mps:
            self.carry_mps = carry_speed()


@dataclass
class Option:
    kind: str  # pass | shoot | dribble | hold | clear
    value: float
    target: tuple[float, float] | None = None
    receiver: str | None = None
    lofted: bool = False
    pace: float = ARRIVE_MPS  # a ground pass's arrival speed, as chosen


def attack(goal_x: float) -> float:
    return 1.0 if goal_x > PITCH_X / 2 else -1.0


def goal_angle(x: float, y: float, goal_x: float) -> float:
    a = fmath.atan2(PITCH_Y / 2 + GOAL_HALF_WIDTH - y, abs(goal_x - x))
    b = fmath.atan2(PITCH_Y / 2 - GOAL_HALF_WIDTH - y, abs(goal_x - x))
    return abs(a - b)


def rate_at(distance: float) -> float:
    """D3: the real scoring rate of a central shot from this distance, between the anchors; none
    beyond the last (out of shooting range)."""
    for (d0, r0), (d1, r1) in zip(SHOT_ANCHORS, SHOT_ANCHORS[1:], strict=False):
        if distance <= d1:
            return r0 + (r1 - r0) * (distance - d0) / (d1 - d0)
    return 0.0


def shot_estimate(x: float, y: float, goal_x: float, opponents: list[tuple[float, float]],
                  keeper: tuple[float, float] | None) -> float:
    """The player's own estimate of a shot from here, between 0 and 1: how often shots from this
    distance go in (D3), less from a tighter angle (by how much of the goal he can see compared with
    a central shot), then compared with the typical shot those rates average over: better with no
    outfield defender he believes is in the triangle to the posts, a little worse with any; and by
    how much of the goal the keeper leaves open against a keeper in his usual spot. The keeper is
    counted once."""
    screened = any((ox, oy) != keeper and in_cone(x, y, goal_x, ox, oy) for ox, oy in opponents)
    q = typical_shot(x, y, goal_x) * (SCREENED_SHOT if screened else CLEAR_SHOT)
    if keeper:
        # The typical shot already faces a keeper in his usual spot, who saves KEEPER_SAVES of
        # what reaches him. This keeper's odds of a save scale with how much of the goal he covers
        # against the usual one (*design*: one save rate for every distance, *verify* by zone), so
        # a better-placed keeper saves more and a worse one less, but never every shot or none.
        usual = 1 - offball.open_goal_share(x, y, goal_x, offball.keeper_spot(x, y, goal_x))
        here = 1 - offball.open_goal_share(x, y, goal_x, keeper)
        ratio = here / usual if usual > 0 else 1.0  # (a usual keeper always covers something)
        odds = KEEPER_SAVES / (1 - KEEPER_SAVES) * ratio
        q *= (1 / (1 + odds)) / (1 - KEEPER_SAVES)
    return min(q, 1.0)  # a probability


def typical_shot(x: float, y: float, goal_x: float) -> float:
    """D3: how often real shots from here score, before anything about this one: the zone rate for
    the distance, less from a tighter angle (by how much of the goal he can see compared with a
    central shot)."""
    d = math.hypot(goal_x - x, PITCH_Y / 2 - y)
    central = goal_angle(goal_x - math.copysign(d, goal_x - x), PITCH_Y / 2, goal_x)
    return rate_at(d) * min(1.0, goal_angle(x, y, goal_x) / central) if central > 0 else 0.0


def in_cone(x: float, y: float, goal_x: float, ox: float, oy: float) -> bool:
    """Is (ox, oy) inside the triangle from the ball to the two posts?"""
    if (ox - x) * (goal_x - x) <= 0 or abs(ox - x) > abs(goal_x - x):
        return False
    share = abs(ox - x) / max(abs(goal_x - x), 1e-6)
    lo = y + share * (PITCH_Y / 2 - GOAL_HALF_WIDTH - y)
    hi = y + share * (PITCH_Y / 2 + GOAL_HALF_WIDTH - y)
    return lo <= oy <= hi


def closest_on_segment(px: float, py: float, ax: float, ay: float, bx: float, by: float
                       ) -> tuple[float, float]:
    """(distance from the point to the segment, share of the way along it at the closest point)."""
    dx, dy = bx - ax, by - ay
    seg = dx * dx + dy * dy
    s = 0.0 if seg == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / seg))
    return math.hypot(ax + s * dx - px, ay + s * dy - py), s


def distance_to_segment(px: float, py: float, ax: float, ay: float, bx: float, by: float) -> float:
    return closest_on_segment(px, py, ax, ay, bx, by)[0]


def value(x: float, y: float, goal_x: float, opponents: list[tuple[float, float]] = (),
          keeper: tuple[float, float] | None = None) -> float:
    """What having the ball here is worth: the chance a possession here leads to a goal. From the
    engine's own measured table if one is in use (D7), otherwise the published expected threat
    from real matches (D9). Who is in the way is judged by each option's chance of working."""
    if POSSESSION is not None:
        return POSSESSION.threat.at(x, y, goal_x)
    return threat.at(x, y, goal_x)


def our_value(scene: Scene, x: float, y: float) -> float:
    """What the player on the ball thinks having it at (x, y) is worth to his team. His team's
    style (T4: directness, counter-attacking) scales what the ball gains (or loses) in worth by
    moving from where it is now to (x, y), by the style's weight: a direct team likes the gain
    forward more and minds the loss going back more, a patient one less of both. A weight of 1
    (mid) leaves the value as it is; a weight of 0 or more never turns a loss into a gain."""
    here = value(scene.x, scene.y, scene.goal_x, scene.opponents, scene.keeper)
    there = value(x, y, scene.goal_x, scene.opponents, scene.keeper)
    return there + (scene.progress_weight - 1) * (there - here)


def our_loss(scene: Scene, x: float, y: float) -> float:
    """What the player on the ball thinks losing it at (x, y) costs, as his team's style fears it
    (T4: risk). What it is worth to the opponents is theirs, so it is not style-weighted."""
    return loss_cost(x, y, scene.goal_x) * scene.loss_weight


def loss_cost(x: float, y: float, goal_x: float) -> float:
    """What losing the ball here costs: what having it here is worth to the opponents."""
    own_goal = PITCH_X - goal_x
    return value(x, y, own_goal)


def pressure(scene: Scene) -> float:
    """0 to 1: how closely the nearest opponent presses, judged in a zone longer in front of the
    player (toward the goal he attacks) than behind him."""
    sign = attack(scene.goal_x)
    return max((perception.pressure_from(scene.x, scene.y, ox, oy, sign) for ox, oy in scene.opponents),
               default=0.0)


def turn_deg(direction: float, heading: float) -> float:
    """How far (degrees, -180 to 180) a kick's direction is from the way the kicker faces."""
    return math.degrees((direction - heading + math.pi) % (2 * math.pi) - math.pi)


def faces(heading: float, dx: float, dy: float) -> bool:
    """P16: does he face within STRIKE_FACING of the way (dx, dy)? One rule for every kick, from his
    feet (can_strike) or from a keeper's hands (engine.can_strike)."""
    return abs(turn_deg(fmath.atan2(dy, dx), heading)) <= math.degrees(STRIKE_FACING)


def can_strike(ox: float, oy: float, heading: float, dx: float, dy: float) -> bool:
    """P16, the engine's own rule: with the ball at (ox, oy) from his body's centre and facing
    `heading`, can he strike it toward (dx, dy) now? Only once he faces within STRIKE_FACING of it
    (the widest run-up angle tested with no loss of speed or accuracy) with the ball on the side
    of his body toward it, so its way out leaves his surface (shape.py) rather than passing
    through him. A throw-in is the engine's own case (engine.can_strike: in his hands)."""
    if not faces(heading, dx, dy):
        return False
    sx, sy = shape.nearest_on_spine(ox, oy, 0.0, 0.0, heading)
    return (ox - sx) * dx + (oy - sy) * dy >= 0


def strike_turn(heading: float, dx: float, dy: float, thrown: bool = False) -> tuple[float, float]:
    """P16: how far (degrees) the kick toward (dx, dy) is from the way he faces when he strikes it,
    and how long he turns first (seconds). Facing within STRIKE_FACING he strikes now; else he
    turns toward it at TURN_RATE until he is, and strikes at that angle. A throw-in leaves his hands
    at once, at whatever angle (can_strike). *Design*, not counted: a ball behind him also comes
    round to his front within a few frames; the engine turns in whole frames, so it strikes up to
    one frame later and up to 14° nearer his facing; and he does not move while he turns, though in
    the engine he brakes and the ball goes with him."""
    off = turn_deg(fmath.atan2(dy, dx), heading)
    limit = math.degrees(STRIKE_FACING)
    if thrown or abs(off) <= limit:
        return off, 0.0
    return math.copysign(limit, off), math.radians(abs(off) - limit) / TURN_RATE


def pass_skill(bx: float, tx: float, ty: float, lofted: bool, goal_x: float) -> str:
    """A3: a ball in the air from a wide position toward the goal he attacks is a cross."""
    wide = abs(ty - PITCH_Y / 2) > 20 and (tx - bx) * attack(goal_x) > 0
    return "crossing" if lofted and wide else "passing"


def struck_speed(speed: float, error: float, foot: float) -> float:
    """A3: the speed a kick meant at `speed` comes off the foot with a speed error `error` (a share)
    and the foot's share of his usual speed. A mishit can carry almost nothing (the 0.3 floor:
    design); no strike exceeds a foot's limit."""
    return min(speed * (max(0.3, 1 + error) * foot), MAX_STRIKE_MPS)


# D1: the pass race. The passer runs, on his own picture of the pitch, the race the engine runs for a
# free ball (engine.plan_chase, engine.contact): whoever first gets a foot (a keeper in his own box,
# his hands) to the ball's path after reacting to the strike takes it, so only the first team-mate
# there matters, and an opponent counts only if he gets there before that team-mate. The race uses an
# average body (P2, P9, P10) and average reactions (P12); the team-mate it is played to expects it.
AVERAGE_BODY = Body(F0_MEAN, V0_MEAN, CS_MEAN)
_TOP = V0_MEAN  # a fresh average body's top speed


def _furthest(run: float, speed: float) -> float:
    """An upper bound on how far an average body already going at `speed` can run in `run`
    seconds: never faster than his top speed, never accelerating faster than from standing
    (body.distance_in is below both), so the race can skip a point cheaply before the exact test."""
    return min(_TOP * run, speed * run + 0.5 * F0_MEAN * run * run)


_GAP_STEP, _SPEED_STEP = 0.25, 0.5  # the grid of the table below, metres and m/s
_SLACK_S = 1e-3  # ten times the solver's tolerance (body.time_to_cover), so a bound stays a bound
_COVER = [[max(0.0, AVERAGE_BODY.time_to_cover(g * _GAP_STEP, u * _SPEED_STEP) - _SLACK_S)
           for u in range(int(_TOP / _SPEED_STEP) + 1)] for g in range(int(120 / _GAP_STEP) + 1)]


def _soonest(gap: float, speed: float) -> float:
    """A lower bound on the seconds an average body going at `speed` needs to cover `gap`: his exact
    time (body.time_to_cover, solved once on a grid) for the grid's gap just below and speed just
    above, since the time grows with the gap and falls with the speed along the way; never above
    his time running flat out from the start (gap / top speed) beyond the grid; less a millisecond,
    below the solver's tolerance."""
    if gap <= 0:
        return 0.0
    g = int(gap / _GAP_STEP)
    if g >= len(_COVER):
        return gap / _TOP
    u = min(len(_COVER[0]) - 1, math.ceil(speed / _SPEED_STEP))
    return _COVER[g][u]


# The race follows the ball's whole flight from the strike, until it rests (bounded by
# ball.FLIGHT_BOUND_S, as engine.ball_destination is): the engine's chase looks only 6 s ahead, but
# re-plans every few frames from wherever the ball is, so over a pass it follows it as far.
RACE_STEP = 2  # the path is checked every second frame, as the engine's chase plans it
# Design: an opponent this much later than the team-mate's take changes nothing (beyond it the
# race's softening, LANE_MARGIN_S, is within 0.04% of certain).
OPPONENT_LATE_S = 8 * LANE_MARGIN_S
# Design: an opponent whose body passes further than this many SDs of the passer's perception error
# outside contact distance is not in the way (the chance beyond is below one in three million).
BODY_SDS = 5.0
# A3: the passer knows his own kick error and weighs the strikes it allows: a deterministic
# quadrature over the same error model the kick is struck with (engine.execute). Each error is
# normal; nodes at the centre and at plus and minus root-3 SDs along each one (weights 1/6 each, the
# centre the rest) reproduce its first four moments, as three-point Gauss-Hermite does in one
# dimension.
NODE_SD = math.sqrt(3.0)
# Design: the passer judges a strike's speed to 0.05 m/s (each component of the launch), finer than
# his kick error at any pass speed; it also lets flights be reused (`flight`).
LAUNCH_STEP_MPS = 0.05
_FLIGHTS: dict[tuple[int, int], tuple[list[tuple[float, float, float, float, float]], bool]] = {}
_FLIGHTS_MAX = 4096  # memory bound on cached flights

Flight = tuple[list[tuple[float, float, float, float, float]], bool]


def fly(key: tuple[int, int]) -> Flight:
    """A ball struck at key * LAUNCH_STEP_MPS (ground, up) m/s along a straight line, flown by the
    engine's ball physics: (seconds, metres along, height, ground speed, vertical speed) every
    RACE_STEP frames, and whether it comes to rest within ball.FLIGHT_BOUND_S."""
    path = ball.predict((0.0, 0.0, 0.0, key[0] * LAUNCH_STEP_MPS, 0.0, key[1] * LAUNCH_STEP_MPS), DT,
                        ball.FLIGHT_BOUND_S)
    last = path[-1]
    rests = last[2] == 0 and last[3] == 0 and last[5] == 0
    points = [(k * DT, s[0], s[2], s[3], s[5]) for k, s in enumerate(path)
              if k % RACE_STEP == 0 or (rests and k == len(path) - 1)]
    return points, rests


def flight(ground: float, up: float) -> Flight:
    """`fly` for a launch as the passer judges it (to LAUNCH_STEP_MPS), remembered for reuse."""
    key = (round(ground / LAUNCH_STEP_MPS), round(up / LAUNCH_STEP_MPS))
    hit = _FLIGHTS.get(key)
    if hit is None:
        if len(_FLIGHTS) >= _FLIGHTS_MAX:
            _FLIGHTS.clear()
        hit = _FLIGHTS[key] = fly(key)
    return hit


def strike_nodes(scene: Scene, tx: float, ty: float, lofted: bool, pace: float
                 ) -> list[tuple[float, float, float, float]]:
    """The strikes the passer expects when he plays it to (tx, ty) this way: (weight, direction
    error in radians, ground speed, vertical speed). Struck as estimated (ARRIVE pace along the
    ground, LOFT_DEG in the air), then scattered by his own kick error (profiles.strike_error) in the
    situation he strikes it in: the skill, the speed, the nearest opponent he sees, his fatigue, and
    the foot, from how far off the way he faces he strikes it (strike_turn: he turns first if he
    must, P16)."""
    dist = math.hypot(tx - scene.x, ty - scene.y)
    ground, up = loft_launch(dist) if lofted else (launch_speed(dist, pace), 0.0)
    speed = math.hypot(ground, up)
    dx, dy = tx - scene.x, ty - scene.y
    turn, _ = strike_turn(scene.heading, dx, dy, scene.throw)
    turn = 0.0 if scene.throw else turn  # thrown with both hands: no kicking side (engine.execute)
    cx, cy = scene.x - scene.ball_offset[0], scene.y - scene.ball_offset[1]
    nearest = min((math.hypot(o[0] - cx, o[1] - cy) for o in scene.moving), default=math.inf)
    skill = pass_skill(scene.x, tx, ty, lofted, scene.goal_x)
    dir_sd, speed_sd, loft_sd, foot = scene.passer.strike_error(skill, speed, nearest, scene.fresh, turn)
    sds = (dir_sd, speed_sd, loft_sd) if up > 0 else (dir_sd, speed_sd)
    centre = 1 - len(sds) / 3
    errors = [(centre, (0.0, 0.0, 0.0))] if centre > 0 else []
    for i, sd in enumerate(sds):
        for sign in (-1.0, 1.0):
            e = [0.0, 0.0, 0.0]
            e[i] = sign * NODE_SD * sd
            errors.append((1 / 6, tuple(e)))
    loft0 = fmath.atan2(up, ground)
    nodes = []
    for w, (d_deg, s_err, l_deg) in errors:
        v = struck_speed(speed, s_err, foot)
        if scene.throw and scene.from_hands:  # L15: as the engine throws it, never faster than an arm can
            v = min(v, KEEPER_THROW_MPS)
        loft = loft0 + math.radians(l_deg)
        nodes.append((w, math.radians(d_deg), v * fmath.cos(loft), v * fmath.sin(loft)))
    return nodes


def out_of_play(x: float, y: float) -> bool:
    """Law 9: is a ball at (x, y) wholly over a goal line or a touchline?"""
    r = ball.RADIUS
    return not (-r <= x <= PITCH_X + r and -r <= y <= PITCH_Y + r)


def in_box(x: float, y: float, goal_x: float) -> bool:
    """Law 1: is (x, y) inside the penalty area in front of the goal at goal_x?"""
    return abs(x - goal_x) <= PENALTY_DEPTH and abs(y - PITCH_Y / 2) <= PENALTY_HALF_WIDTH


def reach_time(points, t_end: float, rests: bool, sx: float, sy: float, ux: float, uy: float,
               px: float, py: float, pvx: float, pvy: float, react: float, limit: float,
               box_x: float | None = None, late: bool = False) -> tuple[float, int]:
    """(seconds, index of the path point) of the first point of the ball's path this player can
    play, by the engine's chase test (body.can_get_to, as engine.can_reach) with an average body:
    below foot height, within a foot's reach, after his reaction, braking first if he is running away
    from it. A keeper whose box is at `box_x` reaches with his hands there (engine.reach): his
    reach envelope since he reacted (offball.reach_for, by the ball's height). A ball that comes
    to rest on the pitch is reached whenever he gets there. (inf, -1) if not before `limit` or
    before the ball is out of play at `t_end`.

    With `late`, a player who cannot get to any of it is given the soonest he could be at a point of
    the path if the ball waited for him there (as engine.plan_chase times a chaser who cannot make it:
    time_to_cover), over the points before `limit`: so how far he is from making it moves the estimate
    smoothly, never all at once."""
    speed = math.hypot(pvx, pvy)
    last = len(points) - 1
    if late:
        return _late_arrival(points, t_end, rests, sx, sy, ux, uy, px, py, pvx, pvy, react, limit, box_x)
    # Nothing on the path is nearer him than its line: skip what he cannot yet reach.
    arms = offball.KEEPER_STAND_REACH_M + offball.KEEPER_DIVE_EXTRA_M if box_x is not None else CONTROL_M
    side = abs((px - sx) * uy - (py - sy) * ux)
    first = min(last, int((react + _soonest(side - arms, speed)) / (RACE_STEP * DT)))
    for i in range(first, len(points)):
        t, a, z, _, _ = points[i]
        if t > limit or t >= t_end:
            break
        resting = rests and i == last
        if t <= react and not resting:
            continue
        bx, by = sx + ux * a, sy + uy * a
        reach_m, reach_z = _FOOT if box_x is None else _reach(bx, by, z, t, react, box_x)
        if z > reach_z:
            continue
        dx, dy = bx - px, by - py
        if resting:  # it waits for him there: he takes it whenever he arrives
            reachable, gap, along = can_get_to(AVERAGE_BODY, dx, dy, reach_m, pvx, pvy, t - react)
            arrive = t if reachable else max(t, react + AVERAGE_BODY.time_to_cover(gap, along))
            return (arrive, i) if arrive <= limit else (math.inf, -1)
        if dx * dx + dy * dy > fmath.ipow(reach_m + _furthest(t - react, speed) + 1e-9, 2):
            continue  # out of his range even flat out (a necessary condition, cheaply first)
        if can_get_to(AVERAGE_BODY, dx, dy, reach_m, pvx, pvy, t - react)[0]:
            return t, i
    return math.inf, -1


_FOOT = offball.reach_for(False, 0.0)  # an outfield player's reach, the same at every moment


def _reach(bx: float, by: float, bz: float, t: float, react: float, box_x: float | None
           ) -> tuple[float, float]:
    """How far he reaches for a ball at (bx, by), height bz, `t` seconds after the strike, and how
    high he reaches at all, by the engine's own rules (offball.may_handle, offball.reach_for): a
    foot, or, for the opposing keeper (his box at `box_x`), his hands in his box, his save begun
    when he reacted (rising from then, or UP_AFTER_CONTACT_S if later). The pass is not his
    release, nor a pass from his own side, so only his box decides. Demo engine v2 (V3): he dives
    only at shots, so at a pass his hands have his standing reach, as the engine gives him."""
    hands = box_x is not None and offball.may_handle(True, in_box(bx, by, box_x), False, False)
    return offball.reach_for(hands, 0.0, bz, t - max(react, offball.UP_AFTER_CONTACT_S))


def _late_arrival(points, t_end: float, rests: bool, sx: float, sy: float, ux: float, uy: float,
                  px: float, py: float, pvx: float, pvy: float, react: float, limit: float,
                  box_x: float | None) -> tuple[float, int]:
    """reach_time with `late`: the least, over the playable points of the path before `limit`, of
    when the ball is there and when he could be (his first reachable point, if he has one). Shortcuts
    that change nothing: the point where the ball passes him gives a first answer; only points he
    could reach sooner than that (within _furthest of it) are searched, in order of a cheap lower
    bound, so few need the exact time to cover."""
    speed = math.hypot(pvx, pvy)
    last = len(points) - 1

    def playable(i: int) -> tuple[float, float, float, float] | None:
        t, a, z, _, _ = points[i]
        if t > limit or t >= t_end or (t <= react and not (rests and i == last)):
            return None
        bx, by = sx + ux * a, sy + uy * a
        reach_m, reach_z = _FOOT if box_x is None else _reach(bx, by, z, t, react, box_x)
        return None if z > reach_z else (t, bx - px, by - py, reach_m)

    def arrival(t: float, dx: float, dy: float, reach_m: float, best: float) -> float:
        # Exact: can_get_to and time_to_cover are one rule, so one who cannot get there even a
        # little after `best` (_SLACK_S, over the solver's tolerance) would time in after it.
        if best < math.inf:
            reachable, _, _ = can_get_to(AVERAGE_BODY, dx, dy, reach_m, pvx, pvy, best + _SLACK_S - react)
            if not reachable:
                return math.inf  # not there before the soonest he already has: no need to time it
        reachable, gap, along = can_get_to(AVERAGE_BODY, dx, dy, reach_m, pvx, pvy, t - react)
        return t if reachable else max(t, react + AVERAGE_BODY.time_to_cover(gap, along))

    along_of = lambda p: p[1]  # noqa: E731
    proj = (px - sx) * ux + (py - sy) * uy
    k = bisect_left(points, proj, key=along_of)
    best, at = math.inf, -1
    for i in (k - 1, k):
        here = playable(i) if 0 <= i <= last else None
        if here:
            arrive = arrival(*here, best)
            if arrive < best:
                best, at = arrive, i
    arms = offball.KEEPER_STAND_REACH_M + offball.KEEPER_DIVE_EXTRA_M if box_x is not None else CONTROL_M
    window = arms + _furthest(best + _SLACK_S - react, speed) if best < math.inf else math.inf
    lo = bisect_left(points, proj - window, key=along_of)
    hi = bisect_right(points, proj + window, key=along_of)
    candidates = []
    for i in range(lo, min(hi, last + 1)):
        t, a, z, _, _ = points[i]
        if t >= best or t > limit or t >= t_end:
            break  # (the same conditions as `playable`, inline for speed)
        if t <= react and not (rests and i == last):
            continue
        bx, by = sx + ux * a, sy + uy * a
        reach_m, reach_z = _FOOT if box_x is None else _reach(bx, by, z, t, react, box_x)
        if z > reach_z:
            continue
        dx, dy = bx - px, by - py
        soonest = react + _soonest(math.hypot(dx, dy) - reach_m, speed)
        candidates.append((max(t, soonest), i, (t, dx, dy, reach_m)))
    candidates.sort()
    for bound, i, here in candidates:
        if bound >= best:
            break  # every later candidate is at least as late
        arrive = arrival(*here, best)
        if arrive < best:
            best, at = arrive, i
    return best, at


def body_near(off_path: float, carried: float, sigma: float) -> bool:
    """Could an opponent this far off the ball's path (at the widest spread of the strikes) be in its
    way, given how far he carries himself before reacting and the passer's perception error of him
    (its largest SD before he reacts)? A shortcut only: body_hit is zero for anyone it rules out."""
    return off_path - carried <= BODY_RADIUS + ball.RADIUS + BODY_SDS * sigma


def body_hit(points, take: float, sx: float, sy: float, ux: float, uy: float,
             ox: float, oy: float, ovx: float, ovy: float, react: float, sigma0: float, sigma_v: float
             ) -> float:
    """The chance the ball strikes this opponent's body on its way, before the team-mate takes it
    at `take` (engine.contact: a body needs no reaction, and any opponent touch ends a pass). Until
    he reacts he carries on as he was going; after it, a ball low enough to play is his race
    (reach_time), so only one at body height counts. Where the ball passes him is judged from where
    the passer believes he is, which may be off by his perception error (sigma0 + sigma_v * seconds:
    perception.POSITION_ERROR_PER_M and VELOCITY_ERROR_PER_M at his distance), out to BODY_SDS."""
    prev = None
    for t, a, z, _, _ in points:
        if t > take:
            return 0.0
        k = min(t, react)
        rx, ry = ox + ovx * k - sx, oy + ovy * k - sy
        along = rx * ux + ry * uy
        if along <= 0:
            return 0.0  # behind the strike: the ball goes away from him
        if a >= along:
            if prev is not None and a > prev[1]:  # where it passed him, between two path points
                f = (along - prev[1]) / (a - prev[1])
                t, z = prev[0] + f * (t - prev[0]), prev[2] + f * (z - prev[2])
            if t > take or z > BODY_HEIGHT or (t >= react and z <= FOOT_REACH_Z):
                return 0.0
            side = abs(rx * uy - ry * ux)
            sigma = max(sigma0 + sigma_v * min(t, react), 1e-3)
            r = BODY_RADIUS + ball.RADIUS
            if side - r > BODY_SDS * sigma:
                return 0.0
            spread = sigma * math.sqrt(2)
            # erf(a) - erf(b) = erfc(b) - erfc(a)
            return 0.5 * (fmath.erfc((-r - side) / spread) - fmath.erfc((r - side) / spread))
        prev = (t, a, z)
    return 0.0


def pass_confidence(scene: Scene, tx: float, ty: float, mx: float, my: float, age: float,
                    lofted: bool, pace: float = ARRIVE_MPS, receiver: str | None = None) -> float:
    """The passer's estimate that a pass to (tx, ty), meant for the team-mate he sees at (mx, my),
    is received by a team-mate: averaged over the strikes his own kick error allows (strike_nodes),
    the first team-mate who can get to the ball's path takes it (reach_time), unless it leaves the
    pitch first, an opponent's body is in its way before he can react (body_hit), or an opponent
    gets there before him (each raced against that take, softened by LANE_MARGIN_S); and the
    team-mate's first touch must keep the ball at his feet (A4, the engine's own touch in
    firsttouch.py: the surface by the ball's height, what it cannot kill left to run; softened by
    CONTROL_MARGIN_MPS)."""
    sx, sy = scene.x, scene.y
    direction = fmath.atan2(ty - sy, tx - sx)
    nodes = strike_nodes(scene, tx, ty, lofted, pace)
    cx, cy = sx - scene.ball_offset[0], sy - scene.ball_offset[1]
    # P16: if he must turn before he can strike it, everyone else moves on meanwhile, each as the
    # passer believes him to be going (he holds the ball where it is while he turns).
    _, wait = strike_turn(scene.heading, tx - sx, ty - sy, scene.throw)
    # Team-mates, the one it is meant for first, from where the passer sees him and expecting it:
    # (x, y, vx, vy, reaction, first touch).
    seen = {m[0]: m for m in scene.mates}
    meant = seen.get(receiver, (receiver, mx, my, age))
    mvx, mvy = meant[4:6] or (0.0, 0.0)
    mates = [(mx + mvx * wait, my + mvy * wait, mvx, mvy, perception.SIMPLE_REACTION_S,
              scene.absorb.get(receiver, CONTROL_EST_MPS))]
    for mid, qx, qy, _, *vel in scene.mates:
        if mid != receiver and (receiver is not None or (qx, qy) != (mx, my)):
            qvx, qvy = vel or (0.0, 0.0)
            mates.append((qx + qvx * wait, qy + qvy * wait, qvx, qvy, perception.CHOICE_REACTION_S,
                          scene.absorb.get(mid, CONTROL_EST_MPS)))
    opponents = [(ox + ovx * wait, oy + ovy * wait, ovx, ovy, keeper)
                 for ox, oy, ovx, ovy, keeper in scene.moving]
    # How far each player is from the ball's whole path at the widest spread of the strikes: a
    # lower bound on when he could get there (at top speed, straight), so the race can skip those
    # who could not be in it.
    longest = max(flight(g, u)[0][-1][1] for _, _, g, u in nodes)
    spread = max(abs(d) for _, d, _, _ in nodes)
    ux0, uy0 = fmath.cos(direction), fmath.sin(direction)
    ex, ey = sx + ux0 * longest, sy + uy0 * longest

    def off_path(px: float, py: float) -> float:
        return max(0.0, distance_to_segment(px, py, sx, sy, ex, ey) - longest * fmath.sin(spread))

    mate_lb = [m[4] + _soonest(off_path(m[0], m[1]) - CONTROL_M, math.hypot(m[2], m[3])) for m in mates]
    arm_max = offball.KEEPER_STAND_REACH_M + offball.KEEPER_DIVE_EXTRA_M
    react = perception.CHOICE_REACTION_S
    rivals = []  # (x, y, vx, vy, keeper, earliest, could his body be in the way, sigma0, sigma_v)
    for ox, oy, ovx, ovy, keeper in opponents:
        off = off_path(ox, oy)
        d = math.hypot(ox - cx, oy - cy)
        sigma0, sigma_v = perception.POSITION_ERROR_PER_M * d, perception.VELOCITY_ERROR_PER_M * d
        lb = react + _soonest(off - (arm_max if keeper else CONTROL_M), math.hypot(ovx, ovy))
        body = body_near(off, math.hypot(ovx, ovy) * react, sigma0 + sigma_v * react)
        rivals.append((ox, oy, ovx, ovy, keeper, lb, body, sigma0, sigma_v))
    total = 0.0
    for w, d_angle, ground, up in nodes:
        points, rests = flight(ground, up)
        ux, uy = fmath.cos(direction + d_angle), fmath.sin(direction + d_angle)
        t_end = math.inf  # out of play (Law 9): the whole ball over a line
        for t, a, _, _, _ in points:
            bx, by = sx + ux * a, sy + uy * a
            if out_of_play(bx, by):
                t_end = t
                break
        take, at, taker = math.inf, -1, None
        for mate, lb in zip(mates, mate_lb, strict=True):
            if lb > take:
                continue
            t, i = reach_time(points, t_end, rests, sx, sy, ux, uy, *mate[:5], take)
            if t < take:
                take, at, taker = t, i, mate
        if taker is None:
            continue  # nobody of his gets to it before it goes out or comes to rest out of reach
        _, a, z, g, vz = points[at]
        if at == len(points) - 1 and rests:
            g = vz = 0.0
        # The engine's own touch (firsttouch.py): the surface by the ball's height where he takes it,
        # made worse as the engine makes it (firsttouch.quality) by what the passer can know: its
        # speed and the opponents he sees near where it is taken (D2's zone); the team-mate is
        # taken to face it, as one expecting it does, fresh and of average composure.
        # A receiver runs onto the ball's path, so it comes into his body: above BODY_TOUCH_Z, the
        # part its height gives (design, verify, A4, D1): pessimistic where the engine finds him beside
        # it, with a foot. The calibration report checks it is a bound, not a fit (`ninety.sim.calibration`,
        # forced passes, seeds 1 to 6, on main b319f21: received more often than estimated in every
        # bin from 0.0 to 0.7, as a cautious estimate should be).
        rel = relative_speed(g * ux, g * uy, vz, taker[2], taker[3])
        tx_, ty_ = sx + ux * a, sy + uy * a
        felt = max((perception.pressure_from(tx_, ty_, ox, oy, attack(scene.goal_x))
                    for ox, oy in scene.opponents), default=0.0)
        worse = firsttouch.quality(0.0, felt, AVERAGE, 1.0, rel, taker[5])
        p = firsttouch.kept_estimate(rel, firsttouch.surface_absorb(taker[5], z) / worse, CONTROL_MARGIN_MPS)
        horizon = take + OPPONENT_LATE_S
        # Where the ball has got to by then, along this strike: nobody further from that stretch of
        # its path than he can run by then matters (a shortcut, like `lb`).
        reached = points[min(len(points) - 1, int(horizon / (RACE_STEP * DT)) + 1)][1]
        hx, hy = sx + ux * reached, sy + uy * reached
        for ox, oy, ovx, ovy, keeper, lb, body, sigma0, sigma_v in rivals:
            if body:
                p *= 1 - body_hit(points, take, sx, sy, ux, uy, ox, oy, ovx, ovy, react, sigma0, sigma_v)
            if lb > horizon:
                continue  # he could not be there soon enough to matter
            near = distance_to_segment(ox, oy, sx, sy, hx, hy) - (arm_max if keeper else CONTROL_M)
            if react + _soonest(near, math.hypot(ovx, ovy)) > horizon:
                continue
            # When he could be there, or how late he would be if he cannot make it: an opponent
            # just short of the lane is nearly as much a risk as one who just reaches it.
            t, _ = reach_time(points, t_end, rests, sx, sy, ux, uy, ox, oy, ovx, ovy, react,
                              horizon, scene.goal_x if keeper else None, late=True)
            if t <= horizon:
                p *= sigmoid((t - take) / LANE_MARGIN_S)
        total += w * p
    return total * (0.8 if age > STALE_S else 1.0)


def room_to_play(space: float) -> float:
    """How much of the ball's worth a receiver this far from the nearest opponent can use: a
    receiver with space can do more with it (*design*: 70% when pressed, all of it from 5 m)."""
    return 0.7 + 0.3 * min(1.0, space / 5.0)


def pass_option(scene: Scene, mate: tuple[str, float, float, float]) -> Option | None:
    mid, mx, my, age, *moving = mate
    # O7: into the space he is running into, by the velocity the passer has seen; a team-mate
    # standing still gets it a step ahead, toward goal.
    dist0 = math.hypot(mx - scene.x, my - scene.y)
    if moving and math.hypot(*moving) > 1.0:
        t_est = min(LEAD_MAX_S, dist0 / PASS_SPEED_EST_MPS)
        lx, ly = moving[0] * t_est, moving[1] * t_est
    else:
        lx, ly = 1.5 * attack(scene.goal_x), 0.0
    tx, ty = min(PITCH_X - 1, max(1.0, mx + lx)), min(PITCH_Y - 1, max(1.0, my + ly))
    dist = math.hypot(tx - scene.x, ty - scene.y)
    if dist < 4 or dist > MAX_PASS_M:
        return None
    gain = our_value(scene, tx, ty)
    space = min((math.hypot(ox - tx, oy - ty) for ox, oy in scene.opponents), default=10.0)
    gain *= room_to_play(space)
    # A pass that fails is lost along the lane or runs on to where it was aimed: the worse of the two.
    mx_, my_ = (scene.x + tx) / 2, (scene.y + ty) / 2
    lost = max(our_loss(scene, mx_, my_), our_loss(scene, tx, ty))
    # D1: how to play it is his choice: along the ground at a pace the lane needs, or, from
    # LOFT_FROM_M, over the top. A throw-in always goes through the air (Law 15). A keeper's
    # throw (throw and from_hands, L15) may roll or go through the air, on the paces a pass
    # already has. No new distance.
    if scene.throw and not scene.from_hands:
        ways = [(True, ARRIVE_MPS)]
    elif scene.throw and scene.from_hands:
        # As far as he can throw it (KEEPER_THROW_MPS): beyond that he kicks it or puts it down.
        ways = [(False, pace) for pace in PASS_PACES if launch_speed(dist, pace) <= KEEPER_THROW_MPS]
        if math.hypot(*loft_launch(dist)) <= KEEPER_THROW_MPS:
            ways.append((True, ARRIVE_MPS))
    elif scene.from_hands:  # a kick from his hands (L15): dropped and struck, it goes through the air
        ways = [(True, ARRIVE_MPS)]
    else:
        ways = [(False, pace) for pace in PASS_PACES]
        if dist >= LOFT_FROM_M:
            ways.append((True, ARRIVE_MPS))
    best = None
    for lofted, pace in ways:
        confidence = pass_confidence(scene, tx, ty, mx, my, age, lofted, pace, mid)
        ev = confidence * gain - (1 - confidence) * lost
        if best is None or ev > best.value:
            best = Option("pass", ev, (tx, ty), mid, lofted, pace)
    return best


OPEN_RADIUS_M = 5.0  # O3: design: how far from his place in the shape an attacker moves to be open
OPEN_GRID_M = OPEN_RADIUS_M / 2  # O3: design: the spots he weighs lie on a grid this fine


def lane_margin(px: float, py: float, sx: float, sy: float,
                defenders: list[tuple[float, float]]) -> float:
    """O3: how late the best-placed defender would be to a ground pass from (px, py) to (sx, sy):
    his time to get a foot to his own nearest point of the lane, or to the spot itself, less the
    ball's there at PASS_SPEED_EST_MPS. Positive, the lane is open; the larger, the more open. A
    pitch-control race (Spearman 2018), simpler than the carrier's own (pass_confidence): one pace,
    defenders from standing, as D1 times a generic player: one whose body is on the lane needs no
    reaction (D1's contact); anyone else reacts (generic_time), then gets within a foot's reach of
    it (*design*: a simplification of D1, not its race)."""
    d = math.hypot(sx - px, sy - py)
    arrive = d / PASS_SPEED_EST_MPS

    def gets_there(gap: float) -> float:  # D1: a body in the way needs no reaction; a foot does
        return 0.0 if gap <= BODY_RADIUS + ball.RADIUS else generic_time(max(0.0, gap - _FOOT[0]))

    worst = math.inf
    for ox, oy in defenders:
        off, share = closest_on_segment(ox, oy, px, py, sx, sy)  # where he would cut it out
        worst = min(worst, gets_there(off) - share * arrive,
                    gets_there(math.hypot(sx - ox, sy - oy)) - arrive)
    return worst


def open_legal(slot: tuple[float, float], offset: tuple[float, float], passer: tuple[float, float] | None,
               onside_x: float, goal_x: float) -> bool:
    """O3: may he stand at his place plus this offset? On the pitch, never offside as he sees it
    (L10), within OPEN_RADIUS_M of his place, and, with a carrier, within passing range (MAX_PASS_M)
    and never nearer the carrier than his place is (coming short is the shape's job: O3's nearest
    two, O6; spots nearer the ball are always safer, so they would draw the whole team in)."""
    x, y = slot[0] + offset[0], slot[1] + offset[1]
    if not (0.5 <= x <= PITCH_X - 0.5 and 0.5 <= y <= PITCH_Y - 0.5) or attack(goal_x) * (x - onside_x) > 0:
        return False
    if math.hypot(*offset) > OPEN_RADIUS_M + 1e-9:
        return False
    if passer is None:
        return True
    px, py = passer
    here = math.hypot(x - px, y - py)
    return here <= MAX_PASS_M and here >= math.hypot(slot[0] - px, slot[1] - py) - 1e-9


def open_spot(slot: tuple[float, float], offset: tuple[float, float], passer: tuple[float, float],
              defenders: list[tuple[float, float]], onside_x: float, goal_x: float) -> tuple[float, float]:
    """O3: where, within OPEN_RADIUS_M of his place in the shape, an attacker off the ball stands so
    that a pass to him is worth most, in the carrier's terms (pass_option): the chance it reaches him
    there (his lane raced, lane_margin, on D1's sigmoid) times what the ball is worth there (D9, with
    the same room to play, room_to_play), less the chance it is cut out times what losing it costs;
    at the neutral style (T4's weights are the carrier's, not his). Open space that is worth
    something (Fernandez and Bornn 2018). He weighs the spots of a grid (OPEN_GRID_M) across the
    carrier's line to him (out of a defender's cover shadow) or further along it (more room behind),
    never toward the carrier, and only those open_legal allows. Returned as an offset from his place.
    He keeps the offset he has unless another is worth more by CHOICE_NOISE_GOALS: options closer
    than that are a coin-flip to the carrier (D4), so moving would change nothing."""
    sx, sy = slot
    px, py = passer
    if math.hypot(sx - px, sy - py) > MAX_PASS_M:
        return (0.0, 0.0)  # out of passing range: not an option to be open for
    r0 = math.hypot(sx - px, sy - py) or 1.0
    ux, uy = (sx - px) / r0, (sy - py) / r0
    g = OPEN_GRID_M
    rings = [(a * -uy + b * ux, a * ux + b * uy) for a in (-2 * g, -g, 0.0, g, 2 * g)
             for b in (0.0, g, 2 * g) if math.hypot(a, b) <= OPEN_RADIUS_M + 1e-9]

    def worth(o: tuple[float, float]) -> float:
        x, y = sx + o[0], sy + o[1]
        reaches = sigmoid(lane_margin(px, py, x, y, defenders) / LANE_MARGIN_S)
        space = min((math.hypot(ox - x, oy - y) for ox, oy in defenders), default=10.0)
        gain = value(x, y, goal_x) * room_to_play(space)
        lost = max(loss_cost((px + x) / 2, (py + y) / 2, goal_x), loss_cost(x, y, goal_x))
        return reaches * gain - (1 - reaches) * lost

    held = offset if open_legal(slot, offset, passer, onside_x, goal_x) else (0.0, 0.0)
    best = max((o for o in rings if open_legal(slot, o, passer, onside_x, goal_x)), key=worth, default=held)
    return best if worth(best) > worth(held) + CHOICE_NOISE_GOALS else held


def short_pass_lean(dist: float) -> float:
    """plays_short: +1 toward a pass under SHORT_PASS_M, -1 away from one over LONG_PASS_M, and in
    between from one to the other. A share of HABIT_PULL; the pass itself is unchanged."""
    if dist <= SHORT_PASS_M:
        return 1.0
    if dist >= LONG_PASS_M:
        return -1.0
    return 1 - 2 * (dist - SHORT_PASS_M) / (LONG_PASS_M - SHORT_PASS_M)


def clear_value(scene: Scene, tx: float, ty: float, contest: float | None = None) -> float:
    """D9, Law 9: what a clearance aimed at (tx, ty) is worth, over the strikes his own kick error
    allows (strike_nodes, lofted, as the pass estimate weighs them): `contest` if it stays in play,
    or, if it crosses a line before any player (either side: whoever gets there, it is still the
    contest, *design*) can get to it, minus the cost of their restart where it went out
    (restart_cost). The race is the pass estimate's reach test (reach_time: average body, a keeper's
    hands in his box) with everyone moved on while he turns to strike (P16), each after an average
    choice reaction; unlike the pass estimate it is a hard race, with no softening, no body in the
    way and no error in where he sees them (*design*)."""
    sx, sy = scene.x, scene.y
    direction = fmath.atan2(ty - sy, tx - sx)
    _, wait = strike_turn(scene.heading, tx - sx, ty - sy, scene.throw)
    react = perception.CHOICE_REACTION_S
    players = []
    for m in scene.mates:
        mvx, mvy = m[4:6] or (0.0, 0.0)
        players.append((m[1] + mvx * wait, m[2] + mvy * wait, mvx, mvy, None, True))
    for ox, oy, ovx, ovy, keeper in scene.moving:
        players.append((ox + ovx * wait, oy + ovy * wait, ovx, ovy, scene.goal_x if keeper else None, False))
    total = 0.0
    for w, d_angle, ground, up in strike_nodes(scene, tx, ty, True, ARRIVE_MPS):
        points, rests = flight(ground, up)
        ux, uy = fmath.cos(direction + d_angle), fmath.sin(direction + d_angle)
        t_end, where = math.inf, None
        for t, a, _, _, _ in points:
            if out_of_play(sx + ux * a, sy + uy * a):
                t_end, where = t, (sx + ux * a, sy + uy * a)
                break
        # Who gets to it first, each side's soonest (the same race, both sides).
        ours, theirs = (math.inf, -1), (math.inf, -1)
        for px, py, pvx, pvy, box, mine in players:
            got = reach_time(points, t_end, rests, sx, sy, ux, uy, px, py, pvx, pvy, react, t_end, box)
            if mine and got[0] < ours[0]:
                ours = got
            elif not mine and got[0] < theirs[0]:
                theirs = got
        kept = where is None or min(ours[0], theirs[0]) < t_end
        if not kept:
            total += w * -restart_cost(*where, scene.goal_x)
            continue
        if contest is not None:
            total += w * contest
            continue
        # Demo engine v2 (D1, D9): where it comes down is a race, not an even contest: his side
        # keeps it as often as the pass estimate's race says (softened by LANE_MARGIN_S), and it is
        # worth what having it, or losing it, there is worth. Once every clearance was an even
        # contest wherever it landed, so he aimed at an empty spot 45 m up the pitch.
        if ours[0] == math.inf and theirs[0] == math.inf:  # nobody before it stops: loose (design: even)
            p, at = 0.5, len(points) - 1
        else:
            p = sigmoid((theirs[0] - ours[0]) / LANE_MARGIN_S) if theirs[0] < math.inf else 1.0
            at = ours[1] if ours[0] <= theirs[0] else theirs[1]
        lx, ly = sx + ux * points[at][1], sy + uy * points[at][1]
        total += w * (p * our_value(scene, lx, ly) - (1 - p) * our_loss(scene, lx, ly))
    return total


def restart_cost(x: float, y: float, goal_x: float) -> float:
    """What the restart costs the side attacking `goal_x` when its ball goes out at (x, y), by the
    line it crossed: their throw-in where it crossed a touchline (Law 15), their goal kick when it
    crossed the goal line they attack (Law 16), their corner when it crossed his own (Law 17). Not
    style-weighted, as the clearance's contest is not (T4)."""
    over_y = max(-y, y - PITCH_Y, 0.0)
    over_x = max(-x, x - PITCH_X, 0.0)
    if over_y >= over_x:  # over a touchline (at a corner, the line it is further over)
        return loss_cost(min(PITCH_X, max(0.0, x)), min(PITCH_Y, max(0.0, y)), goal_x)
    if (x - PITCH_X / 2) * (goal_x - PITCH_X / 2) > 0:  # over the goal line he attacks
        return loss_cost(goal_x - attack(goal_x) * GOAL_KICK_M, PITCH_Y / 2, goal_x)
    own = PITCH_X - goal_x
    return loss_cost(own, 0.0 if y < PITCH_Y / 2 else PITCH_Y, goal_x)


def shot_chance(scene: Scene) -> float:
    """His estimate that a shot from here goes in. With measured tables (D7): how often shots from
    here went in, scaled by how this situation compares with an open one (blockers in the cone, the
    keeper's position), so shooting and moving the ball are judged on the same scale."""
    q = shot_estimate(scene.x, scene.y, scene.goal_x, scene.opponents, scene.keeper)
    if POSSESSION is None:
        return q
    typical = typical_shot(scene.x, scene.y, scene.goal_x)  # what the measured rate averages over
    measured = POSSESSION.finishing.at(scene.x, scene.y, scene.goal_x)
    return min(1.0, measured * q / typical) if typical > 0 else 0.0


def options(scene: Scene) -> list[Option]:
    out = [o for o in (pass_option(scene, mate) for mate in scene.mates) if o]
    if scene.throw:  # Law 15: a throw-in is thrown to someone; it is never a shot or a dribble
        return out
    p = pressure(scene)
    q = shot_chance(scene)
    # D3: a shot is an option inside SHOT_RANGE_M of the goal's centre, straight-line, as the rates it
    # is judged by are (it was once along the pitch only, offering shots from 40 to 50 m out wide).
    if math.hypot(scene.goal_x - scene.x, PITCH_Y / 2 - scene.y) < offball.SHOT_RANGE_M:
        bias = 1.3 if "shoots_from_distance" in scene.traits else 1.0
        # A shot that fails is either blocked, leaving the ball at his feet for them, or missed or
        # saved, which gives the ball back from deep (a goal kick or the keeper's hands).
        blockers = sum(in_cone(scene.x, scene.y, scene.goal_x, ox, oy) for ox, oy in scene.opponents
                       if (ox, oy) != scene.keeper)
        blocked = 1 - fmath.ipow(BLOCKER_FACTOR, blockers)
        # A miss or a save gives them the ball deep in their own half (a goal kick or the keeper's).
        missed = our_loss(scene, scene.goal_x - attack(scene.goal_x) * GOAL_KICK_M, PITCH_Y / 2)
        lost = blocked * our_loss(scene, scene.x, scene.y) + (1 - blocked) * missed
        out.append(Option("shoot", q * bias * (1 + 0.5 * scene.risk) - (1 - q) * lost,
                          (scene.goal_x, PITCH_Y / 2)))
    # Laws 8, 13, 16, 17: carrying a set ball off is touching it twice before anyone else has.
    # Straight at goal, or angled away; demo engine v2 (D6, design): also half that angle and half
    # as much again, so a carrier can go round a defender rather than only at him or well away.
    for turn in () if scene.set_piece else (0.0, 0.4, -0.4, 0.8, -0.8, 1.2, -1.2):
        heading = fmath.atan2(PITCH_Y / 2 - scene.y, scene.goal_x - scene.x) + turn
        tx = scene.x + DRIBBLE_STEP_M * fmath.cos(heading)
        ty = scene.y + DRIBBLE_STEP_M * fmath.sin(heading)
        if not (1 <= tx <= PITCH_X - 1 and 1 <= ty <= PITCH_Y - 1):
            continue
        # Can an opponent reach the carry anywhere along it before he has carried the ball past?
        # A defender within lunge reach of the carry can tackle (the same race the defender judges);
        # one further off must first get to it.
        win = 1.0
        for ox, oy in scene.opponents:
            d, s = closest_on_segment(ox, oy, scene.x, scene.y, tx, ty)
            if d <= LUNGE_REACH_M:
                win *= 1 - tackle_chance(d)
                continue
            # Demo engine v2: he gets there as his body does, from the speed he has along the carry,
            # no faster than he can carry it (as the race times everyone else: generic_time).
            along = (scene.velocity[0] * (tx - scene.x) + scene.velocity[1] * (ty - scene.y)) / DRIBBLE_STEP_M
            my_t = AVERAGE_BODY.time_to_cover(s * DRIBBLE_STEP_M, along, cap=scene.carry_mps)
            win *= sigmoid((generic_time(d) - my_t) / RECEIVE_MARGIN_S)
        gain = our_value(scene, tx, ty)
        ev = win * gain - (1 - win) * our_loss(scene, scene.x, scene.y)
        out.append(Option("dribble", ev, (tx, ty)))
    if abs(scene.goal_x - scene.x) > CLEAR_FROM * PITCH_X:  # in his own third: long and away
        tx = scene.x + attack(scene.goal_x) * CLEAR_AHEAD_M
        ty = CLEAR_IN_FROM_LINE_M if scene.y < PITCH_Y / 2 else PITCH_Y - CLEAR_IN_FROM_LINE_M
        # A long ball away, aimed up the pitch away from goal, or (demo engine v2) toward a
        # team-mate he sees well up the pitch (within kicking range, MAX_CLEAR_M): each valued by the
        # race where it comes down (clear_value), so he aims where his side can win it.
        aims = [(tx, ty)]
        up = sorted(((mx - scene.x) * attack(scene.goal_x), mx, my) for _, mx, my, *_ in scene.mates
                    if math.hypot(mx - scene.x, my - scene.y) <= MAX_CLEAR_M)
        aims += [(mx, my) for ahead, mx, my in up[-CLEAR_MATES:] if ahead >= CLEAR_MATE_FROM_M]
        best = max(((clear_value(scene, ax, ay), ax, ay) for ax, ay in aims), key=lambda c: c[0])
        out.append(Option("clear", best[0], (best[1], best[2]), lofted=True))
    # Holding is waiting to make a move a moment later: worth the best move open to him now, less
    # what the defence recovers while he waits (D9; *verify*: options only decay while he waits,
    # nothing here models a run developing). He cannot wait for ever, so when every move is a bad
    # one, waiting is a little worse still. Under pressure he loses the ball where he stands about
    # half the time he is caught (p * 0.5); otherwise he still makes that move. Holding carries no
    # pull for carrying on.
    best = max((o.value for o in out), default=0.0)
    later = best * (1 - HOLD_DECAY) if best >= 0 else best * (1 + HOLD_DECAY)
    lose = 0.5 * p
    if not scene.committed:
        out.append(Option("hold", (1 - lose) * later - lose * our_loss(scene, scene.x, scene.y)))
    return out


def temperature(scene: Scene) -> float:
    """D4 (design): how loosely the player chooses, as a share of CHOICE_NOISE_GOALS. A good
    decision-maker almost always takes the best option; opponent pressure loosens his choice unless
    he is composed (pressure worsens footballers' decision quality: Musculus et al. 2021)."""
    return (0.15 + 0.6 * (1 - scene.decisions)) * (1 + pressure(scene) * (1 - scene.composure))


def pull(scene: Scene, o: Option) -> float:
    """D4, A5: how far a habit or carrying on draws him to this option, in units of his own
    misjudgement (HABIT_PULL each): takes_players_on toward a dribble, carrying on toward the dribble
    he is on, plays_short toward a short pass and away from a long one."""
    p = 0.0
    if o.kind == "dribble" and "takes_players_on" in scene.traits:
        p += HABIT_PULL
    if o.kind == "dribble" and scene.current == "dribble":
        p += HABIT_PULL
    if o.kind == "pass" and o.target and "plays_short" in scene.traits:
        p += HABIT_PULL * short_pass_lean(math.hypot(o.target[0] - scene.x, o.target[1] - scene.y))
    return p


def score(scene: Scene, o: Option, top: float, t: float) -> float:
    """D4: an option's score before his misjudgement: its value against the best one's, in units of
    his temperature in goals `t` (temperature times CHOICE_NOISE_GOALS), plus the pull of a habit."""
    return (o.value - top) / t + pull(scene, o)


def choice_weights(scene: Scene, opts: list[Option]) -> list[float]:
    """D4: each option's chance of being chosen, up to a factor: exp(score). The odds between two
    options depend only on those two and on him, never on what else is on offer. The randomness
    was once a share of the spread of all his options, so a hopeless option widened it and loosened
    the choice between the good ones: the best option was taken in about a third of decisions."""
    top, t = max(o.value for o in opts), temperature(scene) * CHOICE_NOISE_GOALS
    return [fmath.exp(score(scene, o, top, t)) for o in opts]


def taste_key(scene: Scene, o: Option) -> tuple:
    """Which option this is from one look to the next while he has the ball: a pass by who it is for
    and how, a carry by its direction against the goal, the rest by kind (from #103)."""
    if o.kind == "pass":
        return o.kind, o.receiver, o.lofted
    if o.kind == "dribble" and o.target:
        goal = fmath.atan2(PITCH_Y / 2 - scene.y, scene.goal_x - scene.x)
        turn = fmath.atan2(o.target[1] - scene.y, o.target[0] - scene.x) - goal
        return o.kind, round(((turn + math.pi) % (2 * math.pi) - math.pi) / 0.4)  # demo v2: per direction
    return (o.kind,)


def choose(scene: Scene, rng: random.Random, tastes: dict | None = None) -> Option:
    """D4: the option with the best score plus his own misjudgement of it, a random-utility draw
    (Gumbel), so a single choice falls as choice_weights say. The draw is made once per option and
    kept in `tastes` until he next scans the pitch (the engine starts a new `tastes` then): asked
    again four times a second about the same options he answers the same way, so an option he keeps
    rejecting does not become certain by being asked, and how loosely he chooses does not grow with
    his time on the ball (from #103)."""
    opts = options(scene)
    tastes = {} if tastes is None else tastes
    top, t = max(o.value for o in opts), temperature(scene) * CHOICE_NOISE_GOALS

    def taste(o: Option) -> float:
        k = taste_key(scene, o)
        if k not in tastes:
            tastes[k] = -fmath.log(-fmath.log(max(rng.random(), 1e-12)))
        return tastes[k]

    return max(opts, key=lambda o: score(scene, o, top, t) + taste(o))
