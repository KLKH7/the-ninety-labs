"""Set pieces: how both teams set up for a corner, when it is taken, and where it is delivered.

Corners first (docs/ENGINE.md, layer 10). The routine is a plan of intentions, never a result:
each corner draws its own routine (who attacks which zone, where the runners wait, how many
defenders stay up, whether a team-mate goes short); the runners choose when to set off so they
arrive with the ball; the taker steps back, signals and runs up, and at the ball he chooses a
pass like any other (to where he believes a team-mate will be, D1) and strikes it with his own
execution error. Who gets to it, and whether it is cleared, saved or scored, is decided by the
ball's flight and the engine's contact rules. Constants cite docs/GROUNDING.md (S rows).
"""

from __future__ import annotations

import dataclasses
import math
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ninety.sim import ball, decisions, perception

if TYPE_CHECKING:  # pragma: no cover
    from ninety.sim.engine import Engine, Player

PITCH_X, PITCH_Y = 105.0, 68.0
CENTRE_Y = PITCH_Y / 2
CORNER_ARC_M = 1.0  # Law 1: the corner arc's radius
CORNER_DISTANCE_M = 9.15  # Law 17: opponents keep this far from the corner arc until it is in play
LAW_DISTANCE_M = CORNER_DISTANCE_M + CORNER_ARC_M  # the same, measured from the flag
STAND_OFF_M = LAW_DISTANCE_M + 0.5  # S1: a defender's spot, 0.5 m clear of the Law's distance
BALL_IN = 0.5  # S2 (design): the ball is placed this far in from both lines, 0.71 m from the flag
STRIKE_M = 0.26 + ball.RADIUS + 0.15  # S2: where he strikes from: body radius, ball, a gap behind it
APPROACH_M = (2.0, 4.0)  # S2 (design): after placing it he steps back this far for his run-up
APPROACH_ANGLE_DEG = 30.0  # S2 (design): up to this far either side of straight behind the ball
PLACE_S = 1.5  # S2 (verify): the taker places the ball before he steps back
SETTLED_M = 1.5  # S2 (design): a player this close to his spot is in position
SETTLED_MPS = 1.0  # S2 (design): or has stopped moving toward it (someone stands in the way)
TAKER_AT_M = 0.5  # S2 (design): the taker is at his spot
SET_UP_FAR_M = 10.0  # S2 (design): further than this from his spot a player runs to it, nearer he jogs
SECOND_PHASE_S = 4.0  # S3 (design): the routine holds after the kick until the ball is won or out
MARK_GOAL_SIDE_M = 1.0  # S4 (design): a man-marker stands this far goal-side of his attacker
REST_MARK_M = 2.0  # S5 (design): a rest defender stands this far goal-side of a counter-attacker
KEEPER_SPOT = (0.6, 0.5)  # S7 (design): the defending keeper, just off his line, toward the far post
OWN_BOX_EDGE_M = 16.0  # S5 (design): the attacking keeper waits this far from his own goal line

# S5 (design): attacking zones for a corner, as (depth from the goal line, offset across the goal
# toward the far post). Negative offsets are on the corner's side. Each corner moves every zone
# by up to ZONE_JITTER_M, so no two routines aim at the same points.
ATTACK_ZONES = {
    "near_post": (5.5, -3.0),
    "keeper": (1.5, -0.5),  # stands in front of the keeper, a screen
    "centre": (7.0, 0.5),
    "far_post": (5.0, 4.5),
    "spot": (11.0, 1.5),
    "edge": (18.5, 0.0),  # waits outside the box for a clearance
}
ZONE_JITTER_M = 1.5
BOX_ROLES = ("RCB", "LCB", "ST", "CM", "RW", "LW")  # S5 (design): who may go into the box
EDGE_ROLES = ("RCM", "LCM", "CM")  # S5 (design): who waits on the edge
TAKER_ROLES = ("RW", "LW", "RCM", "LCM", "CM", "RB", "LB")  # S6: the best crosser among these takes it
# S10 (design): attackers who attack a zone wait away from it, at a spot drawn for each corner
# this deep (from the goal line) and this far either side of their zone, and set off when they
# judge they will arrive with the ball.
RUNNING_ZONES = ("near_post", "centre", "far_post", "spot")
RUN_FROM_M = (11.0, 15.0)
RUN_SPREAD_M = 3.0
SHORT_CORNER_M = 15.0  # S8 (design): a team-mate this close to the ball may get it along the ground
SHORT_SETUP_SHARE = 0.15  # S8 (design, verify): corners where a team-mate goes short to the taker
SHORT_SPOT_M = (6.0, 10.0)  # S8 (design): how far from the ball, along the goal line
# S7 (design): defending zones, as (depth from the goal line, offset across toward the far post),
# filled in this order by whoever is not marking; "short_block" stands at the Law's distance in
# line with the ball.
DEFEND_ZONES = {"near_post_zone": (1.0, -4.5), "short_block": None, "edge_cover": (17.0, 0.0),
                "six_yard_near": (5.0, -2.0), "six_yard_far": (5.0, 2.5)}
