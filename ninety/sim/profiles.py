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

# How a squad is generated (docs/GROUNDING.md A1, A6, A7). Every attribute starts as a score in
# standard deviations (z), built from a few shared causes rather than drawn on its own:
#   team strength -> player quality -> archetype within his position -> factors -> attributes.
# Quality lifts every skill a little; a factor ties together skills that go together (technique,
# game intelligence, defending, goalkeeping, speed); the rest is the player's own. Physical
# attributes are percentiles of the sourced distributions (P2, P9, P10) and quality does not move
# them, so the population keeps the measured means and spreads; skill attributes are
# 0.5 + ATTRIBUTE_SD * z. Archetype shifts are in z units.
PHYSICAL = ("pace", "acceleration", "stamina")
FACTOR_OF = {
    "passing": "technique", "crossing": "technique", "finishing": "technique", "first_touch": "technique",
    "dribbling": "technique", "weak_foot": "technique",
    "decisions": "intelligence", "composure": "intelligence", "vision": "intelligence",
    "anticipation": "intelligence", "work_rate": "intelligence",
    "tackling": "defending", "aggression": "defending",
    "handling": "keeping", "reflexes": "keeping",
    "pace": "speed", "acceleration": "speed",
}
QUALITY_LOADING = 0.5  # design: how much a player's overall quality lifts each skill
FACTOR_LOADING = 0.5  # design: how much one factor ties its skills together
SPEED_LOADING = math.sqrt(0.6)  # A7: acceleration and top speed correlate about 0.6 in footballers
# design: spread of team strength in a league, in player-quality SDs. sqrt(2/3) puts 40% of the
# variation in player quality between teams (TEAM_SD² / (TEAM_SD² + 1)).
TEAM_SD = math.sqrt(2 / 3)
TRAIT_BASE, TRAIT_SLOPE = -2.0, 1.5  # design: a trait is likelier the stronger the skill behind it
TRAIT_DRIVERS = {
    "shoots_from_distance": ("finishing",),
    "takes_players_on": ("dribbling",),
    "stays_wide": ("crossing",),
    "runs_in_behind": ("pace", "anticipation"),
    "plays_short": ("passing", "composure"),
}
# Archetypes within each position: (name, share, z shifts). Shares and shifts are design.
ARCHETYPES = {
    "GK": [("shot_stopper", 0.6, {"handling": 1.8, "reflexes": 2.0, "passing": -0.6, "pace": -0.6}),
           ("sweeper_keeper", 0.4, {"handling": 1.5, "reflexes": 1.5, "passing": 0.4, "anticipation": 0.8,
                                    "composure": 0.6, "pace": -0.2})],
    "CB": [("stopper", 0.55, {"tackling": 1.8, "aggression": 1.2, "finishing": -1.5, "dribbling": -1.2,
                              "crossing": -1.2, "passing": -0.4}),
           ("ball_playing", 0.45, {"tackling": 1.2, "passing": 0.8, "composure": 0.8, "vision": 0.6,
                                   "finishing": -1.5, "crossing": -1.0})],
    "FB": [("defensive", 0.45, {"tackling": 1.0, "stamina": 0.5, "pace": 0.3, "crossing": 0.2}),
           ("overlapping", 0.55, {"crossing": 1.2, "stamina": 0.9, "pace": 0.7, "work_rate": 0.8,
                                  "tackling": 0.2})],
    "CM": [("deep_playmaker", 0.3, {"passing": 1.6, "vision": 1.6, "composure": 1.0, "stamina": 0.2}),
           ("box_to_box", 0.4, {"stamina": 0.9, "work_rate": 1.2, "passing": 0.8, "tackling": 0.6,
                                "finishing": 0.3}),
           ("ball_winner", 0.3, {"tackling": 1.6, "aggression": 1.2, "work_rate": 1.2, "stamina": 0.6,
                                 "passing": 0.3})],
    "W": [("touchline_winger", 0.5, {"pace": 0.9, "acceleration": 0.6, "crossing": 1.4, "dribbling": 1.0,
                                     "tackling": -0.9}),
          ("inside_forward", 0.5, {"pace": 0.6, "acceleration": 0.6, "dribbling": 1.4, "finishing": 1.0,
                                   "crossing": 0.2, "tackling": -0.9})],
    "ST": [("poacher", 0.4, {"finishing": 1.8, "anticipation": 1.2, "composure": 0.6, "tackling": -1.2}),
           ("target_forward", 0.3, {"finishing": 1.2, "first_touch": 1.0, "aggression": 0.8, "pace": -0.4,
                                    "tackling": -0.9}),
           ("pressing_forward", 0.3, {"finishing": 1.0, "work_rate": 1.4, "stamina": 0.7, "pace": 0.4,
                                      "tackling": -0.3})],
}
# Share of left-footed players by position (design; about a fifth to a quarter overall).
# A wide player usually has the foot on his own side; an inside forward the other one.
LEFT_FOOTED = {"LB": 0.7, "LW": 0.7, "LCB": 0.35, "LCM": 0.25, "GK": 0.2, "CM": 0.2, "ST": 0.2,
               "RB": 0.1, "RW": 0.1, "RCB": 0.1, "RCM": 0.1}
