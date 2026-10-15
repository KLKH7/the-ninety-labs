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
from bisect import bisect_left
from dataclasses import dataclass

from ninety.sim import ball, threat
from ninety.sim import value as possession

PITCH_X, PITCH_Y = 105.0, 68.0
GOAL_HALF_WIDTH = 3.66
DT = 1 / 25
GENERIC_REACTION_S = 0.365  # D1: how quickly the passer assumes an opponent reacts (P12)
LANE_MARGIN_S = 0.25  # D1: design: how sharply the passer's confidence falls as a lane closes
RECEIVE_MARGIN_S = 0.3  # design: the same for the receiver getting there in time
PRESSURE_FRONT_M, PRESSURE_BEHIND_M = 9.0, 3.0  # D2: pressure zone, longer in front than behind
# D3: how often a shot goes in by distance from the goal's centre, for a central shot: the
# share of real shots that scored by zone (six-yard box 31%, the rest of the central box 17.7%,
# central outside the box 5.3%, long range 2.3%; American Soccer Analysis, 8,291 MLS shots, 2013).
# Distances are the zones' approximate middles (*verify*); beyond 40 m is *design*. A player's
# sense of a good chance comes from what goes in, not from the open goal he sees.
SHOT_ANCHORS = ((0.0, 0.31), (3.0, 0.31), (11.0, 0.177), (20.0, 0.053), (30.0, 0.023), (40.0, 0.01),
                (105.0, 0.0))
BLOCKER_FACTOR = 0.5  # design: each defender in the shooting cone halves the estimate
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
LOFT_OVER_M = 25.0
RECEIVE_HEIGHT_M = 1.0  # a dropping ball is taken on the foot or thigh below about this height
LOFT_DEG = 30.0  # design: the launch angle of a lofted pass or a throw, as estimated and as struck
CONTROL_EST_MPS = 18.0  # A4: the passer's guess of what a first touch can kill: the average (12 + 12 × 0.5)
CONTROL_MARGIN_MPS = 2.0  # design: how sharply that guess falls off
GOAL_KICK_M = 5.5  # Law 16: a goal kick is taken from the goal area
STICKY = 0.003  # design: a small bonus for carrying on with the current choice (no flip-flopping)
CLEAR_FROM = 2 / 3  # a clear is an option in his own third: this share of the pitch from the goal he attacks


# D7: what having the ball is worth by area, measured from the engine's own matches
# (ninety/sim/value.py). Until a table has been measured, the hand-written estimate below is used.
POSSESSION: possession.Tables | None = possession.load()


def _ground_table() -> tuple[list[float], list[tuple[list[float], list[float]]]]:
    """For launch speeds 4 to 36 m/s, the time a ground pass takes to reach each distance."""
    speeds = [4.0 + 2.0 * i for i in range(17)]
    tables = []
    for v0 in speeds:
        path = ball.predict((0, 0, 0, v0, 0, 0), DT, 8.0)
        tables.append(([s[0] for s in path], [i * DT for i in range(len(path))]))
    return speeds, tables


SPEEDS, TABLES = _ground_table()
ARRIVE_MPS = 6.0  # the softest pace a ground pass is struck to arrive at
# D1: the paces a ground pass can be struck to arrive at (design); passes leave the foot at about
# 16 m/s in professional matches (tracking data, arXiv 2210.16474), so 10 to 14 m/s arrivals are normal.
PASS_PACES = (6.0, 10.0, 14.0)
# The launch speed for a ground pass to arrive at each pace, per 0.5 m of distance (0 to 45 m),
# solved once by ball physics rather than on every decision.
LAUNCH = {pace: [ball.ground_pass(max(d * 0.5, 0.5), pace, DT) for d in range(91)] for pace in PASS_PACES}


# The same for a lofted pass at LOFT_DEG: (ground speed, vertical speed) per 0.5 m.
LOFT = [ball.lofted_pass(max(d * 0.5, 0.5), LOFT_DEG, DT) for d in range(91)]


def _arrival_speed(launch: tuple[float, float]) -> float:
    """Speed of a lofted ball when it has come back down to a receiver's foot or thigh (1 m),
    from the same ball physics the engine flies it with (drag slows it on the way)."""
    ground, up = launch
    path = ball.predict((0.0, 0.0, 0.0, ground, 0.0, up), DT, 6.0)
    for state in path[1:]:
        if state[5] < 0 and state[2] <= RECEIVE_HEIGHT_M:
            return math.sqrt(state[3] ** 2 + state[4] ** 2 + state[5] ** 2)
    last = path[-1]
    return math.sqrt(last[3] ** 2 + last[4] ** 2 + last[5] ** 2)


