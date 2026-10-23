"""The Describer: a spoken track for blind and low-vision fans, from the live path's output.

    descriptions = describe(events, cues)        # what to say, when, and where in stereo
    write_track(descriptions, out, t_start)      # audio.json, description.vtt, and audio cues

What it reads is what the live path already gates (ninety/agents/live.py):
- the detected events, each line written here by code from one confident detection (the same
  `MIN_CONFIDENCE` the template graphics air on) and passed through the fact-checker's code half
  (`factcheck.check`): every number and player it says is read off that event;
- the verified insight cues (kind `insight`, `verified` true): the claims the fact-checking agent
  accepted. A rejected or held claim never becomes a cue, and the Describer speaks no cue that is
  not marked verified, so it never speaks either;
- with `shape` (team-shape facts from tracked positions, ninety/intel/shape.py), at most one plain
  sentence a minute on how a team's shape moved ("Home's back line has pushed up 8 metres"), said
  only from a confident fact whose change is larger than tracking error could make, and passed
  through `factcheck.check` and its confidence gate like every other line.

Pace: one voice, never two lines at once, and every line starts within `MAX_LAG_S` of its event.
When the play outruns the voice, a line falls back to its short form, then is dropped, never
delayed; a shot or goal coming up is protected from being pushed late by a pass before it.

Stereo: `pan` follows the ball's pitch x where the event happens. The main camera looks across
the pitch from the near touchline (ninety/render/camera.py), so x 0 is the left of its view
and x 105 the right: pan = x / 52.5 - 1.

Spoken form: the checked line names players by their ids ("h4"); the voice says "Home 4", and
units are said in full. The substitution is fixed (`spoken`), so what is said is what was checked.

Durations: offline (`estimated_seconds`) from a word count; with real synthesis (`--speech
azure` in ninety-e2e) the measured length of the audio replaces the estimate before scheduling.
"""

from __future__ import annotations

import io
import json
import re
import wave
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from xml.sax.saxutils import escape

from jsonschema import validate

from ninety.agents.contracts import Description
from ninety.agents.cues import SCHEMA, _pass_text
from ninety.agents.factcheck import MIN_CONFIDENCE, Claim, check, confidence_gate
from ninety.match.facts import compact
from ninety.match.timeline import Timeline

PITCH_LENGTH_M = 105.0  # schemas/match_event.schema.json: x 0..105
PITCH_WIDTH_M = 68.0
# The brief's requirement for this track: a line is said within 2 s of what it describes.
MAX_LAG_S = 2.0
# Design: a breath between lines, so two descriptions do not run into one sentence.
GAP_S = 0.3
# Design estimate of a neural voice at its default rate, for offline timing only. Replaced by
# the measured audio length whenever lines are synthesised; logged per line as `duration_source`.
WORDS_PER_SECOND = 2.6
LEAD_IN_S = 0.15  # design: the voice's silence before the first word
VOICE = "en-GB-RyanNeural"
LANG = "en-GB"
SLOT = "audio"

# Lower is more important: what keeps its place when there is no time for everything.
PRIORITY = {"goal": 0, "shot": 1, "insight": 2, "interception": 3, "tackle": 3, "pass": 4, "kickoff": 4,
            "shape": 4}
# A shape change is said only when it is larger than tracking error could make it: each minute's
# value is within the position error (ninety/intel/shape.POSITION_ERROR_M, 1.26 m) of the truth, so
# their difference is within twice that, 2.52 m; the smallest whole-metre change past it is 3 m.
SHAPE_CHANGE_M = 3
# What is said about each shape change, by its sign: plain words a listener needs no diagram for.
SHAPE_SAID = {
    ("line_height", 1): "{team}'s back line has pushed up {n} m.",
    ("line_height", -1): "{team}'s back line has dropped back {n} m.",
    ("width", -1): "{team} have narrowed by {n} m.",
    ("width", 1): "{team} have widened by {n} m.",
}

