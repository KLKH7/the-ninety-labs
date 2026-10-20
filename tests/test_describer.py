"""The Describer: a code line for every event at once, a model line only if it passes the
fact-checker, SSML that never turns text into markup, a pan that follows the ball, and a line that
still airs when speech is down. No Azure: the model and speech are fakes of their contracts."""

import asyncio
import json
import xml.etree.ElementTree as ET

import pytest
from jsonschema import validate

from ninety.agents import describer
from ninety.agents.contracts import SCHEMAS, Description
from ninety.agents.cues import SCHEMA
from ninety.agents.describer import Describer, code_description, pan_for, percentile, report
from ninety.agents.factcheck import Claim, check
from ninety.match.facts import match_events
from ninety.speech.tts import ssml

SHOT = {"id": "e00017", "t": 49.24, "type": "shot", "team": "home", "player": "h10", "receiver": None,
        "x": 91.73, "y": 39.64, "end_x": 101.06, "end_y": 33.98, "outcome": "on_target",
        "ball_speed_kmh": 55.6, "source": "truth", "confidence": None}
PASS = {"id": "e00016", "t": 47.0, "type": "pass", "team": "home", "player": "h7", "receiver": "h10",
        "intended": "h10", "x": 80.0, "y": 40.0, "end_x": 90.0, "end_y": 40.0, "outcome": "success",
        "ball_speed_kmh": 40.0, "source": "truth", "confidence": None}
SSML_NS = "{http://www.w3.org/2001/10/synthesis}"


async def _speak(document: str) -> bytes:
    return document.encode()


def _model(text: str):
    async def model(event, around):
        return Description(event["id"], text, "<speak>ignored</speak>", 0.9, "model")

    return model


def _all(d: Describer, event: dict, around=(), verified=False) -> list:
    async def go():
        return [s async for s in d.describe(event, around, verified)]

    return asyncio.run(go())


# -- Speech outage -------------------------------------------------------------------------------


def test_a_speech_outage_still_gives_the_code_line_and_says_speech_is_unavailable():
    async def down(document):
        raise ConnectionError("speech service unreachable")

    d = Describer(speak=down)
    (line,) = _all(d, SHOT)
    assert line.description.source == "code" and line.description.text == "H10 takes a shot"
    assert line.audio is None and line.ms_to_speech is None
    assert line.cue["speech"] == "unavailable" and line.cue["text"] == line.description.text
    assert d.records[0]["aired"] and not d.records[0]["spoken"]
    assert "ConnectionError" in d.records[0]["problems"][0]


def test_speech_slower_than_the_target_counts_as_unavailable():
    async def slow(document):
        await asyncio.sleep(1)
        return b"late"

    (line,) = _all(Describer(speak=slow, speech_timeout_s=0.01), SHOT)
    assert line.audio is None and line.cue["speech"] == "unavailable"


def test_a_spoken_line_says_so_and_logs_its_time_to_speech():
    ticks = iter([10.0, 10.25])
    (line,) = _all(Describer(speak=_speak, clock=lambda: next(ticks)), SHOT)
    assert line.cue["speech"] == "spoken" and line.audio == line.description.ssml.encode()
    assert line.ms_to_speech == pytest.approx(250.0)


# -- SSML ----------------------------------------------------------------------------------------


@pytest.mark.parametrize("text", ['h7 <break time="9s"/> & a1', "it's \"in\"", "</voice><voice name='x'>"])
def test_ssml_escapes_markup_ampersands_and_quotes(text):
    document = ssml(text)
    root = ET.fromstring(document)  # well-formed, whatever the text
    (voice,) = list(root)
    assert voice.tag == f"{SSML_NS}voice" and list(voice) == [], "text must never become an element"
    assert voice.text == text, "the text is read out exactly"
    body = document[document.index(">", document.index("<voice")) + 1:document.index("</voice></speak>")]
    for raw, entity in (("<", "&lt;"), ("&", "&amp;"), ('"', "&quot;"), ("'", "&apos;")):
        assert body.count(entity) == text.count(raw), f"{raw!r} must be written {entity}"


def test_a_model_line_with_markup_is_spoken_as_text():
    text = 'H10 shoots <prosody rate="x-fast">'
    d = Describer(speak=_speak, model=_model(text))
    # The fact-checker passes it (no number, a cited player); the markup is read out, not obeyed.
    code, model = _all(d, SHOT, verified=True)
    assert model.description.source == "model"
    voice = list(ET.fromstring(model.description.ssml))[0]
    assert voice.text == text and list(voice) == []


