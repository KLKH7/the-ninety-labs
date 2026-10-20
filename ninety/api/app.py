"""The public API and the demo site, served from one Azure Container App.

    GET  /                 the viewer (web/viewer, built into the image)
    GET  /phone/           the phone companion (web/phone), on the viewer's origin: the viewer's
                           "connect your phone" QR code points at phone/ beside itself
    GET  /bundle/...       the Replay bundle the viewer plays: one clip through the whole chain,
                           made by ninety-e2e ahead of time (infra/replay.py), so a view costs nothing
    GET  /api/health       the commit this image was built from (the deploy smoke test reads it)
    GET  /api/live/status  Live mode's gate: answers only with the demo passcode
    POST /mcp              the match MCP server (ninety/mcp/match_server.py), for Foundry's agents

/mcp needs the `x-api-key` header and Live mode the `x-demo-passcode` header. Both values live in
Key Vault; the container reads them through its managed identity (infra/main.bicep), so neither is
ever in the repo. Without a configured value the route refuses every call: fail closed. Live
routes (agent runs, speech) mount under /api/live, behind the passcode, as they land.

    uv run uvicorn ninety.api.app:app --port 8000
"""

from __future__ import annotations

import contextlib
import hmac
import os
from pathlib import Path

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from ninety.mcp import match_server

ROOT = Path(__file__).resolve().parents[2]
# Set at image build time (Dockerfile ARG); "dev" when run from a checkout.
COMMIT = os.environ.get("NINETY_COMMIT") or "dev"
KEY_HEADER = b"x-api-key"
PASSCODE_HEADER = b"x-demo-passcode"
VIEWER_DIR = Path(os.environ.get("NINETY_VIEWER_DIR") or ROOT / "web" / "viewer" / "dist")
PHONE_DIR = Path(os.environ.get("NINETY_PHONE_DIR") or ROOT / "web" / "phone" / "dist")
REPLAY_DIR = Path(os.environ.get("NINETY_REPLAY_DIR") or ROOT / "runs" / "replay")

# Same origin only: the viewer loads its scripts, styles, bundle and video from this host and
# nothing else, so `?bundle=` cannot point it at another site, and no page may frame it.
SECURITY_HEADERS = [
    (b"content-security-policy",
     b"default-src 'self'; img-src 'self' data: blob:; media-src 'self' blob:; connect-src 'self'; "
     b"object-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"),
    (b"x-content-type-options", b"nosniff"),
    (b"referrer-policy", b"no-referrer"),
    (b"cross-origin-opener-policy", b"same-origin"),
]


async def health(request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok", "commit": COMMIT})


async def live_status(request: Request) -> JSONResponse:
    return JSONResponse({"live": "ok"})


class RequireKey:
    """Lets a request through only with the right header value, compared in constant time."""

    def __init__(self, app: ASGIApp, key: str | None = None, header: bytes = KEY_HEADER,
                 env: str = "NINETY_MCP_KEY", what: str = "MCP"):
        self.app = app
        self.header = header
        self.what = what
        self.key = key if key is not None else os.environ.get(env, "")

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            sent = dict(scope["headers"]).get(self.header, b"")
            if not self.key:
                await JSONResponse({"error": f"{self.what} is not configured"}, status_code=503)(
                    scope, receive, send
                )
                return
            if not hmac.compare_digest(sent, self.key.encode()):
                await JSONResponse({"error": f"missing or wrong {self.header.decode()}"}, status_code=401)(
                    scope, receive, send
                )
                return
        await self.app(scope, receive, send)


class SecurityHeaders:
    """Adds the headers above to every response, and a cache policy by path."""

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = scope["path"]
        if path.startswith("/assets/"):
            cache = b"public, max-age=31536000, immutable"  # Vite names them by content hash
        elif path.startswith("/bundle/"):
            cache = b"public, max-age=3600"
        else:
            cache = b"no-store"

        async def with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = [h for h in message.get("headers", []) if h[0].lower() != b"cache-control"]
                message["headers"] = [*headers, *SECURITY_HEADERS, (b"cache-control", cache)]
            await send(message)

        await self.app(scope, receive, with_headers)


def build(key: str | None = None, passcode: str | None = None, viewer: Path | None = None,
          replay: Path | None = None, phone: Path | None = None) -> Starlette:
    mcp = match_server.make_server()
    mcp_app = mcp.streamable_http_app()
    viewer = VIEWER_DIR if viewer is None else viewer
    replay = REPLAY_DIR if replay is None else replay
    phone = PHONE_DIR if phone is None else phone

    @contextlib.asynccontextmanager
    async def lifespan(app: Starlette):
        async with mcp.session_manager.run():
            yield

    live = Starlette(routes=[Route("/status", live_status, methods=["GET"])])
    routes = [
        Route("/api/health", health, methods=["GET"]),
        Mount("/api/live", RequireKey(live, passcode, PASSCODE_HEADER, "NINETY_DEMO_PASSCODE", "Live mode")),
        Route("/mcp", RequireKey(mcp_app, key)),
    ]
    # A checkout without a built viewer, phone or Replay bundle still serves the API. The image has
    # the viewer and the bundle (Dockerfile), and the live smoke test fails if either is missing.
    if phone.is_dir():
        # /phone without the slash would fall through to the viewer's mount at /; send it home.
        routes.append(Route("/phone", lambda request: RedirectResponse("/phone/", status_code=308)))
        routes.append(Mount("/phone", StaticFiles(directory=phone, html=True)))
    if replay.is_dir():
        routes.append(Mount("/bundle", StaticFiles(directory=replay)))
    if viewer.is_dir():
        routes.append(Mount("/", StaticFiles(directory=viewer, html=True)))
    app = Starlette(routes=routes, lifespan=lifespan)
    app.add_middleware(SecurityHeaders)
    return app


app = build()
