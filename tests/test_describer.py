"""The Describer model (ninety/agents/describer.py) on the audio description track
(ninety/speech/describe.py): a model line for a verified moment airs only if it passes the
fact-checker, a speech outage still shows every line and says so, SSML never turns text into
markup, and the default run never loads the model. No Azure: the model and speech are fakes of
their contracts. Each test fails when the rule it names is removed (mutation-checked)."""

import asyncio
import contextlib
import json
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from types import SimpleNamespace

import pytest

from ninety import e2e
from ninety.agents import describer
from ninety.agents.contracts import Description
from ninety.agents.factcheck import MIN_CONFIDENCE, Verdict
from ninety.agents.foundry import RegistryDrift
from ninety.speech import describe as d
from ninety.speech import tts
from tests.e2e_clip import write_clip
from tests.test_describe import fake_wav

ROOT = Path(__file__).resolve().parent.parent
SSML_NS = "{http://www.w3.org/2001/10/synthesis}"


def event(i: int, t: float, kind: str = "pass", x: float = 50.0, **extra) -> dict:
    base = {"id": f"e{i}", "t": t, "frame": int(t * 25), "type": kind, "team": "home", "player": "h4",
            "x": x, "y": 30.0, "source": "vision", "confidence": 0.9}
    if kind == "pass":
        base |= {"receiver": "h8", "intended": "h8", "end_x": x + 10, "end_y": 30.0, "outcome": "success",
                 "ball_speed_kmh": 50.0}
    if kind == "shot":
        base |= {"player": "h8", "end_x": 105.0, "end_y": 34.0, "outcome": "on_target",
                 "ball_speed_kmh": 101.4}
    return base | extra


EVENTS = [event(1, 10.0, x=60.0), event(2, 11.0, "shot", x=90.0)]


def insight(evidence: list[str], text: str, verified: bool = True) -> dict:
    return {"id": "insight-" + "-".join(evidence), "t_in": 11.0, "t_out": 16.0, "kind": "insight",
            "slot": "top_right", "anchor": None, "persona": "analyst", "lang": "en", "text": text,
            "verified": verified, "replaces": None, "evidence": evidence}


CLAIM = insight(["e1", "e2"], "h4 finds h8, who shoots on target")
MODEL_LINE = "h8 shoots on target after h4 finds h8"


def said_for(track: d.Track, key: str) -> d.Said:
    return next(s for s in track.said if s.event == key)


async def judge_passes(claim, evidence):
    return Verdict(ok=True)


def judge_refusing(*lines: str, seen: list | None = None):
    """A stand-in Judge: refuses exactly `lines`, as the published Judge refuses a contradiction."""
    async def judge(claim, evidence):
        if seen is not None:
            seen.append((claim.text, list(claim.evidence), [e["id"] for e in evidence]))
        if claim.text in lines:
            return Verdict(ok=False, reasons=[f"contradicted fact: '{claim.text}'"],
                           category="unsupported_claim")
        return Verdict(ok=True)

    return judge


def model_answering(text: str, asked: list | None = None):
    async def model(event, around):
        if asked is not None:
            asked.append((event["id"], [e["id"] for e in around]))
        return Description(event["id"], text, "<speak>ignored</speak>", 0.9, "model")

    return model


# -- The model upgrade -----------------------------------------------------------------------------


def test_a_supported_model_line_is_said_first_and_the_code_line_is_its_fallback():
    track, _ = d.describe(EVENTS, [CLAIM], upgrades={CLAIM["id"]: MODEL_LINE})
    line = said_for(track, CLAIM["id"])
    assert line.source == "model" and line.text == MODEL_LINE and "Home 8" in line.spoken
    lines, _ = d.candidates(EVENTS, [CLAIM], {CLAIM["id"]: MODEL_LINE})
    (claim_line,) = [x for x in lines if x.key == CLAIM["id"]]
    assert claim_line.versions == [MODEL_LINE, f"Fact-checked: {CLAIM['text']}"]
    (cue,) = [c for c in d.audio_cues(track) if c["evidence"] == ["e1", "e2"]]
    assert cue["verified"] is True and cue["text"] == line.spoken


def test_a_model_line_with_an_unsupported_number_is_replaced_by_the_code_line():
    track, refused = d.describe(EVENTS, [CLAIM], upgrades={CLAIM["id"]: "h8 shoots at 143 km/h"})
    line = said_for(track, CLAIM["id"])
    assert line.source == "insight" and line.text == f"Fact-checked: {CLAIM['text']}"
    assert any(r["text"] == "h8 shoots at 143 km/h" and "143" in r["reason"] for r in refused)


