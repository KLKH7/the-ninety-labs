"""Set pieces: how both teams set up for a corner, when it is taken, and where it is delivered.

Corners first (docs/ENGINE.md, layer 10). The routine is a plan of positions, never a result:
the attacking team sends players into named zones of the box and keeps a rest defence on the
opponents left up for a counter; the defending team marks players and zones and sets its
keeper; the taker chooses a delivery from what he believes, and the cross is struck with his
own execution error. What happens next (who gets to it, whether it is cleared, saved or scored)
is decided by the ball's flight and the engine's contact rules. Constants cite
docs/GROUNDING.md (S rows).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ninety.sim import ball, decisions

if TYPE_CHECKING:  # pragma: no cover
    from ninety.sim.engine import Engine, Player

PITCH_X, PITCH_Y = 105.0, 68.0
CENTRE_Y = PITCH_Y / 2
CORNER_ARC_M = 1.0  # Law 1: the corner arc's radius
CORNER_DISTANCE_M = 9.15  # Law 17: opponents keep this far from the corner arc until it is in play
LAW_DISTANCE_M = CORNER_DISTANCE_M + CORNER_ARC_M  # the same, measured from the flag
STAND_OFF_M = LAW_DISTANCE_M + 0.5  # S1: a defender's spot, 0.5 m clear of the Law's distance
BALL_IN = 0.5  # S2 (design): the ball is placed this far in from both lines, 0.71 m from the flag
RUN_UP_M = 0.26 + ball.RADIUS + 0.15  # S2: the taker stands behind the ball: body radius, ball, a gap
PLACE_S = 1.5  # S2 (verify): the taker places the ball and steps back before he can strike
SETTLED_M = 1.5  # S2 (design): a player this close to his spot is in position
SETTLED_MPS = 1.0  # S2 (design): or has stopped moving toward it (someone stands in the way)
TAKER_AT_M = 0.5  # S2 (design): the taker is at his run-up spot
SECOND_PHASE_S = 4.0  # S3 (design): the routine holds after the kick until the ball is won or out
MARK_GOAL_SIDE_M = 1.0  # S4 (design): a man-marker stands this far goal-side of his attacker
REST_MARK_M = 2.0  # S5 (design): a rest defender stands this far goal-side of a counter-attacker
SHORT_CORNER_M = 15.0  # S8 (design): a team-mate this close is a short option
SHORT_BLOCK_M = 5.0  # S7 (design): the defender against a short corner aims this far out (then kept off)

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
# S5 (design): who fills them, by position (centre-backs and the striker go into the box; a
# midfielder waits on the edge).
ATTACK_ORDER = [("RCB", "centre"), ("LCB", "far_post"), ("ST", "near_post"), ("CM", "spot"),
                ("RW", "keeper"), ("LW", "keeper"), ("RCM", "edge"), ("LCM", "edge")]
TAKER_ROLES = ("RW", "LW", "RCM", "LCM", "CM", "RB", "LB")  # S6: the best crosser among these takes it
# S7 (design): defending zones, as (depth from the goal line, offset across toward the far post),
# plus one defender against the short corner, kept at the Law's distance from the ball.
DEFEND_ZONES = {"near_post_zone": (1.0, -4.5), "short_block": None, "six_yard_near": (5.0, -2.0),
                "six_yard_far": (5.0, 2.5)}
COUNTER_ROLES = ("ST", "RW", "LW")  # S7 (design): defenders who stay up for a counter-attack
COUNTER_DEPTH_M = 50.0  # S7 (design): they wait this far from the goal being attacked, near halfway


def goal_line(attacking: str) -> float:
    return PITCH_X if attacking == "home" else 0.0


def into_pitch(attacking: str) -> float:
    """+1 when x grows away from the goal line being attacked."""
    return -1.0 if attacking == "home" else 1.0


@dataclass
class Corner:
    """The plan for one corner: who stands where, and the state of the delivery."""

    team: str  # the attacking team
    spot: tuple[float, float]  # the corner flag
    taker: str
    targets: dict[str, tuple[float, float]] = field(default_factory=dict)  # player -> (x, y)
    zones: dict[str, str] = field(default_factory=dict)  # attacking player -> zone name
    marks: dict[str, str] = field(default_factory=dict)  # defender -> attacker he marks
    rest_marks: dict[str, str] = field(default_factory=dict)  # rest defender -> counter-attacker
    short_block: str | None = None
    placed_at: float | None = None
    delivered_at: float | None = None

    @property
    def side(self) -> float:
        """+1 if the corner is taken from y = 0, so the far post is toward larger y."""
        return 1.0 if self.spot[1] < CENTRE_Y else -1.0

    def zone_point(self, depth: float, across: float) -> tuple[float, float]:
        x = goal_line(self.team) + into_pitch(self.team) * depth
        return x, CENTRE_Y + self.side * across

    @property
    def ball_spot(self) -> tuple[float, float]:
        """Law 17: the ball is placed in the corner area (S2: 0.5 m in from both lines)."""
        return self.spot[0] + into_pitch(self.team) * BALL_IN, self.spot[1] + self.side * BALL_IN

    @property
    def facing(self) -> tuple[float, float]:
        """Unit vector from the ball toward the penalty spot: the way the taker faces."""
        bx, by = self.ball_spot
        tx, ty = self.zone_point(11.0, 0.0)
        d = math.hypot(tx - bx, ty - by)
        return (tx - bx) / d, (ty - by) / d

    @property
    def run_up(self) -> tuple[float, float]:
        """Where the taker stands: behind the ball, so the struck ball moves away from his body."""
        bx, by = self.ball_spot
        ux, uy = self.facing
        return bx - ux * RUN_UP_M, by - uy * RUN_UP_M


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
    defend(engine, c)
    # Rest defence: the keeper at the edge of his own box; everyone else left marks a
    # counter-attacker goal-side, and any spare stands between them and his own goal.
    counter = [pid for pid in c.targets if engine.by_id[pid].team != team
               and engine.by_id[pid].role in COUNTER_ROLES]
    rest = [p for p in engine.players if p.team == team and p.id not in used]
    for p in rest:
        if p.role == "GK":
            c.targets[p.id] = (goal_line(team) + into_pitch(team) * (PITCH_X - 16.0), CENTRE_Y)
        elif counter:
            c.rest_marks[p.id] = counter.pop(0)
        else:
            spare = len(c.targets) % 2
            c.targets[p.id] = c.zone_point(COUNTER_DEPTH_M + 8.0, -8.0 if spare else 8.0)
    return c


def defend(engine: Engine, c: Corner) -> None:
    """The defending team: the keeper on his line, players marking each attacker in the box,
    zones at the near post and across the six-yard box, one against the short corner, and two
    left up for the counter-attack."""
    team = "away" if c.team == "home" else "home"
    defenders = [p for p in engine.players if p.team == team]
    keeper = next(p for p in defenders if p.role == "GK")
    c.targets[keeper.id] = c.zone_point(0.6, 0.5)
    outfield = [p for p in defenders if p is not keeper]
    counter = [p for p in outfield if p.role in COUNTER_ROLES][:2]
    for i, p in enumerate(counter):
        c.targets[p.id] = c.zone_point(COUNTER_DEPTH_M, 10.0 if i else -10.0)
    rest = [p for p in outfield if p not in counter]
    # Markers: the best tacklers take the attackers in the box, nearest to goal first.
    attackers = sorted((pid for pid in c.zones if c.zones[pid] != "edge"),
                       key=lambda pid: ATTACK_ZONES[c.zones[pid]][0])
    markers = sorted(rest, key=lambda p: -p.profile["tackling"])
    for att, mk in zip(attackers, markers, strict=False):
        c.marks[mk.id] = att
    zonal = [p for p in rest if p.id not in c.marks]
    for p, (name, where) in zip(zonal, DEFEND_ZONES.items(), strict=False):
        if name == "short_block":
            ux, uy = c.facing
            c.short_block = p.id
            c.targets[p.id] = (c.spot[0] + ux * SHORT_BLOCK_M, c.spot[1] + uy * SHORT_BLOCK_M)
        else:
            c.targets[p.id] = c.zone_point(*where)
    for i, p in enumerate(zonal[len(DEFEND_ZONES):]):  # anyone left covers the edge of the box
        c.targets[p.id] = c.zone_point(17.0, -4.0 if i % 2 == 0 else 4.0)


def keep_off(c: Corner, x: float, y: float) -> tuple[float, float]:
    """Law 17: push a defender's spot out to STAND_OFF_M from the corner flag if it is closer."""
    dx, dy = x - c.spot[0], y - c.spot[1]
    d = math.hypot(dx, dy)
    if d >= STAND_OFF_M:
        return x, y
    if d < 1e-6:
        (dx, dy), d = c.facing, 1.0
    return c.spot[0] + dx / d * STAND_OFF_M, c.spot[1] + dy / d * STAND_OFF_M


