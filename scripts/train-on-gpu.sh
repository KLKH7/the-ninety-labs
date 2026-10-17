#!/usr/bin/env bash
# Fine-tune RF-DETR Small on a rented GPU machine (AGENTS.md: training only, synthetic renders only,
# machine deleted after the run, checkpoint back with its manifest).
#
#   scripts/train-on-gpu.sh <user@host> <exported-dataset-dir> <name>
#   scripts/train-on-gpu.sh ubuntu@1.2.3.4 runs/coco/v2 ours-v2
#   SSH_PORT=12345 scripts/train-on-gpu.sh root@1.2.3.4 runs/coco/v2 ours-v2   # RunPod-style port
#
# Copies this repo at the current commit (which must be pushed) and the exported COCO dataset,
# trains with ninety/vision/finetune.json, and copies the run back to runs/train/<name>/. Uses the
# SSH key ~/.ssh/ninety_lambda. Delete the machine afterwards; this script never does.
set -euo pipefail
host=$1 data=$2 name=$3
key=~/.ssh/ninety_lambda
port=${SSH_PORT:-22}
ssh_=(ssh -i "$key" -p "$port" -o StrictHostKeyChecking=accept-new -o ServerAliveInterval=60 "$host")
commit=$(git rev-parse HEAD)
git branch -r --contains "$commit" | grep -q . || { echo "push $commit first"; exit 1; }

echo "== code at $commit"
git archive --format=tar.gz "$commit" | "${ssh_[@]}" 'rm -rf ninety && mkdir ninety && tar -xzf - -C ninety'
echo "== data from $data (symlinks resolved)"
"${ssh_[@]}" 'command -v rsync >/dev/null || (apt-get update -qq && apt-get install -y -qq rsync >/dev/null)'
rsync -aL --progress -e "ssh -i $key -p $port" "$data/" "$host:ninety/data/"

echo "== train $name"
"${ssh_[@]}" "bash -lc '
  set -euo pipefail
  cd ninety
  command -v uv >/dev/null || curl -LsSf https://astral.sh/uv/0.12.23/install.sh | sh
  export PATH=\$HOME/.local/bin:\$PATH
  uv sync --locked --group vision
  nvidia-smi --query-gpu=name,memory.total --format=csv
  NINETY_COMMIT=$commit nohup uv run python -m ninety.vision.train --data data --out out/$name --name $name > train-$name.log 2>&1 &
  echo started: tail -f ninety/train-$name.log
'"
echo "When training ends: rsync -a -e 'ssh -i $key -p $port' $host:ninety/out/$name/ runs/train/$name/"
