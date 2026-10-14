"""Synthetic player profiles: who each player is, as attributes that change causes.

An attribute never sets the chance of an outcome. Finishing widens or narrows the error of a
shot; it does not decide whether the shot goes in. Each attribute is 0 to 1 (shown 1 to 20),
and maps to a physical or cognitive parameter documented in docs/GROUNDING.md (rows A1 to A6).
Players are invented: synthetic names, no real people.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from statistics import NormalDist

from ninety.sim import perception
from ninety.sim.body import CS_MEAN, CS_SD, F0_MEAN, F0_SD, V0_MEAN, V0_SD, Body

ATTRIBUTES = ("pace", "acceleration", "stamina", "passing", "crossing", "finishing", "first_touch",
              "dribbling", "tackling", "decisions", "composure", "vision", "anticipation",
              "work_rate", "aggression", "weak_foot", "handling", "reflexes")
TRAITS = ("shoots_from_distance", "takes_players_on", "stays_wide", "runs_in_behind", "plays_short")

# Design: role tendencies. Skill attributes shift from an average 0.5. Physical attributes are
# percentiles of the sourced distributions (P2, P9, P10), so their role shifts are in standard
# deviations of those distributions; a role with no shift keeps the sourced mean and spread.
PHYSICAL = ("pace", "acceleration", "stamina")
ROLE_SHIFTS = {
    "GK": {"handling": 0.3, "reflexes": 0.3, "passing": -0.1, "pace": -0.5},
    "CB": {"tackling": 0.25, "aggression": 0.15, "finishing": -0.25, "dribbling": -0.15, "crossing": -0.2},
    "FB": {"pace": 0.5, "stamina": 0.7, "crossing": 0.15, "work_rate": 0.1},
    "CM": {"passing": 0.2, "vision": 0.2, "stamina": 0.5, "decisions": 0.1, "first_touch": 0.1},
    "W": {"pace": 0.7, "acceleration": 0.5, "dribbling": 0.2, "crossing": 0.15, "tackling": -0.15},
    "ST": {"finishing": 0.25, "anticipation": 0.15, "composure": 0.1, "tackling": -0.2},
}
ROLE_GROUP = {"GK": "GK", "RCB": "CB", "LCB": "CB", "RB": "FB", "LB": "FB", "RCM": "CM", "CM": "CM",
              "LCM": "CM", "RW": "W", "LW": "W", "ST": "ST"}
ATTRIBUTE_SD = 0.17  # design
NORMAL = NormalDist()

# A1 to A6: what each attribute changes.
KICK_ERROR_DEG = 3.0  # A3: preferred-foot direction error at a precise penalty (~21 m/s, 11 m)
KICK_REF_SPEED = 21.0
WEAK_FOOT_ERROR = 3.8 / 3.0  # A3: about 27% wider on the weaker foot ...
WEAK_FOOT_SPEED = 0.88  # A3: ... and about 12% slower
FATIGUE_ERROR = 0.25  # A3: shots about 25% less accurate when fatigued (the slow store, P10)
SPEED_ERROR = 0.06  # design: spread of struck speed, as a share
READ_ERROR_M = 1.5  # design: spread of a keeper's read of a shot's aim, at average anticipation
LOFT_ERROR_DEG = 2.0  # design: spread of launch angle

SYLLABLES = ("ka", "lo", "mi", "ren", "to", "va", "sun", "de", "ri", "an", "bo", "el", "ju", "ny", "or",
             "sa", "te", "vi", "zo", "ma", "ke", "lu", "ni", "pe", "ro")


def synthetic_name(rng: random.Random) -> str:
    def word(parts: int) -> str:
        return "".join(rng.choice(SYLLABLES) for _ in range(parts)).capitalize()
    return f"{word(rng.choice((2, 2, 3)))} {word(rng.choice((2, 3, 3)))}"


@dataclass
class Profile:
    name: str
    foot: str  # "right" or "left"
    attributes: dict[str, float]
    traits: list[str] = field(default_factory=list)

    @classmethod
    def generate(cls, role: str, rng: random.Random) -> Profile:
        shifts = ROLE_SHIFTS[ROLE_GROUP[role]]
        attributes = {}
        for a in ATTRIBUTES:
            if a in PHYSICAL:
                attributes[a] = NORMAL.cdf(rng.gauss(shifts.get(a, 0.0), 1.0))
            else:
                attributes[a] = min(1.0, max(0.0, rng.gauss(0.5 + shifts.get(a, 0.0), ATTRIBUTE_SD)))
        traits = [t for t in TRAITS if rng.random() < 0.15]
        return cls(synthetic_name(rng), "left" if rng.random() < 0.2 else "right", attributes, traits)

    def __getitem__(self, attribute: str) -> float:
        return self.attributes[attribute]

    def rating(self, attribute: str) -> int:
        """The familiar 1 to 20 scale, for display and commentary."""
        return 1 + round(self[attribute] * 19)

    # ---- A1: body ------------------------------------------------------------
    def physique(self) -> Body:
        """Each physical attribute is a percentile of its sourced distribution: acceleration
        from standing (P2), top-speed capability (P9), critical speed (P10)."""
        def z(attribute: str) -> float:
            return NORMAL.inv_cdf(min(0.999, max(0.001, self[attribute])))
        return Body(f0=F0_MEAN + F0_SD * z("acceleration"), v0=V0_MEAN + V0_SD * z("pace"),
                    cs=CS_MEAN + CS_SD * z("stamina"))

    # ---- A2: perception and reaction ------------------------------------------
    def reaction(self) -> float:
        """Choice reaction to a struck ball, across footballers' measured range: quicker with
        better reflexes. The same for keepers; reading the kicker is `read_error_m`."""
        slow, fast = perception.CHOICE_REACTION_RANGE_S
        return slow - (slow - fast) * self["reflexes"]

    def read_error_m(self) -> float:
        """How far off a keeper's early read of a shot's aim can be (a standard deviation):
        anticipation is reading cues, so it narrows the error; it never speeds the reaction."""
        return READ_ERROR_M * (1.5 - self["anticipation"])

    def view_half_angle(self) -> float:
        return math.radians(50 + 20 * self["vision"])  # design

    def scan_interval(self) -> tuple[float, float]:
        mean = 3.5 - 2.0 * self["vision"]  # design: better vision, more frequent scans
        return mean * 0.7, mean * 1.3

    # ---- A4: control -------------------------------------------------------------
    def absorb_mps(self, hands: bool) -> float:
        """Fastest ball (relative to the player) a touch can kill; with the hands, a keeper's
        hold. No study measures either; design, scaled by skill."""
        if hands:
            return 16.0 + 12.0 * self["handling"]
        return 8.0 + 8.0 * self["first_touch"]

    # ---- A3: execution -------------------------------------------------------
    def kick_error(self, skill: str, speed: float, pressure: float, capacity: float,
                   weak_foot: bool) -> tuple[float, float, float]:
        """Standard deviations of a kick's direction (degrees), speed (share) and launch angle
        (degrees). Average skill on the preferred foot at penalty speed gives about 3 degrees;
        error grows with speed, pressure (less for the composed), fatigue and the weaker foot."""
        sigma = KICK_ERROR_DEG * (1.6 - 1.2 * self[skill]) * (speed / KICK_REF_SPEED)
        sigma *= 1 + 0.5 * pressure * (1 - self["composure"])
        sigma *= 1 + FATIGUE_ERROR * (1 - capacity)
        if weak_foot:
            sigma *= 1 + (WEAK_FOOT_ERROR - 1) * (1 - self["weak_foot"])
        return sigma, SPEED_ERROR * (1 + pressure * (1 - self["composure"])), LOFT_ERROR_DEG

    def weak_foot_speed(self) -> float:
        return WEAK_FOOT_SPEED + (1 - WEAK_FOOT_SPEED) * self["weak_foot"]
