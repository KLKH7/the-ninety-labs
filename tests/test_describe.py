"""The Describer (ninety/speech/describe.py): one voice, on time, where the play is, saying only
what the fact-checker let through. Every test here was mutation-checked: each names the line
whose removal or inversion makes it fail."""

import io
import json
import re
import subprocess
import sys
import wave
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from jsonschema import validate

from ninety import e2e
from ninety.agents.factcheck import Claim, check
from ninety.match import detected
from ninety.match.facts import compact
from ninety.speech import describe as d
from tests.e2e_clip import EVENTS, T_START, write_clip

ROOT = Path(__file__).resolve().parent.parent
CUE_SCHEMA = json.loads((ROOT / "schemas/overlay_cue.schema.json").read_text())


def event(i: int, t: float, kind: str = "pass", x: float = 50.0, **extra) -> dict:
    base = {"id": f"e{i}", "t": t, "frame": int(t * 25), "type": kind, "team": "home", "player": "h4",
            "x": x, "y": 30.0, "source": "vision", "confidence": 0.9}
    if kind == "pass":
        base |= {"receiver": "h8", "intended": "h8", "end_x": x + 10, "end_y": 30.0, "outcome": "success",
                 "ball_speed_kmh": 50.0}
    if kind == "shot":
        base |= {"end_x": 105.0, "end_y": 34.0, "outcome": "on_target", "ball_speed_kmh": 101.4}
    return base | extra


# A passage faster than any voice: a pass every 0.6 s for 15 s, then a shot right after a pass. Each
# pass is a different player's, so no two lines are in the same words (which schedule does not repeat).
BUSY = [event(i, round(0.6 * i, 2), x=10 + 3 * i, player=f"h{2 + i % 9}", receiver="h11", intended="h11")
        for i in range(25)]
BUSY_THEN_SHOT = [event(1, 20.0), event(2, 20.5, "shot", x=90.0)]


def insight(evidence: list[str], text: str, verified: bool = True, t: float = 0.0) -> dict:
    return {"id": "insight-" + "-".join(evidence), "t_in": t, "t_out": t + 5, "kind": "insight",
            "slot": "top_right", "anchor": None, "persona": "analyst", "lang": "en", "text": text,
            "verified": verified, "replaces": None, "evidence": evidence}


# ---------------------------------------------------------------- timing


def test_one_voice_never_two_lines_at_once():
    # mutation: drop `free_at = end + GAP_S` in schedule -> lines overlap
    track, _ = d.describe(BUSY, [])
    assert len(track.said) > 3
    for a, b in zip(track.said, track.said[1:], strict=False):
        assert b.t_in >= a.t_out + d.GAP_S - 1e-9, (a.id, b.id)


def test_every_line_starts_within_two_seconds_of_its_event():
    # mutation: drop the `start - line.t > MAX_LAG_S` drop in schedule -> the backlog runs late
    track, _ = d.describe(BUSY, [])
    assert track.dropped, "the passage must outrun the voice, or this test proves nothing"
    times = {e["id"]: e["t"] for e in BUSY}
    for s in track.said:
        assert s.lag_s == pytest.approx(s.t_in - times[s.event])
        assert 0 <= s.lag_s <= d.MAX_LAG_S
    assert d.MAX_LAG_S == 2.0


def test_a_shot_is_not_pushed_late_by_the_pass_before_it():
    # mutation: drop the `upcoming` check in schedule -> the pass's full line makes the shot miss
    track, _ = d.describe(BUSY_THEN_SHOT, [])
    said = {s.event: s for s in track.said}
    assert "e2" in said and said["e2"].lag_s <= d.MAX_LAG_S
    assert said["e1"].short, "the pass gives up its long form for the shot"


# ---------------------------------------------------------------- stereo position


@pytest.mark.parametrize("x, pan", [(0.0, -1.0), (26.25, -0.5), (52.5, 0.0), (78.75, 0.5), (105.0, 1.0)])
def test_pan_follows_the_ball_across_the_cameras_view(x, pan):
    # mutation: flip the sign, or drop the -1 offset, in pan_for
    assert d.pan_for(x) == pan


def test_every_spoken_cue_sits_where_its_event_happened(tmp_path):
    out, _ = run_e2e(tmp_path)
    xs = {e["id"]: e["x"] for e in EVENTS}
    audio = [c for c in cues(out) if c["persona"] == "audio"]
    assert audio
    for cue in audio:
        last = max(cue["evidence"], key=lambda i: next(e["t"] for e in EVENTS if e["id"] == i))
        assert cue["pan"] == d.pan_for(xs[last])
        validate(cue, CUE_SCHEMA)
        assert cue["kind"] == "audio_description" and cue["slot"] == d.SLOT


