"""Off-the-ball decisions: where players go when they do not have the ball.

Each is an intention with the trigger the research describes, chosen from what the player
believes, never an outcome: a keeper narrows the angle and comes out to an attacker through on
goal; defenders mark the attackers who threaten the goal; team-mates of the ball carrier offer
support and make runs in behind when the carrier can play them. Docs: docs/ENGINE.md layer 6,
docs/GROUNDING.md rows O1 to O5.
"""

from __future__ import annotations

import math

from ninety.sim import ball, fmath
from ninety.sim.body import (
    BODY_RADIUS,
    BRAKE_MAX,
    COM_SHARE,
    CONTROL_M,
    FOOT_REACH_Z,
    GRAVITY,
    KEEPER_JUMP_M,
    KEEPER_STATURE_M,
    STANDING_REACH_SHARE,
)
from ninety.sim.perception import CHOICE_REACTION_S

PITCH_X, PITCH_Y = 105.0, 68.0
GOAL_HALF_WIDTH = 3.66
KEEPER_STAND_REACH_M = 1.0  # P11: a keeper's sideways arm reach from the body's centre
# P11: his reach envelope. His hands reach anywhere within KEEPER_ARM_M of his centre of mass (the
# body straight, the arms stretched beyond the head: standing reach less the centre of mass's
# height), sideways no further yet than his arms have stretched over the dive.
KEEPER_COM_Z = KEEPER_STATURE_M * COM_SHARE
KEEPER_ARM_M = KEEPER_STATURE_M * (STANDING_REACH_SHARE - COM_SHARE)
KEEPER_DIVE_EXTRA_M = KEEPER_ARM_M - KEEPER_STAND_REACH_M  # added as the dive stretches him out
# P15: keepers start the sideways part of a save before the kick but the upward part only about
# 245 ms after it, once they see where the ball is going (Higueras-Herbada et al. 2020).
UP_AFTER_CONTACT_S = 0.245
SHOT_AIM_Z_M = (0.1, 2.0)  # design: the heights shots are aimed at (engine.shoot)
# P15: a dive launches the body sideways about 1.4 to 1.5 m (centre of mass, peak 3.6 to 4.0 m/s;
# Monteiro et al. 2022, Sci. Rep.), pushed off over about 0.48 s of ground contact (Ibrahim et al.
# 2019, J. Sports Sci.): so it speeds up at about 7.9 m/s², within what legs give (P2), then carries
# that speed.
KEEPER_DIVE_TRAVEL_M = 1.45
DIVE_PEAK_MPS = 3.8  # P15: the body's peak sideways speed (3.6 to 4.0)
DIVE_PUSH_OFF_S = 0.48  # P15: how long the push-off lasts, speeding him up to DIVE_PEAK_MPS
DIVE_TIME_S = DIVE_PUSH_OFF_S / 2 + KEEPER_DIVE_TRAVEL_M / DIVE_PEAK_MPS  # a full dive: about 0.62 s
KEEPER_DOWN_S = 0.8  # design, verify: how long a keeper is on the ground after a dive
SHOT_SPEEDS_KMH = (70.0, 120.0)  # design, verify: the speeds shots are struck at (engine.shoot)
SHOT_SPEED_SAMPLES = 8  # how finely that range is averaged over
SHOT_HEIGHT_SAMPLES = 4  # and the heights shots are aimed at
KEEPER_DEPTH = (1.0, 6.0)  # O1: design, verify: how far off his line he stands
SHOT_RANGE_M = 40.0  # design: a shot is an option inside this distance of the goal's centre, straight-line
RUSH_RANGE_M = 18.0  # O1: design: an attacker this close and through on goal draws the keeper out
CLOSE_DOWN_M = 2.0  # O1: design: how close the keeper gets to narrow the angle
DANGER_RANGE_M = 25.0  # O2: design: attackers this near our goal are marked man to man
MARK_GOAL_SIDE_M = 1.5  # O2: design: a marker stands this far goal-side of his man
ZONE_RADIUS_M = 5.0  # O2: design: a block defender's zone around his place, about half the block's spacing
SUPPORT_RANGE_M = (8.0, 14.0)  # O3: a diagonal option about 5 to 15 m from the ball
RUN_BEYOND_M = 10.0  # O4: design: a run in behind aims this far beyond the defensive line


