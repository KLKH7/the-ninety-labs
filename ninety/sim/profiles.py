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

from ninety.sim import ball, perception
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
# A3: where instep kicks from the penalty mark (11 m from the goal's centre, about 21 m/s) cross the
# goal line, at a target 1.6 m high just inside a post (Frontiers 2024, 16 players, Figure 2A): a
# tilted ellipse for each foot. Its 95% axes (straight kicks: 4.08 m by 1.91 m on the preferred foot,
# 5.60 m by 2.28 m on the weaker) are 2.448 SDs each way (chi-square, 2 dof: assumed; the paper fits
# a bivariate normal but does not say how it scales the ellipse); its long axis lies 26.9 and 29.4
# degrees from horizontal (Figure 5's straight-kick medians, read from the figure's pixels).
# Projected across and up and down at the target (design: its edge at the post, 3.5 m from the
# centre). Across, seen from the kicking point, that is about 3.6 degrees on the preferred foot. Up
# and down, the measured spread already holds all of a kick's errors, the struck speed's among them
# (a slower ball drops more), so the launch angle's spread is what is left once the engine's own
# speed spread (SPEED_ERROR) has taken its share, both through the ball's own flight to the target:
# about 2.3 degrees on the preferred foot. The weaker foot follows its own ellipse the same way
# (about 1.34 across, 1.45 up and down), derived at the preferred foot's reference speed although the
# weaker foot strikes slower (design). Both grow the same way with the strike (design: one ellipse,
# scaled).
KICK_ELLIPSE_95_M = {"preferred": (4.08, 1.91), "weaker": (5.60, 2.28)}
KICK_ELLIPSE_TILT_DEG = {"preferred": 26.9, "weaker": 29.4}
KICK_REF_DIST_M = 11.0
KICK_TARGET_M = (3.5, 1.6)  # across from the goal's centre, and high
KICK_REF_SPEED = 21.0
SPEED_ERROR = 0.06  # design: spread of struck speed, as a share
FRAME_S = 1 / 25  # the engine's frame (engine.DT), for the ball's flight below


def _ellipse_sds_m(foot: str) -> tuple[float, float]:
    """(across, up and down) SD in metres of a foot's measured ellipse on the goal's plane."""
    long_sd, short_sd = (a / 2 / 2.448 for a in KICK_ELLIPSE_95_M[foot])
    tilt = math.radians(KICK_ELLIPSE_TILT_DEG[foot])
    return (math.hypot(long_sd * math.cos(tilt), short_sd * math.sin(tilt)),
            math.hypot(long_sd * math.sin(tilt), short_sd * math.cos(tilt)))


def _height_at_target(launch: float, speed: float, ground_m: float) -> float:
    """How high the ball is when it has flown `ground_m` along the ground (drag and gravity)."""
    path = ball.predict((0.0, 0.0, 0.0, speed * math.cos(launch), 0.0, speed * math.sin(launch)),
                        FRAME_S, 3.0)
    for a, b in zip(path, path[1:], strict=False):
        if a[0] <= ground_m <= b[0]:
            return a[2] + (ground_m - a[0]) / (b[0] - a[0]) * (b[2] - a[2])
    raise ValueError("the ball does not reach the target")


# Five-point Gauss-Hermite rule for a standard normal (exact for polynomials up to degree 9): nodes 0,
# +-sqrt(5 - sqrt(10)), +-sqrt(5 + sqrt(10)); weights 8/15 and (7 +- 2 sqrt(10)) / 60.
_GH_NODES = (0.0, math.sqrt(5 - math.sqrt(10)), -math.sqrt(5 - math.sqrt(10)),
             math.sqrt(5 + math.sqrt(10)), -math.sqrt(5 + math.sqrt(10)))
_GH_WEIGHTS = (8 / 15, (7 + 2 * math.sqrt(10)) / 60, (7 + 2 * math.sqrt(10)) / 60,
               (7 - 2 * math.sqrt(10)) / 60, (7 - 2 * math.sqrt(10)) / 60)


def _height_sd(launch: float, speed: float, ground_m: float, launch_sd: float) -> float:
    """SD of the ball's height at the target when its launch angle scatters by `launch_sd` (radians)
    and its struck speed by SPEED_ERROR, each independently, through the ball's own flight."""
    first = second = 0.0
    for a, wa in zip(_GH_NODES, _GH_WEIGHTS, strict=True):
        for v, wv in zip(_GH_NODES, _GH_WEIGHTS, strict=True):
            h = _height_at_target(launch + launch_sd * a, speed * (1 + SPEED_ERROR * v), ground_m)
            first += wa * wv * h
            second += wa * wv * h * h
    return math.sqrt(max(second - first * first, 0.0))


