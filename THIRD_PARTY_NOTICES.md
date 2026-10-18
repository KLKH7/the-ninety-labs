# Third-party notices

The Ninety Labs is MIT licensed. It depends on the open-source packages below, each under a
permissive licence. Add a row when you add a dependency; the licence must be one `AGENTS.md`
allows (permissive or MPL-2.0 unmodified, plus its three narrow exceptions for bundled runtimes; never
GPL or AGPL otherwise). Every locked package and its licence is listed below.

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
| starlette, uvicorn | the public API (`ninety/api`) | BSD-3-Clause |
| pydantic (via agent-framework) | typed agent output | MIT |
| pytest, ruff (development) | tests and lint | MIT |
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

These come in with the vision group under other permissive licences, all within the rule in
`AGENTS.md`. None is copyleft for our code; they are listed so nothing is hidden.

| Package | Pulled in by | Licence |
|---|---|---|
| tqdm | rfdetr, transformers | MPL-2.0 AND MIT |
| matplotlib, defusedxml | supervision | PSF |
| pillow | supervision, torchvision | MIT-CMU |
| shellingham | typer | ISC |
| av | supervision | BSD-3-Clause; its wheels bundle FFmpeg (LGPL-2.1), used unmodified |
| nvidia-* CUDA libraries, cuda-toolkit (Linux only) | torch | NVIDIA proprietary, free to redistribute |

## Every locked dependency

All 179 packages in `uv.lock`, with the licence their published metadata gives, written
one way per licence. Where the metadata gives none, the licence was read from the wheel's
metadata or its bundled licence file: azure-core and azure-core-tracing-opentelemetry (MIT),
playwright (Apache-2.0), faster-coco-eval and torch-hungarian (Apache-2.0), and the NVIDIA wheels
(NVIDIA proprietary, free to redistribute; Linux only, under PyTorch in the `vision` group).
`tests/test_third_party_notices.py` fails if a locked package is missing here or a licence is
outside the rule in `AGENTS.md`.

