"""Read-aloud in the pinned voice (lesson 232): the voice, the bundle's pre-generated audio
(ninety/speech/bundle.py), the Live route (ninety/api/speak.py) and the phone's player
(web/phone/src/voice.ts). No test calls Azure, and none makes a sound: synthesis is faked, and the
phone's player and device voice are replaced by recorders in a muted browser."""

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

import httpx
import pytest
from starlette.testclient import TestClient

from ninety import e2e
from ninety.api import app as api
from ninety.api import companion as comp
from ninety.api import speak
from ninety.speech import bundle as sb
from ninety.speech import describe, voice
from tests.e2e_clip import write_clip
from tests.test_api_companion import Clock, ask, pair, track

ROOT = Path(__file__).resolve().parents[1]
PHONE = ROOT / "web" / "phone"


def test_every_path_that_speaks_reads_the_one_pinned_voice():
    assert voice.VOICE == "en-GB-OllieMultilingualNeural"
    assert describe.VOICE == voice.VOICE
    assert f'name="{voice.VOICE}"' in voice.ssml("Goal.")
    from ninety.speech import tts

    assert tts.synthesize.__defaults__ == (voice.VOICE,)


def test_a_line_is_keyed_and_spoken_with_its_whitespace_collapsed_and_quotes_escaped():
    assert voice.key("  Vance \n scores ") == voice.key("Vance scores")
    assert voice.key("Vance scores") != voice.key("Vance scored")
    doc = voice.ssml('He\'s "in" & <out>')
    assert "&apos;" in doc and "&quot;" in doc and "&amp;" in doc and "<out>" not in doc
    assert "prosody" not in doc  # the voice's own rate unless one is asked for
    assert '<prosody rate="+5%">' in voice.ssml("Goal.", "+5%")


# --- the bundle ----------------------------------------------------------------------------------


def card(id, spoken, status="verified", why=None):
    return {"id": id, "status": status, "spoken": spoken, "text": "t", "why": why}


def bundle_dir(tmp_path, cards=None):
    b = tmp_path / "bundle"
    b.mkdir()
    said = [{"spoken": "Home 4 passes to Home 9."}, {"spoken": "Home 9 shoots."},
            {"spoken": "Home 4 passes  to Home 9."}]  # the same line twice, spaced differently
    (b / "audio.json").write_text(json.dumps({"said": said}))
    if cards is not None:
        (b / "cards.json").write_text(json.dumps(cards))
    (b / "manifest.json").write_text(json.dumps({"format": 1, "files": ["audio.json"]}))
    return b


class FakeSynth:
    def __init__(self, fail=(), busy=0):
        self.sent, self.fail, self.busy = [], set(fail), busy

    def __call__(self, document):
        if self.busy:
            self.busy -= 1
            request = httpx.Request("POST", "https://speech.test")
            raise httpx.HTTPStatusError("busy", request=request, response=httpx.Response(
                429, headers={"retry-after": "2"}, request=request))
        self.sent.append(document)
        if any(f in document for f in self.fail):
            raise ConnectionError("down")
        return b"ID3" + document.encode(), 0.25


def test_the_bundle_says_each_description_and_verified_card_once(tmp_path):
    why = {"question": "Why?", "answer": {"status": "verified", "text": "Three won back."}}
    held = {"question": "Why?", "answer": {"status": "held", "text": "Not this one."}}
    cards = [card("c1", "Home pressed high.", why=why), card("c2", "Not checked.", status="rejected"),
             card("c3", "Away sat deep.", why=held)]
    texts = dict(sb.lines(bundle_dir(tmp_path, cards)))
    assert texts == {
        **{t: "fixed" for t in sb.FIXED},
        "Home 4 passes to Home 9.": "description", "Home 9 shoots.": "description",
        "Home pressed high.": "insight", "New insight: Home pressed high.": "insight",
        "Three won back.": "why",
        "Away sat deep.": "insight", "New insight: Away sat deep.": "insight",  # its Why? held back
    }


