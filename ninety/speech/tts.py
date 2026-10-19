"""Text to speech through the Azure AI Speech REST API with Entra auth (no key, no SDK:
the Speech SDK's licence is proprietary, and this project uses permissive licences only)."""

from __future__ import annotations

import asyncio
import time
from xml.sax.saxutils import escape

import httpx
from azure.identity import DefaultAzureCredential

from ninety import config

_credential = DefaultAzureCredential()

VOICE = "en-GB-RyanNeural"
LANG = "en-GB"
# Quotes too: the text is character data today, but an escaped quote can never close an attribute.
_ENTITIES = {'"': "&quot;", "'": "&apos;"}


def ssml(text: str, voice: str = VOICE, lang: str = LANG) -> str:
    """One spoken line as SSML. The text is escaped (&, <, > and both quotes), so nothing in it
    can become markup: an event's or a model's words are always read out, never obeyed."""
    return (
        f'<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" xml:lang="{lang}">'
        f'<voice name="{voice}">{escape(text, _ENTITIES)}</voice></speak>'
    )


def synthesize_ssml(document: str) -> tuple[bytes, float]:
    """Returns MP3 bytes for an SSML document and the seconds the request took."""
    if not config.SPEECH_RESOURCE_ID:
        raise RuntimeError("set NINETY_SPEECH_RESOURCE_ID (see ninety/config.py)")
    token = _credential.get_token("https://cognitiveservices.azure.com/.default").token
    started = time.perf_counter()
    response = httpx.post(
        f"https://{config.SPEECH_REGION}.tts.speech.microsoft.com/cognitiveservices/v1",
        headers={
            "Authorization": f"Bearer aad#{config.SPEECH_RESOURCE_ID}#{token}",
            "Content-Type": "application/ssml+xml",
            "X-Microsoft-OutputFormat": "audio-24khz-48kbitrate-mono-mp3",
            "User-Agent": "the-ninety-labs",
        },
        content=document.encode(),
        timeout=20,
    )
    response.raise_for_status()
    return response.content, time.perf_counter() - started


def synthesize(text: str, voice: str = VOICE) -> tuple[bytes, float]:
    """Returns MP3 bytes and the seconds the request took."""
    return synthesize_ssml(ssml(text, voice))


async def speak(document: str) -> bytes:
    """The `Speak` contract (ninety/agents/contracts.py): SSML in, MP3 out, off the event loop."""
    audio, _ = await asyncio.to_thread(synthesize_ssml, document)
    return audio
