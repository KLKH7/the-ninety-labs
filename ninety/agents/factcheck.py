"""The code half of the fact-checking agent.

A claim passes only if every event it cites exists, every player it names appears in that
evidence, and every number it states can be read off the evidence: a cited field, a count of
cited events, or the minute. Anything else is rejected with a reason the writer can act on.

Evidence may also hold computed facts (ninety/intel/stats.py `Fact.as_dict()`: metric, value, unit,
scope). A cited fact's value counts only when it is written with the fact's unit ("31.2 km/h" for a
km/h fact), never as a bare number, and a fact scoped to a player (`player:h7...`) cites that player.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

# A number standing on its own: not part of an id like "e00042" or a player like "h7". A
# sentence-ending period after it still counts ("in minute 2."), and so do an English ordinal ("the
# 9th minute") and a unit written straight after it ("50km/h", "9999m"): the number is the `n`
# group. Every form a writer can produce is read, or a model could air a number by gluing it.
NUMBER_PATTERN = r"\d+(?:\.\d+)?"
NUMBER = re.compile(rf"(?<![\w.])(?P<n>{NUMBER_PATTERN})(?:st|nd|rd|th)?(?!\d)(?!\.\d)")
# Numbers written as words ("fifty km/h", "twenty-eight", "two hundred and five") are numbers too:
# `check` reads them as digits. Words combine only as English writes one number: a tens word and a
# units word, and a number before "hundred" or "thousand". Two small numbers side by side are two
# numbers, never a sum ("one-two" is not 3).
UNITS = "one two three four five six seven eight nine".split()
TEENS = "ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen".split()
TENS = "twenty thirty forty fifty sixty seventy eighty ninety".split()
WORD_VALUES = (
    {"zero": 0}
    | {w: i for i, w in enumerate(UNITS, 1)}
    | {w: i for i, w in enumerate(TEENS, 10)}
    | {w: 10 * i for i, w in enumerate(TENS, 2)}
)
_WORD = rf"(?:{'|'.join(sorted([*WORD_VALUES, 'hundred', 'thousand'], key=len, reverse=True))})"
_UNIT, _TEEN, _TENS = (rf"(?:{'|'.join(words)})" for words in (UNITS, TEENS, TENS))
_BELOW_100 = rf"(?:{_TENS}(?:[\s-]+{_UNIT}\b)?|{_TEEN}|{_UNIT}|zero)"
_BELOW_1000 = rf"(?:(?:{_UNIT}\s+)?hundred(?:\s+(?:and\s+)?{_BELOW_100}\b)?|{_BELOW_100})"
WORD_NUMBER = re.compile(
    rf"\b(?:(?:{_BELOW_1000}\s+)?thousand(?:\s+(?:and\s+)?{_BELOW_1000}\b)?|{_BELOW_1000})\b", re.I
)
# Number words that are no count: football's idioms (a one-two, a one-on-one, a one-touch pass, a
# two-footed tackle, a one-handed save) and the pronoun "one" ("one of", "no one").
NOT_A_COUNT = re.compile(
    r"\bone[\s-]twos?\b|\bone[\s-]on[\s-]one\b|\bone[\s-]v(?:s\.?|\.)?[\s-]one\b"
    r"|\b(?:one|two)[\s-](?:touch|time|footed|handed)\b"
    r"|\b(?:no|the)\s+one\b|\bone(?=\s+(?:of|another)\b)"
    r"|\buno\s+(?:contra|a)\s+uno\b|\buno(?=\s+de\b)",  # Spanish: one-on-one, "one of"
    re.I,
)
# Spanish number words: the Personalizer writes Spanish variants and they are re-checked here, so
# "cincuenta km/h" and "treinta y uno" are numbers too. As with English, words combine only as
# Spanish writes one number. "un" and "una" are read only inside a number ("veintiún", "treinta y
# una"): alone they are the article "a". "once" (11) is also the English adverb, so it is read
# only before a unit or a counted noun, or after "minuto" (`_ES_ONCE`).
ES_VALUES = (
    {"cero": 0, "uno": 1, "una": 1, "un": 1}
    | {w: i for i, w in enumerate("dos tres cuatro cinco seis siete ocho nueve diez once doce trece "
                                  "catorce quince".split(), 2)}
    | {w: i for i, w in enumerate("dieciséis diecisiete dieciocho diecinueve veinte veintiuno "
                                  "veintidós veintitrés veinticuatro veinticinco veintiséis veintisiete "
                                  "veintiocho veintinueve".split(), 16)}
    | {"dieciseis": 16, "veintiuna": 21, "veintiún": 21, "veintiun": 21, "veintidos": 22,
       "veintitres": 23, "veintiseis": 26}
    | {w: 10 * i for i, w in enumerate("treinta cuarenta cincuenta sesenta setenta ochenta noventa"
                                       .split(), 3)}
    | {"cien": 100, "ciento": 100, "quinientos": 500, "quinientas": 500, "setecientos": 700,
       "setecientas": 700, "novecientos": 900, "novecientas": 900}
    | {f"{p}cient{g}s": n * 100 for p, n in (("dos", 2), ("tres", 3), ("cuatro", 4), ("seis", 6),
                                            ("ocho", 8)) for g in "oa"}
)


def _alt(words: Iterable[str]) -> str:
    return rf"(?:{'|'.join(sorted(words, key=len, reverse=True))})"


_ES_TAIL = _alt(w for w, n in ES_VALUES.items() if 1 <= n <= 9)
_ES_UNIT = _alt(w for w, n in ES_VALUES.items() if 1 <= n <= 9 and w not in ("un", "una"))
_ES_TEEN = _alt(w for w, n in ES_VALUES.items() if 10 <= n <= 29 and w not in ("un", "una"))
_ES_TENS = _alt(w for w, n in ES_VALUES.items() if n in range(30, 100, 10))
_ES_HUNDREDS = _alt(w for w, n in ES_VALUES.items() if n >= 100 and w != "cien")
_ES_BELOW_100 = rf"(?:{_ES_TENS}(?:\s+y\s+{_ES_TAIL}\b)?|{_ES_TEEN}|{_ES_UNIT}|cero)"
_ES_BELOW_1000 = rf"(?:{_ES_HUNDREDS}(?:\s+{_ES_BELOW_100}\b)?|cien|{_ES_BELOW_100})"
ES_WORD_NUMBER = re.compile(
    rf"\b(?:(?:{_ES_BELOW_1000}\s+)?mil(?:\s+{_ES_BELOW_1000}\b)?|{_ES_BELOW_1000})\b", re.I
)
_ES_ONCE = re.compile(
    r"(?:(?<=minuto\s)once\b|\bonce(?=[\s-]+(?:m|metros?|km/h|kil[oó]metros|minutos?|segundos?"
    r"|pases|disparos|tiros|goles|veces|yardas|pies|millas|jugadores)\b))",
    re.I,
)
# Ordinals in words ("his seventh pass", "the ninth minute", "the twenty-first minute") are read
# as their digit form ("7th"), which the number checks already read (lesson 130). "first" and
# "second" are football's words for halves, touches, balls and time ("first time", "a second
# yellow"), so they are read only before "minute"; Spanish likewise ("primer minuto"). Fractions
# and the pitch's thirds are no ordinal ("the final third", "a third of", "the fourth official").
ORDINAL_VALUES = (
    {w: i for i, w in enumerate("first second third fourth fifth sixth seventh eighth ninth tenth "
                                "eleventh twelfth thirteenth fourteenth fifteenth sixteenth "
                                "seventeenth eighteenth nineteenth".split(), 1)}
    | {w: 10 * i for i, w in enumerate("twentieth thirtieth fortieth fiftieth sixtieth seventieth "
                                       "eightieth ninetieth".split(), 2)}
    | {"hundredth": 100}
    | {f"{w}{g}": i for i, w in enumerate("primer segund tercer cuart quint sext séptim octav noven "
                                          "décim".split(), 1) for g in "oa"}
    | {"primer": 1, "tercer": 3, "septimo": 7, "septima": 7, "decimo": 10, "decima": 10}
)
_ORD_LEADS = ("first", "second", "primer", "primero", "primera", "segundo", "segunda")
_ORD_TAIL = _alt(w for w, n in ORDINAL_VALUES.items() if 1 <= n <= 9 and w.isascii() and w.endswith(
    ("st", "nd", "rd", "th")))
ORDINAL = re.compile(
    rf"\b(?:{_TENS}[\s-]+{_ORD_TAIL}"
    rf"|{_alt(w for w in ORDINAL_VALUES if w not in _ORD_LEADS)}"
    rf"|{_alt(_ORD_LEADS)}(?=[\s-]+minut[eo]\b))\b",
    re.I,
)
NOT_AN_ORDINAL = re.compile(
    r"\b(?:final|attacking|defensive|middle|own|opposition)\s+third\b|\bthird[\s-]+man\b"
    r"|\bfourth\s+official\b|\b(?:a|one)\s+(?:third|fourth|fifth|sixth|seventh|eighth|ninth|tenth)\s+of\b"
    r"|\btercer\s+hombre\b|\bcuarto\s+de\b|\bd[ée]cimas?\s+de\b|\btercera\s+parte\b",
    re.I,
)
DISTANCE_UNITS = r"(?:m|metre|metres|meter|meters|metro|metros)"
SPEED_UNITS = r"(?:km/h|kph|kmh|(?:km|kil[oó]met(?:re|er|ro)s?)\s+(?:per|an|por)\s+(?:hour|hora))"
DISTANCE_NUMBER = re.compile(rf"(?P<number>{NUMBER_PATTERN})[\s-]*{DISTANCE_UNITS}\b", re.I)
SPEED_NUMBER = re.compile(rf"(?P<number>{NUMBER_PATTERN})[\s-]*{SPEED_UNITS}\b", re.I)
# Units no fact of ours is in: every distance we publish is in metres and every speed in km/h, so
# "12 yards" is not 12 m and "33 mph" is not 33 km/h. A number in one of them is refused, whatever
# its digits, rather than converted: the writer restates it in our unit.
UNPUBLISHED_UNITS = (
    r"(?:yards?|yds?|yardas?|feet|foot|ft|pies?|inch(?:es)?|mph|mps|m/s|knots?|nudos?|miles?|millas?"
    r"|(?:km|kil[oó]met(?:re|er|ro)s?)(?!/h)(?!\s+(?:per|an|por)\s+(?:hour|hora)\b)"
    r"|(?:m|met(?:re|er|ro)s?)\s+(?:per|por)\s+(?:second|segundo))"
)
UNPUBLISHED_NUMBER = re.compile(
    rf"(?P<number>{NUMBER_PATTERN})[\s-]*(?P<unit>{UNPUBLISHED_UNITS})(?![\w/])", re.I
)
MINUTE_NUMBER = re.compile(
    rf"(?:\bminut[eo]\s+(?P<minute_a>{NUMBER_PATTERN})\b|"
    rf"(?P<minute_b>{NUMBER_PATTERN})\s+minut[eo]s?\b|"
    rf"(?P<minute_c>{NUMBER_PATTERN})'|"
    rf"\b(?P<minute_d>{NUMBER_PATTERN})(?:st|nd|rd|th)[\s-]+minut[eo]\b)",
    re.I,
)
SECOND_NUMBER = re.compile(
    rf"(?:\bsecond\s+(?P<second_a>{NUMBER_PATTERN})\b|"
    rf"(?P<second_b>{NUMBER_PATTERN})\s+(?:second|segundo)s?\b|"
    rf":(?P<second_c>\d{{1,2}})(?!\d))",
    re.I,
)
# A clock form, "12:34", is the elapsed scorebug clock in compact event facts.
CLOCK = re.compile(r"(?<![\w.:])(?P<clock>\d{1,3}:\d{2})(?!\d)")
# Player ids: the synthetic squads' (h1..h11, a1..a11) in ground-truth data, and a team plus track
# id (h-t12) in tracked data, since the tracker reads no shirt numbers and a track is never mapped
# to one. Names in either form are always checked, even when the player is in no known event, so a
# claim cannot name an uninvolved player.
SQUAD_ID = r"[ha](?:[1-9]|1[01])"
TRACK_ID = r"[ha]-t\d+"
PLAYER_ID = rf"(?:{SQUAD_ID}|{TRACK_ID})"
PLAYER = re.compile(rf"\b{PLAYER_ID}\b")
# A verb that says a pass arrived names the player who got it, so that name must be the `receiver` of
# a cited pass: a pass's `intended` or `interceptor` is a cited player too, but did not receive it.
# With the passer named before the verb, it must be his pass that reached that player.
FOUND = re.compile(
    rf"(?:\b(?P<passer>{PLAYER_ID})(?:'s pass)?\s+)?"
    rf"\b(?:finds|found|picks out|picked out)\s+(?P<player>{PLAYER_ID})\b",
    re.I,
)
# A distance or speed the sentence gives to one player must be a value of that player's own cited
# events (or a fact scoped to him), not just of some cited event: "h7's 30 m pass" is false when
# h7's pass was the 12 m one and 30 m was h4's. Bound, and only these forms: a possessive ("h7's
# [up to two words] 30 m"), "h7, whose ... 30 m", a kicking verb with the player as its subject
# ("h7 plays a 30 m pass", "h10 pasa el balón 14 metros"), and "his/her ... 30 m" in a sentence
# naming only one player. Any other wording (passives, "from h7", "de h7") binds nothing and the
# number is checked against all the cited events as before.
_KICKS = (
    "plays|played|hits|hit|sends|sent|fires|fired|drives|drove|strikes|struck|clips|clipped|lofts"
    "|lofted|threads|threaded|curls|curled|whips|whipped|pings|pinged|rolls|rolled|slides|slid"
    "|shoots|shot|passes|passed|pasa|pasó|juega|jugó|envía|envió|envia|envio|lanza|lanzó|dispara"
    "|disparó|golpea|golpeó|manda|mandó"
)
_GAP = r"(?:[^\W\d_]+\s+)"
_UNIT_NUMBER_NEXT = rf"(?={NUMBER_PATTERN}[\s-]*(?:{DISTANCE_UNITS}|{SPEED_UNITS})\b)"
BOUND_TO_PLAYER = re.compile(
    rf"\b(?P<player>{PLAYER_ID})(?:['’]s\s+{_GAP}{{0,2}}|,?\s+whose\s+{_GAP}{{0,2}}"
    rf"|\s+(?:{_KICKS})\s+(?:(?:a|an|the|his|her|el|la|un|una|su)\s+)?{_GAP}?){_UNIT_NUMBER_NEXT}",
    re.I,
)
BOUND_TO_PRONOUN = re.compile(rf"\b(?:his|her)\s+{_GAP}{{0,2}}{_UNIT_NUMBER_NEXT}", re.I)
NUMBER_FIELDS = ("minute", "second", "ball_speed_kmh", "distance_m")
# The unit a fact must be written with to stand for each event field's kind of number.
FIELD_UNITS = {"distance_m": "m", "ball_speed_kmh": "km/h"}
FACT_PLAYER = re.compile(rf"^player:(?P<player>{PLAYER_ID})(?::|$)")
# A cited window stat (ninety/intel/windows.agent_rows, `type: stat`) is a number code computed:
# its value, its percentage for a share, and the minutes its window spans may be stated.
STAT_FIELDS = ("value", "percent", "minute_from", "minute_to")
# What a number read as a minute may match: an event's minute, or the span of a cited stat's window.
FIELD_ALIASES = {"minute": ("minute", "minute_from", "minute_to")}
# Design: a detected event below this confidence is one the detector itself rates no likelier real
# than not, so nothing built on it airs. To be replaced by the value measured from the event
# report's precision at each confidence once detected events are scored (docs/EVALUATION.md).
MIN_CONFIDENCE = 0.5


@dataclass
class Claim:
    text: str
    evidence: list[str]


@dataclass
class Verdict:
    ok: bool
    reasons: list[str] = field(default_factory=list)
    category: str | None = None


def _normalize_clock(clock: str) -> str:
    minute, second = clock.split(":")
    return f"{minute.zfill(2)}:{second.zfill(2)}"


def _number_field(text: str, start: int) -> str | None:
    for field_name, pattern in (
        ("unpublished", UNPUBLISHED_NUMBER),
        ("distance_m", DISTANCE_NUMBER),
        ("ball_speed_kmh", SPEED_NUMBER),
        ("minute", MINUTE_NUMBER),
        ("second", SECOND_NUMBER),
    ):
        for match in pattern.finditer(text):
            number_match = next((group for group in match.groups() if group is not None), None)
            if number_match is not None:
                number_start = match.start() + match.group(0).find(number_match)
                if number_start == start:
                    return field_name
    return None


def _bound_players(text: str) -> dict[int, str]:
    """Where a distance or speed is given to one player (BOUND_TO_PLAYER, BOUND_TO_PRONOUN): the
    number's start in `text`, and the player's id."""
    bound = {m.end(): m.group("player").lower() for m in BOUND_TO_PLAYER.finditer(text)}
    for sentence in re.finditer(r"(?:[^.!?;]|\.(?=\d))+", text):
        players = set(PLAYER.findall(sentence.group().lower()))
        if len(players) == 1:
            (player,) = players
            for m in BOUND_TO_PRONOUN.finditer(sentence.group()):
                bound.setdefault(sentence.start() + m.end(), player)
    return bound


def _player_values(evidence: list[dict], player: str, field_name: str) -> set[float]:
    """The values of `field_name` in the cited events `player` made, and in the cited facts scoped
    to him in that field's unit."""
    return {
        float(e[field_name]) for e in evidence
        if not _is_fact(e) and e.get("player") == player and e.get(field_name) is not None
    } | {
        float(f["value"]) for f in evidence
        if _is_fact(f) and f["unit"] == FIELD_UNITS[field_name]
        and (found := FACT_PLAYER.match(str(f.get("scope", "")))) and found.group("player") == player
    }


