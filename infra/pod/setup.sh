#!/usr/bin/env bash
# Set up a rented Ubuntu machine (a CPU pod, or a Runpod PyTorch GPU pod) to render a dataset at one
# exact commit, then smoke-test it: the GL check, a 10 s clip rendered twice and compared byte for
# byte (determinism), and ninety-validate and ninety-render-check on it.
#
#   GL=gpu bash setup.sh <render commit sha> [driver ref]     # NVIDIA GPU, refusing software GL
#   bash setup.sh <render commit sha> [driver ref]            # software GL (SwiftShader)
#
# The render commit is checked out in /work/render/repo (its code makes the clips); the driver
# (infra/pod/render.py and the plan) comes from [driver ref], default main, into /work/render/driver.
# It also lays out /work for the other sessions that share the pod (/work/README, /work/bin/reserve).
# No secret is needed here: the repository is public. Upload links are given only to `upload`.
set -euo pipefail
SHA=${1:?usage: setup.sh <render commit sha> [driver ref]}
DRIVER_REF=${2:-main}
GL=${GL:-software}
REPO=https://github.com/KLKH7/the-ninety-labs.git

export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq git curl ca-certificates python3 python3-pip python3-venv tmux util-linux >/dev/null
if [ "$GL" = gpu ]; then
  # Chromium reaches the NVIDIA driver through Vulkan or EGL: the loaders, and the vendor files that
  # point them at the driver's libraries when the image does not ship them (the libraries come from
  # the host driver, mounted into the container).
  apt-get install -y -qq libvulkan1 libegl1 libgles2 >/dev/null
  nvidia-smi --query-gpu=name,driver_version --format=csv,noheader
  if [ ! -e /usr/share/vulkan/icd.d/nvidia_icd.json ] && ldconfig -p | grep -q libGLX_nvidia.so.0; then
    mkdir -p /usr/share/vulkan/icd.d
    echo '{"file_format_version":"1.0.0","ICD":{"library_path":"libGLX_nvidia.so.0","api_version":"1.3"}}' \
      > /usr/share/vulkan/icd.d/nvidia_icd.json
  fi
  if [ ! -e /usr/share/glvnd/egl_vendor.d/10_nvidia.json ] && ldconfig -p | grep -q libEGL_nvidia.so.0; then
    mkdir -p /usr/share/glvnd/egl_vendor.d
    echo '{"file_format_version":"1.0.0","ICD":{"library_path":"libEGL_nvidia.so.0"}}' \
      > /usr/share/glvnd/egl_vendor.d/10_nvidia.json
  fi
fi

# the version the Azure render job pins; older pip has no --break-system-packages
pip install --quiet uv==0.12.23 2>/dev/null || pip install --quiet --break-system-packages uv==0.12.23
export UV_NO_DEV=1

W=/work/render
mkdir -p "$W" /work/bin /work/cores
rm -rf "$W/repo" "$W/driver"
git clone -q "$REPO" "$W/repo"
git -C "$W/repo" checkout -q "$SHA"
test "$(git -C "$W/repo" rev-parse HEAD)" = "$(git -C "$W/repo" rev-parse "$SHA^{commit}")"
git clone -q --depth 1 --branch "$DRIVER_REF" "$REPO" "$W/driver" 2>/dev/null \
  || { git clone -q "$REPO" "$W/driver" && git -C "$W/driver" checkout -q "$DRIVER_REF"; }
install -m 755 "$W/driver/infra/pod/reserve.sh" /work/bin/reserve
install -m 755 "$W/driver/infra/pod/cores.sh" /work/bin/cores
install -m 644 "$W/driver/infra/pod/README-work.md" /work/README

cd "$W/repo"
# three.js from web/package-lock.json, integrity checked (as infra/render-job-start.sh does).
python3 - <<'PY'
import base64, hashlib, io, json, os, tarfile, urllib.request
pkg = json.load(open("web/package-lock.json"))["packages"]["node_modules/three"]
data = urllib.request.urlopen(pkg["resolved"], timeout=120).read()
algo, want = pkg["integrity"].split("-", 1)
if base64.b64encode(hashlib.new(algo, data).digest()).decode() != want:
    raise SystemExit("three.js tarball does not match web/package-lock.json integrity")
with tarfile.open(fileobj=io.BytesIO(data)) as t:
    t.extractall("web/node_modules", filter="data")
os.rename("web/node_modules/package", "web/node_modules/three")
print("three", pkg["version"], "integrity ok")
PY
uv sync --locked --group render-job --quiet
uv run --no-sync playwright install --with-deps chromium >/dev/null

# Smoke: the GL check fails loudly when --gl gpu finds only software GL; then seed 3, a 10 s
# training clip, rendered twice in fresh browsers must be byte-identical, and one copy must meet
# the data contract and the render checks.
S=$W/smoke; rm -rf "$S" && mkdir -p "$S"
D="uv run --no-sync python $W/driver/infra/pod/render.py"
P=$W/driver/docs/eval/dataset-v2-freeze.json
$D glcheck --repo . --gl "$GL" --out "$S" | tee $S/glcheck.json
time $D determinism --plan $P --repo . --out "$S" --gl "$GL" --seeds 3 | tee $S/determinism.json
uv run --no-sync ninety-validate $S/determinism/seed3-a
uv run --no-sync ninety-render-check $S/determinism/seed3-a --report $S/check.json | tail -12
nproc; free -g | head -2
echo "setup done ($GL GL): render $(git rev-parse --short HEAD), driver $(git -C "$W/driver" rev-parse --short HEAD)"
