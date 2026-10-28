"""The phone companion's routes: pairing, the relay, the minimap, player cards and questions.

    POST /api/pair                     {"clip": "seed7"} -> a 6-character code, valid for 2 hours
                                       ("code": its old code re-claims it after a restart, if free)
    GET  /api/pair/{code}              {clip, expires_in}, for a phone given only the typed code
    WS   /api/pair/{code}?role=laptop  the laptop sends clock and focus messages
    WS   /api/pair/{code}?role=phone   each phone receives them, the latest first; a refused join
                                       is accepted, then closed with its code (4400, 4404, 4409,
                                       4429), so a browser can read why
    GET  /api/minimap/{clip}?fps=5     downsampled positions (schemas/minimap.schema.json)
    GET  /api/card/{clip}/{player}?t_to=95.2[&t_from=0]   a player_card message
    GET  /api/flow/{clip}/{team}?t_to=95.2[&t_from=0]     a flow message (the wind map)
    POST /api/ask                      a viewer_question -> an answer message

Every message to the phone validates against schemas/companion_message.schema.json, and every
request body against its schema, so an unknown field is a 422. The pairing code is the viewer's
session id (`Question.session`): it names the clip, and the per-session rate limit and model
budget count against it.

Replay and Live (SECURITY.md): /api/ask answers in code unless the request carries the demo
passcode in `x-ninety-passcode`. With it, the Companion agent drafts and the fact-checking agent
gates the answer (ninety/agents/companion.py), within a per-session and per-day budget of model
calls; once a budget is spent, code answers. A match question's answer is one of code's own checked
sentences, so it is gated by the code check alone: the Judge runs where the model writes its own
words, a player question (docs/eval/ask-model-path.md). Each model step has its own time budget
(companion.STEP_S), a question is answered no later than the big screen's playhead, and every
question leaves one trace record (ninety/agents/telemetry.py: no viewer text, only its length and
a hash). Live needs NINETY_DEMO_PASSCODE (a Key Vault
reference in Azure); without it a passcode is refused, so Live fails closed.

Rooms, rate limits and budgets live in this process's memory: the API runs as one Container App
replica (infra/main.bicep), so a phone and its laptop always reach the same rooms. More replicas
would need a shared store (or session affinity) first. A restart forgets every room, and the
laptop pairs again.

Which mode runs is NINETY_COMPANION (`from_env`). Unset or `on`, the deployed configuration: the
routes are mounted and serve only tracked positions (the M1 clip, seed900001, from its tracked
frames file, ninety/match/tracking.py), and a clip whose positions are ground truth gets a 503, so
nothing on the live path reads the answer key (AGENTS.md). `standin` also serves the simulator's
matches, labelled `source: truth` in every message, for building the phone locally. `off` mounts
nothing.
"""

from __future__ import annotations

import asyncio
import dataclasses
import hmac
import json
import logging
import os
import secrets
import time
from collections import OrderedDict, defaultdict, deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from jsonschema import Draft202012Validator, ValidationError
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route, WebSocketRoute
from starlette.websockets import WebSocket, WebSocketDisconnect, WebSocketState

from ninety.agents import companion, companion_match, telemetry
from ninety.agents.contracts import Answer, Ask, Judge, Question, schema_validator
from ninety.intel.window import player_window, team_flow
from ninety.match import tracking
from ninety.mcp import match_server
from ninety.speech import voice

log = logging.getLogger(__name__)

CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"  # no 0/O, 1/I/L: read off a laptop screen
CODE_LENGTH = 6
PAIR_TTL_S = 2 * 60 * 60  # design: longer than a match's broadcast with half-time, then pair again
MAX_ROOMS = 500  # design: bounds memory; the demo needs a handful
MAX_PHONES = 8  # design: a family's phones round one laptop; bounds what one code can fan out
MAX_MESSAGE_BYTES = 1024  # design: a clock or focus message is under 60 bytes
# design: a question is at most 200 characters, which JSON writes in at most 1,200 bytes (\u
# escapes), plus its other fields; anything larger is refused before it is read.
MAX_BODY_BYTES = 2048
RELAYED = {"clock", "focus"}  # what a laptop may send; answers and cards come from the server
FPS_CHOICES = (1, 5, 25)  # divisors of the engine's 25 fps, so frames are evenly spaced
MINIMAP_PLACES = 1  # 0.1 m: finer than a phone's dot, coarser than the tracker's error
PASSCODE_HEADER = "x-ninety-passcode"
# design: how far past the room's playhead a question's match time may be. The laptop sends its clock
# at least once a second (web/viewer/src/companion.ts, EVERY_MS) and the phone runs it on between
# messages, so an honest phone leads the server's estimate by at most that second plus the relay's
# latency; past that the question is about footage the big screen has not shown (a spoiler).
PLAYHEAD_SLACK_S = 2.0
MODES = ("on", "standin", "off")  # NINETY_COMPANION; unset means `on`
# Every clip the companion knows: the simulator stand-ins (served only in `standin`) and the clips
# served from tracked positions.
CLIPS = (*sorted(match_server.MATCHES), *tracking.TRACKED_CLIPS)
# Requests a client may make in a minute (design: a person tapping, never a script).
LIMITS = {"pair": 6, "join": 30, "read": 120, "ask_ip": 20, "ask_session": 10, "relay": 600}
MAX_SPOKEN = 2_000  # design: answers remembered for read-aloud; minutes of a busy demo
SWEEP_KEYS = 10_000  # design: rate-limit keys kept before idle ones are swept
# design: 20 Live answers a viewer, 400 a day. A Live answer (the Companion's draft and the Judge)
# is about 1,400 tokens in and 100 out (our instructions and prompts at 4 characters a token, as
# docs/eval/latency-cost.md counts them), so at gpt-4.1-mini's $0.0004 and $0.0016 per 1,000
# (Azure Retail Prices, read 2026-10-19, in that report) a day's 400 cost at most about $0.29.
SESSION_MODEL_CALLS, DAY_MODEL_CALLS = 20, 400

MESSAGE = schema_validator("companion_message")
QUESTION = schema_validator("viewer_question")
MINIMAP = schema_validator("minimap")
PAIR_BODY = Draft202012Validator(
    {
        "type": "object",
        "additionalProperties": False,
        "required": ["clip"],
        "properties": {
            "clip": {"type": "string", "enum": list(CLIPS)},
            # A screen re-claiming the code it showed, after this server restarted (rooms live in
            # memory) or its own connection dropped, so the phones on it rejoin without a rescan.
            "code": {"type": "string", "pattern": f"^[{CODE_ALPHABET}]{{{CODE_LENGTH}}}$"},
        },
    }
)


class RateLimit:
    """At most `limit` hits per key in any `window` seconds (a sliding log)."""

    def __init__(self, limit: int, window: float = 60.0, clock: Callable[[], float] = time.monotonic):
        self.limit, self.window, self.clock = limit, window, clock
        self.hits: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str) -> bool:
        now = self.clock()
        if len(self.hits) > SWEEP_KEYS:  # drop keys idle for a whole window, so memory stays bounded
            for stale in [k for k, h in self.hits.items() if not h or h[-1] <= now - self.window]:
                del self.hits[stale]
        hits = self.hits[key]
        while hits and hits[0] <= now - self.window:
            hits.popleft()
        if len(hits) >= self.limit:
            return False
        hits.append(now)
        return True


class Budget:
    """Model calls left for a session and for the day (UTC). When either is spent, code answers."""

    def __init__(self, per_session: int, per_day: int, clock: Callable[[], float] = time.time):
        self.per_session, self.per_day, self.clock = per_session, per_day, clock
        self.sessions: dict[str, int] = defaultdict(int)
        self.day, self.today = -1, 0

    def take(self, session: str) -> bool:
        day = int(self.clock() // 86400)
        if day != self.day:
            self.day, self.today = day, 0
        if self.sessions[session] >= self.per_session or self.today >= self.per_day:
            return False
        self.sessions[session] += 1
        self.today += 1
        return True


@dataclass
class Outbox:
    """What one phone still has to be sent, in order. One flusher at a time sends from it, so a
    phone sees its catch-up and the laptop's later messages in the order they were stored, never a
    newer clock overtaken by an older one."""

    ws: WebSocket
    items: deque[dict] = field(default_factory=deque)
    flushing: bool = False


@dataclass
class Room:
    """One pairing. The API runs on one event loop (one uvicorn worker, one replica), so the steps
    between awaits run whole: claiming the laptop slot, a phone joining (outbox filled with the
    latest state, then registered), and a message being stored and queued for every phone."""

    code: str
    clip: str
    expires: float
    laptop: WebSocket | None = None
    phones: dict[WebSocket, Outbox] = field(default_factory=dict)
    latest: dict[str, dict] = field(default_factory=dict)  # last clock and focus, for late phones
    stored_at: dict[str, float] = field(default_factory=dict)  # when each was stored (Companion.clock)
    sending: set[asyncio.Task] = field(default_factory=set)  # flushes in flight, kept until done
    # The match conversation: each phone question and its answer, so a follow-up has its context
    # (ninety/agents/companion_match.py). Capped; it lives and dies with the pairing.
    turns: list[dict] = field(default_factory=list)


@dataclass
class LiveModels:
    """The Companion and the Judge on Foundry, for Live mode. Built on first use."""

    ask: Ask
    judge: Judge
    match_ask: Ask | None = None  # the match Companion (ninety-companion-match), for match questions
    referee_ask: Ask | None = None  # the Referee (ninety-referee), handed rules questions


def client_ip(request: Request | WebSocket) -> str:
    """The caller's address. Container Apps' ingress appends the address it saw to X-Forwarded-For,
    so the last entry is the one a client cannot forge; without the header, the socket's peer."""
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[-1].strip()
    return request.client.host if request.client else "unknown"


def _error(status: int, message: str) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=status)