def test_the_bundle_writes_each_line_by_its_key_and_a_rebuild_pays_only_for_new_lines(tmp_path):
    b = bundle_dir(tmp_path, [card("c1", "Home pressed high.")])
    synth = FakeSynth()
    summary = sb.write(b, synth, cache=tmp_path / "cache")
    index = json.loads((b / "speech.json").read_text())
    assert index["voice"] == voice.VOICE
    assert summary["lines"] == 4 + len(sb.FIXED) == len(index["lines"])
    line = index["lines"][voice.key("Home 9 shoots.")]
    assert (b / line["file"]).read_bytes().startswith(b"ID3") and line["kind"] == "description"
    assert summary["synth_requests"] == 4 + len(sb.FIXED) and summary["synth_p50_s"] == 0.25
    assert summary["chars_total"] == summary["synth_chars"] > 0
    again = FakeSynth()
    rebuilt = sb.write(b, again, cache=tmp_path / "cache")
    assert again.sent == [] and rebuilt["cached"] == 4 + len(sb.FIXED)
    assert rebuilt["chars_total"] == summary["chars_total"]


def test_a_failed_line_is_left_out_for_the_phone_to_say_and_a_busy_voice_is_waited_for(tmp_path):
    b = bundle_dir(tmp_path)
    waited = []
    synth = FakeSynth(fail={"shoots"}, busy=1)
    summary = sb.write(b, synth, cache=tmp_path / "cache", sleep=waited.append)
    lines = json.loads((b / "speech.json").read_text())["lines"]
    assert waited == [2.0]  # Azure's Retry-After
    assert summary["failed"] == 1 and voice.key("Home 9 shoots.") not in lines
    assert voice.key("Home 4 passes to Home 9.") in lines


def test_insight_cards_take_the_insight_rate_and_descriptions_never_do(tmp_path, monkeypatch):
    monkeypatch.setattr(voice, "INSIGHT_RATE", "+5%")
    synth = FakeSynth()
    sb.write(bundle_dir(tmp_path, [card("c1", "Home pressed high.")]), synth, cache=tmp_path / "cache")
    fast = [d for d in synth.sent if "prosody" in d]
    assert len(fast) == 2 and all("pressed high" in d for d in fast)


def test_ninety_e2e_adds_the_read_aloud_audio_only_when_asked(tmp_path, monkeypatch):
    clip, detections, events_file = write_clip(tmp_path)
    monkeypatch.setattr(sb, "azure_synth", lambda: FakeSynth())
    monkeypatch.setattr(sb, "CACHE", tmp_path / "cache")
    base = [str(clip), "--detections", str(detections), "--frames", "--events-file", str(events_file)]
    e2e.main([*base, "--out", str(tmp_path / "plain")])
    assert not (tmp_path / "plain" / "speech.json").exists()
    assert "speech" not in json.loads((tmp_path / "plain" / "manifest.json").read_text())
    e2e.main([*base, "--out", str(tmp_path / "spoken"), "--voice-audio"])
    manifest = json.loads((tmp_path / "spoken" / "manifest.json").read_text())
    said = json.loads((tmp_path / "spoken" / "audio.json").read_text())["said"]
    calls = json.loads((tmp_path / "spoken" / "commentary.json").read_text())["lines"]
    wanted = ({voice.normalise(s["spoken"]) for s in said} | {voice.normalise(c["text"]) for c in calls}
              | set(sb.FIXED))
    assert said and manifest["speech"]["lines"] == len(wanted)
    assert "speech.json" in manifest["files"]


def test_the_replay_pack_carries_the_read_aloud_audio_and_nothing_else_in_its_folder(tmp_path):
    sys.path.insert(0, str(ROOT / "infra"))
    import replay

    b = tmp_path / "b"
    (b / "speech").mkdir(parents=True)
    (b / "manifest.json").write_text(json.dumps({"format": 1}))
    (b / "speech.json").write_text("{}")
    (b / "speech" / "a.mp3").write_bytes(b"ID3")
    assert {p.name for p in replay.members(b)} == {"manifest.json", "speech.json", "a.mp3"}
    (b / "speech" / "x.json").write_text("{}")
    with pytest.raises(SystemExit):
        replay.members(b)