| Package | Version | Licence |
|---|---|---|
| accelerate | 1.15.0 | Apache-2.0 |
| agent-framework-core | 1.21.0 | MIT |
| agent-framework-foundry | 1.14.1 | MIT |
| agent-framework-openai | 1.16.0 | MIT |
| aiohappyeyeballs | 2.7.1 | PSF-2.0 |
| aiohttp | 3.14.5 | Apache-2.0 AND MIT |
| aiosignal | 1.4.0 | Apache-2.0 |
| annotated-doc | 0.0.5 | MIT |
| annotated-types | 0.8.0 | MIT |
| anyio | 4.15.1 | MIT |
| asgiref | 3.12.1 | BSD-3-Clause |
| attrs | 26.1.0 | MIT |
| av | 18.1.0 | BSD-3-Clause |
| av | 19.0.1 | BSD-3-Clause |
| azure-ai-inference | 1.0.0b9 | MIT |
| azure-ai-projects | 2.7.0 | MIT |
| azure-core | 1.41.0 | MIT |
| azure-core-tracing-opentelemetry | 1.0.0b13 | MIT |
| azure-identity | 1.26.0 | MIT |
| azure-monitor-opentelemetry | 1.8.11 | MIT |
| azure-monitor-opentelemetry-exporter | 1.0.0b58 | MIT |
| azure-storage-blob | 12.31.0 | MIT |
| azure-storage-queue | 12.18.0 | MIT |
| certifi | 2026.7.22 | MPL-2.0 |
| cffi | 2.1.1 | MIT-0 |
| charset-normalizer | 3.5.2 | MIT |
| click | 8.5.0 | BSD-3-Clause |
| colorama | 0.4.6 | BSD |
| contourpy | 1.3.3 | BSD |
| contourpy | 1.4.0 | BSD-3-Clause |
| cryptography | 50.0.2 | Apache-2.0 OR BSD-3-Clause |
| cuda-bindings | 13.4.4 | Apache-2.0 |
| cuda-pathfinder | 1.8.3 | Apache-2.0 |
| cuda-toolkit | 13.0.3.0 | NVIDIA proprietary |
| cycler | 0.12.1 | BSD |
| defusedxml | 0.7.1 | PSF-2.0 |
| faster-coco-eval | 1.8.0 | Apache-2.0 |
| filelock | 4.2.0 | MIT |
| filetype | 1.2.0 | MIT |
| fonttools | 4.67.0 | MIT |
| frozenlist | 1.8.0 | Apache-2.0 |
| fsspec | 2026.9.0 | BSD-3-Clause |
| greenlet | 3.5.6 | MIT AND PSF-2.0 |
| h11 | 0.16.0 | MIT |
| hf-xet | 1.7.0 | Apache-2.0 |
| hotcoco | 1.0.1 | MIT |
| httpcore | 1.0.9 | BSD-3-Clause |
| httpcore2 | 2.13.1 | BSD-3-Clause |
| httpx | 0.28.1 | BSD-3-Clause |
| httpx-sse | 0.4.3 | MIT |
| httpx2 | 2.13.1 | BSD-3-Clause |
| httpx2-jsfetch | 1.0 | BSD-3-Clause |
| huggingface-hub | 2.2.0 | Apache-2.0 |
| idna | 3.20 | BSD-3-Clause |
| iniconfig | 2.3.1 | MIT |
| isodate | 0.7.2 | BSD |
| jinja2 | 3.1.6 | BSD |
| jiter | 0.17.0 | MIT |
| jsonschema | 4.26.0 | MIT |
| jsonschema-specifications | 2025.9.1 | MIT |
| kiwisolver | 1.5.1 | BSD |
| lightning-utilities | 0.15.3 | Apache-2.0 |
| markdown-it-py | 4.2.0 | MIT |
| markupsafe | 3.0.4 | BSD-3-Clause |
| matplotlib | 3.11.2 | PSF-2.0 |
| mcp | 1.30.0 | MIT |
| mdurl | 0.1.2 | MIT |
| mpmath | 1.3.0 | BSD |
| msal | 1.39.0 | MIT |
| msal-extensions | 1.3.1 | MIT |
| msgspec | 0.22.0 | BSD-3-Clause |
| msrest | 0.7.1 | MIT |
| multidict | 7.1.0 | Apache-2.0 |
| networkx | 3.6.1 | BSD-3-Clause |
| networkx | 3.7 | BSD-3-Clause |
| numpy | 2.4.6 | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 |
| numpy | 2.5.4 | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 |
| nvidia-cublas | 13.1.1.3 | NVIDIA proprietary |
| nvidia-cuda-cupti | 13.0.85 | NVIDIA proprietary |
| nvidia-cuda-nvrtc | 13.0.88 | NVIDIA proprietary |
| nvidia-cuda-runtime | 13.0.96 | NVIDIA proprietary |
| nvidia-cudnn-cu13 | 9.24.0.43 | NVIDIA proprietary |
| nvidia-cufft | 12.0.0.61 | NVIDIA proprietary |
| nvidia-cufile | 1.15.1.6 | NVIDIA proprietary |
| nvidia-curand | 10.4.0.35 | NVIDIA proprietary |
| nvidia-cusolver | 12.0.4.66 | NVIDIA proprietary |
| nvidia-cusparse | 12.6.3.3 | NVIDIA proprietary |
| nvidia-cusparselt-cu13 | 0.8.1 | NVIDIA proprietary |
| nvidia-nccl-cu13 | 2.30.7 | NVIDIA proprietary |
| nvidia-nvjitlink | 13.4.92 | NVIDIA proprietary |
| nvidia-nvshmem-cu13 | 3.4.5 | NVIDIA proprietary |
| nvidia-nvtx | 13.0.85 | Apache-2.0 |
| oauthlib | 4.0.0 | BSD-3-Clause |
| openai | 3.29.0 | Apache-2.0 |
| opencv-python-headless | 5.0.0.93 | Apache-2.0 |
| opentelemetry-api | 1.45.1 | Apache-2.0 |
| opentelemetry-instrumentation | 0.66b1 | Apache-2.0 |
| opentelemetry-instrumentation-asgi | 0.66b1 | Apache-2.0 |
| opentelemetry-instrumentation-dbapi | 0.66b1 | Apache-2.0 |
| opentelemetry-instrumentation-django | 0.66b1 | Apache-2.0 |
| opentelemetry-instrumentation-fastapi | 0.66b1 | Apache-2.0 |
| opentelemetry-instrumentation-flask | 0.66b1 | Apache-2.0 |
| opentelemetry-instrumentation-httpx | 0.66b1 | Apache-2.0 |
| opentelemetry-instrumentation-logging | 0.66b1 | Apache-2.0 |
| opentelemetry-instrumentation-psycopg2 | 0.66b1 | Apache-2.0 |
| opentelemetry-instrumentation-requests | 0.66b1 | Apache-2.0 |
| opentelemetry-instrumentation-urllib | 0.66b1 | Apache-2.0 |
| opentelemetry-instrumentation-urllib3 | 0.66b1 | Apache-2.0 |
| opentelemetry-instrumentation-wsgi | 0.66b1 | Apache-2.0 |
| opentelemetry-resource-detector-azure | 0.3.0 | Apache-2.0 |
| opentelemetry-sdk | 1.45.1 | Apache-2.0 |
| opentelemetry-semantic-conventions | 0.66b1 | Apache-2.0 |
| opentelemetry-util-http | 0.66b1 | Apache-2.0 |
| packaging | 26.3 | Apache-2.0 OR BSD-2-Clause |
| peft | 0.21.2 | Apache-2.0 |
| pillow | 13.0.0 | MIT-CMU |
| pillow-avif-plugin | 1.6.0 | MIT |
| playwright | 1.56.0 | Apache-2.0 |
| pluggy | 1.6.0 | MIT |
| propcache | 0.5.4 | Apache-2.0 |
| psutil | 7.2.2 | BSD-3-Clause |
| pyarrow | 26.0.0 | Apache-2.0 |
| pycocotools | 2.0.11 | BSD-2-Clause |
| pycparser | 3.11 | BSD-3-Clause |
| pydantic | 2.14.1 | MIT |
| pydantic-core | 2.50.1 | MIT |
| pydantic-settings | 2.15.0 | MIT |
| pydeprecate | 0.9.0 | Apache-2.0 |
| pyee | 13.0.1 | MIT |
| pygments | 2.21.0 | BSD-2-Clause |
| pyjwt | 2.15.1 | MIT |
| pyparsing | 3.3.3 | MIT |
| pytest | 9.1.1 | MIT |
| python-dateutil | 2.9.0.post0 | Apache-2.0 OR BSD-3-Clause |
| python-dotenv | 1.2.4 | BSD-3-Clause |
| python-multipart | 0.0.32 | Apache-2.0 |
| pytorch-lightning | 2.6.6 | Apache-2.0 |
| pywin32 | 312 | PSF-2.0 |
| pyyaml | 6.0.3 | MIT |
| referencing | 0.37.0 | MIT |
| regex | 2026.9.29 | Apache-2.0 AND CNRI-Python |
| requests | 2.34.2 | Apache-2.0 |
| requests-oauthlib | 2.0.0 | ISC |
| requests-toolbelt | 1.0.0 | Apache-2.0 |
| rfdetr | 1.11.2 | Apache-2.0 |
| rich | 15.0.0 | MIT |
| roboflow | 1.7.1 | Apache-2.0 |
| rpds-py | 2026.9.1 | MIT |
| ruff | 0.17.0 | MIT |
| safetensors | 0.8.0 | Apache-2.0 |
| scipy | 1.17.1 | BSD |
| scipy | 1.18.1 | BSD |
| setuptools | 84.0.0 | MIT |
| shellingham | 1.5.4 | ISC |
| simplejpeg | 1.9.0 | MIT |
| six | 1.17.0 | MIT |
| sniffio | 1.3.1 | MIT OR Apache-2.0 |
| sse-starlette | 3.5.0 | BSD-3-Clause |
| starlette | 1.8.0 | BSD-3-Clause |
| supervision | 0.31.0 | MIT |
| sympy | 1.14.0 | BSD |
| tokenizers | 0.23.3 | Apache-2.0 |
| torch | 2.14.1 | Apache-2.0 AND Apache-2.0 WITH LLVM-exception AND BSD-2-Clause AND BSD-3-Clause AND BSL-1.0 AND MIT |
| torch-hungarian | 0.1.0rc0 | Apache-2.0 |
| torchmetrics | 1.8.2 | Apache-2.0 |
| torchvision | 0.29.1 | BSD |
| tqdm | 4.70.1 | MPL-2.0 AND MIT |
| transformers | 5.20.1 | Apache-2.0 |
| triton | 3.8.0 | MIT |
| truststore | 0.10.5 | MIT |
| typer | 0.25.1 | MIT |
| typing-extensions | 4.16.0 | PSF-2.0 |
| typing-inspection | 0.4.4 | MIT |
| ultrafast-pycocotools | 0.1.14 | BSD-2-Clause |
| urllib3 | 2.8.0 | MIT |
| uvicorn | 0.54.0 | BSD-3-Clause |
| vernier | 0.5.4 | MIT OR Apache-2.0 |
| wrapt | 2.5.1 | BSD-2-Clause |
| yarl | 1.25.1 | Apache-2.0 |

