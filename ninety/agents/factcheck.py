"""The code half of the fact-checking agent.

A claim passes only if every event it cites exists, every player it names appears in that
evidence, and every number it states can be read off the evidence: a cited field, a count of
cited events, or the minute. Anything else is rejected with a reason the writer can act on.

Evidence may also hold computed facts (ninety/intel/stats.py `Fact.as_dict()`: metric, value, unit,
scope). A cited fact's value counts only when it is written with the fact's unit ("31.2 km/h" for a
km/h fact), never as a bare number, and a fact scoped to a player (`player:h7...`) cites that player.

Evidence may hold team-shape facts too (ninety/intel/shape.py, `type: shape`). A claim about a
team's shape must cite one, its numbers must be the facts' (a distance in metres, an area in square
metres, a count of players), its team must be the fact's, and its words must agree with the fact: a
line that "pushed up" has a positive change, a "high line" stands above the reference range, and so
on (`shape_reasons`). A shape fact built on too few tracked players is held by the confidence gate.
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
# An N-on-M ("a two-on-one") is a word only when no unit or counted noun follows it: in "a
# two-on-three m pass" the "three" is a distance, checked like any other (review of #268).
_NO_UNIT_AFTER = (
    r"(?![\s-]*(?:m|metres?|meters?|metros?|km|km/h|kph|kmh|k\.p\.h|kil[oó]met\w*|yards?|yds?|yardas?"
    r"|feet|foot|ft|pies|mph|m\.p\.h|minutes?|minutos?|seconds?|secs?|segundos?|players|men|outfielders"
    r"|jugadores|hombres|passes|pases|shots|tiros|disparos|goals|goles|times|veces)(?![\w/]))"
)
NOT_A_COUNT = re.compile(
    r"\bone[\s-]twos?\b|\bone[\s-]on[\s-]one\b|\bone[\s-]v(?:s\.?|\.)?[\s-]one\b"
    r"|\b(?:one|two)[\s-](?:touch|time|footed|handed)\b"
    r"|\b(?:no|the)\s+one\b|\bone(?=\s+(?:of|another|side)\b)"  # "one side's back line": no count
    r"|\b(?:one|two|three|four)[\s-](?:on|v(?:s\.?|\.)?)[\s-](?:one|two|three|four)\b"  # a two-on-one
    + _NO_UNIT_AFTER +
    # Spanish: one-on-one ("uno contra uno", "un dos contra uno"), "one of", beating a man ("se va
    # de uno"), "a hundred per cent", "at full tilt" ("a mil por hora"), "with both feet"
    r"|\b(?:uno|dos|tres|cuatro)\s+(?:contra|a)\s+(?:uno|dos|tres|cuatro)\b" + _NO_UNIT_AFTER +
    r"|\buno(?=\s+de\b)"
    r"|\b(?:va|van|fue|ir|irse|marcha|marchó)\s+de\s+uno\b|\bcien\s+por\s+cien\b"
    r"|\bmil\s+por\s+hora\b|\b(?:los|las|ambos)\s+dos\s+pies\b",
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
    r"\b(?:final|attacking|defensive|middle|own|opposition)[\s-]+third\b|\bthird[\s-]+man\b"
    r"|\bfourth\s+official\b|\b(?:a|one)\s+(?:third|fourth|fifth|sixth|seventh|eighth|ninth|tenth)\s+of\b"
    r"|\btercer\s+hombre\b|\bcuarto\s+de\b|\bd[ée]cimas?\s+de\b|\btercera\s+parte\b",
    re.I,
)
DISTANCE_UNITS = r"(?:m|metre|metres|meter|meters|metro|metros)"
SPEED_UNITS = r"(?:km/h|kph|kmh|k\.p\.h|(?:km|kil[oó]met(?:re|er|ro)s?)\s+(?:per|an|por)\s+(?:hour|hora))"
DISTANCE_NUMBER = re.compile(rf"(?P<number>{NUMBER_PATTERN})[\s-]*{DISTANCE_UNITS}\b", re.I)
SPEED_NUMBER = re.compile(rf"(?P<number>{NUMBER_PATTERN})[\s-]*{SPEED_UNITS}\b", re.I)
# Units no fact of ours is in: every distance we publish is in metres and every speed in km/h, so
# "12 yards" is not 12 m and "33 mph" is not 33 km/h. A number in one of them is refused, whatever
# its digits, rather than converted: the writer restates it in our unit.
UNPUBLISHED_UNITS = (
    # A pitch marking ("the six-yard box", "the 12-yard spot") is a name, not a measurement: its
    # number is checked as a bare number, as before.
    r"(?:yards?(?![\s-]+(?:box|line|area|spot|mark)\b)|yds?|yardas?|feet|foot|ft|pies?|inch(?:es)?"
    r"|mph|m\.p\.h|mps|m/s|knots?|nudos?|miles?|millas?"
    r"|(?:km|kil[oó]met(?:re|er|ro)s?)(?!/h)(?!\s+(?:per|an|por)\s+(?:hour|hora)\b)"
    r"|(?:m|met(?:re|er|ro)s?)\s+(?:per|por)\s+(?:second|segundo))"
)
UNPUBLISHED_NUMBER = re.compile(
    rf"(?P<number>{NUMBER_PATTERN})[\s-]*(?P<unit>{UNPUBLISHED_UNITS})(?![\w/])", re.I
)
# An area: "900 m²", "900m2", "900 sq m", "900 square metres" (a shape fact's unit, m²).
AREA_UNITS = r"(?:m²|m2|sq\.?\s*m|square\s+(?:metres|meters|metre|meter))"
AREA_NUMBER = re.compile(rf"(?P<number>{NUMBER_PATTERN})\s*{AREA_UNITS}(?!\w)", re.I)
# A count of players: "7 players", "seven home players" (read as digits first), "all 7 outfielders".
PLAYERS_NUMBER = re.compile(
    rf"(?P<number>{NUMBER_PATTERN})\s+(?:(?:home|away|of\s+their|of\s+its|outfield)\s+)?"
    r"(?:players|men|outfielders|outfield\s+players)\b", re.I,
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
# h7's pass was the 12 m one and 30 m was h4's. A binding starts only at these forms, with the first
# distance or speed at most two words on: a possessive ("h7's crisp 30 m"), "h7, whose ... 30 m", a
# kicking verb with the player as its subject ("h7 plays a curling 30 m pass", "h7 juega un pase de
# 30 metros"), and "his/her" when exactly one player is named before it in the sentence (or, if
# none is, in the sentence before). A possessive, "whose" or "his" binds only its own noun phrase, the
# first number ("h4 receives h7's 12 m pass and plays a 30 m pass" binds only 12, to h7); a kicking
# verb binds every distance and speed up to the next player id, ";", "and"/"y" or the end of the
# sentence ("h7 plays a 12 m pass at 40 km/h"). Any other wording (passives,
# "from h7", "de h7") binds nothing and the number is checked against all the cited events.
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
    rf"|(?P<verb>\s+(?:{_KICKS})\s+(?:(?:a|an|the|his|her|el|la|un|una|su)\s+)?{_GAP}{{0,2}})){_UNIT_NUMBER_NEXT}",
    re.I,
)
BOUND_TO_PRONOUN = re.compile(rf"\b(?:his|her)\s+{_GAP}{{0,2}}{_UNIT_NUMBER_NEXT}", re.I)
# Where a binding's clause ends: the next player id, a semicolon, or the end of the sentence.
CLAUSE_END = re.compile(rf"\b{PLAYER_ID}\b|;|\b(?:and|y|but|pero|then|luego)\b|[.!?](?!\d)|$", re.I)
# Dots inside a unit ("k.p.h.") end no clause or sentence: they are masked before either is found.
UNIT_DOTS = re.compile(r"\b[km]\.p\.h\b\.?", re.I)
SENTENCE = re.compile(r"(?:[^.!?;]|\.(?=\d))+")
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
# Measured: on ours-v2's 16 matched validation passes (docs/eval/attribution-derive.md, side
# confidence) the 5 whose side was wrong scored 0.431 to 0.96 on `team_confidence`, and the 11 right
# ones 0.447 to 0.985. A claim that names a team is held unless every detected event it cites had
# its side told above the highest wrong side, 0.96. This is no guarantee: it is the maximum of 5
# wrong sides, so a new wrong side would exceed it about 1 time in 6 (exchangeability), and it was
# measured on passes only, yet applies to every event. It holds most team claims on today's vision
# (9 of the 11 right sides too), which is the point until the side is told reliably (#200, #202).
# Re-measure when the side decision changes.
MIN_TEAM_CONFIDENCE = 0.96
# A claim that names a side, in English or Spanish (ninety/personalizer/core.TEAM_WORDS): "home",
# "away", "the hosts", "the visitors", "the visiting side", "local", "visitantes", "los de casa".
# It errs on holding: "away from goal" is held too.
TEAM_NAMED = re.compile(
    r"\b(?:home|away|hosts?|visit(?:ors?|ing)|local(?:es)?|visitantes?|de\s+casa)\b", re.I)


def side_known(event: Mapping) -> bool:
    """Whether a team may be named from this event: a ground-truth event (no detection confidence),
    or a detected one whose side was told above MIN_TEAM_CONFIDENCE. Every writer that names a side
    from an event (the template graphics, the Describer) asks this, as the confidence gate does. A
    shape fact (ninety/intel/shape.py) carries the least sure side of the players it was computed
    from, gated the same way."""
    if event.get("type") == "shape":
        side = event.get("team_confidence")
        return side is not None and side > MIN_TEAM_CONFIDENCE
    if event.get("confidence") is None:
        return True
    side = event.get("team_confidence")
    return side is not None and side > MIN_TEAM_CONFIDENCE


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
        ("area_m2", AREA_NUMBER),
        ("players", PLAYERS_NUMBER),
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
    """Where a distance or speed is given to one player (BOUND_TO_PLAYER, BOUND_TO_PRONOUN): each
    such number's start in `text`, and the player's id."""
    anchors = [(m.end(), m.group("player").lower(), m.group("verb") is not None)
               for m in BOUND_TO_PLAYER.finditer(text)]
    masked = UNIT_DOTS.sub(lambda m: "x" * len(m.group()), text)
    sentences = list(SENTENCE.finditer(masked))
    for k, sentence in enumerate(sentences):
        for m in BOUND_TO_PRONOUN.finditer(text, sentence.start(), sentence.end()):
            before = set(PLAYER.findall(masked[sentence.start():m.start()].lower()))
            if not before and k:
                before = set(PLAYER.findall(sentences[k - 1].group().lower()))
            if len(before) == 1:
                anchors.append((m.end(), before.pop(), False))
    bound: dict[int, str] = {}
    for start, player, verb in sorted(anchors):
        # A possessive, "whose" or pronoun binds its own noun phrase, the first number; a kicking
        # verb binds its whole clause.
        if not verb:
            bound.setdefault(start, player)  # the anchor ends where its first number starts
            continue
        end = CLAUSE_END.search(masked, start).start()
        for pattern in (DISTANCE_NUMBER, SPEED_NUMBER):
            for m in pattern.finditer(text, start, end):
                bound.setdefault(m.start("number"), player)
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


def _is_shape(item: Mapping) -> bool:
    return item.get("type") == "shape"


def shape_values(evidence: list[dict], unit: str) -> set[float]:
    """What a cited shape fact in `unit` lets a claim state: its value, and the size of its change
    from the minute before ("pushed up 8 m" for a change of +8, "dropped 5 m" for -5)."""
    values: set[float] = set()
    for row in evidence:
        if _is_shape(row) and row["unit"] == unit:
            values.add(float(row["value"]))
            if row.get("change") is not None:
                values.add(abs(float(row["change"])))
    return values


def allowed_numbers(events: list[dict]) -> set[float]:
    """Numbers a claim may state bare: event fields and counts. A fact's value is not one of them:
    it needs its unit (see `check`). Of a shape fact, only a count of players and its minute may
    stand bare; shape facts are not events, so they add nothing to the counts of events."""
    shapes = [e for e in events if _is_shape(e)]
    events = [e for e in events if not _is_fact(e) and not _is_shape(e)]
    values: set[float] = {float(len(events))} | shape_values(shapes, "players")
    values.update(float(row["minute"]) for row in shapes)
    for event in events:
        values.update(float(event[name]) for name in NUMBER_FIELDS if name in event)
        if event.get("type") == "stat":
            values.update(float(event[name]) for name in STAT_FIELDS if name in event)
    values.update(float(n) for n in Counter(e["type"] for e in events).values())
    values.update(float(n) for n in Counter((e["team"], e["type"]) for e in events).values())
    return values


# ---------------------------------------------------------------------------------------------
# Team shape (ninety/intel/shape.py): the words a claim about shape uses, and what each must agree
# with in the cited shape facts.
# ---------------------------------------------------------------------------------------------

# Reference ranges in professional matches (docs/GROUNDING.md S6 to S9: Rico-González et al., 2022,
# a systematic review of positional data): own goal line to the defensive line 22 to 28 m, team
# width 35 to 48 m, team area (convex hull) reported from 750 to 1,831 m². A word of degree says the
# team is outside the range: a "high line" above 28 m, a "deep block" below 22 m, "narrow" below
# 35 m, "compact" below 750 m².
DEEP_LINE_M, HIGH_LINE_M = 22, 28
NARROW_M = 35
COMPACT_M2 = 750
# Words that make a claim a claim about shape: it must cite a shape fact.
SHAPE_TERMS = re.compile(
    r"\b(?:back\s+(?:line|four|five)|defensive\s+(?:line|block)|(?:high|higher|deep|deeper|low|mid)\s+"
    r"(?:line|block)|compact(?:ness)?|narrow(?:er|ed|s|ing)?\b(?!\s+angle)|width|team\s+shape|"
    r"(?:their|its|the)\s+shape|between\s+the\s+lines|(?:behind|ahead\s+of|in\s+front\s+of)\s+the\s+ball)\b",
    re.I,
)
TEAM_WORD = re.compile(r"\b(home|away)\b", re.I)
_M = rf"(?P<n>{NUMBER_PATTERN})\s*{DISTANCE_UNITS}\b"
# (words, metric, test on the fact's value, test on its change). A comparative word ("pushed up")
# needs a change from the minute before; a word of degree ("high line") reads the value.
SHAPE_WORDS = (
    (re.compile(r"\b(?:push(?:ed|es|ing)?\s+(?:up|higher|forward)|step(?:ped|s|ping)?\s+up|"
                r"(?:raised|lifted)\s+(?:the|its|their)\s+(?:line|block)|higher\s+line|moved\s+up)\b", re.I),
     "line_height", None, lambda c: c > 0),
    (re.compile(r"\b(?:dropp(?:ed|ing)|drops?|fell|falls?|sank|sinks?|retreat(?:ed|s|ing)?)\s+"
                r"(?:back|deep(?:er)?|off)\b|\bsat\s+deeper\b|\bdeeper\s+(?:line|block)\b", re.I),
     "line_height", None, lambda c: c < 0),
    (re.compile(r"\bhigh\s+(?:line|block)\b", re.I), "line_height", lambda v: v > HIGH_LINE_M, None),
    (re.compile(r"\b(?:deep|low)\s+(?:line|block)\b|\b(?:sat|sitting|sits)\s+deep\b", re.I),
     "line_height", lambda v: v < DEEP_LINE_M, None),
    (re.compile(r"\bnarrow(?:er|ed|ing)\b|\bnarrows\b|\btucked\s+in\b", re.I),
     "width", None, lambda c: c < 0),
    (re.compile(r"\bnarrow\b(?!\s+angle)", re.I), "width", lambda v: v < NARROW_M, None),
    (re.compile(r"\b(?:wider|widen(?:ed|s|ing)?|spread\s+wide)\b", re.I), "width", None, lambda c: c > 0),
    (re.compile(r"\b(?:more\s+compact|compacted|tighten(?:ed|s|ing)?|squeez(?:ed|es|ing)|closed\s+up)\b",
                re.I),
     "area", None, lambda c: c < 0),
    (re.compile(r"(?<!more\s)(?<!less\s)\bcompact\b", re.I), "area", lambda v: v < COMPACT_M2, None),
    (re.compile(r"\b(?:less\s+compact|stretched|spread\s+out|opened\s+up|loosened)\b", re.I),
     "area", None, lambda c: c > 0),
)
# A number written next to a metric's words is that metric's: its value, or the size of its change.
# Each pattern holds one number, the `n` group.
_LINE_WORDS = (r"push(?:ed|es|ing)?\s+(?:up|higher|forward)|step(?:ped|s|ping)?\s+up|moved\s+up|"
               r"dropp(?:ed|ing)\s+(?:back|deeper|off)|retreat(?:ed|s|ing)?|(?:back|defensive)\s+line|line")
SHAPE_NUMBERS = tuple((re.compile(p, re.I), metrics) for p, metrics in (
    (rf"\b(?:{_LINE_WORDS})\D{{0,30}}?{_M}", ("line_height",)),
    (rf"\b(?:width|narrow(?:er|ed)|wider|widened)\D{{0,20}}?{_M}", ("width",)),
    (rf"{_M}\s+(?:wide|across)\b", ("width",)),
    (rf"\blength\D{{0,20}}?{_M}", ("length",)),
    (rf"{_M}\s+(?:long|from\s+front\s+to\s+back)\b", ("length",)),
    (rf"{_M}\s+(?:between|separat\w*)\b", ("back_to_mid", "mid_to_front")),
    (rf"\b(?:between\s+the\s+lines|gap)\D{{0,20}}?{_M}", ("back_to_mid", "mid_to_front")),
    (rf"(?P<n>{NUMBER_PATTERN})\s+(?:\w+\s+){{0,3}}?(?:behind|goal-side\s+of)\s+the\s+ball",
     ("behind_ball",)),
    (rf"(?P<n>{NUMBER_PATTERN})\s+(?:\w+\s+){{0,3}}?(?:ahead\s+of|in\s+front\s+of)\s+the\s+ball",
     ("ahead_of_ball",)),
))
# Words that make a number next to a metric its change, not its value ("pushed up 8 m", "2 more
# players behind the ball"); without one, the number is the value ("a line 38 m from goal").
CHANGE_WORDS = re.compile(
    r"\b(?:push\w*|step\w*|mov\w*|dropp\w*|drops?|retreat\w*|narrow\w+|wid\w+|stretch\w*|by|higher|"
    r"deeper|further|more|fewer|extra|less)\b", re.I,
)
SHAPE_NAMES = {"line_height": "line height", "width": "width", "area": "area", "length": "length",
               "back_to_mid": "gap between the lines", "mid_to_front": "gap between the lines",
               "behind_ball": "count behind the ball", "ahead_of_ball": "count ahead of the ball"}


def _row_numbers(row: Mapping, change: bool = True) -> set[float]:
    """A fact's value, and with `change` the size of its change from the minute before."""
    moved = {abs(float(row["change"]))} if change and row.get("change") is not None else set()
    return {float(row["value"])} | moved


