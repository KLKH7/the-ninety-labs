"""The commentary track: a commentator's voice for the match, from the live path's checked output.

    track = commentary(events, cues, clubs)     # what to say and when, never two lines at once
    write(track, out)                           # commentary.json in the bundle

The phone's commentary toggle plays it (web/phone). Its audio is made with the rest of the
bundle's read-aloud lines in the pinned voice (ninety/speech/bundle.py, `--voice-audio`), keyed by
each line's text, so `text` is exactly what is said.

What it says, and only this:
- a detected goal, shot or restart (kickoff, out of play, set piece, half-time), each line written
  here by code from one vision detection (source "vision", with a confidence) at or above the
  confidence gate (`factcheck.MIN_CONFIDENCE`), passed
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

Time: lines are placed on the VIDEO's clock (match time through the clip's Timeline), since a
condensed match cuts dead balls and two moments either side of a cut are seconds apart on screen
however far apart in the match; each line also carries its match time `t` for the player. Lengths
are estimated from the words; once the bundle is voiced, `refit` replaces each estimate with the
audio's own length and drops, lowest priority first, any line that would then overlap.
"""

from __future__ import annotations

import json
import math
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path

from ninety.agents.factcheck import Claim, check, confidence_gate, side_known
from ninety.match.facts import compact
from ninety.match.timeline import Timeline
from ninety.speech import describe, voice

FORMAT = 1
PRIORITY = {"goal": 0, "shot": 1, "restart": 2, "insight": 3}
MAX_LAG_S = describe.MAX_LAG_S  # the Describer's limit: a line said late is about the wrong play
GAP_S = 1.0  # design: the silence a commentator leaves between calls, so the crowd is heard
SHOT_SAID = {"on_target": "on target", "off_target": "wide", "blocked": "blocked"}
# A detected set piece's restart (schemas/match_event.schema.json `restart`), with its taker's side
# and without it.
RESTART_SAID = {
    "corner": ("Corner to {side}.", "A corner."),
    "goal_kick": ("Goal kick to {side}.", "A goal kick."),
    "throw_in": ("{side} throw.", "A throw-in."),
    "free_kick": ("Free kick to {side}.", "A free kick."),
    "penalty_kick": ("Penalty to {side}!", "A penalty!"),
}
Seconds = Callable[[str], float]  # what is said -> how long it takes to say


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
    v: float  # video seconds the call starts: the clock lines are spaced on
    v_end: float
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
        # Only that it went out: which restart follows is vision's own reading (a set piece's
        # `restart`), never inferred here from where the ball crossed.
        return "restart", ["It's gone out of play."]
    if kind == "set_piece":
        # Which restart (vision's `restart`, #325): `team` is the side taking it, named only when sure.
        said = RESTART_SAID.get(event.get("restart") or "")
        if said is None:
            return "restart", ["A set piece."]
        sure, unsure = said
        return "restart", [sure.format(side=side)] if side else [unsure]
    return None


def calls(events: list[dict], cues: list[dict]) -> tuple[list[Call], list[dict]]:
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
                verdict = confidence_gate(claim, known)  # it holds an unsure detection too
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
        if event.get("source") != "vision" or event.get("confidence") is None:
            reason = "not a vision detection with a confidence: the commentary calls only those"
            refused.append({"evidence": [event["id"]], "text": None, "reason": reason})
            continue
        kind, versions = written
        versions = checked(versions, [event["id"]])
        if versions:
            out.append(Call(event["id"], event["t"], kind, [event["id"]], versions, _side(event) is not None))
    for cue in cues:
        # The Producer's insight, in English: the Personalizer's persona and language variants are
        # versions of the same claim, and a commentator calls a moment once.
        if cue.get("kind") != "insight" or cue.get("persona") != "analyst" or cue.get("lang", "en") != "en":
            continue
        evidence = list(cue.get("evidence") or [])
        if cue.get("verified") is not True:
            refused.append({"evidence": evidence, "text": cue.get("text"), "reason": "not verified"})
            continue
        if not evidence or any(i not in by_id for i in evidence):
            refused.append({"evidence": evidence, "text": cue.get("text"), "reason": "cites unknown events"})
            continue
        versions = checked([cue["text"]], evidence)
        if versions:
            sides = all(side_known(by_id[i]) for i in evidence)
            out.append(Call(cue["id"], cue["t_in"], "insight", evidence, versions, sides))
    return out, refused


