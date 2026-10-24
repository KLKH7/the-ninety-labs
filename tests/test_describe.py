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


# A passage faster than any voice: a pass every 0.6 s for 15 s, then a shot right after a pass.
BUSY = [event(i, round(0.6 * i, 2), x=10 + 3 * i) for i in range(25)]
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
    # The pass gives up its long form for the shot, or is not said at all: never the shot late.
    assert "e1" not in said or said["e1"].short


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
    # A line that starts after the 3 s clip's last frame is placed at its end (the timeline clamps).
    clip_s = 75 / 25
    assert starts == pytest.approx([min(s["t_in"] - T_START, clip_s) for s in audio["said"]], abs=1e-3)


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