def _send(message: dict) -> dict:
    """Every message to the phone passes the schema first, or is never sent."""
    MESSAGE.validate(message)
    return message


async def _refuse(ws: WebSocket, code: int) -> None:
    """Refuse a join with a close code the phone can read. A close sent before the accept never
    reaches a browser (it sees 1006), so the socket is accepted first; no slot has been taken."""
    await ws.accept()
    await ws.close(code=code)


class TooLarge(ValueError):
    """A request body over MAX_BODY_BYTES."""


async def _read_body(request: Request, cap: int = MAX_BODY_BYTES) -> bytes:
    """The body, read only as far as the cap: a declared length over it is refused unread, and a
    stream that runs past it (chunked, or a length that lies) is cut off there."""
    declared = request.headers.get("content-length")
    if declared is not None and (not declared.isdigit() or int(declared) > cap):
        raise TooLarge(f"body over {cap} bytes")
    body = b""
    async for chunk in request.stream():
        body += chunk
        if len(body) > cap:
            raise TooLarge(f"body over {cap} bytes")
    return body


def _seed(clip: str) -> int:
    return match_server.MATCHES[clip]


def _track(clip: str) -> tracking.Track:
    """A clip's positions: tracked from the video, or a simulator stand-in's (labelled truth).
    Raises tracking.NotTracked when a tracked clip has no usable tracked frames."""
    if clip in tracking.TRACKED_CLIPS:
        return tracking.tracked(clip)
    return tracking.track(clip, _seed(clip), match_server.MINUTES, match_server.MATCH_DIR)


def _query_numbers(request: Request, allowed: set[str], required: set[str] = frozenset()) -> dict[str, float]:
    unknown = set(request.query_params) - allowed
    if unknown:
        raise ValueError(f"unknown query parameters: {', '.join(sorted(unknown))}")
    missing = required - set(request.query_params)
    if missing:
        raise ValueError(f"missing query parameters: {', '.join(sorted(missing))}")
    try:
        return {k: float(v) for k, v in request.query_params.items()}
    except ValueError:
        raise ValueError("query parameters must be numbers") from None


