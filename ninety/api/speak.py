"""Live read-aloud: an Ask answer spoken in the pinned voice (ninety/speech/voice.py).

    POST /api/live/speak   {"text": "..."} or {"text": "...", "answer": "..."} -> audio/mpeg

Mounted under /api/live, so it needs the demo passcode (ninety/api/app.py): Replay mode never calls
Speech. The bundle's lines are pre-generated (ninety/speech/bundle.py); this route is for what only
exists live, an answer to a fan's question.

It speaks only text this process has just answered with (`Companion.answered`): a fan's own words,
or anything else posted to it, are never sent to Speech, so the route cannot be used as a free
voice for arbitrary text. The phone says an answer with its player ids named ("a-t4" as "Oakfield
player 4", web/viewer/src/teams.ts nameIds), so it may send that text with the `answer` it was
made from: the answer must be one given, and the text must be it with each id replaced by a short
name (`named_from`), and nothing else changed. Each IP is rate-limited, and a day's characters are
capped (`DAY_CHARS`); an answer said twice is served from memory. Signs in as the Container App's
managed identity through the shared aio credential (ninety/agents/credentials.py), never a key.
Any Speech failure (sign-in, an outage, the free tier's 20 requests a minute) is a 503, and the
phone falls back to the device's voice for that line.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from ninety.api.companion import RateLimit, TooLarge, _read_body, client_ip
from ninety.speech import voice

log = logging.getLogger(__name__)

MAX_TEXT = 600  # design: an answer is one or two sentences; a card's longest spoken form is ~300
MAX_BODY_BYTES = 4096  # MAX_TEXT characters as JSON escapes, with room
PER_MINUTE = 20  # design: a person tapping play; also the F0 resource's own 20 requests a minute
# design: at S1's $15 per million characters (ninety/speech/bundle.py, USD_PER_CHAR) a day of
# 50,000 characters costs at most $0.75; about 500 answers.
DAY_CHARS = 50_000
CACHED = 256  # design: answers kept in memory, so a replayed answer is not paid for twice

# A player id as web/viewer/src/teams.ts nameIds finds one, and what it may be said as: a short name
# ("Oakfield player 4", "Home 9"). Design: at most four words of 20 characters, no punctuation but
# apostrophes and hyphens, more than any club, role and number we draw; so a name slot cannot carry
# a sentence of its own.
PLAYER_ID = re.compile(r"\b[ha](?:-t\d+|[1-9]|1[01])\b")
NAME = r"[A-Za-z][A-Za-z0-9'-]{0,19}(?: [A-Za-z0-9'-]{1,20}){0,3}"


def named_from(text: str, answer: str) -> bool:
    """Whether `text` is `answer` with each player id in it replaced by a short name."""
    parts = PLAYER_ID.split(answer)
    if len(parts) == 1:
        return text == answer
    pattern = NAME.join(re.escape(p) for p in parts)
    return re.fullmatch(pattern, text) is not None


Synth = Callable[[str], Awaitable[tuple[bytes, float]]]  # SSML -> (MP3, seconds the request took)


class Speaker:
    def __init__(self, answered: Callable[[str], bool], synth: Synth | None = None,
                 clock: Callable[[], float] = time.time):
        self.answered = answered
        self.synth = synth
        self.clock = clock
        self.limit = RateLimit(PER_MINUTE)
        self.day, self.spent = -1, 0
        self.cache: OrderedDict[str, bytes] = OrderedDict()
        self.lock = asyncio.Lock()
        self.timings: list[float] = []  # seconds per synthesis, for the latency report

    def _take(self, chars: int) -> bool:
        day = int(self.clock() // 86_400)
        if day != self.day:
            self.day, self.spent = day, 0
        if self.spent + chars > DAY_CHARS:
            return False
        self.spent += chars
        return True

    async def _synth(self) -> Synth:
        async with self.lock:  # two first requests must not build two clients
            if self.synth is None:
                import httpx

                from ninety.agents import credentials
                from ninety.speech import tts

                credential, client = credentials.new_credential(), httpx.AsyncClient()

                async def synth(document: str) -> tuple[bytes, float]:
                    return await tts.asynthesize_ssml(document, credential, client)

                self.synth = synth
            return self.synth

    async def speak(self, request: Request) -> Response:
        if not self.limit.allow(client_ip(request)):
            return JSONResponse({"error": "too many requests; wait a minute"}, status_code=429)
        try:
            body = json.loads(await _read_body(request, MAX_BODY_BYTES))
            fields = isinstance(body, dict) and set(body) in ({"text"}, {"text", "answer"})
            text = body["text"] if fields else None
            given = body.get("answer", text) if fields else None
        except TooLarge as exc:
            return JSONResponse({"error": str(exc)}, status_code=413)
        except json.JSONDecodeError:
            text = given = None
        if (not isinstance(text, str) or not isinstance(given, str) or not voice.normalise(text)
                or len(text) > MAX_TEXT):
            return JSONResponse({"error": f'send {{"text": ...}}, at most {MAX_TEXT} characters'},
                                status_code=422)
        text, given = voice.normalise(text), voice.normalise(given)
        k = voice.key(text)
        if not self.answered(voice.key(given)) or not named_from(text, given):
            return JSONResponse({"error": "only an answer this server gave can be spoken"}, status_code=403)
        audio = self.cache.get(k)
        if audio is None:
            if not self._take(len(text)):
                return JSONResponse({"error": "today's speech budget is spent"}, status_code=429)
            try:
                audio, seconds = await (await self._synth())(voice.ssml(text))
            except Exception as exc:  # noqa: BLE001  any Speech failure: the phone says it itself
                log.warning("speech failed: %s", type(exc).__name__)  # the type only: no token
                return JSONResponse({"error": "the voice is unavailable"}, status_code=503)
            self.timings.append(seconds)
            self.cache[k] = audio
            while len(self.cache) > CACHED:
                self.cache.popitem(last=False)
        else:
            self.cache.move_to_end(k)
        return Response(audio, media_type="audio/mpeg")