def keeper_depth_m(distance: float) -> float:
    """O1: how far off his line the keeper sets himself with the ball this far from his goal's
    centre: near his line against a near shot, where his reaction time is shortest, further out the
    further the ball is, up to his sweeping spot at the edge of shooting range (*design*, *verify*:
    one published figure, an average of 4.8 m off the line with the ball in his own third, FIFA
    Club World Cup 2021). Coming out to an attacker through on goal is the rush (close_down_spot)."""
    lo, hi = KEEPER_DEPTH
    return lo + (hi - lo) * min(1.0, max(0.0, distance) / SHOT_RANGE_M)


def keeper_spot(ball_x: float, ball_y: float, own_goal_x: float) -> tuple[float, float]:
    """O1: on the line that bisects the angle between the posts as seen from the ball, keeper_depth_m
    off his line, and never outside the posts: on a tight angle, where the bisector leaves the goal
    mouth, he comes back along it until he stands within them (*design*). Never nearer the ball than
    when he rushes out to close it down; with the ball almost on his line he stays on it, between
    the posts."""
    gy = PITCH_Y / 2
    a1 = fmath.atan2(gy - GOAL_HALF_WIDTH - ball_y, own_goal_x - ball_x)
    a2 = fmath.atan2(gy + GOAL_HALF_WIDTH - ball_y, own_goal_x - ball_x)
    mid = fmath.atan2(fmath.sin(a1) + fmath.sin(a2), fmath.cos(a1) + fmath.cos(a2))
    ux, uy = fmath.cos(mid), fmath.sin(mid)  # from the ball toward the goal, between the posts
    if abs(ux) < 1e-6:
        return own_goal_x, gy
    to_line = (own_goal_x - ball_x) / ux  # along the bisector to the goal line
    along = to_line - keeper_depth_m(math.hypot(own_goal_x - ball_x, gy - ball_y)) / abs(ux)
    off = ball_y + uy * along - gy
    if abs(off) > GOAL_HALF_WIDTH and abs(uy) > 1e-9:  # outside the posts: back along the bisector
        along = (gy + math.copysign(GOAL_HALF_WIDTH, off) - ball_y) / uy
    if along < CLOSE_DOWN_M:  # the ball is almost on his line: he stays on it, between the posts
        return own_goal_x, min(gy + GOAL_HALF_WIDTH, max(gy - GOAL_HALF_WIDTH, ball_y))
    return ball_x + ux * along, ball_y + uy * along


def open_goal_share(x: float, y: float, goal_x: float, keeper: tuple[float, float]) -> float:
    """The share of the goal mouth, as seen from (x, y), that a keeper at `keeper` cannot get a hand
    across before a typical shot gets there (P11, P15). Used by the keeper to choose where to
    stand and by the shooter to judge him: one definition."""
    def bearing(px: float, py: float) -> float:
        return fmath.atan2(py - y, abs(px - x))
    lo, hi = sorted((bearing(goal_x, PITCH_Y / 2 - GOAL_HALF_WIDTH),
                     bearing(goal_x, PITCH_Y / 2 + GOAL_HALF_WIDTH)))
    if hi <= lo:
        return 0.0
    if (keeper[0] - x) * (goal_x - x) <= 0:  # behind the shooter: he covers nothing
        return 1.0
    gap = math.hypot(keeper[0] - x, keeper[1] - y)
    k = bearing(*keeper)
    lo_kmh, hi_kmh = SHOT_SPEEDS_KMH
    open_share = 0.0
    for i in range(SHOT_SPEED_SAMPLES):  # over the speeds shots are struck at, not one typical speed
        speed = (lo_kmh + (hi_kmh - lo_kmh) * (i + 0.5) / SHOT_SPEED_SAMPLES) / 3.6
        for j in range(SHOT_HEIGHT_SAMPLES):  # and the heights they are aimed at: his reach differs
            z = SHOT_AIM_Z_M[0] + (SHOT_AIM_Z_M[1] - SHOT_AIM_Z_M[0]) * (j + 0.5) / SHOT_HEIGHT_SAMPLES
            half = fmath.atan2(keeper_reach_m(gap / speed, CHOICE_REACTION_S, z), max(gap, 1e-6))
            covered = max(0.0, min(hi, k + half) - max(lo, k - half))
            open_share += (hi - lo - covered) / (hi - lo) / SHOT_SPEED_SAMPLES / SHOT_HEIGHT_SAMPLES
    return open_share


