"""Roles and mentalities: what a player's archetype makes him want to do off the ball, and how a
team's build-up style shapes it (docs/GROUNDING.md R-rows below, T4, O9).

A role is an intention, never an outcome: an overlapping full back wants to run beyond the ball on
his flank, an inside forward wants to cut inside and run in behind, a deep-lying playmaker wants to
drop and receive. Whether the run is found, the pass arrives or the take-on works is decided by the
same perception, decisions, race and body as everything else. All values here are *design*: common
football role concepts (Kian, 2026-10-15: baseline football concepts need no citation), never
fitted to a match rate.
"""

from __future__ import annotations

from dataclasses import dataclass

DEFEND, BALANCED, ATTACK = -1, 0, 1


@dataclass(frozen=True)
class Role:
    duty: int  # DEFEND, BALANCED or ATTACK: how far and how often he goes forward with the ball
    forward_m: float  # his in-possession spot, this many metres higher (negative: deeper)
    inside_m: float  # and this many metres nearer the centre (negative: wider)
    runs: frozenset[str] = frozenset()  # the runs he makes when the carrier can play one
    high_press: bool = False  # out of possession he goes to the ball beyond his team's engagement line


# In behind: beyond the last line. Diagonal: in behind, from wide toward the near half-space.
# Overlap: beyond the ball on his own flank. Late: into the box once the ball is in the final third.
# Drop: comes short toward the ball to receive in front of the block.
ROLES = {
    "shot_stopper": Role(DEFEND, 0.0, 0.0),
    "sweeper_keeper": Role(DEFEND, 0.0, 0.0),
    "stopper": Role(DEFEND, -2.0, 0.0),
    "ball_playing": Role(BALANCED, 0.0, -3.0),  # splits wider to receive in build-up
    "defensive": Role(DEFEND, -6.0, 2.0),
    "overlapping": Role(ATTACK, 6.0, 0.0, frozenset({"overlap"})),
    "deep_playmaker": Role(BALANCED, -6.0, 0.0, frozenset({"drop"})),
    "box_to_box": Role(ATTACK, 4.0, 0.0, frozenset({"late"}), high_press=True),
    "ball_winner": Role(DEFEND, -3.0, 0.0),
    "touchline_winger": Role(BALANCED, 0.0, -2.0),
    "inside_forward": Role(ATTACK, 0.0, 5.0, frozenset({"diagonal"})),
    "poacher": Role(ATTACK, 0.0, 0.0, frozenset({"in_behind"})),
    "target_forward": Role(BALANCED, -4.0, 0.0, frozenset({"drop"})),
    "pressing_forward": Role(ATTACK, 0.0, 0.0, frozenset({"in_behind"}), high_press=True),
}
DEFAULT = Role(BALANCED, 0.0, 0.0)


@dataclass(frozen=True)
class Style:
    forward_m: float  # the whole team's in-possession shape, this many metres higher
    width_m: float  # and this much wider either side
    run_duties: tuple[int, ...]  # the duties whose runs the team makes


# T4: build-up style. Short: patient, wide, everyone available. Balanced. Counter: forwards stay
# high and the team goes direct, only the attacking roles run. Drawn per team like the block.
STYLES = {
    "short": Style(-3.0, 3.0, (BALANCED, ATTACK)),
    "balanced": Style(0.0, 0.0, (BALANCED, ATTACK)),
    "counter": Style(4.0, -2.0, (ATTACK,)),
}

OVERLAP_AHEAD_M = 10.0  # an overlap runs this far beyond the ball, on his flank
OVERLAP_TOUCHLINE_M = 4.0  # this far in from the touchline
OVERLAP_FLANK_M = 20.0  # the ball is on his flank when it is within this of his own spot across
DIAGONAL_HALF_SPACE_M = 9.0  # an inside forward's run ends this far from the centre line
LATE_RUN_DEPTH_M = 12.0  # a late run arrives this far from goal (around the penalty spot)
DROP_AHEAD_M = 12.0  # a player dropping short offers himself this far in front of the ball


def role_of(archetype: str | None) -> Role:
    return ROLES.get(archetype or "", DEFAULT)