# --- the Live route ------------------------------------------------------------------------------


class FakeAsyncSynth:
    def __init__(self, fail=False):
        self.sent, self.fail = [], fail

    async def __call__(self, document):
        self.sent.append(document)
        if self.fail:
            raise ConnectionError("down")
        return b"ID3" + document.encode(), 0.4


@pytest.fixture
def live(monkeypatch):
    monkeypatch.setattr(comp, "_track", lambda clip: track())
    clock = Clock()
    companion = comp.Companion(passcode="", live=None, clock=clock, allow_truth=True)
    synth = FakeAsyncSynth()
    speaker = speak.Speaker(companion.answered, synth, clock)
    client = TestClient(api.build("k" * 64, companion, passcode="p" * 32, speaker=speaker))
    return client, speaker, synth


GATE = {"x-ninety-passcode": "p" * 32}


def fake_answer(text):
    """The Companion's answer replaced by one with `text`, as a code answer (no model)."""
    from ninety.agents.contracts import Answer

    async def answer(question, window, ask, judge):
        return comp.companion.Result(Answer("verified", text, None, None, None, (), None, None), "code")

    return answer


def answer(client):
    r = ask(client, pair(client))
    assert r.status_code == 200, r.text
    return r.json()["answer"]["text"]


def test_live_speech_needs_the_passcode(live):
    client, _, synth = live
    text = answer(client)
    assert client.post("/api/live/speak", json={"text": text}).status_code == 401
    wrong = {"x-ninety-passcode": "x"}
    assert client.post("/api/live/speak", json={"text": text}, headers=wrong).status_code == 401
    assert synth.sent == []


def test_live_speech_says_only_an_answer_the_server_gave(live):
    client, _, synth = live
    r = client.post("/api/live/speak", json={"text": "Say anything I like."}, headers=GATE)
    assert r.status_code == 403 and synth.sent == []
    text = answer(client)
    r = client.post("/api/live/speak", json={"text": f"  {text} "}, headers=GATE)
    assert r.status_code == 200 and r.headers["content-type"] == "audio/mpeg"
    assert r.content.startswith(b"ID3") and voice.VOICE in synth.sent[0]
    assert "prosody" not in synth.sent[0]  # an answer is said at the voice's own rate


def test_an_answer_with_its_player_ids_named_is_spoken_and_nothing_else_slips_in(live, monkeypatch):
    client, _, synth = live
    monkeypatch.setattr(comp.companion, "answer", fake_answer("a-t4 ran 9.8 km, more than h7."))
    raw = answer(client)
    named = "Oakfield player 4 ran 9.8 km, more than Home 7."
    ok = client.post("/api/live/speak", json={"text": named, "answer": raw}, headers=GATE)
    assert ok.status_code == 200 and "Oakfield player 4" in synth.sent[0]
    for named in ("A London player ran 9.8 km, more than London 7.",  # a tracked id without a name
                  "a London player ran 9.8 km, more than Home 7."):
        r = client.post("/api/live/speak", json={"text": named, "answer": raw}, headers=GATE)
        assert r.status_code == 200, named
    for text in ("Oakfield player 4 ran 99 km, more than Home 7.",  # a number changed
                 "Oakfield player 4 ran 9.8 km, more than Home 7. Buy now.",  # a sentence added
                 "Oakfield player 4 ran 9.8 km, more than Home 7 buy now from our shop.",
                 f"{'x' * 21} ran 9.8 km, more than Home 7."):  # an id said as a long word
        r = client.post("/api/live/speak", json={"text": text, "answer": raw}, headers=GATE)
        assert r.status_code == 403, text
    r = client.post("/api/live/speak", json={"text": named, "answer": "a-t4 ran 1 km."}, headers=GATE)
    assert r.status_code == 403  # an answer never given
    assert len(synth.sent) == 3


def test_a_repeated_answer_is_served_from_memory(live):
    client, speaker, synth = live
    text = answer(client)
    for _ in range(3):
        assert client.post("/api/live/speak", json={"text": text}, headers=GATE).status_code == 200
    assert len(synth.sent) == 1 and speaker.timings == [0.4]