# Thirds of the camera's view, and of the pitch's width from the near touchline. Design: thirds
# are how a commentator places play ("down the left", "in the middle"), coarse enough to hear.
ACROSS = ("on the left", "in the middle", "on the right")
DEPTH = ("near side", None, "far side")


@dataclass(frozen=True)
class Line:
    """One thing the Describer could say: its versions longest first, all already checked."""

    key: str  # the event id, or the insight cue's id
    t: float  # match time of what it describes
    priority: int
    pan: float
    evidence: list[str]
    versions: list[str]  # checked text (player ids, units as written), full form first
    source: str  # "event" or "shape" (written here) or "insight" (a verified claim)


@dataclass
class Said:
    id: str
    event: str
    t_event: float
    t_in: float
    t_out: float
    lag_s: float
    pan: float
    text: str  # the checked form
    spoken: str
    ssml: str
    short: bool
    source: str
    evidence: list[str]
    duration_s: float
    duration_source: str  # "estimated" or "measured"
    file: str | None = None
    synth_s: float | None = None


@dataclass
class Track:
    said: list[Said]
    dropped: list[dict] = field(default_factory=list)
    mode: str = "estimated"
    synth_requests: int = 0  # every line version synthesised, said or not
    synth_chars: int = 0  # their SSML length: an upper bound on the characters billed


# ---------------------------------------------------------------- where the play is


def pan_for(x: float) -> float:
    """Stereo position from pitch x: -1 the left of the main camera's view, 1 the right."""
    return round(max(-1.0, min(1.0, x / (PITCH_LENGTH_M / 2) - 1.0)), 2)


def where(x: float, y: float) -> str:
    across = ACROSS[min(2, int(3 * x / PITCH_LENGTH_M))]
    depth = DEPTH[min(2, int(3 * y / PITCH_WIDTH_M))]
    return f"{across}, {depth}" if depth else across


# ---------------------------------------------------------------- what is said


def _who(event: dict) -> str:
    return event.get("player") or event["team"]


def event_versions(event: dict) -> list[str]:
    """The line for one event, full then short. Numbers come from the event itself."""
    kind, who, place = event["type"], _who(event), where(event["x"], event["y"])
    if kind == "goal":
        return [f"Goal! {who} scores, {place}.", f"Goal! {who} scores."]
    if kind == "shot":
        outcome = {"on_target": "on target", "off_target": "off target", "blocked": "blocked"}.get(
            event.get("outcome") or "")
        tail = f", {outcome}." if outcome else "."
        across = place.split(",")[0].removeprefix("on the ").removeprefix("in the ")
        return [f"{who} shoots from the {across}{tail}", f"{who} shoots{tail}"]
    if kind == "pass":
        action = _pass_text(event, "casual")
        found = event.get("outcome") == "success" and event.get("receiver")
        short = f"{who} to {event['receiver']}." if found else f"{action}."
        return [f"{action}, {place}.", short]
    if kind == "interception":
        return [f"{who} wins it {place}.", f"{who} wins it."]
    if kind == "tackle":
        target = f" {event['receiver']}" if event.get("receiver") else ""
        return [f"{who} tackles{target}, {place}.", f"{who} tackles{target}."]
    if kind == "kickoff":
        return [f"Kick-off, {who}.", ]
    return []


PLAYER_SPOKEN = re.compile(r"\b([ha])(\d{1,2})\b")
TEAM_SPOKEN = re.compile(r"\b(home|away)\b")


def spoken(text: str) -> str:
    """What the voice says for a checked line: ids as names, units in full, arrows as words."""
    out = PLAYER_SPOKEN.sub(lambda m: f"{'Home' if m[1] == 'h' else 'Away'} {m[2]}", text)
    out = TEAM_SPOKEN.sub(lambda m: m[1].capitalize(), out)
    out = out.replace("→", "to").replace("km/h", "kilometres an hour")
    out = re.sub(r"(\d+(?:\.\d+)?) m\b", r"\1 metres", out)
    return out[0].upper() + out[1:] if out else out