ROLE_GROUP = {"GK": "GK", "RCB": "CB", "LCB": "CB", "RB": "FB", "LB": "FB", "RCM": "CM", "CM": "CM",
              "LCM": "CM", "RW": "W", "LW": "W", "ST": "ST"}
ATTRIBUTE_SD = 0.17  # design: spread of a skill attribute around an average 0.5
NORMAL = NormalDist()
# Skill attributes are NORMAL.cdf(SKILL_SCALE * z): the same 0.17 spread near the average, but
# saturating smoothly toward 0 and 1 instead of piling up at a clamp.
SKILL_SCALE = ATTRIBUTE_SD / 0.3989
FORMATION_ROLES = ("GK", "RB", "RCB", "LCB", "LB", "RCM", "CM", "LCM", "RW", "ST", "LW")


def _physical_centre() -> dict[str, float]:
    """The average physical shift over a squad's positions and archetypes, removed so that a
    whole squad keeps the sourced means (P2, P9, P10) while positions still differ."""
    centre = {}
    for a in PHYSICAL:
        total = 0.0
        for role in FORMATION_ROLES:
            kinds = ARCHETYPES[ROLE_GROUP[role]]
            total += sum(share * shifts.get(a, 0.0) for _, share, shifts in kinds) / sum(k[1] for k in kinds)
        centre[a] = total / len(FORMATION_ROLES)
    return centre


PHYSICAL_CENTRE = _physical_centre()


def sigmoid(x: float) -> float:
    return 1 / (1 + math.exp(-x))


def team_strength(rng: random.Random) -> float:
    """A team's strength in player-quality SDs (0 is a league-average side)."""
    return rng.gauss(0.0, TEAM_SD)