## Bundled inside dependencies' wheels

Code another package ships inside its own wheel, unmodified. Each is one of the narrow exceptions
in `AGENTS.md`.

| Component | Inside | Licence | Why it is allowed |
|---|---|---|---|
| FreeType | matplotlib | FTL OR GPL-2.0-or-later | dual licence, taken under the FTL (BSD-style, with credit) |
| libgfortran, libgcc (GCC runtime) | numpy, scipy | GPL-3.0-or-later WITH GCC-exception-3.1 | the GCC Runtime Library Exception lets non-GPL programs use it |
| libquadmath | scipy | LGPL-2.1-or-later | LGPL, bundled unmodified and dynamically linked |
| FFmpeg | av, opencv-python-headless | LGPL-2.1-or-later | LGPL, bundled unmodified and dynamically linked |
| NVIDIA CUDA libraries | torch (Linux, `vision` group) | NVIDIA proprietary | redistributable runtime, optional group only |

## Algorithms adapted, not dependencies

`ninety/sim/fmath.py` reimplements, in our own Python, the algorithms and polynomial coefficients
of fdlibm's `e_exp.c`, `e_log.c`, `k_sin.c`, `k_cos.c`, `s_atan.c` and `e_atan2.c`. fdlibm's
notice, which its terms ask us to keep:

> Copyright (C) 1993 by Sun Microsystems, Inc. All rights reserved.
> Developed at SunPro, a Sun Microsystems, Inc. business.
> Permission to use, copy, modify, and distribute this software is freely granted, provided that
> this notice is preserved.