def _roster_ids(known: dict[str, dict], roster: Iterable[Mapping | str] | None) -> set[str]:
    if roster is None:
        values = [
            value
            for event in known.values()
            for value in (event.get("player"), event.get("receiver"), event.get("intended"),
                          event.get("interceptor"), event.get("deflected_by"))
            if value
        ]
    else:
        values = [
            item.get("id") if isinstance(item, Mapping) else item
            for item in roster
        ]
    return {str(value) for value in values if value}


def _is_fact(item: Mapping) -> bool:
    """A computed fact (`Fact.as_dict()`), whose value needs its unit. Events and cited window stats
    (`type: stat`, which states its value bare) carry a `type`; a fact does not."""
    return "type" not in item and "metric" in item and "unit" in item and "value" in item


def _fact_values(evidence: list[dict], unit: str) -> set[float]:
    return {float(f["value"]) for f in evidence if _is_fact(f) and f["unit"] == unit}


def _word_value(phrase: str) -> int:
    """The value of one well-formed number in words (WORD_NUMBER matched it, so a units word only
    ever follows a tens word or leads a scale)."""
    total = current = 0
    for word in re.findall(rf"\b{_WORD}\b", phrase, re.I):
        word = word.lower()
        if word in WORD_VALUES:
            current += WORD_VALUES[word]
        elif word == "hundred":
            current = max(current, 1) * 100
        else:
            total, current = total + max(current, 1) * 1000, 0
    return total + current