def shape_reasons(text: str, evidence: list[dict]) -> list[str]:
    """Why a claim's words about team shape disagree with the shape facts it cites (none: they agree).
    `text` has its number words already in digits."""
    rows = [r for r in evidence if _is_shape(r)]
    if not rows and not SHAPE_TERMS.search(text):
        return []
    if not rows:
        term = SHAPE_TERMS.search(text).group()
        return [f"'{term}' is a claim about team shape: cite the shape fact it rests on"]
    reasons: list[str] = []
    named = {m.lower() for m in TEAM_WORD.findall(text)}
    if named and not named & {r["team"] for r in rows}:
        cited = sorted({r["team"] for r in rows})
        reasons.append(f"the cited shape facts are {cited}'s, not {sorted(named)}'s")
    teams = [(m.start(), m.group().lower()) for m in TEAM_WORD.finditer(text)]

    def of(at: int) -> list[dict]:
        """The cited shape facts a word at `at` is about: those of the team named last before it
        ("home pushed up while away dropped back"), or of every cited team when none is named."""
        before = [team for start, team in teams if start < at]
        return [r for r in rows if r["team"] == before[-1]] if before else rows

    for words, metric, on_value, on_change in SHAPE_WORDS:
        for m in words.finditer(text):
            facts = [r for r in of(m.start()) if r["metric"] == metric]
            name = SHAPE_NAMES[metric]
            if not facts:
                reasons.append(f"'{m.group()}' is about the {name}: cite that shape fact")
            elif on_change and not any(r.get("change") is not None and on_change(r["change"]) for r in facts):
                changes = [r.get("change") for r in facts]
                reasons.append(f"'{m.group()}' disagrees with the cited {name} change ({changes})")
            elif on_value and not any(on_value(r["value"]) for r in facts):
                values = [r["value"] for r in facts]
                reasons.append(f"'{m.group()}' disagrees with the cited {name} ({values} {facts[0]['unit']})")
    for pattern, metrics in SHAPE_NUMBERS:
        for m in pattern.finditer(text):
            n = m.group("n")
            facts = [r for r in of(m.start("n")) if r["metric"] in metrics]
            change = CHANGE_WORDS.search(m.group()) is not None
            if not any(float(n) in _row_numbers(r, change) for r in facts):
                reasons.append(f"number {n} is not the cited {SHAPE_NAMES[metrics[0]]}")
    return reasons


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
            if expected_field == "distance_m":
                values |= shape_values(evidence, "m")
            elif expected_field == "area_m2":
                values |= shape_values(evidence, "m²")
            elif expected_field == "players":  # a count of players: any count a bare number may be
                values |= allowed
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
    reasons += shape_reasons(text, evidence)
    reasons += play_reasons(claim.text, evidence)

    return Verdict(ok=not reasons, reasons=reasons)


