#!/usr/bin/env bash
# Entry point of the render job container (infra/main.bicep): Microsoft's public Playwright image,
# which already has Chromium and its libraries at our pinned playwright version, plus this repo at
# the commit in NINETY_COMMIT. Nothing is built: Azure for Students blocks ACR Tasks, and an
# emulated amd64 build of Chromium ran a laptop out of memory.
#
# The container's command fetches the repo tarball and runs this file from it; this file installs
# three.js from web/package-lock.json (integrity checked), syncs uv.lock, and runs the job.
set -euo pipefail
cd "$(dirname "$0")/.."

python3 - <<'PY'
import base64, hashlib, io, json, tarfile, urllib.request
pkg = json.load(open("web/package-lock.json"))["packages"]["node_modules/three"]
data = urllib.request.urlopen(pkg["resolved"], timeout=120).read()
algo, want = pkg["integrity"].split("-", 1)
if base64.b64encode(hashlib.new(algo, data).digest()).decode() != want:
    raise SystemExit("three.js tarball does not match web/package-lock.json integrity")
with tarfile.open(fileobj=io.BytesIO(data)) as t:
    t.extractall("web/node_modules", filter="data")
import os; os.rename("web/node_modules/package", "web/node_modules/three")
print("three", pkg["version"], "integrity ok")
PY

pip install --quiet --break-system-packages uv==0.12.23
export UV_NO_DEV=1 UV_PYTHON_PREFERENCE=only-system
uv sync --locked --group render-job --quiet
uv run --no-sync playwright install chromium  # a no-op when the image already has it
exec uv run --no-sync python -m ninety.render.job