def _es_value(phrase: str) -> int:
    """The value of one well-formed Spanish number in words (ES_WORD_NUMBER matched it)."""
    total = current = 0
    for word in re.findall(r"[^\W\d_]+", phrase.lower()):
        if word == "mil":
            total, current = total + max(current, 1) * 1000, 0
        elif word != "y":
            current += ES_VALUES[word]
    return total + current


def _ordinal_digits(m: re.Match) -> str:
    """An ordinal in words as its digit form: "seventh" is "7th", "twenty-first" is "21st"."""
    *tens, last = re.split(r"[\s-]+", m.group().lower())
    n = sum(WORD_VALUES[w] for w in tens) + ORDINAL_VALUES[last]
    return f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


def spelled_as_digits(text: str) -> str:
    """The text with every number written in words, English or Spanish, replaced by its digits
    ("fifty km/h" and "cincuenta km/h" become "50 km/h", "his seventh pass" becomes "his 7th
    pass"), so the number checks read it like any other."""
    def spans(pattern: re.Pattern, text: str) -> list[range]:
        return [range(m.start(), m.end()) for m in pattern.finditer(text)]

    not_ordinals = spans(NOT_AN_ORDINAL, text)
    text = ORDINAL.sub(
        lambda m: m.group() if any(m.start() in s for s in not_ordinals) else _ordinal_digits(m), text
    )
    idioms = spans(NOT_A_COUNT, text)

    def digits(m: re.Match) -> str:
        if any(m.start() in span for span in idioms):
            return m.group()
        return str(_word_value(m.group()))

    text = WORD_NUMBER.sub(digits, text)
    idioms = spans(NOT_A_COUNT, text)

    def es_digits(m: re.Match) -> str:
        if any(m.start() in span for span in idioms):
            return m.group()
        if m.group().lower() == "once" and not _ES_ONCE.match(text, m.start()):
            return m.group()  # the English adverb
        return str(_es_value(m.group()))

    return ES_WORD_NUMBER.sub(es_digits, text)


