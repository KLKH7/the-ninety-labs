"""Set pieces: how both teams set up for a corner, when it is taken, and where it is delivered.

Corners first (docs/ENGINE.md, layer 10). The routine is a plan of positions, never a result:
the attacking team sends its tallest-playing roles into named zones of the box and keeps a rest
defence; the defending team marks zones and players and sets its keeper; the taker chooses a
delivery from what he believes, the cross is struck with his own crossing error, and what
happens in the box (who gets to it, whether it is cleared, saved or scored) is decided by the
ball's flight and the engine's contact rules. Constants cite docs/GROUNDING.md (S rows).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ninety.sim import decisions

if TYPE_CHECKING:  # pragma: no cover
    from ninety.sim.engine import Engine, Player

PITCH_X, PITCH_Y = 105.0, 68.0
CENTRE_Y = PITCH_Y / 2
CORNER_ARC_M = 1.0  # Law 17 / Law 1: the corner arc's radius
CORNER_DISTANCE_M = 9.15  # Law 17: opponents keep this far from the corner arc until it is in play
STAND_OFF_M = CORNER_DISTANCE_M + CORNER_ARC_M + 0.5  # S1: measured from the flag; 0.5 m clear of the line
PLACE_S = 1.5  # S2 (verify): the taker places the ball and steps back before he can strike
SETTLED_M = 1.5  # S2 (design): a player this close to his spot is in position
SETTLED_MPS = 1.0  # S2 (design): or has stopped moving toward it (someone stands in the way)
SECOND_PHASE_S = 4.0  # S3 (design): the routine holds after the kick until the ball is won or out
MARK_GOAL_SIDE_M = 1.0  # S4 (design): a man-marker stands this far goal-side of his attacker

# S5 (design): attacking zones for a corner, as (depth from the goal line, offset across the goal
# toward the far post). Negative offsets are on the corner's side.
ATTACK_ZONES = {
    "near_post": (5.5, -3.0),
    "keeper": (1.5, -0.5),  # stands in front of the keeper
    "centre": (7.0, 0.5),
    "far_post": (5.0, 4.5),
    "spot": (11.0, 1.5),
    "edge": (18.5, 0.0),  # waits outside the box for a clearance
}
# S5 (design): who fills them, in order of preference by position (centre-backs and the striker
# attack the ball in the air; a midfielder waits on the edge).
ATTACK_ORDER = [("RCB", "centre"), ("LCB", "far_post"), ("ST", "near_post"), ("CM", "spot"),
                ("RW", "keeper"), ("LW", "keeper"), ("RCM", "edge"), ("LCM", "edge")]
TAKER_ROLES = ("RW", "LW", "RCM", "LCM", "CM", "RB", "LB")  # S6: the best crosser among these takes it
REST_DEFENCE = ("RB", "LB")  # S5 (design): full-backs stay back with the keeper
# S7 (design): defending zones, as (depth from the goal line, offset across toward the far post).
DEFEND_ZONES = {"near_post_zone": (1.0, -4.5), "six_yard_near": (5.0, -2.0),
                "six_yard_far": (5.0, 2.5), "front_post": (3.0, -1.0)}
COUNTER_ROLES = ("ST", "RW", "LW")  # S7 (design): defenders who stay up for a counter-attack


def goal_line(attacking: str) -> float:
    return PITCH_X if attacking == "home" else 0.0


def into_pitch(attacking: str) -> float:
    """+1 when x grows away from the goal line being attacked."""
    return -1.0 if attacking == "home" else 1.0


@dataclass
class Corner:
    """The plan for one corner: who stands where, and the state of the delivery."""

    team: str  # the attacking team
    spot: tuple[float, float]
    taker: str
    targets: dict[str, tuple[float, float]] = field(default_factory=dict)  # player -> (x, y)
    zones: dict[str, str] = field(default_factory=dict)  # attacking player -> zone name
    marks: dict[str, str] = field(default_factory=dict)  # defender -> attacker he marks
    placed_at: float | None = None
    delivered_at: float | None = None

    @property
    def side(self) -> float:
        """+1 if the corner is taken from y = 0, so the far post is toward larger y."""
        return 1.0 if self.spot[1] < CENTRE_Y else -1.0

    def zone_point(self, depth: float, across: float) -> tuple[float, float]:
        x = goal_line(self.team) + into_pitch(self.team) * depth
        return x, CENTRE_Y + self.side * across


def plan(engine: Engine, team: str, spot: tuple[float, float]) -> Corner:
    """Assign every player a spot for the corner. Positions only: nothing here decides an outcome."""
    by_role = {p.role: p for p in engine.players if p.team == team}
    takers = [by_role[r] for r in TAKER_ROLES if r in by_role]
    taker = max(takers, key=lambda p: p.profile["crossing"])
    c = Corner(team, spot, taker.id)
    used = {taker.id}
    for role, zone in ATTACK_ORDER:
        p = by_role.get(role)
        if p is None or p.id in used or zone in c.zones.values():
            continue
        c.zones[p.id] = zone
        c.targets[p.id] = c.zone_point(*ATTACK_ZONES[zone])
        used.add(p.id)
    for p in engine.players:  # rest defence: everyone else of the attacking team holds back
        if p.team == team and p.id not in used:
            depth = 40.0 if p.role != "GK" else PITCH_X - 16.0
            across = 0.0 if p.role == "GK" else (-12.0 if p.role in ("RB", "RCM") else 12.0)
            c.targets[p.id] = (goal_line(team) + into_pitch(team) * depth, CENTRE_Y + across)
    defend(engine, c)
    return c


def defend(engine: Engine, c: Corner) -> None:
    """The defending team: the keeper on his line, zonal players at the near post and across the
    six-yard box, everyone else marks an attacker in the box, and two stay up for the counter."""
    team = "away" if c.team == "home" else "home"
    defenders = [p for p in engine.players if p.team == team]
    keeper = next(p for p in defenders if p.role == "GK")
    c.targets[keeper.id] = c.zone_point(0.6, 0.5)
    outfield = [p for p in defenders if p is not keeper]
    counter = [p for p in outfield if p.role in COUNTER_ROLES][:2]
    for i, p in enumerate(counter):
        c.targets[p.id] = (goal_line(c.team) + into_pitch(c.team) * 45.0, CENTRE_Y + (-10.0 if i else 10.0))
    rest = [p for p in outfield if p not in counter]
    # Markers: the best tacklers take the attackers in the box, nearest to goal first.
    attackers = sorted((pid for pid in c.zones if c.zones[pid] != "edge"),
                       key=lambda pid: ATTACK_ZONES[c.zones[pid]][0])
    markers = sorted(rest, key=lambda p: -p.profile["tackling"])
    for att, mk in zip(attackers, markers, strict=False):
        c.marks[mk.id] = att
    zonal = [p for p in rest if p.id not in c.marks]
    for p, (_, (depth, across)) in zip(zonal, DEFEND_ZONES.items(), strict=False):
        c.targets[p.id] = c.zone_point(depth, across)
    for p in zonal[len(DEFEND_ZONES):]:  # anyone left covers the edge of the box
        c.targets[p.id] = c.zone_point(17.0, -4.0 + 8.0 * (zonal.index(p) % 2))


def keep_off(c: Corner, x: float, y: float) -> tuple[float, float]:
    """Law 17: push a defender's spot out to STAND_OFF_M from the corner flag if it is closer."""
    dx, dy = x - c.spot[0], y - c.spot[1]
    d = math.hypot(dx, dy)
    if d >= STAND_OFF_M:
        return x, y
    if d < 1e-6:
        dx, dy, d = into_pitch(c.team), c.side, math.sqrt(2)
    return c.spot[0] + dx / d * STAND_OFF_M, c.spot[1] + dy / d * STAND_OFF_M


