"""Off-the-ball decisions: where players go when they do not have the ball.

Each is an intention with the trigger the research describes, chosen from what the player
believes, never an outcome: a keeper narrows the angle and comes out to an attacker through on
goal; defenders mark the attackers who threaten the goal; team-mates of the ball carrier offer
support and make runs in behind when the carrier can play them. Docs: docs/ENGINE.md layer 6,
docs/GROUNDING.md rows O1 to O5.
"""

from __future__ import annotations

import math

from ninety.sim import ball
from ninety.sim.body import (
    BODY_RADIUS,
    BRAKE_MAX,
    CONTROL_M,
    FOOT_REACH_Z,
    HAND_REACH_Z,
    HEAD_JUMP_Z,
    HEAD_REACH_M,
    HEAD_STAND_Z,
    JUMP_RISE_S,
)
from ninety.sim.perception import CHOICE_REACTION_S

PITCH_X, PITCH_Y = 105.0, 68.0
GOAL_HALF_WIDTH = 3.66
KEEPER_STAND_REACH_M = 1.0  # P11: a keeper's sideways arm reach from the body's centre
KEEPER_DIVE_EXTRA_M = 0.8  # P11: added as the dive stretches out, hips to fingertips about 1.8 m
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
KEEPER_DEPTH = (1.0, 6.0)  # O1: design, verify: how far off his line he stands
SHOT_RANGE_M = 40.0  # design: a shot is an option inside this distance of the goal
KEEPER_DEPTH_STEP_M = 0.5  # O1: design: the depths he weighs, this far apart
RUSH_RANGE_M = 18.0  # O1: design: an attacker this close and through on goal draws the keeper out
CLOSE_DOWN_M = 2.0  # O1: design: how close the keeper gets to narrow the angle
DANGER_RANGE_M = 25.0  # O2: design: attackers this near our goal are marked man to man
MARK_GOAL_SIDE_M = 1.5  # O2: design: a marker stands this far goal-side of his man
SUPPORT_RANGE_M = (8.0, 14.0)  # O3: a diagonal option about 5 to 15 m from the ball
RUN_BEYOND_M = 10.0  # O4: design: a run in behind aims this far beyond the defensive line


def keeper_spot(ball_x: float, ball_y: float, own_goal_x: float) -> tuple[float, float]:
    """O1: on the line that bisects the angle between the posts as seen from the ball, at the depth
    (within KEEPER_DEPTH) that leaves the least of the goal open to a shot from there, given how far
    he can get in the time the shot takes: against a far shot he stays deep, where his dive has time
    to unfold; against a near one he comes out and narrows the angle."""
    gy = PITCH_Y / 2
    a1 = math.atan2(gy - GOAL_HALF_WIDTH - ball_y, own_goal_x - ball_x)
    a2 = math.atan2(gy + GOAL_HALF_WIDTH - ball_y, own_goal_x - ball_x)
    mid = math.atan2(math.sin(a1) + math.sin(a2), math.cos(a1) + math.cos(a2))
    ux, uy = math.cos(mid), math.sin(mid)  # from the ball toward the goal, between the posts
    if abs(ux) < 1e-6:
        return own_goal_x, gy
    to_line = (own_goal_x - ball_x) / ux  # along the bisector to the goal line
    if math.hypot(own_goal_x - ball_x, gy - ball_y) > SHOT_RANGE_M:  # out of range: he sweeps
        along = max(0.0, to_line - KEEPER_DEPTH[1] / abs(ux))
        return ball_x + ux * along, ball_y + uy * along
    best = None
    lo, hi = KEEPER_DEPTH
    for k in range(int((hi - lo) / KEEPER_DEPTH_STEP_M) + 1):
        depth = lo + k * KEEPER_DEPTH_STEP_M
        along = to_line - depth / abs(ux)
        if along < CLOSE_DOWN_M:  # no nearer the ball than when he rushes out to close it down
            continue
        spot = ball_x + ux * along, ball_y + uy * along
        open_share = open_goal_share(ball_x, ball_y, own_goal_x, spot)
        if best is None or open_share < best[0] - 1e-12:
            best = (open_share, spot)
    if best is None:  # the ball is almost on his line: he stays on it, between the posts
        return own_goal_x, min(gy + GOAL_HALF_WIDTH, max(gy - GOAL_HALF_WIDTH, ball_y))
    return best[1]


