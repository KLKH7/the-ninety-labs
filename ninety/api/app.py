"""The public API, served from Azure Container Apps.

    GET  /api/health   the commit this image was built from (the deploy smoke test reads it)
    POST /mcp          the match MCP server (ninety/mcp/match_server.py), for Foundry's agents
    /api/pair, /api/minimap, /api/card, /api/ask   the phone companion (ninety/api/companion.py)

/mcp needs the `x-api-key` header. The key lives in Key Vault; the container reads it through its
managed identity and Foundry holds it in a project connection (infra/main.bicep), so it is never
in the repo. Without a configured key the endpoint refuses every call: fail closed.

    uv run uvicorn ninety.api.app:app --port 8000
"""

from __future__ import annotations

import contextlib
import hmac
import os

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.types import ASGIApp, Receive, Scope, Send

from ninety.api.companion import Companion, foundry_models
from ninety.mcp import match_server

# Set at image build time (Dockerfile ARG); "dev" when run from a checkout.
COMMIT = os.environ.get("NINETY_COMMIT") or "dev"
KEY_HEADER = b"x-api-key"


async def health(request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok", "commit": COMMIT})


class RequireKey:
    """Lets a request through only with the right key, compared in constant time."""

    def __init__(self, app: ASGIApp, key: str | None = None):
        self.app = app
        self.key = key if key is not None else os.environ.get("NINETY_MCP_KEY", "")

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            sent = dict(scope["headers"]).get(KEY_HEADER, b"")
            if not self.key:
                await JSONResponse({"error": "MCP is not configured"}, status_code=503)(scope, receive, send)
                return
            if not hmac.compare_digest(sent, self.key.encode()):
                await JSONResponse({"error": "missing or wrong x-api-key"}, status_code=401)(
                    scope, receive, send
                )
                return
        await self.app(scope, receive, send)


def build(key: str | None = None, companion: Companion | None = None) -> Starlette:
    mcp = match_server.make_server()
    companion = companion or Companion(live=foundry_models)
    mcp_app = mcp.streamable_http_app()

    @contextlib.asynccontextmanager
    async def lifespan(app: Starlette):
        async with mcp.session_manager.run():
            yield

    return Starlette(
        routes=[
            Route("/api/health", health, methods=["GET"]),
            Route("/mcp", RequireKey(mcp_app, key)),
            *companion.routes(),
        ],
        lifespan=lifespan,
    )


app = build()