# ---------------------------------------------------------------- only checked content is spoken


def test_an_unverified_insight_is_never_spoken():
    # mutation: drop the `verified is not True` refusal in candidates
    events = [event(1, 1.0, "shot", x=90.0)]
    track, refused = d.describe(events, [insight(["e1"], "h4 shot, on target, 101 km/h.", verified=False)])
    assert all("Fact-checked" not in s.text for s in track.said)
    assert [r["reason"] for r in refused] == ["not verified"]


def test_a_verified_cue_with_a_false_number_is_still_refused():
    # mutation: return `texts` unchecked from `checked` in candidates
    events = [event(1, 1.0, "shot", x=90.0)]
    track, refused = d.describe(events, [insight(["e1"], "h4 shot, on target, 143 km/h.")])
    assert all("143" not in s.text and "143" not in s.spoken for s in track.said)
    assert "number 143 is not a cited ball_speed_kmh" in refused[0]["reason"]


def test_a_planted_rejected_claim_is_never_spoken(tmp_path):
    """With --plant the Analyst's first draft carries a false number; the fact-checker rejects it
    (trace.json) and only the rewrite airs. Nothing the voice or the captions say has it."""
    out, manifest = run_e2e(tmp_path, "--plant")
    (claim,) = json.loads((out / "trace.json").read_text())["claims"]
    (reject,) = [s for s in claim["steps"] if s["action"] == "reject"]
    planted = re.search(r"number (\d+(?:\.\d+)?) ", reject["detail"])[1]
    audio = json.loads((out / "audio.json").read_text())
    said = " ".join(s["text"] + " " + s["spoken"] + " " + s["ssml"] for s in audio["said"])
    assert planted not in said and planted not in (out / "description.vtt").read_text()
    assert any(s["source"] == "insight" for s in audio["said"]), "the accepted rewrite is said"
    assert manifest["audio"]["lines"] == len(audio["said"])


def test_an_unsure_detection_is_not_described():
    # mutation: drop the MIN_CONFIDENCE refusal in candidates
    track, refused = d.describe([event(1, 1.0, confidence=0.3)], [])
    assert not track.said and "below 0.50" in refused[0]["reason"]


def test_every_line_said_passes_the_fact_checker_and_is_said_as_checked():
    track, _ = d.describe(BUSY + BUSY_THEN_SHOT[1:], [])
    known = {e["id"]: compact(e) for e in BUSY + BUSY_THEN_SHOT}
    for s in track.said:
        assert check(Claim(s.text, s.evidence), known).ok, s.text
        assert s.spoken == d.spoken(s.text)


def test_spoken_form_names_players_and_units():
    # Said as a commentator would, not as a graphic reads (Kian: no machine-sounding lines).
    assert d.spoken("h4 → h8, 12 m, 48 km/h.") == \
        "Home's number 4 plays it 12 metres to number 8, at 48 kilometres an hour."
    assert d.spoken("h8 shot, on target, 101 km/h.") == \
        "Home's number 8 shoots at 101 kilometres an hour, on target."
    assert d.spoken("away plays a pass, on the left.") == "Away plays a pass, on the left."
    # A tracked player has no shirt number the tracker read: no "number 12" for track 12.
    assert d.spoken("a-t9 → a-t4, 30 m.") == "An away player plays it 30 metres to a team-mate."
    assert d.spoken("h7 plays a 12 m pass to a4.") == \
        "Home's number 7 plays a 12-metre pass to Away's number 4."
    assert "→" not in d.spoken("h4 → h8.") and "Fact-checked" not in d.spoken("h4 → h8.")


# ---------------------------------------------------------------- SSML and WebVTT


def test_ssml_is_well_formed_and_escaped():
    markup = d.ssml("Home 4 & <Home 8>", d.PRIORITY["pass"])
    root = ET.fromstring(markup)
    ns = "{http://www.w3.org/2001/10/synthesis}"
    assert root.tag == f"{ns}speak" and root.find(f"{ns}voice").get("name") == d.VOICE
    assert "".join(root.itertext()) == "Home 4 & <Home 8>"
    shot = ET.fromstring(d.ssml("Home 9 shoots.", d.PRIORITY["shot"]))
    assert shot.find(f"{ns}voice/{ns}prosody") is not None


