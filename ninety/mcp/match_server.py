"""Read-only MCP server exposing the match to agents.

Agents never see raw files or the ground-truth log directly: they query typed, compact events
through these tools. Run it over stdio:

    uv run python -m ninety.mcp.match_server
"""

import os

from mcp.server.fastmcp import FastMCP

from ninety.match.facts import AGENT_TYPES, events_in

SEED = int(os.environ.get("NINETY_SEED", "7"))
MINUTES = float(os.environ.get("NINETY_MINUTES", "5"))

server = FastMCP("ninety-match")


@server.tool()
def list_events(minute_from: int, minute_to: int, event_type: str | None = None) -> list[dict]:
    """Events between two match minutes (inclusive), oldest first. Optionally one type:
    pass, shot, goal, tackle, interception or pressure. Each event has id, clock, minute, second,
    type, team, player, and where relevant receiver, outcome, ball_speed_kmh and distance_m."""
    types = (event_type,) if event_type in AGENT_TYPES else AGENT_TYPES
    return events_in(SEED, MINUTES, minute_from, minute_to, types)[:60]


@server.tool()
def match_info() -> dict:
    """The match being analysed: seed, length in minutes and the event types available."""
    return {"seed": SEED, "minutes": MINUTES, "event_types": list(AGENT_TYPES)}


if __name__ == "__main__":
    server.run()
