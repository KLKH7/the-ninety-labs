"""Fictional clubs and their team sheets: what a fan is told a team and a player are called.

The renderer gives each clip two fictional three-letter codes for the score bug (ninety/render/
params.TEAM_CODES). Each code here has a fictional club name, and each club a team sheet for a
match: eleven starters, each with a name, a shirt number and a position in the 4-3-3 the engine
plays (rules 4.4 and 4.7: no real club, player, kit or crest). London Athletic and Lisbon Esportes
are fictional clubs named after real cities (Kian's choice, Oct 24): the cities are real, the clubs,
their players, kits and crests are not. The sheet is drawn from the match's
seed and the club's code, so the same match always has the same names, and it is the kind of
thing a broadcaster has before kick-off: it says who plays where, never where anyone is.

Which tracked player is which name is not on the sheet: vision infers it from where each track
stands in its team's shape (ninety/intel/roles.py), with a confidence, and the fact-checker says
a name only when that confidence is high enough (ninety/agents/insight_check.py).

Surnames are built from syllables, not taken from a list of people, so they are invented names.
"""

from __future__ import annotations

import random
from dataclasses import asdict, dataclass

# One fictional club per renderer code (ninety/render/params.TEAM_CODES), the names every screen
# shows (web/viewer/src/teams.ts CLUBS): tests hold all three equal.
CLUBS = {
    "ASH": "Ashvale",
    "CRW": "Crowmere",
    "DUN": "Dunhollow",
    "ELM": "Elmwick",
    "FEN": "Lisbon Esportes",
    "GRV": "Grovely",
    "HLT": "Holtmoor",
    "IVY": "Ivydale",
    "KST": "Kestwood",
    "MRL": "Merlton",
    "OAK": "London Athletic",
    "QRY": "Quarrydale",
    # The broadcast's new scorebug codes for the same two clubs (the renderer moves OAK and FEN to
    # LON and LIS): both spellings name one club.
    "LON": "London Athletic",
    "LIS": "Lisbon Esportes",
}


def possessive(name: str) -> str:
    """A name's possessive as a broadcaster writes it: "London Athletic's", and a plural-looking name
    ending in s takes the apostrophe alone, "Lisbon Esportes'" (never "Lisbon Esportes's")."""
    return f"{name}'" if name.endswith("s") else f"{name}'s"
# The 4-3-3 the engine plays (ninety/sim/engine.FORMATION, the same role codes; tests hold them
# equal): role code, shirt number (the common squad numbering of a 4-3-3, *design*), what a fan calls
# it, and its line.
POSITIONS = (
    ("GK", 1, "goalkeeper", "goalkeeper"),
    ("RB", 2, "right-back", "defender"),
    ("RCB", 4, "right centre-back", "defender"),
    ("LCB", 5, "left centre-back", "defender"),
    ("LB", 3, "left-back", "defender"),
    ("RCM", 8, "right-sided midfielder", "midfielder"),
    ("CM", 6, "holding midfielder", "midfielder"),
    ("LCM", 10, "left-sided midfielder", "midfielder"),
    ("RW", 7, "right winger", "forward"),
    ("ST", 9, "striker", "forward"),
    ("LW", 11, "left winger", "forward"),
)
ROLES = tuple(p[0] for p in POSITIONS)
LABEL = {p[0]: p[2] for p in POSITIONS}
LINE = {p[0]: p[3] for p in POSITIONS}
FIRST = (
    "Alex",
    "Ben",
    "Callum",
    "Dan",
    "Eli",
    "Femi",
    "Gabe",
    "Hugo",
    "Isaac",
    "Jonah",
    "Kai",
    "Leo",
    "Marco",
    "Nico",
    "Owen",
    "Rafa",
    "Sami",
    "Theo",
    "Tomas",
    "Yusuf",
    "Zane",
    "Ilya",
    "Mateo",
    "Ravi",
)
ONSET = ("Br", "C", "D", "F", "G", "H", "K", "L", "M", "N", "P", "R", "S", "T", "V", "W", "Th", "St")
VOWEL = ("a", "e", "i", "o", "u", "ai", "ou")
CODA = ("ndell", "rrow", "lby", "nton", "vick", "mble", "sker", "ddon", "rrick", "lmore", "nnet", "ssop")


@dataclass(frozen=True)
class Starter:
    club: str
    role: str
    number: int
    name: str
    position: str  # what a fan calls the role
    line: str


# Short names for a score line, where they differ from the full name (Kian, Oct 24).
SHORT = {"OAK": "London", "FEN": "Lisbon", "LON": "London", "LIS": "Lisbon"}


def short_name(code: str) -> str:
    return SHORT.get(code) or club_name(code)


def club_name(code: str) -> str:
    if code not in CLUBS:
        raise ValueError(f"unknown club code {code!r}")
    return CLUBS[code]


def _surname(rng: random.Random) -> str:
    return rng.choice(ONSET) + rng.choice(VOWEL) + rng.choice(CODA)


def team_sheet(seed: int, code: str) -> tuple[Starter, ...]:
    """The eleven starters of club `code` in the match of `seed`, in POSITIONS order."""
    club = club_name(code)
    rng = random.Random(f"teamsheet-{seed}-{club}")  # by name: a club's two codes give one team sheet
    names: set[str] = set()
    out = []
    for role, number, label, line in POSITIONS:
        while True:
            name = f"{rng.choice(FIRST)} {_surname(rng)}"
            if name.split()[1] not in {n.split()[1] for n in names}:
                break
        names.add(name)
        out.append(Starter(club, role, number, name, label, line))
    return tuple(out)


@dataclass(frozen=True)
class Fixture:
    """The two clubs of a served match: which plays as home (attacks toward x = 105) and away."""

    seed: int
    home_code: str
    away_code: str

    @property
    def clubs(self) -> dict[str, str]:
        return {"home": club_name(self.home_code), "away": club_name(self.away_code)}

    def sheet(self, team: str) -> tuple[Starter, ...]:
        return team_sheet(self.seed, self.home_code if team == "home" else self.away_code)

    def as_dict(self) -> dict:
        return {
            "clubs": self.clubs,
            "codes": {"home": self.home_code, "away": self.away_code},
            "sheets": {team: [asdict(s) for s in self.sheet(team)] for team in ("home", "away")},
        }


__all__ = [
    "CLUBS",
    "SHORT",
    "short_name",
    "LABEL",
    "LINE",
    "POSITIONS",
    "ROLES",
    "Fixture",
    "Starter",
    "club_name",
    "team_sheet",
]
