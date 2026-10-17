"""The first touch: one rule for the engine's touch and the passer's estimate of it (A4).

A player who has reacted to the ball and reaches it cushions it: the surface he meets it with
(by the ball's height: foot, thigh, chest or head) takes out up to what it can kill of the ball's
speed relative to him (A4: `Profile.absorb_mps` for a foot, CUSHION of that for the others), and he
sends what is left toward where he chose, with his own error, wider on a surface he aims less well
with (AIM_ERROR). What is left decides the rest, never a roll: a ball slow enough for him to
keep up with stays at his feet; anything more is a heavy touch, free until he is back on it after
TOUCH_GAP_S, like a dribbling touch (D6), and whoever reaches it first has it. A ball far too fast
for him to steer beats the surface and rebounds, as a ball he has not reacted to does. Constants cite
docs/GROUNDING.md (A4, P14, D6).
"""

from __future__ import annotations

import math

from ninety.sim import fmath
from ninety.sim.body import CONTROL_M
from ninety.sim.profiles import FATIGUE_ERROR, PRESSURE_ERROR, TURN_ERROR

BODY_TOUCH_Z = 0.45  # design (P14): above this, a ball he is under is a thigh, chest or head, not a foot
# A4, P14: the part that meets a ball, by the height of the ball's bottom: each up to the height
# given (design: thigh or raised foot from 0.45 to 0.9 m, chest 1.1 to 1.5 m, head above 1.6 m; the
# gaps between go to the nearer part, at 1.0 and 1.55 m).
SURFACES = (("foot", BODY_TOUCH_Z), ("thigh", 1.0), ("chest", 1.55), ("head", math.inf))
# design: what each kills, as a share of what his foot kills (no study measures a first touch by
# body part; GROUNDING A4). The chest gives most and drops the ball at his feet; the head kills
# least and redirects (skilled headers can send a ball on faster than it came, A4).
CUSHION = {"foot": 1.0, "thigh": 0.5, "chest": 0.75, "head": 0.25}
# design: how much wider his direction error is with each, against the foot's.
AIM_ERROR = {"foot": 1.0, "thigh": 1.5, "chest": 2.0, "head": 1.25}
TOUCH_GAP_S = 0.6  # D6 (design, verify): how long a touched ball runs before he is back on it
# What he can let the ball run and still keep it at his feet: no more than his reach (CONTROL_M) opens
# up between him and the ball before he is back on it (TOUCH_GAP_S). About 1.7 m/s.
KEEP_MPS = CONTROL_M / TOUCH_GAP_S


def surface(z: float) -> str:
    """The part of him a ball meets at height z (its bottom): foot, thigh, chest or head."""
    return next(name for name, top in SURFACES if z <= top)


def surface_absorb(foot_absorb: float, z: float) -> float:
    """What the surface he meets it with can kill (m/s, relative to him): his foot's, or the
    CUSHION share of it for a thigh, chest or head."""
    return foot_absorb * CUSHION[surface(z)]


def beaten(rel: float, absorb: float, foot_absorb: float) -> bool:
    """Is the ball far too fast for the surface to steer at all? He can steer on what is left after
    the surface's cushion up to what his foot could kill (design, *verify*); more beats him and it
    rebounds (MISCONTROL_KEEP in the engine). On the foot, twice what it kills; a head kills little
    but still steers a ball well beyond that."""
    return rel > absorb + foot_absorb


def residual(rel: float, absorb: float) -> float:
    """The speed (relative to him) the ball leaves a cushioned touch with, before his error."""
    return max(0.0, rel - absorb)


def at_feet(speed: float) -> bool:
    """Does a ball leaving his touch at `speed` (relative to him) stay at his feet?"""
    return speed <= KEEP_MPS


def kept_estimate(rel: float, absorb: float, margin: float) -> float:
    """The passer's estimate that the touch keeps the ball at the receiver's feet: the same rule,
    softened by `margin` (m/s). A heavy touch is counted as lost, though the race for it may still
    go his way (*verify*: pessimistic, as a failed touch was before)."""
    x = (absorb + KEEP_MPS - rel) / margin
    return 1.0 / (1.0 + fmath.exp(-max(-30.0, min(30.0, x))))


# What makes a touch worse (A4): each factor scales his direction error up and his cushion down by
# the same factor, from `quality`. First-touch skill acts through A4's kill limit (absorb_mps) and
# A3's skill term in the error, as before.
# Pressure is A3's term (PRESSURE_ERROR, design), measured by D2's zone from the nearest opponent.
# A4's kill limits are set for an ordinary reception: an average player, fresh and unpressed, facing
# or side-on to a pass that arrives at a typical 12 to 15 m/s (quality 1). Faster than that (from
# its middle, TYPICAL_ARRIVAL_MPS) the touch gets worse:
# by SPEED_WORSE for every foot-kill's worth of speed above it (design).
TYPICAL_ARRIVAL_MPS = 13.5  # A4: the middle of the 12 to 15 m/s a typical professional pass arrives at
SPEED_WORSE = 0.5


def approach_penalty(approach_deg: float) -> float:
    """0 to 1 for where the ball comes from against the way he faces (degrees, 0 = from straight in
    front): 0 from in front or side-on, the ordinary receptions A4 is set for; rising to 1 with his
    back to it (180), from behind his shoulder (design)."""
    a = abs((approach_deg + 180.0) % 360.0 - 180.0)
    return max(0.0, (a - 90.0) / 90.0)


def quality(approach_deg: float, pressure: float, composure: float, energy: float, rel: float,
            foot_absorb: float) -> float:
    """How much worse this touch is than his best: his direction error is multiplied by it and what
    his surface kills divided by it (1 at best). The angle the ball comes from against the way he
    faces (from behind him, up to half again: A3's TURN_ERROR), pressure from the nearest opponent in
    D2's zone (A3's PRESSURE_ERROR, eased by composure), his energy (the slow store's share left, P10,
    with A3's FATIGUE_ERROR, as for a kick) and the ball's speed relative to him beyond a typical
    pass's, against what his foot kills (SPEED_WORSE)."""
    scale = 1 + TURN_ERROR * approach_penalty(approach_deg)
    scale *= 1 + PRESSURE_ERROR * pressure * (1 - composure)
    scale *= 1 + FATIGUE_ERROR * (1 - max(0.0, min(1.0, energy)))
    scale *= 1 + SPEED_WORSE * max(0.0, rel - TYPICAL_ARRIVAL_MPS) / max(foot_absorb, 1e-6)
    return scale
