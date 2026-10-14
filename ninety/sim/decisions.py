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

from ninety.sim import ball

PITCH_X, PITCH_Y = 105.0, 68.0
GOAL_HALF_WIDTH = 3.66
DT = 1 / 25
GENERIC_REACTION_S = 0.365  # D1: how quickly the passer assumes an opponent reacts (P12)
LANE_MARGIN_S = 0.25  # D1: design: how sharply the passer's confidence falls as a lane closes
RECEIVE_MARGIN_S = 0.3  # design: the same for the receiver getting there in time
PRESSURE_FRONT_M, PRESSURE_BEHIND_M = 9.0, 3.0  # D2: pressure zone, longer in front than behind
SHOT_SHAPE = 0.75  # D3: the player's own estimate of a shot: 0.75 × (goal angle)², about 0.3 at
                   # 11 m central, 0.12 at 18 m, 0.03 at 35 m (the published shape of shot quality)
BLOCKER_FACTOR = 0.5  # design: each defender in the shooting cone halves the estimate
PROGRESS_VALUE = 0.04  # design: value of possession per 100 m nearer goal, beyond shot threat
LOSS_BASE = 0.02  # design: cost of losing the ball anywhere
STALE_S = 2.0  # design: a team-mate not seen for this long is a less certain option
DRIBBLE_STEP_M = 6.0
MAX_PASS_M = 45.0
LOFT_OVER_M = 25.0


def _ground_table() -> tuple[list[float], list[tuple[list[float], list[float]]]]:
    """For launch speeds 4 to 36 m/s, the time a ground pass takes to reach each distance."""
    speeds = [4.0 + 2.0 * i for i in range(17)]
    tables = []
    for v0 in speeds:
        path = ball.predict((0, 0, 0, v0, 0, 0), DT, 8.0)
        tables.append(([s[0] for s in path], [i * DT for i in range(len(path))]))
    return speeds, tables


SPEEDS, TABLES = _ground_table()
ARRIVE_MPS = 6.0  # design: the speed a ground pass is struck to arrive at
# The launch speed for a ground pass to arrive at ARRIVE_MPS, per 0.5 m of distance (0 to 45 m),
# solved once by ball physics rather than on every decision.
LAUNCH = [ball.ground_pass(max(d * 0.5, 0.5), ARRIVE_MPS, DT) for d in range(91)]


def launch_speed(distance: float) -> float:
    return LAUNCH[min(len(LAUNCH) - 1, max(0, round(distance / 0.5)))]


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


@dataclass
class Scene:
    """What the player on the ball believes, in the frame of the team he plays for."""
    x: float
    y: float
    goal_x: float  # the goal he attacks
    mates: list[tuple[str, float, float, float]]  # (id, x, y, seconds since seen)
    opponents: list[tuple[float, float]]  # believed positions
    keeper: tuple[float, float] | None  # believed opposition keeper
    decisions: float
    composure: float
    dribbling: float
    traits: tuple[str, ...]
    risk: float  # -1 protect a lead ... +1 chase the game


@dataclass
class Option:
    kind: str  # pass | shoot | dribble | hold | clear
    value: float
    target: tuple[float, float] | None = None
    receiver: str | None = None
    lofted: bool = False


def attack(goal_x: float) -> float:
    return 1.0 if goal_x > PITCH_X / 2 else -1.0


def goal_angle(x: float, y: float, goal_x: float) -> float:
    a = math.atan2(PITCH_Y / 2 + GOAL_HALF_WIDTH - y, abs(goal_x - x))
    b = math.atan2(PITCH_Y / 2 - GOAL_HALF_WIDTH - y, abs(goal_x - x))
    return abs(a - b)


def shot_estimate(x: float, y: float, goal_x: float, opponents: list[tuple[float, float]],
                  keeper: tuple[float, float] | None) -> float:
    """The player's own estimate of a shot from here: the goal angle, halved for each defender
    he believes is in the shooting cone, reduced if the keeper stands on the line of the shot."""
    q = SHOT_SHAPE * goal_angle(x, y, goal_x) ** 2
    for ox, oy in opponents:
        if in_cone(x, y, goal_x, ox, oy):
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


def distance_to_segment(px: float, py: float, ax: float, ay: float, bx: float, by: float) -> float:
    dx, dy = bx - ax, by - ay
    seg = dx * dx + dy * dy
    s = 0.0 if seg == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / seg))
    return math.hypot(ax + s * dx - px, ay + s * dy - py)


def value(x: float, y: float, goal_x: float) -> float:
    """What having the ball here is worth: the threat of a shot from it, plus progress."""
    progress = 1 - abs(goal_x - x) / PITCH_X
    return SHOT_SHAPE * goal_angle(x, y, goal_x) ** 2 + PROGRESS_VALUE * progress


def loss_cost(x: float, y: float, goal_x: float) -> float:
    """What losing the ball here costs: the threat the opponents gain from it."""
    own_goal = PITCH_X - goal_x
    return LOSS_BASE + value(x, y, own_goal)


