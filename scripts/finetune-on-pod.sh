#!/usr/bin/env bash
# Runs ON the GPU pod that rendered the dataset: fine-tune RF-DETR Small against the rendered clips in
# place (docs/eval/finetune-v2freeze/PLAN.md). Started from the Mac by scripts/finetune-v2freeze.sh,
# which copies this repo (at a pushed commit) to $WORK/ninety and the initial checkpoint to
# $WORK/init. No credential is on the pod; the outputs are copied back over SSH.
#
#   bash finetune-on-pod.sh prepare                       environment and a CUDA check; reads no clip
#   bash finetune-on-pod.sh run <render out> <name>       verify, export, train under the cap, record
#
# The config (with its time cap), the render run and its commit are pre-registered in the plan; only
# the paths are arguments.
set -euo pipefail
WORK=${WORK:-/work/finetune}
CONFIG=ninety/vision/finetune-v2freeze.json
RUN=v2freeze
RENDER_COMMIT=aea01f4e5d168b0ff3e8e44143cd4baaaf9a3f60
TORCH=2.14.1 TORCHVISION=0.29.1  # uv.lock's; the fallback builds below keep these versions
cd "$WORK/ninety"
export PATH=$HOME/.local/bin:$PATH
py=$WORK/ninety/.venv/bin/python  # direct, not through uv run, so a signal reaches the trainer itself

cuda_ok() {
  "$py" - <<'EOF'
import torch
assert torch.cuda.is_available(), "CUDA not available"
x = torch.ones(1024, 1024, device="cuda")
assert (x @ x).sum().item() == 1024 ** 3
print(torch.__version__, torch.version.cuda, torch.cuda.get_device_name(0))
EOF
}

case ${1:?prepare or run} in
prepare)
  command -v uv >/dev/null || curl -LsSf https://astral.sh/uv/0.12.23/install.sh | sh
  uv sync --locked --group vision
  nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv,noheader
  # The lock's torch is built for CUDA 13.0 (driver 580 or newer). On an older driver, the same
  # versions built for CUDA 12.8, then 12.6 (pre-registered in the plan); machine.json records which.
  if ! cuda_ok; then
    for cu in cu128 cu126; do
      echo "== torch $TORCH for $cu"
      uv pip install --python "$py" --reinstall "torch==$TORCH" "torchvision==$TORCHVISION" \
        --index-url "https://download.pytorch.org/whl/$cu" && cuda_ok && break
    done
    cuda_ok
  fi
  sha256sum "$WORK/init/checkpoint_best_total.pth"
  ;;
run)
  out=${2:?render out} name=${3:?model name}
  dest=$WORK/out/$name
  [ ! -e "$dest/train-manifest.json" ] || { echo "$dest already holds a run"; exit 1; }
  mkdir -p "$dest"
  exec > >(tee -a "$WORK/finetune-$name.log") 2>&1
  echo "== $(date -u +%FT%TZ) clips of $out (run $RUN at $RENDER_COMMIT), checked against the manifest"
  "$py" -m ninety.vision.pod_clips "$out" --run "$RUN" --commit "$RENDER_COMMIT" --config "$CONFIG" \
    --work "$WORK/data-$name"
  echo "== $(date -u +%FT%TZ) export"
  rm -rf "$WORK/coco-$name"
  mapfile -t clips < "$WORK/data-$name/clips.txt"
  "$py" -m ninety.vision.coco_export "${clips[@]}" --out "$WORK/coco-$name" --config "$WORK/data-$name/config.json"
  "$py" - "$dest/machine.json" "$name" <<'EOF'
import datetime as dt, json, subprocess, sys, torch
smi = subprocess.run(["nvidia-smi", "-L"], capture_output=True, text=True).stdout.splitlines()
drv = subprocess.run(["nvidia-smi", "--query-gpu=driver_version", "--format=csv,noheader"],
                     capture_output=True, text=True).stdout.strip()
json.dump({"run": sys.argv[2], "recorded": dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "provider": "RunPod", "gpu": torch.cuda.get_device_name(0),
           "gpu_memory_gib": round(torch.cuda.get_device_properties(0).total_memory / 2**30, 1),
           "nvidia_smi": smi, "driver": drv, "torch": torch.__version__, "cuda": torch.version.cuda},
          open(sys.argv[1], "w"), indent=2)
EOF
  cap=$("$py" -c "import json; print(json.load(open('$CONFIG'))['time_cap_minutes'])")
  echo "== $(date -u +%FT%TZ) train $name from $(sha256sum "$WORK/init/checkpoint_best_total.pth"), cap $cap min"
  set +e
  NINETY_COMMIT=$(cat "$WORK/ninety/COMMIT") timeout -s INT -k 5m "${cap}m" "$py" -m ninety.vision.train \
    --data "$WORK/coco-$name" --out "$dest" --name "$name" --config "$WORK/data-$name/config.json" \
    --init "$WORK/init/checkpoint_best_total.pth" --dataset-list "$WORK/data-$name/dataset-list.json"
  code=$?
  set -e
  case $code in
    0) ;;
    124|137) "$py" -m ninety.vision.train --out "$dest" --record-only "time cap of $cap minutes" ;;
    *) "$py" -m ninety.vision.train --out "$dest" --record-only "failed with exit code $code: not a model to use" ;;
  esac
  cp "$WORK/finetune-$name.log" "$dest/train.log"
  # what comes back to the Mac; last.ckpt (optimizer state) and the EMA copies stay on the pod
  (cd "$dest" && sha256sum $(ls checkpoint_best_total.pth train-manifest.json metrics.csv \
    training_config.json machine.json train.log 2>/dev/null) > SHA256SUMS)
  echo "== $(date -u +%FT%TZ) done (exit $code)"; cat "$dest/SHA256SUMS"
  ;;
*) echo "prepare or run"; exit 2 ;;
esac
