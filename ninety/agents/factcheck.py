"""The code half of the fact-checking agent.

A claim passes only if every event it cites exists, every player it names appears in that
evidence, and every number it states can be read off the evidence: a cited field, a count of
cited events, or the minute. Anything else is rejected with a reason the writer can act on.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

# A number standing on its own: not part of an id like "e00042" or a player like "h7".
# A sentence-ending period after it still counts ("in minute 2.").
NUMBER = re.compile(r"(?<![\w.])\d+(?:\.\d+)?(?!\w)(?!\.\d)")
# Player ids are a team letter and a squad number, e.g. h7 or a10.
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


def allowed_numbers(events: list[dict]) -> set[float]:
    values: set[float] = {float(len(events))}
    for event in events:
        values.update(float(event[name]) for name in NUMBER_FIELDS if name in event)
    values.update(float(n) for n in Counter(e["type"] for e in events).values())
    values.update(float(n) for n in Counter((e["team"], e["type"]) for e in events).values())
    return values


def check(claim: Claim, known: dict[str, dict]) -> Verdict:
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
        if value not in allowed:
            reasons.append(f"number {match.group()} is not in the cited evidence")

    players = {e["player"] for e in evidence} | {e.get("receiver") for e in evidence}
    for name in sorted(set(PLAYER.findall(claim.text)) - players):
        reasons.append(f"player {name} does not appear in the cited evidence")

    return Verdict(ok=not reasons, reasons=reasons)