class Companion:
    """The routes and their in-memory state. `live` builds the Foundry models for Live mode."""

    def __init__(
        self,
        passcode: str | None = None,
        live: Callable[[], Awaitable[LiveModels]] | None = None,
        clock: Callable[[], float] = time.time,
        allow_truth: bool = False,
    ):
        self.passcode = passcode if passcode is not None else os.environ.get("NINETY_DEMO_PASSCODE", "")
        self.allow_truth = allow_truth  # only the local stand-in mode serves simulator positions
        self.live_factory, self.live_models = live, None
        self.live_lock = asyncio.Lock()
        self.clock = clock
        self.rooms: dict[str, Room] = {}
        self.limits = {name: RateLimit(n) for name, n in LIMITS.items()}
        self.budget = Budget(SESSION_MODEL_CALLS, DAY_MODEL_CALLS, clock)
        # Keys (ninety/speech/voice.key) of the answers given lately: the only text the Live
        # read-aloud route (ninety/api/speak.py) will send to Speech.
        self.spoken: OrderedDict[str, None] = OrderedDict()

    def _served(self, clip: str) -> tracking.Track | JSONResponse:
        """The clip's track, or a 503 when its positions are ground truth and this server may not
        serve them (AGENTS.md: nothing on the live path reads the answer key after Milestone 1)."""
        if clip not in tracking.TRACKED_CLIPS and not self.allow_truth:
            # A stand-in's positions are the simulator's: refused by name, before any file is read
            # or match simulated, so `on` never touches the answer key.
            return _error(503, "positions are ground truth; the companion needs tracked positions")
        try:
            track = _track(clip)
        except tracking.NotTracked as exc:
            return _error(503, str(exc))
        if track.source == tracking.SOURCE and not self.allow_truth:
            return _error(503, "positions are ground truth; the companion needs tracked positions")
        return track

    # --- rooms -----------------------------------------------------------------------------------

    def _purge(self) -> None:
        now = self.clock()
        for code in [c for c, room in self.rooms.items() if room.expires <= now]:
            del self.rooms[code]
            self.budget.sessions.pop(code, None)  # the code was the session: its budget goes too

    def room(self, code: str) -> Room | None:
        self._purge()
        return self.rooms.get(code)

    def _new_code(self) -> str:
        while True:
            code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))
            if code not in self.rooms:
                return code

    async def pair(self, request: Request) -> JSONResponse:
        if not self.limits["pair"].allow(client_ip(request)):
            return _error(429, "too many pairings; wait a minute")
        try:
            body = json.loads(await _read_body(request) or b"{}")
            PAIR_BODY.validate(body)
        except TooLarge as exc:
            return _error(413, str(exc))
        except (json.JSONDecodeError, ValidationError) as exc:
            return _error(422, f"invalid pairing request: {getattr(exc, 'message', exc)}")
        served = self._served(body["clip"])  # a clip this server cannot show is never paired
        if isinstance(served, JSONResponse):
            return served
        self._purge()
        wanted = body.get("code")
        held = self.rooms.get(wanted) if wanted else None
        if held is not None:
            # Still open: given back only for the same clip with no screen on it, which is no more
            # than the laptop slot the relay already offers whoever holds the code.
            if held.clip != body["clip"] or held.laptop is not None:
                return _error(409, "that code is in use; pair again for a new one")
            return JSONResponse({"code": held.code, "clip": held.clip,
                                 "expires_in": max(0, int(held.expires - self.clock()))})
        if len(self.rooms) >= MAX_ROOMS:
            return _error(503, "too many rooms open; try again later")
        # A free code asked for back is taken as it is: no likelier to guess than a new random one.
        room = Room(wanted or self._new_code(), body["clip"], self.clock() + PAIR_TTL_S)
        self.rooms[room.code] = room
        return JSONResponse({"code": room.code, "clip": room.clip, "expires_in": PAIR_TTL_S}, status_code=201)

    async def pairing(self, request: Request) -> JSONResponse:
        """A pairing's clip and seconds left, for a phone given only the typed code (a scanned link
        carries the clip). Under the join limit, so it is no faster a way to guess codes."""
        if not self.limits["join"].allow(client_ip(request)):
            return _error(429, "too many joins; wait a minute")
        room = self.room(request.path_params["code"])
        if room is None:
            return _error(404, "unknown or expired code")
        return JSONResponse({"clip": room.clip, "expires_in": max(0, int(room.expires - self.clock()))})

    async def relay(self, ws: WebSocket) -> None:
        # Joins are limited per address before the code is looked up, so codes cannot be guessed
        # at speed (31^6 of them): a guessed code would let a stranger fill the phone slots, take
        # a dropped laptop's place or spend the session's model budget.
        if not self.limits["join"].allow(client_ip(ws)):
            await _refuse(ws, 4429)
            return
        code, role = ws.path_params["code"], ws.query_params.get("role")
        room = self.room(code)
        if role not in ("laptop", "phone") or set(ws.query_params) != {"role"}:
            await _refuse(ws, 4400)
            return
        if room is None:
            await _refuse(ws, 4404)  # unknown or expired: the laptop pairs again
            return
        refused = (
            4409 if role == "laptop" and room.laptop is not None  # one laptop per room
            else 4429 if role == "phone" and len(room.phones) >= MAX_PHONES
            else None
        )
        if refused is not None:
            await _refuse(ws, refused)
            return
        # Each slot is taken in the same step as the check above, before the accept's await, so
        # two joining at once can neither share the laptop slot nor pass the phone cap. A phone's
        # outbox holds the latest state first and is not sent from until it is accepted, so a
        # message stored meanwhile queues behind the catch-up: each arrives once, in order.
        box = None
        if role == "laptop":
            room.laptop = ws
        else:
            box = Outbox(ws, deque(self._catch_up(room)), flushing=True)
            room.phones[ws] = box
        try:
            await ws.accept()
            if box is not None:
                box.flushing = False
                await self._flush(room, box)
            while True:
                text = await ws.receive_text()
                if self.room(code) is not room:
                    await self._close_room(room, 4410)  # expired while open
                    return
                if role == "phone":
                    await ws.close(code=1008)  # phones only listen
                    return
                if not self.limits["relay"].allow(code):
                    await ws.close(code=1008)
                    return
                message = self._relayable(text)
                if message is None:
                    await ws.close(code=1007)  # not a clock or focus message
                    return
                room.latest[message["type"]] = message
                room.stored_at[message["type"]] = self.clock()
                for phone_box in list(room.phones.values()):
                    phone_box.items.append(message)
                    # Each phone is sent to on its own task, so a stalled phone holds up only itself.
                    task = asyncio.create_task(self._flush(room, phone_box))
                    room.sending.add(task)
                    task.add_done_callback(room.sending.discard)
        except WebSocketDisconnect:
            pass
        finally:
            if role == "laptop" and room.laptop is ws:
                room.laptop = None
            room.phones.pop(ws, None)

    def _catch_up(self, room: Room) -> list[dict]:
        """The latest state for a phone joining late. A playing clock has run on since the laptop
        sent it (up to a second ago), so it is sent as it stands now, not as it stood then; a
        paused clock and a focus are sent as stored."""
        out = []
        for kind, message in room.latest.items():
            if kind == "clock" and message.get("playing"):
                message = {**message, "t": round(self._playhead(room), 2)}
            out.append(message)
        return out

    def _playhead(self, room: Room) -> float | None:
        """Where the big screen is now: its last clock, run on since it was sent if it is playing.
        None before the laptop has sent one."""
        clock = room.latest.get("clock")
        if clock is None:
            return None
        if not clock.get("playing"):
            return clock["t"]
        return clock["t"] + max(0.0, self.clock() - room.stored_at.get("clock", self.clock()))

    def _asked_at(self, room: Room, track: tracking.Track, t: float) -> float:
        """The match time a question is answered at: never past the room's playhead (plus
        PLAYHEAD_SLACK_S) nor the clip's end, so a phone cannot ask about what the big screen has not
        shown. Before the laptop has sent a clock nothing has been shown: the playhead is 0."""
        playhead = self._playhead(room)
        return min(t, (playhead or 0.0) + PLAYHEAD_SLACK_S, track.duration)

    @staticmethod
    async def _flush(room: Room, box: Outbox) -> None:
        """Send what the phone is owed, unless another flusher already is (it sends this too)."""
        if box.flushing:
            return
        box.flushing = True
        try:
            while box.items:
                await box.ws.send_json(box.items.popleft())
        except (WebSocketDisconnect, RuntimeError):  # the phone went away
            room.phones.pop(box.ws, None)
            box.items.clear()
        finally:
            box.flushing = False

    @staticmethod
    def _relayable(text: str) -> dict | None:
        if len(text.encode()) > MAX_MESSAGE_BYTES:
            return None
        try:
            message = json.loads(text)
            MESSAGE.validate(message)
        except (json.JSONDecodeError, ValidationError):
            return None
        return message if message["type"] in RELAYED else None

    async def _close_room(self, room: Room, code: int) -> None:
        for ws in [room.laptop, *list(room.phones)]:
            if ws is not None and ws.client_state == WebSocketState.CONNECTED:
                await ws.close(code=code)

    # --- reads -----------------------------------------------------------------------------------

    async def minimap(self, request: Request) -> JSONResponse:
        if not self.limits["read"].allow(client_ip(request)):
            return _error(429, "too many requests; wait a minute")
        clip = request.path_params["clip"]
        if clip not in CLIPS:
            return _error(404, f"unknown clip {clip!r}")
        try:
            fps = int(_query_numbers(request, {"fps"}).get("fps", 5))
        except ValueError as exc:
            return _error(422, str(exc))
        if fps not in FPS_CHOICES:
            return _error(422, f"fps must be one of {list(FPS_CHOICES)}")
        track = self._served(clip)
        if isinstance(track, JSONResponse):
            return track
        step = tracking.FPS // fps
        frames = [
            {
                "t": f["t"],
                "ball": [round(f["ball"]["x"], MINIMAP_PLACES), round(f["ball"]["y"], MINIMAP_PLACES)],
                "players": [
                    [p["id"], round(p["x"], MINIMAP_PLACES), round(p["y"], MINIMAP_PLACES)]
                    for p in f["players"]
                ],
            }
            for f in track.frames[::step]
        ]
        body = {
            "clip": clip,
            "source": track.source,
            "fps": fps,
            "roster": list(track.roster),
            "frames": frames,
        }
        MINIMAP.validate(body)
        return JSONResponse(body)

    def _window(self, track: tracking.Track, player: str, t_from: float, t_to: float):
        t_to = min(t_to, track.duration)
        return track, player_window(track.frames, player, min(t_from, t_to), t_to, track.restarts)

    async def card(self, request: Request) -> JSONResponse:
        if not self.limits["read"].allow(client_ip(request)):
            return _error(429, "too many requests; wait a minute")
        clip, player = request.path_params["clip"], request.path_params["player"]
        if clip not in CLIPS:
            return _error(404, f"unknown clip {clip!r}")
        track = self._served(clip)
        if isinstance(track, JSONResponse):
            return track
        if player not in track.roster:
            return _error(422, f"{player!r} is not on the roster of {clip}")
        try:
            q = _query_numbers(request, {"t_from", "t_to"}, {"t_to"})
        except ValueError as exc:
            return _error(422, str(exc))
        t_from, t_to = q.get("t_from", 0.0), q["t_to"]
        if not 0 <= t_from <= t_to:
            return _error(422, "need 0 <= t_from <= t_to")
        track, window = self._window(track, player, t_from, t_to)
        if window is None:
            return _error(404, f"no positions of {player} in that window")
        card = window.card(track.source)
        if track.source == "tracked":
            total = player_total(clip, player, t_to)
            if total is not None:
                card["player_total"] = total
        return JSONResponse(_send(card))

    async def flow(self, request: Request) -> JSONResponse:
        if not self.limits["read"].allow(client_ip(request)):
            return _error(429, "too many requests; wait a minute")
        clip, team = request.path_params["clip"], request.path_params["team"]
        if clip not in CLIPS:
            return _error(404, f"unknown clip {clip!r}")
        if team not in ("home", "away"):
            return _error(422, "team must be home or away")
        try:
            q = _query_numbers(request, {"t_from", "t_to"}, {"t_to"})
        except ValueError as exc:
            return _error(422, str(exc))
        t_from, t_to = q.get("t_from", 0.0), q["t_to"]
        if not 0 <= t_from <= t_to:
            return _error(422, "need 0 <= t_from <= t_to")
        track = self._served(clip)
        if isinstance(track, JSONResponse):
            return track
        t_to = min(t_to, track.duration)
        field = team_flow(track.frames, team, min(t_from, t_to), t_to, track.restarts)
        return JSONResponse(_send(field.message(track.source)))

    # --- questions -------------------------------------------------------------------------------

    def _live_mode(self, request: Request) -> bool | JSONResponse:
        sent = request.headers.get(PASSCODE_HEADER)
        if sent is None:
            return False
        if not self.passcode or self.live_factory is None:
            return _error(503, "Live mode is not configured")
        if not hmac.compare_digest(sent.encode(), self.passcode.encode()):
            return _error(401, "wrong passcode")
        return True

    async def ask(self, request: Request) -> JSONResponse:
        if not self.limits["ask_ip"].allow(client_ip(request)):
            return _error(429, "too many questions; wait a minute")
        live = self._live_mode(request)
        if isinstance(live, JSONResponse):
            return live
        try:
            body = json.loads(await _read_body(request))
            QUESTION.validate(body)
            question = Question(**body)
        except TooLarge as exc:
            return _error(413, str(exc))
        except (json.JSONDecodeError, ValidationError, TypeError, ValueError) as exc:
            return _error(422, f"invalid question: {getattr(exc, 'message', exc)}")
        room = self.room(question.session)
        if room is None:
            return _error(404, "unknown or expired session; pair again")
        if not self.limits["ask_session"].allow(question.session):
            return _error(429, "too many questions; wait a minute")
        track = self._served(room.clip)
        if isinstance(track, JSONResponse):
            return track
        if question.player is not None and question.player not in track.roster:
            return _error(422, f"{question.player!r} is not on the roster of {room.clip}")
        asked_at = self._asked_at(room, track, question.t)
        record_fields = {"clip": room.clip, "live": bool(live), "t_asked": question.t, "t_used": asked_at,
                         "question": telemetry.text_digest(question.text)}
        question = dataclasses.replace(question, t=asked_at)
        with telemetry.ask_trace(**record_fields) as record:  # sent when the question is answered
            message = await self._answer(question, room, track, live, record)
        return JSONResponse(message)

    async def _answer(self, question: Question, room: Room, track: tracking.Track, live: bool,
                      record: dict) -> dict:
        if question.player is None:
            insights = _insights(room.clip)
            if insights is not None:
                # A match question: the match Companion chooses the insight tools in Live mode (within
                # the session's budget), with the pairing's earlier turns; code routes and answers
                # otherwise or when it fails. The budget is taken on the first model call, so a
                # question code answers on its own (small talk, an overview) spends none.
                ask = referee_ask = None
                if live:
                    ask, referee_ask = self._metered(question.session, "match_ask", "referee_ask")
                record["path"] = "match"
                result = await companion_match.answer_match(
                    question, insights, ask, None, history=room.turns, referee_ask=referee_ask
                )
                turn = {"question": question.text, "answer": result.answer.text, "calls": list(result.tools)}
                room.turns = [*room.turns, turn][-MAX_TURNS:]
                record.update(source=result.source, reasons=list(result.reasons),
                              tools=[c["name"] for c in result.tools], status=result.answer.status)
                return _send({"type": "answer", "answer": answer_json(result.answer),
                              "source": result.source})
        window = None
        if question.player is not None:
            _, window = self._window(track, question.player, 0.0, question.t)
        ask = judge = None
        if live and window is not None and self.budget.take(question.session):
            models = await self._live_models()
            if models is not None:
                ask, judge = models.ask, models.judge
        record["path"] = "player"
        result = await companion.answer(question, window, ask, judge)
        record.update(source=result.source, reasons=list(result.reasons), tools=[],
                      status=result.answer.status)
        message = _send({"type": "answer", "answer": answer_json(result.answer), "source": result.source})
        for said in (message["answer"].get("text"), message["answer"].get("spoken")):
            if isinstance(said, str) and said.strip():
                self.spoken[voice.key(said)] = None
                self.spoken.move_to_end(voice.key(said))
        while len(self.spoken) > MAX_SPOKEN:
            self.spoken.popitem(last=False)
        return message

    def _metered(self, session: str, *roles: str) -> tuple[Ask, ...]:
        """The Live models as the match Companion calls them, one per role. The first call to any of
        them takes one from the session's budget (one per question, however many steps); a spent
        budget, or models that could not be built, raise NoModel, and code answers with that reason."""
        taken: dict[str, bool] = {}

        def metered(role: str) -> Ask:
            async def call(prompt: str) -> str:
                if "budget" not in taken:
                    taken["budget"] = self.budget.take(session)
                if not taken["budget"]:
                    raise companion.NoModel("model budget spent")
                models = await self._live_models()
                # A role not published (no Referee) is answered by the first role, as before.
                model = (getattr(models, role, None) or getattr(models, roles[0], None)) if models else None
                if model is None:
                    raise companion.NoModel("Live models unavailable")
                return await model(prompt)

            return call

        return tuple(metered(role) for role in roles)

    def answered(self, key: str) -> bool:
        """Whether an answer with this text (ninety/speech/voice.key) was given lately."""
        return key in self.spoken

    async def _live_models(self) -> LiveModels | None:
        """The Live models, built on the first Live question. A failure to build them (no identity,
        Foundry unreachable, a pin missing) gives that question the code answer and is tried again on
        the next one: any model failure gives a code answer, never a 500 (lesson 96)."""
        async with self.live_lock:  # two first questions must not build two clients
            if self.live_models is None:
                try:
                    self.live_models = await self.live_factory()
                except Exception as exc:  # noqa: BLE001  whatever the SDK raises, the viewer gets code
                    log.warning("could not build the Live models: %s", type(exc).__name__)
                    return None
            return self.live_models

    def routes(self) -> list:
        return [
            Route("/api/pair", self.pair, methods=["POST"]),
            Route("/api/pair/{code}", self.pairing, methods=["GET"]),
            WebSocketRoute("/api/pair/{code}", self.relay),
            Route("/api/minimap/{clip}", self.minimap, methods=["GET"]),
            Route("/api/card/{clip}/{player}", self.card, methods=["GET"]),
            Route("/api/flow/{clip}/{team}", self.flow, methods=["GET"]),
            Route("/api/ask", self.ask, methods=["POST"]),
        ]