# A1 to A6: what each attribute changes.
KICK_ERROR_DEG = 3.0  # A3: preferred-foot direction error at a precise penalty (~21 m/s, 11 m)
KICK_REF_SPEED = 21.0
WEAK_FOOT_ERROR = 3.8 / 3.0  # A3: about 27% wider on the weaker foot ...
WEAK_FOOT_SPEED = 0.88  # A3: ... and about 12% slower
FATIGUE_ERROR = 0.25  # A3: design, *verify*: about 25% wider when the slow store (P10) is spent
SPEED_ERROR = 0.06  # design: spread of struck speed, as a share
FOOT_ABSORB_MPS = (12.0, 12.0)  # A4: a first touch kills 12 m/s plus 12 m/s more at full first-touch skill
READ_ERROR_M = 1.5  # design: spread of a keeper's read of a shot's aim, at average anticipation
LOFT_ERROR_DEG = 2.0  # design: spread of launch angle
# P17: design, verify: a header's direction and height are this much less precise than a kick's
HEADER_ERROR = 2.0
TURN_ERROR = 0.5  # design: error widens by up to half again for a ball struck across the body
PRESSURE_M = 3.0  # design: an opponent this close puts the kicker under full pressure
WEAK_SIDE_DEG = 30.0  # design: a kick this far to the weaker foot's side is struck with it
MAX_STRIKE_MPS = 36.0  # design: the hardest a foot strikes a ball, below the 40 m/s check (P3)

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
    archetype: str = ""
    quality: float = 0.0  # overall quality in SDs; it moves skills, it is never used directly

    @classmethod
    def generate(cls, role: str, rng: random.Random, strength: float = 0.0,
                 archetype: str | None = None) -> Profile:
        """One player for a position, in a team of the given strength (the archetype is drawn
        by its share unless given)."""
        group = ROLE_GROUP[role]
        names = ARCHETYPES[group]
        if archetype is None:
            archetype = rng.choices(names, weights=[a[1] for a in names])[0][0]
        shifts = next(a[2] for a in names if a[0] == archetype)
        quality = strength + rng.gauss(0.0, 1.0)
        # sorted, so the draws come in the same order on every run
        factors = {f: rng.gauss(0.0, 1.0) for f in sorted(set(FACTOR_OF.values()))}
        z = {}
        for a in ATTRIBUTES:
            factor = FACTOR_OF.get(a)
            if a in PHYSICAL:  # quality does not make a player faster; speed ties pace to acceleration
                load = SPEED_LOADING if factor else 0.0
                common = load * factors["speed"] if factor else 0.0
                shift = shifts.get(a, 0.0) - PHYSICAL_CENTRE[a]
                z[a] = shift + common + math.sqrt(1 - load * load) * rng.gauss(0.0, 1.0)
            else:
                own = math.sqrt(1 - QUALITY_LOADING ** 2 - FACTOR_LOADING ** 2)
                z[a] = (shifts.get(a, 0.0) + QUALITY_LOADING * quality + FACTOR_LOADING * factors[factor]
                        + own * rng.gauss(0.0, 1.0))
        attributes = {a: NORMAL.cdf(z[a] if a in PHYSICAL else SKILL_SCALE * z[a]) for a in ATTRIBUTES}
        traits = []
        for trait, drivers in TRAIT_DRIVERS.items() if group != "GK" else ():  # outfield habits
            drive = sum(z[d] for d in drivers) / len(drivers)
            if rng.random() < sigmoid(TRAIT_BASE + TRAIT_SLOPE * drive):
                traits.append(trait)
        left = LEFT_FOOTED[role]
        if archetype == "inside_forward":  # cuts inside onto his stronger foot
            left = 1 - left if role in ("LW", "RW") else left
        foot = "left" if rng.random() < left else "right"
        return cls(synthetic_name(rng), foot, attributes, traits, archetype, round(quality, 3))

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
        hold. No study measures either directly. The foot's range is set so an average player
        kills the 12 to 15 m/s a typical professional pass arrives at (passes leave the foot at
        about 16 m/s; arXiv 2210.16474); *design*, *verify*."""
        if hands:
            return 16.0 + 12.0 * self["handling"]
        return FOOT_ABSORB_MPS[0] + FOOT_ABSORB_MPS[1] * self["first_touch"]

    # ---- A3: execution -------------------------------------------------------
    def kick_error(self, skill: str, speed: float, pressure: float, capacity: float,
                   weak_foot: bool, turn_deg: float = 0.0) -> tuple[float, float, float]:
        """Standard deviations of a kick's direction (degrees), speed (share) and launch angle
        (degrees). Average skill on the preferred foot at penalty speed, struck the way he faces,
        gives about 3 degrees; error grows with speed, pressure (less for the composed), fatigue,
        the angle across his body, and the weaker foot (the sourced 27% at an average weak foot)."""
        sigma = KICK_ERROR_DEG * (1.6 - 1.2 * self[skill]) * (speed / KICK_REF_SPEED)
        sigma *= 1 + 0.5 * pressure * (1 - self["composure"])
        sigma *= 1 + FATIGUE_ERROR * (1 - capacity)
        sigma *= 1 + TURN_ERROR * min(abs(turn_deg), 180.0) / 180.0
        if weak_foot:
            sigma *= 1 + (WEAK_FOOT_ERROR - 1) * 2 * (1 - self["weak_foot"])
        return sigma, SPEED_ERROR * (1 + pressure * (1 - self["composure"])), LOFT_ERROR_DEG

    def strike_error(self, skill: str, speed: float, nearest_opponent_m: float, capacity: float,
                     turn_deg: float, header: bool = False) -> tuple[float, float, float, float]:
        """The kick error of a strike in the situation it is struck in, one definition for the kick
        (engine.execute) and the striker's own estimate of it (decisions.pass_confidence):
        (direction SD in degrees, speed SD as a share, launch-angle SD in degrees, the share of the
        intended speed he gets off that foot). Pressure from the nearest opponent; the foot from
        the kick's direction against the way he faces (`turn_deg`). A `header` (P17) is met with the
        head, which turns to the ball, so no foot and no angle across the body; its direction and
        height are HEADER_ERROR times less precise."""
        pressure = min(1.0, max(0.0, (PRESSURE_M - nearest_opponent_m) / PRESSURE_M))
        if header:
            dir_sd, speed_sd, loft_sd = self.kick_error(skill, speed, pressure, capacity, False)
            return dir_sd * HEADER_ERROR, speed_sd, loft_sd * HEADER_ERROR, 1.0
        weak = (turn_deg > WEAK_SIDE_DEG) if self.foot == "right" else (turn_deg < -WEAK_SIDE_DEG)
        dir_sd, speed_sd, loft_sd = self.kick_error(skill, speed, pressure, capacity, weak, turn_deg)
        return dir_sd, speed_sd, loft_sd, self.weak_foot_speed() if weak else 1.0

    def weak_foot_speed(self) -> float:
        """Share of his usual speed off the weaker foot: the sourced 88% at an average weak foot."""
        return 1 - (1 - WEAK_FOOT_SPEED) * 2 * (1 - self["weak_foot"])