def _ellipse_sds_deg(foot: str) -> tuple[float, float]:
    """(across, launch angle) SD in degrees that reproduce a foot's measured ellipse at the target.
    Across: a metre there is cos^2 of its bearing over 11 m of angle. Up and down: the ball's height
    at the target moves with its launch angle and with its speed, so the launch angle's spread is the
    one that, with the engine's speed spread, gives the measured spread through the ball's own flight
    (exactly, by quadrature over both, not linearised: height is not linear in speed)."""
    across_m, up_m = _ellipse_sds_m(foot)
    y, z = KICK_TARGET_M
    ground = math.hypot(KICK_REF_DIST_M, y)
    across = math.degrees(across_m * (KICK_REF_DIST_M / ground) ** 2 / KICK_REF_DIST_M)
    forward, rise = ball.shot(ground, KICK_REF_SPEED, z, FRAME_S)
    launch, speed = math.atan2(rise, forward), math.hypot(forward, rise)
    if _height_sd(launch, speed, ground, 0.0) >= up_m:
        raise ValueError("SPEED_ERROR alone spreads the ball wider than the measured vertical (A3)")
    launch_sd = ball._bisect(lambda sd: _height_sd(launch, speed, ground, sd), 0.0, 0.2, up_m, rounds=40)
    return across, math.degrees(launch_sd)


KICK_ERROR_DEG, LOFT_ERROR_DEG = _ellipse_sds_deg("preferred")  # about 3.6 and 2.3
# A3: the weaker foot's own ellipse against the preferred one's, across and up and down ...
WEAK_FOOT_ERROR = tuple(w / p for w, p in zip(_ellipse_sds_deg("weaker"), (KICK_ERROR_DEG, LOFT_ERROR_DEG),
                                                strict=True))
WEAK_FOOT_SPEED = 0.88  # A3: ... and about 12% slower
FATIGUE_ERROR = 0.25  # A3: design, *verify*: about 25% wider when the slow store (P10) is spent
FOOT_ABSORB_MPS = (12.0, 12.0)  # A4: a first touch kills 12 m/s plus 12 m/s more at full first-touch skill
READ_ERROR_M = 1.5  # design: spread of a keeper's read of a shot's aim, at average anticipation
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
        gives the measured spread, about 3.6 degrees across and 2.3 of launch angle; both grow alike
        with speed, pressure (less for the composed), fatigue and the angle across his body, and on
        the weaker foot follow its own measured ellipse (at an average weak-foot rating)."""
        scale = (1.6 - 1.2 * self[skill]) * (speed / KICK_REF_SPEED)
        scale *= 1 + 0.5 * pressure * (1 - self["composure"])
        scale *= 1 + FATIGUE_ERROR * (1 - capacity)
        scale *= 1 + TURN_ERROR * min(abs(turn_deg), 180.0) / 180.0
        across, up = KICK_ERROR_DEG * scale, LOFT_ERROR_DEG * scale
        if weak_foot:  # the measured weaker foot at an average weak-foot rating, more or less either side
            across *= 1 + (WEAK_FOOT_ERROR[0] - 1) * 2 * (1 - self["weak_foot"])
            up *= 1 + (WEAK_FOOT_ERROR[1] - 1) * 2 * (1 - self["weak_foot"])
        return across, SPEED_ERROR * (1 + pressure * (1 - self["composure"])), up

    def strike_error(self, skill: str, speed: float, nearest_opponent_m: float, capacity: float,
                     turn_deg: float) -> tuple[float, float, float, float]:
        """The kick error of a strike in the situation it is struck in, one definition for the kick
        (engine.execute) and the striker's own estimate of it (decisions.pass_confidence):
        (direction SD in degrees, speed SD as a share, launch-angle SD in degrees, the share of the
        intended speed he gets off that foot). Pressure from the nearest opponent; the foot from
        the kick's direction against the way he faces (`turn_deg`)."""
        pressure = min(1.0, max(0.0, (PRESSURE_M - nearest_opponent_m) / PRESSURE_M))
        weak = (turn_deg > WEAK_SIDE_DEG) if self.foot == "right" else (turn_deg < -WEAK_SIDE_DEG)
        dir_sd, speed_sd, loft_sd = self.kick_error(skill, speed, pressure, capacity, weak, turn_deg)
        return dir_sd, speed_sd, loft_sd, self.weak_foot_speed() if weak else 1.0

    def weak_foot_speed(self) -> float:
        """Share of his usual speed off the weaker foot: the sourced 88% at an average weak foot."""
        return 1 - (1 - WEAK_FOOT_SPEED) * 2 * (1 - self["weak_foot"])
