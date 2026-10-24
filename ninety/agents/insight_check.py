"""The code half of the fact-checking agent for insight claims: what the phone says about a match.

An insight claim is one sentence citing insight facts (ninety/intel/insights.py), team-shape facts
or detected events by id. Its text is for a fan, so it names clubs and players the way a fan
hears them ("Oakfield", "Tomas Varick", "Oakfield's left-back"), never "home", "away" or a track id.
It passes only if (docs/GROUNDING.md I7):

- it cites at least one id, and every id is known;
- every number is a cited fact's value, or one of its `also` numbers, written with that number's
  unit (or a word for it: "4 Fenwick players" for 4 `opponents`), or a cited minute or clock. The
  reader is the fact-checker's own (factcheck.spelled_as_digits, factcheck.NUMBER), so a number
  spelled in words or glued to its unit is read too (lessons 129, 130, 151);
- the first club it names is the side of a cited fact, so a claim cannot hand one team's line
  break, overload or counter-press to the other; every club it names plays in the match;
- every player it names is a cited fact's passer, receiver or presser by his team-sheet name,
  every position it names one of theirs; a name or position that is right but said below its
  measured gate is held, not rejected (ninety/intel/roles.py);
- a word that says what kind of insight it is (an overload, a line break, a counter-press, open
  options) cites a fact of that kind;
- it uses no "home"/"away" team words and no track ids.

`gate` then holds (does not reject) a claim on a fact that is not confident, or on a detected event
below the detector's floor (factcheck.MIN_CONFIDENCE): it may be right, but it does not air.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping

from ninety.agents.factcheck import (
    CLOCK,
    MIN_CONFIDENCE,
    MINUTE_NUMBER,
    NUMBER,
    PLAYER,
    Claim,
    Verdict,
    _normalize_clock,
    shape_reasons,
    spelled_as_digits,
)
from ninety.intel.teamsheet import LABEL

# The words a unit may be written as. A count of opponents is of players; seconds may be "s".
UNIT_WORDS = {
    "opponents": ("opponents", "opponent", "players", "player", "men", "man"),
    "players": ("players", "player", "men", "man"),
    "extra players": (
        "extra players",
        "extra player",
        "more players",
        "more player",
        "extra men",
        "extra man",
        "players more",
        "spare players",
        "spare player",
    ),
    "teammates": tuple(
        f"{a}{w}"
        for a in ("", "open ")
        for w in (
            "teammates",
            "teammate",
            "team-mates",
            "team-mate",
            "options",
            "option",
            "players",
            "player",
        )
    ),
    "s": ("s", "seconds", "second", "secs", "sec"),
    "passes": ("passes", "pass"),
    "%": ("%", "percent", "per cent"),
    "crosses": ("crosses", "cross", "times", "time"),
    "times": ("times", "time"),
    "turnovers": ("turnovers", "turnover", "times"),
    "regains": ("regains", "regain", "times"),
    "overloads": ("overloads", "overload", "times"),
    "m": ("m", "metres", "metre", "meters", "meter"),
    "m²": ("m²", "m2", "square metres", "square meters"),
}
# What a word says the claim is about (case-insensitive, whole words). The lists are design: the
# plain words fans and pundits use for each insight.
KIND_WORDS = {
    "one_two": r"one[- ]twos?|wall pass\w*",
    "counter": r"counter[- ]attack\w*|on the break",
    "overload": (
        r"overload\w*|outnumber\w*|numbers? up|numerical (?:advantage|superiority)|extra (?:man|men|player)"
    ),
    "line_break": (
        r"bypass\w*|line[- ]break\w*|broke (?:the|their) lines?|breaks? (?:the|their) lines?"
        r"|cut through|took out|taking out|packing"
    ),
    "counter_press": (
        r"counter[- ]?press\w*|gegenpress\w*|won (?:it|the ball) back|wins? (?:it|the ball) back|regain\w*"
    ),
    "pass_options": (
        r"open (?:team-?mates?|options?|players?|men)|unmarked|free (?:man|men|team-?mates?)"
        r"|passing options?|nobody (?:was )?open"
    ),
}
# Every answer and card is also spoken (screen readers, the Describer): a sentence that leans on the
# drawing ("see the arrow") says nothing to a fan who cannot see it.
VISUAL_WORD = re.compile(
    r"\b(?:see|look at|as shown|shown (?:here|above|below)|highlighted|on (?:the )?screen"
    r"|the (?:arrow|circle|dot|dots|box|shading|map)|in (?:red|blue|yellow|green))\b",
    re.I,
)
TEAM_WORD = re.compile(
    r"\b(?:home|away)\s+(?:team|side|club|players?|defen\w+|keeper)\b|\b(?:home|away)'s\b|^\s*(?:home|away)\b",
    re.I,
)


def _num(x: float) -> str:
    return str(int(x)) if float(x).is_integer() else str(x)


def _pairs(facts: Iterable[Mapping]) -> set[tuple[float, str, str | None]]:
    """Each number a fact states: (value, unit, context). A context is a pattern the words just
    before the number must match ("against " for the other side's players, "within " for the
    counter-press window): a number written in a context may stand only for a number of that context,
    and a number of a context only where it is written in it, so "5 seconds" cannot be the window
    when the sentence says it was the regain."""
    out = set()
    for f in facts:
        if f.get("value") is not None and f.get("unit"):
            out.add((float(f["value"]), f["unit"], None))
        for item in f.get("also") or ():
            n, unit, context = (*item, None)[:3]
            if n is not None:
                out.add((float(n), unit, context))
    return out


def _people(facts: Iterable[Mapping], people: Mapping[str, Mapping]) -> list[Mapping]:
    """The players the cited facts are about, as `roles.who` describes them."""
    ids = []
    for f in facts:
        ids += [f.get(k) for k in ("passer", "receiver", "player")]
        ids += f.get("players") or []
    return [people[i] for i in ids if i and i in people]


def check(
    claim: Claim,
    known: Mapping[str, Mapping],
    clubs: Mapping[str, str],
    people: Mapping[str, Mapping] | None = None,
    sheet_names: Iterable[str] = (),
) -> Verdict:
    """The code checks (see the module docstring). `clubs` maps team to club name; `people` maps a
    track id to its `roles.who` record; `sheet_names` is every name on both team sheets."""
    people = people or {}
    reasons: list[str] = []
    held: list[str] = []
    if not claim.evidence:
        reasons.append("cite at least one fact id as evidence")
    missing = [i for i in claim.evidence if i not in known]
    if missing:
        reasons.append(f"unknown fact ids: {', '.join(missing)}")
    cited = [known[i] for i in claim.evidence if i in known]
    text = spelled_as_digits(claim.text)

    # Team words and ids: a fan hears clubs and names.
    if TEAM_WORD.search(claim.text):
        reasons.append("name the club, never home or away")
    if VISUAL_WORD.search(claim.text):
        reasons.append(
            f"'{VISUAL_WORD.search(claim.text).group()}' needs the picture: say it in words, it is spoken"
        )
    for tid in sorted(set(PLAYER.findall(claim.text))):
        reasons.append(f"{tid} is an id: name the player or his position")

    # Clubs. A club written straight after a number is what was counted ("6 Fenwick players"): for
    # a line break that is the opponents. The first club named otherwise is who acted, and must be
    # the side of a cited fact, so a claim cannot hand one team's insight to the other.
    names = {name: team for team, name in clubs.items()}
    named = sorted((m.start(), m.group()) for n in names for m in re.finditer(rf"\b{re.escape(n)}\b", text))
    sides = {f.get("team") for f in cited if f.get("team")}
    counted = [(at, n) for at, n in named if re.search(rf"{NUMBER.pattern}\s+$", text[:at])]
    actors = [(at, n) for at, n in named if (at, n) not in counted]
    if actors and sides and names[actors[0][1]] not in sides:
        reasons.append(
            f"{actors[0][1]} is not the side of the cited facts "
            f"({', '.join(clubs[s] for s in sorted(sides))})"
        )
    breaks = {f.get("team") for f in cited if f.get("kind") == "line_break"}
    for _, n in counted:
        if breaks and names[n] in breaks and len(breaks) == 1:
            reasons.append(f"a line break counts opponents: {n} is the passing side")

    # Numbers: a cited fact's number with its unit, a cited minute, or a cited clock.
    pairs = _pairs(cited)
    clocks = {_normalize_clock(f["clock"]) for f in cited if f.get("clock")}
    for m in CLOCK.finditer(text):
        if _normalize_clock(m.group("clock")) not in clocks:
            reasons.append(f"clock {m.group('clock')} is not a cited clock")
    clock_spans = [range(m.start(), m.end()) for m in CLOCK.finditer(text)]
    minutes = {
        float(f[k]) for f in cited for k in ("minute", "minute_from", "minute_to") if f.get(k) is not None
    }
    minute_at = {}
    for m in MINUTE_NUMBER.finditer(text):
        group = next(g for g in m.groups() if g is not None)
        minute_at[m.start() + m.group(0).find(group)] = float(group)
    clubs_re = "|".join(re.escape(n) for n in names) or "(?!)"
    for m in NUMBER.finditer(text):
        if any(m.start() in span for span in clock_spans):
            continue
        value = float(m.group("n"))
        if m.start() in minute_at:
            if value not in minutes:
                reasons.append(f"minute {m.group('n')} is not a cited minute")
            continue
        after, before = text[m.end() :], text[: m.start()]
        contexts = {c for _, _, c in pairs if c and re.search(c, before, re.I)}
        ok = False
        for v, unit, context in pairs:
            if v != value or (context in contexts if contexts else context is None) is False:
                continue
            words = "|".join(re.escape(w) for w in UNIT_WORDS.get(unit, (unit,)))
            if re.match(rf"\s*(?:(?:{clubs_re})\s+)?(?:{words})(?!\w)", after, re.I):
                ok = True
                break
        if not ok:
            reasons.append(f"number {m.group('n')} is not a cited fact's number with its unit")

    # Players and positions.
    about = _people(cited, people)
    said_names = {w["name"] for w in about if w.get("name")}
    unsure_names = {w["sheet_name"] for w in about if w.get("sheet_name") and not w.get("name")}
    for name in sorted(set(sheet_names)):
        if not re.search(rf"\b{re.escape(name)}\b", claim.text):
            continue
        if name in said_names:
            continue
        if name in unsure_names:
            held.append(f"{name} is said below the name gate: name him by his position")
        else:
            reasons.append(f"{name} is not a player of the cited facts")
    said_positions = {w["position"] for w in about if w.get("position")}
    unsure_positions = {LABEL[w["role"]] for w in about if w.get("role") and not w.get("position")}
    for label in sorted(set(LABEL.values()), key=len, reverse=True):
        if not re.search(rf"\b{re.escape(label)}\b", claim.text, re.I):
            continue
        if label in said_positions:
            continue
        if label in unsure_positions:
            held.append(f"{label} is said below the position gate")
        else:
            reasons.append(f"no cited player is the {label}")

    # Team shape: the shape fact-checker's own rules (#228), with the clubs read as its team words.
    shape_text = text
    for team, name in clubs.items():
        shape_text = re.sub(rf"\b{re.escape(name)}\b", team, shape_text)
    reasons += shape_reasons(shape_text, list(cited))

    # Kind words.
    kinds = {f.get("kind") for f in cited}
    for kind, words in KIND_WORDS.items():
        if re.search(rf"\b(?:{words})\b", claim.text, re.I) and kind not in kinds:
            reasons.append(f"'{kind.replace('_', ' ')}' needs a cited {kind} fact")

    if reasons:
        return Verdict(ok=False, reasons=reasons)
    if held:
        return Verdict(ok=False, reasons=held, category="low_confidence")
    return Verdict(ok=True)


def gate(claim: Claim, known: Mapping[str, Mapping], min_confidence: float = MIN_CONFIDENCE) -> Verdict:
    """Holds a claim on an unsure fact: its bounds disagree, or its detected event is below the floor."""
    reasons = []
    for i in claim.evidence:
        f = known.get(i)
        if f is None:
            continue
        if f.get("confident") is False:
            reasons.append(
                f"{i} is not confident (tracked {f.get('tracked')}, bounds {f.get('lo')} to {f.get('hi')})"
            )
        c = f.get("event_confidence", f.get("confidence"))
        if c is not None and c < min_confidence:
            reasons.append(f"{i} rests on a detection at confidence {c:.2f}, below {min_confidence:.2f}")
    return Verdict(ok=not reasons, reasons=reasons, category="low_confidence" if reasons else None)


def verify(claim: Claim, known, clubs, people=None, sheet_names=()) -> Verdict:
    """The code checks, then the gate: a wrong claim is rejected before an unsure one is held."""
    v = check(claim, known, clubs, people, sheet_names)
    if not v.ok:
        return v
    return gate(claim, known)


__all__ = ["KIND_WORDS", "UNIT_WORDS", "check", "gate", "verify"]
