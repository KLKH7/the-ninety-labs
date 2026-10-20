"""The code half of the fact-checking agent.

A claim passes only if every event it cites exists, every player it names appears in that
evidence, and every number it states can be read off the evidence: a cited field, a count of
cited events, or the minute. Anything else is rejected with a reason the writer can act on.

Evidence may also hold computed facts (ninety/intel/stats.py `Fact.as_dict()`: metric, value, unit,
scope). A cited fact's value counts only when it is written with the fact's unit ("31.2 km/h" for a
km/h fact), never as a bare number, and a fact scoped to a player (`player:h7...`) cites that player.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

# A number standing on its own: not part of an id like "e00042" or a player like "h7".
# A sentence-ending period after it still counts ("in minute 2."), and so does an English ordinal
# ("the 9th minute", "his 3rd pass"): the number is the `n` group.
NUMBER_PATTERN = r"\d+(?:\.\d+)?"
NUMBER = re.compile(rf"(?<![\w.])(?P<n>{NUMBER_PATTERN})(?:st|nd|rd|th)?(?!\w)(?!\.\d)")
DISTANCE_UNITS = r"(?:m|metre|metres|meter|meters)"
SPEED_UNITS = r"(?:km/h|kph)"
DISTANCE_NUMBER = re.compile(rf"(?P<number>{NUMBER_PATTERN})\s*{DISTANCE_UNITS}\b", re.I)
SPEED_NUMBER = re.compile(rf"(?P<number>{NUMBER_PATTERN})\s*{SPEED_UNITS}\b", re.I)
MINUTE_NUMBER = re.compile(
    rf"(?:\bminute\s+(?P<minute_a>{NUMBER_PATTERN})\b|"
    rf"(?P<minute_b>{NUMBER_PATTERN})\s+minutes?\b|"
    rf"(?P<minute_c>{NUMBER_PATTERN})'|"
    rf"\b(?P<minute_d>{NUMBER_PATTERN})(?:st|nd|rd|th)\s+minute\b)",
    re.I,
)
SECOND_NUMBER = re.compile(
    rf"(?:\bsecond\s+(?P<second_a>{NUMBER_PATTERN})\b|"
    rf"(?P<second_b>{NUMBER_PATTERN})\s+seconds?\b|"
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
    clock_spans = [range(match.start(), match.end()) for match in CLOCK.finditer(claim.text)]
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
    for match in NUMBER.finditer(claim.text):
        if any(match.start() in span for span in clock_spans):
            continue
        value = float(match.group("n"))
        expected_field = _number_field(claim.text, match.start())
        if expected_field:
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
        elif value not in allowed and not any(
            float(f["value"]) == value and _unit_follows(claim.text, match.end(), str(f["unit"]))
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