def test_webvtt_is_timed_on_the_clip(tmp_path):
    out, _ = run_e2e(tmp_path)
    vtt = (out / "description.vtt").read_text()
    assert vtt.startswith("WEBVTT\nKind: descriptions")
    audio = json.loads((out / "audio.json").read_text())
    stamps = re.findall(r"(\d\d):(\d\d):(\d\d)\.(\d{3}) --> ", vtt)
    starts = [int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000 for h, m, s, ms in stamps]
    assert starts == pytest.approx([s["t_in"] - T_START for s in audio["said"]], abs=1e-3)


# ---------------------------------------------------------------- synthesis, offline and behind the flag


def fake_wav(seconds: float) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(24000)
        w.writeframes(b"\0\0" * int(24000 * seconds))
    return buf.getvalue()


def test_measured_audio_length_replaces_the_estimate(tmp_path):
    calls = []

    def synth(markup: str, fmt: str):
        calls.append(fmt)
        return fake_wav(0.8), 0.25

    voice = d.Voice(synth)
    track, refused = d.describe(EVENTS, [], voice)
    voice.save(track, tmp_path)
    summary = d.write_track(track, refused, tmp_path, T_START)
    assert calls and set(calls) == {d.WAV_FORMAT}
    assert all(s.duration_s == 0.8 and s.duration_source == "measured" for s in track.said)
    assert all((tmp_path / s.file).read_bytes() == fake_wav(0.8) for s in track.said)
    assert summary["mode"] == "azure" and summary["synth_p50_s"] == 0.25 == summary["synth_p95_s"]
    assert summary["synth_requests"] == len(calls) == len(voice.audio)
    assert summary["synth_chars"] == sum(len(m) for m in voice.audio)
    # Short audio leaves room for every event the estimate had to drop.
    assert len(track.said) == len(EVENTS)


def test_the_default_run_makes_no_azure_call(tmp_path):
    # mutation: import ninety.speech.tts at the top of describe.py
    code = "import sys, ninety.e2e, ninety.speech.describe; print('ninety.speech.tts' in sys.modules)"
    loaded = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True,
                            cwd=ROOT)
    assert loaded.stdout.strip() == "False"
    out, manifest = run_e2e(tmp_path)
    assert manifest["audio"]["mode"] == "estimated" and not (out / "audio").exists()


# ---------------------------------------------------------------- helpers


def run_e2e(tmp_path: Path, *extra: str) -> tuple[Path, dict]:
    clip, detections, events_file = write_clip(tmp_path)
    out = tmp_path / "bundle"
    e2e.main([str(clip), "--out", str(out), "--detections", str(detections), "--frames",
              "--events-file", str(events_file), *extra])
    return out, json.loads((out / "manifest.json").read_text())


def cues(out: Path) -> list[dict]:
    return [json.loads(line) for line in (out / "cues.jsonl").read_text().splitlines()]


def test_webvtt_follows_the_clips_timeline_across_a_cut():
    """A clip whose picture cuts from a dead ball to its restart (ninety/match/timeline.py): a line
    is placed where the video shows its match time, not at its time since the clip's start."""
    from ninety.match.timeline import Timeline

    # 2 s shown from 60.0 s, then the cut, then 4 s from 90.0 s.
    tl = Timeline([{"index": 0, "frame": 1500, "frames": 50},
                   {"index": 50, "frame": 2250, "frames": 100}], 25)
    said = [d.Said(id=f"a{i}", event=f"e{i}", t_event=t, t_in=t, t_out=t + 1.5, lag_s=0.0, pan=0.0, text="x",
                   spoken="x", ssml="<speak/>", short=False, source="template", evidence=[], duration_s=1.5,
                   duration_source="estimated") for i, t in enumerate((60.5, 91.0))]
    vtt = d.webvtt(d.Track(said=said), 60.0, tl)
    stamps = re.findall(r"(\d\d):(\d\d):(\d\d)\.(\d{3}) --> (\d\d):(\d\d):(\d\d)\.(\d{3})", vtt)
    secs = [[int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000 for h, m, s, ms in (st[:4], st[4:])]
            for st in stamps]
    assert secs == [pytest.approx([0.5, 2.0], abs=1e-3), pytest.approx([3.0, 4.5], abs=1e-3)]


NUMBER = re.compile(r"\d+(?:\.\d+)?")
TRACK = re.compile(r"\b[ha]-t\d+\b")
SIDE_WORD = re.compile(r"\b(?:home|away)\b", re.I)


def numbers(text: str) -> list[str]:
    return sorted(NUMBER.findall(TRACK.sub("", text)))