ARRIVAL = [_arrival_speed(launch) for launch in LOFT]


def launch_speed(distance: float, pace: float = ARRIVE_MPS) -> float:
    table = LAUNCH[pace]
    return table[min(len(table) - 1, max(0, round(distance / 0.5)))]


def loft_launch(distance: float) -> tuple[float, float]:
    return LOFT[min(len(LOFT) - 1, max(0, round(distance / 0.5)))]


def loft_arrival(distance: float) -> float:
    return ARRIVAL[min(len(ARRIVAL) - 1, max(0, round(distance / 0.5)))]


def loft_time(distance: float) -> float:
    """Seconds a lofted pass is in the air: up and down under gravity (drag shortens it a little)."""
    return 2 * loft_launch(distance)[1] / ball.GRAVITY


def dribble_speed(dribbling: float) -> float:
    """How fast a player can carry the ball, m/s (design): one definition for choosing and doing."""
    return 2.5 + 2.0 * dribbling


def ground_time(v0: float, distance: float) -> float:
    """Seconds for a ground pass struck at v0 to travel `distance` (inf if it stops short)."""
    i = min(len(SPEEDS) - 1, max(0, round((v0 - SPEEDS[0]) / 2.0)))
    dists, times = TABLES[i]
    k = bisect_left(dists, distance)
    return times[k] if k < len(dists) else math.inf


def _generic_time(distance: float) -> float:
    tau = 9.9 / 5.2
    if distance <= 0:
        return GENERIC_REACTION_S
    t = distance / 9.9 + tau
    for _ in range(8):
        f = 9.9 * t - 9.9 * tau * (1 - math.exp(-t / tau)) - distance
        t -= f / max(9.9 * (1 - math.exp(-t / tau)), 1e-6)
    return GENERIC_REACTION_S + max(t, 0.0)


GENERIC = [_generic_time(d * 0.25) for d in range(481)]  # 0 to 120 m, every 0.25 m


def generic_time(distance: float) -> float:
    """How long the passer assumes any player takes to cover a distance from standing, after
    reacting: an average body (acceleration about 5.2 m/s², top speed about 9.9 m/s)."""
    return GENERIC[min(len(GENERIC) - 1, max(0, round(distance / 0.25)))]


def sigmoid(x: float) -> float:
    return 1 / (1 + math.exp(-max(-30.0, min(30.0, x))))


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
    throw: bool = False  # Law 15: a throw-in, so every pass is thrown (lofted) and nothing else
    current: str | None = None  # what he is doing now (dribble or hold), for STICKY


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
    a = math.atan2(PITCH_Y / 2 + GOAL_HALF_WIDTH - y, abs(goal_x - x))
    b = math.atan2(PITCH_Y / 2 - GOAL_HALF_WIDTH - y, abs(goal_x - x))
    return abs(a - b)


def rate_at(distance: float) -> float:
    """D3: the real scoring rate of a central shot from this distance, between the anchors."""
    for (d0, r0), (d1, r1) in zip(SHOT_ANCHORS, SHOT_ANCHORS[1:], strict=False):
        if distance <= d1:
            return r0 + (r1 - r0) * (distance - d0) / (d1 - d0)
    return 0.0


def shot_estimate(x: float, y: float, goal_x: float, opponents: list[tuple[float, float]],
                  keeper: tuple[float, float] | None) -> float:
    """The player's own estimate of a shot from here, between 0 and 1: how often shots from this
    distance go in (D3), less from a tighter angle (by how much of the goal he can see compared with
    a central shot), halved for each defender he believes is in the shooting cone, reduced if the
    keeper stands on the line of the shot. The keeper is counted once, as the keeper."""
    d = math.hypot(goal_x - x, PITCH_Y / 2 - y)
    central = goal_angle(goal_x - math.copysign(d, goal_x - x), PITCH_Y / 2, goal_x)
    q = rate_at(d) * min(1.0, goal_angle(x, y, goal_x) / central) if central > 0 else 0.0
    for ox, oy in opponents:
        if (ox, oy) != keeper and in_cone(x, y, goal_x, ox, oy):  # the keeper is counted below
            q *= BLOCKER_FACTOR
    if keeper:
        cx, cy = goal_x, PITCH_Y / 2
        off = distance_to_segment(keeper[0], keeper[1], x, y, cx, cy)
        q *= 0.4 + 0.6 * min(1.0, off / 3.0)  # design: a well-placed keeper covers the shot
    return q


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


