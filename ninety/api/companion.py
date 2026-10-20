"""The phone companion's routes: pairing, the relay, the minimap, player cards and questions.

    POST /api/pair                     {"clip": "seed7"} -> a 6-character code, valid for 2 hours
    WS   /api/pair/{code}?role=laptop  the laptop sends clock and focus messages
    WS   /api/pair/{code}?role=phone   each phone receives them, the latest first
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
calls; once a budget is spent, code answers. Live needs NINETY_DEMO_PASSCODE (a Key Vault
reference in Azure); without it a passcode is refused, so Live fails closed.

Rooms, rate limits and budgets live in this process's memory: the API runs as one Container App
replica (infra/main.bicep), so a phone and its laptop always reach the same rooms. More replicas
would need a shared store (or session affinity) first. A restart forgets every room, and the
laptop pairs again.

Which mode runs is NINETY_COMPANION (`app_mode`): unset, the routes are not mounted, which is the
deployed configuration; `standin` serves the simulator's matches, labelled `source: truth` in every
message, for building the phone locally; `on` serves only tracked positions and answers 503 for a
clip whose positions are ground truth. Nothing tracks positions from the video yet, so after
Milestone 1 the companion stays off where it is deployed (AGENTS.md, "Ground truth is the answer
key"), and turns on when tracked positions exist (ninety/match/tracking.py).
"""

from __future__ import annotations

import hmac
import json
import os
import secrets
import time
from collections import defaultdict, deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from jsonschema import Draft202012Validator, ValidationError
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route, WebSocketRoute
from starlette.websockets import WebSocket, WebSocketDisconnect, WebSocketState

from ninety.agents import companion
from ninety.agents.contracts import Answer, Ask, Judge, Question, schema_validator
from ninety.intel.window import player_window, team_flow
from ninety.match import tracking
from ninety.mcp import match_server

CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"  # no 0/O, 1/I/L: read off a laptop screen
CODE_LENGTH = 6
PAIR_TTL_S = 2 * 60 * 60
MAX_ROOMS = 500  # design: bounds memory; the demo needs a handful
MAX_PHONES = 8  # per room
MAX_MESSAGE_BYTES = 1024
RELAYED = {"clock", "focus"}  # what a laptop may send; answers and cards come from the server
FPS_CHOICES = (1, 5, 25)  # divisors of the engine's 25 fps, so frames are evenly spaced
MINIMAP_PLACES = 1  # 0.1 m: finer than a phone's dot, coarser than the tracker's error
PASSCODE_HEADER = "x-ninety-passcode"
MODES = ("standin", "on")  # NINETY_COMPANION; unset means the routes are not mounted
# Requests a client may make in a minute (design: a person tapping, never a script).
LIMITS = {"pair": 6, "read": 120, "ask_ip": 20, "ask_session": 10, "relay": 600}
SESSION_MODEL_CALLS, DAY_MODEL_CALLS = 20, 400  # design: about $1 a day at the demo's model price

MESSAGE = schema_validator("companion_message")
QUESTION = schema_validator("viewer_question")
MINIMAP = schema_validator("minimap")
PAIR_BODY = Draft202012Validator(
    {
        "type": "object",
        "additionalProperties": False,
        "required": ["clip"],
        "properties": {"clip": {"type": "string", "enum": sorted(match_server.MATCHES)}},
    }
)


class RateLimit:
    """At most `limit` hits per key in any `window` seconds (a sliding log)."""

    def __init__(self, limit: int, window: float = 60.0, clock: Callable[[], float] = time.monotonic):
        self.limit, self.window, self.clock = limit, window, clock
        self.hits: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str) -> bool:
        now, hits = self.clock(), self.hits[key]
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


@dataclass
class LiveModels:
    """The Companion and the Judge on Foundry, for Live mode. Built on first use."""

    ask: Ask
    judge: Judge


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


def _seed(clip: str) -> int:
    return match_server.MATCHES[clip]