# Words about play that a cited fact must show (Kian's blind labels, docs/eval/factcheck-human-labels.md).
# A long ball is a pass of 32 m or more: Opta's 35 yards (GROUNDING I11, *verify*).
LONG_BALL_M = 32
LONG_BALL = re.compile(r"\blong\s+(?:balls?|pass(?:es)?)\b", re.I)
# Play under pressure: said only with a cited pressure event (an opponent closing the ball down).
UNDER_PRESSURE = re.compile(
    r"\b(?:despite|under|amid)\s+(?:the\s+|heavy\s+|intense\s+|their\s+|sustained\s+)?pressure\b"
    r"|\bpressured\b", re.I,
)
# A connective that orders two moments in time. Joining an interception to the very pass it cut out
# makes one act two: the events record a cut-out pass twice, as the pass (its `interceptor`) and as
# the interception where the ball arrives.
BEFORE_AFTER = re.compile(r"\b(?:after|before|following|followed\s+by|preceded\s+by)\b", re.I)
WINS_IT = re.compile(r"intercept|\bcut\s+out\b|\bwins?\s+(?:it|the\s+ball)\b", re.I)
A_PASS = re.compile(r"\bpass(?:es|ed)?\b", re.I)


def _same_act(evidence: list[dict]) -> list[tuple[dict, dict]]:
    """(pass, interception) pairs that are one act: a cited pass cut out by a player, and his cited
    interception as the next cited event after it."""
    order = sorted((e for e in evidence if e.get("type")),
                   key=lambda e: (e.get("minute") or 0, e.get("clock") or ""))
    pairs = []
    for n, p in enumerate(order[:-1]):
        nxt = order[n + 1]
        if (p.get("type") == "pass" and p.get("outcome") == "fail" and p.get("interceptor")
                and nxt.get("type") == "interception" and nxt.get("player") == p["interceptor"]):
            pairs.append((p, nxt))
    return pairs


