#!/usr/bin/env bash
# The look-freeze fine-tune on the GPU pod that rendered dataset v2, driven from the maintainer's Mac
# (docs/eval/finetune-v2freeze/PLAN.md). The pod trains against the rendered clips in place
# (scripts/finetune-on-pod.sh); only the checkpoint and its records come back.
#
#   SSH_PORT=<port> INIT=<dir of ours-v4> scripts/finetune-v2freeze.sh <user@host> prepare
#       code at this commit (pushed) to /work/finetune/ninety, ours-v4 to /work/finetune/init, the
#       environment and a CUDA check. Reads no clip; may run while the render runs if its owner agrees.
#   SSH_PORT=<port> scripts/finetune-v2freeze.sh <user@host> start <render out>
#       in tmux session `finetune` on the pod: verify the clips, export, train under the time cap;
#       CRASHED=<seeds> names training seeds the render's owner reported crashed with no report
#   SSH_PORT=<port> scripts/finetune-v2freeze.sh <user@host> status
#   SSH_PORT=<port> scripts/finetune-v2freeze.sh <user@host> fetch [dest]
#       the checkpoint, manifest, metrics and log to <dest>/ours-freeze (default runs/train), checked
#       against the pod's SHA256SUMS and the manifest's checkpoint_sha256
#
# Only synthetic renders are on the pod and nothing secret goes to it. Delete the pod afterwards
# (Kian); this never does.
set -euo pipefail
host=${1:?user@host} cmd=${2:?prepare, start, status or fetch}
name=ours-freeze
init_sha=95d361542361890926202999257904391395497cc74447c7da0e3b618fb6922d  # ours-v4, pre-registered
key=~/.ssh/ninety_lambda
port=${SSH_PORT:-22}
work=/work/finetune
ssh_=(ssh -i "$key" -p "$port" -o StrictHostKeyChecking=accept-new -o ServerAliveInterval=60 "$host")
scp_=(scp -q -i "$key" -P "$port")

case $cmd in
prepare)
  init=${INIT:?INIT=<folder with ours-v4 checkpoint_best_total.pth and train-manifest.json>}
  [ "$(shasum -a 256 "$init/checkpoint_best_total.pth" | cut -d' ' -f1)" = "$init_sha" ] \
    || { echo "$init is not ours-v4 ($init_sha)"; exit 1; }
  commit=$(git rev-parse HEAD)
  git branch -r --contains "$commit" | grep -q . || { echo "push $commit first"; exit 1; }
  echo "== code at $commit to $work/ninety (the environment is kept)"
  git archive --format=tar.gz "$commit" | "${ssh_[@]}" "mkdir -p $work/ninety $work/init && cd $work/ninety \
    && find . -mindepth 1 -maxdepth 1 ! -name .venv -exec rm -rf {} + && tar -xzf - && echo $commit > COMMIT"
  echo "== ours-v4 to $work/init"
  "${scp_[@]}" "$init/checkpoint_best_total.pth" "$init/train-manifest.json" "$host:$work/init/"
  "${ssh_[@]}" "bash -lc 'bash $work/ninety/scripts/finetune-on-pod.sh prepare'"
  ;;
start)
  out=${3:?the render out folder on the pod (manifest.json, v2freeze/train/seed<N>/)}
  "${ssh_[@]}" "command -v tmux >/dev/null || (apt-get update -qq && apt-get install -y -qq tmux >/dev/null); \
    tmux new -d -s finetune 'bash -lc \"CRASHED=${CRASHED:-} bash $work/ninety/scripts/finetune-on-pod.sh run $out $name\"' \
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
