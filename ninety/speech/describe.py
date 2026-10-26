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
from ninety.agents.cues import SCHEMA, UNNAMED, _pass_text
from ninety.agents.factcheck import MIN_CONFIDENCE, Claim, check, confidence_gate, side_known
from ninety.match.facts import compact
from ninety.match.timeline import Timeline
from ninety.speech import voice

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
VOICE = voice.VOICE  # pinned in ninety/speech/voice.py
LANG = "en-GB"
SLOT = "audio"
# design: the Describer model's own limit (ninety/agents/describer.py, INSTRUCTIONS), held by code.
# One short sentence a fan can take in between plays; at WORDS_PER_SECOND it is about 8 s of voice.
# A longer line is refused rather than trusted to the schedule, which shortens only for a line
# behind it, so a long model line with nothing after it would otherwise be read in full.
MODEL_MAX_WORDS = 20
# Quotes too: an escaped quote can never close an attribute, wherever the builder puts the text.
QUOTES = {'"': "&quot;", "'": "&apos;"}

# Lower is more important: what keeps its place when there is no time for everything.
PRIORITY = {"goal": 0, "shot": 1, "insight": 2, "interception": 3, "tackle": 3, "pass": 4, "kickoff": 4,
            "set_piece": 4, "shape": 4}
# A detected set piece (ninety/vision/restarts.py) by its kind, and why a free kick or penalty was
# given as far as tracking can tell (ninety/intel/restart_cause.py). A foul is never said to be
# anyone's: tracking sees positions, not contact.
RESTART_NAMES = {"corner": "Corner", "goal_kick": "Goal kick", "throw_in": "Throw-in",
                 "free_kick": "Free kick", "penalty_kick": "Penalty"}
CAUSE_WORDS = {"offside": "likely for offside", "foul_likely": "likely for a foul", "foul": "for a foul"}
# The cause is said only once it is measured: SAY_CAUSE is turned on when the validation cause table
# (ninety/eval/restart_score.py, `cause.right`) clears the bar docs/eval/restarts-vision-plan.md
# states before scoring. Until then the line names only the restart's kind; the cause stays in the
# data. A claim ships with its measurement (AGENTS.md).
SAY_CAUSE = False
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
    source: str  # "event" or "shape" (written here), "insight" (a verified claim) or "model" (its model line)
    # Whether every detection the line cites had its side told surely (factcheck.side_known): only then
    # may the voice name a player's side ("a home player"), since a track id's letter is that side.
    side_known: bool = True


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
    speech: str | None = None  # with real synthesis: "spoken", or "unavailable" when it failed


@dataclass
class Track:
    said: list[Said]
    dropped: list[dict] = field(default_factory=list)
    mode: str = "estimated"
    synth_requests: int = 0  # every line version synthesised, said or not
    synth_chars: int = 0  # their SSML length: an upper bound on the characters billed
    synth_failed: int = 0  # requests that failed: their lines were shown, not spoken


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
    """The player, or the team only when its side is known (factcheck.side_known)."""
    return event.get("player") or (event["team"] if side_known(event) else UNNAMED)


def event_versions(event: dict) -> list[str]:
    """The line for one event, full then short. Numbers come from the event itself."""
    return [_opening_capital(v) for v in _versions(event)]


def _opening_capital(line: str) -> str:
    """A sentence that opens on "a player" opens with a capital ("A player shoots.", "Goal! A player
    scores."); "a player" mid-sentence stays lower case ("Kick-off, a player."). A player id or a side
    (said as its club later, by spoken()) is left as it is."""
    if line.startswith(f"{UNNAMED} "):
        line = "A" + line[1:]
    return line.replace(f"Goal! {UNNAMED} ", "Goal! A player ")


