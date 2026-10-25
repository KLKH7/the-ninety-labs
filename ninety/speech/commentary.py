"""The commentary track: a commentator's voice for the match, from the live path's checked output.

    track = commentary(events, cues, clubs)     # what to say and when, never two lines at once
    write(track, out)                           # commentary.json in the bundle

The phone's commentary toggle plays it (web/phone). Its audio is made with the rest of the
bundle's read-aloud lines in the pinned voice (ninety/speech/bundle.py, `--voice-audio`), keyed by
each line's text, so `text` is exactly what is said.

What it says, and only this:
- a detected goal, shot or restart (kickoff, out of play, set piece, half-time), each line written
  here by code from one detection at or above the confidence gate (`factcheck.MIN_CONFIDENCE`), passed
  through the fact-checker's code half and its confidence gate (`factcheck.check`,
  `confidence_gate`). A club is named only when that event's side was told surely
  (`factcheck.side_known`), and never a player: the live path has no name it can vouch for yet;
- a verified insight (an `insight` cue marked verified: a claim the fact-checking agent accepted),
  as the Describer says it (`describe.spoken`), which names a side only where it was told surely.

Nothing here reads ground truth: only the detected events and the cues the live path wrote.

Pace (design, the Coordinator's brief): one voice; a line starts within MAX_LAG_S of its moment and
leaves at least GAP_S of silence before the next. Lines are placed by priority (goals, then shots,
then restarts, then insights) and, within one, in time order; a line that cannot fit falls back to
its short form, then is dropped with the reason. So a goal is never crowded out by an insight.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from ninety.agents.factcheck import Claim, check, confidence_gate, side_known
from ninety.match.facts import compact
from ninety.speech import describe, voice

FORMAT = 1
PRIORITY = {"goal": 0, "shot": 1, "restart": 2, "insight": 3}
RESTARTS = ("kickoff", "out_of_play", "set_piece", "half_time")
MAX_LAG_S = describe.MAX_LAG_S  # the Describer's limit: a line said late is about the wrong play
GAP_S = 1.0  # design: the silence a commentator leaves between calls, so the crowd is heard
# A pitch line, in metres from the near touchline or the left goal line (schemas/match_event: x 0..105,
# y 0..68). Vision places an out-of-play event where the ball crossed; within a metre of a touchline
# it went over the touchline, where Law 15 restarts play with a throw-in.
TOUCHLINE_M = 1.0
SHOT_SAID = {"on_target": "on target", "off_target": "wide", "blocked": "blocked"}


@dataclass(frozen=True)
class Call:
    """One thing the commentator could say: its checked versions, longest first."""

    key: str  # the event id, or the insight cue's id
    t: float  # match time of the moment
    kind: str  # a PRIORITY key
    evidence: list[str]
    versions: list[str]  # what is said, already checked
    sides: bool  # whether the side words in it were told surely


@dataclass
class Line:
    """One call in commentary.json (the format agreed with the big-screen player, web/viewer)."""

    id: str
    t: float  # match seconds the call starts, the clock of cues and events
    t_end: float
    text: str  # exactly what is said
    event: str | None  # the detected event called, or None for an insight
    kind: str
    priority: int
    short: bool
    t_event: float
    evidence: list[str]
    audio: str | None = None  # the call's audio, relative to the bundle: set by ninety/speech/bundle.py


def _side(event: dict) -> str | None:
    """"home" or "away" when the event's side was told surely; else None, and no side is said."""
    return event["team"] if event.get("team") in ("home", "away") and side_known(event) else None


def event_versions(event: dict) -> tuple[str, list[str]] | None:
    """(kind, versions) for one detected event, in its checked form ("home" and "away" for the
    sides, which the voice says as the clubs); None for an event a commentator does not call."""
    kind, side = event["type"], _side(event)
    if kind == "goal":
        return "goal", ([f"Goal! {side} score!", "Goal!"] if side else ["Goal!"])
    if kind == "shot":
        said = SHOT_SAID.get(event.get("outcome") or "")
        who = f"{side} shoot" if side else "A shot"
        return "shot", ([f"{who}, {said}.", f"{who}."] if said else [f"{who}."])
    if kind == "kickoff":
        return "restart", [f"{side} kick off." if side else "Kick-off."]
    if kind == "half_time":
        return "restart", ["Half-time."]
    if kind == "out_of_play":
        over_touchline = event["y"] <= TOUCHLINE_M or event["y"] >= describe.PITCH_WIDTH_M - TOUCHLINE_M
        return "restart", ["It's gone out for a throw." if over_touchline else "It's gone out of play."]
    if kind == "set_piece":
        return "restart", ["A set piece."]
    return None