def ssml(text: str, priority: int, voice: str = VOICE) -> str:
    """SSML for Azure AI Speech. A goal or shot is said a little higher and quicker."""
    body = escape(text)
    if priority <= PRIORITY["shot"]:
        body = f'<prosody rate="+10%" pitch="+8%">{body}</prosody>'
    return (
        f'<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" xml:lang="{LANG}">'
        f'<voice name="{voice}">{body}</voice></speak>'
    )


def estimated_seconds(text: str) -> float:
    return round(LEAD_IN_S + len(text.split()) / WORDS_PER_SECOND, 2)


# ---------------------------------------------------------------- the script


def _said(row: dict) -> tuple[str, int]:
    return row["metric"], 1 if row["change"] > 0 else -1


def shape_lines(shape: list[dict]) -> list[tuple[float, str, str]]:
    """(time, text, fact id) for at most one shape change a minute: the largest confident change in
    line height or width of at least SHAPE_CHANGE_M, said at the end of the minute it was measured
    over (a minute's shape is known only once it has been played)."""
    out = []
    for minute in sorted({r["minute"] for r in shape}):
        moved = [r for r in shape if r["minute"] == minute and r["confident"] and r.get("change")
                 and abs(r["change"]) >= SHAPE_CHANGE_M and _said(r) in SHAPE_SAID]
        if moved:
            r = max(moved, key=lambda r: (abs(r["change"]), r["metric"] == "line_height", r["id"]))
            text = SHAPE_SAID[_said(r)].format(team=r["team"], n=abs(r["change"]))
            out.append((60.0 * minute, text, r["id"]))
    return out


def candidates(
    events: list[dict], cues: list[dict], shape: list[dict] | None = None
) -> tuple[list[Line], list[dict]]:
    """Every line the Describer may say, each checked, and what it refused to say and why."""
    shape = list(shape or ())
    known = {e["id"]: compact(e) for e in events} | {r["id"]: r for r in shape}
    by_id = {e["id"]: e for e in events}
    refused: list[dict] = []

    def checked(texts: list[str], evidence: list[str]) -> list[str]:
        ok = []
        for text in texts:
            verdict = check(Claim(text, evidence), known)
            if verdict.ok:  # an unsure detection or shape fact is never said
                verdict = confidence_gate(Claim(text, evidence), known)
            if verdict.ok:
                ok.append(text)
            else:
                refused.append({"evidence": evidence, "text": text, "reason": "; ".join(verdict.reasons)})
        return ok

    insights: dict[str, Line] = {}
    for cue in cues:
        if cue.get("kind") != "insight":
            continue
        if cue.get("verified") is not True:
            refused.append({"evidence": cue["evidence"], "text": cue["text"], "reason": "not verified"})
            continue
        cited = [by_id[i] for i in cue["evidence"] if i in by_id]
        facts = [i for i in cue["evidence"] if i in known and i not in by_id]  # shape facts it cites
        if len(cited) + len(facts) != len(cue["evidence"]) or not cited:
            refused.append({"evidence": cue["evidence"], "text": cue["text"],
                            "reason": "cites unknown events"})
            continue
        last = max(cited, key=lambda e: (e["t"], e["id"]))
        versions = checked([f"Fact-checked: {cue['text']}"], list(cue["evidence"]))
        if versions:
            insights[last["id"]] = Line(cue["id"], cue["t_in"], PRIORITY["insight"], pan_for(last["x"]),
                                        list(cue["evidence"]), versions, "insight")

    lines: list[Line] = []
    for event in events:
        if event["id"] in insights:
            # The verified claim is said in this event's place, never both.
            lines.append(insights.pop(event["id"]))
            continue
        if event["type"] not in PRIORITY:
            continue
        confidence = event.get("confidence")
        if confidence is not None and confidence < MIN_CONFIDENCE:
            reason = f"detected with confidence {confidence:.2f}, below {MIN_CONFIDENCE:.2f}"
            refused.append({"evidence": [event["id"]], "text": None, "reason": reason})
            continue
        versions = checked(event_versions(event), [event["id"]])
        if versions:
            lines.append(Line(event["id"], event["t"], PRIORITY[event["type"]], pan_for(event["x"]),
                              [event["id"]], versions, "event"))
    lines.extend(insights.values())  # an insight whose last event is not in this list: none today
    for t, text, fact in shape_lines(shape):
        versions = checked([text], [fact])
        if versions:  # about the whole team, so said from the centre
            lines.append(Line(fact, t, PRIORITY["shape"], 0.0, [fact], versions, "shape"))
    lines.sort(key=lambda line: (line.t, line.priority, line.key))
    return lines, refused