def test_a_model_line_naming_a_player_outside_the_evidence_is_refused():
    track, refused = d.describe(EVENTS, [CLAIM], upgrades={CLAIM["id"]: "a3 is beaten as h8 shoots"})
    assert said_for(track, CLAIM["id"]).source == "insight"
    assert any("a3" in r["reason"] for r in refused)


def test_a_model_line_over_its_word_limit_is_refused():
    long = "h4 finds h8 and " * 5 + "h8 shoots on target"
    assert len(long.split()) > d.MODEL_MAX_WORDS
    track, refused = d.describe(EVENTS, [CLAIM], upgrades={CLAIM["id"]: long})
    assert said_for(track, CLAIM["id"]).source == "insight"
    assert any(f"over {d.MODEL_MAX_WORDS} words" in r["reason"] for r in refused)
    at_limit = " ".join(["h8"] * (d.MODEL_MAX_WORDS - 3) + ["shoots", "on", "target"])
    track, _ = d.describe(EVENTS, [CLAIM], upgrades={CLAIM["id"]: at_limit})
    assert said_for(track, CLAIM["id"]).source == "model"


def test_a_model_line_that_would_push_a_goal_late_falls_back_to_the_code_line():
    long = " ".join(["h8"] * (d.MODEL_MAX_WORDS - 3) + ["shoots", "on", "target"])
    goal = event(3, 15.0, "goal", x=104.0, player="h8")  # room for the short line, not the long one
    track, _ = d.describe([*EVENTS, goal], [CLAIM], upgrades={CLAIM["id"]: long})
    line = said_for(track, CLAIM["id"])
    assert line.short and line.source == "insight" and line.text == f"Fact-checked: {CLAIM['text']}"
    assert said_for(track, "e3").lag_s <= d.MAX_LAG_S


def test_the_model_writes_words_only_its_pan_and_ssml_are_code():
    markup = 'h8 shoots <prosody rate="x-fast">on target</prosody>'
    track, _ = d.describe(EVENTS, [CLAIM], upgrades={CLAIM["id"]: markup})
    line = said_for(track, CLAIM["id"])
    assert line.source == "model" and line.pan == d.pan_for(90.0)
    voice = ET.fromstring(line.ssml).find(f"{SSML_NS}voice")
    assert list(voice) == [] and voice.text == line.spoken, "the model's markup is read, not obeyed"


# -- Asking the model ----------------------------------------------------------------------------


def test_the_model_is_asked_only_for_a_verified_moment_with_its_evidence():
    asked = []
    unverified = insight(["e1"], "h4 finds h8", verified=False)
    model = model_answering("h8 shoots", asked)
    texts, calls = asyncio.run(describer.upgrades(EVENTS, [CLAIM, unverified], model, judge_passes))
    assert asked == [("e2", ["e1"])], "the claim's last event, with the earlier evidence around it"
    assert texts == {CLAIM["id"]: "h8 shoots"} and [c["cue"] for c in calls] == [CLAIM["id"]]


def test_the_model_is_never_given_an_unsure_detection():
    asked = []
    unsure = [EVENTS[0] | {"confidence": MIN_CONFIDENCE - 0.01}, EVENTS[1]]
    model = model_answering("h8 shoots", asked)
    texts, _ = asyncio.run(describer.upgrades(unsure, [CLAIM], model, judge_passes))
    assert asked == [] and texts == {}
    sure = [EVENTS[0] | {"confidence": MIN_CONFIDENCE}, EVENTS[1]]
    texts, _ = asyncio.run(describer.upgrades(sure, [CLAIM], model, judge_passes))
    assert asked and texts


def test_a_failing_or_late_model_leaves_the_code_line_and_says_why():
    async def broken(event, around):
        raise ConnectionError("foundry down")

    async def late(event, around):
        await asyncio.sleep(1)
        return Description(event["id"], "h8 shoots", "", 0.0, "model")

    for model, why in ((broken, "ConnectionError"), (late, "TimeoutError")):
        texts, calls = asyncio.run(describer.upgrades(EVENTS, [CLAIM], model, judge_passes, timeout_s=0.01))
        assert texts == {} and why in calls[0]["problem"]
        track, _ = d.describe(EVENTS, [CLAIM], upgrades=texts)
        assert said_for(track, CLAIM["id"]).source == "insight"