def open_goal_share(x: float, y: float, goal_x: float, keeper: tuple[float, float],
                    speeds_kmh: tuple[float, float] = SHOT_SPEEDS_KMH) -> float:
    """The share of the goal mouth, as seen from (x, y), that a keeper at `keeper` cannot get a hand
    across before a typical shot gets there (P11, P15), struck at `speeds_kmh` (a header: the speed
    a header leaves at, P18). Used by the keeper to choose where to stand and by the shooter to
    judge him: one definition."""
    def bearing(px: float, py: float) -> float:
        return math.atan2(py - y, abs(px - x))
    lo, hi = sorted((bearing(goal_x, PITCH_Y / 2 - GOAL_HALF_WIDTH),
                     bearing(goal_x, PITCH_Y / 2 + GOAL_HALF_WIDTH)))
    if hi <= lo:
        return 0.0
    if (keeper[0] - x) * (goal_x - x) <= 0:  # behind the shooter: he covers nothing
        return 1.0
    gap = math.hypot(keeper[0] - x, keeper[1] - y)
    k = bearing(*keeper)
    lo_kmh, hi_kmh = speeds_kmh
    open_share = 0.0
    for i in range(SHOT_SPEED_SAMPLES):  # over the speeds shots are struck at, not one typical speed
        speed = (lo_kmh + (hi_kmh - lo_kmh) * (i + 0.5) / SHOT_SPEED_SAMPLES) / 3.6
        half = math.atan2(keeper_reach_m(gap / speed, CHOICE_REACTION_S), max(gap, 1e-6))
        covered = max(0.0, min(hi, k + half) - max(lo, k - half))
        open_share += (hi - lo - covered) / (hi - lo) / SHOT_SPEED_SAMPLES
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


def marking(defenders: dict[str, tuple[float, float]], attackers: dict[str, tuple[float, float]],
            own_goal_x: float) -> dict[str, tuple[float, float]]:
    """O2: each attacker near our goal is picked up by the nearest free defender, who stands
    goal-side of him. Returns defender id -> spot."""
    threats = sorted((a for a in attackers.items()
                      if math.hypot(a[1][0] - own_goal_x, a[1][1] - PITCH_Y / 2) < DANGER_RANGE_M),
                     key=lambda a: math.hypot(a[1][0] - own_goal_x, a[1][1] - PITCH_Y / 2))
    free = dict(defenders)
    spots = {}
    for _, (ax, ay) in threats:
        if not free:
            break
        pid = min(free, key=lambda k: math.hypot(free[k][0] - ax, free[k][1] - ay))
        free.pop(pid)
        gx, gy = own_goal_x, PITCH_Y / 2
        d = math.hypot(gx - ax, gy - ay) or 1.0
        spots[pid] = (ax + (gx - ax) / d * MARK_GOAL_SIDE_M, ay + (gy - ay) / d * MARK_GOAL_SIDE_M)
    return spots


def support_spot(player: tuple[float, float], ball: tuple[float, float], goal_x: float,
                 pressure_from: tuple[float, float] | None) -> tuple[float, float]:
    """O3: a diagonal option 8 to 14 m from the ball, off the line between ball and pressure,
    on the player's own side of the ball."""
    bx, by = ball
    px, py = player
    forward = 1.0 if goal_x > bx else -1.0
    side = 1.0 if py >= by else -1.0
    angle = math.atan2(side * 0.7, forward)  # a forward diagonal on his side
    if pressure_from:  # turn away from where the pressure comes from
        ax, ay = pressure_from
        if (ay - by) * side > 0:
            angle = math.atan2(side * 1.0, -forward * 0.3)
    dist = min(SUPPORT_RANGE_M[1], max(SUPPORT_RANGE_M[0], math.hypot(px - bx, py - by)))
    x = bx + math.cos(angle) * dist
    y = by + math.sin(angle) * dist
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


