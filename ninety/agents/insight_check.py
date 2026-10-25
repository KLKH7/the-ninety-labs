"""The code half of the fact-checking agent for insight claims: what the phone says about a match.

An insight claim is one sentence citing insight facts (ninety/intel/insights.py), team-shape facts
or detected events by id. Its text is for a fan, so it names clubs and players the way a fan
hears them ("London Athletic", "Tomas Varick", "London Athletic's left-back"), never "home",
"away" or a track id.
It passes only if (docs/GROUNDING.md I7):

- it cites at least one id, and every id is known;
- every number is a cited fact's value, or one of its `also` numbers, written with that number's
  unit (or a word for it: "4 Lisbon Esportes players" for 4 `opponents`), or a cited minute or clock. The
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
    "shots": ("shots", "shot"),
    "degrees": ("degrees", "degree"),
    "m²": ("m²", "m2", "square metres", "square meters"),
}
# What a word says the claim is about (case-insensitive, whole words). The lists are design: the
# plain words fans and pundits use for each insight.
UNSOURCED = r"counter[- ]?attack\w*|on the break|break(?:s|ing)? at speed|fast break\w*"
REGAIN = r"won (?:it|the ball) back|wins? (?:it|the ball) back|regain\w*"
# A word another kind's facts also say: a counter-attack starts with a regain (GROUNDING I12, I4), so
# "won the ball back" is a cited counter fact's own words too.
ALSO_SAID_BY = {"counter_press": (REGAIN, {"counter"})}
KIND_WORDS = {
    "one_two": r"one[- ]twos?|wall pass\w*",
    "overload": (
        r"overload\w*|outnumber\w*|numbers? up|numerical (?:advantage|superiority)|extra (?:man|men|player)"
    ),
    "line_break": (
        r"bypass\w*|line[- ]break\w*|broke (?:the|their) lines?|breaks? (?:the|their) lines?"
        r"|cut through|took out|taking out|packing"
    ),
    "counter_press": rf"counter[- ]?press\w*|gegenpress\w*|{REGAIN}",
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
# A call on an offside, in the past tense a reading is told in (the Law's own summaries say "is in
# an offside position if…", which calls nothing). The cited reading's verdict must be the call.
VERDICT_WORDS = (
    (
        "offside",
        re.compile(r"\bwas (?:in an offside position|offside)\b|\bbeyond the (?:offside )?line\b", re.I),
    ),
    ("onside", re.compile(r"\bwas onside\b|\bonside by\b|\bwas(?:n't| not) offside\b", re.I)),
    ("too_close", re.compile(r"\btoo close\b", re.I)),
)
# Words that say which way a fact went, checked against the fact's own fields (polarity): whether
# a turnover was won back (`regained`, or a summary's regains), whether a pass was lost (`outcome`),
# whether it went to an open teammate (`target_open`), and whether anyone was open at all (`value`).
NEVER_WON = re.compile(
    r"\b(?:never|didn't|did not|couldn't|could not|failed to|unable to)\s+(?:won|win)\s+"
    r"(?:it|the ball|possession)\s+back\b"
    r"|\bwithout (?:winning|getting) (?:it|the ball) back\b|\bnot (?:won|regained)\b"
    r"|\b(?:never|didn't|did not|couldn't|could not|failed to|unable to)\s+(?:regain|recover|get)\w*\b"
    r"|\b(?:no|zero|not a single)\s+regains?\b",
    re.I,
)
WON_BACK = re.compile(
    r"\b(?:won|win|wins|winning|got|gets)\s+(?:it|the ball|possession)\s+back\b|\bregain(?:ed|s)?\b", re.I
)
NONE_OPEN = re.compile(
    r"\bno(?:body)?\s+(?:(?:open|free)\s+)?(?:teammates?|options?|one)\b|\bnobody\s+(?:was\s+)?(?:open|free)\b"
    r"|\bnot (?:a|any) (?:teammates?|options?)\b",
    re.I,
)
ELSEWHERE = re.compile(
    r"\bwent elsewhere\b|\binstead\b|\bignored\b|\bmissed (?:an?|the) (?:open|free)\b"
    r"|\bdid(?:n't| not) (?:use|find|pick)\b",
    re.I,
)
TO_OPEN = re.compile(
    r"\b(?:found|picked out|to|played in|reached)\s+(?:an?|the)\s+(?:open|free|unmarked)\s+"
    r"(?:teammate|team-mate|man|player)\b",
    re.I,
)
LOST = re.compile(
    r"\blost (?:the ball|it|the pass|a pass|possession)\b|\bwas lost\b|\bgave (?:it|the ball) away\b"
    r"|\bmisplaced\b|\bgiven away\b",
    re.I,
)
COMPLETED = re.compile(
    r"\bcompleted\b|\bfound (?:a|his|their|a) (?:teammate|team-mate|man)\b|\bkept (?:it|the ball)\b", re.I
)
NONE_OF = re.compile(
    r"\b(?:no|zero|not a single)\s+(overloads|crosses|turnovers|regains|line breaks)\b", re.I
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

    # Clubs. A club written straight after a number is what was counted ("6 Lisbon Esportes players"): for
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
    # A cited team-sheet row says who plays where (never where anyone is): its name with its position.
    rows = [f for f in cited if f.get("kind") == "sheet"]
    if rows and len(rows) == len(cited):
        # Only a sentence of sheet rows alone: cited beside a moment, a row would vouch its name for
        # whoever the moment is about (the goalkeeper's name on another player's pass).
        about += [{"name": f["name"], "position": f["position"]} for f in rows]
    for f in rows:
        for other in rows:
            if other is not f and re.search(
                rf"\b{re.escape(f['name'])}\b[^.;]*?\b{re.escape(other['position'])}\b", claim.text, re.I
            ) and not re.search(
                rf"\b{re.escape(f['name'])}\b[^.;]*?\b{re.escape(f['position'])}\b", claim.text, re.I
            ):
                reasons.append(
                    f"{f['name']} is the {f['position']} on the team sheet, not the {other['position']}"
                )
    # A fact about two players (a one-two, a pass) said with one of them twice and the other never:
    # whatever joins the two mentions ("X and X", "X played it to X and back").
    for f in cited:
        a, b = f.get("passer"), f.get("receiver")
        if not a or not b or a == b:
            continue
        na, nb = (people.get(t, {}).get("name") or people.get(t, {}).get("sheet_name") for t in (a, b))
        if not na or not nb or na == nb:
            continue
        for one, other in ((na, nb), (nb, na)):
            if len(re.findall(rf"\b{re.escape(one)}\b", claim.text)) > 1 and not re.search(
                rf"\b{re.escape(other)}\b", claim.text
            ):
                reasons.append(f"{one} is said as two players")
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

    # Offside calls.
    verdicts = {f.get("verdict") for f in cited if f.get("kind") == "offside"}
    for verdict, words in VERDICT_WORDS:
        m = words.search(claim.text)
        if m and verdict not in verdicts:
            reasons.append(
                f"'{m.group()}' is a call the cited offside readings do not make "
                f"({sorted(verdicts) or 'none'})"
            )

    # Polarity: the words that say which way it went must agree with the cited facts' own fields.
    reasons += polarity_reasons(claim.text, cited)  # a known reversal: wrong, rejected
    # A direction cue the check cannot match to the fact: it may be right, but it is not affirmatively
    # matched, so it is held, never passed (the Coordinator's decision: fail closed).
    held += direction_reasons(
        claim.text, cited, clubs, [*sheet_names, *(w.get("say", "") for w in people.values())]
    )

    # No published definition with a time window was found for a counter-attack (GROUNDING I12), so
    # whatever is cited, a sentence never calls a regain that led to a shot one.
    if re.search(rf"\b(?:{UNSOURCED})\b", claim.text, re.I):
        reasons.append("'counter-attack' has no cited definition: say a regain that led to a shot")

    # Kind words.
    kinds = {f.get("kind") for f in cited}
    for kind, words in KIND_WORDS.items():
        if not re.search(rf"\b(?:{words})\b", claim.text, re.I) or kind in kinds:
            continue
        shared, others = ALSO_SAID_BY.get(kind, ("", set()))
        rest = claim.text
        if shared and kinds & others:
            rest = re.sub(rf"\b(?:{shared})\b", "", rest, flags=re.I)
        if re.search(rf"\b(?:{words})\b", rest, re.I):
            reasons.append(f"'{kind.replace('_', ' ')}' needs a cited {kind} fact")

    if reasons:
        return Verdict(ok=False, reasons=reasons)
    if held:
        return Verdict(ok=False, reasons=held, category="low_confidence")
    return Verdict(ok=True)


def polarity_reasons(text: str, cited: list[Mapping]) -> list[str]:
    """Why a sentence's direction disagrees with the cited facts: it says a turnover was (not) won
    back, a pass was lost or kept, it went (not) to an open teammate, nobody was open, or there were
    none of something, and the cited facts say the other."""
    out = []
    # The "why?" definition says what winning it back does; it claims no regain of its own.
    text = re.sub(r"winning the ball back within \d+ seconds of losing it", " ", text, flags=re.I)
    presses = [f for f in cited if f.get("kind") == "counter_press" and f.get("metric") == "pressers"]
    regains = [f for f in cited if f.get("metric") == "regains_within_5s"]
    passes = [f for f in cited if f.get("metric") == "open_teammates_ahead"]
    counters = [f for f in cited if f.get("metric") == "regain_to_shot_s"]  # each starts at a regain (I12)
    if presses or regains or counters:
        won = (
            any(f.get("regained") for f in presses) or any(f.get("value") for f in regains) or bool(counters)
        )
        if NEVER_WON.search(text):
            if won:
                out.append("it says the ball was not won back; the cited facts say it was")
        elif WON_BACK.search(text) and not won:
            out.append("it says the ball was won back; the cited facts say it was not")
    if passes:
        if NONE_OPEN.search(text) and any(f.get("value") for f in passes):
            out.append("it says nobody was open; the cited pass had open teammates")
        if ELSEWHERE.search(text) and not any(f.get("target_open") is False for f in passes):
            out.append("it says the pass missed an open teammate; the cited pass did not")
        if TO_OPEN.search(text) and not any(f.get("target_open") is True for f in passes):
            out.append("it says the pass found an open teammate; the cited pass did not")
        # "lost the ball" may be a cited turnover's, not the pass's: with a press fact cited too, it
        # is left to the closed check (which holds) rather than rejected.
        turnover = bool(presses or regains)
        if LOST.search(text) and not turnover and not any(f.get("outcome") == "fail" for f in passes):
            out.append("it says the pass was lost; the cited pass was completed")
        if COMPLETED.search(text) and not any(f.get("outcome") == "success" for f in passes):
            out.append("it says the pass was completed; the cited pass was lost")
    for m in NONE_OF.finditer(text):
        unit = m.group(1).lower()
        same = [
            f
            for f in cited
            if str(f.get("unit", "")).lower() == unit or unit.rstrip("s") in str(f.get("metric", ""))
        ]
        if any(f.get("value") for f in same):
            out.append(f"it says {m.group()}; the cited facts count some")
    return out


# Closed-world direction (the merge queue's reviews: a list of wrong phrasings fails open, and so did
# a list of direction words). For a fact whose direction matters, the sentence is taken apart: the
# phrases that state the fact's own direction (`_approved`), its numbers, the clubs, the players and
# positions, and a short list of glue words are removed. Any word left over is a word the check
# cannot vouch for, so the sentence is held, never passed, and code's own sentence airs instead. A
# true sentence in other words is held too: that is the cost of failing closed, and it is measured
# (tests/test_insight_check.py). A known reversal (`polarity_reasons`) is rejected. Only the
# metrics in DIRECTED are covered: any other fact's direction words are left to the Judge.
GLUE = frozenset(
    # No word here may carry direction (the merge queue's fifth review took out open, teammate,
    # again, all, each, one, only, away, straight and same, and its sixth "that was it" took out it,
    # this, that, so, also and just, and its seventh the pronouns, verbs, prepositions and pitch words
    # (they, had, was, with, to, ball, players, ahead, further, up)): a direction must come in the fact's own
    # phrases, or the sentence is held.
    """a an the and but then while of from for at in when after before both minute minutes time times
    second seconds s m moment his her there""".split()
)
DIRECTED = (
    "pressers",
    "regains_within_5s",
    "open_teammates_ahead",
    "passes_with_no_open_teammate_ahead",
    "extra_players",
    "overload_moments",
    "regain_to_shot_s",
    "possession_share",
    "final_third_share",
)
_N = r"\d+(?:\.\d+)?"


# Code's own sentences, clause by clause (ninety/agents/companion_match.code_texts, scout.WHY_TEXT and
# scout.where_spoken): with the glue list this short, a sentence code writes passes only because
# each of its clauses is a phrase of the fact it states.
_THIRD = r"in their (?:own|middle|final) third,? (?:in the centre|on the (?:left|right))"
_WHERE = r"it was (?:close to [\w ']+? goal|in [\w ']+? third|in midfield)(?: on the (?:near|far) side)?"
TEMPLATES = {
    "pressers": [
        rf"won the ball back {_N} seconds after losing it, with {_N} players? around it",
        rf"lost the ball and had {_N} players? near it in the next {_N} seconds",
        rf"winning the ball back within {_N} seconds of losing it stops the other side from breaking, and",
        rf"had {_N} players? near the ball",
    ],
    "regains_within_5s": [
        rf"lost the ball {_N} times? in open play",
        rf"and (?:never won it back|won it back once|won it back {_N} times) within {_N} seconds",
    ],
    "open_teammates_ahead": [
        r"lost the ball with no teammate free further up the pitch",
        rf"had {_N} teammates? free further up the pitch, but the pass went elsewhere and was lost",
        r"at the moment of that pass",
        rf"had {_N} open teammates? further forward",
    ],
    "passes_with_no_open_teammate_ahead": [rf"made {_N} pass(?:es)? with no open teammate further forward"],
    "extra_players": [
        rf"had {_N} players? against {_N} players? around the ball, {_THIRD}",
        rf"with {_N} players? against {_N} players? around the ball",
        r"had a spare player there",
    ],
    "overload_moments": [rf"built {_N} overloads?", rf"most often {_THIRD}"],
    "regain_to_shot_s": [rf"won the ball back and had a shot {_N} seconds later"],
    "possession_share": [rf"had {_N}% of possession", r"counted by passes as TV counts it"],
    "final_third_share": [
        r"the ball was in",
        rf"attacking third (?:{_N}%|between {_N}% and {_N}%) of the footage shown",
    ],
}


def _approved(f: Mapping) -> list[str]:
    """The phrases that state this fact's own direction, and the neutral ones its sentences use."""
    span = r"(?:from minute \d+ to minute \d+|in minute \d+)"  # when, in the words code writes it
    return [*TEMPLATES.get(f.get("metric"), ()), _WHERE, span, *_phrases(f)]