COUNTER_ROLES = ("ST", "RW", "LW")  # S7 (design): defenders who may stay up for a counter-attack
LEFT_UP = (1, 2)  # S7 (design, verify): how many stay up, drawn for each corner
COUNTER_DEPTH_M = 50.0  # S7 (design): they wait this far from the goal being attacked, near halfway
SPARE_REST = (COUNTER_DEPTH_M + 8.0, 8.0)  # S5 (design): a rest defender with nobody to mark


def goal_line(attacking: str) -> float:
    return PITCH_X if attacking == "home" else 0.0


def into_pitch(attacking: str) -> float:
    """+1 when x grows away from the goal line being attacked."""
    return -1.0 if attacking == "home" else 1.0


@dataclass
class Corner:
    """The plan for one corner: who intends to go where, and the state of the delivery."""

    team: str  # the attacking team
    spot: tuple[float, float]  # the corner flag
    taker: str
    approach: tuple[float, float] = (0.0, 0.0)  # where the taker starts his run-up
    targets: dict[str, tuple[float, float]] = field(default_factory=dict)  # player -> (x, y)
    zones: dict[str, str] = field(default_factory=dict)  # attacking player -> zone name
    starts: dict[str, tuple[float, float]] = field(default_factory=dict)  # runner -> where he waits
    going: set[str] = field(default_factory=set)  # runners who have set off
    marks: dict[str, str] = field(default_factory=dict)  # defender -> attacker he marks
    left_up: list[str] = field(default_factory=list)  # defenders left up for the counter
    rest_marks: dict[str, str] = field(default_factory=dict)  # rest defender -> counter-attacker
    short_block: str | None = None
    placed_at: float | None = None
    signalled_at: float | None = None  # the taker has started his run-up
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
        """Unit vector from the ball toward the penalty spot."""
        bx, by = self.ball_spot
        tx, ty = self.zone_point(11.0, 0.0)
        d = math.hypot(tx - bx, ty - by)
        return (tx - bx) / d, (ty - by) / d

    @property
    def run_up(self) -> tuple[float, float]:
        """Where the taker places the ball from, and strikes it from: just behind it."""
        bx, by = self.ball_spot
        ux, uy = self.facing
        return bx - ux * STRIKE_M, by - uy * STRIKE_M


def plan(engine: Engine, team: str, spot: tuple[float, float]) -> Corner:
    """Draw this corner's routine. Intentions only: nothing here decides where the ball goes."""
    rng = engine.rng
    by_role = {p.role: p for p in engine.players if p.team == team}
    takers = [by_role[r] for r in TAKER_ROLES if r in by_role]
    taker = max(takers, key=lambda p: p.profile["crossing"])
    c = Corner(team, spot, taker.id)
    bx, by = c.ball_spot
    ux, uy = c.facing
    back = math.atan2(-uy, -ux) + math.radians(rng.uniform(-APPROACH_ANGLE_DEG, APPROACH_ANGLE_DEG))
    d = rng.uniform(*APPROACH_M)
    c.approach = (bx + math.cos(back) * d, by + math.sin(back) * d)
    used = {taker.id}
    # Who attacks which zone is drawn for each corner; one of the box players may go short.
    box = [by_role[r] for r in BOX_ROLES if r in by_role and by_role[r].id not in used]
    rng.shuffle(box)
    if rng.random() < SHORT_SETUP_SHARE and box:
        short = box.pop()
        along = rng.uniform(*SHORT_SPOT_M)
        c.targets[short.id] = (bx + into_pitch(team) * along, by + c.side * 1.5)
        c.zones[short.id] = "short"
        used.add(short.id)
    for p, zone in zip(box, [z for z in ATTACK_ZONES if z != "edge"], strict=False):
        add_to_zone(engine, c, p, zone)
        used.add(p.id)
    edge = next((by_role[r] for r in EDGE_ROLES if r in by_role and by_role[r].id not in used), None)
    if edge:
        add_to_zone(engine, c, edge, "edge")
        used.add(edge.id)
    defend(engine, c)
    # Rest defence: the keeper at the edge of his own box; everyone else left marks a defender
    # who stayed up, goal-side, and any spare stands between them and his own goal.
    counter = list(c.left_up)
    for p in engine.players:
        if p.team != team or p.id in used:
            continue
        if p.role == "GK":
            c.targets[p.id] = (goal_line(team) + into_pitch(team) * (PITCH_X - OWN_BOX_EDGE_M), CENTRE_Y)
        elif counter:
            c.rest_marks[p.id] = counter.pop(0)
        else:
            spare = len(c.targets) % 2
            c.targets[p.id] = c.zone_point(SPARE_REST[0], -SPARE_REST[1] if spare else SPARE_REST[1])
    return c


