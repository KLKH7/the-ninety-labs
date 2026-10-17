"""What running hard is worth to a player: the price he puts on running above critical speed,
weighed against what the run is worth in the situation. One rule, used by every caller
(docs/GROUNDING.md, P17).

The price is the hazard score of anticipatory pacing (de Koning et al. 2011): an athlete changes
pace by the product of how hard it feels now and the fraction of the event still to come. Over a
match, "how hard it feels" is how far the slow store has fallen (P10): the match-long decline,
not the reserve's dip after each sprint, which refills in minutes and is the body's limit, not a
reason to save himself for the rest of the match. So the price rises as the slow store falls
against the match he still has to play, and falls to nothing at the final whistle.

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
# The exchange rate between goals and the hazard score, *design*, *verify*: a hazard of 1 is his
# slow store gone with the whole match left, so he can no longer run above critical speed for a
# match. A sending-off with 30 minutes left costs about 0.39 to 0.50 goals (top five European
# leagues, 2022), about 1.2 to 1.5 over a whole match at that rate; losing only his running above
# critical speed is taken as a quarter of losing him (*design*): about 0.3 goals.
EFFORT_GOALS = 0.3
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


def price(body: Body, stamina: float, t: float) -> float:
    """The hazard score (strain times the match left), lowered for a player with more stamina."""
    return strain(body) * time_left(t) * (1.0 - STAMINA_SPAN * (stamina - 0.5))


def worth(goals: float, work_rate: float) -> float:
    """What a run worth `goals` is worth to him on the hazard score's scale: more to a player with
    a higher work rate. Never below nothing."""
    return max(0.0, goals) / EFFORT_GOALS * (1.0 + WORK_RATE_SPAN * (work_rate - 0.5))


def closes_down(arrive: float, controlled_at: float) -> float:
    """The chance a presser who reaches the carrier `arrive` seconds from now still finds the ball
    at his feet, when the carrier has (or will have) it under control `controlled_at` seconds from
    now: certain if he is there first, then falling as the carrier's time on the ball runs out."""
    return math.exp(-max(0.0, arrive - controlled_at) / ON_BALL_S)


def accepts(body: Body, stamina: float, work_rate: float, t: float, goals: float) -> bool:
    """Does he make a run worth `goals`? Only if it is worth more to him than it costs."""
    return worth(goals, work_rate) > price(body, stamina, t)


def run_speed(body: Body, stamina: float, work_rate: float, t: float, goals: float) -> float:
    """The speed he asks for on a run worth `goals`: up to his top-speed capability while it costs
    him nothing, nearer his critical speed as the price approaches what it is worth (half the
    speed above it when they are equal; *design*). His body still caps what he gets (body.move)."""
    w = worth(goals, work_rate)
    p = price(body, stamina, t)
    share = w / (w + p) if w + p > 0 else 1.0
    return body.cs + (body.v0 - body.cs) * share
