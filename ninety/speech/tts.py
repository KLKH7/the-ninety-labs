"""Text to speech through the Azure AI Speech REST API with Entra auth (no key, no SDK:
the Speech SDK's licence is proprietary, and this project uses permissive licences only)."""

from __future__ import annotations

import time
from xml.sax.saxutils import escape

import httpx
from azure.identity import DefaultAzureCredential

from ninety import config

_credential = DefaultAzureCredential()


def synthesize(text: str, voice: str = "en-GB-RyanNeural") -> tuple[bytes, float]:
    """Returns MP3 bytes and the seconds the request took."""
    ssml = f'<speak version="1.0" xml:lang="en-GB"><voice name="{voice}">{escape(text)}</voice></speak>'
    return synthesize_ssml(ssml)


def synthesize_ssml(ssml: str, output_format: str = "audio-24khz-48kbitrate-mono-mp3") -> tuple[bytes, float]:
    """Audio for an SSML document (ninety/speech/describe.py writes them), and the seconds the
    request took."""
    if not config.SPEECH_RESOURCE_ID:
        raise RuntimeError("set NINETY_SPEECH_RESOURCE_ID (see ninety/config.py)")
    token = _credential.get_token("https://cognitiveservices.azure.com/.default").token
    started = time.perf_counter()
    response = httpx.post(
        f"https://{config.SPEECH_REGION}.tts.speech.microsoft.com/cognitiveservices/v1",
        headers={
            "Authorization": f"Bearer aad#{config.SPEECH_RESOURCE_ID}#{token}",
            "Content-Type": "application/ssml+xml",
            "X-Microsoft-OutputFormat": output_format,
            "User-Agent": "the-ninety-labs",
        },
        content=ssml.encode(),
        timeout=20,
    )
    response.raise_for_status()
    return response.content, time.perf_counter() - started