MAX_TURNS = 6  # design: a pairing remembers its last six exchanges, more than the model is shown


PLAYER_TOTAL_KEYS = ("player", "name", "source", "source_label", "running_to_minute", "footage_s",
                     "tracked_s", "footage_coverage", "distance_m", "top_kmh")


def player_total(clip: str, track_id: str, t: float) -> dict | None:
    """The match so far of the player the Player ID feed names on this tactical track: his running
    over every track the feed names his, to the last minute ended by t and never later
    (ninety/intel/player_stats.py, as the MCP tool serves it), with what it covers and why a figure
    is withheld. None when the feed does not name the track, so the card keeps its per-track
    numbers: one track's stretch, never said as his match."""
    mi = _insights(clip)
    row = mi.track_player_stats(track_id, t) if mi is not None else None
    if row is None:
        return None
    withheld = {k: row["withheld"][k] for k in ("distance_m", "top_kmh") if k in row["withheld"]}
    return {**{k: row[k] for k in PLAYER_TOTAL_KEYS}, "withheld": withheld}


def _insights(clip: str):
    """The clip's insight facts, or None when it has no tracked frames or is not served."""
    from ninety.mcp import match_server

    try:
        return match_server.insights_of(clip)
    except ValueError:
        return None


def answer_json(answer: Answer) -> dict:
    return {
        "status": answer.status,
        "text": answer.text,
        "metric": answer.metric,
        "value": answer.value,
        "unit": answer.unit,
        "evidence": list(answer.evidence),
        "t_from": answer.t_from,
        "t_to": answer.t_to,
        "visual": answer.visual,
        "names": answer.names,
        "spoken": answer.spoken,
        "follow_ups": list(answer.follow_ups),
        "headline": answer.headline,
    }


