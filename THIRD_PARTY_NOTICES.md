# Third-party notices

The Ninety Labs is MIT licensed. It depends on the open-source packages below, each under a
permissive licence (MIT, Apache-2.0 or BSD). Add a row when you add a dependency; the
licence must be one of those three (see `AGENTS.md`).

| Package | Used for | Licence |
|---|---|---|
| agent-framework-core, agent-framework-foundry | agents and workflow | MIT |
| azure-identity | keyless Entra authentication | MIT |
| azure-ai-projects | publishing agents to Microsoft Foundry | MIT |
| azure-monitor-opentelemetry | agent traces to Application Insights and Foundry; brings OpenTelemetry (Apache-2.0), psutil (BSD-3-Clause), wrapt (BSD-2-Clause) and, through msrest, requests-oauthlib (ISC) | MIT |
| httpx | Azure AI Speech REST calls | BSD-3-Clause |
| jsonschema | data contract validation | MIT |
| azure-storage-blob (`render-job` group) | render job uploads clips to Blob Storage | MIT |
| mcp | MCP server and client | MIT |
| a2a-sdk (with its `http-server` extra) | the Personalizer's A2A server and client (`ninety/personalizer`); brings google-api-core, google-auth, googleapis-common-protos and proto-plus (Apache-2.0), protobuf (BSD-3-Clause), json-rpc (MIT), pyasn1 (BSD-2-Clause) and pyasn1-modules (BSD) | Apache-2.0 |
| starlette, uvicorn | the public API (`ninety/api`) | BSD-3-Clause |
| pydantic (via agent-framework) | typed agent output | MIT |
| pytest, pytest-xdist and its execnet, ruff (development) | tests (in parallel workers) and lint | MIT |
| uv (container build only) | installs `uv.lock` into the API image | MIT or Apache-2.0 |

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
| rfdetr 1.11.2 (with its `train` extra), RF-DETR Small weights | object detection and fine-tuning | Apache-2.0 |
| torch, torchvision | neural network runtime | BSD-3-Clause |
| transformers, huggingface-hub, tokenizers, safetensors, hf-xet | model backbone and weight loading | Apache-2.0 |
| supervision | detection utilities | MIT |
| pydeprecate, requests, cuda-bindings, cuda-pathfinder | rfdetr and torch internals | Apache-2.0 |
| python-dateutil | matplotlib | Apache-2.0 or BSD-3-Clause |
| numpy, scipy, sympy, mpmath, networkx, fsspec, jinja2, markupsafe, contourpy, cycler, kiwisolver, pygments | numerics and torch internals | BSD |
| triton, typer, rich, markdown-it-py, mdurl, annotated-doc, filelock, pyparsing, fonttools, six, setuptools | torch (Linux) and CLI internals | MIT |
| pytorch-lightning, lightning-utilities, torchmetrics, peft, accelerate (rfdetr `train` extra) | the training loop | Apache-2.0 |
| faster-coco-eval, torch-hungarian, pyarrow, requests-toolbelt (rfdetr `train` extra) | COCO evaluation, matching, data loading | Apache-2.0 |
| opencv-python-headless (rfdetr `train` extra) | image decoding in training | Apache-2.0; its wheels bundle FFmpeg (LGPL-2.1), used unmodified |
| roboflow (rfdetr `train` extra) | not used: a client for Roboflow's hosted service, imported by rfdetr; we never call it and send no data to it | Apache-2.0 |
| pycocotools, ultrafast-pycocotools, psutil | COCO metrics, system info | BSD |
| hotcoco, simplejpeg, filetype, pillow-avif-plugin | COCO evaluation, JPEG decoding, file types | MIT |
| vernier | rfdetr training internals | MIT OR Apache-2.0 |

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