def play_reasons(text: str, evidence: list[dict]) -> list[str]:
    """What a claim says of the play that its cited facts must show."""
    reasons = []
    if LONG_BALL.search(text) and not any(
        e.get("type") == "pass" and (e.get("distance_m") or 0) >= LONG_BALL_M for e in evidence
    ):
        reasons.append(f"a long ball is a pass of {LONG_BALL_M} m or more: no cited pass is")
    if UNDER_PRESSURE.search(text) and not any(e.get("type") == "pressure" for e in evidence):
        reasons.append("play under pressure is said, but no cited event is a pressure event")
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        for m in BEFORE_AFTER.finditer(sentence):
            left, right = sentence[: m.start()], sentence[m.end():]
            if _same_act(evidence) and ((WINS_IT.search(left) and A_PASS.search(right))
                                        or (A_PASS.search(left) and WINS_IT.search(right))):
                p, i = _same_act(evidence)[0]
                reasons.append(f"{i['id']} is {p['id']} being cut out: one act, not one {m.group().lower()} "
                               "the other")
                break
    return reasons


# The highlights reel's fan words (ninety/highlights.py, LABELS) and the labels each may be said
# of: a "rocket" only of a ROCKET or a THUNDERBOLT (a screamer that is also a rocket), and so on.
# Words for what vision does not measure yet (where the ball crossed the goal mouth, the woodwork)
# or that no number defines (worldie) may be said of no moment (docs/eval/highlights-plan.md).
LABEL_WORDS = tuple((re.compile(p, re.I), frozenset(labels)) for p, labels in (
    (r"\bthunderbolts?\b", ("THUNDERBOLT",)),
    (r"\bscreamers?\b", ("SCREAMER", "THUNDERBOLT")),
    (r"\blong[\s-]ranger?\b|\bfrom\s+(?:distance|range)\b", ("LONG-RANGE", "SCREAMER", "THUNDERBOLT")),
    (r"\brockets?\b|\brocketed\b|\bpiledrivers?\b|\bblistering\b|\bthunderous\b|\bfierce\b|\bpowerful\b"
     r"|\bhammer(?:ed|s)?\b|\bblast(?:ed|s)?\b|\bnet[\s-]?buster\b", ("ROCKET", "THUNDERBOLT")),
    (r"\breflex(?:es)?\b|\bpoint[\s-]blank\b", ("REFLEX SAVE",)),
    (r"\btap[\s-]?in\b|\btapped\s+in\b|\bpoacher'?s?\b", ("TAP-IN",)),
    (r"\btop\s+bins\b|\btop\s+corner\b|\bbottom\s+corner\b|\bupper\s+90\b|\bcrossbar\b|\boff\s+the\s+(?:bar|post)\b"
     r"|\bwoodwork\b|\bpost\b|\bworldie\b|\bwonder[\s-]?goal\b|\bgolazo\b|\bbanger\b|\bbelter\b", ()),
))