async def foundry_models() -> LiveModels:
    """The published Companion and Judge, at the versions pinned in foundry_agents.json. Signs in as
    the Container App's managed identity through the shared aio credential (ninety/agents/
    credentials.py, lesson 69: a sync one would fetch its token on the event loop's thread and stall
    every relay), signed in here, before the first question waits on it. No key."""
    import contextlib

    from agent_framework.foundry import FoundryAgent

    from ninety import config
    from ninety.agents import credentials, foundry
    from ninety.agents.factcheck import Claim, Verdict
    from ninety.agents.judge import judge as run_judge
    from ninety.agents.judge import judge_agent

    stack = contextlib.AsyncExitStack()  # kept open for the life of the process
    credential = await stack.enter_async_context(credentials.new_credential())
    await credentials.sign_in(credential)
    client = foundry.chat_client(credential)
    agents = []
    from ninety.agents.referee import referee_agent

    match_agent = companion_match.companion_match_agent(client)
    locals_ = (companion.companion_agent(client), judge_agent(client), match_agent, referee_agent(client))
    for local in locals_:
        name, version = foundry.pinned(local)
        published = FoundryAgent(
            project_endpoint=config.FOUNDRY_PROJECT,
            agent_name=name,
            agent_version=version,
            credential=credential,
        )
        agents.append(await stack.enter_async_context(published))
    companion_ag, judge_ag, match_ag, referee_ag = agents

    async def text_of(agent, prompt: str) -> str:
        reply = await agent.run(prompt)
        telemetry.note_usage(reply)  # its tokens, into the question's trace
        return reply.text

    class Noted:
        """The Judge agent with each reply's tokens noted, as text_of notes the others'."""

        async def run(self, prompt, **kwargs):
            reply = await judge_ag.run(prompt, **kwargs)
            telemetry.note_usage(reply)
            return reply

    async def ask(prompt: str) -> str:
        return await text_of(companion_ag, prompt)

    async def judge(claim: Claim, evidence: list[dict]) -> Verdict:
        # The step budget (companion.STEP_S) bounds it: the Judge's own 15 s and retry are the slice's.
        return await run_judge(Noted(), claim, evidence)

    async def match_ask(prompt: str) -> str:
        return await text_of(match_ag, prompt)

    async def referee_ask(prompt: str) -> str:
        return await text_of(referee_ag, prompt)

    return LiveModels(ask, judge, match_ask, referee_ask)


def from_env(env: dict[str, str] | None = None) -> Companion | None:
    """The companion NINETY_COMPANION asks for. Unset or `on` (as deployed): mounted, serving only
    tracked positions, with a 503 for a clip whose positions are ground truth. `standin`: the
    simulator matches too, labelled truth, for building the phone locally. `off`: not mounted. Any
    other value is a typo that must not pass silently."""
    mode = (os.environ if env is None else env).get("NINETY_COMPANION", "") or "on"
    if mode not in MODES:
        raise ValueError(f"NINETY_COMPANION={mode!r}: use one of {', '.join(MODES)}, or leave it unset")
    if mode == "off":
        return None
    return Companion(live=foundry_models, allow_truth=mode == "standin")