SPOKEN_FORMS = [
    "h4 → h8, 12 m, 48 km/h, 3 m from goal.", "h8 pass, 12 m, 40 km/h.", "h4 → h8 (in flight), 12 m.",
    "a pass (incomplete), 22 m, 137.2 km/h.", "a-t4 → a-t5, 8 m, 42.2 km/h.",
    "h4 → h8 (cut out by a3), 12 m.",
    "h8 shot, on target, 101.4 km/h.", "h4's pass for h8 is cut out by a3.", "a-t4 finds a-t5, on the left.",
    "Goal! h9 scores, in the middle.", "h7 plays a 12 m pass to a4, at 31 km/h.", "h4 to h8.",
]


@pytest.mark.parametrize("text", SPOKEN_FORMS)
@pytest.mark.parametrize("side_known", [True, False])
def test_what_is_said_carries_the_checked_numbers_and_no_side_the_line_does_not(text, side_known):
    # Review of #267: spoken() must not drop a number, nor add a side the checked text does not state.
    said = d.spoken(text, side_known)
    assert numbers(said) == numbers(text), said
    assert "→" not in said and "Fact-checked" not in said
    if not side_known and not re.search(r"\b[ha]\d", text):  # track ids only: their letter is unsure
        assert not SIDE_WORD.search(said), said


def test_a_line_about_a_detection_whose_side_is_unsure_names_no_side():
    # The M1 clip's sides were told at 0.529, except v00005's at 0.964 (above the gate): the voice says
    # "a player" where the side is unsure, and may say "an away player" only for v00005.
    from ninety.agents.factcheck import side_known

    events = detected.load(detected.m1_path(detected.M1_CLIP))
    sure = {e["id"]: side_known(e) for e in events}
    track, _ = d.describe(events, [])
    assert track.said
    for s in track.said:
        assert bool(SIDE_WORD.search(s.spoken)) <= all(sure[i] for i in s.evidence), s.spoken
    assert any(not sure[i] for s in track.said for i in s.evidence)  # the case is in the data


def test_the_sides_are_named_as_their_clubs_when_the_bundle_knows_them():
    clubs = {"home": "London", "away": "Lisbon"}
    assert d.spoken("h11 → h8, 17 m.", clubs=clubs) == "London's number 11 plays it 17 metres to number 8."
    assert d.spoken("a-t4 finds a-t5.", True, clubs=clubs) == "A Lisbon player finds a team-mate."
    assert d.spoken("a-t4 finds a-t5.", False, clubs=clubs) == "A player finds another player."  # unsure
    assert d.spoken("home's back line has pushed up 8 m.", clubs=clubs).startswith("London's back line")


def test_a_verified_claim_citing_an_unsure_side_is_said_without_one():
    # A claim naming players by track id passes the side gate (no side word in its text), so the
    # Describer must not add the side when it speaks it: v00001's side was told at 0.529.
    events = detected.load(detected.m1_path(detected.M1_CLIP))
    first = next(e for e in events if e["id"] == "v00001")
    cue = {"id": "insight-v00001", "kind": "insight", "verified": True, "t_in": first["t"],
           "text": f"{first['player'] or 'a-t4'} finds {first.get('receiver') or 'a-t5'}.",
           "evidence": ["v00001"]}
    track, _ = d.describe(events, [cue])
    line = next(s for s in track.said if s.event == "insight-v00001")
    assert not SIDE_WORD.search(line.spoken), line.spoken


def test_a_possessive_and_a_repeated_track_read_as_sentences():
    assert d.spoken("h4's pass for h8 is cut out by a3.") == \
        "The pass from Home's number 4 for number 8 is cut out by Away's number 3."
    assert d.spoken("h-t9 → h-t9, 3 m.", False) == "A player plays it 3 metres to the same player."


# ---------------------------------------------------------------- set pieces (ninety/vision/restarts.py)

SURE = min(1.0, d.MIN_CONFIDENCE + 0.5)  # a confident detection
SIDE_SURE = 0.99  # above factcheck.MIN_TEAM_CONFIDENCE


def set_piece(restart=None, team_confidence=SIDE_SURE, **extra) -> dict:
    e = event(1, 8.0, "set_piece", x=40.0, team="away", player=None, confidence=SURE,
              team_confidence=team_confidence)
    return e | extra | ({"restart": restart} if restart else {})


@pytest.mark.parametrize("restart, name", [("corner", "Corner"), ("goal_kick", "Goal kick"),
                                           ("throw_in", "Throw-in"), ("free_kick", "Free kick"),
                                           ("penalty_kick", "Penalty"), (None, "Set piece")])