def _versions(event: dict) -> list[str]:
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
    if kind == "set_piece":
        name = RESTART_NAMES.get(event.get("restart") or "", "Set piece")
        # The side by name when it was told surely (spoken() turns it into the club's name), else
        # no side at all: "A free kick".
        head = f"{name} to {event['team']}" if side_known(event) else f"A {name.lower()}"
        why = CAUSE_WORDS.get(event.get("cause") or "", "") if SAY_CAUSE else ""
        head += f", {why}" if why else ""
        return [f"{head}, {place}.", f"{head}."]
    return []


PLAYER_SPOKEN = re.compile(r"\b([ha])(?:(\d{1,2})|-t(\d+))\b")
TEAM_SPOKEN = re.compile(r"\b(home|away)\b")
# The graphics' compact forms ("h11 → h8, 17 m, 53 km/h", "h8 shot, on target, 101 km/h", "h4 → h8
# (cut out by a3), 12 m"): read for a screen, not a voice. Said as a commentator would say them, with
# the same numbers and the same players.
_ID = r"(?:[ha](?:\d{1,2}|-t\d+)|a player)"
_NUM = r"\d+(?:\.\d+)?"
HEAD_PASS = re.compile(rf"^(?P<a>{_ID}) → (?P<b>{_ID})(?: \((?P<how>[^)]+)\))?$")
HEAD_PLAIN = re.compile(rf"^(?P<a>{_ID}) pass(?: \((?P<how>[^)]+)\))?$|^a pass(?: \((?P<how2>[^)]+)\))?$")
HEAD_SHOT = re.compile(rf"^(?P<a>{_ID}) shot$|^a shot$")
DIST = re.compile(rf"^({_NUM}) m$")
SPEED = re.compile(rf"^({_NUM}) km/h$")
POSSESSIVE = re.compile(rf"\b({_ID})'s pass\b")


def _sentence(text: str) -> str:
    """A graphic's compact form as a sentence; any other text unchanged. Nothing is dropped: a part
    that is neither a distance nor a speed is kept as it was written."""
    body = text.strip()
    end = "." if body.endswith(".") else ""
    head, *rest = [p.strip() for p in body.removesuffix(".").split(", ")]
    dist = next((DIST.match(p)[1] for p in rest if DIST.match(p)), None)
    speed = next((SPEED.match(p)[1] for p in rest if SPEED.match(p)), None)
    other = "".join(f", {p}" for p in rest if not DIST.match(p) and not SPEED.match(p))
    at = f", at {speed} km/h" if speed else ""
    if m := HEAD_PASS.match(head):
        how, a, b = m["how"], m["a"], m["b"]
        length = f" {dist} m" if dist else ""
        if how == "in flight":
            out = f"{a} plays it{length} towards {b}{at}"
        elif how == "incomplete":
            out = f"{a} plays it{length} for {b}{at}, but it doesn't arrive"
        elif how:
            out = f"{a} plays it{length} for {b}{at}, {how}"
        else:
            out = f"{a} plays it{length} to {b}{at}"
        return out + other + "."
    if m := HEAD_PLAIN.match(head):
        how = m["how"] or m["how2"]
        size = f"a {dist} m pass" if dist else "a pass"
        lead = f"{m['a']} plays {size}" if m["a"] else size.capitalize()
        tail = "" if not how else ", but it doesn't arrive" if how == "incomplete" else f", {how}"
        return lead + (f" at {speed} km/h" if speed else "") + tail + other + "."
    if m := HEAD_SHOT.match(head):
        who = m["a"] or "a player"
        return f"{who} shoots" + (f" at {speed} km/h" if speed else "") + other + "."
    return POSSESSIVE.sub(lambda m: f"the pass from {m[1]}", body.removesuffix(".")) + end


as_sentence = _sentence  # the offline stand-in Tactician writes its claim this way (ninety/e2e.py)


