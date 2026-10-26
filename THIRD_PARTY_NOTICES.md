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
| a2a-sdk (with its `http-server` extra) | the Personalizer's A2A server and client (`ninety/personalizer`); brings google-api-core, google-auth, googleapis-common-protos and proto-plus (Apache-2.0), protobuf (BSD-3-Clause), json-rpc (MIT), pyasn1 (BSD-2-Clause), pyasn1-modules (BSD) and, before Python 3.13, culsans and aiologic (ISC) | Apache-2.0 |
| starlette, uvicorn | the public API (`ninety/api`) | BSD-3-Clause |
| websockets | the WebSocket protocol for uvicorn, which serves the phone relay (`ninety/api/companion.py`) | BSD-3-Clause |
| pydantic (via agent-framework) | typed agent output | MIT |
| pytest, pytest-xdist and its execnet, ruff (development) | tests (in parallel workers) and lint | MIT |
| numpy (development; also with the vision group) | the camera fit of event detection, tested in CI | BSD-3-Clause |
| pillow (development; also with the vision group) | images for event detection's runtime truth guard, tested in CI | MIT-CMU |
| uv (container build only) | installs `uv.lock` into the API image | MIT or Apache-2.0 |

## Viewer and phone companion (`web/viewer`, `web/phone`)

The viewer and the phone ship as plain HTML, CSS and JavaScript. Two packages reach a page: in the
viewer, qrcode-generator, which draws the pairing QR code; in the phone, Ionic's web components
(@ionic/core, pinned exactly in `web/phone/package.json`), its view layer in iOS mode, with what
they bring into the bundle (ionicons, the Stencil runtime, tslib). The rest build them, and none
reaches a page. Pinned in `web/viewer/package-lock.json` and `web/phone/package-lock.json`.

| Package | Used for | Licence |
|---|---|---|
| qrcode-generator 2.0.4 (viewer, in the page) | the QR code of the phone's address | MIT |
| @ionic/core 9.0.6 (phone, in the page) | tabs, headers, segments, lists, sheets: the phone's view layer | MIT |
| ionicons 8.1.0 (through @ionic/core, in the page) | the icon component Ionic loads | MIT |
| @stencil/core 4.45.2 (through @ionic/core, its runtime in the page) | the runtime of Ionic's web components | MIT |
| tslib 2.8.1 (through @ionic/core, in the page) | TypeScript helpers | 0BSD |
| vite 6.4.4, and through it esbuild, rollup, postcss, nanoid and 57 more | dev server and build | MIT |
| typescript 5.9.3 | type checking | Apache-2.0 |
| @types/node | types for the build config | MIT |
| source-map-js (through vite) | source maps | BSD-3-Clause |
| picocolors (through vite) | coloured terminal output | ISC |

## Sound

The referee's whistle on the broadcast's mp4 is synthesised by our own code
(`ninety/render/audio.py`: a tone with a flutter, generated sample by sample with the Python
standard library). No recording or third-party sound is used, so there is nothing to license.

## Data

| Data | Used for | Source and terms |
|---|---|---|
| `ninety/sim/data/expected_threat_12x8.json` | what having the ball in each area is worth (GROUNDING D9) | Expected Threat grid by Karun Singh, file open_xt_12x8_v1 (karun.in). Its licence is not stated: *verify* before release, or replace it with a grid measured from open event data |

## Vision group (`uv sync --group vision`)

The detector's dependencies are in the optional `vision` group, so `uv sync` and CI do not
download PyTorch. rfdetr is pinned to one exact version; we use only RF-DETR Small, whose weights
are Apache-2.0. The PML-1.0 sizes (Atto, Femto, Pico, XL, 2XL) live in `rfdetr_plus`, which we
never install (it comes only with the `rfdetr[plus]` extra).

The live detection image (`infra/live-job.Dockerfile`) installs this group as locked, except
torch and torchvision, which it takes as PyTorch's CPU builds of the same versions (BSD-3-Clause,
from download.pytorch.org, pinned by sha256). On Linux the locked torch also pulls NVIDIA's CUDA
libraries (`nvidia-*`, `cuda-toolkit`), which are under NVIDIA's own licence, not one on our list;
the image leaves every one of them out, and a test fails if the lock gains one it does not.

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

All 193 packages in `uv.lock`, with the licence their published metadata gives, written
one way per licence. Ten publish no licence on PyPI; how each was checked from its wheel is in
[Packages that publish no licence](#packages-that-publish-no-licence). The NVIDIA wheels (free to
redistribute) are Linux only and come in with PyTorch in the `vision` group.
`tests/test_third_party_notices.py` fails if a locked package is missing here or a licence is
outside the rule in `AGENTS.md`.