# O6: where each role stands while his team has the ball. The team stands in lines, as it does
# without the ball (team.py): the back line a set distance behind the ball, the forwards on the
# opponents' last line (onside), and the others spread across the team's length between them, so
# whoever has the ball has team-mates ahead of him as well as behind. Team length in possession is
# about 31 to 46 m and width 35 to 48 m (Rico-Gonzalez review), so the widest players stand about
# 21 m either side of the centre; formations in and out of possession differ (Shaw and Glickman
# 2019). Line shares and the back line's distance behind the ball are design, *verify*.
# role: (share of the team's length ahead of its back line, or None for the forwards; metres across)
SHAPE_IN_POSSESSION = {
    "RCB": (0.0, -11.0), "LCB": (0.0, 11.0),
    "RB": (1 / 3, -18.0), "LB": (1 / 3, 18.0), "CM": (1 / 3, 0.0),
    "RCM": (2 / 3, -13.0), "LCM": (2 / 3, 13.0),
    "RW": (None, -21.0), "LW": (None, 21.0), "ST": (None, 0.0),
}
BACK_LINE_BEHIND_M = 24.0  # the back line's distance behind the ball
TEAM_LENGTH_MAX_M = 46.0  # the most a team stretches with the ball, back line to forwards (Rico-Gonzalez)
DEEPEST_M = 12.0  # nobody's in-possession spot is deeper than this from his own goal
ONSIDE_STEP_M = 1.0  # L10 (design): attackers hold a step onside of the line they see
BALL_SIDE_IN_POSSESSION = 0.15  # the shape leans this share toward the ball's side
FINAL_THIRD_M = 70.0  # ball this far from his own goal: the box is attacked
# S5 (design): the box's zones attacking players run at, as (depth from the goal line, offset
# across toward the far post): near post, centre, far post, penalty spot. A corner (setpieces) and
# a cross in open play (decisions.cross_options) aim at the same zones.
RUN_ZONES = {"near_post": (5.5, -3.0), "centre": (7.0, 0.5), "far_post": (5.0, 4.5), "spot": (11.0, 1.5)}
BOX_RUNS = {"ST": (99.0, 4.0), "far_winger": (98.0, -7.0), "RCM": (88.0, 0.0)}  # near post, far post, edge


def attacking_slot(role: str, own_goal_x: float, ball_x: float, ball_y: float,
                   last_line_x: float) -> tuple[float, float] | None:
    # `last_line_x`: the furthest a player of this side may stand and be onside, as he sees it.
    """O6: where this role stands while his team has the ball. The back line follows the ball, the
    attackers stand on the opponents' last line (onside) no further than the team's length ahead
    of it, and the other lines are spread between; with the ball wide in the final third, the
    striker, the far-side winger and a midfielder attack the near post, the far post and the box
    edge."""
    shape = SHAPE_IN_POSSESSION.get(role)
    if shape is None:
        return None
    fwd = 1.0 if own_goal_x < PITCH_X / 2 else -1.0
    ball_u = abs(ball_x - own_goal_x)
    last_u = abs(last_line_x - own_goal_x) - ONSIDE_STEP_M  # a step onside of their last defender
    across = 1.0 if fwd > 0 else -1.0  # width is mirrored for the side attacking toward x = 0
    wide_ball = abs(ball_y - PITCH_Y / 2) > 12.0
    if ball_u > FINAL_THIRD_M and wide_ball:
        ball_side = 1.0 if ball_y > PITCH_Y / 2 else -1.0
        far_winger = (role == "RW" and ball_side * across > 0) or (role == "LW" and ball_side * across < 0)
        key = "far_winger" if far_winger else role
        if key in BOX_RUNS:
            u, side = BOX_RUNS[key]
            u = min(u, max(last_u, ball_u))  # L10: he waits onside for the delivery
            return own_goal_x + fwd * u, PITCH_Y / 2 + ball_side * side
    share, width = shape
    back_u = max(DEEPEST_M, ball_u - BACK_LINE_BEHIND_M)
    front_u = max(min(last_u, back_u + TEAM_LENGTH_MAX_M), ball_u - 5.0)
    u = front_u if share is None else back_u + share * (front_u - back_u)
    u = min(PITCH_X - 3.0, max(DEEPEST_M, u))
    y = PITCH_Y / 2 + across * width + (ball_y - PITCH_Y / 2) * BALL_SIDE_IN_POSSESSION
    return own_goal_x + fwd * u, min(PITCH_Y - 2.0, max(2.0, y))