def through_on_goal(carrier: tuple[float, float], own_goal_x: float,
                    defenders: list[tuple[float, float]]) -> bool:
    """O1: an attacker near our goal with no defender between him and it."""
    cx, cy = carrier
    if math.hypot(cx - own_goal_x, cy - PITCH_Y / 2) > RUSH_RANGE_M:
        return False
    for dx, dy in defenders:
        closer = abs(dx - own_goal_x) < abs(cx - own_goal_x)
        lateral = abs(dy - (cy + (PITCH_Y / 2 - cy) * abs(dx - cx) / max(abs(own_goal_x - cx), 1e-6)))
        if closer and lateral < 3.0:
            return False
    return True


def close_down_spot(carrier: tuple[float, float], own_goal_x: float) -> tuple[float, float]:
    """O1: rushing out, the keeper aims a little short of the attacker on the line to goal."""
    cx, cy = carrier
    gx, gy = own_goal_x, PITCH_Y / 2
    d = math.hypot(cx - gx, cy - gy) or 1.0
    return cx + (gx - cx) / d * CLOSE_DOWN_M, cy + (gy - cy) / d * CLOSE_DOWN_M


def pick_up(defenders: dict[str, tuple[float, float]], attackers: dict[str, tuple[float, float]],
            own_goal_x: float, keep: dict[str, str] | None = None) -> dict[str, str]:
    """O2: each attacker near our goal, nearest the goal first, is picked up by the nearest free
    defender. With `keep` (defender id -> attacker id), a defender still free first keeps the man he
    marks, wherever that man goes: kept only while near, a man seen just at the edge of DANGER_RANGE_M
    was dropped and picked up again from one look to the next. Returns defender id -> attacker id."""
    threats = sorted((a for a in attackers.items()
                      if math.hypot(a[1][0] - own_goal_x, a[1][1] - PITCH_Y / 2) < DANGER_RANGE_M),
                     key=lambda a: math.hypot(a[1][0] - own_goal_x, a[1][1] - PITCH_Y / 2))
    free = dict(defenders)
    pairs = {did: aid for did, aid in (keep or {}).items() if did in free and aid in attackers}
    for did in pairs:
        free.pop(did)
    for aid, (ax, ay) in threats:
        if aid in pairs.values():
            continue
        if not free:
            break
        did = min(free, key=lambda k: math.hypot(free[k][0] - ax, free[k][1] - ay))
        free.pop(did)
        pairs[did] = aid
    return pairs


def goal_side(man: tuple[float, float], own_goal_x: float) -> tuple[float, float]:
    """O2: where his marker stands, MARK_GOAL_SIDE_M from him toward the centre of our goal."""
    ax, ay = man
    gx, gy = own_goal_x, PITCH_Y / 2
    d = math.hypot(gx - ax, gy - ay) or 1.0
    return ax + (gx - ax) / d * MARK_GOAL_SIDE_M, ay + (gy - ay) / d * MARK_GOAL_SIDE_M