# The review's four lines: each passes the code checks (ids, numbers and players are all cited),
# yet each contradicts the evidence (e1 a completed pass, e2 a shot on target, no goal; h4 and h8
# play for home). Only the Judge can refuse them.
CONTRADICTIONS = ("h8 scores for home", "h8 shoots wide", "h4 loses the ball to the away side",
                  "away h8 shoots")


@pytest.mark.parametrize("line", CONTRADICTIONS)
def test_a_model_line_the_judge_refuses_never_airs(line):
    seen = []
    texts, calls = asyncio.run(describer.upgrades(EVENTS, [CLAIM], model_answering(line),
                                                  judge_refusing(*CONTRADICTIONS, seen=seen)))
    assert seen == [(line, ["e1", "e2"], ["e1", "e2"])], "the Judge sees the line and all its evidence"
    assert texts == {} and calls[0]["problem"].startswith("judge:")
    track, _ = d.describe(EVENTS, [CLAIM], upgrades=texts)
    assert said_for(track, CLAIM["id"]).source == "insight", "the code line stays"


def test_the_judge_only_sees_lines_the_code_checks_pass():
    seen = []
    model = model_answering("h8 shoots at 143 km/h")
    texts, calls = asyncio.run(describer.upgrades(EVENTS, [CLAIM], model, judge_refusing(seen=seen)))
    assert seen == [] and texts == {} and calls[0]["problem"].startswith("code checks:")


def test_a_failing_or_late_judge_keeps_the_code_line():
    async def down(claim, evidence):
        raise ConnectionError("judge down")

    async def late(claim, evidence):
        await asyncio.sleep(1)
        return Verdict(ok=True)

    for judge, why in ((down, "ConnectionError"), (late, "TimeoutError")):
        texts, calls = asyncio.run(describer.upgrades(EVENTS, [CLAIM], model_answering(MODEL_LINE), judge,
                                                      timeout_s=0.05))
        assert texts == {} and "judge unavailable" in calls[0]["problem"] and why in calls[0]["problem"]


def test_a_model_line_needs_the_claims_own_code_line_to_pass():
    # The claim states a number its evidence does not hold: its code line is refused, and a model
    # line for the same moment must not air in its place.
    false_claim = insight(["e1", "e2"], "h8 shoots on target at 143 km/h")
    track, refused = d.describe(EVENTS, [false_claim], upgrades={false_claim["id"]: MODEL_LINE})
    assert all(s.event != false_claim["id"] for s in track.said)
    assert any("143" in r["reason"] for r in refused)


def test_the_published_agent_is_asked_for_words_and_its_tokens_are_counted():
    sent = []

    class Agent:
        async def run(self, prompt):
            sent.append(json.loads(prompt))
            return SimpleNamespace(value=describer.Line(text="h8 shoots on target"), text="",
                                   usage_details={"input_token_count": 120, "output_token_count": 9})

    tokens: dict[str, int] = {}
    answer = asyncio.run(describer.foundry_describe(Agent(), tokens)(EVENTS[1], [EVENTS[0]]))
    assert answer.text == "h8 shoots on target" and answer.source == "model"
    assert sent[0]["event"]["id"] == "e2" and [e["id"] for e in sent[0]["around"]] == ["e1"]
    assert "x" not in sent[0]["event"], "the model reads the fact-checker's fields, not positions"
    assert tokens == {"input": 120, "output": 9}


# -- Speech outage -------------------------------------------------------------------------------


def test_a_speech_outage_still_shows_every_line_and_its_cue_says_speech_is_unavailable(tmp_path):
    def down(markup, fmt):
        raise ConnectionError("speech service unreachable")

    offline, _ = d.describe(EVENTS, [CLAIM])
    voice = d.Voice(down)
    track, refused = d.describe(EVENTS, [CLAIM], voice)
    voice.save(track, tmp_path)
    assert [s.text for s in track.said] == [s.text for s in offline.said], "the estimate keeps the schedule"
    assert all(s.speech == "unavailable" and s.file is None for s in track.said)
    assert all(c["speech"] == "unavailable" for c in d.audio_cues(track))
    summary = d.write_track(track, refused, tmp_path, 0.0)
    assert summary["synth_failed"] == len(voice.failed) > 0
    assert summary["synth_requests"] == len(voice.failed), "a failed request is still a request"
    assert "ConnectionError" in next(iter(voice.failed.values()))