def keeper_reach_m(seconds: float, reaction_s: float) -> float:
    """P11, P15: how far sideways a keeper can stop the ball, `seconds` after it is struck: until he
    reacts only his body is in the way (as in the engine's contact rule: hands need a reaction);
    then his standing reach, the dive's stretch and the body's launch over DIVE_TIME_S."""
    if seconds < reaction_s:
        return BODY_RADIUS + ball.RADIUS
    return arm_reach_m(seconds - reaction_s) + KEEPER_DIVE_TRAVEL_M * dive_progress(seconds - reaction_s)


def may_handle(keeper: bool, in_own_box: bool, released_it: bool, back_pass: bool) -> bool:
    """Law 12: a keeper may handle the ball only inside his own penalty area; not again after
    releasing it until another player has touched it; and not from a team-mate's deliberate pass (a
    kick or a throw-in) that nobody else has touched."""
    return keeper and in_own_box and not released_it and not back_pass


def reach_at(hands: bool, since_react_s: float, z: float, heads: bool = True) -> float | None:
    """P11: how far from his body's centre a player can play a ball whose lowest point is at height
    `z`, `since_react_s` after he reacted to it. A keeper's hands (`hands`: in his box, Law 12)
    reach up to HAND_REACH_Z, his arms stretched for that long. Otherwise a foot plays a ball below
    FOOT_REACH_Z, and above it his head: standing (or stooping) up to HEAD_STAND_Z, or jumping up to
    HEAD_JUMP_Z once he has had JUMP_RISE_S to rise; with `heads` False, only his feet (he lets it
    drop: engine.goes_up). None: out of his reach at that height. One rule for the engine
    (engine.reach) and the passer's race (decisions.pass_confidence)."""
    if hands:
        return arm_reach_m(max(0.0, since_react_s)) if z <= HAND_REACH_Z else None
    if z <= FOOT_REACH_Z:
        return CONTROL_M
    if heads and (z <= HEAD_STAND_Z or (z <= HEAD_JUMP_Z and since_react_s >= JUMP_RISE_S)):
        return HEAD_REACH_M
    return None


def reach_limits(hands: bool, since_react_s: float, heads: bool = True) -> list[tuple[float, float]]:
    """P11: (how far from his centre, up to what height) each part of him plays the ball,
    `since_react_s` after he reacted: the same limits as reach_at, for a contact test along a path
    (engine.contact): a keeper's hands; or his foot, then his head (standing, or jumping once he
    has had time to rise)."""
    if hands:
        return [(arm_reach_m(max(0.0, since_react_s)), HAND_REACH_Z)]
    zones = [(CONTROL_M, FOOT_REACH_Z)]
    if heads:
        zones.append((HEAD_REACH_M, HEAD_JUMP_Z if since_react_s >= JUMP_RISE_S else HEAD_STAND_Z))
    return zones


def headed(hands: bool, z: float) -> bool:
    """A touch at this height is a header: above a foot's reach and not in a keeper's hands."""
    return not hands and z > FOOT_REACH_Z


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