def label_reasons(text: str, label: str) -> list[str]:
    """A caption may use a fan's word only of a moment the code gave that label: what earns it is
    a measured number (ninety/highlights.py), never the writer's taste."""
    return [f"'{m.group()}' is not said of a {label}: the code gave this moment no such label"
            for pattern, labels in LABEL_WORDS if label not in labels
            for m in [pattern.search(text)] if m]


# How the attack started (ninety/highlights.py, `origin`; the plan's Amendment 2). A caption may name
# a restart only of a moment whose origin is that restart. Counter-attacks are never given (the rule
# does not try them), so their words are always refused.
SET_PIECES = ("corner", "throw_in", "goal_kick", "free_kick", "penalty_kick", "kick_off")
ORIGIN_WORDS = tuple((re.compile(p, re.I), frozenset(origins)) for p, origins in (
    # "corner" the restart, not a part of the goal ("top corner", "far corner of the net")
    (r"(?<!top )(?<!far )(?<!near )(?<!upper )(?<!lower )(?<!bottom )\bcorners?(?:[\s-]kicks?)?\b"
     r"(?!\s+of\s+the)", ("corner",)),
    (r"\bthrow[\s-]?ins?\b", ("throw_in",)),
    (r"\bgoal[\s-]?kicks?\b", ("goal_kick",)),
    (r"\bkick[\s-]?offs?\b", ("kick_off",)),
    (r"\bset[\s-]?pieces?\b|\bdead[\s-]ball\b|\brestarts?\b", SET_PIECES),
    (r"\bfree[\s-]?kicks?\b", ("free_kick",)),
    (r"\bpenalt(?:y|ies)\b|\bspot[\s-]kicks?\b|\bfrom\s+the\s+spot\b", ("penalty_kick",)),
    (r"\bcounter(?:[\s-]?attack(?:s|ing)?)?\b|\bon\s+the\s+break\b", ()),
))