def test_a_spoken_line_says_so_and_an_offline_one_carries_no_speech_field(tmp_path):
    voice = d.Voice(lambda markup, fmt: (fake_wav(0.5), 0.2))
    track, _ = d.describe(EVENTS, [], voice)
    voice.save(track, tmp_path)
    assert all(c["speech"] == "spoken" for c in d.audio_cues(track))
    offline, _ = d.describe(EVENTS, [])
    assert all("speech" not in c for c in d.audio_cues(offline))


# -- SSML ----------------------------------------------------------------------------------------


@pytest.mark.parametrize("text", ['h7 <break time="9s"/> & a1', "it's \"in\"", "</voice><voice name='x'>"])
def test_ssml_escapes_markup_ampersands_and_quotes(text):
    for priority in (d.PRIORITY["shot"], d.PRIORITY["pass"]):  # with and without prosody
        document = d.ssml(text, priority)
        voice = ET.fromstring(document).find(f"{SSML_NS}voice")
        inner = voice[0] if len(voice) else voice
        assert list(inner) == [] and inner.text == text, "the text is read out exactly, never markup"
        body = document[document.index(">", document.index("<voice")) + 1:]
        for raw, entity in (("<", "&lt;"), ("&", "&amp;"), ('"', "&quot;"), ("'", "&apos;")):
            assert body.count(entity) == text.count(raw), f"{raw!r} must be written {entity}"


def test_the_claim_speech_path_escapes_quotes_too(monkeypatch):
    sent = []
    monkeypatch.setattr(tts, "synthesize_ssml", lambda document: sent.append(document) or (b"", 0.0))
    tts.synthesize("it's \"in\" & <out>")
    assert "&quot;" in sent[0] and "&apos;" in sent[0] and "&lt;out&gt;" in sent[0]
    assert ET.fromstring(sent[0]).find("voice").text == "it's \"in\" & <out>"


# -- The run ------------------------------------------------------------------------------------


def test_the_default_run_never_loads_the_model():
    # mutation: import ninety.agents.describer at the top of ninety/e2e.py
    code = "import sys, ninety.e2e; print('ninety.agents.describer' in sys.modules)"
    loaded = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True,
                            cwd=ROOT)
    assert loaded.stdout.strip() == "False"


def test_e2e_with_the_describer_model_airs_its_checked_line(tmp_path, monkeypatch):
    asked = []

    @contextlib.asynccontextmanager
    async def fake_foundry(tokens):
        tokens["input"] = 100
        yield model_answering("h8 shoots on target", asked), judge_passes

    monkeypatch.setattr(describer, "foundry_model", fake_foundry)
    clip, detections, events_file = write_clip(tmp_path)
    out = tmp_path / "bundle"
    e2e.main([str(clip), "--out", str(out), "--detections", str(detections), "--frames",
              "--events-file", str(events_file), "--describer", "foundry"])
    manifest = json.loads((out / "manifest.json").read_text())
    audio = json.loads((out / "audio.json").read_text())
    assert manifest["audio"]["describer"]["mode"] == "foundry"
    assert manifest["audio"]["describer"]["tokens"] == {"input": 100}
    assert asked, "the offline Analyst's verified claim is a verified moment"
    assert [s["source"] for s in audio["said"]].count("model") == 1
    assert manifest["audio"]["describer"]["unavailable"] is None


def run_with_foundry(tmp_path, monkeypatch, fails_with: Exception) -> tuple[dict, dict]:
    @contextlib.asynccontextmanager
    async def unreachable(tokens):
        raise fails_with
        yield  # pragma: no cover

    monkeypatch.setattr(describer, "foundry_model", unreachable)
    clip, detections, events_file = write_clip(tmp_path)
    out = tmp_path / "bundle"
    e2e.main([str(clip), "--out", str(out), "--detections", str(detections), "--frames",
              "--events-file", str(events_file), "--describer", "foundry"])
    return (json.loads((out / "audio.json").read_text()),
            json.loads((out / "manifest.json").read_text())["audio"]["describer"])


def test_foundry_unreachable_at_start_still_writes_the_code_track(tmp_path, monkeypatch):
    audio, record = run_with_foundry(tmp_path, monkeypatch, ConnectionError("sign-in expired"))
    assert audio["said"] and all(s["source"] != "model" for s in audio["said"])
    assert record["unavailable"] == "ConnectionError: sign-in expired" and record["calls"] == []


def test_a_drifted_agent_still_refuses_to_run(tmp_path, monkeypatch):
    with pytest.raises(RegistryDrift):
        run_with_foundry(tmp_path, monkeypatch, RegistryDrift("ninety-describer changed since version 1"))
