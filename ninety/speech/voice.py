"""The one voice a fan hears, pinned here, and the SSML every read-aloud line is sent as.

en-GB-OllieMultilingualNeural was chosen by ear on Oct 23 from samples of all 17 British neural voices and
two HD voices on our Speech resource (lesson 232): chosen by ear, never the browser's system voice,
which the phone uses only when it is offline. Every path that speaks to a fan reads `VOICE`: the
bundle's pre-generated audio (ninety/speech/bundle.py), the Live route (ninety/api/speak.py) and the
Describer's track (ninety/speech/describe.py).

Lines are keyed by `key(text)`: the SHA-256 of the text with its whitespace collapsed, the same key
web/phone/src/voice.ts computes, so the phone finds a line's audio by the text it is about to say.
"""

from __future__ import annotations

import hashlib
from xml.sax.saxutils import escape

VOICE = "en-GB-OllieMultilingualNeural"
LANG = "en-GB"
# The MP3 every read-aloud line is made in: 24 kHz mono at 48 kbit/s, about 6 KB a second of speech.
FORMAT = "audio-24khz-48kbitrate-mono-mp3"
# A livelier rate for insight cards only (audio description stays at the voice's own rate). None
# until it has been heard to sound natural in this voice; then "+5%".
INSIGHT_RATE: str | None = None
# Quotes too: an escaped quote can never close an attribute, wherever the builder puts the text.
QUOTES = {'"': "&quot;", "'": "&apos;"}


def normalise(text: str) -> str:
    """The text as it is keyed and spoken: runs of whitespace as one space, none at either end."""
    return " ".join(text.split())


def key(text: str) -> str:
    return hashlib.sha256(normalise(text).encode()).hexdigest()


def ssml(text: str, rate: str | None = None, voice: str = VOICE) -> str:
    body = escape(normalise(text), QUOTES)
    if rate:
        body = f'<prosody rate="{rate}">{body}</prosody>'
    return (
        f'<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" xml:lang="{LANG}">'
        f'<voice name="{voice}">{body}</voice></speak>'
    )
