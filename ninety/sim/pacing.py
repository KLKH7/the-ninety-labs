"""What running hard is worth to a player: the price he puts on running above critical speed,
weighed against what the run is worth in the situation. One rule, used by every caller
(docs/GROUNDING.md, P17).

The price is the hazard score of anticipatory pacing (de Koning et al. 2011): an athlete changes
pace by the product of how hard it feels now and the fraction of the event still to come. Here
"how hard it feels" is how much of a fresh reserve he has spent (P10), so the price rises as his
reserve falls against the match he still has to play, and falls to nothing at the final whistle.

What a run is worth comes from the situation, in goals, by the engine's own estimates (the caller
computes it): a press is worth the chance it reaches the carrier before he can play the ball,
times what winning it there is worth to both sides (D9's threat table); a loose ball or a lunge is
worth what winning or denying it there is worth; a run in behind is worth the threat it adds.
So a press on a carrier who has just received it near our goal is worth a lot, and one on a
defender with time and space at the back almost nothing. Stamina (A1) lowers the price, work rate
(A5) raises what a run is worth to him. Only his choice reads it: the body still sets what he can
do (body.py), and a choice never changes the body.
"""

from __future__ import annotations

from ninety.sim.body import D0, Body

MATCH_S = 90 * 60.0  # Law 7: two halves of 45 minutes (the engine plays them without a break)
# *Design*, set before measuring: the exchange rate between goals and the hazard score. Running
# himself empty with the whole match left (a hazard of 1) costs his team 0.1 goals of later play,
# so a run worth 0.01 goals is worth a hazard of 0.1.
EFFORT_GOALS = 0.1
STAMINA_SPAN = 0.5  # *design*: stamina from 0 to 1 takes the price from 1.25 to 0.75 times
WORK_RATE_SPAN = 1.0  # *design*: work rate from 0 to 1 takes a run's worth from 0.5 to 1.5 times


def strain(body: Body) -> float:
    """How hard it feels now: the share of a fresh reserve he has spent (0 fresh, 1 empty). Against
    a fresh reserve, not the slow store's ceiling, so a match-long decline is felt too."""
    return min(1.0, max(0.0, 1.0 - body.reserve / D0))


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