def goal_side(px: float, py: float, gx: float, gy: float, gap: float) -> tuple[float, float]:
    d = math.hypot(gx - px, gy - py) or 1.0
    return px + (gx - px) / d * gap, py + (gy - py) / d * gap


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
        return c.run_up if c.delivered_at is None else None
    if p.id in c.marks:  # goal-side of his attacker
        att = engine.by_id[c.marks[p.id]]
        x, y = goal_side(att.x, att.y, goal_line(c.team), CENTRE_Y, MARK_GOAL_SIDE_M)
    elif p.id in c.rest_marks:  # goal-side of the counter-attacker, toward his own goal
        opp = engine.by_id[c.rest_marks[p.id]]
        x, y = goal_side(opp.x, opp.y, PITCH_X - goal_line(c.team), CENTRE_Y, REST_MARK_M)
    elif p.id in c.targets:
        x, y = c.targets[p.id]
    else:
        return None
    if p.team != c.team and c.delivered_at is None:
        x, y = keep_off(c, x, y)
    return x, y


def law_distance_kept(engine: Engine) -> bool:
    """Law 17: no opponent within 9.15 m of the corner arc."""
    c: Corner = engine.set_play
    return all(math.hypot(p.x - c.spot[0], p.y - c.spot[1]) >= LAW_DISTANCE_M
               for p in engine.players if p.team != c.team)