def marking(defenders: dict[str, tuple[float, float]], attackers: dict[str, tuple[float, float]],
            own_goal_x: float, pairs: dict[str, str] | None = None) -> dict[str, tuple[float, float]]:
    """O2: each attacker near our goal is picked up by the nearest free defender (pick_up), who
    stands goal-side of him. Returns defender id -> spot."""
    pairs = pick_up(defenders, attackers, own_goal_x) if pairs is None else pairs
    return {pid: goal_side(attackers[aid], own_goal_x) for pid, aid in pairs.items()}


def zone_man(slot: tuple[float, float], attackers: dict[str, tuple[float, float]],
             current: str | None = None) -> str | None:
    """O2 beyond the box: whom a defender in the block tracks: the attacker nearest his place in the
    block, if one is inside his zone (ZONE_RADIUS_M); the one he tracks already, while still inside."""
    inside = {k: v for k, v in attackers.items()
              if math.hypot(v[0] - slot[0], v[1] - slot[1]) <= ZONE_RADIUS_M}
    if current in inside:
        return current
    return min(inside, key=lambda k: math.hypot(inside[k][0] - slot[0], inside[k][1] - slot[1]), default=None)


def zone_spot(slot: tuple[float, float], man: tuple[float, float], own_goal_x: float) -> tuple[float, float]:
    """O2 beyond the box: a defender in the block with an attacker in his zone stands goal-side of him,
    as a marker does (MARK_GOAL_SIDE_M), but never further than ZONE_RADIUS_M from his place, so the
    block keeps its shape (R8). Tracking runners is a large part of what defenders do out of possession
    (Ade, Fitzpatrick and Bradley 2016, *J Sports Sci* 34: 2205-2214)."""
    x, y = goal_side(man, own_goal_x)
    sx, sy = slot
    off = math.hypot(x - sx, y - sy)
    if off > ZONE_RADIUS_M:
        x, y = sx + (x - sx) * ZONE_RADIUS_M / off, sy + (y - sy) * ZONE_RADIUS_M / off
    return x, y


def support_spot(player: tuple[float, float], ball: tuple[float, float], goal_x: float,
                 pressure_from: tuple[float, float] | None) -> tuple[float, float]:
    """O3: a diagonal option 8 to 14 m from the ball, off the line between ball and pressure,
    on the player's own side of the ball."""
    bx, by = ball
    px, py = player
    forward = 1.0 if goal_x > bx else -1.0
    side = 1.0 if py >= by else -1.0
    angle = fmath.atan2(side * 0.7, forward)  # a forward diagonal on his side
    if pressure_from:  # turn away from where the pressure comes from
        ax, ay = pressure_from
        if (ay - by) * side > 0:
            angle = fmath.atan2(side * 1.0, -forward * 0.3)
    dist = min(SUPPORT_RANGE_M[1], max(SUPPORT_RANGE_M[0], math.hypot(px - bx, py - by)))
    x = bx + fmath.cos(angle) * dist
    y = by + fmath.sin(angle) * dist
    return min(PITCH_X - 1, max(1.0, x)), min(PITCH_Y - 1, max(1.0, y))


def run_in_behind(player: tuple[float, float], line_x: float, goal_x: float,
                  carrier_can_play: bool, onside: bool) -> tuple[float, float] | None:
    """O4: a forward run beyond the defensive line, started only when the carrier can play it
    (ball under control, facing forward, not pressed) and while the runner is onside."""
    if not (carrier_can_play and onside):
        return None
    forward = 1.0 if goal_x > PITCH_X / 2 else -1.0
    x = line_x + forward * RUN_BEYOND_M
    if (goal_x - x) * forward < 3:  # never run into the goal itself
        x = goal_x - forward * 3
    return x, min(PITCH_Y - 1, max(1.0, player[1]))