def said(call: Call, n: int, clubs: dict[str, str] | None) -> str:
    """What the voice says for version `n` of a call: the sides as their clubs, ids never as a
    number or a name (`describe.spoken`, which names a side only where it was told surely)."""
    return describe.spoken(call.versions[n], call.sides, compact=n > 0, clubs=clubs)


def _up(t: float) -> float:
    """A time to the hundredth, never earlier than `t`: a line never starts before its moment."""
    return math.ceil(round(t * 100, 6)) / 100


def schedule(found: list[Call], clubs: dict[str, str] | None = None,
             duration: Seconds = describe.estimated_seconds,
             timeline: Timeline | None = None) -> tuple[list[Line], list[dict]]:
    """Place each call by priority, then time, on the video's clock: at the earliest start within
    MAX_LAG_S of its moment that leaves GAP_S of silence on both sides of every line already placed;
    its short form if the full one does not fit; else dropped, with why."""
    video = timeline.to_video if timeline else (lambda t: t)
    match = timeline.to_match if timeline else (lambda v: v)
    placed: list[Line] = []
    dropped: list[dict] = []
    for call in sorted(found, key=lambda c: (PRIORITY[c.kind], c.t, c.key)):
        at = video(call.t)
        line = None
        for n in range(len(call.versions)):
            text = said(call, n, clubs)
            seconds = duration(text)
            start = _first_gap(placed, at, seconds)
            if start is not None:
                start = _up(start)
                end = _up(start + seconds)
                event = None if call.kind == "insight" else call.key
                t = _up(match(start))
                line = Line(f"cm-{call.key}", t, _up(t + seconds), text, event, call.kind,
                            PRIORITY[call.kind], n > 0, call.t, call.evidence, start, end)
                break
        if line is None:
            dropped.append({"id": call.key, "t": call.t, "reason": "no room within the lag limit"})
            continue
        placed.append(line)
    return sorted(placed, key=lambda line: line.v), dropped


def _first_gap(placed: list[Line], at: float, seconds: float) -> float | None:
    """The earliest start in [at, at + MAX_LAG_S] with GAP_S clear of every placed line, or None."""
    starts = [at] + [p.v_end + GAP_S for p in placed if at <= p.v_end + GAP_S <= at + MAX_LAG_S]
    for start in sorted(starts):
        end = start + seconds
        if all(end + GAP_S <= p.v or start >= p.v_end + GAP_S for p in placed):
            return start
    return None


def refit(body: dict, seconds: dict[str, float]) -> dict:
    """The track with each line's measured length (`seconds`, by line id, from its audio) in place
    of the estimate: kept by priority, then time; a line that would now overlap one kept before it
    is dropped, with why. Starts never move: a line is said at its moment or not at all."""
    kept: list[dict] = []
    for line in sorted(body["lines"], key=lambda li: (li["priority"], li["v"], li["id"])):
        length = seconds.get(line["id"])
        if length is not None:
            line = {**line, "v_end": _up(line["v"] + length), "t_end": _up(line["t"] + length)}
        if all(line["v_end"] + GAP_S <= k["v"] or line["v"] >= k["v_end"] + GAP_S for k in kept):
            kept.append(line)
        else:
            body["dropped"].append({"id": line["id"], "t": line["t_event"],
                                    "reason": "its audio runs longer than estimated: no room"})
    body["lines"] = sorted(kept, key=lambda li: li["v"])
    return body


def commentary(events: list[dict], cues: list[dict], clubs: dict[str, str] | None = None,
               timeline: Timeline | None = None) -> dict:
    """commentary.json's body for a bundle's detected events and live cues."""
    found, refused = calls(events, cues)
    lines, dropped = schedule(found, clubs, timeline=timeline)
    return {"format": FORMAT, "voice": voice.VOICE, "gap_s": GAP_S, "max_lag_s": MAX_LAG_S,
            "lines": [asdict(line) for line in lines], "dropped": dropped, "refused": refused}


def write(body: dict, out: Path) -> dict:
    """commentary.json in `out`; returns the summary for the bundle's manifest."""
    (out / "commentary.json").write_text(json.dumps(body, indent=1) + "\n")
    return summary(body)


def summary(body: dict) -> dict:
    return {"count": len(body["lines"]), "dropped": len(body["dropped"]), "refused": len(body["refused"]),
            "chars": sum(len(line["text"]) for line in body["lines"])}
