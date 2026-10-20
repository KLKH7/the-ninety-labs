"""Spanish through Azure Translator, behind a flag: facts are protected, failures fail closed."""

import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest

from ninety.agents.contracts import Profile, Variant
from ninety.agents.factcheck import Claim
from ninety.personalizer import translate
from ninety.personalizer.translate import TranslationUnavailable

LINE = "h7 finds h9 at 01:28, 38 km/h, for home."


def test_facts_are_marked_notranslate_and_come_back_unchanged():
    html = translate.protect(LINE + " <b>&")
    for fact in ("h7", "h9", "01:28", "38", "home"):
        assert f'<span class="notranslate">{fact}</span>' in html
    assert "<b>" not in html and "&lt;b&gt;" in html
    assert translate.unprotect(html) == LINE + " <b>&"


class Credential:
    async def get_token(self, scope):
        assert scope == translate.SCOPE
        return SimpleNamespace(token="tok")


def test_azure_sends_protected_html_with_an_entra_token():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["request"] = request
        sent = json.loads(request.content)[0]["Text"]
        spanish = sent.replace(" finds ", " encuentra a ").replace(" for ", " para ")
        return httpx.Response(200, json=[{"translations": [{"text": spanish, "to": "es"}]}])

    fn = translate.azure("https://tr.example/", "westeurope", Credential(), httpx.MockTransport(handler))
    assert asyncio.run(fn(LINE, "es")) == "h7 encuentra a h9 at 01:28, 38 km/h, para home."
    request = seen["request"]
    assert request.url.path == "/translator/text/v3.0/translate"
    assert dict(request.url.params) == {"api-version": "3.0", "from": "en", "to": "es", "textType": "html"}
    assert request.headers["Authorization"] == "Bearer tok"
    assert request.headers["Ocp-Apim-Subscription-Region"] == "westeurope"


@pytest.mark.parametrize("reply", [httpx.Response(429), httpx.Response(200, json={"unexpected": True})])
def test_a_service_failure_is_translation_unavailable(reply):
    fn = translate.azure("https://tr.example", None, Credential(), httpx.MockTransport(lambda r: reply))
    with pytest.raises(TranslationUnavailable):
        asyncio.run(fn(LINE, "es"))


def test_recorded_answers_are_exact_or_unavailable(tmp_path):
    path = tmp_path / "es.json"
    path.write_text(json.dumps({"es": {LINE: "h7 encuentra a h9."}}))
    fn = translate.recorded(path)
    assert asyncio.run(fn(LINE, "es")) == "h7 encuentra a h9."
    with pytest.raises(TranslationUnavailable):
        asyncio.run(fn(LINE + " ", "es"))


def test_the_flag_is_off_by_default(tmp_path):
    path = tmp_path / "es.json"
    path.write_text("{}")
    assert translate.from_env({}) is None
    assert translate.from_env({translate.FLAG: "off"}) is None
    assert translate.from_env({translate.FLAG: "mock"}) is translate.mock
    assert callable(translate.from_env({translate.FLAG: f"recorded:{path}"}))
    with pytest.raises(ValueError, match=translate.ENDPOINT):
        translate.from_env({translate.FLAG: "azure"})
    with pytest.raises(ValueError):
        translate.from_env({translate.FLAG: "google"})


def test_the_mock_is_marked_as_not_a_translation():
    assert asyncio.run(translate.mock(LINE, "es")) == translate.MOCK_PREFIX + LINE


# --- translated: the English variant of the same persona, translated, then re-checked ----------

EVIDENCE = [{"id": "e1", "type": "pass", "team": "home", "player": "h4", "receiver": "h9",
             "outcome": "success", "distance_m": 32, "minute": 2, "clock": "01:10"}]
CLAIM = Claim("h4 finds h9 over 32 m at 01:10.", ["e1"])


async def _lowercase_writer(claim, evidence, profiles):
    return [Variant(p.persona, p.lang, claim.text.replace("finds", "picks out"), tuple(claim.evidence))
            for p in profiles]


def _profiles():
    return [Profile("casual", "en"), Profile("casual", "es"), Profile("club", "es", club="home")]


def test_spanish_is_the_english_variant_translated():
    seen = []

    async def spanish(text, lang):
        seen.append((text, lang))
        return text.replace("picks out", "encuentra a").replace("over", "a")

    variants = asyncio.run(translate.translated(_lowercase_writer, spanish)(CLAIM, EVIDENCE, _profiles()))
    assert [(v.persona, v.lang, v.text) for v in variants] == [
        ("casual", "en", "h4 picks out h9 over 32 m at 01:10."),
        ("casual", "es", "h4 encuentra a h9 a 32 m at 01:10."),
        ("club", "es", "h4 encuentra a h9 a 32 m at 01:10."),
    ]
    assert seen == [("h4 picks out h9 over 32 m at 01:10.", "es")] * 2


def test_the_writer_only_ever_sees_english_profiles():
    asked = []

    async def writer(claim, evidence, profiles):
        asked.extend(p.lang for p in profiles)
        return [Variant(p.persona, p.lang, claim.text, tuple(claim.evidence)) for p in profiles]

    asyncio.run(translate.translated(writer, translate.mock)(CLAIM, EVIDENCE, _profiles()))
    assert set(asked) == {"en"}


@pytest.mark.parametrize(("spanish", "why"), [
    (lambda t, lang: t.replace("32", "23"), "23"),
    (lambda t, lang: t.replace("01:10", "10:01"), "10:01"),
    (lambda t, lang: (_ for _ in ()).throw(TranslationUnavailable("down")), "translator: down"),
], ids=["number", "clock", "down"])
def test_a_translation_that_fails_or_loses_a_fact_gets_the_verified_text(spanish, why):
    async def fn(text, lang):
        return spanish(text, lang)

    run = translate.translated(_lowercase_writer, fn)
    variants, dropped = asyncio.run(run.explained(CLAIM, EVIDENCE, _profiles()))
    assert [v.text for v in variants[1:]] == [CLAIM.text, CLAIM.text]
    assert set(dropped) == {1, 2} and all(why in d for d in dropped.values())
    assert variants[0].text == "h4 picks out h9 over 32 m at 01:10." and 0 not in dropped


def test_an_english_drop_is_reported_and_a_spanish_one_is_not_blamed_on_the_writer():
    async def explained(claim, evidence, profiles):
        return ([Variant(p.persona, p.lang, claim.text, tuple(claim.evidence)) for p in profiles],
                {i: "writer: bad" for i in range(len(profiles))})

    async def writer(claim, evidence, profiles):
        return (await explained(claim, evidence, profiles))[0]

    writer.explained = explained
    run = translate.translated(writer, translate.mock)
    _, dropped = asyncio.run(run.explained(CLAIM, EVIDENCE, _profiles()))
    assert dropped == {0: "writer: bad"}