# O6: where each role stands while his team has the ball (design, *verify* against team shape in
# possession: length about 31 to 46 m and width 35 to 48 m, Rico-Gonzalez review, so the widest
# players stand about 21 m either side of the centre; formations in and
# out of possession differ, Shaw and Glickman 2019). Heights are metres from his own goal line,
# relative to the ball; the attackers hold the opponents' last line, staying onside.
# role: (metres behind the ball, or None for the opponents' last line; metres across from the centre)
SHAPE_IN_POSSESSION = {
    "RCB": (24.0, -11.0), "LCB": (24.0, 11.0),
    "RB": (8.0, -18.0), "LB": (8.0, 18.0),
    "CM": (10.0, 0.0), "RCM": (3.0, -13.0), "LCM": (3.0, 13.0),
    "RW": (None, -21.0), "LW": (None, 21.0), "ST": (None, 0.0),
}
DEEPEST_M = 12.0  # nobody's in-possession spot is deeper than this from his own goal
# O6, R8: a team in possession is at most this long, its deepest outfield player to its most
# advanced (*design*: a cap at the top of the typical lengths reported across studies, 31 to 46 m,
# Rico-Gonzalez review; the source gives a range, not a maximum). With
# the ball deep the team does not collapse onto it: the back line stands no further behind the
# forwards than this, so the shape spreads, as teams spread most in build-up (stretch index and
# effective area highest in build-up play, Hands et al. 2026, Int. J. Perf. Anal. Sport).
LENGTH_MAX_M = 46.0
STAYS_WIDE_M = 4.0  # design: stays_wide, further toward the touchline his role already occupies
BALL_SIDE_IN_POSSESSION = 0.15  # the shape leans this share toward the ball's side
FINAL_THIRD_M = 70.0  # ball this far from his own goal: the box is attacked
BOX_RUNS = {"ST": (99.0, 4.0), "far_winger": (98.0, -7.0), "RCM": (88.0, 0.0)}  # near post, far post, edge
# Lesson 202: at a corner the box runners wait no nearer goal than the penalty mark (Law 1: 11 m from
# the goal line; design: where they start) and make their runs as the taker runs up. A dynamic attack
# went with more shots from corners than a static one (Casal et al. 2015, Int J Perf Anal Sport
# 15:430-451, 1,139 corners in elite football; verify: read from the abstract).
BOX_RUN_START_M = 11.0


def attacking_slot(role: str, own_goal_x: float, ball_x: float, ball_y: float,
                   last_line_x: float, wide_m: float = 0.0,
                   waiting: bool = False) -> tuple[float, float] | None:
    # `last_line_x`: the furthest a player of this side may stand and be onside, as he sees it.
    """O6: where this role stands while his team has the ball. Heights follow the ball; attackers
    stand on the opponents' last line (onside); with the ball wide in the final third, the striker,
    the far-side winger and a midfielder attack the near post, the far post and the box edge.
    The team is at most LENGTH_MAX_M long (R8): when the ball is so deep that the roles behind it
    would stand further than that behind the forwards, those roles move up together, keeping their
    spacing, until the back line is LENGTH_MAX_M behind the forwards or level with the ball; the
    forwards then hold no more than LENGTH_MAX_M ahead of the back line. `waiting`: a corner not yet
    being run up to, so every role whose spot is nearer the goal waits at BOX_RUN_START_M from it and
    makes his run as the taker runs up (lesson 202)."""
    shape = SHAPE_IN_POSSESSION.get(role)
    if shape is None:
        return None
    fwd = 1.0 if own_goal_x < PITCH_X / 2 else -1.0
    ball_u = abs(ball_x - own_goal_x)
    last_u = abs(last_line_x - own_goal_x) - 1.0  # a step onside of their last defender
    across = 1.0 if fwd > 0 else -1.0  # width is mirrored for the side attacking toward x = 0
    wide_ball = abs(ball_y - PITCH_Y / 2) > 12.0
    if ball_u > FINAL_THIRD_M and wide_ball:
        ball_side = 1.0 if ball_y > PITCH_Y / 2 else -1.0
        far_winger = (role == "RW" and ball_side * across > 0) or (role == "LW" and ball_side * across < 0)
        key = "far_winger" if far_winger else role
        if key in BOX_RUNS:
            u, side = BOX_RUNS[key]
            u = min(u, max(last_u, ball_u))  # L10: he waits onside for the delivery
            if waiting:
                u = min(u, PITCH_X - BOX_RUN_START_M)
            return own_goal_x + fwd * u, PITCH_Y / 2 + ball_side * side
    behind, width = shape
    deepest = max(b for b, _ in SHAPE_IN_POSSESSION.values() if b is not None)
    front_u = last_u  # the forwards: their last line (and never far behind the ball, below)
    # R8: no longer than LENGTH_MAX_M, so the roles behind the ball move up; but the back line never
    # ahead of the ball (design: it stays goal-side of it, as cover if the ball is lost)
    up = min(deepest, max(0.0, front_u - LENGTH_MAX_M - (ball_u - deepest)))
    if behind is None:
        u = max(min(front_u, ball_u - deepest + up + LENGTH_MAX_M), ball_u - 5.0)
    else:
        u = ball_u - behind + up
    u = min(PITCH_X - 3.0, max(DEEPEST_M, u))
    if waiting:  # lesson 202: everyone the box is attacked by starts his run from the penalty mark
        u = min(u, PITCH_X - BOX_RUN_START_M)
    y = PITCH_Y / 2 + across * width + (ball_y - PITCH_Y / 2) * BALL_SIDE_IN_POSSESSION
    if wide_m and width:
        y += math.copysign(wide_m, across * width)  # his side of the pitch, further out
    return own_goal_x + fwd * u, min(PITCH_Y - 2.0, max(2.0, y))


