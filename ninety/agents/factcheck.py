"""The code half of the fact-checking agent.

A claim passes only if every event it cites exists, every player it names appears in that
evidence, and every number it states can be read off the evidence: a cited field, a count of
cited events, or the minute. Anything else is rejected with a reason the writer can act on.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

# A number standing on its own: not part of an id like "e00042" or a player like "h7".
# A sentence-ending period after it still counts ("in minute 2.").
NUMBER_PATTERN = r"\d+(?:\.\d+)?"
NUMBER = re.compile(rf"(?<![\w.]){NUMBER_PATTERN}(?!\w)(?!\.\d)")
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
# A clock form, "12:34": the part before the colon must be a cited `minute` and the part after a
# cited `second`, the convention agents read today (an event at 1:28 of play is minute 2, second
# 28, and agents write "2:28"). Known issue: the scorebug shows the elapsed clock, 01:28.
CLOCK_MINUTE = re.compile(r"(?<![\w.:])(?P<number>\d{1,3}):\d{2}(?!\d)")
# The synthetic squads' player ids (h1..h11, a1..a11). Names in this form are always checked,
# even when the player is in no known event, so a claim cannot name an uninvolved player.
PLAYER = re.compile(r"\b[ha](?:[1-9]|1[01])\b")
NUMBER_FIELDS = ("minute", "second", "ball_speed_kmh", "distance_m")


@dataclass
class Claim:
    text: str
    evidence: list[str]


@dataclass
class Verdict:
    ok: bool
    reasons: list[str] = field(default_factory=list)
    category: str | None = None


def _number_field(text: str, start: int) -> str | None:
    if any(m.start("number") == start for m in CLOCK_MINUTE.finditer(text)):
        return "minute"
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
            for value in (event.get("player"), event.get("receiver"))
            if value
        ]
    else:
        values = [
            item.get("id") if isinstance(item, Mapping) else item
            for item in roster
        ]
    return {str(value) for value in values if value}


def allowed_numbers(events: list[dict]) -> set[float]:
    values: set[float] = {float(len(events))}
    for event in events:
        values.update(float(event[name]) for name in NUMBER_FIELDS if name in event)
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
    for match in NUMBER.finditer(claim.text):
        value = float(match.group())
        expected_field = _number_field(claim.text, match.start())
        if expected_field:
            values = {
                float(event[expected_field])
                for event in evidence
                if event.get(expected_field) is not None
            }
            if value not in values:
                reasons.append(
                    f"number {match.group()} is not a cited {expected_field}"
                )
        elif value not in allowed:
            reasons.append(f"number {match.group()} is not in the cited evidence")

    cited_players = {
        value
        for event in evidence
        for value in (event.get("player"), event.get("receiver"))
        if value
    }
    named_players = {
        player_id
        for player_id in _roster_ids(known, roster)
        if re.search(rf"(?<!\w){re.escape(player_id)}(?!\w)", claim.text)
    } | set(PLAYER.findall(claim.text))
    for name in sorted(named_players - cited_players):
        reasons.append(f"player {name} does not appear in the cited evidence")

    return Verdict(ok=not reasons, reasons=reasons)