def add_to_zone(engine: Engine, c: Corner, p: Player, zone: str) -> None:
    depth, across = ATTACK_ZONES[zone]
    depth += engine.rng.uniform(-ZONE_JITTER_M, ZONE_JITTER_M)
    across += engine.rng.uniform(-ZONE_JITTER_M, ZONE_JITTER_M)
    c.zones[p.id] = zone
    c.targets[p.id] = c.zone_point(max(depth, 0.5), across)
    if zone in RUNNING_ZONES:
        start = engine.rng.uniform(*RUN_FROM_M)
        side = across + engine.rng.uniform(-RUN_SPREAD_M, RUN_SPREAD_M)
        c.starts[p.id] = c.zone_point(max(start, depth), side)


def defend(engine: Engine, c: Corner) -> None:
    """The defending team: the keeper on his line, one or two forwards left up, the best tacklers
    marking the attackers in the box, and the rest in zones (near post, against the short
    corner, the edge of the box, then the six-yard box)."""
    team = "away" if c.team == "home" else "home"
    defenders = [p for p in engine.players if p.team == team]
    keeper = next(p for p in defenders if p.role == "GK")
    c.targets[keeper.id] = c.zone_point(*KEEPER_SPOT)
    outfield = [p for p in defenders if p is not keeper]
    forwards = [p for p in outfield if p.role in COUNTER_ROLES]
    up = forwards[:engine.rng.choice(LEFT_UP)]
    for i, p in enumerate(up):
        c.left_up.append(p.id)
        c.targets[p.id] = c.zone_point(COUNTER_DEPTH_M, 10.0 if i else -10.0)
    rest = [p for p in outfield if p not in up]
    # Markers: the best tacklers take the attackers in the box, nearest to goal first.
    attackers = sorted((pid for pid, z in c.zones.items() if z in ATTACK_ZONES and z != "edge"),
                       key=lambda pid: abs(c.targets[pid][0] - goal_line(c.team)))
    markers = sorted(rest, key=lambda p: -p.profile["tackling"])
    for att, mk in zip(attackers, markers, strict=False):
        c.marks[mk.id] = att
    zonal = [p for p in rest if p.id not in c.marks]
    for p, (name, where) in zip(zonal, DEFEND_ZONES.items(), strict=False):
        if name == "short_block":  # in line with the ball, at the Law's distance plus the margin (S1)
            ux, uy = c.facing
            c.short_block = p.id
            c.targets[p.id] = (c.spot[0] + ux * STAND_OFF_M, c.spot[1] + uy * STAND_OFF_M)
        else:
            c.targets[p.id] = c.zone_point(*where)
    for p in zonal[len(DEFEND_ZONES):]:  # more than the zones: join the six-yard line
        c.targets[p.id] = c.zone_point(5.0, engine.rng.uniform(-3.0, 3.0))


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


def over(engine: Engine) -> bool:
    """S3: after the kick the routine holds until someone has the ball, play stops, or 4 s pass."""
    c: Corner | None = engine.set_play
    if c is None or c.delivered_at is None:
        return False
    return (engine.possessor is not None or engine.restart is not None
            or engine.t - c.delivered_at > SECOND_PHASE_S)