Duration = Callable[[str, str], tuple[float, str]]  # (spoken text, SSML) -> (seconds, how it was found)


def estimate(words: str, _ssml: str) -> tuple[float, str]:
    return estimated_seconds(words), "estimated"


def schedule(lines: list[Line], duration: Duration) -> Track:
    """One voice in time order: each line starts when the last ended (plus GAP_S), at most
    MAX_LAG_S after its event; it shortens, then drops, rather than run late or push a more
    important line coming up past MAX_LAG_S."""
    said: list[Said] = []
    dropped: list[dict] = []
    free_at = float("-inf")
    for i, line in enumerate(lines):
        start = max(line.t, free_at)
        if start - line.t > MAX_LAG_S:
            dropped.append({"id": line.key, "t": line.t, "reason": f"voice busy until {free_at:.2f}"})
            continue
        upcoming = [n for n in lines[i + 1:] if n.priority < line.priority]
        chosen = None
        for n, text in enumerate(line.versions):
            words = spoken(text)
            seconds, how = duration(words, ssml(words, line.priority))
            end = start + seconds
            if all(end + GAP_S - n2.t <= MAX_LAG_S for n2 in upcoming if n2.t < end + GAP_S):
                chosen = (n, text, words, seconds, how)
                break
        if chosen is None:
            dropped.append({"id": line.key, "t": line.t, "reason": "would push a more important line late"})
            continue
        n, text, words, seconds, how = chosen
        end = round(start + seconds, 2)
        description = Description(line.key, words, ssml(words, line.priority), line.pan, "code")
        said.append(Said(
            id=f"ad-{line.key}", event=line.key, t_event=line.t, t_in=round(start, 2), t_out=end,
            lag_s=round(start - line.t, 2), pan=description.pan, text=text, spoken=description.text,
            ssml=description.ssml, short=n > 0, source=line.source, evidence=line.evidence,
            duration_s=seconds, duration_source=how,
        ))
        free_at = end + GAP_S
    return Track(said, dropped)


def describe(
    events: list[dict], cues: list[dict], duration: Duration = estimate, shape: list[dict] | None = None
) -> tuple[Track, list[dict]]:
    """The spoken track for detected `events` and the live path's `cues` (and the clip's shape facts,
    when it has tracked positions), and the refusals."""
    lines, refused = candidates(events, cues, shape)
    return schedule(lines, duration), refused


# ---------------------------------------------------------------- real synthesis (behind a flag)

WAV_FORMAT = "riff-24khz-16bit-mono-pcm"  # a WAV's length is exact from its header


def wav_seconds(audio: bytes) -> float:
    with wave.open(io.BytesIO(audio)) as w:
        return round(w.getnframes() / w.getframerate(), 3)