def _phrases(f: Mapping) -> list[str]:
    metric = f.get("metric")
    if metric == "pressers":
        out = [
            r"lost the ball",
            r"(?:after )?losing it",
            r"winning the ball back within \d+ seconds of losing it",
            rf"{_N} players? (?:near|around) (?:it|the ball)",
            rf"(?:sent )?{_N} players? (?:to )?press(?:ed|ing)?",
            r"pressed",
            rf"in the next {_N} seconds",
            rf"{_N} seconds (?:later|after losing it)",
            rf"within {_N} seconds",
        ]
        out += (
            [r"won (?:it|the ball) back"]
            if f.get("regained")
            else [r"(?:did not|didn't|never|could not|couldn't) (?:win|won|get|got) (?:it|the ball) back"]
        )
        return out
    if metric == "regains_within_5s":
        out = [r"lost the ball \d+ times?", r"in open play", r"within \d+ seconds"]
        out += (
            [r"never won it back", r"(?:had )?no regains"]
            if not f.get("value")
            else [r"won (?:it|the ball) back (?:once|\d+ times)", r"(?:made )?\d+ regains?"]
        )
        return out
    if metric == "open_teammates_ahead":
        out = [r"the pass", r"further up the pitch", r"further forward"]
        out += (
            [r"lost the ball", r"lost (?:a|the) pass", r"was lost"]
            if f.get("outcome") == "fail"
            else [r"completed (?:the|a) pass", r"kept the ball"]
        )
        if f.get("target_open") is False:
            out += [r"went elsewhere"]
        if f.get("target_open") is True:
            out += [r"found (?:an open teammate|one of them)", r"played it to an open teammate"]
        out += (
            [r"no (?:open )?teammate(?: free| open)?"]
            if not f.get("value")
            else [rf"{_N} (?:open )?teammates?(?: free| open)?"]
        )
        return out
    if metric == "passes_with_no_open_teammate_ahead":
        return [
            r"(?:made |had )?\d+ passes",
            r"with no open teammate",
            r"no teammate free",
            r"further forward",
            r"further up the pitch",
        ]
    if metric == "extra_players":
        return [
            rf"{_N} extra players?",
            rf"{_N} players? against {_N} players?",
            r"a spare player there",
            r"built an overload",
            r"(?:had )?an overload",
            r"in their (?:own|middle|final) third",
            r"(?:on the (?:left|right)|in the centre)",
        ]
    if metric == "overload_moments":
        return (
            [r"built no overloads", r"no overloads"]
            if not f.get("value")
            else [
                rf"built {_N} overloads?",
                r"built an overload",
                rf"{_N} overloads?",
                r"most often in their (?:own|middle|final) third",
                r"(?:on the (?:left|right)|in the centre)",
            ]
        )
    return []