def loss_cost(x: float, y: float, goal_x: float) -> float:
    """What losing the ball here costs: what having it here is worth to the opponents."""
    own_goal = PITCH_X - goal_x
    return value(x, y, own_goal)


def pressure(scene: Scene) -> float:
    """0 to 1: how closely the nearest opponent presses, judged in a zone longer in front of the
    player (toward the goal he attacks) than behind him."""
    worst = 0.0
    for ox, oy in scene.opponents:
        ahead = (ox - scene.x) * attack(scene.goal_x) > 0
        reach = PRESSURE_FRONT_M if ahead else PRESSURE_BEHIND_M
        worst = max(worst, 1 - math.hypot(ox - scene.x, oy - scene.y) / reach)
    return max(0.0, worst)


def pass_confidence(scene: Scene, tx: float, ty: float, mx: float, my: float, age: float,
                    lofted: bool, pace: float = ARRIVE_MPS) -> float | None:
    """The passer's estimate that a pass to (tx, ty) reaches the team-mate at (mx, my) and is
    controlled: no opponent gets to the ball's path first, the team-mate gets there in time, and
    the ball arrives slowly enough to kill. None if a ground pass would stop short."""
    dist = math.hypot(tx - scene.x, ty - scene.y)
    v0 = launch_speed(dist, pace) if not lofted else 0.0
    arrive = ground_time(v0, dist) if not lofted else loft_time(dist)
    if not math.isfinite(arrive):
        return None
    confidence = 1.0
    for ox, oy in scene.opponents:  # can any opponent reach the ball's path before the ball?
        d, s = closest_on_segment(ox, oy, scene.x, scene.y, tx, ty)
        along = s * dist  # how far along the pass his closest point is
        if lofted and along < 0.8 * dist:
            continue  # the ball is over his head until it comes down
        t_ball = ground_time(v0, along) if not lofted else arrive
        if not math.isfinite(t_ball):
            t_ball = arrive
        confidence *= sigmoid((generic_time(max(0.0, d - 1.0)) - t_ball) / LANE_MARGIN_S)
    receiver_t = generic_time(math.hypot(tx - mx, ty - my))
    confidence *= sigmoid((arrive + 0.5 - receiver_t) / RECEIVE_MARGIN_S)
    # Can he control it when it gets there? A lofted ball arrives slower than it was struck (drag).
    arrival = loft_arrival(dist) if lofted else pace
    confidence *= sigmoid((CONTROL_EST_MPS - arrival) / CONTROL_MARGIN_MPS)
    return confidence * (0.8 if age > STALE_S else 1.0)


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
    lofted = scene.throw or dist > LOFT_OVER_M
    gain = value(tx, ty, scene.goal_x, scene.opponents, scene.keeper)
    space = min((math.hypot(ox - tx, oy - ty) for ox, oy in scene.opponents), default=10.0)
    gain *= 0.7 + 0.3 * min(1.0, space / 5.0)  # a receiver with space can do more with it
    # A pass that fails is lost along the lane or runs on to where it was aimed: the worse of the two.
    mx_, my_ = (scene.x + tx) / 2, (scene.y + ty) / 2
    lost = max(loss_cost(mx_, my_, scene.goal_x), loss_cost(tx, ty, scene.goal_x))
    best = None
    for pace in ((ARRIVE_MPS,) if lofted else PASS_PACES):  # he picks the pace the lane needs
        confidence = pass_confidence(scene, tx, ty, mx, my, age, lofted, pace)
        if confidence is None:
            continue
        ev = confidence * gain - (1 - confidence) * lost
        if best is None or ev > best.value:
            best = Option("pass", ev, (tx, ty), mid, lofted, pace)
    return best


def shot_chance(scene: Scene) -> float:
    """His estimate that a shot from here goes in. With measured tables (D7): how often shots from
    here went in, scaled by how this situation compares with an open one (blockers in the cone, the
    keeper's position), so shooting and moving the ball are judged on the same scale."""
    q = shot_estimate(scene.x, scene.y, scene.goal_x, scene.opponents, scene.keeper)
    if POSSESSION is None:
        return q
    open_shot = shot_estimate(scene.x, scene.y, scene.goal_x, [], None)
    measured = POSSESSION.finishing.at(scene.x, scene.y, scene.goal_x)
    return min(1.0, measured * q / open_shot) if open_shot > 0 else 0.0