def _names(text: str, side_known: bool = True, compact: bool = False,
           clubs: dict[str, str] | None = None) -> str:
    """Ids as a commentator says them. A squad id is its side's shirt number ("Home's number 11", then
    "number 8"). A tracked player has no shirt number the tracker read, so a track id is never said as
    a number: he is "a home player", then "a team-mate", only when the line's side was told surely;
    otherwise "a player", then "another player" (a track id's letter is the tracker's side vote, which
    the voice says only when the gate passes it; the graphic's id still shows it: EVALUATION.md, known
    residual).
    The same player named again is "the same player". `compact` (a short version) drops the side."""
    sides: set[str] = set()
    seen: dict[str, str] = {}

    def say(m: re.Match) -> str:
        whole, side = m[0], ("home" if m[1] == "h" else "away")
        if whole in seen:
            return "the same player" if m[3] else f"number {m[2]}"
        first = side not in sides
        sides.add(side)
        if m[2]:
            club = (clubs or {}).get(side, side.capitalize())
            phrase = f"number {m[2]}" if compact or not first else f"{club}'s number {m[2]}"
        elif side_known and not compact:
            if clubs and side in clubs:
                phrase = f"a {clubs[side]} player" if first else "a team-mate"
            else:
                phrase = ("an away player" if side == "away" else "a home player") if first else "a team-mate"
        else:
            phrase = "a player" if not seen else "another player"
        seen[whole] = phrase
        return phrase

    return PLAYER_SPOKEN.sub(say, text)


def spoken(text: str, side_known: bool = True, compact: bool = False,
           clubs: dict[str, str] | None = None) -> str:
    """What the voice says for a checked line: a sentence, not a graphic's compact form; ids as a
    commentator names players; units in full. The substitutions are fixed: what is said carries
    exactly the checked line's numbers, and names no side the checked line does not (a track id's
    side only where it was told surely). `clubs` names the sides ({"home": "London", ...}, from the
    bundle's team codes): "London's number 11" rather than "Home's number 11"."""
    names = clubs or {}
    out = TEAM_SPOKEN.sub(lambda m: names.get(m[1], m[1].capitalize()), _sentence(text))
    out = _names(out, side_known, compact, clubs)
    out = out.replace("→", "to").replace("km/h", "kilometres an hour")
    out = re.sub(rf"({_NUM}) m pass\b", r"\1-metre pass", out)
    out = re.sub(rf"({_NUM}) m\b", r"\1 metres", out)
    return out[0].upper() + out[1:] if out else out


def ssml(text: str, priority: int, voice: str = VOICE) -> str:
    """SSML for Azure AI Speech. A goal or shot is said a little higher and quicker."""
    body = escape(text, QUOTES)
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
            # The side, only when it was told surely; else "one side" (a shape fact's side comes from
            # the same side decision a detection's does, and is gated the same way).
            who = r["team"] if side_known(r) else "one side"
            text = SHAPE_SAID[_said(r)].format(team=who, n=abs(r["change"]))
            out.append((60.0 * minute, text, r["id"]))
    return out


def candidates(
    events: list[dict], cues: list[dict], upgrades: dict[str, str] | None = None,
    shape: list[dict] | None = None,
) -> tuple[list[Line], list[dict]]:
    """Every line the Describer may say, each checked, and what it refused to say and why.

    `upgrades` maps a verified insight cue's id to a line the Describer model wrote for that moment
    (ninety/agents/describer.py). It is checked here like every other line, against the claim's
    evidence; if it passes it is said first, with the code line as its shorter fallback, and if it
    fails the code line stays and the refusal says why. `shape` is the clip's team-shape facts."""
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

    def sides_told(evidence: list[str]) -> bool:
        """Whether every cited detection's side was told surely: only then may the voice say a side."""
        return all(side_known(known[i]) for i in evidence if i in known and known[i].get("type") != "shape")

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
        # Said as the sentence itself: that it was checked is shown in How we know, never said.
        versions = checked([cue["text"]], list(cue["evidence"]))
        source = "insight"
        if versions and (upgrades or {}).get(cue["id"]):
            text = upgrades[cue["id"]]
            if len(text.split()) > MODEL_MAX_WORDS:
                refused.append({"evidence": list(cue["evidence"]), "text": text,
                                "reason": f"model line over {MODEL_MAX_WORDS} words"})
                model = []
            else:
                model = checked([text], list(cue["evidence"]))
            if model:
                versions, source = model + versions, "model"
        if versions:
            insights[last["id"]] = Line(cue["id"], cue["t_in"], PRIORITY["insight"], pan_for(last["x"]),
                                        list(cue["evidence"]), versions, source,
                                        sides_told(cue["evidence"]))

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
                              [event["id"]], versions, "event", sides_told([event["id"]])))
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


