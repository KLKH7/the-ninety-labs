"""What a screen shows for a tracked player: never his raw track id.

A track id ("h-t2033") is the tracker's label, not a name, a shirt or a role: it is checked (the
fact-checker matches it against the cited events) but never aired. On every text a screen shows, the
graphics, the agents' insights and the claim trace, `render` says it as the voice does
(ninety/speech/describe.py, `_names`): "a London player", then "a team-mate" for another of his side,
"the same player" when named again; and "a player", then "another player", when his side was not told
surely (`sure`, the bundle's `sides_known`). The numbers and the rest of the text are untouched, so
what is shown carries exactly what was checked. A squad id ("h4", the simulator's) is a shirt number
and is left as it is.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

TRACK_ID = re.compile(r"\b([ha])-t(\d+)\b")
SENTENCE_START = re.compile(r"(^['\"]?|[.!?]\s+['\"]?)([a-z])")  # a quoted draft starts a sentence too


def render(text: str, sure: Iterable[str], clubs: dict[str, str] | None = None) -> str:
    """The text with each track id said as a fan reads it (module docstring)."""
    sure = set(sure)
    seen: dict[str, str] = {}
    sides: set[str] = set()

    def say(m: re.Match) -> str:
        track = m[0]
        if track in seen:
            return "the same player"
        side = "home" if m[1] == "h" else "away"
        if track in sure:
            phrase = "a team-mate" if side in sides else f"a {(clubs or {}).get(side, side)} player"
            sides.add(side)
        else:
            unsure_before = any(p in ("a player", "another player") for p in seen.values())
            phrase = "another player" if unsure_before else "a player"
        seen[track] = phrase
        return phrase

    out = TRACK_ID.sub(say, text)
    return SENTENCE_START.sub(lambda m: m[1] + m[2].upper(), out) if out != text else out


def cues(rows: list[dict], sure: Iterable[str], clubs: dict[str, str] | None = None) -> list[dict]:
    """Every cue with its shown text rendered."""
    sure = set(sure)
    return [{**c, "text": render(c["text"], sure, clubs)} if isinstance(c.get("text"), str) else c
            for c in rows]


def trace(claims: list[dict], sure: Iterable[str], clubs: dict[str, str] | None = None) -> list[dict]:
    """The claim trace as the viewer shows it: each claim's text and each step's detail rendered."""
    sure = set(sure)
    return [{**c, "text": render(c.get("text") or "", sure, clubs),
             "steps": [{**s, "detail": render(s.get("detail") or "", sure, clubs)}
                       for s in c.get("steps", [])]}
            for c in claims]