| Package | Version | Licence |
|---|---|---|
| a2a-sdk | 1.2.3 | Apache-2.0 |
| accelerate | 1.15.0 | Apache-2.0 |
| agent-framework-core | 1.21.0 | MIT |
| agent-framework-foundry | 1.14.1 | MIT |
| agent-framework-openai | 1.16.0 | MIT |
| aiohappyeyeballs | 2.7.1 | PSF-2.0 |
| aiohttp | 3.14.5 | Apache-2.0 AND MIT |
| aiologic | 0.17.1 | ISC |
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
| culsans | 0.11.0 | ISC |
| cycler | 0.12.1 | BSD |
| defusedxml | 0.7.1 | PSF-2.0 |
| execnet | 2.1.2 | MIT |
| faster-coco-eval | 1.8.0 | Apache-2.0 |
| filelock | 4.2.0 | MIT |
| filetype | 1.2.0 | MIT |
| fonttools | 4.67.0 | MIT |
| frozenlist | 1.8.0 | Apache-2.0 |
| fsspec | 2026.9.0 | BSD-3-Clause |
| google-api-core | 2.42.0 | Apache-2.0 |
| google-auth | 2.62.0 | Apache-2.0 |
| googleapis-common-protos | 1.75.5 | Apache-2.0 |
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
| json-rpc | 1.15.0 | MIT |
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
| proto-plus | 1.29.0 | Apache-2.0 |
| protobuf | 7.36.2 | BSD-3-Clause |
| psutil | 7.2.2 | BSD-3-Clause |
| pyarrow | 26.0.0 | Apache-2.0 |
| pyasn1 | 0.6.4 | BSD-2-Clause |
| pyasn1-modules | 0.4.2 | BSD |
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
| pytest-xdist | 3.8.0 | MIT |
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
| websockets | 17.3 | BSD-3-Clause |
| wrapt | 2.5.1 | BSD-2-Clause |
| yarl | 1.25.1 | Apache-2.0 |

## Packages that publish no licence

Ten of the packages above publish no licence on PyPI (no licence expression, field or classifier,
checked against PyPI's metadata for the locked version on 2026-10-19), so each was read from the
locked wheel itself, its metadata and its bundled licence file:

| Package | What the wheel says | Recorded as |
|---|---|---|
| azure-core, azure-core-tracing-opentelemetry | `License-Expression: MIT`; LICENSE is Microsoft's MIT licence | MIT |
| playwright | `License-Expression: Apache-2.0`; LICENSE is Apache 2.0 | Apache-2.0 |
| faster-coco-eval, torch-hungarian | no expression; the bundled LICENSE is Apache 2.0 | Apache-2.0 |
| nvidia-cuda-runtime, nvidia-cudnn-cu13, nvidia-nvshmem-cu13 | `License-Expression: LicenseRef-NVIDIA-Proprietary`; License.txt is NVIDIA's licence agreement | NVIDIA proprietary |
| nvidia-nccl-cu13 | `License-Expression: LicenseRef-NVIDIA-Proprietary`, though its License.txt is a BSD-style notice | NVIDIA proprietary (the metadata, the stricter of the two) |
| cuda-toolkit | a 2.5 KB meta-package with no code, no licence field and no licence file; it only requires the NVIDIA libraries | NVIDIA proprietary, with the libraries it installs |

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

## Tools run, not shipped

Programs the producer runs on their own machine to make a bundle. No code of theirs is in the repo,
a wheel, the container image or a bundle; only their output is.

| Tool | What for | Licence | Why it is allowed |
|---|---|---|---|
| ffmpeg (the producer's system install, e.g. Homebrew's) | `ninety/footage.py`: encodes the bundle's video.mp4, HLS ladder and highlight clips | that build's licence (Homebrew's is GPL, `--enable-gpl`) | run as an external program on the producer's Mac, never linked or shipped; its output, the video, is not covered by the GPL. The H.264 encoder used is Apple's VideoToolbox (`h264_videotoolbox`, part of macOS), never libx264 (GPL); the AAC encoder is ffmpeg's own (`aac`). This is not the FFmpeg bundled inside `av` or OpenCV's wheels (above) |

The encode is macOS only (VideoToolbox): on Linux, CI and the Azure image, `ninety-e2e` finds no
H.264 encoder and ships JPEG frames. **Open for Kian:** H.264 and AAC are patent-licensed formats
(royalty terms from their patent pools, e.g. for free internet video). Whether distributing our
demo's H.264/AAC video needs anything is a question for Kian, not settled here.

## Algorithms adapted, not dependencies

`ninety/sim/fmath.py` reimplements, in our own Python, the algorithms and polynomial coefficients
of fdlibm's `e_exp.c`, `e_log.c`, `k_sin.c`, `k_cos.c`, `s_atan.c` and `e_atan2.c`. fdlibm's
notice, which its terms ask us to keep:

> Copyright (C) 1993 by Sun Microsystems, Inc. All rights reserved.
> Developed at SunPro, a Sun Microsystems, Inc. business.
> Permission to use, copy, modify, and distribute this software is freely granted, provided that
> this notice is preserved.

The phone companion ports two MIT-licensed UI components to plain TypeScript and CSS (no code of
theirs is installed or bundled as a dependency):

- `web/phone/src/ticker.ts` follows Magic UI's NumberTicker (its spring: stiffness 100, damping 60),
  [magicuidesign/magicui](https://github.com/magicuidesign/magicui), MIT, Copyright (c) Magic UI.
- The `.skeleton` style in `web/phone/src/style.css` follows shadcn/ui's Skeleton (a pulsing
  rounded block), [shadcn-ui/ui](https://github.com/shadcn-ui/ui), MIT, Copyright (c) 2023 shadcn.

> Permission is hereby granted, free of charge, to any person obtaining a copy of this software and
> associated documentation files (the "Software"), to deal in the Software without restriction,
> including without limitation the rights to use, copy, modify, merge, publish, distribute,
> sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is
> furnished to do so, subject to the following conditions: The above copyright notice and this
> permission notice shall be included in all copies or substantial portions of the Software.
> THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND.