def pressure(scene: Scene) -> float:
    """0 to 1: how closely the nearest opponent presses, judged in a zone longer in front of the
    player (toward the goal he attacks) than behind him."""
    worst = 0.0
    for ox, oy in scene.opponents:
        ahead = (ox - scene.x) * attack(scene.goal_x) > 0
        reach = PRESSURE_FRONT_M if ahead else PRESSURE_BEHIND_M
        worst = max(worst, 1 - math.hypot(ox - scene.x, oy - scene.y) / reach)
    return max(0.0, worst)


def pass_option(scene: Scene, mate: tuple[str, float, float, float]) -> Option | None:
    mid, mx, my, age = mate
    lead = 1.5 * attack(scene.goal_x)
    tx, ty = min(PITCH_X - 1, max(1.0, mx + lead)), my
    dist = math.hypot(tx - scene.x, ty - scene.y)
    if dist < 4 or dist > MAX_PASS_M:
        return None
    lofted = dist > LOFT_OVER_M
    v0 = launch_speed(dist) if not lofted else 0.0
    arrive = ground_time(v0, dist) if not lofted else dist / 16.0  # design: a lofted ball's flight
    if not math.isfinite(arrive):
        return None
    confidence = 1.0
    for ox, oy in scene.opponents:  # can any opponent reach the ball's path before the ball?
        d = distance_to_segment(ox, oy, scene.x, scene.y, tx, ty)
        along = math.hypot(ox - scene.x, oy - scene.y)
        if lofted and along < 0.8 * dist:
            continue  # the ball is over his head until it comes down
        reach_at = min(along, dist)
        t_ball = ground_time(v0, reach_at) if not lofted else arrive
        if not math.isfinite(t_ball):
            t_ball = arrive
        confidence *= sigmoid((generic_time(max(0.0, d - 1.0)) - t_ball) / LANE_MARGIN_S)
    receiver_t = generic_time(math.hypot(tx - mx, ty - my))
    confidence *= sigmoid((arrive + 0.5 - receiver_t) / RECEIVE_MARGIN_S)
    if age > STALE_S:
        confidence *= 0.8
    gain = value(tx, ty, scene.goal_x)
    space = min((math.hypot(ox - tx, oy - ty) for ox, oy in scene.opponents), default=10.0)
    gain *= 0.7 + 0.3 * min(1.0, space / 5.0)  # a receiver with space can do more with it
    mx_, my_ = (scene.x + tx) / 2, (scene.y + ty) / 2
    ev = confidence * gain - (1 - confidence) * loss_cost(mx_, my_, scene.goal_x)
    return Option("pass", ev, (tx, ty), mid, lofted)


def options(scene: Scene) -> list[Option]:
    here = value(scene.x, scene.y, scene.goal_x)
    p = pressure(scene)
    out: list[Option] = []
    for mate in scene.mates:
        o = pass_option(scene, mate)
        if o:
            out.append(o)
    q = shot_estimate(scene.x, scene.y, scene.goal_x, scene.opponents, scene.keeper)
    if abs(scene.goal_x - scene.x) < 40:
        bias = 1.3 if "shoots_from_distance" in scene.traits else 1.0
        out.append(Option("shoot", q * bias * (1 + 0.5 * scene.risk) - (1 - q) * LOSS_BASE,
                          (scene.goal_x, PITCH_Y / 2)))
    for turn in (0.0, 0.8, -0.8):  # straight at goal, or angled away
        heading = math.atan2(PITCH_Y / 2 - scene.y, scene.goal_x - scene.x) + turn
        tx = scene.x + DRIBBLE_STEP_M * math.cos(heading)
        ty = scene.y + DRIBBLE_STEP_M * math.sin(heading)
        if not (1 <= tx <= PITCH_X - 1 and 1 <= ty <= PITCH_Y - 1):
            continue
        my_t = DRIBBLE_STEP_M / (2.5 + 2.0 * scene.dribbling)
        their_t = min((generic_time(math.hypot(ox - tx, oy - ty)) for ox, oy in scene.opponents),
                      default=9.0)
        win = sigmoid((their_t - my_t) / RECEIVE_MARGIN_S)
        out.append(Option("dribble", win * value(tx, ty, scene.goal_x) - (1 - win) * loss_cost(
            scene.x, scene.y, scene.goal_x), (tx, ty)))
    out.append(Option("hold", here * (1 - p) - p * 0.5 * loss_cost(scene.x, scene.y, scene.goal_x)))
    if abs(scene.goal_x - scene.x) > 0.6 * PITCH_X:  # in his own third: the ball can go long and away
        wide = 4.0 if scene.y < PITCH_Y / 2 else PITCH_Y - 4.0
        out.append(Option("clear", -LOSS_BASE, (scene.x + attack(scene.goal_x) * 45.0, wide), lofted=True))
    return out


def temperature(scene: Scene) -> float:
    """Design: how loosely the player chooses. A good decision-maker almost always takes the best
    option; pressure loosens his choice unless he is composed."""
    return (0.004 + 0.02 * (1 - scene.decisions)) * (1 + pressure(scene) * (1 - scene.composure))


def choose(scene: Scene, rng: random.Random) -> Option:
    opts = options(scene)
    t = temperature(scene)
    top = max(o.value for o in opts)
    weights = [math.exp((o.value - top) / t) for o in opts]
    return rng.choices(opts, weights=weights)[0]
