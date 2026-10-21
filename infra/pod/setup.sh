#!/usr/bin/env bash
# Set up a rented Ubuntu 24.04 CPU machine to render a dataset at one exact commit, then smoke-test
# it: one 60 s clip with ninety-validate and ninety-render-check, and a 10 s determinism re-render.
#
#   bash setup.sh <render commit sha> [driver ref]
#
# The render commit is checked out in /work/render/repo (its code makes the clips); the driver
# (infra/pod/render.py and the plan) comes from [driver ref], default main, into /work/render/driver.
# It also lays out /work for the other sessions that share the pod (/work/README, /work/bin/reserve).
# No secret is needed here: the repository is public. Upload links are given only to `upload`.
set -euo pipefail
SHA=${1:?usage: setup.sh <render commit sha> [driver ref]}
DRIVER_REF=${2:-main}
REPO=https://github.com/KLKH7/the-ninety-labs.git

export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq git curl ca-certificates python3 python3-pip python3-venv tmux util-linux >/dev/null

pip install --quiet --break-system-packages uv==0.12.23  # the version the Azure render job pins
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

# Smoke: seed 7 from 0:00 for 60 s, as the look-freeze review rendered it (software GL here), then
# the determinism re-render on a 10 s clip, the dataset's length: re-rendering the 60 s clip would
# double the smoke (a 10 s clip took 130 s on the maintainer's Mac with software GL).
S=$W/smoke; rm -rf "$S" && mkdir -p "$S"
time uv run --no-sync ninety-render --seed 7 --start 0 --seconds 60 --out $S/seed7 | tail -12
uv run --no-sync ninety-validate $S/seed7
uv run --no-sync ninety-render-check $S/seed7 --report $S/check.json | tail -12
uv run --no-sync ninety-render --seed 3 --seconds 10 --out $S/seed3 | tail -3
uv run --no-sync ninety-render-check $S/seed3 --determinism --report $S/determinism.json | tail -8
nproc; free -g | head -2
echo "setup done: render $(git rev-parse --short HEAD), driver $(git -C "$W/driver" rev-parse --short HEAD)"