def taker_spot(engine: Engine, c: Corner) -> tuple[float, float] | None:
    """The taker goes to the ball and places it, steps back for his run-up, and once he has
    signalled runs up to strike it."""
    if c.delivered_at is not None:
        return None
    if c.placed_at is None or c.signalled_at is not None:
        return c.run_up
    return c.run_up if engine.t - c.placed_at < PLACE_S else c.approach


def target(engine: Engine, p: Player) -> tuple[float, float] | None:
    """Where this player wants to be during the corner, or None when the routine has no say."""
    c: Corner | None = engine.set_play
    if c is None:
        return None
    if p.id == c.taker:
        return taker_spot(engine, c)
    if p.id in c.marks:  # goal-side of his attacker
        att = engine.by_id[c.marks[p.id]]
        x, y = goal_side(att.x, att.y, goal_line(c.team), CENTRE_Y, MARK_GOAL_SIDE_M)
    elif p.id in c.rest_marks:  # goal-side of the counter-attacker, toward his own goal
        opp = engine.by_id[c.rest_marks[p.id]]
        x, y = goal_side(opp.x, opp.y, PITCH_X - goal_line(c.team), CENTRE_Y, REST_MARK_M)
    elif p.id in c.starts and p.id not in c.going:  # waiting to make his run
        x, y = c.starts[p.id]
    elif p.id in c.targets:
        x, y = c.targets[p.id]
    else:
        return None
    if p.team != c.team and c.delivered_at is None:
        x, y = keep_off(c, x, y)
    return x, y


def running(engine: Engine, p: Player) -> bool:
    """A runner who has set off, or a defender marking one: both go flat out."""
    c: Corner | None = engine.set_play
    if c is None:
        return False
    return p.id in c.going or c.marks.get(p.id) in c.going


def law_distance_kept(engine: Engine) -> bool:
    """Law 17: no opponent within 9.15 m of the corner arc."""
    c: Corner = engine.set_play
    return all(math.hypot(p.x - c.spot[0], p.y - c.spot[1]) >= LAW_DISTANCE_M
               for p in engine.players if p.team != c.team)


def at(p: Player, spot: tuple[float, float]) -> bool:
    return math.hypot(p.x - spot[0], p.y - spot[1]) <= TAKER_AT_M


def everyone_set(engine: Engine) -> bool:
    """Every player has reached his spot or stopped moving toward it, and the Law is kept."""
    c: Corner = engine.set_play
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


def time_to_ball(engine: Engine, c: Corner) -> float:
    """How long the taker needs to reach the ball from where he is (0 once he is there)."""
    taker = engine.by_id[c.taker]
    sx, sy = c.run_up
    gap = math.hypot(sx - taker.x, sy - taker.y)
    along = (taker.vx * (sx - taker.x) + taker.vy * (sy - taker.y)) / gap if gap > 1e-9 else 0.0
    return taker.physique.time_to_cover(gap, along)


def cross_time(distance: float) -> float:
    """Seconds a lofted cross takes to reach `distance`: the launch the taker would strike, flown by
    the engine's own ball physics (the passer's estimate does the same, lesson 23)."""
    points, _ = decisions.flight(*decisions.loft_launch(distance))
    t0, a0 = 0.0, 0.0
    for t, along, *_ in points:
        if along >= distance:
            return t0 + (t - t0) * (distance - a0) / (along - a0) if along > a0 else t
        t0, a0 = t, along
    return t0


def set_off(engine: Engine, c: Corner) -> None:
    """S10: each runner sets off when he judges that leaving now gets him to his zone as the
    ball arrives: the taker's time to the ball plus the cross's time in the air, against his own
    time to cover the gap. He responds to the signal after a simple reaction time (P12)."""
    if engine.t - c.signalled_at < perception.SIMPLE_REACTION_S:
        return
    bx, by = c.ball_spot
    still = time_to_ball(engine, c)
    for pid in c.starts:
        if pid in c.going:
            continue
        r = engine.by_id[pid]
        zx, zy = c.targets[pid]
        flight = cross_time(math.hypot(zx - bx, zy - by))
        if r.physique.time_to_cover(math.hypot(zx - r.x, zy - r.y), 0.0) >= still + flight:
            c.going.add(pid)