def target(engine: Engine, p: Player) -> tuple[float, float] | None:
    """Where this player wants to be during the corner, or None when the routine no longer applies."""
    c: Corner | None = engine.set_play
    if c is None:
        return None
    if c.delivered_at is not None:
        won = engine.possessor is not None
        if won or engine.restart is not None or engine.t - c.delivered_at > SECOND_PHASE_S:
            engine.set_play = None
            return None
    if p.id == c.taker:
        return c.spot if c.delivered_at is None else None
    if p.id in c.marks:
        att = engine.by_id[c.marks[p.id]]
        gx, gy = goal_line(c.team), CENTRE_Y
        d = math.hypot(gx - att.x, gy - att.y) or 1.0
        x, y = att.x + (gx - att.x) / d * MARK_GOAL_SIDE_M, att.y + (gy - att.y) / d * MARK_GOAL_SIDE_M
    elif p.id in c.targets:
        x, y = c.targets[p.id]
    else:
        return None
    if p.team != c.team and c.delivered_at is None:
        x, y = keep_off(c, x, y)
    return x, y


def ready(engine: Engine) -> bool:
    """The corner can be taken once the ball is placed and everyone has reached his spot or
    stopped trying to (someone stands in the way). Time to restart emerges; there is no timer."""
    c: Corner = engine.set_play
    taker = engine.by_id[c.taker]
    if math.hypot(taker.x - c.spot[0], taker.y - c.spot[1]) > 1.0:
        return False
    if c.placed_at is None:
        c.placed_at = engine.t
    if engine.t - c.placed_at < PLACE_S:
        return False
    for p in engine.players:
        if p.id == c.taker:
            continue
        spot = target(engine, p)
        if spot is None:
            continue
        far = math.hypot(spot[0] - p.x, spot[1] - p.y) > SETTLED_M
        moving = math.hypot(p.vx, p.vy) > SETTLED_MPS
        if far and moving:
            return False
    return True


