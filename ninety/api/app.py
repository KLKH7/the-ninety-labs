"""The public API, served from Azure Container Apps.

Today it has one route, the health check that the deploy workflow's smoke test calls. It reports
the commit the image was built from, so a deploy is only called done when the new revision is the
one answering. Replay and live routes are added with the viewer (docs/PLAN.md).

    uv run uvicorn ninety.api.app:app --port 8000
"""

from __future__ import annotations

import os

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

# Set at image build time (Dockerfile ARG); "dev" when run from a checkout.
COMMIT = os.environ.get("NINETY_COMMIT") or "dev"


async def health(request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok", "commit": COMMIT})


app = Starlette(routes=[Route("/api/health", health, methods=["GET"])])
