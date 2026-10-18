#!/usr/bin/env bash
# Fine-tune RF-DETR Small on a rented GPU machine (AGENTS.md: training only, synthetic renders only,
# machine deleted after the run, checkpoint back with its manifest).
#
#   scripts/train-on-gpu.sh <user@host> <data> <name>
#     <data> = a local exported COCO dataset (copied up), or azure:<run>[,<run>...] (fetched there)
#   SSH_PORT=12345 scripts/train-on-gpu.sh root@1.2.3.4 azure:v2los,v2 ours-v2  # RunPod; v2los first wins
#   scripts/train-on-gpu.sh ubuntu@1.2.3.4 runs/coco/v2 ours-v2
#   EPOCHS=1 ...                                   a smoke run; the manifest records the override
#   INIT=runs/train/ours-v2 CONFIG=ninety/vision/finetune-short.json ...   continue from our checkpoint
#
# azure:<runs>: a read-only SAS link to the `renders` container, valid 6 hours, is made here with
# your Azure sign-in and sent to the machine over SSH's stdin, never as an argument or a file. The
# machine fetches the labels and every 5th frame of each run (ninety/vision/fetch_clips.py),
# exports them (ninety/vision/coco_export.py) and trains with ninety/vision/finetune.json.
#
# Copies this repo at the current commit (which must be pushed). Training runs detached; copy the
# run back with the command printed at the end. Delete the machine afterwards; this never does.
set -euo pipefail
host=$1 data=$2 name=$3
key=~/.ssh/ninety_lambda
port=${SSH_PORT:-22}
epochs_arg=${EPOCHS:+--epochs $EPOCHS}  # a smoke run only; real runs use finetune.json's epochs
config_arg=${CONFIG:+--config $CONFIG}  # another committed config, e.g. a short fine-tune
init_arg=${INIT:+--init init/checkpoint_best_total.pth}  # INIT=runs/train/ours-v2: start from our checkpoint
ssh_=(ssh -i "$key" -p "$port" -o StrictHostKeyChecking=accept-new -o ServerAliveInterval=60 "$host")
commit=$(git rev-parse HEAD)
git branch -r --contains "$commit" | grep -q . || { echo "push $commit first"; exit 1; }

echo "== code at $commit"
# replace everything but the installed environment; clips and data from an earlier run are removed,
# so a later fetch never mistakes an old run's clips for this run's
git archive --format=tar.gz "$commit" | "${ssh_[@]}" \
  'mkdir -p ninety && find ninety -mindepth 1 -maxdepth 1 ! -name .venv ! -name out -exec rm -rf {} + && tar -xzf - -C ninety'

if [ -n "${INIT:-}" ]; then
  echo "== initial checkpoint from $INIT"
  "${ssh_[@]}" 'mkdir -p ninety/init'
  scp -q -P "$port" -i "$key" "$INIT/checkpoint_best_total.pth" "$INIT/train-manifest.json" "$host:ninety/init/"
fi

echo "== environment"
"${ssh_[@]}" "bash -lc '
  set -euo pipefail
  cd ninety
  command -v uv >/dev/null || curl -LsSf https://astral.sh/uv/0.12.23/install.sh | sh
  export PATH=\$HOME/.local/bin:\$PATH
  uv sync --locked --group vision
  nvidia-smi --query-gpu=name,memory.total --format=csv
'"

if [[ $data == azure:* ]]; then
  runs=${data#azure:}
  # the storage account, from RENDER_STORAGE_ACCOUNT or azd; anything but a valid name falls back
  account=${RENDER_STORAGE_ACCOUNT:-$(azd env get-value RENDER_STORAGE_ACCOUNT 2>/dev/null || true)}
  [[ $account =~ ^[a-z0-9]{3,24}$ ]] || account=stninetyicrxiozwmmxmg
  expiry=$(date -u -v+6H +%Y-%m-%dT%H:%MZ 2>/dev/null || date -u -d '+6 hours' +%Y-%m-%dT%H:%MZ)
  echo "== read-only link to $account/renders, valid until $expiry UTC"
  sas=$(az storage container generate-sas --account-name "$account" --name renders --permissions rl \
    --expiry "$expiry" --auth-mode login --as-user -o tsv 2>/dev/null || true)
  [ -n "$sas" ] || { echo "could not make the link: are you signed in to Azure with blob read access?"; exit 1; }
  fetches=""
  for r in ${runs//,/ }; do fetches+="uv run --no-sync python -m ninety.vision.fetch_clips $r --out clips; "; done
  echo "== fetch $runs, export, train $name"
  printf '%s\n' "https://$account.blob.core.windows.net/renders?$sas" | "${ssh_[@]}" "bash -lc '
    set -euo pipefail
    read -r RENDERS_SAS_URL; export RENDERS_SAS_URL
    cd ninety && export PATH=\$HOME/.local/bin:\$PATH
    $fetches
    unset RENDERS_SAS_URL
    rm -rf data && uv run --no-sync python -m ninety.vision.coco_export clips/seed* --out data --config ninety/vision/finetune.json
    NINETY_COMMIT=$commit nohup uv run --no-sync python -m ninety.vision.train --data data --out out/$name --name $name $epochs_arg $config_arg $init_arg > train-$name.log 2>&1 &
    echo started: tail -f ninety/train-$name.log
  '"
else
  echo "== data from $data (symlinks resolved)"
  "${ssh_[@]}" 'command -v rsync >/dev/null || (apt-get update -qq && apt-get install -y -qq rsync >/dev/null)'
  rsync -aL --progress -e "ssh -i $key -p $port" "$data/" "$host:ninety/data/"
  echo "== train $name"
  "${ssh_[@]}" "bash -lc '
    cd ninety && export PATH=\$HOME/.local/bin:\$PATH
    NINETY_COMMIT=$commit nohup uv run --no-sync python -m ninety.vision.train --data data --out out/$name --name $name $epochs_arg $config_arg $init_arg > train-$name.log 2>&1 &
    echo started: tail -f ninety/train-$name.log
  '"
fi
# the checkpoint the vision report uses and the run's records; last.ckpt (optimizer state, ~0.5 GB) and
# the EMA copies stay on the machine
echo "When training ends: mkdir -p runs/train/$name && for f in checkpoint_best_total.pth train-manifest.json metrics.csv training_config.json; do scp -P $port -i $key $host:ninety/out/$name/\$f runs/train/$name/; done"