def direction_reasons(
    text: str, cited: list[Mapping], clubs: Mapping[str, str] = (), names: Iterable[str] = ()
) -> list[str]:
    """The words a sentence about a directed fact uses that the check cannot vouch for (see above)."""
    directed = [f for f in cited if f.get("metric") in DIRECTED]
    if not directed:
        return []
    rest = spelled_as_digits(text)  # "three players pressing" is "3 players pressing"
    # Take out the longest matches first, wherever they are, so a short phrase never eats the middle
    # of a longer one ("an overload" inside "built an overload").
    spans = sorted(
        ((m.start(), m.end()) for f in directed for p in _approved(f) for m in re.finditer(p, rest, re.I)),
        key=lambda se: (se[0] - se[1], se[0]),
    )
    taken: list[tuple[int, int]] = []
    for a, b in spans:
        if all(b <= c or a >= d for c, d in taken):
            taken.append((a, b))
    for a, b in sorted(taken, reverse=True):
        rest = rest[:a] + " " + rest[b:]
    for name in sorted({*dict(clubs).values(), *names, *LABEL.values()}, key=len, reverse=True):
        rest = re.sub(rf"\b{re.escape(name)}(?:'s)?\b", " ", rest, flags=re.I)
    words = [w for w in re.findall(r"[a-z]+(?:[-'][a-z]+)*", rest.lower()) if w not in GLUE]
    if not words:
        return []
    say = "; ".join(sorted({p for f in directed for p in _approved(f)}))
    return [f"'{' '.join(words[:6])}' is not one of the fact's own words: say it as {say}"]


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