def calls(events: list[dict], cues: list[dict], clubs: dict[str, str] | None = None
          ) -> tuple[list[Call], list[dict]]:
    """Every call the commentator may make, each checked, and what was refused and why."""
    known = {e["id"]: compact(e) for e in events}
    by_id = {e["id"]: e for e in events}
    refused: list[dict] = []

    def checked(texts: list[str], evidence: list[str]) -> list[str]:
        ok = []
        for text in texts:
            claim = Claim(text, evidence)
            verdict = check(claim, known)
            if verdict.ok:
                verdict = confidence_gate(claim, known)
            if verdict.ok:
                ok.append(text)
            else:
                refused.append({"evidence": evidence, "text": text, "reason": "; ".join(verdict.reasons)})
        return ok

    out: list[Call] = []
    for event in events:
        written = event_versions(event)
        if written is None:
            continue
        kind, versions = written
        versions = checked(versions, [event["id"]])  # the confidence gate holds an unsure detection
        if versions:
            out.append(Call(event["id"], event["t"], kind, [event["id"]], versions, _side(event) is not None))
    for cue in cues:
        if cue.get("kind") != "insight" or cue.get("persona") not in (None, "analyst"):
            continue
        if cue.get("verified") is not True:
            refused.append({"evidence": cue["evidence"], "text": cue["text"], "reason": "not verified"})
            continue
        if not cue["evidence"] or any(i not in by_id for i in cue["evidence"]):
            refused.append({"evidence": cue["evidence"], "text": cue["text"],
                            "reason": "cites unknown events"})
            continue
        versions = checked([cue["text"]], list(cue["evidence"]))
        if versions:
            sides = all(side_known(by_id[i]) for i in cue["evidence"])
            out.append(Call(cue["id"], cue["t_in"], "insight", list(cue["evidence"]), versions, sides))
    return out, refused


def said(call: Call, n: int, clubs: dict[str, str] | None) -> str:
    """What the voice says for version `n` of a call: the sides as their clubs, ids never as a
    number or a name (`describe.spoken`, which names a side only where it was told surely)."""
    return describe.spoken(call.versions[n], call.sides, compact=n > 0, clubs=clubs)


def schedule(found: list[Call], clubs: dict[str, str] | None = None,
             duration=describe.estimated_seconds) -> tuple[list[Line], list[dict]]:
    """Place each call by priority, then time: at the earliest start within MAX_LAG_S of its moment
    that leaves GAP_S of silence on both sides of every line already placed; its short form if the
    full one does not fit; else dropped, with why."""
    placed: list[Line] = []
    dropped: list[dict] = []
    for call in sorted(found, key=lambda c: (PRIORITY[c.kind], c.t, c.key)):
        line = None
        for n in range(len(call.versions)):
            text = said(call, n, clubs)
            seconds = duration(text)
            start = _first_gap(placed, call.t, seconds)
            if start is not None:
                event = None if call.kind == "insight" else call.key
                line = Line(f"cm-{call.key}", round(start, 2), round(start + seconds, 2), text, event,
                            call.kind, PRIORITY[call.kind], n > 0, call.t, call.evidence)
                break
        if line is None:
            dropped.append({"id": call.key, "t": call.t, "reason": "no room within the lag limit"})
            continue
        placed.append(line)
    return sorted(placed, key=lambda line: line.t), dropped


def _first_gap(placed: list[Line], t: float, seconds: float) -> float | None:
    """The earliest start in [t, t + MAX_LAG_S] with GAP_S clear of every placed line, or None."""
    starts = [t] + [p.t_end + GAP_S for p in placed if t <= p.t_end + GAP_S <= t + MAX_LAG_S]
    for start in sorted(starts):
        end = start + seconds
        if all(end + GAP_S <= p.t or start >= p.t_end + GAP_S for p in placed):
            return start
    return None


def commentary(events: list[dict], cues: list[dict], clubs: dict[str, str] | None = None) -> dict:
    """commentary.json's body for a bundle's detected events and live cues."""
    found, refused = calls(events, cues, clubs)
    lines, dropped = schedule(found, clubs)
    return {"format": FORMAT, "voice": voice.VOICE, "gap_s": GAP_S, "max_lag_s": MAX_LAG_S,
            "lines": [asdict(line) for line in lines], "dropped": dropped, "refused": refused}


def write(body: dict, out: Path) -> dict:
    """commentary.json in `out`; returns the summary for the bundle's manifest."""
    (out / "commentary.json").write_text(json.dumps(body, indent=1) + "\n")
    return {"count": len(body["lines"]), "dropped": len(body["dropped"]), "refused": len(body["refused"]),
            "chars": sum(len(line["text"]) for line in body["lines"])}
