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


# A ball speed as the bundle's words write or say it, with what joins it to the sentence (", " or
# " at "), which goes with it: the same reading as the viewer's gate (web/viewer/src/speed.ts).
# The fact-checker's other units too (factcheck.SPEED_UNITS: kmh, k.p.h, km per hour), so an unsayable
# speed in one of them leaves the words as well. A speed in spelled-out words ("one hundred km/h") is
# not found here: an aired claim may state a measured speed only in digits (factcheck.SHOWN_SPEED).
SPEED_TEXT = re.compile(
    r"(,\s*|\s+at\s+|\s+)?(\d+(?:\.\d+)?)\s*"
    r"(km/h|kph|kmh|k\.p\.h\.?|(?:km|kilomet(?:re|er)s?)\s+(?:an|per)\s+hour)", re.I)


def speeds(text: str, cited: Iterable[dict]) -> str:
    """The text with each ball speed no cited event may state taken out (factcheck.sayable_speed): a
    screen bands every speed it shows once the bundle's speed is measured (manifest.speed), so a held
    draft's or a shot's must not be there to band."""
    from ninety.agents.factcheck import sayable_speed

    ok = {float(e["ball_speed_kmh"]) for e in cited if sayable_speed(e)}
    ok |= {float(round(v)) for v in ok}

    def keep(m: re.Match) -> str:
        return m[0] if float(m[2]) in ok else ""

    out = SPEED_TEXT.sub(keep, text)
    if out == text:
        return text
    out = re.sub(r"\(\s*\)", "", out)  # "(101 km/h)" leaves no empty brackets
    out = re.sub(r"\s{2,}", " ", out)
    out = re.sub(r",([.!?'])", r"\1", re.sub(r"\s+([,.!?:])", r"\1", out))
    return re.sub(r":([.!?])", r"\1", out).strip()  # "Shot speed: 101 km/h." is "Shot speed." 


def gate_speeds(
    cue_rows: list[dict], claims: list[dict], events: list[dict]
) -> tuple[list[dict], list[dict]]:
    """Cues and the claim trace with every speed their cited events may not state taken out."""
    by_id = {e["id"]: e for e in events}

    def cited(ids) -> list[dict]:
        return [by_id[i] for i in ids or () if i in by_id]

    rows = [{**c, "text": speeds(c["text"], cited(c.get("evidence")))}
            if isinstance(c.get("text"), str) else c for c in cue_rows]
    traced = [{**c, "text": speeds(c.get("text") or "", cited(c.get("evidence"))),
               "steps": [{**s, "detail": speeds(s.get("detail") or "", cited(c.get("evidence")))}
                         for s in c.get("steps", [])]} for c in claims]
    return rows, traced