def choose_delivery(engine: Engine, taker: Player) -> tuple[float, float, str | None]:
    """The taker picks where to put the cross from what he believes: each attacker's zone (or a
    short ball to a team-mate nearby) is worth its threat times his estimate that it gets there
    before a defender, minus the cost of losing it. A softmax picks, as for any decision."""
    c: Corner = engine.set_play
    scene = engine.scene_for(taker)
    opts: list[decisions.Option] = []
    for mid, mx, my, age in scene.mates:
        zone = c.zones.get(mid)
        short = math.hypot(mx - scene.x, my - scene.y) <= 15.0
        if zone is None and not short:
            continue
        tx, ty = (mx, my) if short else c.zone_point(*ATTACK_ZONES[zone])
        lofted = not short
        conf = decisions.pass_confidence(scene, tx, ty, mx, my, age, lofted)
        if conf is None:
            continue
        gain = decisions.value(tx, ty, scene.goal_x, scene.opponents, scene.keeper)
        lost = decisions.loss_cost(tx, ty, scene.goal_x)
        opts.append(decisions.Option("pass", conf * gain - (1 - conf) * lost, (tx, ty), mid, lofted))
    if not opts:  # nobody seen: aim at the far side of the six-yard box
        return (*c.zone_point(*ATTACK_ZONES["far_post"]), None)
    t = decisions.temperature(scene)
    top = max(o.value for o in opts)
    weights = [math.exp((o.value - top) / t) for o in opts]
    o = engine.rng.choices(opts, weights=weights)[0]
    return (*o.target, o.receiver)


def deliver(engine: Engine, taker: Player) -> None:
    """Strike the corner: a cross with the taker's own crossing error, or a short pass."""
    c: Corner = engine.set_play
    tx, ty, _ = choose_delivery(engine, taker)
    bx, by = engine.ball[0], engine.ball[1]
    dist = math.hypot(tx - bx, ty - by)
    short = dist <= 15.0
    ground, up = (decisions.launch_speed(dist), 0.0) if short else decisions.loft_launch(dist)
    taker.heading = math.atan2(ty - by, tx - bx)
    vx, vy, vz = engine.execute(taker, *engine.aim(bx, by, tx, ty, ground, up),
                                "passing" if short else "crossing")
    engine.kicked = engine.emit("pass", taker.team, bx, by, player=taker.id,
                                ball_speed_kmh=round(math.sqrt(vx * vx + vy * vy + vz * vz) * 3.6, 1))
    engine.kick(taker, vx, vy, vz)
    c.delivered_at = engine.t
