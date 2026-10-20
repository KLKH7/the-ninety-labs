# The API image (ninety/api), deployed to Azure Container Apps by `azd deploy api`.
# Dependencies come from uv.lock, so the image runs exactly what CI tested.
# Container Apps runs linux/amd64 only. The platform is pinned here, not left to the builder:
# Docker's legacy builder on an Apple-silicon Mac reused a cached arm64 base under an amd64 label,
# and the app failed in Azure with "exec format error".
FROM --platform=linux/amd64 ghcr.io/astral-sh/uv:0.12.23 AS uv
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

ARG NINETY_COMMIT=unknown
ENV NINETY_COMMIT=${NINETY_COMMIT} PATH="/app/.venv/bin:${PATH}"

RUN useradd --uid 10001 --no-create-home app
USER app

EXPOSE 8000
CMD ["uvicorn", "ninety.api.app:app", "--host", "0.0.0.0", "--port", "8000", "--no-server-header"]
