# The demo image: the API (ninety/api), the match MCP server, the viewer (web/viewer), the phone
# companion (web/phone) and the Replay bundle the viewer plays, deployed to Azure Container Apps by `azd deploy api` (or `azd up`).
# Dependencies come from uv.lock and the package-lock.json files, so the image runs what CI tested.
# Container Apps runs linux/amd64 only. The platform is pinned here, not left to the builder:
# Docker's legacy builder on an Apple-silicon Mac reused a cached arm64 base under an amd64 label,
# and the app failed in Azure with "exec format error".
FROM --platform=linux/amd64 ghcr.io/astral-sh/uv:0.12.23 AS uv

# The viewer: static files only, so the build machine's architecture does not matter.
FROM node:22.21.1-slim AS viewer
WORKDIR /viewer
COPY web/viewer/package.json web/viewer/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/viewer ./
RUN npm run build

# The phone companion (web/phone), served at /phone/ on the viewer's origin. `npm run build` is the
# production bundle only: the mock feed and the mock laptop page never reach it (vite.config.ts).
FROM node:22.21.1-slim AS phone
WORKDIR /phone
COPY web/phone/package.json web/phone/package-lock.json ./
RUN npm ci --no-audit --no-fund
# The phone imports the viewer's radar, match, speech and club modules (../../viewer/src from /phone).
COPY web/viewer/src /viewer/src
COPY web/phone ./
RUN npm run build && test -f dist/index.html && test ! -e dist/mock-laptop.html

FROM --platform=linux/amd64 python:3.12-slim

COPY --from=uv /uv /usr/local/bin/uv

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_NO_DEV=1

# Dependencies first, so a code-only change reuses this layer.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --locked --no-install-project

COPY ninety ./ninety
RUN uv sync --locked
# Read by the code at run time: the event schema (ninety/match/detected.py) and the detected events
# the MCP server serves for the M1 clip. .dockerignore keeps the rest of tests/ out.
COPY schemas ./schemas
# The whole folder, which .dockerignore narrows to the detected events and, once committed, the
# tracked positions the phone companion serves (ninety/match/tracking.py): a COPY glob that
# matches no file fails the build, and the tracked file does not exist yet.
COPY tests/fixtures/ ./tests/fixtures/

# The matches the MCP server serves, simulated now so a tool call is a lookup, never a simulation
# (Foundry gives an MCP call 100 s; one simulation takes longer than that on a quarter CPU).
ENV NINETY_MATCH_DIR=/app/matches
# The phone companion's frames are written beside them; a missing one would make a request simulate.
RUN uv run --no-sync python -m ninety.mcp.match_server --precompute /app/matches \
    && uv run --no-sync python -c "from ninety.mcp import match_server as m; \
[m.events_of(k) for k in (*m.DETECTED, *m.MATCHES)]" \
    && uv run --no-sync python -c "import pathlib; from ninety.mcp import match_server as m; \
assert all((pathlib.Path(m.MATCH_DIR) / 'frames' / f'{k}.json').exists() for k in m.MATCHES)"

# Replay mode: one clip already through the whole chain (ninety-e2e), packed by infra/replay.py and
# published as a release asset. Refused unless its bytes match the pinned hash, so a changed or
# replaced asset fails the build instead of reaching the demo. A new bundle changes both lines.
ARG REPLAY_URL=https://github.com/KLKH7/the-ninety-labs/releases/download/replay-seed900001-0f101db/replay.tar.gz
ARG REPLAY_SHA256=a5591d2666949076e5e81ccae616ca478c299067824dd46417a208d61e4fa9b9
ENV NINETY_REPLAY_DIR=/app/replay NINETY_VIEWER_DIR=/app/viewer NINETY_PHONE_DIR=/app/phone
# infra/replay.py unpack checks the hash, then the same allow-list pack applied (no answer-key file).
COPY infra/replay.py /tmp/replay.py
RUN python -c "import sys,urllib.request as u; open(sys.argv[2], 'wb').write(u.urlopen(sys.argv[1], timeout=120).read())" \
    "$REPLAY_URL" /tmp/replay.tar.gz \
    && python /tmp/replay.py unpack /tmp/replay.tar.gz /app/replay "$REPLAY_SHA256" \
    && test -f /app/replay/manifest.json && rm /tmp/replay.tar.gz /tmp/replay.py
COPY --from=viewer /viewer/dist /app/viewer
COPY --from=phone /phone/dist /app/phone

ARG NINETY_COMMIT=unknown
ENV NINETY_COMMIT=${NINETY_COMMIT} PATH="/app/.venv/bin:${PATH}"

RUN useradd --uid 10001 --no-create-home app
USER app

EXPOSE 8000
CMD ["uvicorn", "ninety.api.app:app", "--host", "0.0.0.0", "--port", "8000", "--no-server-header"]
