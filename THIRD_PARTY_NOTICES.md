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
| starlette, uvicorn | the public API (`ninety/api`) | BSD-3-Clause |
| pydantic (via agent-framework) | typed agent output | MIT |
| pytest, ruff (development) | tests and lint | MIT |
| uv (container build only) | installs `uv.lock` into the API image | MIT or Apache-2.0 |

Planned, added when first used: RF-DETR (Apache-2.0 sizes only), supervision (MIT).