def schedule(lines: list[Line], duration: Duration, clubs: dict[str, str] | None = None) -> Track:
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
            words = spoken(text, line.side_known, compact=n > 0, clubs=clubs)
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
        # A model line that did not fit falls back to the claim's own (code) line.
        source = "insight" if line.source == "model" and n > 0 else line.source
        description = Description(line.key, words, ssml(words, line.priority), line.pan,
                                  "model" if source == "model" else "code")
        said.append(Said(
            id=f"ad-{line.key}", event=line.key, t_event=line.t, t_in=round(start, 2), t_out=end,
            lag_s=round(start - line.t, 2), pan=description.pan, text=text, spoken=description.text,
            ssml=description.ssml, short=n > 0, source=source, evidence=line.evidence,
            duration_s=seconds, duration_source=how,
        ))
        free_at = end + GAP_S
    return Track(said, dropped)


def describe(events: list[dict], cues: list[dict], duration: Duration = estimate,
             upgrades: dict[str, str] | None = None, shape: list[dict] | None = None,
             clubs: dict[str, str] | None = None) -> tuple[Track, list[dict]]:
    """The spoken track for detected `events` and the live path's `cues` (and the clip's shape facts,
    when it has tracked positions), and the refusals. `clubs` names the sides when the bundle knows
    its teams (see `spoken`)."""
    lines, refused = candidates(events, cues, upgrades, shape)
    return schedule(lines, duration, clubs), refused


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
        self.failed: dict[str, str] = {}  # SSML -> why synthesis failed

    def __call__(self, words: str, markup: str) -> tuple[float, str]:
        """Measured length, or on a failed request (an outage, a refused sign-in) the estimate:
        the line is still scheduled and shown, and its cue says speech is unavailable."""
        if markup not in self.audio and markup not in self.failed:
            try:
                self.audio[markup] = self.synth(markup, WAV_FORMAT)
            except Exception as e:  # noqa: BLE001  an outage must never silence the line; recorded
                self.failed[markup] = f"{type(e).__name__}: {e}"
        if markup in self.failed:
            return estimated_seconds(words), "estimated"
        return wav_seconds(self.audio[markup][0]), "measured"

    def save(self, track: Track, out: Path) -> None:
        """Each said line's audio as audio/<id>.wav, with how long its request took."""
        (out / "audio").mkdir(exist_ok=True)
        for s in track.said:
            if s.ssml in self.failed:
                s.speech = "unavailable"
                continue
            audio, took = self.audio[s.ssml]
            s.speech = "spoken"
            s.file = f"audio/{s.id}.wav"
            s.synth_s = round(took, 3)
            (out / s.file).write_bytes(audio)
        track.mode = "azure"
        track.synth_requests = len(self.audio) + len(self.failed)
        track.synth_chars = sum(len(markup) for markup in self.audio)
        track.synth_failed = len(self.failed)


# ---------------------------------------------------------------- outputs


def audio_cues(track: Track) -> list[dict]:
    """The track as overlay cues for the `audio` persona (schemas/overlay_cue.schema.json)."""
    out = []
    for s in track.said:
        cue = {
            "id": s.id, "t_in": s.t_in, "t_out": s.t_out, "kind": "audio_description", "slot": SLOT,
            "anchor": None, "persona": "audio", "lang": "en", "text": s.spoken, "pan": s.pan,
            "replaces": None, "verified": s.source in ("insight", "model"), "evidence": s.evidence,
        }
        if s.speech is not None:
            cue["speech"] = s.speech
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
        "synth_failed": track.synth_failed,
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