def keeper_reach_m(seconds: float, reaction_s: float, z: float) -> float:
    """P11, P15: how far sideways a keeper can stop a ball at height `z`, `seconds` after it is
    struck: until he reacts only his body is in the way (as in the engine's contact rule: hands
    need a reaction); then his hands' reach at that height (reach_for, the engine's own envelope)
    and the body's launch over DIVE_TIME_S. Nothing, over the top of his envelope."""
    if seconds < reaction_s:
        return BODY_RADIUS + ball.RADIUS
    diving = seconds - reaction_s
    reach_m, reach_z = reach_for(True, diving, z, seconds - max(reaction_s, UP_AFTER_CONTACT_S))
    if z > reach_z:
        return 0.0
    return reach_m + KEEPER_DIVE_TRAVEL_M * dive_progress(diving)


def may_handle(keeper: bool, in_own_box: bool, released_it: bool, back_pass: bool) -> bool:
    """Law 12: a keeper may handle the ball only inside his own penalty area; not again after
    releasing it until another player has touched it; and not from a team-mate's deliberate pass (a
    kick or a throw-in) that nobody else has touched."""
    return keeper and in_own_box and not released_it and not back_pass


def reach_for(hands: bool, stretched_s: float, z: float = 0.0, rising_s: float = 0.0
              ) -> tuple[float, float]:
    """How far (from the body's centre, across the ground) a player can reach a ball at height `z`,
    and the highest he can reach at all: a foot (CONTROL_M, below FOOT_REACH_Z), or a keeper's
    hands (P11, P15). His hands reach within KEEPER_ARM_M of his centre of mass, sideways no further
    than his arms have stretched since his save began (`stretched_s`). His centre of mass can be
    as high as his jump has lifted it `rising_s` after it began (UP_AFTER_CONTACT_S after the
    kick at the soonest), or as low as falling since his save began has dropped it. One rule for
    the engine (engine.reach, engine.contact), the keeper's dive, the passer's race
    (decisions.pass_confidence) and the shooter's judgement (keeper_reach_m)."""
    if not hands:
        return CONTROL_M, FOOT_REACH_Z
    stretched = max(0.0, stretched_s)
    top = KEEPER_COM_Z + jump_rise_m(rising_s)
    # design: down to the ground (lying on his side it is nearer 0.15 to 0.2 m up; the difference to
    # his reach across is under 2 cm)
    low = max(0.0, KEEPER_COM_Z - 0.5 * GRAVITY * stretched * stretched)
    off = max(z - top, low - z, 0.0)  # how far above or below where his centre of mass can be
    across = math.sqrt(max(KEEPER_ARM_M * KEEPER_ARM_M - off * off, 0.0))
    return min(arm_reach_m(stretched), across), top + KEEPER_ARM_M