def _unit_follows(text: str, end: int, unit: str) -> bool:
    """Is `unit` written straight after the number ending at `end` ("512 m", "3 frames")?"""
    return re.match(rf"\s*{re.escape(unit)}(?!\w)", text[end:], re.I) is not None


def allowed_numbers(events: list[dict]) -> set[float]:
    """Numbers a claim may state bare: event fields and counts. A fact's value is not one of them:
    it needs its unit (see `check`)."""
    events = [e for e in events if not _is_fact(e)]
    values: set[float] = {float(len(events))}
    for event in events:
        values.update(float(event[name]) for name in NUMBER_FIELDS if name in event)
        if event.get("type") == "stat":
            values.update(float(event[name]) for name in STAT_FIELDS if name in event)
    values.update(float(n) for n in Counter(e["type"] for e in events).values())
    values.update(float(n) for n in Counter((e["team"], e["type"]) for e in events).values())
    return values


def check(
    claim: Claim,
    known: dict[str, dict],
    roster: Iterable[Mapping | str] | None = None,
) -> Verdict:
    reasons = []
    if not claim.evidence:
        reasons.append("cite at least one event id as evidence")
    missing = [i for i in claim.evidence if i not in known]
    if missing:
        reasons.append(f"unknown event ids: {', '.join(missing)}")
    evidence = [known[i] for i in claim.evidence if i in known]

    allowed = allowed_numbers(evidence)
    for match in CLOCK.finditer(claim.text):
        cited_clocks = {
            _normalize_clock(event["clock"])
            for event in evidence
            if event.get("clock") is not None
        }
        clock = match.group("clock")
        normalized = _normalize_clock(clock)
        if normalized not in cited_clocks:
            reasons.append(f"clock {clock} is not a cited clock")
    text = spelled_as_digits(claim.text)
    clock_spans = [range(match.start(), match.end()) for match in CLOCK.finditer(text)]
    bound = _bound_players(text)
    for match in NUMBER.finditer(text):
        if any(match.start() in span for span in clock_spans):
            continue
        value = float(match.group("n"))
        expected_field = _number_field(text, match.start())
        if expected_field == "unpublished":
            reasons.append(
                f"number {match.group()} is in a unit the evidence does not use: "
                "state distances in metres and speeds in km/h"
            )
        elif expected_field:
            values = {
                float(event[name])
                for event in evidence
                for name in FIELD_ALIASES.get(expected_field, (expected_field,))
                if event.get(name) is not None
            }
            if expected_field in FIELD_UNITS:
                values |= _fact_values(evidence, FIELD_UNITS[expected_field])
            if value not in values:
                reasons.append(
                    f"number {match.group()} is not a cited {expected_field}"
                )
            elif (player := bound.get(match.start())) and expected_field in FIELD_UNITS and (
                value not in _player_values(evidence, player, expected_field)
            ):
                reasons.append(f"number {match.group()} is not a cited {expected_field} of {player}")
        elif value not in allowed and not any(
            float(f["value"]) == value and _unit_follows(text, match.end(), str(f["unit"]))
            for f in evidence
            if _is_fact(f)
        ):
            reasons.append(f"number {match.group()} is not in the cited evidence")
    cited_players = {
        value
        for event in evidence
        for value in (event.get("player"), event.get("receiver"), event.get("intended"),
                      event.get("interceptor"), event.get("deflected_by"))
        if value
    } | {
        found.group("player")
        for fact in evidence
        if _is_fact(fact) and (found := FACT_PLAYER.match(str(fact.get("scope", ""))))
    }
    named_players = {
        player_id
        for player_id in _roster_ids(known, roster)
        if re.search(rf"(?<!\w){re.escape(player_id)}(?!\w)", claim.text)
    } | set(PLAYER.findall(claim.text))
    for name in sorted(named_players - cited_players):
        reasons.append(f"player {name} does not appear in the cited evidence")
    passes = [event for event in evidence if event.get("type") == "pass"]
    for match in FOUND.finditer(claim.text):
        name, passer = match.group("player").lower(), (match.group("passer") or "").lower()
        if passer and passer not in {p.get("player") for p in passes}:
            continue  # not a pass he made ("a4 found h9 in possession", citing a tackle)
        if not passer and not passes:
            continue
        found = {(p.get("player"), p.get("receiver")) for p in passes}
        if not any(r == name and (not passer or s == passer) for s, r in found):
            reasons.append(f"player {name} received no cited pass" + (f" from {passer}" if passer else ""))

    return Verdict(ok=not reasons, reasons=reasons)