def origin_reasons(text: str, origin: str | None) -> list[str]:
    """A caption may say how the attack started only as the code found it (ninety/highlights.py)."""
    said = origin.replace("_", " ") if origin else "not seen"
    return [f"'{m.group()}' does not fit how this attack started ({said})"
            for pattern, origins in ORIGIN_WORDS if origin not in origins
            for m in [pattern.search(text)] if m]


def confidence_gate(
    claim: Claim, known: dict[str, dict], min_confidence: float = MIN_CONFIDENCE, team_view: bool = False
) -> Verdict:
    """Holds back a claim that cites a detected event the detector is not sure of.

    Only detected events carry a confidence (ninety/match/facts.compact); ground-truth events in
    the pre-M1 recordings have none and pass. A shape fact (ninety/intel/shape.py) is unsure when
    too few of the team were tracked for it (`confident` false), and holds a claim the same way. A
    claim that names a team ("home", "away") is held too unless every detected event it cites had
    its side told with `team_confidence` above MIN_TEAM_CONFIDENCE; an unknown side counts as
    unsure. With `team_view` (a variant written from one club's side, whatever its words: "our
    side", "they") every claim is a team claim. The verdict's category, `low_confidence`, makes the
    claim held, not rejected (ninety/agents/contracts.status_for): the claim may be right, but
    nothing airs until a confident detection supports it.
    """
    reasons = [
        f"event {i} was detected with confidence {known[i]['confidence']:.2f}, "
        f"below {min_confidence:.2f}: cite a confident detection"
        for i in claim.evidence
        if i in known and known[i].get("confidence") is not None and known[i]["confidence"] < min_confidence
    ] + [
        f"shape fact {i} rests on {known[i]['tracked']} of {known[i]['of']} {known[i]['team']} players "
        f"tracked, fewer than the {known[i]['need']} it needs: cite a confident shape fact"
        for i in claim.evidence
        if i in known and _is_shape(known[i]) and not known[i]["confident"]
    ]
    if TEAM_NAMED.search(claim.text) or team_view:
        for i in claim.evidence:
            event = known.get(i, {})
            side = event.get("team_confidence")
            # A detected event (it has a confidence) whose side is unknown counts as unsure.
            if not side_known(event):
                told = "unknown" if side is None else f"{side:.2f}"
                reasons.append(f"event {i}'s side was told with confidence {told}, not above "
                               f"{MIN_TEAM_CONFIDENCE:.2f}: a claim naming a team waits for a surer side")
    return Verdict(ok=not reasons, reasons=reasons, category="low_confidence" if reasons else None)


def parse_claim(text: str) -> Claim:
    """A writer's reply, {"text": ..., "evidence": [...]}, as a Claim; the JSON may sit inside prose."""
    body = re.search(r"\{.*\}", text, re.S)
    data = json.loads(body.group() if body else text)
    if not isinstance(data, dict):
        raise ValueError(f"the Analyst's reply is not a JSON object: {text[:80]!r}")
    return Claim(text=str(data.get("text", "")), evidence=[str(i) for i in data.get("evidence", [])])
