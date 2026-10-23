#!/usr/bin/env bash
# The tactical fine-tune on the GPU pod that rendered dataset tactical, driven from the maintainer's Mac
# (docs/eval/finetune-tactical/PLAN.md). The pod trains on tiles of the rendered views in place
# (scripts/finetune-tactical-on-pod.sh); only the checkpoint and its records come back. A copy of
# scripts/finetune-tactical.sh with this run's model, initial checkpoint and paths.
#
#   SSH_PORT=<port> INIT=<dir of ours-freeze> scripts/finetune-tactical.sh <user@host> prepare
#       code at this commit (pushed) to /workspace/finetune/ninety, ours-freeze to /workspace/finetune/init, the
#       environment and a CUDA check. Reads no clip; may run while the render runs if its owner agrees.
#   SSH_PORT=<port> scripts/finetune-tactical.sh <user@host> start <render out>
#       in tmux session `finetune` on the pod: verify the clips, export, train under the time cap;
#       CRASHED=<seeds> names training seeds the render's owner reported crashed with no report
#   SSH_PORT=<port> scripts/finetune-tactical.sh <user@host> status
#   SSH_PORT=<port> scripts/finetune-tactical.sh <user@host> fetch [dest]
#       the checkpoint, manifest, metrics and log to <dest>/ours-freeze (default runs/train), checked
#       against the pod's SHA256SUMS and the manifest's checkpoint_sha256
#
# Only synthetic renders are on the pod and nothing secret goes to it. Delete the pod afterwards
# (Kian); this never does.
set -euo pipefail
host=${1:?user@host} cmd=${2:?prepare, start, status or fetch}
name=ours-tactical
init_sha=0fafe959ec2e08279e5741261ac4e639f2b87f0c11384a2d0e976dda6ef5d5e5  # ours-freeze, pre-registered
key=~/.ssh/ninety_lambda
port=${SSH_PORT:-22}
work=/workspace/finetune
ssh_=(ssh -i "$key" -p "$port" -o StrictHostKeyChecking=accept-new -o ServerAliveInterval=60 "$host")
scp_=(scp -q -i "$key" -P "$port")

case $cmd in
prepare)
  init=${INIT:?INIT=<folder with ours-freeze checkpoint_best_total.pth and train-manifest.json>}
  [ "$(shasum -a 256 "$init/checkpoint_best_total.pth" | cut -d' ' -f1)" = "$init_sha" ] \
    || { echo "$init is not ours-freeze ($init_sha)"; exit 1; }
  commit=$(git rev-parse HEAD)
  git branch -r --contains "$commit" | grep -q . || { echo "push $commit first"; exit 1; }
  echo "== code at $commit to $work/ninety (the environment is kept)"
  git archive --format=tar.gz "$commit" | "${ssh_[@]}" "mkdir -p $work/ninety $work/init && cd $work/ninety \
    && find . -mindepth 1 -maxdepth 1 ! -name .venv -exec rm -rf {} + && tar -xzf - && echo $commit > COMMIT"
  echo "== ours-freeze to $work/init"
  "${scp_[@]}" "$init/checkpoint_best_total.pth" "$init/train-manifest.json" "$host:$work/init/"
  "${ssh_[@]}" "bash -lc 'bash $work/ninety/scripts/finetune-tactical-on-pod.sh prepare'"
  ;;
start)
  out=${3:?the render out folder on the pod (manifest.json, tactical1/train/seed<N>/)}
  "${ssh_[@]}" "command -v tmux >/dev/null || (apt-get update -qq && apt-get install -y -qq tmux >/dev/null); \
    tmux new -d -s finetune 'bash -lc \"CRASHED=${CRASHED:-} RENDER_COMMIT=${RENDER_COMMIT:?} bash $work/ninety/scripts/finetune-tactical-on-pod.sh run $out $name\"' \
    && echo started: tmux attach -t finetune, or $work/finetune-$name.log"
  ;;
status)
  "${ssh_[@]}" "tail -n 5 $work/finetune-$name.log; nvidia-smi --query-gpu=utilization.gpu,memory.used --format=csv"
  ;;
fetch)
  dest=${3:-runs/train}/$name
  mkdir -p "$dest"
  files=$("${ssh_[@]}" "cat $work/out/$name/SHA256SUMS" | awk '{print $2}')
  for f in $files SHA256SUMS; do "${scp_[@]}" "$host:$work/out/$name/$f" "$dest/"; done
  (cd "$dest" && shasum -a 256 -c SHA256SUMS)
  python3 - "$dest" <<'EOF'
import hashlib, json, sys
from pathlib import Path
d = Path(sys.argv[1])
m = json.loads((d / "train-manifest.json").read_text())
got = hashlib.sha256((d / "checkpoint_best_total.pth").read_bytes()).hexdigest()
assert m["checkpoint_sha256"] == got, "the checkpoint does not match its manifest"
print(json.dumps({k: m.get(k) for k in ("name", "started", "finished", "stopped", "checkpoint_sha256")}, indent=2))
EOF
  ;;
*) echo "prepare, start, status or fetch"; exit 2 ;;
esac