def advance(engine: Engine) -> bool:
    """One tick of the corner while the ball is dead. Returns True when the taker reaches the
    ball on his run-up: the moment he strikes it. The ball is placed when he first gets to it;
    he signals (the set-piece event) once he has stepped back, everyone is set and the Law's
    distance is kept (no timer: the time to restart emerges from the players)."""
    c: Corner = engine.set_play
    taker = engine.by_id[c.taker]
    if c.placed_at is None:
        if at(taker, c.run_up):  # a new ball: it may jump only while out of play (Law 9)
            c.placed_at = engine.t
            engine.ball = (*c.ball_spot, 0.0, 0.0, 0.0, 0.0)
        return False
    if c.signalled_at is None:
        face_ball(engine, taker)
        if engine.t - c.placed_at >= PLACE_S and at(taker, c.approach) and everyone_set(engine):
            c.signalled_at = engine.t
            engine.corner_ready()
        return False
    set_off(engine, c)
    return at(taker, c.run_up) and law_distance_kept(engine)


def strikeable(c: Corner, tx: float, ty: float) -> bool:
    """The target is in front of the ball as he runs up to it, so the struck ball moves away
    from his body."""
    bx, by = c.ball_spot
    ux, uy = c.facing
    return (tx - bx) * ux + (ty - by) * uy > 0


def choose_delivery(engine: Engine, taker: Player) -> decisions.Option | None:
    """At the ball, the taker picks a pass like any other (D1): to where he believes each
    team-mate will be, led by the velocity he has seen, scored on what he believes; a softmax
    picks (D4). Only targets in front of him can be struck. Beyond a short corner the ball goes
    through the air (S8): before heading existed (P18) the pass estimates rated every ball into a
    crowded box as hopeless and a ground ball won on a tie, so the delivery's height is fixed and
    only its target is chosen (whether that rule can now go is open, S8). The lofted-only scoring
    is the one a throw-in uses."""
    c: Corner = engine.set_play
    scene = engine.scene_for(taker)
    aerial = dataclasses.replace(scene, throw=True)  # pass_option scores lofted balls only
    bx, by = c.ball_spot
    opts = []
    for m in scene.mates:
        short = math.hypot(m[1] - bx, m[2] - by) <= SHORT_CORNER_M
        o = decisions.pass_option(scene if short else aerial, m)
        if o and strikeable(c, *o.target):
            opts.append(o)
    if not opts:
        return None
    t = decisions.temperature(scene)
    top = max(o.value for o in opts)
    weights = [math.exp((o.value - top) / t) for o in opts]
    return engine.rng.choices(opts, weights=weights)[0]


def intended(c: Corner, option: decisions.Option) -> tuple[float, float, float]:
    """The strike as the taker means it (before his execution error), from the shared pass
    estimates (D1): lofted, or along the ground at the pace he chose."""
    bx, by = c.ball_spot
    tx, ty = option.target
    dist = math.hypot(tx - bx, ty - by)
    if option.lofted:
        ground, up = decisions.loft_launch(dist)
    else:
        ground, up = decisions.launch_speed(dist, option.pace), 0.0
    return (tx - bx) / dist * ground, (ty - by) / dist * ground, up


def far_post(c: Corner) -> decisions.Option:
    """Nobody seen: a cross into the far side of the six-yard box."""
    return decisions.Option("pass", 0.0, c.zone_point(*ATTACK_ZONES["far_post"]), None, True)


def deliver(engine: Engine, taker: Player) -> None:
    """Strike the corner with the taker's own execution error. A delivery away from the line of
    his run-up is struck across his body (and may be his weaker foot)."""
    c: Corner = engine.set_play
    option = choose_delivery(engine, taker) or far_post(c)
    bx, by = engine.ball[0], engine.ball[1]
    skill = "crossing" if option.lofted else "passing"
    vx, vy, vz = engine.execute(taker, *intended(c, option), skill)
    engine.pass_target = option.target
    engine.intended = option.receiver
    engine.kicked = engine.emit("pass", taker.team, bx, by, player=taker.id,
                                ball_speed_kmh=round(math.sqrt(vx * vx + vy * vy + vz * vz) * 3.6, 1))
    engine.kick(taker, vx, vy, vz)
    c.delivered_at = engine.t


def face_ball(engine: Engine, taker: Player) -> None:
    """While he waits, the taker looks along his run-up toward the ball."""
    bx, by = engine.set_play.ball_spot
    taker.heading = math.atan2(by - taker.y, bx - taker.x)
