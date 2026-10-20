"""The Personalizer as an A2A server: a separate process the Producer calls over the A2A protocol.

One request is one A2A message with one data part:

    {"claim": {"text": ..., "evidence": [...]}, "evidence": [<event>, ...], "profiles": [<Profile>, ...]}

and the reply is one message with one data part, {"variants": [<Variant>, ...], "dropped": {...}}:
one variant per profile in order, and why the server replaced a profile's variant with the verified
text, by profile number. Profiles are rebuilt with `Profile`, which refuses any value outside its
allow-lists, so a viewer's text never reaches the model; a request that fails validation is
refused with an A2A invalid-params error before any model call.

    uv run uvicorn --factory ninety.personalizer.server:live_app --port 8001

`live_app` calls the Foundry prompt agent `ninety-personalizer` at its pinned version
(ninety/agents/foundry_agents.json) as the container's managed identity; `create_app` takes any
Personalize, so tests run the same server with no Azure.
"""

from __future__ import annotations

from dataclasses import asdict

from a2a.helpers.proto_helpers import get_data_parts, new_data_message
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import create_agent_card_routes, create_jsonrpc_routes
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import AgentCapabilities, AgentCard, AgentInterface, AgentSkill
from a2a.utils.constants import PROTOCOL_VERSION_CURRENT
from a2a.utils.errors import InvalidParamsError, UnsupportedOperationError
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

from ninety.agents.contracts import Personalize, Profile
from ninety.agents.factcheck import Claim

RPC_PATH = "/"
# Design cap on one request's size: four written personas in two languages is eight profiles, and a
# club or player choice can split one persona; past 16 a request is refused, not queued.
MAX_PROFILES = 16


def agent_card(url: str) -> AgentCard:
    return AgentCard(
        name="ninety-personalizer",
        description="Rewrites one verified football claim for each viewer profile and language.",
        version="1",
        supported_interfaces=[
            AgentInterface(url=url, protocol_binding="JSONRPC", protocol_version=PROTOCOL_VERSION_CURRENT)
        ],
        capabilities=AgentCapabilities(streaming=False),
        default_input_modes=["application/json"],
        default_output_modes=["application/json"],
        skills=[
            AgentSkill(
                id="personalize",
                name="Personalize a verified claim",
                description="analyst, casual, club and player focus; English and Spanish",
                tags=["football", "personalization"],
            )
        ],
    )


def read_request(data: object) -> tuple[Claim, list[dict], list[Profile]]:
    """The claim, evidence and profiles of a request, or ValueError. Unknown fields are refused."""
    if not isinstance(data, dict) or set(data) != {"claim", "evidence", "profiles"}:
        raise ValueError("expected exactly claim, evidence and profiles")
    claim, evidence, profiles = data["claim"], data["evidence"], data["profiles"]
    if not isinstance(claim, dict) or set(claim) != {"text", "evidence"}:
        raise ValueError("claim: expected exactly text and evidence")
    if not isinstance(claim["text"], str) or not all(isinstance(i, str) for i in claim["evidence"]):
        raise ValueError("claim: text and evidence ids must be strings")
    if not isinstance(evidence, list) or not all(isinstance(e, dict) and "id" in e for e in evidence):
        raise ValueError("evidence: expected a list of events with ids")
    if not isinstance(profiles, list) or not 0 < len(profiles) <= MAX_PROFILES:
        raise ValueError(f"profiles: expected 1 to {MAX_PROFILES}")
    try:
        parsed = [Profile(**p) for p in profiles]
    except TypeError as e:  # a field Profile does not have
        raise ValueError(f"profile: {e}") from None
    return Claim(claim["text"], list(claim["evidence"])), evidence, parsed


class PersonalizerExecutor(AgentExecutor):
    def __init__(self, personalize: Personalize):
        self.personalize = personalize

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        parts = get_data_parts(context.message.parts) if context.message else []
        if len(parts) != 1 or len(context.message.parts) != 1:
            # A text part is refused, not skipped: a request is data, never instructions.
            raise InvalidParamsError("send exactly one data part and nothing else")
        try:
            claim, evidence, profiles = read_request(parts[0])
        except ValueError as e:
            raise InvalidParamsError(str(e)) from None
        explained = getattr(self.personalize, "explained", None)  # core.model_personalizer's
        if explained is not None:
            variants, dropped = await explained(claim, evidence, profiles)
        else:
            variants, dropped = await self.personalize(claim, evidence, profiles), {}
        reply = {
            "variants": [{**asdict(v), "evidence": list(v.evidence)} for v in variants],
            "dropped": {str(i): why for i, why in dropped.items()},  # JSON keys are strings
        }
        await event_queue.enqueue_event(new_data_message(reply, context_id=context.context_id))

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        raise UnsupportedOperationError("a personalization answers at once; nothing to cancel")


async def _health(request) -> JSONResponse:
    return JSONResponse({"ok": True})


def create_app(personalize: Personalize, url: str = "http://localhost:8001/", lifespan=None) -> Starlette:
    card = agent_card(url)
    handler = DefaultRequestHandler(
        agent_executor=PersonalizerExecutor(personalize), task_store=InMemoryTaskStore(), agent_card=card
    )
    routes = [
        *create_agent_card_routes(card),
        *create_jsonrpc_routes(handler, RPC_PATH),
        Route("/health", _health),
    ]
    return Starlette(routes=routes, lifespan=lifespan)


def live_app() -> Starlette:
    """The deployed server: the published Foundry agent behind the re-check."""
    import contextlib
    import os

    from ninety.personalizer.core import model_personalizer, published_ask

    published = {}  # the Ask, once the lifespan has signed in

    async def ask(text: str) -> str:
        return await published["ask"](text)

    @contextlib.asynccontextmanager
    async def lifespan(app):
        async with published_ask() as (published["ask"], _):
            yield

    from ninety.personalizer import translate

    personalize = model_personalizer(ask)
    if (translator := translate.from_env()) is not None:  # NINETY_TRANSLATOR, off by default
        personalize = translate.translated(personalize, translator)
    url = os.environ.get("NINETY_PERSONALIZER_URL", "http://localhost:8001/")
    return create_app(personalize, url, lifespan)