def confidence_gate(
    claim: Claim, known: dict[str, dict], min_confidence: float = MIN_CONFIDENCE
) -> Verdict:
    """Holds back a claim that cites a detected event the detector is not sure of.

    Only detected events carry a confidence (ninety/match/facts.compact); ground-truth events in
    the pre-M1 recordings have none and pass. The verdict's category, `low_confidence`, makes the
    claim held, not rejected (ninety/agents/contracts.status_for): the claim may be right, but
    nothing airs until a confident detection supports it.
    """
    reasons = [
        f"event {i} was detected with confidence {known[i]['confidence']:.2f}, "
        f"below {min_confidence:.2f}: cite a confident detection"
        for i in claim.evidence
        if i in known and known[i].get("confidence") is not None and known[i]["confidence"] < min_confidence
    ]
    return Verdict(ok=not reasons, reasons=reasons, category="low_confidence" if reasons else None)


def parse_claim(text: str) -> Claim:
    """A writer's reply, {"text": ..., "evidence": [...]}, as a Claim; the JSON may sit inside prose."""
    body = re.search(r"\{.*\}", text, re.S)
    data = json.loads(body.group() if body else text)
    if not isinstance(data, dict):
        raise ValueError(f"the Analyst's reply is not a JSON object: {text[:80]!r}")
    return Claim(text=str(data.get("text", "")), evidence=[str(i) for i in data.get("evidence", [])])
