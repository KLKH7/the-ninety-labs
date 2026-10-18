"""Read-only MCP server exposing matches to agents.

Agents never see raw files or the ground-truth log directly: they query typed, compact events
through these tools, naming the match they were asked about. Two transports, the same tools:

    uv run python -m ninety.mcp.match_server                       # stdio, for local agents
    uv run python -m ninety.mcp.match_server --precompute matches/  # write the served matches

Over HTTP it is mounted at /mcp in the API (ninety/api/app.py), where Foundry's published
Analyst calls it with a key (infra/main.bicep). The served matches are a fixed list, simulated
when the image is built: a call never starts a simulation, so it answers in milliseconds and
cannot be used to make the server do expensive work. The simulator gives the same match on every
machine (docs/LESSONS.md, lesson 29), so a precomputed match equals one computed here.
"""

from __future__ import annotations

import argparse
import json
import os
from functools import lru_cache
from pathlib import Path

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from ninety.match.facts import AGENT_TYPES, events_in

MINUTES = 5  # every served match is a five-minute clip, as the slice and the evaluations use
MATCHES = {"seed7": 7, "seed21": 21, "seed33": 33}  # the demo match and the held-out evaluation seeds
MATCH_DIR = os.environ.get("NINETY_MATCH_DIR", "")
MAX_EVENTS = 60
TOOLS = ("list_events", "match_info")  # the published Analyst may call only these (tests check they exist)

def match_id(seed: int) -> str:
    return f"seed{seed}"


@lru_cache(maxsize=len(MATCHES))
def events_of(match: str) -> tuple[dict, ...]:
    if match not in MATCHES:
        raise ValueError(f"unknown match {match!r}; available: {', '.join(MATCHES)}")
    stored = Path(MATCH_DIR) / f"{match}.json" if MATCH_DIR else None
    if stored and stored.exists():
        return tuple(json.loads(stored.read_text()))
    return tuple(events_in(MATCHES[match], MINUTES, 1, MINUTES + 1))


def list_events(match: str, minute_from: int, minute_to: int, event_type: str | None) -> list[dict]:
    """Events of one match between two match minutes (inclusive), oldest first. `match` is the
    match id you were given (for example seed7). Optionally one event_type: pass, shot, goal,
    tackle, interception or pressure; null for all. Each event has id, clock, minute, second,
    type, team, player, and where relevant receiver (completed passes), intended (who a pass was
    for), interceptor (who won it), deflected_by (who only touched it), outcome, ball_speed_kmh
    and distance_m."""
    types = (event_type,) if event_type in AGENT_TYPES else AGENT_TYPES
    rows = [e for e in events_of(match) if minute_from <= e["minute"] <= minute_to and e["type"] in types]
    return rows[:MAX_EVENTS]


def match_info(match: str) -> dict:
    """One match: its id, length in minutes and the event types available."""
    events_of(match)  # refuses an unknown match
    return {"match": match, "minutes": MINUTES, "event_types": list(AGENT_TYPES)}


def make_server() -> FastMCP:
    """A server with the match tools. Stateless with JSON responses: what Foundry's MCP tool needs
    (one request, one answer, no session). The API builds its own, since an HTTP server's session
    manager runs once."""
    server = FastMCP(
        "ninety-match",
        stateless_http=True,
        json_response=True,
        # DNS-rebinding protection guards servers on a user's own machine and accepts only localhost
        # Host headers; ours is public and answers only with the key, so the Host check is off.
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )
    for tool in (list_events, match_info):
        server.add_tool(tool)
    return server


server = make_server()


def precompute(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    for match, seed in MATCHES.items():
        rows = events_in(seed, MINUTES, 1, MINUTES + 1)
        (out / f"{match}.json").write_text(json.dumps(rows, separators=(",", ":")))
        print(f"{match}: {len(rows)} events")


def main() -> None:
    ap = argparse.ArgumentParser(description="The match MCP server (stdio), or precompute its matches.")
    ap.add_argument("--precompute", type=Path, metavar="DIR", help="write every served match to DIR")
    args = ap.parse_args()
    if args.precompute:
        precompute(args.precompute)
    else:
        server.run()


if __name__ == "__main__":
    main()
