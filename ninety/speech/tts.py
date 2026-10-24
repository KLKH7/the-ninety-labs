"""Text to speech through the Azure AI Speech REST API with Entra auth (no key, no SDK:
the Speech SDK's licence is proprietary, and this project uses permissive licences only)."""

from __future__ import annotations

import time
from xml.sax.saxutils import escape

import httpx
from azure.identity import DefaultAzureCredential

from ninety import config
from ninety.speech.voice import FORMAT, VOICE

SCOPE = "https://cognitiveservices.azure.com/.default"
_credential = DefaultAzureCredential()


def synthesize(text: str, voice: str = VOICE) -> tuple[bytes, float]:
    """Returns MP3 bytes and the seconds the request took."""
    # Quotes too (as ninety/speech/describe.py): an escaped quote can never close an attribute.
    body = escape(text, {'"': "&quot;", "'": "&apos;"})
    ssml = f'<speak version="1.0" xml:lang="en-GB"><voice name="{voice}">{body}</voice></speak>'
    return synthesize_ssml(ssml)


def _request(token: str, output_format: str) -> tuple[str, dict]:
    url = f"https://{config.SPEECH_REGION}.tts.speech.microsoft.com/cognitiveservices/v1"
    return url, {
        "Authorization": f"Bearer aad#{config.SPEECH_RESOURCE_ID}#{token}",
        "Content-Type": "application/ssml+xml",
        "X-Microsoft-OutputFormat": output_format,
        "User-Agent": "the-ninety-labs",
    }


def synthesize_ssml(ssml: str, output_format: str = FORMAT) -> tuple[bytes, float]:
    """Audio for an SSML document (ninety/speech/describe.py writes them), and the seconds the
    request took."""
    if not config.SPEECH_RESOURCE_ID:
        raise RuntimeError("set NINETY_SPEECH_RESOURCE_ID (see ninety/config.py)")
    url, headers = _request(_credential.get_token(SCOPE).token, output_format)
    started = time.perf_counter()
    response = httpx.post(url, headers=headers, content=ssml.encode(), timeout=20)
    response.raise_for_status()
    return response.content, time.perf_counter() - started


async def asynthesize_ssml(ssml: str, credential, client: httpx.AsyncClient,
                           output_format: str = FORMAT) -> tuple[bytes, float]:
    """The same request from inside an event loop (the API): an aio credential
    (ninety/agents/credentials.py) and an async client, so a synthesis never blocks other requests."""
    if not config.SPEECH_RESOURCE_ID:
        raise RuntimeError("set NINETY_SPEECH_RESOURCE_ID (see ninety/config.py)")
    token = (await credential.get_token(SCOPE)).token
    url, headers = _request(token, output_format)
    started = time.perf_counter()
    response = await client.post(url, headers=headers, content=ssml.encode(), timeout=20)
    response.raise_for_status()
    return response.content, time.perf_counter() - started
