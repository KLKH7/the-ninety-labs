"""Scene geometry shared by the labels (Python) and the pixels (three.js).

Players are labelled from capsules (thighs, shins, torso, arms) and spheres (head, hair). Python
computes every capsule in world coordinates for every frame. The page skins a mesh inside that
volume and draws the capsules for the ball. The labelled box stays the capsule box. Standing, trunk and
arms are drawn to fill the body shape the engine's contact physics uses (ninety/sim/shape.py)
between hip and shoulder height, turned the way the engine says he faces. The legs are narrower
than that shape, and running, the arms swing and the trunk leans outside it (docs/GROUNDING.md,
P11).
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

from ninety.render.camera import Camera
from ninety.render.fouls import LOOK_MAX, tip
from ninety.render.meshpose import (
    ASSET_STATURE_M,
    BROW_Y,
    STAND_BLEND,
    STRIDE_GROW,
    arm_points,
    asset,
    gait_foot,
)
from ninety.sim import shape
from ninety.sim.body import F0_MEAN, F0_SD, GRAVITY

BALL_RADIUS = 0.11
STRIDE_M = 1.7  # fallback, used only where a caller has no speed yet


def _step_m(speed: float) -> float:
    """One step. A walk stays near two a second. A jog at 3 m/s is about 1.1 m and 2.7 a
    second. A sprint stays near 4.4 a second and lengthens the step (Debaere 2013)."""
    if speed <= 1.6:
        return max(0.55, speed / 2.0)
    if speed <= 3.0:
        return 0.80 + (speed - 1.6) * (0.30 / 1.4)
    return min(1.10 + (speed - 3.0) * 0.125, 1.80)


def _stride(speed: float) -> float:
    """Ground covered by one full cycle, which is two steps."""
    return 2.0 * _step_m(speed)


# The share of the stride a foot is on the grass (duty factor), walking and running, by speed (m/s):
# Swinnen et al. 2026 (J Exp Biol, jeb.252161, treadmill: walking 0.628 at 1.25, 0.605 at 2.0;
# running 0.397 at 2.0, 0.358 at 2.5, 0.324 at 3.33, 0.303 at 4.17) and Martinez-Sobrino et al. 2023
# (J Sports Sci Med 22:790, track: 0.290 at 5.07, 0.256 at 7.32). People change from a walk to a
# run at about 1.96 m/s (Neptune and Sasaki 2005, J Exp Biol 208:799); the drawn gait goes from the
# one to the other across GAIT_SWITCH_MPS (design: a band, so a player hovering at the switch speed
# does not flicker between the two). Below 1.25 m/s the walk's share is held (no source).
WALK_DUTY = ((1.25, 0.628), (2.0, 0.605))
RUN_DUTY = ((2.0, 0.397), (2.5, 0.358), (3.33, 0.324), (4.17, 0.303), (5.07, 0.290), (7.32, 0.256))
GAIT_SWITCH_MPS = (1.76, 2.16)


def _table(points: tuple, v: float) -> float:
    """Piecewise linear through (speed, value) points, held flat beyond the ends."""
    if v <= points[0][0]:
        return points[0][1]
    for (a, fa), (b, fb) in zip(points, points[1:], strict=False):
        if v <= b:
            return fa + (fb - fa) * (v - a) / (b - a)
    return points[-1][1]


def _running(speed: float) -> float:
    """How much of the drawn gait is a run (0 walking, 1 running), across GAIT_SWITCH_MPS."""
    lo, hi = GAIT_SWITCH_MPS
    return min(max((speed - lo) / (hi - lo), 0.0), 1.0)


def _duty(speed: float) -> float:
    """Share of the cycle a foot is down: a walk overlaps (both feet down), a run has a flight phase."""
    r = _running(speed)
    return _table(WALK_DUTY, speed) * (1.0 - r) + _table(RUN_DUTY, speed) * r


def turn_toward(heading: float, target: float, dt: float, rate: float = 5.0) -> float:
    """Face `target` without snapping. A body turns; it does not swap ends in one frame."""
    diff = (target - heading + math.pi) % (2 * math.pi) - math.pi
    cap = rate * dt
    if diff > cap:
        diff = cap
    elif diff < -cap:
        diff = -cap
    return heading + diff


# How a turn is drawn (design, renderer only: the engine's heading and position are unchanged).
# The hips lead: they face where the engine has him face LEAD_AHEAD_FRAMES later (0.12 s), at
# most LEAD_MAX ahead of the chest, which faces the engine's heading (what collides is what is
# drawn, P11). A foot on the grass keeps its place and the way it points; the hips turn over it
# until the hip runs out of rotation (HIP_ROT, inside the hip's 35 to 45 degree range either way),
# then it pivots on the spot. Standing, a foot that has fallen STEP_DIST behind where it would
# stand, or STEP_YAW behind the way the hips face, steps there: one foot at a time, each step
# STEP_FRAMES long and lifting STEP_LIFT, so a turn on the spot is a run of short steps.
LEAD_AHEAD_FRAMES = 3
LEAD_MAX = 0.4
HIP_ROT = 0.7
STEP_YAW = 0.45
STEP_DIST = 0.25
STEP_FRAMES = 7  # 0.28 s at 25 fps
STEP_LIFT = 0.08
STEP_PEAK_MPS = 3.0  # the fastest a stepping foot travels (design: a quick step, not a kick)
# On the move a stepping foot must outpace the body it steps after, as a stride's swinging foot does
# (it covers a stride while the body covers a step): up to this many times his speed (design).
STEP_CATCH_UP = 2.5
# A foot caught in the air by a touch (the stride's swing) is down within this many frames, the rest
# of a swing at walking pace, before it carries on low to where it stands (design).
LAND_FRAMES = 3
SETTLE = 0.5  # standing still, a foot that far (as a share of the step limits) squares up
# Below this pace the feet step after the body as when standing (design): drifting at 0.4 to 0.6 m/s
# the engine's pose flickers between walk and stand every frame, and a stride restarted each time
# never landed: both feet hovered 10 to 20 cm up for seconds.
STRIDE_FROM_MPS = 0.7
# Where a standing foot sits under the hips: the asset's rest pose (foot marker, object metres
# in the asset's own metres): lateral, forward.
FOOT_HOME = (0.219, 0.127)
ANKLE_BACK = 0.11  # the drawn ankle sits this far behind the foot marker (asset rest pose)
# The furthest ahead of the hips the mesh's leg puts a flat foot on the grass, in the asset's own metres
# (measured from the asset: 1 cm short of a plant 0.30 m ahead, 3.6 cm at 0.35, 13.5 cm at 0.45).
# A run lands no further, or the drawn foot lands short and slides forward to its plant.
PLANT_AHEAD_MAX = 0.30
# The gait plants their feet. A touch with the foot or thigh is taken in stride: the other foot stays
# planted and the touch takes the one that meets the ball.
PLANT_ACTIONS = ("stand", "walk", "run", "chest", "head", "strike", "foot", "thigh", "hands", "throw", "dive")
# Running, each foot is planted over the part of the stride where the gait (meshpose.gait) has it
# on the grass: the stored stride swings a foot along one path and it is lowest and going back
# around these phases (measured on the asset: the left foot is forward at 1.5 pi and lifts behind
# after 2 pi). The leg takes and gives back the plant over PLANT_EASE_FRAMES.
STANCE_CENTRE = {"l": 1.75 * math.pi, "r": 0.75 * math.pi}
PLANT_EASE_FRAMES = 3
# The furthest behind the hips a foot on the grass stays in a stride (asset metres, measured: at
# 0.30 the leg holds the foot within 1 mm of its plant; at 0.32 it lifts it 2 cm and drags it, and the
# 0.45 once used here dragged the push-off toe up to 17 cm a frame), how far either side of his line
# of running a foot lands (design: a runner's feet land close to the line).
STANCE_BEHIND_MAX = 0.30
RUN_HALF_WIDTH_M = 0.11
# How high a swinging foot is carried (asset metres) by speed (m/s). Walking, clear of the grass
# (design). Running, as high as folds the drawn knee to Fukuchi et al. 2017's peak swing knee flexion
# (Table 4: 93.5 degrees at 2.5 m/s, 108.7 at 3.5, 119.1 at 4.5), measured on the asset with the bob
# drawn (93.5 at 0.18, 108.7 at 0.335). The drawn leg folds no further than 111 degrees, its foot kept
# within reach behind the hips (STANCE_BEHIND_MAX), which it reaches at 0.40, and held there faster
# (higher, the leg falls short of the foot: 9 cm at 0.45, 17 cm at 0.54, at 7 m/s). Measured: the
# largest knee angle over 50 frames at a steady speed, which varies by about 2 degrees with where the
# frames fall in the stride. Drawn on a level pelvis, a fold like this read as prancing (lesson 164);
# the bob carries it.
SWING_LIFT_M = ((1.5, 0.10), (2.5, 0.18), (3.5, 0.335), (4.5, 0.40))
LATE_LIFT = 0.5  # past this share of its swing a foot still on the grass waits for the next one
# Running, a foot is highest early in its swing, behind the hips, and comes through low to land
# (Fukuchi et al. 2017, Fig. 3: the knee most folded at about 69% of the stride, a third of the way
# through a swing that starts at about 54%); walking, highest midway.
RUN_SWING_PEAK = 0.35
# The hips rise and fall twice a stride (the bob), peak to peak in metres by speed (m/s). Walking they
# are highest over the foot at mid-stance and lowest as the weight passes from one foot to the other
# (Orendurff et al. 2004, the table: 2.74 cm at 0.7 m/s, 3.61 at 1.0, 4.06 at 1.2, 4.83 at 1.6).
# Running they are lowest at mid-stance (Lee and Farley 1998) and fall freely in the air, so the rise
# over a flight of t seconds is GRAVITY * t^2 / 8 and the rest of the bob is the dip over the stance.
# The running bob by speed: Fadillioglu et al. 2022 (8.7 cm at 2.78 m/s, the mean of their experts'
# 9.14 and novices' 8.23); Hanley et al. 2022 (Premier League players on a treadmill, Fig. 2, the
# mean of the low and high duty factor groups: 8.55 cm at 3.33 m/s, 8.35 at 4.44, 7.55 at 5.56);
# Gullstrand et al. 2009 (about 7.5 cm at 6.1 m/s); Coh et al. 2018 (a sprinter at 12 m/s: 4.5 cm in
# their Table 3, 4.9 in their text; 4.7 taken).
WALK_BOB = ((0.7, 0.0274), (1.0, 0.0361), (1.2, 0.0406), (1.6, 0.0483))
RUN_BOB = ((2.78, 0.087), (3.33, 0.0855), (4.44, 0.0835), (5.56, 0.0755), (6.1, 0.075), (12.0, 0.047))
# The trunk's lean (radians, forward +) on top of the stored stride's own, which draws 10.2 degrees
# from a jog up, as runners lean at 10 to 12 km/h (Folland et al. 2017, Table 2: 10.3 degrees). By
# speed: to 14.3 degrees at a sprinter's top speed (Nagahara et al. 2014: upper trunk at 75.7 degrees
# from the horizontal, peak speed 10.04 m/s). Speeding up or slowing at a m/s^2 the body leans by
# atan(a / GRAVITY), so the push of the ground passes through it (Kugler and Janshen 2010: the force's
# direction follows the body's lean, r = 0.93), half of it drawn in the trunk (LEAN_DRAWN), the feet
# following the stride; slowing, the trunk comes back to upright and no further (design: the drawn
# legs cannot plant ahead of him, which carries the rest of a braking lean). The acceleration is the
# engine's velocity's along the way he faces, from the mean of the ACCEL_BOX frames before this one
# to the mean of this one and those after (design: at a steady jog the engine's speed rises and brakes
# back every 9 frames or so, seed 21's a5 3.2 to 4.0 m/s, and eased over 5 frames the trunk nodded
# every step to a blind critic; from boxes behind him only, it leaned 5 frames late, forward while
# braking), and the lean eases toward it by LEAN_EASE a frame (design: no step when a box moves on).
# Folland's runners ran at 10, 11 and 12 km/h: their lean is taken at 11 km/h, 3.05 m/s. Speeding up,
# the lean is no more than the hardest push a player of the engine has from standing allows (its
# acceleration from standing, three spreads above the mean, GROUNDING P2): a velocity the engine
# changes in a frame (a collision) is no push.
RUN_LEAN = ((3.05, 0.0), (10.04, math.radians(14.3 - 10.3)))
ACCEL_MAX = F0_MEAN + 3 * F0_SD
STRIDE_LEAN = math.radians(10.2)  # the stored stride's own lean (measured on the asset, pelvis to neck)
ACCEL_BOX = 8
LEAN_EASE = 0.2
# The trunk takes half the body's lean (design: Kugler and Janshen's lean is the whole body's, from the
# foot, and the drawn stride does not angle the legs back; drawn whole in the trunk, two blind critics
# saw a stoop or a lunge at 4 m/s^2).
LEAN_DRAWN = 0.5
TRUNK_M = 0.48  # hips to shoulders (the capsules' 0.92 to 1.40, asset metres): a lean's reach forward
# The arms swing wider with speed above the stored run's (meshpose.gait's pump), whose shoulder swings
# through 83 degrees (measured on the asset at 4 m/s and up), to 126.5 at a sprinter's top speed (Mann
# and Herman 1985, Olympic 200 m final, top-speed phase: 135 and 118 degrees, first and eighth),
# taken as 10.04 m/s (Nagahara et al. 2014's peak speed; design, the race's speed is not in the source).
PUMP = ((asset()["armRunSpeed"], 1.0), (10.04, 126.5 / 83.0))
# The bob comes and goes with the stride over this many frames (design: a touch, a lunge or a jump
# takes the hips off the stride, and they do not jump back to it).
BOB_EASE_FRAMES = 3
RUN_MIX_RATE = 0.2  # the most a swing's walk-to-run timing changes in a frame (design)
REACH_CLEAR_M = 0.15  # reaching, a foot clears the grass by this times the share of the way left (design)
FRAME_S = 0.04  # one frame at the engine's 25 fps (ninety.sim.engine.FPS)
MESH_ARM_ACTIONS = ("strike", "foot", "thigh", "chest", "head", "hands", "shield", "throw")
HIP_PIVOT_Z = 0.99  # the mesh's spine_01 joint, where a bend over the ball starts (asset rest pose)

# A keeper's dive is drawn once, from the engine's dive (its action "dive", how far along it he is).
# It grows no faster than the engine's own dives do (DIVE_IN_FRAMES: 0.105 a frame, measured on seed
# 8001's a1), so one the engine starts at full stretch (its "down after a dive") still grows. It keeps
# the side and the way he faced when it began until he is up (the engine turns a keeper on the grass
# toward the ball, and drawn as it turned, the stretched body spun and dived again the other way),
# never shrinks while the engine holds it, and fades over DIVE_UP_FRAMES into whatever he does next
# (the catch, standing, running: dive_up), his body turning to the engine's facing over the same
# frames (design: 1 s, as a keeper takes to get up; a snap in a frame read as a second dive).
DIVE_IN_FRAMES = 10
DIVE_UP_FRAMES = 50  # (lesson 280: 2 s, a person's get-up through one knee; was 1 s)

# How a touch is drawn (design). The engine says which part met the ball and the frame says where
# the ball was. The touching part reaches that point on the contact frame, along the way the touch
# pushed the ball (its change of velocity): drawn back over TOUCH_WIND_S, through the ball, on
# for TOUCH_FOLLOW_S. A harder touch swings further. Its weight rises over the window up to
# TOUCH_SET_S before contact and falls over TOUCH_RECOVER_S after the follow-through.
TOUCH_WIND_S = 0.2
TOUCH_FOLLOW_S = 0.2
TOUCH_SET_S = 0.04  # a touch's part is on its path this long before the contact frame
# A foul's contact (lesson 173, design): the fouler's foot meets the fouled player's legs this far in
# from his centre on the fouler's side, at this height (the shins; a challenge that hits the man).
FOUL_REACH_M = 0.25
FOUL_SHIN_M = 0.25
# After the follow-through the part comes back to the stride, and the hips back up out of a lunge,
# over TOUCH_RECOVER_S: a body does not snap back upright in two frames.
TOUCH_RECOVER_S = 0.28
# A ball in close control (engine.tick_carrier, D6: the softest push is not his, so it stays at his
# feet) rides against his body and is moved by no touch of the engine's. Drawn, the swinging foot
# plays it every step, left and right in turn, late in its swing as it comes through low to land
# (V5), so the stride's feet do not run through it (*design*: a touch a step is what keeps a ball
# the engine holds against his body there; the share of the swing is *design*).
CARRY_M = 0.4  # the ball's centre this near his tracked point, on the grass, is at his feet (design)
CARRY_GROUND_M = 0.05  # and no higher than this off it (design: a rolling ball, not a bounce)
TAP_AT = 0.75  # how far through the foot's swing it meets the ball (design)
TAP_HALF = 0.2  # the touch is drawn over this share of the swing either side of it (design)
TAP_ACROSS = 0.5  # a tapping foot meets the ball this share of its radius to its own side (design)
# The engine settles a carried ball to his feet on the side it wants it (engine.tick_carrier, D8:
# shielding, a strike's turn), up to BALL_TO_FEET a second, with no touch of its own. A move this far
# against his body in a frame is drawn as a foot rolling it there (*design*: twice the 4 to 5 cm a
# frame the ball swings round him as he turns at P16's rate, which needs no foot of its own).
SETTLE_M = 0.10
# How a kick is drawn (design, renderer only: the engine says when the ball left and how fast). A
# strike, or a touch that sends the ball away at KICK_OUT_MIN or faster, is a swing of the leg: the
# foot goes back and up behind the hip over KICK_BACK_S (the knee folding, the thigh behind the
# body), swings through over KICK_SWING_S, speeding up, to meet the ball on the contact frame, and
# follows through the way the ball went, rising, over KICK_FOLLOW_S. A harder kick (power, 0 at
# KICK_OUT_MIN to 1 at KICK_OUT_MAX) draws further back, higher, and follows further. The shape is
# that of the instep kick (backswing, forward swing, follow-through: Lees and Nolan 1998, J Sports
# Sci 16:211-234; Kellis and Katis 2007, J Sports Sci Med 6:154-165, *verify* the timings).
KICK_BACK_S = 0.2
KICK_SWING_S = 0.12
KICK_FOLLOW_S = 0.16
KICK_OUT_MIN = 6.0
KICK_OUT_MAX = 25.0
KICK_BACK_M = (0.25, 0.45)  # foot behind the hip at the top of the backswing, soft to hard
KICK_UP_M = (0.30, 0.55)  # its height off the grass
KICK_FOLLOW_M = (0.25, 0.55)  # how far on past the ball it follows through
KICK_RISE_M = (0.15, 0.45)  # and how far it rises doing so
# A keeper holding the ball (the frame names him possessor and his pose is hands) has a hand either
# side of it (meshpose.HOLD_SIDE). A ball below HOLD_STAND_Z (centre height, asset metres) is taken
# bent over it: the trunk bends forward by up to HOLD_BEND and the hips drop by up to HOLD_DROP_M,
# deepest at a ball on the grass (design; a keeper scooping up a ground ball stoops to it). The hands
# go to the ball over HOLD_EASE_S before he has it and leave it as long after.
HOLD_STAND_Z = 1.0
HOLD_BEND = 1.5
HOLD_DROP_M = 0.33  # as low as the planted legs still reach with flat feet (measured on the asset)
HOLD_EASE_S = 0.16
# The highest the drawn hands reach standing, in the asset's metres (*measured*: meshpose.arm_points
# with the hold aimed 1.8 to 3 m up tops out at 1.91). A ball caught above it is drawn caught in a
# jump, as a header above the brow is, and no higher (HEADER_LIFT_MAX).
HAND_REACH_Z = 1.91
HOLD_RUN_MPS = 4.0  # at this speed or faster a keeper takes the ball without dropping his hips (design)
# How a throw-in is drawn (design, renderer only). The ball is the engine's and the body follows it,
# never the reverse: it lies on the grass in front of the taker until the frame the engine names him
# thrower, rises straight up into his hands over his head from the next frame (engine.throw_hands,
# at P6's 12 m/s: about four frames), stays there while he sets, and leaves on the first frame after
# (Law 15, GROUNDING L7 and D5). Drawn, he bends over the ball and has a hand either side of it
# (meshpose.HOLD_SIDE, as a keeper holds it) by the frame it starts to rise, over THROW_PICK_S; keeps
# them on it as it rises, the trunk bent over it only as far as its height asks (as a keeper's,
# hold_at), so he straightens as it comes up; leans into the throw (THROW_LEAN) over the
# THROW_LOAD_S before he lets it go, so the ball is over his head with the elbows bent; and follows
# through: his hands go on the way the ball went, THROW_FOLLOW_M, and down THROW_DROP_M over
# THROW_FOLLOW_S, the trunk bending on to THROW_BEND, and come back to his sides over
# THROW_RECOVER_S. The engine holds the ball where it lets it go, in front of his head,
# so the drawn throw has no backswing behind the head: drawing one would move the ball off its truth.
THROW_PICK_S = 0.7
HANG_AHEAD_M, HANG_Z = 0.05, 0.75  # between his hands as they hang (asset rest pose, asset metres)
THROW_LOAD_S = 0.2
THROW_LEAN = 0.2
THROW_FOLLOW_S = 0.2
THROW_FOLLOW_M = 0.35
THROW_DROP_M = 0.55
THROW_BEND = 0.45
THROW_RECOVER_S = 0.5
TOUCH_PARTS = ("foot", "thigh", "chest", "head")
HEADER_LIFT_MAX = 0.3  # a header above the standing brow is drawn as a jump, at most this high
HEAD_Z = 1.575  # the centre of the mesh's head (chin about 1.47, skull top 1.684, asset metres)
REF_STATURE_M = 1.84  # the stature body_parts' capsule radii are given for
HEADER_AIR_S = 0.24  # half the time in the air
# A foot reaching a ball beyond a standing leg's reach lunges: the hips drop until the leg (hip to
# sole LEG_M, in the asset's own metres, from the asset) reaches it from a hip HIP_SIDE_M to that side,
# by at most LUNGE_MAX (design). The engine's foot reaches 1 m from his centre (P14).
LEG_M = 0.9
HIP_SIDE_M = 0.1
HIP_M = 0.91
LUNGE_MAX = 0.3
# With the hips lowered (a lunge, a stoop) a foot stays down while it is within LOW_HOLD_M of where
# it would stand; a body moving on past it steps it back under him (design: inside the 0.3 to 0.45 m
# the lowered leg was measured to reach with a flat foot).
LOW_HOLD_M = 0.3
LOW_M = 0.05  # how far the hips drop before the body counts as lowered (a lunge, a stoop)
OUT_OF_REACH_M = 0.45  # a planted foot this far from where it stands is beyond the leg (asset m, measured)


def _wrap(a: float) -> float:
    return (a + math.pi) % (2 * math.pi) - math.pi


def _ease(u: float) -> float:
    u = min(max(u, 0.0), 1.0)
    return u * u * (3.0 - 2.0 * u)


SKIN_TONES = ("#f5d0b5", "#e8b897", "#d19a74", "#b07850", "#8d5a3b", "#6b4329", "#4a2e1d")
HAIR_COLORS = ("#1b1410", "#3b2516", "#6b4a2b", "#a37a4c", "#d9c08c", "#2b2b2b", "#8a3b1d")


@dataclass(frozen=True)
class Look:
    """Per-player appearance, fixed for the clip and logged in clip.json."""

    id: str
    team: str
    role: str
    height_m: float
    build: float  # 0.9 slim .. 1.15 broad
    skin: str
    hair: str
    hair_style: str = "short"  # bald, short, crown. A second draw, so the fields above stay put.


def sample_looks(players: list[dict], seed: int) -> list[Look]:
    rng = random.Random(f"looks-{seed}")
    # Own stream. Drawing it on `rng` would move the next player's height and shirt colour.
    shape = random.Random(f"looks-shape-{seed}")
    looks = []
    for p in players:
        looks.append(
            Look(
                id=p["id"],
                team=p["team"],
                role=p.get("role", ""),
                height_m=round(min(max(rng.gauss(1.81, 0.07), 1.65), 1.98), 3),
                build=round(rng.uniform(0.9, 1.15), 3),
                skin=rng.choice(SKIN_TONES),
                hair=rng.choice(HAIR_COLORS),
                hair_style=shape.choice(("bald", "short", "short", "crown")),
            )
        )
    return looks


@dataclass
class Gait:
    phase: float = 0.0
    heading: float = 0.0  # radians in the pitch plane, from the engine when it has one
    speed: float = 0.0
    action: str = "stand"  # the engine's pose: run, or the part that met the ball
    dive: float = 0.0  # -1..1, keeper reaching to his left or right
    plant_l: tuple[float, ...] | None = None  # world (x, y, yaw, lift) of a foot the mesh puts there
    plant_r: tuple[float, ...] | None = None
    down_l: bool = False
    down_r: bool = False
    lead: float = 0.0  # how far the hips are ahead of the chest in a turn (radians)
    dive_n: int = -1  # frames into the dive being drawn, -1 when none (keeper_dive)
    up_n: int = -1  # frames into getting up after it, -1 when none
    dive_side: float = 1.0  # the side he dived to, as it was when the dive began
    dive_heading: float = 0.0  # the way he faced when it began
    dive_drawn: float = 0.0  # how far along the drawn dive is (0..1)
    dive_from: float = 0.0  # where a dive taken up again in mid get-up starts from
    dive_up: float = 0.0  # getting up: how much of the dive (signed by side) is still drawn over the pose
    feet: dict = field(default_factory=dict)  # side -> foot on the grass or stepping (_stance)
    ankle: dict = field(default_factory=dict)  # side -> last drawn sole (x, y, height): where a step starts
    touch: dict | None = None  # the part meeting the ball now: part, side, at (world), w
    hold: dict | None = None  # a held ball: at (world, its centre), w, bend
    supporting: bool = False  # the feet stand and step for a touch or a lunge (_feet)
    played: str | None = None  # the foot that played the ball last frame (_feet)
    lift: float = 0.0  # metres the body is raised (a header's jump) or lowered (a lunge, a stoop)
    bob: float = 0.0  # metres the stride raises or lowers the hips this frame (_bob), drawn with lift
    bob_w: float = 0.0  # how much of the stride's bob is drawn (BOB_EASE_FRAMES)
    bob_at: float = 0.0  # the stride's bob when it was last drawn
    flight_s: float = 0.0  # how long both feet have been off the grass in a run (_stride_feet)
    vel: list = field(default_factory=list)  # the engine's velocity, the last ACCEL_BOX frames (pace)
    accel: float = 0.0  # his acceleration the way he faces, from the engine's velocity (m/s^2, pace)
    lean: float = 0.0  # the trunk's lean on top of the stride's (radians, forward +, pace)
    accel_lat: float = 0.0  # his acceleration across the way he faces (m/s^2, to his left +, pace)
    roll: float = 0.0  # the trunk tipped into a turn (radians, to his left +, pace)
    fall: float = 0.0  # radians the body is tipped over its feet: a fouled player going down (fouls.py)
    signal: dict | None = None  # one hand up: side, at (world), w (fouls.signal_at)
    dive_tip: float = 0.0  # radians the drawn dive has the body over (dive_pose)
    dive_lie: float = 0.0  # and at its deepest, which the get-up starts from
    tip_ahead: float = 0.0  # metres ahead of his tracked point the body tips over (fouls.tip)
    crouch: dict | None = None  # getting up on one knee: w, lead (fouls.get_up)
    brace: dict | None = None  # a fouled player's hands out as he falls: l, r (world), w (fouls.fall_at)
    look: dict | None = None  # the head turned: yaw (radians from his facing), w (fouls.look_at)
    fall_dir: float = 0.0  # the way he falls, pitch radians
    look_yaw: float = 0.0  # where his head is turned to watch the ball, from his facing (watch_ball)


def update_gait(g: Gait, dx: float, dy: float, dt: float, face: tuple[float, float] | None) -> None:
    d = math.hypot(dx, dy)
    speed = d / dt
    g.speed += (speed - g.speed) * 0.3
    if d > 0.01:
        target = math.atan2(dy, dx)
    elif face is not None and math.hypot(*face) > 0.1:
        target = math.atan2(face[1], face[0])
    else:
        target = g.heading
    diff = (target - g.heading + math.pi) % (2 * math.pi) - math.pi
    g.heading = turn_toward(g.heading, g.heading + diff, dt)
    g.phase = (g.phase + 2 * math.pi * d / _stride(speed)) % (2 * math.pi)


def pace(g: Gait, vx: float, vy: float, heading: float, dt: float, ahead: list | None = None) -> None:
    """Follow the engine's velocity (m/s): his acceleration the way he faces, and the trunk's lean
    from it and from his speed (RUN_LEAN). `ahead` is the engine's velocity over the next frames:
    the acceleration is the change from the ACCEL_BOX frames before this one to this and the ones
    after, so the lean comes as the pace changes, not after it."""
    future = [(vx, vy), *(ahead or [])][:ACCEL_BOX]
    n = ACCEL_BOX
    if len(g.vel) == n and len(future) == n:
        # Until both boxes are full (the clip's first and last frames) he keeps the last one: a
        # shorter box is the engine's frame-to-frame steps again.
        ax = (sum(v[0] for v in future) - sum(v[0] for v in g.vel)) / (n * n * dt)
        ay = (sum(v[1] for v in future) - sum(v[1] for v in g.vel)) / (n * n * dt)
        g.accel = ax * math.cos(heading) + ay * math.sin(heading)
        g.accel_lat = -ax * math.sin(heading) + ay * math.cos(heading)
    g.vel.append((vx, vy))
    del g.vel[:-ACCEL_BOX]
    v = math.hypot(vx, vy)
    target = LEAN_DRAWN * math.atan(min(g.accel, ACCEL_MAX) / GRAVITY) + _table(RUN_LEAN, v)
    g.lean += (target - g.lean) * LEAN_EASE
    g.lean = max(g.lean, -_stride_lean(v))  # slowing, back to upright and no further
    # Into a turn, as into a change of pace: the body leans the way it is accelerated, across as
    # along (Kugler and Janshen 2010: the ground force follows the lean), drawn by the same share.
    across = max(-ACCEL_MAX, min(ACCEL_MAX, g.accel_lat))
    g.roll += (LEAN_DRAWN * math.atan(across / GRAVITY) - g.roll) * LEAN_EASE


def _stride_lean(speed: float) -> float:
    """The stored stride's own lean as meshpose draws it at this speed: grown with the stride
    (STRIDE_GROW, from the asset's walkScale) and out of the stance (STAND_BLEND)."""
    if speed < STAND_BLEND[0]:
        return 0.0
    walk = asset()["walkScale"]
    t = min(max((speed - STRIDE_GROW[0]) / (STRIDE_GROW[1] - STRIDE_GROW[0]), 0.0), 1.0)
    share = walk + (1.0 - walk) * t
    if speed < STAND_BLEND[1]:
        share *= (speed - STAND_BLEND[0]) / (STAND_BLEND[1] - STAND_BLEND[0])
    return STRIDE_LEAN * share


def _pump(speed: float) -> float:
    """How much wider than the stored run's the arms swing at this speed (PUMP)."""
    return _table(PUMP, speed)


def advance_gaits(gaits: dict[str, Gait], prev_xy: dict[str, tuple[float, float]], frame: dict,
                  dt: float, ahead: dict | None = None, after: list[dict] | None = None) -> None:
    """One frame of every player's gait: stride from how far he moved, and the way he faces, his
    speed and his pose from the engine (face), so the body is drawn turned as it collides.
    `ahead` is the engine's frame LEAD_AHEAD_FRAMES on: the hips lead into the turn it holds.
    `after` is the engine's next frames (up to ACCEL_BOX): the trunk leans into a change of pace."""
    bx, by = frame["ball"]["x"], frame["ball"]["y"]
    later = {pl["id"]: pl for pl in ahead["players"]} if ahead else {}
    coming: dict[str, list] = {}
    for fr in after or []:
        for p in fr["players"]:
            coming.setdefault(p["id"], []).append((p.get("vx", 0.0), p.get("vy", 0.0)))
    for pl in frame["players"]:
        g = gaits[pl["id"]]
        px, py = prev_xy.get(pl["id"], (pl["x"], pl["y"]))
        update_gait(g, pl["x"] - px, pl["y"] - py, dt, (bx - pl["x"], by - pl["y"]))
        pace(g, pl.get("vx", 0.0), pl.get("vy", 0.0), g.heading, dt, coming.get(pl["id"]))
        prev_xy[pl["id"]] = (pl["x"], pl["y"])
        face(g, pl)
        keeper_dive(g)
        nxt = later.get(pl["id"])
        g.lead = 0.0
        if nxt is not None and "heading" in nxt and "heading" in pl and g.action not in ("dive", "throw"):
            g.lead = min(max(_wrap(nxt["heading"] - pl["heading"]), -LEAD_MAX), LEAD_MAX)


def contacts(frames: list[dict], events: list[dict] | None = None) -> dict[str, list[dict]]:
    """Every touch the engine drew, per player: the frame the part meets the ball, the part, which
    side of him the ball was, where the ball was, and how the touch changed its velocity.

    A touch names its part from the frame it happened (scene pose, engine TOUCH_POSE_S), so that
    frame shows the ball as it left the part. A strike is drawn over its wind-up; the ball leaves on
    the frame after the last one, so the last wind-up frame shows the ball still at his foot. A
    tackle that pokes the ball loose has no pose of its own (engine.poke): its event names the
    tackler and the frame, and his foot is drawn meeting the ball there.
    """
    found: list[tuple[str, int, str, int, int]] = []
    prev: dict[str, str] = {}
    for i, fr in enumerate(frames):
        for pl in fr["players"]:
            a, was = pl.get("action", ""), prev.get(pl["id"], "")
            prev[pl["id"]] = a
            if a in TOUCH_PARTS and a != was:
                found.append((pl["id"], i, a, max(i - 1, 0), i))
            elif was == "strike" and a != "strike" and i > 0:
                found.append((pl["id"], i - 1, "strike", i - 1, i))
    index = {fr.get("frame", i): i for i, fr in enumerate(frames)}
    seen = {(who, at) for who, at, *_ in found}
    aimed: dict[tuple[str, int], dict] = {}  # a contact aimed at a body, not the ball
    for ev in events or ():
        i = index.get(ev.get("frame"))
        if ev.get("type") == "tackle" and ev.get("player") and i and (ev["player"], i) not in seen:
            found.append((ev["player"], i, "foot", i - 1, i))
        foul = ev.get("type") == "foul" and ev.get("player") and ev.get("receiver")
        if foul and i and (ev["player"], i) not in seen:
            # The foul is the fouler's leg into the other man (Law 12; lesson 173): his foot goes to
            # the fouled player's legs, shin high, on the side facing him, as a tackle's goes to the ball.
            pos = {p["id"]: p for p in frames[i]["players"]}
            them, him = pos.get(ev["receiver"]), pos.get(ev["player"])
            if them and him:
                dx, dy = him["x"] - them["x"], him["y"] - them["y"]
                d = math.hypot(dx, dy) or 1.0
                aimed[(ev["player"], i)] = {"x": them["x"] + dx / d * FOUL_REACH_M,
                                            "y": them["y"] + dy / d * FOUL_REACH_M, "z": FOUL_SHIN_M}
                found.append((ev["player"], i, "foot", i - 1, i))
    settled = _settles(frames, found)
    found.extend(settled)
    out: dict[str, list[dict]] = {}
    for pid, at, part, v_in, v_out in sorted(found, key=lambda f: (f[1], f[0])):
        who = next((p for p in frames[at]["players"] if p["id"] == pid), None)
        if who is None:
            continue
        bi, bo = frames[v_in]["ball"], frames[v_out]["ball"]
        b = frames[at]["ball"]
        if (pid, at) in aimed:
            b, bi, bo = aimed[(pid, at)], {"vx": 0.0, "vy": 0.0}, {"vx": 0.0, "vy": 0.0}
        elif part != "strike":
            # The part met the ball inside the tick, where its path from the frame before
            # passed closest to him; by this frame the ball has flown on from there.
            b = _closest(bi, bo, who["x"], who["y"])
        dvx = bo.get("vx", 0.0) - bi.get("vx", 0.0)
        dvy = bo.get("vy", 0.0) - bi.get("vy", 0.0)
        if (pid, at, part, v_in, v_out) in settled:
            # The engine gives a settled ball his velocity, so the way the foot rolls it is the way
            # it moved against him over the frame.
            was = next(p for p in frames[v_in]["players"] if p["id"] == pid)
            dvx = (bo["x"] - who["x"]) - (bi["x"] - was["x"])
            dvy = (bo["y"] - who["y"]) - (bi["y"] - was["y"])
            dvx, dvy = dvx * round(1 / FRAME_S), dvy * round(1 / FRAME_S)
        h = who.get("heading", 0.0)
        hx, hy = math.cos(h), math.sin(h)
        lateral = (b["x"] - who["x"]) * -hy + (b["y"] - who["y"]) * hx
        out.setdefault(pid, []).append({
            "frame": at,
            "part": part,
            "side": "l" if lateral >= 0 else "r",
            "ball": (b["x"], b["y"], b["z"] + BALL_RADIUS),
            "dv": (dvx, dvy),
            "out": math.hypot(bo.get("vx", 0.0), bo.get("vy", 0.0)),
            "heading": h,
            "at": (who["x"], who["y"]),
            # A settle is the ball rolled at his feet, never a kick, however fast he runs with it.
            "settle": (pid, at, part, v_in, v_out) in settled,
        })
    return out


def _settles(frames: list[dict], found: list[tuple]) -> list[tuple[str, int, str, int, int]]:
    """Frames where a carried ball moves SETTLE_M or more against its carrier's body with no touch of
    the engine's drawn there: the first of each run of such frames, as a touch with the foot (contacts).
    Frames inside one of his own touches' windows are left to that touch."""
    lo, hi = _touch_window({"part": "strike", "out": KICK_OUT_MIN})
    near: dict[str, list[int]] = {}
    for who, at, *_ in found:
        near.setdefault(who, []).append(at)
    out: list[tuple[str, int, str, int, int]] = []
    last: dict[str, int] = {}
    for i in range(1, len(frames)):
        fr, pr = frames[i], frames[i - 1]
        who = fr.get("possessor")
        if not who or pr.get("possessor") != who:
            continue
        p = next((q for q in fr["players"] if q["id"] == who), None)
        q = next((q for q in pr["players"] if q["id"] == who), None)
        b, c = fr["ball"], pr["ball"]
        # Only a ball he runs or stands with: in any other pose the engine is drawing a touch, a
        # strike's turn or a hold of its own.
        if p is None or q is None or p.get("action") not in ("walk", "run", "stand"):
            continue
        if max(b["z"], c["z"]) > CARRY_GROUND_M:
            continue
        moved = math.hypot((b["x"] - p["x"]) - (c["x"] - q["x"]), (b["y"] - p["y"]) - (c["y"] - q["y"]))
        if moved < SETTLE_M:
            continue
        run = last.get(who) == i - 1
        last[who] = i
        if run or any(lo * round(1 / FRAME_S) < i - at < hi * round(1 / FRAME_S) for at in near.get(who, ())):
            continue
        out.append((who, i, "foot", i - 1, i))
        near.setdefault(who, []).append(i)
    return out


def _closest(a: dict, b: dict, x: float, y: float) -> dict:
    """The point of the ball's straight path from `a` to `b` nearest (x, y), in the pitch plane."""
    dx, dy = b["x"] - a["x"], b["y"] - a["y"]
    n = dx * dx + dy * dy
    t = 0.0 if n < 1e-12 else min(max(((x - a["x"]) * dx + (y - a["y"]) * dy) / n, 0.0), 1.0)
    return {"x": a["x"] + dx * t, "y": a["y"] + dy * t, "z": a["z"] + (b["z"] - a["z"]) * t}


def _kick(c: dict) -> bool:
    return c["part"] == "strike" or (c["part"] == "foot" and c["out"] >= KICK_OUT_MIN and not c.get("settle"))


def _touch_window(c: dict) -> tuple[float, float]:
    """Seconds before and after the contact frame that the touch is drawn. A lunge starts going
    down as long before the touch as it takes to come back up after it."""
    if _kick(c):
        return -(KICK_BACK_S + KICK_SWING_S), KICK_FOLLOW_S + TOUCH_RECOVER_S
    return -max(TOUCH_WIND_S, TOUCH_RECOVER_S), TOUCH_FOLLOW_S + TOUCH_RECOVER_S


def _touch_weight(c: dict, u: float) -> float:
    lo, hi = _touch_window(c)
    if _kick(c):
        rise = _ease((u + KICK_BACK_S + KICK_SWING_S) / KICK_BACK_S)
    else:
        # The part sets off for the ball from the start of the window, so a foot that was far from
        # it (a poke from mid-stride) is not flung there in a few frames.
        rise = _ease((u - lo) / (-lo - TOUCH_SET_S))
    return min(rise, _ease((hi - u) / TOUCH_RECOVER_S))


def touch_at(g: Gait, mine: list[dict], fi: int, height_m: float, fps: int,
             x: float | None = None, y: float | None = None) -> None:
    """Set the part meeting the ball at frame `fi` (g.touch) and any jump to a header (g.lift).
    (x, y) is where he is now; a kick's backswing is drawn behind his hips there."""
    g.touch, g.lift = None, 0.0
    best = None
    for c in mine:
        u = (fi - c["frame"]) / fps
        lo, hi = _touch_window(c)
        if lo < u < hi:
            w = _touch_weight(c, u)
            if w <= 0.0 and c["part"] not in ("foot", "strike"):
                continue
            # Two touches close together: the one further into its swing is drawn.
            if best is None or w > best[2] or (w == best[2] and abs(u) < abs(best[1])):
                best = (c, u, w)
    if best is None:
        return
    c, u, w = best
    k = height_m / ASSET_STATURE_M
    part = c["part"]
    dvx, dvy = c["dv"]
    n = math.hypot(dvx, dvy)
    dx, dy = (dvx / n, dvy / n) if n > 0.5 else (math.cos(c["heading"]), math.sin(c["heading"]))
    bx, by, bz = c["ball"]
    gap = {"foot": 0.02, "strike": 0.02, "thigh": 0.05}.get(part, 0.02)
    px, py = bx - dx * (BALL_RADIUS + gap), by - dy * (BALL_RADIUS + gap)
    pz = max(bz - 0.07, 0.03) if part in ("foot", "strike") else bz - 0.05 if part == "thigh" else bz
    if _kick(c):
        at = _kick_path(c, u, (px, py, pz), (dx, dy), g.heading,
                        c["at"] if x is None or y is None else (x, y), k)
    else:
        if part == "foot":
            back = min(max(0.12 + 0.012 * c["out"], 0.12), 0.4) * k
            follow = min(max(0.08 + 0.01 * c["out"], 0.08), 0.35) * k
            rise = 0.6
        else:
            back, follow, rise = 0.08 * k, 0.05 * k, 0.0
        if u < 0:
            s = min(u / TOUCH_WIND_S, 1.0) ** 2 if u > -TOUCH_WIND_S else 1.0
            off, up = -back * s, back * rise * s
        else:
            # Past the follow-through it stays there while it eases back to the stride.
            q = math.sin(0.5 * math.pi * min(u / TOUCH_FOLLOW_S, 1.0))
            off, up = follow * q, follow * rise * 0.5 * q
        at = (px + dx * off, py + dy * off, pz + up)
    if u > 0 and x is not None and y is not None:
        # After the ball has gone the follow-through goes on with him: a part left reaching for a
        # spot on the grass he has run past drags the leg out behind him.
        at = (at[0] + x - c["at"][0], at[1] + y - c["at"][1], at[2])
    g.touch = {
        "part": part,
        "side": c["side"],
        "soft": part == "foot" and not _kick(c),  # a touch, not a kick: taken in stride on the move (_feet)
        "at": [round(at[0], 4), round(at[1], 4), round(max(at[2], 0.02), 4)],
        "w": round(w, 4),
    }
    if part in ("foot", "strike"):
        far = math.hypot(px - c["at"][0], py - c["at"][1]) / k - HIP_SIDE_M
        if far > 0:
            hip = math.sqrt(max(LEG_M * LEG_M - far * far, 0.0))
            drop = min(max(HIP_M - hip, 0.0), LUNGE_MAX) * k
            # The hips go down over the whole wind-up and start back up as soon as the ball has
            # gone, over TOUCH_RECOVER_S: he does not run on crouched in the follow-through.
            lo, _ = _touch_window(c)
            sink = min(_ease((u - lo) / -lo), _ease((TOUCH_RECOVER_S - u) / TOUCH_RECOVER_S))
            g.lift = -round(drop * sink, 4)
    if part == "head":
        rise_m = min(pz - BROW_Y * k, HEADER_LIFT_MAX)
        if rise_m > 0.02:
            g.lift = round(rise_m * max(0.0, 1.0 - (u / HEADER_AIR_S) ** 2), 4)


def carry_at(g: Gait, frame: dict, pid: str, x: float, y: float, height_m: float) -> None:
    """A ball in close control (CARRY_M): each step the swinging foot plays it (g.touch), left and
    right in turn, late in its swing (TAP_AT), on the ball's back on that foot's side, taken in
    stride like any touch on the move (_feet). Leaves
    g.touch alone when the engine's own touch, a hold or a throw is drawn, or he is not carrying it."""
    if g.touch is not None or g.hold is not None or frame.get("possessor") != pid:
        return
    if g.action not in ("walk", "run") or g.speed < STRIDE_FROM_MPS:
        return
    b = frame["ball"]
    rx, ry = b["x"] - x, b["y"] - y
    if b["z"] > CARRY_GROUND_M or math.hypot(rx, ry) > CARRY_M:
        return
    k = height_m / ASSET_STATURE_M
    hx, hy = math.cos(g.heading), math.sin(g.heading)
    stride = _stride(g.speed)
    reach = (PLANT_AHEAD_MAX + STANCE_BEHIND_MAX) * k
    half = min(_duty(g.speed) * math.pi, math.pi * reach / stride)  # as _stride_feet has the stance
    air = 2 * math.pi - 2 * half

    def off_for(side: str) -> float:  # how far, in its touch's half-widths, from its swing meeting the ball
        return abs(_wrap(g.phase - (STANCE_CENTRE[side] + half + TAP_AT * air))) / (TAP_HALF * air)

    side = min(("l", "r"), key=off_for)
    off = off_for(side)
    if off >= 1.0:
        return
    sign = 1.0 if side == "l" else -1.0
    # The foot behind the ball, the way he carries it (touch_at's foot, with no kick in it).
    n = math.hypot(rx, ry) or 1.0
    dx, dy = (rx / n, ry / n) if math.hypot(rx, ry) > BALL_RADIUS else (hx, hy)
    bx, by, bz = b["x"], b["y"], b["z"] + BALL_RADIUS
    # On that foot's side of the ball's back (*design*: half the radius across, so a left and a right
    # foot do not both meet it dead centre).
    across = TAP_ACROSS * BALL_RADIUS * sign
    px = bx - dx * (BALL_RADIUS + 0.02) - dy * across
    py = by - dy * (BALL_RADIUS + 0.02) + dx * across
    g.touch = {"part": "foot", "side": side, "soft": True,
               "at": [round(px, 4), round(py, 4), round(max(bz - 0.07, 0.03), 4)],
               "w": round(_ease(1.0 - off), 4)}


# A player watches the ball: his head turns toward it on the neck, no further than LOOK_MAX (fouls.py,
# *design*), no faster than P16's 350 degrees a second, which P16 applies to where he looks too (the
# source measures the body's turn, not the head's: *design*). Drawn only: the body faces the engine's
# heading. A ball nearer than LOOK_NEAR_M is at his feet or on him: he looks the way he faces (*design*).
LOOK_RATE = math.radians(350.0)
LOOK_NEAR_M = 0.5
# The contact poses the mesh draws whole (meshpose._CONTACT less _FEET): no lean into a turn on them.
ROLL_FREE = ("chest", "head", "hands", "dive", "shield")
ROLL_HEAD = 1.2  # the label's head goes 1.2 times the shoulders' way (*design*, measured near the mesh's)


def watch_ball(g: Gait, x: float, y: float, ball: tuple[float, float, float]) -> None:
    """Turn the head toward the ball (g.look) unless a foul's look is drawn (fouls.look_at), or he is
    diving, throwing or down, when the head stays with the body."""
    if g.look is not None:
        g.look_yaw = g.look["yaw"]
        return
    want = 0.0
    far = math.hypot(ball[0] - x, ball[1] - y) > LOOK_NEAR_M
    if g.action not in ("dive", "throw") and not g.fall and far:
        want = max(-LOOK_MAX, min(LOOK_MAX, _wrap(math.atan2(ball[1] - y, ball[0] - x) - g.heading)))
    step = LOOK_RATE * FRAME_S
    g.look_yaw += max(-step, min(step, want - g.look_yaw))
    g.look = {"yaw": round(g.look_yaw, 4), "w": 1.0} if abs(g.look_yaw) > 1e-3 else None


def _kick_path(c: dict, u: float, contact: tuple, d: tuple, heading: float, xy: tuple,
               k: float) -> tuple[float, float, float]:
    """Where the kicking foot is aimed `u` seconds from contact: back behind the hip, through the
    ball, on after it (KICK_*)."""
    power = min(max((c["out"] - KICK_OUT_MIN) / (KICK_OUT_MAX - KICK_OUT_MIN), 0.0), 1.0)

    def mix(span: tuple[float, float]) -> float:
        return (span[0] + (span[1] - span[0]) * power) * k

    hx, hy = math.cos(heading), math.sin(heading)
    sign = 1.0 if c["side"] == "l" else -1.0
    side = HIP_SIDE_M * k * sign
    back = mix(KICK_BACK_M)
    top = (xy[0] - hy * side - hx * back, xy[1] + hx * side - hy * back, mix(KICK_UP_M))
    if u <= -KICK_SWING_S:
        return top
    if u <= 0:
        t = 1.0 + u / KICK_SWING_S
        e = t * t  # the foot speeds up into the ball
        return tuple(top[i] + (contact[i] - top[i]) * e for i in range(3))
    q = math.sin(0.5 * math.pi * min(u / KICK_FOLLOW_S, 1.0))
    on, up = mix(KICK_FOLLOW_M) * q, mix(KICK_RISE_M) * q
    return (contact[0] + d[0] * on, contact[1] + d[1] * on, contact[2] + up)


HOLD_ACTIONS = ("hands", "bowl")


def holds(frames: list[dict]) -> dict[str, list[tuple[int, int]]]:
    """Per keeper, the runs of frames (first, last) in which he holds the ball: the frame names him
    its possessor and his pose is hands, or bowl: a throw along the ground, the ball brought down in
    his hands to the grass (the engine's own wind-up; lesson 204), so his hands stay on it to the grass."""
    out: dict[str, list[tuple[int, int]]] = {}
    for i, fr in enumerate(frames):
        who = fr.get("possessor")
        if not who:
            continue
        pl = next((p for p in fr["players"] if p["id"] == who), None)
        if pl is None or pl.get("action") not in HOLD_ACTIONS:
            continue
        runs = out.setdefault(who, [])
        if runs and runs[-1][1] == i - 1:
            runs[-1] = (runs[-1][0], i)
        else:
            runs.append((i, i))
    return out


def hold_at(g: Gait, runs: list[tuple[int, int]], fi: int, ball: tuple[float, float, float],
            height_m: float, fps: int) -> None:
    """Set the hands on a held ball (g.hold), bending over it and dropping the hips if it is low."""
    g.hold = None
    ease = HOLD_EASE_S * fps
    w = 0.0
    for first, last in runs:
        if first - ease < fi < last + ease:
            w = max(w, min(_ease((fi - (first - ease)) / ease), _ease((last + ease - fi) / ease)))
    if w <= 0.0:
        return
    k = height_m / ASSET_STATURE_M
    z = ball[2] + BALL_RADIUS
    depth = _hold_depth(z, k)
    g.hold = {
        "at": [round(ball[0], 4), round(ball[1], 4), round(z, 4)],
        "w": round(w, 4),
        "bend": round(HOLD_BEND * depth, 4),
    }
    # On the move he stoops less: lowered, the legs could not reach feet the body is running past.
    moving = max(0.0, 1.0 - g.speed / HOLD_RUN_MPS)
    g.lift = min(g.lift, -round(HOLD_DROP_M * depth * k * w * moving, 4))
    over = z - HAND_REACH_Z * k
    if over > 0.0:
        # Above his reach he goes up to it: his hands meet the ball on the frame the engine has him
        # take it, as high as a jump is drawn, the ball coming down into them from there.
        g.lift = round(min(over, HEADER_LIFT_MAX) * w, 4)


def _hold_depth(z: float, k: float) -> float:
    """How far over a ball with its centre `z` high a body bends to hold it: 1 on the grass, 0 from
    HOLD_STAND_Z up (in the player's own scale)."""
    return min(max((HOLD_STAND_Z * k - z) / ((HOLD_STAND_Z - BALL_RADIUS) * k), 0.0), 1.0)


def throws(frames: list[dict], fps: int = 25) -> dict[str, list[dict]]:
    """Per taker, his throw-ins: the frame the engine names him thrower (the ball still on the grass;
    it rises from the next frame), the release (the first frame after: the ball still in his hands,
    moving from the next frame) with where the ball was and the way it went, and the ball's centre
    from THROW_PICK_S before the start to the release, where his hands go."""
    out: dict[str, list[dict]] = {}
    prev: dict[str, str] = {}
    pick = round(THROW_PICK_S * fps)
    for i, fr in enumerate(frames):
        for pl in fr["players"]:
            a, was = pl.get("action", ""), prev.get(pl["id"], "")
            prev[pl["id"]] = a
            if a == "throw" and was != "throw":
                out.setdefault(pl["id"], []).append({"start": i, "release": None, "way": None,
                                                     "first": max(0, i - pick)})
            elif was == "throw" and a != "throw" and out.get(pl["id"]):
                t = out[pl["id"]][-1]
                if t["release"] is None:
                    t["release"] = i
                    b0 = fr["ball"]
                    b1 = frames[i + 1]["ball"] if i + 1 < len(frames) else None
                    dx, dy = (b1["x"] - b0["x"], b1["y"] - b0["y"]) if b1 else (b0.get("vx", 0.0),
                                                                                   b0.get("vy", 0.0))
                    n = math.hypot(dx, dy)
                    h = pl.get("heading", 0.0)
                    t["way"] = (dx / n, dy / n) if n > 1e-6 else (math.cos(h), math.sin(h))
                    t["body"] = (pl["x"], pl["y"], h)  # where he stood as he let it go
    for mine in out.values():
        for t in mine:
            last = t["release"] if t["release"] is not None else len(frames) - 1
            balls = (frames[j]["ball"] for j in range(t["first"], last + 1))
            t["ball"] = [(b["x"], b["y"], b["z"] + BALL_RADIUS) for b in balls]
    return out


def throw_at(g: Gait, mine: list[dict], fi: int, height_m: float, fps: int, x: float, y: float) -> None:
    """A throw-in at frame `fi` (throws): both hands on the ball from before it rises until it is
    thrown, then on through the throw (g.hold), bending over it and dropping the hips while it is low
    (g.lift). (x, y) is where he is now. Leaves g.hold and g.lift alone when he is not taking one."""
    pick = round(THROW_PICK_S * fps)
    for t in mine:
        start, rel, first = t["start"], t["release"], t["first"]
        end = math.inf if rel is None else rel + (THROW_FOLLOW_S + THROW_RECOVER_S) * fps
        if not start - pick < fi < end:
            continue
        k = height_m / ASSET_STATURE_M
        # Reaching down for it, the trunk, the hips and the hands' aim go together, from where his
        # hands hang to the ball: an arm aimed at the ball from a body not yet bent to it flips
        # between ways of reaching it.
        s = _ease((fi - (start - pick)) / pick) if fi < start else 1.0
        w = min(1.0, 3.0 * s)
        u = -math.inf if rel is None else (fi - rel) / fps  # seconds since the ball left his hands
        if u > THROW_FOLLOW_S:
            w = min(w, 1.0 - _ease((u - THROW_FOLLOW_S) / THROW_RECOVER_S))
        if u <= 0:
            at = t["ball"][fi - first]
            if s < 1.0:
                hx, hy = math.cos(g.heading), math.sin(g.heading)
                hang = (x + hx * HANG_AHEAD_M * k, y + hy * HANG_AHEAD_M * k, HANG_Z * k)
                at = tuple(hang[j] + (at[j] - hang[j]) * s for j in range(3))
        else:
            # The hands go on the way the ball went, and down, and come back to his sides from there:
            # where they are is kept relative to him, as he turns and walks off after the throw.
            q = math.sin(0.5 * math.pi * min(u / THROW_FOLLOW_S, 1.0))
            bx, by, bz = t["ball"][rel - first]
            sx, sy, sh = t["body"]
            dx, dy = t["way"]
            fx, fy = bx - sx + dx * THROW_FOLLOW_M * k * q, by - sy + dy * THROW_FOLLOW_M * k * q
            c, sn = math.cos(g.heading - sh), math.sin(g.heading - sh)
            at = (x + fx * c - fy * sn, y + fx * sn + fy * c, bz - THROW_DROP_M * k * q)
        # Bent over the ball while it is low, and straightening as it rises, all the way up to where he
        # holds it: the trunk comes up over the whole lift, not in its first two frames. It is up most
        # of the way by the time the ball passes his chest, or his shoulders would be down over the
        # ball, closer to it than his arms can fold to hold it (measured on the asset).
        top = max(max(b[2] for b in t["ball"]), HOLD_STAND_Z * k)
        depth = min(max((top - at[2]) / (top - BALL_RADIUS), 0.0), 1.0) if u <= 0 else 0.0
        bend = HOLD_BEND * depth ** 1.5 * s
        if -THROW_LOAD_S < u <= 0:
            bend += THROW_LEAN * _ease((u + THROW_LOAD_S) / THROW_LOAD_S)
        elif u > 0:
            bend += THROW_LEAN + (THROW_BEND - THROW_LEAN) * _ease(u / THROW_FOLLOW_S)
        g.hold = {"at": [round(at[0], 4), round(at[1], 4), round(at[2], 4)], "w": round(w, 4),
                  "bend": round(bend, 4)}
        # The hips come up ahead of the trunk, for the same reason.
        moving = max(0.0, 1.0 - g.speed / HOLD_RUN_MPS)
        g.lift = min(g.lift, -round(HOLD_DROP_M * depth * depth * k * s * moving, 4))
        return


def face(g: Gait, player: dict) -> None:
    """Turn the drawn body the way the engine says he faces, when the frame says (the engine
    already limits how fast a body turns, GROUNDING P16), so it is drawn as it collides. The
    engine's speed and pose (run, strike, dive, throw, the part that met the ball) come with it."""
    if "heading" in player:
        g.heading = player["heading"]
    if "vx" in player:
        g.speed = math.hypot(player["vx"], player.get("vy", 0.0))
    if "action" in player:
        # A bowl is drawn as the hold it is (holds): both hands on the ball as it comes down to the
        # grass, no kicking leg; the release is the pass the engine makes from the grass.
        g.action = "hands" if player["action"] == "bowl" else player["action"]
        g.dive = player.get("dive", 0.0)


def keeper_dive(g: Gait) -> None:
    """Draw the engine's dive once (DIVE_IN_FRAMES, DIVE_UP_FRAMES): after face(), set the drawn
    dive (g.dive), the dive still drawn while he gets up (g.dive_up) and the drawn facing (g.heading)
    for this frame."""
    g.dive_up = 0.0
    if g.action == "dive":
        if g.dive_n < 0:
            g.dive_from = g.dive_drawn if g.up_n >= 0 else 0.0
            if g.up_n < 0:
                g.dive_side = 1.0 if g.dive >= 0.0 else -1.0
                g.dive_heading = g.heading
        g.dive_n += 1
        g.up_n = -1
        ramp = g.dive_from + (1.0 - g.dive_from) * min(1.0, (g.dive_n + 1) / DIVE_IN_FRAMES)
        g.dive_drawn = max(g.dive_drawn if g.dive_n > 0 else 0.0, min(abs(g.dive), ramp))
        g.dive, g.heading = g.dive_side * g.dive_drawn, g.dive_heading
        return
    if g.dive_n < 0 and g.up_n < 0:
        return
    if g.dive_n >= 0:
        g.dive_n, g.up_n = -1, 0
        g.dive_from = g.dive_drawn
    else:
        g.up_n += 1
    if g.up_n >= DIVE_UP_FRAMES:
        g.up_n, g.dive_drawn = -1, 0.0
        return
    t = _ease((g.up_n + 1) / DIVE_UP_FRAMES)
    g.heading = g.dive_heading + _wrap(g.heading - g.dive_heading) * t
    g.dive_drawn = g.dive_from * (1.0 - t)
    g.dive_up = g.dive_side * g.dive_drawn


# A keeper's dive is drawn as a person dives (lesson 280, *design*): the body straight, tipped over
# his feet toward the side he dives (the engine's side), as far as DIVE_TIP at full stretch, with the
# arms reaching on past his head (his feet stay planted: lifted, they left their plants in a frame);
# getting up, the get-up of a fall
# (fouls.get_up). The engine's position stays his feet. The stored dive pose bent the spine
# 1.7 rad sideways over straight legs: it read as a lean and twisted the skinned body.
DIVE_TIP = math.radians(80.0)
DIVE_ARMS_OUT = 0.15  # metres the hands go toward his dive side, past the head
DIVE_ARMS_LET_GO = 0.7  # of the get-up, over which the arms come down
# The body goes over no faster than this a frame (*design*: the hands, 2.4 m out past his head with
# the arms up, then move no more than the limb cap of tests/test_render_motion.py, 0.14 m a frame);
# a full dive is on the grass in 0.9 s.
DIVE_TIP_RATE = 0.06
# He goes over his near foot's outside edge, not his tracked point (*design*: the boots and their
# capsules reach about this far out; tipped over the tracked point the near foot went 0.28 m into the
# grass), and so lies on his side, his hip on the grass.
DIVE_TIP_AHEAD_M = 0.3
DIVE_UP_STILL_MPS = 1.5  # moving this fast or faster, the get-up has no kneel


def dive_pose(g: Gait, x: float, y: float, height_m: float) -> None:
    """After fouls.fall_at: a keeper's drawn dive (g.dive, or g.dive_up getting up) as the body
    tipped over his feet (g.fall, g.fall_dir), his jump (g.lift) and his arms (g.brace)."""
    from ninety.render import fouls

    m = g.dive if g.action == "dive" else g.dive_up
    if not m:
        g.dive_tip = g.dive_lie = 0.0
        return
    side = 1.0 if m > 0 else -1.0
    mag = min(abs(m), 1.0)
    way = g.heading + side * math.pi / 2  # his left is +
    if g.action == "dive":
        # Over no faster than DIVE_TIP_RATE: the body is in the air until it is down.
        g.dive_tip = min(DIVE_TIP * mag, g.dive_tip + DIVE_TIP_RATE) if mag >= g.dive_tip / DIVE_TIP \
            else g.dive_tip
        g.fall, arms, crouch, g.dive_lie = g.dive_tip, 1.0, 0.0, g.dive_tip
    else:
        want, arms, crouch = fouls.get_up(g.dive_lie, (g.up_n + 1) / DIVE_UP_FRAMES)
        g.dive_tip = max(want, g.dive_tip - DIVE_TIP_RATE)  # up no faster than he went over
        g.fall = g.dive_tip
        g.crouch = None  # his feet are planted again: the lowered body bends the knees (lift)
        # On a knee only while the engine has him still: moving, he gets up as he goes.
        still = min(max(1.0 - g.speed / DIVE_UP_STILL_MPS, 0.0), 1.0)
        g.lift = min(g.lift, fouls.crouch_lift(crouch * still, "l", height_m))  # a catch's lowering stays
    g.fall_dir = way
    g.tip_ahead = DIVE_TIP_AHEAD_M
    lx, ly = -math.sin(g.heading), math.cos(g.heading)
    if g.action == "dive" or arms > 0.0:
        # The arms on past his head through the dive, let go of over the first of the get-up (the
        # catch's or the stand's arms come back under them): no jump to the grass in a frame.
        hands = {}
        top = (fouls.SHOULDER_Z + fouls.ARM_M * fouls.ARM_REACH) * height_m
        for s_, sign in (("l", 1.0), ("r", -1.0)):
            off = sign * fouls.SHOULDER_SIDE_M + side * DIVE_ARMS_OUT
            hands[s_] = [round(x + off * lx, 4), round(y + off * ly, 4), round(top + g.lift, 4)]
        w = fouls._smooth(g.dive_lie / DIVE_TIP)  # up as he goes over
        if g.action != "dive":
            w *= 1.0 - fouls._smooth((g.up_n + 1) / DIVE_UP_FRAMES / DIVE_ARMS_LET_GO)
        g.brace = {"w": round(w, 4), **hands} if w > 0.0 else None


def reach_sign(x: float, y: float, g: Gait, ball: tuple[float, ...] | None) -> float:
    """Which foot the ball is on: 1 is his left, -1 his right. 0 if the pose does not pick a side."""
    if g.action not in ("strike", "foot", "thigh"):
        return 0.0
    if g.touch is not None and g.touch["part"] in ("strike", "foot", "thigh"):
        return 1.0 if g.touch["side"] == "l" else -1.0
    if ball is None:
        return 0.0
    hx, hy = math.cos(g.heading), math.sin(g.heading)
    lateral = (ball[0] - x) * -hy + (ball[1] - y) * hx
    return 1.0 if lateral >= 0 else -1.0


def _step_frames(dist: float, speed: float = 0.0) -> int:
    """How many frames a step of `dist` metres takes: STEP_FRAMES, or longer for a long step, so
    the foot is never faster than STEP_PEAK_MPS, or STEP_CATCH_UP times the body's `speed` when he
    is moving faster than a step would follow (it covers its way in the middle 70% of the step,
    smoothstep, whose peak is 1.5 times its mean). A support foot left behind by a running player
    stepped at standing pace and never caught him up: the leg hung toward it (seed 7, h6's strike)."""
    peak = max(STEP_PEAK_MPS, STEP_CATCH_UP * speed)
    return max(STEP_FRAMES, math.ceil(1.5 * dist / (0.7 * peak * FRAME_S)))


def _gait_pose(g: Gait, x: float, y: float) -> dict:
    return {"action": g.action, "speed": g.speed, "phase": g.phase, "lead": g.lead, "x": x, "y": y}


def _home(x: float, y: float, yaw: float, k: float, sign: float) -> tuple[float, float]:
    hx, hy = math.cos(yaw), math.sin(yaw)
    f, side = FOOT_HOME[1] * k, FOOT_HOME[0] * k * sign
    return (x + hx * f - hy * side, y + hy * f + hx * side)


def _feet(g: Gait, x: float, y: float, k: float) -> None:
    """Which feet are on the grass this frame, where, and pointing which way (g.feet, g.plant_*).

    Running, a foot lands a little ahead on its part of the stride and stays put until the stride
    lifts it. Standing or shuffling, the feet stay put and step when the body has turned or moved
    off them (STEP_*). Either way a foot on the grass keeps the way it pointed when it landed,
    pivoting only when the hip can turn no further (HIP_ROT).
    """
    pel = g.heading + g.lead
    busy, soft = None, False
    if g.touch is not None and g.touch["w"] > 0 and g.touch["part"] in ("foot", "strike", "thigh"):
        busy, soft = g.touch["side"], bool(g.touch.get("soft"))
    # A foot that has just played the ball comes back to the grass from where the touch drew it
    # (g.ankle), not from where it stood before the touch: the body has moved on since, and a foot
    # left there can be beyond the leg's reach (a first touch then a strike on the move).
    released = g.played if g.played != busy else None
    if released is not None:
        g.feet.pop(released, None)
    g.played = busy
    lunge = g.lift < -LOW_M * k  # the support foot stays down under a lunge, whatever the pose
    # While a foot or thigh plays the ball, the other foot is the support: it stands, and steps after
    # the body, instead of following the stride into the air. A kick or a thigh needs it. A soft touch
    # with the foot on the move (STRIDE_FROM_MPS or faster) is taken in stride: the other foot keeps
    # running (*design*: a support foot left standing for the touch's 0.76 s while the body ran on at
    # 3.5 m/s drew him skating stiff-legged through a first touch, seed 8080 frames 1866 to 1876).
    # Out of a touch or a lunge the feet go back to the stride once no foot is in the middle of a
    # step: a stepping foot handed to the stride would be dropped where the stride has it.
    stepping_now = any(f.get("swing") is not None for f in g.feet.values())
    in_stride = soft and g.speed >= STRIDE_FROM_MPS
    support = lunge or (busy is not None and not in_stride) or (g.supporting and stepping_now)
    g.supporting = support
    striding = False
    if (g.action not in PLANT_ACTIONS and not support) or g.lift > 0.02:
        g.feet = {}
    elif g.action != "stand" and g.speed >= STRIDE_FROM_MPS and not support:
        g.bob_at = _stride_feet(g, x, y, k, pel)
        striding = True
    else:
        for side, sign in (("l", 1.0), ("r", -1.0)):
            hx_, hy_ = _home(x, y, pel, k, sign)
            foot = g.feet.get(side)
            if foot is not None and foot.get("air"):
                # Out of a stride in the air: it comes down as a step from where it is.
                frames = _step_frames(math.hypot(foot["x"] - hx_, foot["y"] - hy_), g.speed)
                foot = {"x": foot["x"], "y": foot["y"], "yaw": foot["yaw"], "z": foot["z"], "w": 1.0,
                        "swing": (foot["x"], foot["y"], foot["yaw"], 0, frames, foot["z"]), "over": False}
            elif foot is not None and foot.get("swing") == "stride":
                foot["swing"] = None
            if foot is None:
                # A foot coming out of a stride or a touch starts where it was drawn last: on the
                # grass it stays there, and in the air it comes down as a step to where it stands.
                # Out of the stride the leg takes the plant over PLANT_EASE_FRAMES; a foot the touch
                # has just let go is drawn there already, and the leg keeps it.
                fx, fy, fz = g.ankle.get(side, (hx_, hy_, 0.0))
                taken = 1.0 if side == released else 0.0
                foot = {"x": fx, "y": fy, "yaw": pel, "z": fz, "swing": None, "w": taken}
                if fz > 0.02:
                    frames = _step_frames(math.hypot(fx - hx_, fy - hy_), g.speed)
                    foot["swing"], foot["over"] = (fx, fy, pel, 0, frames, fz), False
            foot["w"] = min(1.0, foot.get("w", 1.0) + 1.0 / PLANT_EASE_FRAMES)
            if foot["swing"] is not None:
                sx, sy, syaw, age, steps, *rest = foot["swing"]
                z0 = rest[0] if rest else 0.0
                age += 1
                # It travels while it is off the grass, and once over its spot comes straight down
                # there, however the hips go on turning.
                e = _ease((age / steps - 0.15) / 0.7)
                if not foot.get("over"):
                    foot["x"], foot["y"] = sx + (hx_ - sx) * e, sy + (hy_ - sy) * e
                    foot["yaw"] = syaw + _wrap(pel - syaw) * e
                    foot["over"] = e >= 1.0
                done = min(age / steps, 1.0)
                foot["z"] = z0 * max(0.0, 1.0 - age / LAND_FRAMES) + STEP_LIFT * k * math.sin(math.pi * done)
                foot["swing"] = None if age >= steps else (sx, sy, syaw, age, steps, z0)
                if foot["swing"] is None:
                    foot["z"], foot["over"] = 0.0, False
            g.feet[side] = foot
        # The foot playing the ball keeps its plant (where the touch blends from and back to) within
        # the leg's reach: the body goes on moving through a touch, and a plant left behind it is a
        # foot the leg can only dangle toward. It is drawn along at the edge of the reach.
        if busy is not None:
            foot = g.feet[busy]
            hx_, hy_ = _home(x, y, pel, k, 1.0 if busy == "l" else -1.0)
            gone = math.hypot(foot["x"] - hx_, foot["y"] - hy_)
            if foot["swing"] is None and gone > OUT_OF_REACH_M * k:
                f = OUT_OF_REACH_M * k / gone
                foot["x"], foot["y"] = hx_ + (foot["x"] - hx_) * f, hy_ + (foot["y"] - hy_) * f
        # A planted foot the body has left beyond the leg's reach steps at once, whatever the other
        # foot is doing: held there, the leg cannot reach it and is drawn through the grass.
        for side, sign in (("l", 1.0), ("r", -1.0)):
            foot = g.feet[side]
            hx_, hy_ = _home(x, y, pel, k, sign)
            gone = math.hypot(foot["x"] - hx_, foot["y"] - hy_)
            held = side == busy  # the touch's own, kept within reach above
            if foot["swing"] is None and not held and gone > OUT_OF_REACH_M * k:
                start = (foot["x"], foot["y"], foot["yaw"], 0, _step_frames(gone, g.speed))
                foot["swing"], foot["over"] = start, False
        # One foot steps at a time; the foot playing the ball is the touch's, not a step.
        stepping = any(f["swing"] is not None for s, f in g.feet.items() if s != busy)
        if not stepping:
            # Once the body has stopped turning he squares up: a foot half as far off steps too.
            settle = SETTLE if abs(g.lead) < 0.05 else 1.0
            worst = None
            for side, sign in (("l", 1.0), ("r", -1.0)):
                foot = g.feet[side]
                hx_, hy_ = _home(x, y, pel, k, sign)
                off = math.hypot(foot["x"] - hx_, foot["y"] - hy_)
                if side == busy:
                    continue  # the touching foot is the touch's (its plant is where its swing starts)
                if lunge and off < LOW_HOLD_M * k:
                    continue  # lowered, he keeps a foot down while the leg still reaches it
                err = max(
                    off / (STEP_DIST * k * settle),
                    abs(_wrap(foot["yaw"] - pel)) / (STEP_YAW * settle),
                )
                if err >= 1.0 and (worst is None or err > worst[0]):
                    worst = (err, side)
            if worst is not None:
                foot = g.feet[worst[1]]
                hx_, hy_ = _home(x, y, pel, k, 1.0 if worst[1] == "l" else -1.0)
                frames = _step_frames(math.hypot(foot["x"] - hx_, foot["y"] - hy_), g.speed)
                foot["swing"], foot["over"] = (foot["x"], foot["y"], foot["yaw"], 0, frames), False
    step = 1.0 / BOB_EASE_FRAMES
    g.bob_w = min(1.0, g.bob_w + step) if striding else max(0.0, g.bob_w - step)
    g.bob = round(g.bob_w * g.bob_at, 4)
    for foot in g.feet.values():
        if foot["swing"] is None:
            # The hips turn over a planted foot until the hip will turn no further; then it pivots.
            rel = _wrap(foot["yaw"] - pel)
            if abs(rel) > HIP_ROT:
                foot["yaw"] = pel + math.copysign(HIP_ROT, rel)
    for side in ("l", "r"):
        foot = g.feet.get(side)
        plant = None
        if foot is not None:
            plant = (round(foot["x"], 4), round(foot["y"], 4), round(foot["yaw"], 4), round(foot["z"], 4),
                     round(foot.get("w", 1.0), 4))
        down = foot is not None and foot["swing"] is None
        if side == "l":
            g.plant_l, g.down_l = plant, down
        else:
            g.plant_r, g.down_r = plant, down


def _swing_lift(speed: float) -> float:
    """How high a foot is carried at the top of its swing (asset metres, SWING_LIFT_M)."""
    return _table(SWING_LIFT_M, speed)


def _bob(speed: float, ph: float, half: float, stride: float, flight: tuple[float, float] | None) -> float:
    """How far the stride has the hips above (+) or below (-) where they stand, in metres, at phase
    `ph`, with each foot's stance `half` either side of its STANCE_CENTRE (WALK_BOB, RUN_BOB).

    Walking, the body vaults over the leg (highest at mid-stance, where the leg is straight under
    the hips, so no higher than standing) and is lowest midway between the stances. Running, it is
    at standing height as a foot lands and leaves and lowest at mid-stance; with both feet off the
    grass (`flight`: seconds since the last foot left it, seconds until the next lands) it falls
    freely, up and back down. The free fall is physics; the walk's cosine and the stance's
    quarter cosine are design (smooth, at the sourced heights and times)."""
    off = min(abs(_wrap(ph - c)) for c in STANCE_CENTRE.values())  # 0 at mid-stance, pi/2 midway
    walk = -_table(WALK_BOB, speed) * (1.0 - math.cos(2.0 * off)) / 2.0
    # The rise of a flight as long as the stride's (between its stances) is the part of the bob the
    # stance does not take.
    flight_s = max(math.pi - 2.0 * half, 0.0) / math.pi * stride / (2.0 * speed)
    dip = max(_table(RUN_BOB, speed) - GRAVITY * flight_s * flight_s / 8.0, 0.0)
    run = -dip * math.cos(0.5 * math.pi * off / half) if off < half else 0.0
    if flight is not None:
        run += GRAVITY * flight[0] * flight[1] / 2.0
    r = _running(speed)
    return walk * (1.0 - r) + run * r


def _stride_feet(g: Gait, x: float, y: float, k: float, pel: float) -> float:
    """Walking and running, each foot is on the grass for its stance and carried through the air for
    its swing, every frame at a place, never a pose: the gait's two stored poses swing a foot back
    and forth along one path, so a foot left to them drags along the grass (lesson 157).

    The stride's phase says when a foot lands and lifts: a stance centred on STANCE_CENTRE, the duty
    share of the stride (_duty) but no longer than the leg reaches under the hips, from
    PLANT_AHEAD_MAX ahead to STANCE_BEHIND_MAX behind. On the grass the foot stays where it landed,
    and lifts once its stance is over or the hips have gone on past where the leg reaches it. In
    the air it keeps its own count of how far through the swing it is, advanced by the stride's
    phase over the swing's share of it, and lands when the count is done: a change of speed changes
    how fast the count runs and where the foot will land, never where the foot is now (a swing read
    straight off the phase jumped when the stance's share changed under it). It is carried
    from where it lifted to where the body will be when it lands, that much ahead of the hips, on an
    arc up to _swing_lift. Returns the stride's bob (_bob) for this frame."""
    stride = _stride(g.speed)
    reach = (PLANT_AHEAD_MAX + STANCE_BEHIND_MAX) * k
    half = min(_duty(g.speed) * math.pi, math.pi * reach / stride)
    travel = stride * half / math.pi  # how far the body moves over one stance
    ahead = min(travel / 2, PLANT_AHEAD_MAX * k)
    air = 2 * math.pi - 2 * half  # the swing's share of the stride, in phase
    ph = g.phase % (2 * math.pi)
    hx, hy = math.cos(g.heading), math.sin(g.heading)
    lx, ly = -hy, hx
    lift = _swing_lift(g.speed) * k
    run = _running(g.speed)  # how much of a run's timing a swing taken now has, for all of it
    per_frame = 2 * math.pi * g.speed * FRAME_S / stride  # the phase's advance in a frame

    def rel(fx: float, fy: float) -> tuple[float, float]:  # forward and to the left of him
        return (fx - x) * hx + (fy - y) * hy, (fx - x) * lx + (fy - y) * ly

    def lift_off(foot: dict, e: float) -> dict:
        # It left the grass between the last frame and this one, so it is drawn a frame into its
        # swing (p0): drawn where it lifted, a sprinter's foot hung a frame on the grass beyond the
        # leg's reach, and both feet were seen off the grass together in one frame only.
        start = (foot["x"], foot["y"], foot["yaw"], foot.get("z", 0.0))
        p0 = e - per_frame / air if air > 0.0 else e
        return {**foot, "air": True, "e": e, "e0": e, "p0": p0, "ph": ph, "from": start, "run": run}

    for side, sign in (("l", 1.0), ("r", -1.0)):
        off = _wrap(ph - STANCE_CENTRE[side])
        lat = RUN_HALF_WIDTH_M * k * sign
        foot = g.feet.get(side)
        if foot is not None and isinstance(foot.get("swing"), tuple):
            # In the middle of a step from standing: it carries on as a swing from where it is, landing
            # within LAND_FRAMES if its stance has already begun.
            if abs(off) < half:
                e = 1.0 - LAND_FRAMES * per_frame / air
            else:
                e = ((off - half) % (2 * math.pi)) / air
            step = {"x": foot["x"], "y": foot["y"], "yaw": foot["yaw"], "z": foot["z"]}
            foot = lift_off(step, min(max(e, 0.0), 0.95))
        if foot is None:
            if abs(off) < half:
                # Starting the stride on this foot: it is where the stance has it by now.
                r = ahead - travel * (off + half) / (2 * half)
                foot = {"x": x + hx * r + lx * lat, "y": y + hy * r + ly * lat, "yaw": pel, "z": 0.0,
                        "swing": None, "w": 1.0}
                g.feet[side] = foot
                continue
            # A foot with no place yet is where its swing has it by now: it lifted behind the
            # hips, where the body was when the swing began.
            e = ((off - half) % (2 * math.pi)) / air
            back = ahead - travel - stride * e * air / (2 * math.pi)
            foot = lift_off({"x": x + hx * back + lx * lat, "y": y + hy * back + ly * lat, "yaw": pel,
                             "z": 0.0}, 0.0)
            foot["e"] = e
        if not foot.get("air"):
            f, _ = rel(foot["x"], foot["y"])
            past = half <= off and off < half + air  # its stance is over
            other = g.feet.get("r" if side == "l" else "l")
            other_down = other is None or not other.get("air")
            # The other foot is down, or past the middle of its swing and coming down: in a run it is
            # about two thirds through as this one lifts. Setting off, a foot lifting on its phase
            # while the other had only just left the grass sent both up together, a hop.
            other_landing = other_down or (other["e"] - other["e0"]) / max(1.0 - other["e0"], 1e-6) >= 0.5
            # Beyond the leg's reach it lifts early, but only while the other foot is on the grass:
            # setting off from standing, both feet were behind the reach at once and lifted together.
            beyond = f < -STANCE_BEHIND_MAX * k  # held longer, the leg would drag it
            if (past and (other_landing or beyond)) or (beyond and other_down):
                # Its count starts where the stride's phase has it, before zero when the leg's reach
                # lifts it early, so it lands when its stance comes round again and the two feet stay
                # half a stride apart (counted from zero, an early lift landed late: both feet were
                # high at once, a hop).
                e = (off - half) / air if past else -((half - off) % (2 * math.pi)) / air
                if e <= LATE_LIFT:
                    foot = lift_off(foot, e)
            if not foot.get("air"):
                foot["swing"], foot["w"] = None, 1.0
                g.feet[side] = foot
                continue
        else:
            foot["e"] += ((ph - foot["ph"]) % (2 * math.pi)) / air
            foot["ph"] = ph
        e = min(foot["e"], 1.0)  # on the frame the swing is done the foot is where it ends: on the grass
        sx, sy, syaw, sz = foot["from"]
        p0 = foot["p0"]
        p = min(max((e - p0) / max(1.0 - p0, 1e-6), 0.0), 1.0)
        # Where the body will be when this foot lands, and that far ahead of the hips: from its count
        # unclamped, so on the frame it lands past its count the plant stays where it was going.
        on = stride * (1.0 - foot["e"]) * air / (2 * math.pi) + ahead
        tx, ty = x + hx * on + lx * lat, y + hy * on + ly * lat
        # A swing's timing follows his pace no faster than RUN_MIX_RATE a frame, so it never jumps.
        foot["run"] = r = foot["run"] + min(max(run - foot["run"], -RUN_MIX_RATE), RUN_MIX_RATE)
        ee = _ease(p)
        wx, wy = sx + (tx - sx) * ee, sy + (ty - sy) * ee
        # How high: up to _swing_lift, highest midway walking and early running (RUN_SWING_PEAK), so
        # a running foot comes through low to land and is down before the other is high.
        if p <= RUN_SWING_PEAK:
            up_run = math.sin(0.5 * math.pi * p / RUN_SWING_PEAK)
        else:
            up_run = math.cos(0.5 * math.pi * (p - RUN_SWING_PEAK) / (1.0 - RUN_SWING_PEAK)) ** 2
        up = math.sin(math.pi * p) * (1.0 - r) + up_run * r
        wz = sz * (1.0 - p) + lift * up
        # Running, off the grass it is no further behind the hips than the leg reaches
        # (STANCE_BEHIND_MAX): the hips going away from it, left there, the leg search folded the knee
        # to come near it, the heel up at the seat. Only as it leaves the grass (by STEP_LIFT up), so a
        # foot still down is never dragged; walking, the hips do not outrun it.
        f, _ = rel(wx, wy)
        if f < -STANCE_BEHIND_MAX * k:
            d = (-STANCE_BEHIND_MAX * k - f) * r * min(max(wz - sz * (1.0 - p), 0.0) / (STEP_LIFT * k), 1.0)
            wx, wy = wx + hx * d, wy + hy * d
        foot["x"], foot["y"] = wx, wy
        foot["yaw"] = syaw + _wrap(pel - syaw) * ee
        foot["z"] = wz
        foot["swing"], foot["w"] = "stride", 1.0
        if e >= 1.0:
            foot = {"x": wx, "y": wy, "yaw": foot["yaw"], "z": 0.0, "swing": None, "w": 1.0}
        g.feet[side] = foot
    # In the air the body is in free fall from the frame both feet are off the grass (a swing's first
    # frame still has its foot on it) to the frame the swinging foot's count lands it.
    up = [f for f in g.feet.values() if f.get("air") and f["z"] > 0.0]
    flight = None
    if len(up) == 2 and per_frame > 0.0:
        left = min(max(1.0 - f["e"], 0.0) for f in up) * air / per_frame * FRAME_S
        flight = (g.flight_s, left)
        g.flight_s += FRAME_S
    else:
        g.flight_s = 0.0
    return _bob(g.speed, ph, half, stride, flight)


def _reach_leg(hip, knee, ankle, toe, touch: dict, fwd: tuple[float, float], k: float):
    """The touching leg's capsules, eased from the stride toward the ball by the touch's weight.

    A foot reaches with its sole (the mesh's foot marker) and its knee folds forward, both thigh
    and shin 0.42 m in the asset's own metres; a thigh reaches with its knee and the shin hangs from it.
    """
    w = touch["w"]
    tx, ty, tz = touch["at"]
    seg = 0.42 * k
    if touch["part"] == "thigh":
        k2 = [tx, ty, max(tz, 0.3 * k)]
        a2 = [tx - fwd[0] * 0.05 * k, ty - fwd[1] * 0.05 * k, max(k2[2] - 0.40 * k, 0.06 * k)]
        t2 = [a2[0] + fwd[0] * 0.10 * k, a2[1] + fwd[1] * 0.10 * k, max(a2[2] - 0.04 * k, 0.04 * k)]
    else:
        a2 = [tx - fwd[0] * 0.08 * k, ty - fwd[1] * 0.08 * k, max(tz + 0.03 * k, 0.06 * k)]
        vx, vy, vz = a2[0] - hip[0], a2[1] - hip[1], a2[2] - hip[2]
        d = math.sqrt(vx * vx + vy * vy + vz * vz) or 1.0
        if d > 2 * seg:  # out of reach: the leg straight toward it
            a2 = [hip[0] + vx * 2 * seg / d, hip[1] + vy * 2 * seg / d, hip[2] + vz * 2 * seg / d]
            vx, vy, vz, d = a2[0] - hip[0], a2[1] - hip[1], a2[2] - hip[2], 2 * seg
        ux, uy, uz = vx / d, vy / d, vz / d
        dot = fwd[0] * ux + fwd[1] * uy
        nx, ny, nz = fwd[0] - dot * ux, fwd[1] - dot * uy, -dot * uz
        nn = math.sqrt(nx * nx + ny * ny + nz * nz)
        if nn < 1e-6:
            nx, ny, nz, nn = 0.0, 0.0, 1.0, 1.0
        bend = math.sqrt(max(seg * seg - (d / 2) ** 2, 0.0))
        k2 = [
            hip[0] + vx / 2 + nx / nn * bend,
            hip[1] + vy / 2 + ny / nn * bend,
            hip[2] + vz / 2 + nz / nn * bend,
        ]
        t2 = [a2[0] + fwd[0] * 0.13 * k, a2[1] + fwd[1] * 0.13 * k, max(a2[2] - 0.03 * k, 0.04 * k)]

    def mix(p, q):
        return [round(p[i] + (q[i] - p[i]) * w, 4) for i in range(3)]

    return mix(knee, k2), mix(ankle, a2), mix(toe, t2)


def mesh_pose(g: Gait, x: float, y: float, reach: float) -> dict:
    """What the page needs to pose the mesh this frame (render.js anglesFor, meshpose.pose_angles)."""
    return {
        "action": g.action,
        "phase": round(g.phase, 4),
        "speed": round(g.speed, 3),
        "reach": reach,
        "dive": round(g.dive, 3),
        "dive_up": round(g.dive_up, 3),
        "plant_l": [round(v, 4) for v in g.plant_l] if g.plant_l else None,
        "plant_r": [round(v, 4) for v in g.plant_r] if g.plant_r else None,
        "lead": round(g.lead, 4),
        "lift": round(g.lift, 4),
        "bob": round(g.bob, 4),
        "lean": round(g.lean, 4),
        "roll": round(g.roll, 4),
        "pump": round(_pump(g.speed), 4),
        "touch": g.touch,
        "hold": g.hold,
        "x": round(x, 4),
        "y": round(y, 4),
        "fall": round(g.fall, 4),
        "fall_dir": round(g.fall_dir, 4),
        "signal": g.signal,
        "brace": g.brace,
        "crouch": g.crouch,
        "tip_ahead": g.tip_ahead,
        "look": g.look,
    }


def body_parts(
    x: float, y: float, look: Look, g: Gait, ball: tuple[float, ...] | None = None
) -> list[dict]:
    """Capsules (a, b, r) and spheres (a only) in world metres, tagged with a colour slot.

    The heading, speed and action come from the engine. The stride phase is how far these
    feet have already travelled, so a run cycles instead of sliding.
    """
    k = look.height_m / ASSET_STATURE_M
    w = look.build
    hx, hy = math.cos(g.heading), math.sin(g.heading)  # forward
    lx, ly = -hy, hx  # left
    speed_n = min(g.speed / 7.0, 1.0)
    # Under 4 m/s the engine calls it a walk. On the pitch that speed is a press, and it has to look like one.
    pressing = g.action == "run" or (g.action not in ("dive", "throw") and g.speed >= 2.2)
    step = _step_m(g.speed)
    if g.action == "throw":
        amp = 0.0
    elif g.action == "dive":
        amp = speed_n * 0.16 * k
    elif g.speed > 0.45:
        amp = min(step * 0.50, 0.62) * k
    else:
        amp = 0.0
    s = math.sin(g.phase)
    dive = 0.0  # a dive is the body tipped over his feet (dive_pose), not bent
    lean = (0.16 if pressing else 0.05) * min(g.speed / 5.0, 1.0) * k
    if g.action in PLANT_ACTIONS and g.action not in ("chest", "head", "hands", "throw"):
        lean += math.sin(g.lean) * TRUNK_M * k  # the trunk tipped at the hips (pace)
    # Across, into a turn (pace), in the poses the mesh tips it in (meshpose._upper): not one of its
    # own whole-body contact poses.
    roll_m = 0.0 if g.action in ROLL_FREE else math.sin(g.roll) * TRUNK_M * k
    if g.action == "chest":
        lean = -0.14 * k  # the chest opens onto a ball he is under
    elif g.action == "head":
        lean = 0.12 * k
    _feet(g, x, y, k)
    touch = g.touch if g.touch is not None and g.touch["w"] > 0 else None
    hold = g.hold if g.hold is not None and g.hold["w"] > 0 else None
    lift = g.lift + g.bob
    # Away from the gait the arms are labelled where the mesh draws them: balancing a kick, spread
    # for a chest control, reaching for a held ball (meshpose.arm_points). The gait's own capsule
    # arms stay: standing they fill the engine's body outline (P11).
    mesh_arms = None
    if hold is not None or touch is not None or g.action in MESH_ARM_ACTIONS or g.brace is not None:
        mesh_arms = arm_points(mesh_pose(g, x, y, 0.0), g.heading, look.height_m)

    def at(f: float, side: float, z: float) -> list[float]:
        # A dive reaches sideways and folds the body down. The feet stay on the grass.
        if dive and z > 0.35:
            side += dive * (0.25 + 0.7 * min(z / 1.5, 1.0)) * k
            z -= abs(dive) * 0.42 * k * min((z - 0.35) / 1.2, 1.0)
        if roll_m:
            # Tipped from the hips up in proportion to height, the head (above the TRUNK_M of hips
            # to shoulders) a little further: the label goes with the drawn trunk.
            side += roll_m * min(max((z - HIP_PIVOT_Z * k) / (TRUNK_M * k), 0.0), ROLL_HEAD)
        return [
            round(x + hx * f + lx * side, 4), round(y + hy * f + ly * side, 4), round(max(z + lift, 0.02), 4)
        ]

    def toward(of: float, os: float, oz: float, max_m: float) -> tuple[float, float, float]:
        """Body-frame point pulled toward the ball, and no further than the joint can reach."""
        if ball is None:
            return of, os, oz
        bz = ball[2] + BALL_RADIUS if len(ball) > 2 else 0.22
        tf = (ball[0] - x) * hx + (ball[1] - y) * hy
        ts = (ball[0] - x) * lx + (ball[1] - y) * ly
        vf, vs, vz = tf - of, ts - os, bz - oz
        dist = math.sqrt(vf * vf + vs * vs + vz * vz) or 1.0
        scale = min(1.0, max_m / dist)
        return of + vf * scale, os + vs * scale, max(oz + vz * scale, 0.02)

    strided = {side: gait_foot(_gait_pose(g, x, y), g.heading, look.height_m, side, with_height=True)
               for side in ("l", "r")}
    # Capsule radii are given for a player of REF_STATURE_M and grow with his stature; where they
    # sit comes from the asset (k), so the label stays the shape P11 measured.
    kr = look.height_m / REF_STATURE_M
    sleeve_r = 0.06 * kr
    arm_r = 0.048 * kr
    # The outer edge of the sleeves is the shoulder breadth over the deltoids (shape.py, P11).
    shoulder_y = shape.SHOULDER_BREADTH_M / 2 - sleeve_r
    parts = []
    played: dict[str, tuple[float, float, float]] = {}  # the sole a touch draws, side -> (x, y, height)
    for side, sign in (("l", 1.0), ("r", -1.0)):
        # The same stride as the mesh's (meshpose.gait): at sin(phase) = 1 the right foot is forward.
        swing = -amp * s * sign
        # The hips lead the chest in a turn (g.lead), so the hip joints sit turned by it.
        hip = at(-0.10 * k * sign * math.sin(g.lead), 0.10 * k * sign * math.cos(g.lead), 0.92 * k)
        plant = g.plant_l if sign > 0 else g.plant_r
        # Off the grass the leg is where the mesh's stride has it (meshpose.gait_foot): the knee
        # ahead of the line from hip to ankle, as a knee bends.
        gx, gy, gz = strided[side]
        ankle = [round(gx - hx * ANKLE_BACK * k, 4), round(gy - hy * ANKLE_BACK * k, 4),
                 round(0.08 * k + gz, 4)]
        toe = [round(gx + hx * 0.02 * k, 4), round(gy + hy * 0.02 * k, 4), round(0.05 * k + gz, 4)]
        knee = [
            round((hip[0] + ankle[0]) / 2 + hx * 0.10 * k, 4),
            round((hip[1] + ankle[1]) / 2 + hy * 0.10 * k, 4),
            round((hip[2] + ankle[2]) / 2 + 0.03 * k, 4),
        ]
        if plant is not None:
            # A foot on the grass stays where it landed, pointing the way it landed; the body moves
            # and turns over it. A stepping foot is lifted off the grass on its way. A stride's
            # plant is taken and given back over a few frames (its weight).
            fx, fy = math.cos(plant[2]), math.sin(plant[2])
            az = 0.08 * k + plant[3]
            ax, ay = plant[0] - fx * ANKLE_BACK * k, plant[1] - fy * ANKLE_BACK * k
            pk = [
                round((hip[0] + ax) / 2 + hx * 0.04 * k, 4),
                round((hip[1] + ay) / 2 + hy * 0.04 * k, 4),
                round((hip[2] + az) / 2 + 0.05 * k, 4),
            ]
            pa = [round(ax, 4), round(ay, 4), round(az, 4)]
            pt = [round(ax + fx * 0.13 * k, 4), round(ay + fy * 0.13 * k, 4), round(0.05 * k + plant[3], 4)]
            pw = plant[4] if len(plant) > 4 else 1.0
            knee, ankle, toe = ([round(a[i] + (b[i] - a[i]) * pw, 4) for i in range(3)]
                                for a, b in ((knee, pk), (ankle, pa), (toe, pt)))
        if touch is not None and touch["part"] in ("foot", "strike", "thigh") and touch["side"] == side:
            knee, ankle, toe = _reach_leg(hip, knee, ankle, toe, touch, (hx, hy), k)
            played[side] = (ankle[0] + hx * ANKLE_BACK * k, ankle[1] + hy * ANKLE_BACK * k,
                            max(ankle[2] - 0.08 * k, 0.0))
        # At the hips the thigh is no deeper than the engine's body (P11), however big the player.
        thigh_r = min(0.085 * kr * w, shape.CHEST_DEPTH_M / 2)
        parts.append({"n": f"thigh_{side}", "a": hip, "b": knee, "r": round(thigh_r, 4), "c": "shorts"})
        shin_r = 0.058 * kr * w
        parts.append({"n": f"shin_{side}", "a": knee, "b": ankle, "r": round(shin_r, 4), "c": "socks"})
        parts.append({"n": f"boot_{side}", "a": ankle, "b": toe, "r": round(0.042 * kr, 4), "c": "boots"})
        # Opposite arm, elbow kept bent so a run pumps instead of hanging straight. Standing, the
        # sleeve hangs inside the deltoid and the hand inside the shoulder breadth (shape.py, P11).
        pump = -swing * (1.35 if pressing else 0.65)
        shoulder = at(lean, shoulder_y * sign, 1.40 * k)
        if mesh_arms is not None:
            shoulder, elbow, hand = (mesh_arms[f"{j}_{side}"] for j in ("shoulder", "elbow", "hand"))
        elif g.action == "dive":
            elbow = at(lean, 0.32 * k * w * sign, 1.20 * k)
            hand = at(lean + dive * 0.10 * k, 0.42 * k * w * sign, 1.15 * k)
        else:
            elbow = at(pump * 0.55 + lean, shoulder_y * sign, 1.16 * k)
            hand = at(pump * 0.12 + lean, (shoulder_y + sleeve_r - arm_r) * sign, 0.93 * k)
        parts.append({"n": f"arm_{side}", "a": shoulder, "b": elbow, "r": round(sleeve_r, 4), "c": "shirt"})
        parts.append({"n": f"forearm_{side}", "a": elbow, "b": hand, "r": round(arm_r, 4), "c": "skin"})
    # Where each foot is drawn now, for a step that starts from it (_feet): on the ball, on its
    # plant, or where the mesh's stride has it. The capsules' own stride is the label's, not the
    # picture's.
    for side in ("l", "r"):
        plant = g.plant_l if side == "l" else g.plant_r
        if side in played:
            g.ankle[side] = played[side]
        elif plant is not None and (len(plant) < 5 or plant[4] >= 0.5):
            g.ankle[side] = (plant[0], plant[1], plant[3])
        else:
            g.ankle[side] = strided[side]
    # The trunk: three capsules side by side, each as thick as the chest is deep, filling the width
    # up to the inside of the hanging arms, so at chest height, trunk and arms span the engine's
    # body (shape.py) across and front to back.
    half = shape.CHEST_DEPTH_M / 2
    arm_inner = shoulder_y + sleeve_r - 2 * arm_r
    trunk_y = max(0.0, arm_inner - half)
    for side, sign in (("l", 1.0), ("", 0.0), ("r", -1.0)):
        parts.append(
            {
                "n": f"torso_{side}" if side else "torso",
                "a": at(lean * 0.4, trunk_y * sign, 0.98 * k),
                "b": at(lean, trunk_y * sign, 1.36 * k),
                "r": round(half, 4),
                "c": "shirt",
            }
        )
    parts.append(
        {
            "n": "neck",
            "a": at(lean, 0.0, 1.44 * k),
            "b": at(lean * 1.1, 0.0, 1.52 * k),
            "r": round(0.048 * kr, 4),
            "c": "skin",
        }
    )
    if g.action == "head":
        hf, hs, hz = toward(lean, 0.0, HEAD_Z * k, 0.18 * k)
        head = at(hf, hs, hz)
    else:
        head = at(lean * 1.15, dive * 0.05 * k, HEAD_Z * k)
    parts.append({"n": "head", "a": head, "r": round(0.105 * kr, 4), "c": "skin"})
    parts.append(
        {
            "n": "hair",
            "a": [head[0] - hx * 0.02, head[1] - hy * 0.02, round(head[2] + 0.05 * k, 4)],
            "r": round(0.09 * kr, 4),
            "c": "hair",
        }
    )
    if touch is not None and touch["part"] in ("chest", "head"):
        _lean_to(parts, touch, head, (hx, hy), k, at(lean, 0.0, 1.28 * k))
    if hold is not None and hold["bend"] > 0:
        _bend_over(parts, hold["bend"] * hold["w"], at(0.0, 0.0, HIP_PIVOT_Z * k), (hx, hy))
    if g.fall:
        # A fouled player down: the whole body tipped over his feet, as the page tips the mesh.
        for part in parts:
            for key in ("a", "b"):
                if key in part:
                    part[key] = [round(v, 4) for v in tip(part[key], x, y, g.fall, g.fall_dir, g.tip_ahead)]
    return parts


def _bend_over(parts: list[dict], angle: float, pivot: list[float], fwd: tuple[float, float]) -> None:
    """Turn the trunk, neck and head forward about the hips, as the mesh's spine bends over a held
    ball (meshpose.HOLD_BEND); the arms are the mesh's already."""
    c, s = math.cos(angle), math.sin(angle)

    def turn(p: list[float]) -> list[float]:
        f = (p[0] - pivot[0]) * fwd[0] + (p[1] - pivot[1]) * fwd[1]
        z = p[2] - pivot[2]
        f2, z2 = f * c + z * s, z * c - f * s
        return [round(p[0] + fwd[0] * (f2 - f), 4), round(p[1] + fwd[1] * (f2 - f), 4),
                round(max(pivot[2] + z2, 0.02), 4)]

    for part in parts:
        if part["n"] in ("torso", "torso_l", "torso_r", "neck", "head", "hair"):
            part["a"] = turn(part["a"])
            if "b" in part:
                part["b"] = turn(part["b"])


def _lean_to(parts: list[dict], touch: dict, head: list[float], fwd: tuple[float, float], k: float,
             chest: list[float]) -> None:
    """Lean the upper body so the chest or the brow meets the ball, eased by the touch's weight."""
    if touch["part"] == "head":
        point = [head[0] + fwd[0] * 0.12 * k, head[1] + fwd[1] * 0.12 * k, head[2] + 0.06 * k]
        moved = {"head": (1.0, 1.0), "hair": (1.0, 1.0), "neck": (0.5, 1.0)}
    else:
        point = [chest[0] + fwd[0] * 0.14 * k, chest[1] + fwd[1] * 0.14 * k, chest[2]]
        moved = {"head": (1.0, 1.0), "hair": (1.0, 1.0), "neck": (1.0, 1.0),
                 "torso": (0.0, 1.0), "torso_l": (0.0, 1.0), "torso_r": (0.0, 1.0),
                 "arm_l": (1.0, 1.0), "arm_r": (1.0, 1.0), "forearm_l": (1.0, 1.0), "forearm_r": (1.0, 1.0)}
    d = [(touch["at"][i] - point[i]) * touch["w"] for i in range(3)]
    n = math.sqrt(sum(v * v for v in d))
    cap = 0.35 * k
    if n > cap:
        d = [v * cap / n for v in d]
    for part in parts:
        if part["n"] not in moved:
            continue
        sa, sb = moved[part["n"]]
        part["a"] = [round(part["a"][i] + d[i] * sa, 4) for i in range(3)]
        if "b" in part:
            part["b"] = [round(part["b"][i] + d[i] * sb, 4) for i in range(3)]


def parts_box(cam: Camera, parts: list[dict]) -> tuple[float, float, float, float] | None:
    """Analytic image box of a set of capsules and spheres, unclipped. None if behind the camera."""
    xs, ys = [], []
    f = cam.focal_px
    for p in parts:
        for key in ("a", "b"):
            if key not in p:
                continue
            c = tuple(p[key])
            uv = cam.project(c)
            if uv is None:
                return None
            rpx = f * p["r"] / cam.depth(c)
            xs += [uv[0] - rpx, uv[0] + rpx]
            ys += [uv[1] - rpx, uv[1] + rpx]
    return (min(xs), min(ys), max(xs), max(ys))


def ball_parts(x: float, y: float, z: float, spin: tuple[float, float, float] | None = None) -> list[dict]:
    part = {
        "n": "ball",
        "a": [round(x, 4), round(y, 4), round(z + BALL_RADIUS, 4)],
        "r": BALL_RADIUS,
        "c": "ball",
    }
    if spin is not None:
        part["spin"] = [round(spin[0], 4), round(spin[1], 4), round(spin[2], 4)]
    return [part]


def drawn_ball(frame: dict, carrier_heading: float | None = None) -> tuple[float, float, float]:
    """Where the ball is drawn: where the engine has it. A carrier's ball is already against his
    body on the side he faces (engine.py, tick_carrier), so it is drawn there, not moved."""
    b = frame["ball"]
    return (b["x"], b["y"], b["z"])


# ---- pitch keypoints ----------------------------------------------------------------------


def _keypoints() -> list[tuple[str, float, float]]:
    L, W, cy = 105.0, 68.0, 34.0
    pts = [
        ("corner_nl", 0, 0),
        ("corner_fl", 0, W),
        ("corner_nr", L, 0),
        ("corner_fr", L, W),
        ("half_near", L / 2, 0),
        ("half_far", L / 2, W),
        ("centre", L / 2, cy),
        ("circle_near", L / 2, cy - 9.15),
        ("circle_far", L / 2, cy + 9.15),
        ("circle_left", L / 2 - 9.15, cy),
        ("circle_right", L / 2 + 9.15, cy),
    ]
    for side, gx, s in (("l", 0.0, 1), ("r", L, -1)):
        pts += [
            (f"box_{side}_goal_near", gx, cy - 20.16),
            (f"box_{side}_goal_far", gx, cy + 20.16),
            (f"box_{side}_edge_near", gx + s * 16.5, cy - 20.16),
            (f"box_{side}_edge_far", gx + s * 16.5, cy + 20.16),
            (f"six_{side}_goal_near", gx, cy - 9.16),
            (f"six_{side}_goal_far", gx, cy + 9.16),
            (f"six_{side}_edge_near", gx + s * 5.5, cy - 9.16),
            (f"six_{side}_edge_far", gx + s * 5.5, cy + 9.16),
            (f"spot_{side}", gx + s * 11.0, cy),
            (f"post_{side}_near", gx, cy - 3.66),
            (f"post_{side}_far", gx, cy + 3.66),
        ]
        # where the penalty arc meets the box edge
        dy = math.sqrt(9.15**2 - 5.5**2)
        pts += [(f"arc_{side}_near", gx + s * 16.5, cy - dy), (f"arc_{side}_far", gx + s * 16.5, cy + dy)]
    return pts


KEYPOINTS = _keypoints()


def project_keypoints(cam: Camera) -> list[dict]:
    """Keypoints that fall inside the image, with exact pixel positions (visibility set later)."""
    out = []
    for name, x, y in KEYPOINTS:
        uv = cam.project((x, y, 0.0))
        if uv is None or not (0 <= uv[0] < cam.width and 0 <= uv[1] < cam.height):
            continue
        out.append({"name": name, "px": round(uv[0], 3), "py": round(uv[1], 3)})
    return out


# ---- clip window --------------------------------------------------------------------------


def crowding(frame: dict, radius: float = 4.0) -> int:
    bx, by = frame["ball"]["x"], frame["ball"]["y"]
    return sum(1 for p in frame["players"] if math.hypot(p["x"] - bx, p["y"] - by) <= radius)


# A player stands in for his drawn body: the torso capsule body_parts draws (radius 0.23 m at an
# average build) up to the mean height sample_looks draws (1.81 m). Only the window choice uses
# these; the labels still come from the drawn capsules and the pixels.
OCCLUDER_RADIUS_M = 0.23
OCCLUDER_HEIGHT_M = 1.81


def ball_hidden(cam_pos: tuple[float, float, float], ball: tuple[float, float, float], players) -> bool:
    """True if a player stands on the camera's line of sight to the ball's centre.

    The sight line is a segment from the lens to the ball. A player blocks it when he stands
    between the two in the pitch plane, within OCCLUDER_RADIUS_M of it, and the line passes
    him below OCCLUDER_HEIGHT_M. A player beside or behind the ball, or under a ball in the
    air, does not hide it, however close he is.
    """
    cx, cy, cz = cam_pos
    bx, by, bz = ball[0], ball[1], ball[2] + BALL_RADIUS
    dx, dy = bx - cx, by - cy
    reach2 = dx * dx + dy * dy
    if reach2 == 0:
        return False
    reach = math.sqrt(reach2)
    for px, py in players:
        ox, oy = px - cx, py - cy
        along = (ox * dx + oy * dy) / reach2  # 0 at the lens, 1 at the ball
        if not 0 < along < 1:
            continue
        if abs(ox * dy - oy * dx) / reach > OCCLUDER_RADIUS_M:
            continue
        if cz + along * (bz - cz) <= OCCLUDER_HEIGHT_M:
            return True
    return False


def ball_live(prev: dict | None, frame: dict, pitch_x: float = 105.0, pitch_y: float = 68.0) -> bool:
    """The ball is on the pitch and in play: someone has it, or it moved since the last frame.

    A still ball nobody has is a dead ball waiting for a restart (Law 9: out of play after it
    crosses a line or the referee stops play), and a ball off the pitch is not in play either.
    A player standing beside a dead ball for the whole restart wait is not footage of a player
    hiding the ball in play: on seed 7004 that wait filled a crowded window (250 frames counted
    hidden, none hidden in the render).
    """
    b = frame["ball"]
    if not (0.0 <= b["x"] <= pitch_x and 0.0 <= b["y"] <= pitch_y):
        return False
    if frame.get("possessor") is not None or prev is None:
        return True
    a = prev["ball"]
    return (a["x"], a["y"], a["z"]) != (b["x"], b["y"], b["z"])


def crowded_start(
    frames: list[dict],
    n: int,
    earliest: int,
    latest: int,
    cam_positions: list[tuple[float, float, float]],
    step: int = 25,
) -> int:
    """Start frame of the n-frame window where the ball, in play, is most often behind a player.

    cam_positions[i] is where the broadcast lens stood at frame i. Occlusion is a matter of
    where players stand on the line from that lens to the ball, not of how many are near it:
    a crowd on the far side of the ball hides nothing. Players near the ball break ties.
    """
    hidden = [0] * (len(frames) + 1)  # prefix sums of hidden frames
    for i, f in enumerate(frames[: len(cam_positions)]):
        b = f["ball"]
        players = [(p["x"], p["y"]) for p in f["players"]]
        live = ball_live(frames[i - 1] if i else None, f)
        blocked = live and ball_hidden(cam_positions[i], (b["x"], b["y"], b["z"]), players)
        hidden[i + 1] = hidden[i] + blocked
    best, best_score = earliest, (-1, -1.0)
    for s in range(earliest, max(earliest, latest) + 1, step):
        if s + n > len(cam_positions):
            break
        window = frames[s : s + n : 5]
        score = (hidden[s + n] - hidden[s], sum(crowding(f) for f in window) / len(window))
        if score > best_score:
            best, best_score = s, score
    return best


# A goalkeeper's own touches and his dive: the actions the engine names when he handles the ball
# or throws himself at it (ninety/sim). Arms over the ball are what hides it from the lens.
KEEPER_ACTIONS = ("hands", "dive", "throw", "bowl")
# The penalty area, 16.5 m from the goal line and 40.32 m wide (Law 1): where a keeper handles.
PENALTY_DEPTH_M = 16.5
PENALTY_HALF_WIDTH_M = 20.16


def keeper_busy(frame: dict) -> bool:
    return any(p.get("role") == "GK" and p.get("action") in KEEPER_ACTIONS for p in frame["players"])


def in_penalty_area(ball: dict, pitch_x: float = 105.0, pitch_y: float = 68.0) -> bool:
    near_goal = ball["x"] <= PENALTY_DEPTH_M or ball["x"] >= pitch_x - PENALTY_DEPTH_M
    return near_goal and abs(ball["y"] - pitch_y / 2) <= PENALTY_HALF_WIDTH_M


def keeper_start(frames: list[dict], n: int, earliest: int, latest: int, step: int = 25) -> int:
    """Start frame of the n-frame window where a goalkeeper most often handles or dives.

    A keeper's catch, parry or dive puts his arms and body over the ball, the situation `crowded`
    does not aim at: it ranks windows by outfield players on the sight line. Frames with the
    ball in a penalty area break ties, so a match with no keeper action still gets a goalmouth.
    """
    busy = [0] * (len(frames) + 1)
    box = [0] * (len(frames) + 1)
    for i, f in enumerate(frames):
        busy[i + 1] = busy[i] + keeper_busy(f)
        box[i + 1] = box[i] + in_penalty_area(f["ball"])
    best, best_score = earliest, (-1, -1)
    for s in range(earliest, max(earliest, latest) + 1, step):
        if s + n > len(frames):
            break
        score = (busy[s + n] - busy[s], box[s + n] - box[s])
        if score > best_score:
            best, best_score = s, score
    return best