def ready(engine: Engine) -> bool:
    """The corner can be taken once the taker has placed the ball (PLACE_S after reaching it),
    every player has reached his spot or stopped moving toward it, and no opponent is inside the
    Law's distance. Time to restart emerges from the players; there is no timer."""
    c: Corner = engine.set_play
    taker = engine.by_id[c.taker]
    rx, ry = c.run_up
    if math.hypot(taker.x - rx, taker.y - ry) > TAKER_AT_M:
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
    return law_distance_kept(engine)


def strikeable(c: Corner, tx: float, ty: float) -> bool:
    """The target is in front of the taker, so the struck ball moves away from his body."""
    bx, by = c.ball_spot
    ux, uy = c.facing
    return (tx - bx) * ux + (ty - by) * uy > 0


def choose_delivery(engine: Engine, taker: Player) -> tuple[float, float]:
    """The taker picks where to put the corner from what he believes: each attacker's zone (or a
    short ball to a team-mate nearby) is worth its threat times his estimate that it gets there
    before a defender, minus the cost of losing it. A softmax picks, as for any decision."""
    c: Corner = engine.set_play
    scene = engine.scene_for(taker)
    opts: list[decisions.Option] = []
    for mid, mx, my, age in scene.mates:
        zone = c.zones.get(mid)
        short = math.hypot(mx - scene.x, my - scene.y) <= SHORT_CORNER_M
        if zone is None and not short:
            continue
        tx, ty = (mx, my) if short else c.zone_point(*ATTACK_ZONES[zone])
        if not strikeable(c, tx, ty):
            continue
        conf = decisions.pass_confidence(scene, tx, ty, mx, my, age, lofted=not short)
        if conf is None:
            continue
        gain = decisions.value(tx, ty, scene.goal_x, scene.opponents, scene.keeper)
        lost = decisions.loss_cost(tx, ty, scene.goal_x)
        opts.append(decisions.Option("pass", conf * gain - (1 - conf) * lost, (tx, ty), mid, not short))
    if not opts:  # nobody seen: into the far side of the six-yard box
        return c.zone_point(*ATTACK_ZONES["far_post"])
    t = decisions.temperature(scene)
    top = max(o.value for o in opts)
    weights = [math.exp((o.value - top) / t) for o in opts]
    return engine.rng.choices(opts, weights=weights)[0].target


def intended(c: Corner, tx: float, ty: float) -> tuple[float, float, float]:
    """The strike as the taker means it (before his execution error): a ground pass for a short
    corner, a lofted cross otherwise, both from the shared pass estimates (D1)."""
    bx, by = c.ball_spot
    dist = math.hypot(tx - bx, ty - by)
    short = dist <= SHORT_CORNER_M
    ground, up = (decisions.launch_speed(dist), 0.0) if short else decisions.loft_launch(dist)
    return (tx - bx) / dist * ground, (ty - by) / dist * ground, up


def deliver(engine: Engine, taker: Player) -> None:
    """Strike the corner with the taker's own execution error. He faces the ball from behind it,
    so a delivery away from that line is struck across his body (and may be his weaker foot)."""
    c: Corner = engine.set_play
    tx, ty = choose_delivery(engine, taker)
    bx, by = engine.ball[0], engine.ball[1]
    short = math.hypot(tx - bx, ty - by) <= SHORT_CORNER_M
    vx, vy, vz = engine.execute(taker, *intended(c, tx, ty), "passing" if short else "crossing")
    engine.kicked = engine.emit("pass", taker.team, bx, by, player=taker.id,
                                ball_speed_kmh=round(math.sqrt(vx * vx + vy * vy + vz * vz) * 3.6, 1))
    engine.kick(taker, vx, vy, vz)
    c.delivered_at = engine.t


def face_ball(engine: Engine, taker: Player) -> None:
    """While waiting to strike, the taker stands behind the ball looking along his run-up (the
    ball is too close for perception.facing to turn him toward it)."""
    ux, uy = engine.set_play.facing
    taker.heading = math.atan2(uy, ux)