# -- The model upgrade -----------------------------------------------------------------------------


def test_a_model_line_with_an_unsupported_number_is_replaced_by_the_code_line():
    d = Describer(speak=_speak, model=_model("H10 shoots from 30 metres at 143 km/h, on target"))
    lines = _all(d, SHOT, [PASS], verified=True)
    assert [s.description.source for s in lines] == ["code"]
    refused = [r for r in d.records if r["source"] == "model"]
    assert refused and not refused[0]["aired"]
    assert any("143" in p for p in refused[0]["problems"])


def test_a_supported_model_line_airs_after_the_code_line_and_replaces_its_cue():
    text = "h7 finds h10, who shoots on target at 56 km/h"
    lines = _all(Describer(speak=_speak, model=_model(text)), SHOT, [PASS], verified=True)
    code, model = lines
    assert code.description.source == "code" and model.description.text == text
    assert model.cue["replaces"] == code.cue["id"] and model.cue["verified"]
    assert model.cue["evidence"] == ["e00016", "e00017"]
    # The model writes words only: its pan and SSML are thrown away and rebuilt by code.
    assert model.description.pan == pan_for(SHOT["x"]) and "ignored" not in model.description.ssml


def test_the_model_is_asked_only_for_a_verified_moment():
    asked = []

    async def model(event, around):
        asked.append(event["id"])
        return Description(event["id"], "H10 shoots", "", 0.0, "model")

    assert [s.description.source for s in _all(Describer(speak=_speak, model=model), SHOT)] == ["code"]
    assert asked == []


def test_the_code_line_is_out_before_the_model_answers():
    async def go():
        gate = asyncio.Event()

        async def model(event, around):
            await gate.wait()
            return Description(event["id"], "H10 shoots", "", 0.0, "model")

        stream = Describer(speak=_speak, model=model).describe(SHOT, (), True).__aiter__()
        first = await asyncio.wait_for(stream.__anext__(), 1)  # the model has not answered
        gate.set()
        second = await stream.__anext__()
        return first, second

    first, second = asyncio.run(go())
    assert first.description.source == "code" and second.description.source == "model"


def test_a_failing_model_keeps_the_code_line():
    async def broken(event, around):
        raise TimeoutError("no answer")

    d = Describer(speak=_speak, model=broken)
    assert [s.description.source for s in _all(d, SHOT, verified=True)] == ["code"]
    assert "model unavailable" in d.records[-1]["problems"][0]


# -- Pan -----------------------------------------------------------------------------------------


def test_pan_follows_the_ball_from_left_to_right_and_stays_in_bounds():
    assert pan_for(0.0) == -1.0 and pan_for(52.5) == 0.0 and pan_for(105.0) == 1.0
    xs = [x / 2 for x in range(-20, 232)]  # 10 m beyond each goal line, as a detection may be
    pans = [pan_for(x) for x in xs]
    assert all(-1.0 <= p <= 1.0 for p in pans)
    assert pans == sorted(pans) and pans[0] == -1.0 and pans[-1] == 1.0
    on_pitch = [pan_for(x) for x in xs if 0 <= x <= 105]
    assert len(set(on_pitch)) == len(on_pitch), "every metre of the pitch moves the sound"


def test_every_line_and_cue_carries_the_pan_of_its_event():
    left, right = {**SHOT, "id": "e1", "x": 10.0}, {**SHOT, "id": "e2", "x": 95.0}
    d = Describer(speak=_speak)
    (a,), (b,) = _all(d, left), _all(d, right)
    assert a.cue["pan"] == a.description.pan == pan_for(10.0) < 0 < pan_for(95.0) == b.cue["pan"]


# -- Code lines ----------------------------------------------------------------------------------


def _passes(event):
    line = code_description(event)
    assert "None" not in line.text, f"a missing field is spoken: {line.text!r}"
    facts = describer.facts(event)
    assert check(Claim(line.text, [event["id"]]), {event["id"]: facts}).ok, line.text
    validate(describer.audio_cue(line, event["t"], [event["id"]], True), SCHEMA)


EVENT_SCHEMA = json.loads((SCHEMAS / "match_event.schema.json").read_text())
EVENT_KINDS = tuple(EVENT_SCHEMA["properties"]["type"]["enum"])