def options(scene: Scene) -> list[Option]:
    out = [o for o in (pass_option(scene, mate) for mate in scene.mates) if o]
    if scene.throw:  # Law 15: a throw-in is thrown to someone; it is never a shot or a dribble
        return out
    here = value(scene.x, scene.y, scene.goal_x, scene.opponents, scene.keeper)
    p = pressure(scene)
    q = shot_chance(scene)
    if abs(scene.goal_x - scene.x) < 40:
        bias = 1.3 if "shoots_from_distance" in scene.traits else 1.0
        # A shot that fails is either blocked, leaving the ball at his feet for them, or missed or
        # saved, which gives the ball back from deep (a goal kick or the keeper's hands).
        blockers = sum(in_cone(scene.x, scene.y, scene.goal_x, ox, oy) for ox, oy in scene.opponents
                       if (ox, oy) != scene.keeper)
        blocked = 1 - BLOCKER_FACTOR ** blockers
        # A miss or a save gives them the ball deep in their own half (a goal kick or the keeper's).
        missed = loss_cost(scene.goal_x - attack(scene.goal_x) * GOAL_KICK_M, PITCH_Y / 2, scene.goal_x)
        lost = blocked * loss_cost(scene.x, scene.y, scene.goal_x) + (1 - blocked) * missed
        out.append(Option("shoot", q * bias * (1 + 0.5 * scene.risk) - (1 - q) * lost,
                          (scene.goal_x, PITCH_Y / 2)))
    for turn in (0.0, 0.8, -0.8):  # straight at goal, or angled away
        heading = math.atan2(PITCH_Y / 2 - scene.y, scene.goal_x - scene.x) + turn
        tx = scene.x + DRIBBLE_STEP_M * math.cos(heading)
        ty = scene.y + DRIBBLE_STEP_M * math.sin(heading)
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
            my_t = s * DRIBBLE_STEP_M / dribble_speed(scene.dribbling)
            win *= sigmoid((generic_time(d) - my_t) / RECEIVE_MARGIN_S)
        gain = value(tx, ty, scene.goal_x, scene.opponents, scene.keeper)
        ev = win * gain - (1 - win) * loss_cost(scene.x, scene.y, scene.goal_x)
        out.append(Option("dribble", ev + (STICKY if scene.current == "dribble" else 0.0), (tx, ty)))
    # Holding gains nothing and the defence reorganises while he waits (D9), so it keeps only part
    # of what the ball is worth here; under pressure it also risks losing it where he stands.
    hold = here * (1 - HOLD_DECAY) * (1 - p) - p * 0.5 * loss_cost(scene.x, scene.y, scene.goal_x)
    out.append(Option("hold", hold + (STICKY if scene.current == "hold" else 0.0)))
    if abs(scene.goal_x - scene.x) > CLEAR_FROM * PITCH_X:  # in his own third: long and away
        wide = 4.0 if scene.y < PITCH_Y / 2 else PITCH_Y - 4.0
        tx = scene.x + attack(scene.goal_x) * 45.0
        # A long ball away is a contest where it lands (an even one: design).
        contest = 0.5 * value(tx, wide, scene.goal_x) - 0.5 * loss_cost(tx, wide, scene.goal_x)
        out.append(Option("clear", contest, (tx, wide), lofted=True))
    return out


def temperature(scene: Scene) -> float:
    """Design: how loosely the player chooses, relative to how different his options are. A good
    decision-maker almost always takes the best option; pressure loosens his choice unless he is
    composed."""
    return (0.15 + 0.6 * (1 - scene.decisions)) * (1 + pressure(scene) * (1 - scene.composure))


def choose(scene: Scene, rng: random.Random) -> Option:
    opts = options(scene)
    values = [o.value for o in opts]
    mean = sum(values) / len(values)
    spread = math.sqrt(sum((v - mean) ** 2 for v in values) / len(values))
    # D4: the randomness is a share of how far apart the options are, so a choice between close
    # options is loose and one between clearly different options is not, wherever on the pitch.
    t = temperature(scene) * max(spread, 1e-4)
    top = max(o.value for o in opts)
    weights = [math.exp((o.value - top) / t) for o in opts]
    return rng.choices(opts, weights=weights)[0]
