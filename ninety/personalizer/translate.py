"""The second language through Azure Translator, behind a flag (docs/PLAN.md: "two languages via
Translator"). With the flag off, the Personalizer's model writes Spanish itself (core.INSTRUCTIONS).

    NINETY_TRANSLATOR=off               no Spanish (the default)
    NINETY_TRANSLATOR=mock              a marked fake for tests and offline runs: "[es] <the English>"
    NINETY_TRANSLATOR=recorded:<path>   answers recorded from Azure Translator, looked up exactly
    NINETY_TRANSLATOR=azure             the live service: NINETY_TRANSLATOR_ENDPOINT (the resource's
                                        custom domain), signed in with the managed identity

A translator never decides what is true. `translated` translates the English variant the
Personalizer wrote for the same persona; the facts in it (player ids, numbers, clocks, teams) are
sent marked `notranslate`, so the service carries them across untouched, and the Spanish line then
goes through the same re-check as any variant (core.recheck). A translation that fails, or that
loses a fact, gets the verified English text, which the live path does not air as Spanish.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Awaitable, Callable
from html import escape, unescape
from pathlib import Path

import httpx

from ninety.agents.contracts import Personalize, Profile, Variant
from ninety.agents.factcheck import CLOCK, NUMBER, PLAYER, Claim
from ninety.personalizer.core import SOURCE_LANG, TEAM, recheck

Translate = Callable[[str, str], Awaitable[str]]  # (English text, target lang) -> translated text

FLAG = "NINETY_TRANSLATOR"
ENDPOINT = "NINETY_TRANSLATOR_ENDPOINT"
REGION = "NINETY_TRANSLATOR_REGION"
SCOPE = "https://cognitiveservices.azure.com/.default"  # Entra ID scope for Azure AI services
API_VERSION = "3.0"
TIMEOUT_SECONDS = 5.0  # design: a translation later than this misses the insight's 5 s on screen
MOCK_PREFIX = "[es] "
# The tokens that carry facts.
FACT = re.compile("|".join(f"(?:{p.pattern})" for p in (CLOCK, NUMBER, PLAYER, TEAM)))
NO_TRANSLATE = re.compile(r'<span class="notranslate">(.*?)</span>', re.S)


class TranslationUnavailable(RuntimeError):
    """No translation could be made: the service failed, or a recording has no answer for it."""


def protect(text: str) -> str:
    """The text as HTML with each fact token wrapped so the translator leaves it alone."""
    out, last = [], 0
    for match in FACT.finditer(text):
        out.append(escape(text[last:match.start()]))
        out.append(f'<span class="notranslate">{escape(match.group())}</span>')
        last = match.end()
    out.append(escape(text[last:]))
    return "".join(out)


def unprotect(html: str) -> str:
    return unescape(NO_TRANSLATE.sub(lambda m: m.group(1), html))


async def mock(text: str, lang: str) -> str:
    """Not a translation: the English, marked, so a test or an offline run shows where Spanish goes."""
    return MOCK_PREFIX + text


def recorded(path: str | Path) -> Translate:
    """Answers recorded from the live service: {"es": {"<English>": "<Spanish>", ...}}."""
    table = json.loads(Path(path).read_text())

    async def translate(text: str, lang: str) -> str:
        try:
            return table[lang][text]
        except KeyError:
            raise TranslationUnavailable(f"no recorded {lang} translation for {text!r}") from None

    return translate


def azure(
    endpoint: str,
    region: str | None = None,
    credential=None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> Translate:
    """Azure Translator, v3 `translate`, called with an Entra ID token: no key in the repo or the image."""
    if credential is None:
        from azure.identity.aio import DefaultAzureCredential

        credential = DefaultAzureCredential()
    url = endpoint.rstrip("/") + "/translator/text/v3.0/translate"

    async def translate(text: str, lang: str) -> str:
        try:
            token = await credential.get_token(SCOPE)
            headers = {"Authorization": f"Bearer {token.token}"}
            if region:
                headers["Ocp-Apim-Subscription-Region"] = region
            async with httpx.AsyncClient(transport=transport, timeout=TIMEOUT_SECONDS) as client:
                response = await client.post(
                    url,
                    params={"api-version": API_VERSION, "from": "en", "to": lang, "textType": "html"},
                    headers=headers,
                    json=[{"Text": protect(text)}],
                )
                response.raise_for_status()
                return unprotect(response.json()[0]["translations"][0]["text"])
        except Exception as error:  # the service, sign-in, network or an unexpected reply
            raise TranslationUnavailable(f"Azure Translator: {type(error).__name__}") from error

    return translate


def from_env(env: dict[str, str] | None = None) -> Translate | None:
    """The translator the flag asks for, or None when Spanish is off."""
    env = dict(os.environ) if env is None else env
    flag = env.get(FLAG, "off")
    if flag == "off":
        return None
    if flag == "mock":
        return mock
    if flag.startswith("recorded:"):
        return recorded(flag.removeprefix("recorded:"))
    if flag == "azure":
        if not env.get(ENDPOINT):
            raise ValueError(f"{FLAG}=azure needs {ENDPOINT}")
        return azure(env[ENDPOINT], env.get(REGION))
    raise ValueError(f"unknown {FLAG} value {flag!r}: off, mock, recorded:<path> or azure")


def translated(personalize: Personalize, translate: Translate) -> Personalize:
    """`personalize` for the English profiles; every other language is the English variant of the
    same persona, club and player through `translate`, then re-checked. Keeps `.explained`, so the
    server still reports why a variant was dropped."""

    async def explained(
        claim: Claim, evidence: list[dict], profiles: list[Profile]
    ) -> tuple[list[Variant], dict[int, str]]:
        english = [Profile(p.persona, SOURCE_LANG, p.club, p.player) for p in profiles]
        inner = getattr(personalize, "explained", None)
        if inner is not None:
            written, dropped = await inner(claim, evidence, english)
        else:
            written, dropped = await personalize(claim, evidence, english), {}
        texts, why = {}, {i: d for i, d in dropped.items() if profiles[i].lang == SOURCE_LANG}
        for i, (profile, variant) in enumerate(zip(profiles, written, strict=True)):
            if profile.lang == SOURCE_LANG:
                texts[i] = variant.text
                continue
            try:
                texts[i] = await translate(variant.text, profile.lang)
            except TranslationUnavailable as error:
                why[i] = f"translator: {error}"
        variants, failed = recheck(claim, evidence, profiles, texts)
        return variants, {**why, **{i: d for i, d in failed.items() if i not in why}}

    async def run(claim: Claim, evidence: list[dict], profiles: list[Profile]) -> list[Variant]:
        return (await explained(claim, evidence, profiles))[0]

    run.explained = explained
    return run
