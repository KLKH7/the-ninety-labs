# The demo image: the API (ninety/api), the match MCP server, the viewer (web/viewer) and the
# Replay bundle it plays, deployed to Azure Container Apps by `azd deploy api` (or `azd up`).
# Dependencies come from uv.lock and web/viewer/package-lock.json, so the image runs what CI tested.
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
COPY tests/fixtures/detected-*.jsonl ./tests/fixtures/

# The matches the MCP server serves, simulated now so a tool call is a lookup, never a simulation
# (Foundry gives an MCP call 100 s; one simulation takes longer than that on a quarter CPU).
ENV NINETY_MATCH_DIR=/app/matches
RUN uv run --no-sync python -m ninety.mcp.match_server --precompute /app/matches \
    && uv run --no-sync python -c "from ninety.mcp import match_server as m; \
[m.events_of(k) for k in (*m.DETECTED, *m.MATCHES)]"

# Replay mode: one clip already through the whole chain (ninety-e2e), packed by infra/replay.py and
# published as a release asset. Refused unless its bytes match the pinned hash, so a changed or
# replaced asset fails the build instead of reaching the demo. A new bundle changes both lines.
ARG REPLAY_URL=https://github.com/KLKH7/the-ninety-labs/releases/download/replay-seed900001-v1/replay.tar.gz
ARG REPLAY_SHA256=bfd5828b973afd076ef6f571119725f1e9226d0dd522847497e1b1e80aa1af48
ENV NINETY_REPLAY_DIR=/app/replay NINETY_VIEWER_DIR=/app/viewer
RUN python -c "import hashlib,io,sys,tarfile,urllib.request as u; \
d=u.urlopen(sys.argv[1], timeout=120).read(); h=hashlib.sha256(d).hexdigest(); \
h == sys.argv[2] or sys.exit(f'replay bundle sha256 {h}, expected {sys.argv[2]}'); \
tarfile.open(fileobj=io.BytesIO(d)).extractall(sys.argv[3], filter='data')" \
    "$REPLAY_URL" "$REPLAY_SHA256" /app/replay \
    && test -f /app/replay/manifest.json
COPY --from=viewer /viewer/dist /app/viewer

ARG NINETY_COMMIT=unknown
ENV NINETY_COMMIT=${NINETY_COMMIT} PATH="/app/.venv/bin:${PATH}"

RUN useradd --uid 10001 --no-create-home app
USER app

EXPOSE 8000
CMD ["uvicorn", "ninety.api.app:app", "--host", "0.0.0.0", "--port", "8000", "--no-server-header"]
