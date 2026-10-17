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

## Vision group (`uv sync --group vision`)

The detector's dependencies are in the optional `vision` group, so `uv sync` and CI do not
download PyTorch. rfdetr is pinned to one exact version; we use only RF-DETR Small, whose weights
are Apache-2.0. The PML-1.0 sizes (Atto, Femto, Pico, XL, 2XL) live in `rfdetr_plus`, which we
never install (it comes only with the `rfdetr[plus]` extra).

| Package | Used for | Licence |
|---|---|---|
| rfdetr 1.11.2, RF-DETR Small weights | object detection | Apache-2.0 |
| torch, torchvision | neural network runtime | BSD-3-Clause |
| transformers, huggingface-hub, tokenizers, safetensors, hf-xet | model backbone and weight loading | Apache-2.0 |
| supervision | detection utilities | MIT |
| pydeprecate, requests, cuda-bindings, cuda-pathfinder | rfdetr and torch internals | Apache-2.0 |
| python-dateutil | matplotlib | Apache-2.0 or BSD-3-Clause |
| numpy, scipy, sympy, mpmath, networkx, fsspec, jinja2, markupsafe, contourpy, cycler, kiwisolver, pygments | numerics and torch internals | BSD |
| triton, typer, rich, markdown-it-py, mdurl, annotated-doc, filelock, pyparsing, fonttools, six, setuptools | torch (Linux) and CLI internals | MIT |

These come in with the vision group under other permissive licences, outside the three named
above. None is copyleft for our code; they are listed so nothing is hidden.

| Package | Pulled in by | Licence |
|---|---|---|
| tqdm | rfdetr, transformers | MPL-2.0 AND MIT |
| matplotlib, defusedxml | supervision | PSF |
| pillow | supervision, torchvision | MIT-CMU |
| shellingham | typer | ISC |
| av | supervision | BSD-3-Clause; its wheels bundle FFmpeg (LGPL-2.1), used unmodified |
| nvidia-* CUDA libraries, cuda-toolkit (Linux only) | torch | NVIDIA proprietary, free to redistribute |

## Algorithms adapted, not dependencies

`ninety/sim/fmath.py` reimplements, in our own Python, the algorithms and polynomial coefficients
of fdlibm's `e_exp.c`, `e_log.c`, `k_sin.c`, `k_cos.c`, `s_atan.c` and `e_atan2.c`. fdlibm's
notice, which its terms ask us to keep:

> Copyright (C) 1993 by Sun Microsystems, Inc. All rights reserved.
> Developed at SunPro, a Sun Microsystems, Inc. business.
> Permission to use, copy, modify, and distribute this software is freely granted, provided that
> this notice is preserved.