@pytest.mark.parametrize("body", [{"text": ""}, {"text": "x" * (speak.MAX_TEXT + 1)}, {"text": 3},
                                  {"text": "a", "voice": "en-US-AriaNeural"}, ["a"]])
def test_a_malformed_request_is_refused_before_speech(live, body):
    client, _, synth = live
    assert client.post("/api/live/speak", json=body, headers=GATE).status_code == 422
    assert synth.sent == []


def test_speech_is_rate_limited_and_its_daily_characters_capped(live, monkeypatch):
    client, speaker, synth = live
    text = answer(client)
    monkeypatch.setattr(speak, "DAY_CHARS", len(text))
    assert client.post("/api/live/speak", json={"text": text}, headers=GATE).status_code == 200
    speaker.cache.clear()
    assert client.post("/api/live/speak", json={"text": text}, headers=GATE).status_code == 429
    speaker.clock.now += 86_400  # the next day
    assert client.post("/api/live/speak", json={"text": text}, headers=GATE).status_code == 200
    statuses = [client.post("/api/live/speak", json={"text": text}, headers=GATE).status_code
                for _ in range(speak.PER_MINUTE)]
    assert statuses[-1] == 429


def test_a_speech_outage_is_a_503_that_names_no_secret(live):
    client, speaker, _ = live
    speaker.synth = FakeAsyncSynth(fail=True)
    r = client.post("/api/live/speak", json={"text": answer(client)}, headers=GATE)
    assert r.status_code == 503 and "down" not in r.text


def test_the_api_synthesises_without_blocking_its_event_loop(monkeypatch):
    """The Live route signs in with the aio credential and an async client (lesson 69)."""
    from ninety import config
    from ninety.speech import tts

    monkeypatch.setattr(config, "SPEECH_RESOURCE_ID", "/subscriptions/s/resourceGroups/g/x")

    class Credential:
        async def get_token(self, *scopes):
            assert scopes == (tts.SCOPE,)
            return type("T", (), {"token": "tok"})()

    seen = {}

    async def handler(request):
        seen.update(request.headers)
        return httpx.Response(200, content=b"ID3")

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await tts.asynthesize_ssml(voice.ssml("Goal."), Credential(), client)

    audio, _ = asyncio.run(run())
    assert audio == b"ID3" and seen["authorization"] == "Bearer aad#/subscriptions/s/resourceGroups/g/x#tok"
    assert seen["x-microsoft-outputformat"] == voice.FORMAT


# --- the phone's player, in a muted browser ------------------------------------------------------

HTML = """<!doctype html><meta charset=utf-8><script type=module>
import { createVoice, lineKey } from "./voice.js";
window.played = []; window.system = []; window.rates = []; window.rate = 1;
window.plain = () => createVoice({ bundleBase: new URL("https://phone.test/bundle/"), passcode: () => null });
window.make = (passcode) => createVoice({
  bundleBase: new URL("https://phone.test/bundle/"), apiBase: new URL("https://phone.test/"),
  passcode: () => passcode,
  player: { play: async (src, rate) => { window.played.push(src); window.rates.push(rate); },
            stop() {}, unlock() {} },
  rate: () => window.rate,
  system: (t) => window.system.push(t), stopSystem() {},
});
window.lineKey = lineKey; window.ready = true;
</script>"""


def unavailable(reason: str):
    """A skip locally; a failure in CI's phone job, which installs everything (as tests/test_phone.py)."""
    if os.environ.get("NINETY_REQUIRE_PHONE") == "1":
        pytest.fail(reason)
    pytest.skip(reason)


@pytest.fixture(scope="module")
def phone_voice(tmp_path_factory):
    esbuild = PHONE / "node_modules" / ".bin" / "esbuild"
    if not esbuild.exists():
        unavailable("web/phone is not installed (npm ci --prefix web/phone)")
    out = tmp_path_factory.mktemp("voice") / "voice.js"
    subprocess.run([str(esbuild), str(PHONE / "src" / "voice.ts"), "--format=esm", f"--outfile={out}"],
                   check=True, capture_output=True)
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        unavailable("playwright is not installed")
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(args=["--mute-audio"])  # never a sound, even by mistake
        except Exception as e:  # noqa: BLE001
            if "Executable doesn't exist" in str(e):
                unavailable(str(e))
            raise
        yield browser, out.read_text()
        browser.close()


