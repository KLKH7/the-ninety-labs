"""What running hard is worth to a player: the price he puts on running above critical speed, and
the choices that read it. One rule, used by every caller (docs/GROUNDING.md, P17).

The shape is the hazard score of anticipatory pacing (de Koning et al. 2011): an athlete changes
pace by the product of how hard it feels now and the fraction of the event still to come. Here
"how hard it feels" is how much of a fresh reserve he has spent (P10), so the price rises as his
reserve falls against the match he still has to play, and falls to nothing at the final whistle.
Stamina (A1) lowers the price, work rate (A5) raises what a run is worth to him. Only his choice
reads it: the body still sets what he can do (body.py), and a choice never changes the body.
"""

from __future__ import annotations

from ninety.sim.body import D0, Body

MATCH_S = 90 * 60.0  # Law 7: two halves of 45 minutes (the engine plays them without a break)
# What a run is worth, on the hazard score's scale (0 to 1). *Design*, set before measuring:
CONTEST_VALUE = 1.0  # a ball he can win now: a committed lunge, a loose ball his team sends him to
ROUTINE_VALUE = 0.15  # a press he is asked to make, a run in behind: worth it while he is fresh
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


def worth(value: float, work_rate: float) -> float:
    """What a run of this value is worth to him: more to a player with a higher work rate."""
    return value * (1.0 + WORK_RATE_SPAN * (work_rate - 0.5))


def accepts(body: Body, stamina: float, work_rate: float, t: float, value: float = ROUTINE_VALUE) -> bool:
    """Does he make a run of this value? Only if it is worth more to him than it costs."""
    return worth(value, work_rate) > price(body, stamina, t)


def run_speed(body: Body, stamina: float, work_rate: float, t: float, value: float) -> float:
    """The speed he asks for on a run of this value: up to his top-speed capability while it
    costs him nothing, nearer his critical speed as the price approaches what it is worth (half
    the speed above it when they are equal). His body still caps what he gets (body.move)."""
    w = worth(value, work_rate)
    p = price(body, stamina, t)
    share = w / (w + p) if w + p > 0 else 1.0
    return body.cs + (body.v0 - body.cs) * share