def test_each_set_piece_is_named_with_the_side_taking_it_when_the_side_is_sure(restart, name):
    full, short = d.event_versions(set_piece(restart))
    assert short == f"{name} to away."
    assert full == f"{name} to away, {d.where(40.0, 30.0)}."
    unsure_full, unsure_short = d.event_versions(set_piece(restart, team_confidence=None))
    assert unsure_short == f"A {name.lower()}."
    assert unsure_full == f"A {name.lower()}, {d.where(40.0, 30.0)}."


def test_a_set_piece_side_is_said_as_the_club_only_past_the_side_gate():
    from ninety.agents.factcheck import MIN_TEAM_CONFIDENCE
    clubs = {"home": "London", "away": "Lisbon"}
    sure = d.event_versions(set_piece("free_kick"))[1]
    assert d.spoken(sure, True, clubs=clubs) == "Free kick to Lisbon."
    for side in (MIN_TEAM_CONFIDENCE, None):  # at the gate, or not told: no side
        line = d.event_versions(set_piece("free_kick", team_confidence=side))[1]
        assert d.spoken(line, False, clubs=clubs) == "A free kick."


def test_no_cause_is_said_until_it_is_measured(monkeypatch):
    for cause in ("offside", "foul_likely", "foul", "unknown"):
        for line in d.event_versions(set_piece("free_kick", cause=cause)):
            assert not re.search(r"foul|offside|likely", line), line
    # Once SAY_CAUSE is turned on by the measurement, the words are all hedged but a penalty's.
    monkeypatch.setattr(d, "SAY_CAUSE", True)
    said = {c: d.event_versions(set_piece("free_kick", cause=c))[1]
            for c in ("offside", "foul_likely", "unknown")}
    assert said == {"offside": "Free kick to away, likely for offside.",
                    "foul_likely": "Free kick to away, likely for a foul.", "unknown": "Free kick to away."}
    assert d.event_versions(set_piece("penalty_kick", cause="foul"))[1] == "Penalty to away, for a foul."
    assert d.SAY_CAUSE is True


def test_a_set_piece_never_names_a_fouler():
    for line in d.event_versions(set_piece("free_kick", cause="foul_likely", player="a-t4")):
        assert "a-t4" not in line


def test_a_player_is_capitalised_only_where_he_opens_a_sentence():
    """Demo audit: "Goal! a player scores." The unnamed player opens a sentence with a capital, and
    stays lower case mid-sentence ("Kick-off, a player.")."""
    unnamed = {"player": None, "team": "home", "team_confidence": 0.1, "confidence": 0.9, "x": 90, "y": 30,
               "outcome": None}
    assert d.event_versions({**unnamed, "type": "goal"})[1] == "Goal! A player scores."
    assert d.event_versions({**unnamed, "type": "shot"})[1] == "A player shoots."
    assert d.event_versions({**unnamed, "type": "kickoff"}) == ["Kick-off, a player."]


def test_a_goal_is_said_for_the_goal_events_side_never_the_scorers_track_letter():
    """Preview, Oct 26 (lesson 283): goal 1 was Lisbon's (match.json's goals, the goal event's side
    from the player-ID feed), but its scorer's track was `h-t9029` and the voice said "Goal! A London
    player scores". The goal's side is the goal event's, and the scorer is named by the feed."""
    goal = {"id": "s09-v00003", "t": 1292.12, "frame": 32303, "type": "goal", "team": "away",
            "team_confidence": 1.0, "team_source": "id_feed", "player": "h-t9029", "x": 0.0, "y": 34.4,
            "source": "vision", "confidence": 0.999, "outcome": None}
    clubs = {"home": "London", "away": "Lisbon"}
    for names, scorer in (({"h-t9029": "Eli Hourrick"}, "Eli Hourrick"), ({}, "A Lisbon player")):
        track, _ = d.describe([goal], [], clubs=clubs, names=names)
        (said,) = track.said
        opening = (f"Goal! {scorer} scores for Lisbon", f"Goal! {scorer} scores,")
        assert said.spoken.startswith(opening), said.spoken
        assert "Lisbon" in said.spoken
        assert "London" not in said.spoken
    # A goal whose side is not told surely names no side at all.
    unsure = {**goal, "team_confidence": 0.5, "team_source": None}
    (said,) = d.describe([unsure], [], clubs=clubs)[0].said
    assert "London" not in said.spoken and "Lisbon" not in said.spoken, said.spoken