@pytest.mark.parametrize("kind", EVENT_KINDS)
@pytest.mark.parametrize("acted", [True, False])
def test_every_kind_of_event_gets_a_code_line_the_fact_checker_passes(kind, acted):
    # Built here, not drawn from a seed (lesson 47): every kind the schema allows, with and without
    # a known player, as a detected event may leave it out.
    event = {"id": "e1", "t": 12.0, "type": kind, "team": "away", "x": 40.0, "y": 30.0,
             "player": "a4" if acted else None, "receiver": "h9" if acted else None,
             "outcome": None, "ball_speed_kmh": None, "end_x": None, "end_y": None, "source": "truth"}
    _passes(event)


def test_every_event_of_a_match_gets_a_code_line_the_fact_checker_passes():
    for event in match_events(7, 5):
        _passes(event)


@pytest.mark.parametrize(("outcome", "text"), [
    ("success", "H2 wins the ball from a11"),
    ("fail", "H2 challenges a11, and the away side keep the ball"),
    (None, "H2 challenges a11"),
])
def test_a_tackle_line_follows_its_outcome(outcome, text):
    tackle = {**SHOT, "type": "tackle", "player": "h2", "receiver": "a11", "outcome": outcome,
              "ball_speed_kmh": None, "end_x": None, "end_y": None}
    assert code_description(tackle).text == text


def test_a_detected_event_without_optional_fields_still_gets_a_line():
    detected = {"id": "d1", "t": 3.0, "type": "pass", "team": "away", "x": 20.0, "y": 30.0,
                "source": "vision", "confidence": 0.8}
    line = code_description(detected)
    assert line.text == "Pass by the away side"
    assert line.pan == pan_for(20.0)


# -- The report ----------------------------------------------------------------------------------


def test_percentile_is_nearest_rank():
    values = list(range(1, 21))
    assert percentile(values, 0.5) == 10 and percentile(values, 0.95) == 19 and percentile([7], 0.95) == 7


def test_the_report_counts_only_what_was_measured():
    records = [
        {"event": "e1", "source": "code", "aired": True, "spoken": True, "ms_to_speech": 800.0,
         "chars": 10, "problems": []},
        {"event": "e2", "source": "code", "aired": True, "spoken": False, "ms_to_speech": None,
         "chars": 12, "problems": ["speech unavailable: ConnectionError: x"]},
        {"event": "e2", "source": "model", "aired": False, "spoken": False, "ms_to_speech": None,
         "chars": 0, "problems": ["number 143 is not a cited ball_speed_kmh"]},
    ]
    meta = {"when": "now", "commit": "abc", "command": "cmd", "seed": 7, "minutes": "5", "events": 2,
            "voice": "v", "region": "r", "model": "m", "upgrade": "u"}
    text = report(records, meta, {"input": 100})
    assert "| code | 2 | 1 | 800 | 800 | 800 |" in text and "| model | 0 | 0 | n/a | n/a | n/a |" in text
    assert "refused: 1" in text and "not spoken, cue marked unavailable: e2" in text
    assert "| characters sent to speech (line text) | 22 |" in text
    assert "| model output tokens | not reported |" in text


# -- Confidence ----------------------------------------------------------------------------------


def test_an_unsure_detection_is_not_described_and_unsure_context_is_not_given_to_the_model():
    from ninety.agents.factcheck import MIN_CONFIDENCE

    unsure = {**SHOT, "source": "vision", "confidence": MIN_CONFIDENCE - 0.01}
    d = Describer(speak=_speak)
    assert _all(d, unsure) == []
    assert not d.records[0]["aired"] and "held" in d.records[0]["problems"][0]
    sure = {**SHOT, "source": "vision", "confidence": MIN_CONFIDENCE}
    assert [s.description.source for s in _all(Describer(speak=_speak), sure)] == ["code"]

    seen = []

    async def model(event, around):
        seen.extend(e["id"] for e in around)
        return Description(event["id"], "H10 shoots", "", 0.0, "model")

    unsure_pass = {**PASS, "source": "vision", "confidence": MIN_CONFIDENCE - 0.01}
    lines = _all(Describer(speak=_speak, model=model), sure, [unsure_pass], verified=True)
    assert seen == [] and lines[-1].cue["evidence"] == ["e00017"]