class Voice:
    """Lines synthesised through Azure AI Speech (ninety/speech/tts.py), or any `synth` with its
    signature. Used as the scheduler's `duration`: the measured length of each line's audio
    replaces the estimate, and the audio is kept for the lines that are said."""

    def __init__(self, synth: Callable[[str, str], tuple[bytes, float]] | None = None):
        if synth is None:
            from ninety.speech import tts  # imports the Azure credential: only behind the flag

            synth = tts.synthesize_ssml
        self.synth = synth
        self.audio: dict[str, tuple[bytes, float]] = {}

    def __call__(self, _words: str, markup: str) -> tuple[float, str]:
        if markup not in self.audio:
            self.audio[markup] = self.synth(markup, WAV_FORMAT)
        return wav_seconds(self.audio[markup][0]), "measured"

    def save(self, track: Track, out: Path) -> None:
        """Each said line's audio as audio/<id>.wav, with how long its request took."""
        (out / "audio").mkdir(exist_ok=True)
        for s in track.said:
            audio, took = self.audio[s.ssml]
            s.file = f"audio/{s.id}.wav"
            s.synth_s = round(took, 3)
            (out / s.file).write_bytes(audio)
        track.mode = "azure"
        track.synth_requests = len(self.audio)
        track.synth_chars = sum(len(markup) for markup in self.audio)


# ---------------------------------------------------------------- outputs


def audio_cues(track: Track) -> list[dict]:
    """The track as overlay cues for the `audio` persona (schemas/overlay_cue.schema.json)."""
    out = []
    for s in track.said:
        cue = {
            "id": s.id, "t_in": s.t_in, "t_out": s.t_out, "kind": "audio_description", "slot": SLOT,
            "anchor": None, "persona": "audio", "lang": "en", "text": s.spoken, "pan": s.pan,
            "replaces": None, "verified": s.source == "insight", "evidence": s.evidence,
        }
        validate(cue, SCHEMA)
        out.append(cue)
    return out


def _vtt_time(seconds: float) -> str:
    ms = round(max(0.0, seconds) * 1000)
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"


def webvtt(track: Track, t_start: float, timeline: Timeline | None = None) -> str:
    """A WebVTT description track timed on the clip (0 at its first frame). The caption sits
    across the frame where the sound is. A clip whose picture cuts (ninety/match/timeline.py)
    places each line where the video shows its match time, for as long as it is spoken."""
    blocks = ["WEBVTT\nKind: descriptions\nLanguage: en\n"]
    for s in track.said:
        position = round((s.pan + 1) * 50)
        position = min(90, max(10, position))
        start = timeline.to_video(s.t_in) if timeline is not None else s.t_in - t_start
        end = start + (s.t_out - s.t_in)
        blocks.append(
            f"{s.id}\n{_vtt_time(start)} --> {_vtt_time(end)} "
            f"position:{position}% align:center\n{s.spoken}\n"
        )
    return "\n".join(blocks)


def write_track(track: Track, refused: list[dict], out: Path, t_start: float, voice: str = VOICE,
                timeline: Timeline | None = None) -> dict:
    """audio.json (every line with its timing, pan, SSML and how its length was found) and
    description.vtt in `out`. Returns the summary for the bundle's manifest."""
    lags = sorted(s.lag_s for s in track.said)
    synth = sorted(s.synth_s for s in track.said if s.synth_s is not None)
    summary = {
        "mode": track.mode,
        "voice": voice,
        "lines": len(track.said),
        "dropped": len(track.dropped),
        "refused": len(refused),
        "max_lag_s": max(lags, default=0.0),
        "limit_lag_s": MAX_LAG_S,
        "synth_p50_s": _quantile(synth, 0.5),
        "synth_p95_s": _quantile(synth, 0.95),
        "synth_requests": track.synth_requests,
        "synth_chars": track.synth_chars,
        "vtt": "description.vtt",
    }
    doc = {**summary, "said": [asdict(s) for s in track.said], "dropped_lines": track.dropped,
           "refused_lines": refused}
    (out / "audio.json").write_text(json.dumps(doc, indent=2) + "\n")
    (out / "description.vtt").write_text(webvtt(track, t_start, timeline))
    return summary


def _quantile(values: list[float], q: float) -> float | None:
    """Nearest-rank quantile; None with nothing measured."""
    if not values:
        return None
    return values[min(len(values) - 1, max(0, round(q * len(values) + 0.5) - 1))]