def jump_rise_m(rising_s: float) -> float:
    """P11: the most his centre of mass can have risen `rising_s` after his jump began: thrown up
    fast enough to rise KEEPER_JUMP_M, then flying under gravity (at the top he can be no higher)."""
    if rising_s <= 0:
        return 0.0
    up = math.sqrt(2 * GRAVITY * KEEPER_JUMP_M)
    t = min(rising_s, up / GRAVITY)
    return up * t - 0.5 * GRAVITY * t * t


def arm_reach_m(diving_s: float) -> float:
    """P11, P15: his reach from his body's centre, `diving_s` into a dive: standing reach, stretched
    out over the dive at the same pace as the body's launch."""
    return KEEPER_STAND_REACH_M + KEEPER_DIVE_EXTRA_M * dive_progress(diving_s)


def dive_progress(t: float) -> float:
    """P15: the share of a full dive's sideways travel done `t` seconds after it starts: he
    speeds up to the cited peak speed over the push-off, then carries it (the whole travel takes
    DIVE_TIME_S)."""
    ramp = DIVE_PUSH_OFF_S
    t = min(max(t, 0.0), DIVE_TIME_S)
    if t <= ramp:
        done = 0.5 * DIVE_PEAK_MPS / ramp * t * t
    else:
        done = 0.5 * DIVE_PEAK_MPS * ramp + DIVE_PEAK_MPS * (t - ramp)
    return done / KEEPER_DIVE_TRAVEL_M


def dive_motion(t: float, v0: float = 0.0) -> tuple[float, float]:
    """P15: how far (m) and how fast (m/s) the body has gone toward the dive `t` seconds into it,
    from a sideways speed `v0` toward it when it began. The dive is one push (dive_progress's,
    speeding him up to DIVE_PEAK_MPS); a run toward the dive is where the push starts from, never
    lost; a run away from it is first braked as any body brakes (P2), then he pushes."""
    push = DIVE_PEAK_MPS / _dive_ramp()
    t = max(t, 0.0)
    gone = 0.0
    if v0 < 0:
        braking = -v0 / BRAKE_MAX
        if t <= braking:
            return v0 * t + 0.5 * BRAKE_MAX * t * t, v0 + BRAKE_MAX * t
        gone, t, v0 = -v0 * v0 / (2 * BRAKE_MAX), t - braking, 0.0
    top = max(DIVE_PEAK_MPS, v0)
    pushing = (top - v0) / push
    if t <= pushing:
        return gone + v0 * t + 0.5 * push * t * t, v0 + push * t
    return gone + v0 * pushing + 0.5 * push * pushing * pushing + top * (t - pushing), top


def dive_time_to(metres: float, v0: float = 0.0) -> float:
    """P15: how long into a dive the body has gone `metres` toward it (dive_motion inverted)."""
    push = DIVE_PEAK_MPS / _dive_ramp()
    before = 0.0
    if v0 < 0:
        before = -v0 / BRAKE_MAX
        metres += v0 * v0 / (2 * BRAKE_MAX)  # what the braking took him away first
        v0 = 0.0
    top = max(DIVE_PEAK_MPS, v0)
    pushing = (top - v0) / push
    pushed = v0 * pushing + 0.5 * push * pushing * pushing
    if metres <= pushed:
        return before + (math.sqrt(v0 * v0 + 2 * push * metres) - v0) / push
    return before + pushing + (metres - pushed) / top


def _dive_ramp() -> float:
    """P15: how long the full dive speeds up for: the push-off."""
    return DIVE_PUSH_OFF_S