def _track(clip: str) -> tracking.Track:
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
        self.clock = clock
        self.rooms: dict[str, Room] = {}
        self.limits = {name: RateLimit(n) for name, n in LIMITS.items()}
        self.budget = Budget(SESSION_MODEL_CALLS, DAY_MODEL_CALLS, clock)

    def _served(self, clip: str) -> tracking.Track | JSONResponse:
        """The clip's track, or a 503 when its positions are ground truth and this server may not
        serve them (AGENTS.md: nothing on the live path reads the answer key after Milestone 1)."""
        track = _track(clip)
        if track.source == tracking.SOURCE and not self.allow_truth:
            return _error(503, "positions are ground truth; the companion needs tracked positions")
        return track

    # --- rooms -----------------------------------------------------------------------------------

    def _purge(self) -> None:
        now = self.clock()
        for code in [c for c, room in self.rooms.items() if room.expires <= now]:
            del self.rooms[code]

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
            body = json.loads(await request.body() or b"{}")
            PAIR_BODY.validate(body)
        except (json.JSONDecodeError, ValidationError) as exc:
            return _error(422, f"invalid pairing request: {getattr(exc, 'message', exc)}")
        self._purge()
        if len(self.rooms) >= MAX_ROOMS:
            return _error(503, "too many rooms open; try again later")
        room = Room(self._new_code(), body["clip"], self.clock() + PAIR_TTL_S)
        self.rooms[room.code] = room
        return JSONResponse({"code": room.code, "clip": room.clip, "expires_in": PAIR_TTL_S}, status_code=201)

    async def relay(self, ws: WebSocket) -> None:
        code, role = ws.path_params["code"], ws.query_params.get("role")
        room = self.room(code)
        if role not in ("laptop", "phone") or set(ws.query_params) != {"role"}:
            await ws.close(code=4400)
            return
        if room is None:
            await ws.close(code=4404)  # unknown or expired: the laptop pairs again
            return
        refused = (
            4409 if role == "laptop" and room.laptop is not None  # one laptop per room
            else 4429 if role == "phone" and len(room.phones) >= MAX_PHONES
            else None
        )
        if refused is not None:
            await ws.close(code=refused)
            return
        if role == "laptop":
            room.laptop = ws  # claimed before the accept's await, so a second laptop cannot slip in
        try:
            await ws.accept()
            if role == "phone":
                # Joined and caught up in one step: what was stored before is in the outbox first,
                # what is stored after is queued behind it. Each message arrives once, in order.
                box = Outbox(ws, deque(room.latest.values()))
                room.phones[ws] = box
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
                boxes = list(room.phones.values())
                for box in boxes:
                    box.items.append(message)
                for box in boxes:
                    await self._flush(room, box)
        except WebSocketDisconnect:
            pass
        finally:
            if role == "laptop" and room.laptop is ws:
                room.laptop = None
            room.phones.pop(ws, None)

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
        if clip not in match_server.MATCHES:
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
        if clip not in match_server.MATCHES:
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
        return JSONResponse(_send(window.card(track.source)))

    async def flow(self, request: Request) -> JSONResponse:
        if not self.limits["read"].allow(client_ip(request)):
            return _error(429, "too many requests; wait a minute")
        clip, team = request.path_params["clip"], request.path_params["team"]
        if clip not in match_server.MATCHES:
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
            body = json.loads(await request.body())
            QUESTION.validate(body)
            question = Question(**body)
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
        window = None
        if question.player is not None:
            _, window = self._window(track, question.player, 0.0, question.t)
        ask = judge = None
        if live and window is not None and self.budget.take(question.session):
            if self.live_models is None:
                self.live_models = await self.live_factory()
            ask, judge = self.live_models.ask, self.live_models.judge
        result = await companion.answer(question, window, ask, judge)
        return JSONResponse(_send({"type": "answer", "answer": answer_json(result.answer)}))

    def routes(self) -> list:
        return [
            Route("/api/pair", self.pair, methods=["POST"]),
            WebSocketRoute("/api/pair/{code}", self.relay),
            Route("/api/minimap/{clip}", self.minimap, methods=["GET"]),
            Route("/api/card/{clip}/{player}", self.card, methods=["GET"]),
            Route("/api/flow/{clip}/{team}", self.flow, methods=["GET"]),
            Route("/api/ask", self.ask, methods=["POST"]),
        ]


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
    }


async def foundry_models() -> LiveModels:
    """The published Companion and Judge, at the versions pinned in foundry_agents.json. Signs in as
    the Container App's managed identity (DefaultAzureCredential), so there is no key."""
    import contextlib

    from agent_framework.foundry import FoundryAgent
    from azure.identity import DefaultAzureCredential

    from ninety import config
    from ninety.agents import foundry
    from ninety.agents.factcheck import Claim, Verdict
    from ninety.agents.judge import judge as run_judge
    from ninety.agents.judge import judge_agent

    credential = DefaultAzureCredential()
    client = foundry.chat_client(credential)
    stack = contextlib.AsyncExitStack()  # kept open for the life of the process
    agents = []
    for local in (companion.companion_agent(client), judge_agent(client)):
        name, version = foundry.pinned(local)
        published = FoundryAgent(
            project_endpoint=config.FOUNDRY_PROJECT,
            agent_name=name,
            agent_version=version,
            credential=credential,
        )
        agents.append(await stack.enter_async_context(published))
    companion_ag, judge_ag = agents

    async def ask(prompt: str) -> str:
        return (await companion_ag.run(prompt)).text

    async def judge(claim: Claim, evidence: list[dict]) -> Verdict:
        return await run_judge(judge_ag, claim, evidence)

    return LiveModels(ask, judge)


def from_env(env: dict[str, str] | None = None) -> Companion | None:
    """The companion NINETY_COMPANION asks for: None (unset, as deployed), the local stand-in, or
    `on`, which refuses ground-truth positions. Any other value is a typo that must not pass silently."""
    mode = (os.environ if env is None else env).get("NINETY_COMPANION", "")
    if not mode:
        return None
    if mode not in MODES:
        raise ValueError(f"NINETY_COMPANION={mode!r}: use one of {', '.join(MODES)}, or leave it unset")
    return Companion(live=foundry_models, allow_truth=mode == "standin")