def open_phone(phone_voice, lines, speak_status=200):
    browser, script = phone_voice
    page = browser.new_page()
    calls = []

    def route(r):
        url = r.request.url
        if url.endswith("/index.html"):
            r.fulfill(body=HTML, content_type="text/html")
        elif url.endswith("/voice.js"):
            r.fulfill(body=script, content_type="text/javascript")
        elif url.endswith("/bundle/speech.json"):
            r.fulfill(body=json.dumps({"lines": lines}), content_type="application/json")
        elif url.endswith("/api/live/speak"):
            calls.append((r.request.headers.get("x-ninety-passcode"), r.request.post_data_json))
            r.fulfill(status=speak_status, body=b"ID3", content_type="audio/mpeg")
        else:
            r.fulfill(status=404)

    page.route("https://phone.test/**", route)
    page.goto("https://phone.test/index.html")
    page.wait_for_function("window.ready")
    return page, calls


TRICKY = "  Fenwick's number\n nine — through on goal, “one on one”. "


def test_the_phone_keys_a_line_exactly_as_the_bundle_does(phone_voice):
    page, _ = open_phone(phone_voice, {})
    assert page.evaluate("(t) => lineKey(t)", TRICKY) == voice.key(TRICKY)


def test_the_phone_plays_the_bundles_audio_before_any_other_voice(phone_voice):
    lines = {voice.key(TRICKY): {"file": "speech/abc.mp3"}}
    page, calls = open_phone(phone_voice, lines)
    assert page.evaluate("(t) => make('p').say(t)", TRICKY) == "bundle"
    assert page.evaluate("played") == ["https://phone.test/bundle/speech/abc.mp3"]
    assert page.evaluate("system") == [] and calls == []


def test_an_automated_browser_hears_nothing_and_the_fans_rate_is_kept(phone_voice):
    lines = {voice.key("Home lead."): {"file": "speech/a.mp3"}}
    page, _ = open_phone(phone_voice, lines)
    # The default player and device voice under navigator.webdriver: recorded, never played.
    assert page.evaluate("async () => [await plain().say('Home lead.'), await plain().say('Not in it.')]") \
        == ["bundle", "system"]
    heard = page.evaluate("window.ninetySpokenAloud")
    assert heard == ["https://phone.test/bundle/speech/a.mp3", "Not in it."]
    page.evaluate("window.rate = 3")  # outside the phone's 0.8 to 1.6: held to it
    page.evaluate("() => make('p').say('Home lead.')")
    assert page.evaluate("rates") == [1.6]


def test_without_the_passcode_a_line_missing_from_the_bundle_never_reaches_the_api(phone_voice):
    page, calls = open_phone(phone_voice, {})
    assert page.evaluate("() => make(null).say('Home lead.')") == "system"
    assert calls == [] and page.evaluate("system") == ["Home lead."]


def test_in_live_mode_an_answer_is_spoken_by_the_api_and_the_device_only_if_it_fails(phone_voice):
    page, calls = open_phone(phone_voice, {})
    assert page.evaluate("() => make('p').say('Home 9 ran 9.8 km.')") == "api"
    assert calls == [("p", {"text": "Home 9 ran 9.8 km."})]
    assert page.evaluate("played")[0].startswith("blob:") and page.evaluate("system") == []
    down, _ = open_phone(phone_voice, {}, speak_status=503)
    assert down.evaluate("() => make('p').say('Home 9 ran 9.8 km.')") == "system"


def test_the_device_voice_is_the_last_resort_in_voice_ts():
    """speechSynthesis appears once, in the fallback, never as the first choice (lesson 232)."""
    source = (PHONE / "src" / "voice.ts").read_text()
    assert source.count("speechSynthesis.speak(") == 1
    assert source.index("player.play(new URL(hit.file") < source.index("system(line)")


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
