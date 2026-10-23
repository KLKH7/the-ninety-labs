# The live detection image: ninety/vision/live_job.py on one clip, on CPU, in the Container Apps
# job of infra/live-job.bicep. Built from the repo root (infra/live-job.sh build):
#
#   docker buildx build --platform linux/amd64 -f infra/live-job.Dockerfile \
#     --build-arg CHECKPOINT=<name in its train-manifest.json> --build-arg NINETY_COMMIT=$(git rev-parse HEAD) -t <tag> .
#
# The clip and the checkpoint are inputs, staged by infra/live-job.sh stage in runs/live-input/
# (gitignored): the clip as `clip/` (index.jsonl and images/ only) and the checkpoint as
# `checkpoint/` (the weights and the train-manifest.json they were trained with). The build runs
# the job's own checks on both, so an image whose clip carries the answer key, or whose weights do
# not match their record, is never made. A new clip or checkpoint is a new build, not new code.
#
# Dependencies are the vision group of uv.lock, hash-checked, except torch and torchvision, which
# come as PyTorch's CPU builds at the locked versions, pinned by sha256. The locked Linux builds
# pull NVIDIA's CUDA libraries (allowed in the vision group, AGENTS.md), which a CPU job never uses
# and which would make the image several GB larger; none of them is installed here. rfdetr is the
# pinned version,
# and only RF-DETR Small is loaded (ninety/vision/model.py).
# Container Apps runs linux/amd64 only; the platform is pinned as in the API's Dockerfile.
FROM --platform=linux/amd64 ghcr.io/astral-sh/uv:0.12.23 AS uv
FROM --platform=linux/amd64 python:3.12-slim

COPY --from=uv /uv /usr/local/bin/uv

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy VIRTUAL_ENV=/app/.venv PATH="/app/.venv/bin:${PATH}" \
    PYTHONPATH=/app

COPY pyproject.toml uv.lock README.md ./
# Everything torch's CUDA build brings is left out by name; the rest installs exactly as locked.
RUN uv export --frozen --no-dev --group vision --no-emit-project \
      --no-emit-package torch --no-emit-package torchvision --no-emit-package triton \
      --no-emit-package cuda-bindings --no-emit-package cuda-pathfinder --no-emit-package cuda-toolkit \
      --no-emit-package nvidia-cublas --no-emit-package nvidia-cuda-cupti \
      --no-emit-package nvidia-cuda-nvrtc --no-emit-package nvidia-cuda-runtime \
      --no-emit-package nvidia-cudnn-cu13 --no-emit-package nvidia-cufft --no-emit-package nvidia-cufile \
      --no-emit-package nvidia-curand --no-emit-package nvidia-cusolver --no-emit-package nvidia-cusparse \
      --no-emit-package nvidia-cusparselt-cu13 --no-emit-package nvidia-nccl-cu13 \
      --no-emit-package nvidia-nvjitlink --no-emit-package nvidia-nvshmem-cu13 --no-emit-package nvidia-nvtx \
      -o /tmp/locked.txt \
    && ! grep -iE '^(nvidia|cuda|triton|torch)' /tmp/locked.txt \
    && printf '%s\n' \
      'torch @ https://download.pytorch.org/whl/cpu/torch-2.14.1%2Bcpu-cp312-cp312-manylinux_2_28_x86_64.whl --hash=sha256:5a6363570c753812540a05eb82380e329469cbe668643e88111414c12627711f' \
      'torchvision @ https://download.pytorch.org/whl/cpu/torchvision-0.29.1%2Bcpu-cp312-cp312-manylinux_2_28_x86_64.whl --hash=sha256:ef220d4b21878c58947851beb7337382897159105f012f0c9c07bf7e84174d7e' \
      > /tmp/torch-cpu.txt \
    && uv venv /app/.venv \
    && uv pip install --require-hashes --no-deps -r /tmp/locked.txt -r /tmp/torch-cpu.txt \
    && ! uv pip list | grep -iE '^(nvidia|cuda|triton)' \
    && rm /tmp/locked.txt /tmp/torch-cpu.txt

COPY ninety ./ninety

ARG CLIP_DIR=runs/live-input/clip
ARG CHECKPOINT_DIR=runs/live-input/checkpoint
ARG CHECKPOINT
COPY ${CLIP_DIR}/ /data/clip/
COPY ${CHECKPOINT_DIR}/ /data/checkpoint/
RUN test -n "${CHECKPOINT}" || { echo "pass --build-arg CHECKPOINT=<name in train-manifest.json>"; exit 1; } \
    && python -c "import sys; from pathlib import Path; from ninety.vision import live_job as j; \
j.check_input(Path('/data/clip')); \
j.verify_checkpoint(Path('/data/checkpoint/checkpoint_best_total.pth'), sys.argv[1])" "${CHECKPOINT}"

ARG NINETY_COMMIT=unknown
ENV NINETY_COMMIT=${NINETY_COMMIT} NINETY_CHECKPOINT=${CHECKPOINT}

RUN useradd --uid 10001 --no-create-home app
USER app

CMD ["sh", "-c", "exec python -m ninety.vision.live_job /data/clip --checkpoint \"$NINETY_CHECKPOINT\" --weights /data/checkpoint/checkpoint_best_total.pth --out /tmp/live --echo"]
