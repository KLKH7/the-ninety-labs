"""What running hard is worth to a player: the price he puts on each metre run above critical
speed, so a run costs the metres it would take above it, weighed against what the run is worth
in the situation. One rule, used by every caller (docs/GROUNDING.md, P17).

The price per metre follows the hazard score of anticipatory pacing (de Koning et al. 2011): an
athlete changes pace by the product of how hard it feels now and the fraction of the event still
to come. Over a match, "how hard it feels" is how far the slow store has fallen (P10): the
match-long decline, not the reserve's dip after each sprint, which refills in minutes and is the
body's limit, not a reason to save himself for the rest of the match. So a metre costs nothing
while he is fresh, more as the slow store falls against the match he still has to play, and
nothing again at the final whistle; a step to pressing distance costs little, a long chase more.

What a run is worth comes from the situation, in goals, by the engine's own estimates (the caller
computes it): a press is worth the danger it takes away (the threat of their ball there, D9) and,
where he could win it, the threat of ours, times the chance he closes the carrier down before the
carrier plays it; a loose ball or a lunge is worth what winning it there is worth; a run in behind
the threat it adds. Stamina (A1) lowers the price, work rate (A5) raises what a run is worth to
him. Only his choice reads it: the body still sets what he can do (body.py), and a choice never
changes the body.
"""

from __future__ import annotations

import math

from ninety.sim.body import D0, Body

MATCH_S = 90 * 60.0  # Law 7: two halves of 45 minutes (the engine plays them without a break)
# The price of a metre above critical speed at a hazard of 1, *design*, set from a stated argument
# before measuring what it does: a hard 20 m chase by a moderately tired player costs about what a
# press in midfield is worth. Moderately tired: his slow store 20% down at half-time, a hazard of
# 0.1. A hard 20 m chase: flat out at the mean top-speed capability (P9, 10 m/s) above the mean
# critical speed (P10, 3.9 m/s), 12.2 m above it. A press in midfield: the engine's own worth for a
# settled carrier at halfway with the presser 8 m off (Engine.press_run), 0.0068 goals.
MIDFIELD_PRESS_GOALS = 0.0068
CHASE_ABOVE_M = 12.2
MODERATE_HAZARD = 0.1
GOALS_PER_METRE = MIDFIELD_PRESS_GOALS / (CHASE_ABOVE_M * MODERATE_HAZARD)
# How long a carrier keeps the ball once he has it under control, on average (*design*, *verify*):
# taken as memoryless, so a presser arriving `t` seconds after control finds him still on it with
# chance exp(-t / ON_BALL_S). Teams in possession play about one pass every 5 s (arXiv 2005.04020),
# which includes the ball's travel and every touch between passes; 2 s is taken for one carrier.
ON_BALL_S = 2.0
STAMINA_SPAN = 0.5  # *design*: stamina from 0 to 1 takes the price from 1.25 to 0.75 times
WORK_RATE_SPAN = 1.0  # *design*: work rate from 0 to 1 takes a run's worth from 0.5 to 1.5 times


def strain(body: Body) -> float:
    """How hard the match feels now: the share of the slow store that has gone (P10), 0 at kick-off."""
    return min(1.0, max(0.0, 1.0 - body.ceiling / D0))


def time_left(t: float) -> float:
    """The fraction of the match still to play at match time t (seconds)."""
    return min(1.0, max(0.0, (MATCH_S - t) / MATCH_S))


def hazard(body: Body, stamina: float, t: float) -> float:
    """The hazard score (strain times the match left), lowered for a player with more stamina."""
    return strain(body) * time_left(t) * (1.0 - STAMINA_SPAN * (stamina - 0.5))


def metres_above(distance: float, speed: float, cs: float) -> float:
    """The metres above critical speed a run of `distance` at `speed` takes from his reserve (P10:
    what his reserve spends, the excess over critical speed for as long as the run lasts)."""
    return max(0.0, speed - cs) * distance / speed if speed > 0 else 0.0


def cost(body: Body, stamina: float, t: float, metres: float) -> float:
    """What spending `metres` above critical speed costs him now, in goals."""
    return metres * GOALS_PER_METRE * hazard(body, stamina, t)


def worth(goals: float, work_rate: float) -> float:
    """What a run worth `goals` is worth to him: more to a player with a higher work rate. Never
    below nothing."""
    return max(0.0, goals) * (1.0 + WORK_RATE_SPAN * (work_rate - 0.5))


def closes_down(arrive: float, controlled_at: float) -> float:
    """The chance a presser who reaches the carrier `arrive` seconds from now still finds the ball
    at his feet, when the carrier has (or will have) it under control `controlled_at` seconds from
    now: certain if he is there first, then falling as the carrier's time on the ball runs out."""
    return math.exp(-max(0.0, arrive - controlled_at) / ON_BALL_S)


def accepts(body: Body, stamina: float, work_rate: float, t: float, goals: float, metres: float) -> bool:
    """Does he make a run worth `goals` that takes `metres` above critical speed? Only if it is
    worth more to him than it costs (so one that costs nothing whenever it is worth anything)."""
    return worth(goals, work_rate) > cost(body, stamina, t, metres)


def run_speed(body: Body, stamina: float, work_rate: float, t: float, goals: float,
              distance: float) -> float:
    """The speed he asks for on a run of `distance` worth `goals`: up to his top-speed capability
    while it costs him nothing, nearer his critical speed as what it would cost flat out approaches
    what it is worth (half the speed above it when they are equal; *design*). His body still caps
    what he gets (body.move)."""
    w = worth(goals, work_rate)
    c = cost(body, stamina, t, metres_above(distance, body.v0, body.cs))
    share = w / (w + c) if w + c > 0 else 1.0
    return body.cs + (body.v0 - body.cs) * share
