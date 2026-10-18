"""Roles and mentalities: what a player's archetype makes him want to do off the ball, and how a
team's style (style.py, its directness dial) shapes it (docs/GROUNDING.md O9, O10, T4).

A role is an intention, never an outcome: an overlapping full back wants to run beyond the ball on
his flank, an inside forward wants to cut inside and run in behind, a deep-lying playmaker wants to
drop and receive. Whether the run is found, the pass arrives or the take-on works is decided by the
same perception, decisions, race and body as everything else. All values here are *design*: common
football role concepts (Kian, 2026-10-15: baseline football concepts need no citation), never
fitted to a match rate.
"""

from __future__ import annotations

from dataclasses import dataclass

from ninety.sim import fmath

DEFEND, BALANCED, ATTACK = -1, 0, 1


@dataclass(frozen=True)
class Role:
    duty: int  # DEFEND, BALANCED or ATTACK: how far and how often he goes forward with the ball
    forward_m: float  # his in-possession spot, this many metres higher (negative: deeper)
    inside_m: float  # and this many metres nearer the centre (negative: wider)
    # O10: his prior on each off-ball move beyond holding his spot (offball.MOVES), as a weight on
    # what the move is worth: 0 or absent means the move is not in his repertoire.
    moves: tuple[tuple[str, float], ...] = ()
    high_press: bool = False  # out of possession he goes to the ball beyond his team's engagement line

    def prior(self, kind: str) -> float:
        return dict(self.moves).get(kind, 0.0)


# O10: the moves each role leans toward. A prior multiplies what the move is worth to his team, so a
# role makes its run more often, never a run that is worth nothing. 1.5 is a role's signature move,
# 1 an ordinary one, below 1 one it makes reluctantly. In behind: beyond the last line, in his lane.
# Channel: in behind, from wide toward the near half-space. Overlap: beyond the ball on his own flank.
# Late: into the box once the ball is in the final third. Short: toward the ball to receive in front
# of the block. All *design*: common role concepts (Kian, 2026-10-15), never fitted to a match rate.
ROLES = {
    "shot_stopper": Role(DEFEND, 0.0, 0.0),
    "sweeper_keeper": Role(DEFEND, 0.0, 0.0),
    "stopper": Role(DEFEND, -2.0, 0.0),
    "ball_playing": Role(BALANCED, 0.0, -3.0),  # splits wider to receive in build-up
    "defensive": Role(DEFEND, -6.0, 2.0),
    "overlapping": Role(ATTACK, 6.0, 0.0, (("overlap", 1.5),)),
    "deep_playmaker": Role(BALANCED, -6.0, 0.0, (("short", 1.5),)),
    "box_to_box": Role(ATTACK, 4.0, 0.0, (("late", 1.5), ("short", 0.7)), high_press=True),
    "ball_winner": Role(DEFEND, -3.0, 0.0, (("short", 0.7),)),
    "touchline_winger": Role(BALANCED, 0.0, -2.0, (("in_behind", 1.0),)),
    "inside_forward": Role(ATTACK, 0.0, 5.0, (("channel", 1.5), ("in_behind", 0.7), ("late", 0.7))),
    "poacher": Role(ATTACK, 0.0, 0.0, (("in_behind", 1.5), ("late", 1.0))),
    "target_forward": Role(BALANCED, -4.0, 0.0, (("short", 1.5), ("in_behind", 0.7))),
    "pressing_forward": Role(ATTACK, 0.0, 0.0, (("in_behind", 1.0), ("short", 0.7)), high_press=True),
}
DEFAULT = Role(BALANCED, 0.0, 0.0)


# O10, T4: how a team's directness (style.py) weighs the off-ball moves, on top of the role's prior.
# A direct side wants runs in behind and few players coming short; a patient one the reverse (the
# build-up settings of common team instructions). At full directness a move's weight is the
# "direct" value, at none the "patient" one, at the mid value 1, in between geometrically. *design*
DIRECT_MOVES = {"short": 0.7, "in_behind": 1.5, "channel": 1.5, "overlap": 0.7}
PATIENT_MOVES = {"short": 1.5, "in_behind": 0.7, "channel": 0.7}


def style_weight(directness_tilt: float, kind: str) -> float:
    """O10: the weight a team's directness (its tilt, -1 to 1, style.tilt) puts on an off-ball move."""
    if directness_tilt >= 0:
        return fmath.exp(directness_tilt * fmath.log(DIRECT_MOVES.get(kind, 1.0)))
    return fmath.exp(-directness_tilt * fmath.log(PATIENT_MOVES.get(kind, 1.0)))


TRAIT_MOVES = {"runs_in_behind": {"in_behind": 1.5}}  # O10: a habit is a prior on one move (*design*)

OVERLAP_AHEAD_M = 10.0  # an overlap runs this far beyond the ball, on his flank
OVERLAP_TOUCHLINE_M = 4.0  # this far in from the touchline
OVERLAP_FLANK_M = 20.0  # the ball is on his flank when it is within this of his own spot across
DIAGONAL_HALF_SPACE_M = 9.0  # an inside forward's run ends this far from the centre line
LATE_RUN_DEPTH_M = 12.0  # a late run arrives this far from goal (around the penalty spot)
DROP_AHEAD_M = 12.0  # a player dropping short offers himself this far in front of the ball


def role_of(archetype: str | None) -> Role:
    return ROLES.get(archetype or "", DEFAULT)
