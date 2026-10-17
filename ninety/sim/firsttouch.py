"""The first touch: one rule for the engine's touch and the passer's estimate of it (A4).

A player who has reacted to the ball and reaches it cushions it: the surface he meets it with
takes out up to what it can kill of the ball's speed relative to him (A4: `Profile.absorb_mps`, a
thigh, chest or head AERIAL_ABSORB of a foot's), and he sends what is left toward where he chose,
with his own error. What is left decides the rest, never a roll: a ball slow enough for him to
keep up with stays at his feet; anything more is a heavy touch, free until he is back on it after
TOUCH_GAP_S, like a dribbling touch (D6), and whoever reaches it first has it. A ball far too fast
for the surface beats it and rebounds, as a ball he has not reacted to does. Constants cite
docs/GROUNDING.md (A4, P14, D6).
"""

from __future__ import annotations

from ninety.sim import fmath
from ninety.sim.body import CONTROL_M

BODY_TOUCH_Z = 0.45  # design (P14): above this, a ball he is under is a thigh, chest or head, not a foot
AERIAL_ABSORB = 0.5  # design: those kill about half the pace a foot does (A4), same first touch
TOUCH_GAP_S = 0.6  # D6 (design, verify): how long a touched ball runs before he is back on it
# What he can let the ball run and still keep it at his feet: no more than his reach (CONTROL_M) opens
# up between him and the ball before he is back on it (TOUCH_GAP_S). About 1.7 m/s.
KEEP_MPS = CONTROL_M / TOUCH_GAP_S
# design, *verify*: a ball more than this many times what the surface kills beats it: it rebounds
# off him (MISCONTROL_KEEP in the engine) rather than being steered.
BEATEN_FACTOR = 2.0


def surface_absorb(foot_absorb: float, z: float) -> float:
    """What the surface he meets it with can kill (m/s, relative to him): the foot's, or a thigh,
    chest or head's above BODY_TOUCH_Z."""
    return foot_absorb * (AERIAL_ABSORB if z > BODY_TOUCH_Z else 1.0)


def beaten(rel: float, absorb: float) -> bool:
    """Is the ball far too fast for the surface to steer at all?"""
    return rel > BEATEN_FACTOR * absorb


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
