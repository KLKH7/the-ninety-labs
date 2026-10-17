# Third-party notices

The Ninety Labs is MIT licensed. It depends on the open-source packages below, each under a
permissive licence (MIT, Apache-2.0 or BSD). Add a row when you add a dependency; the
licence must be one of those three (see `AGENTS.md`).

| Package | Used for | Licence |
|---|---|---|
| agent-framework-core, agent-framework-foundry | agents and workflow | MIT |
| azure-identity | keyless Entra authentication | MIT |
| httpx | Azure AI Speech REST calls | BSD-3-Clause |
| jsonschema | data contract validation | MIT |
| mcp | MCP server and client | MIT |
| pydantic (via agent-framework) | typed agent output | MIT |
| pytest, ruff (development) | tests and lint | MIT |

## Data

| Data | Used for | Source and terms |
|---|---|---|
| `ninety/sim/data/expected_threat_12x8.json` | what having the ball in each area is worth (GROUNDING D9) | Expected Threat grid by Karun Singh, file open_xt_12x8_v1 (karun.in). Its licence is not stated: *verify* before release, or replace it with a grid measured from open event data |

Planned, added when first used: RF-DETR (Apache-2.0 sizes only), supervision (MIT).
