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

## Algorithms adapted, not dependencies

`ninety/sim/fmath.py` reimplements, in our own Python, the algorithms and polynomial coefficients
of fdlibm's `e_exp.c`, `e_log.c`, `k_sin.c`, `k_cos.c`, `s_atan.c` and `e_atan2.c`. fdlibm's
notice, which its terms ask us to keep:

> Copyright (C) 1993 by Sun Microsystems, Inc. All rights reserved.
> Developed at SunPro, a Sun Microsystems, Inc. business.
> Permission to use, copy, modify, and distribute this software is freely granted, provided that
> this notice is preserved.
