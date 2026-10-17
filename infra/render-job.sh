#!/usr/bin/env bash
# Render training clips on Azure: one Container Apps job execution per range of seeds, in parallel.
# Needs `azd provision` first (infra/README.md). Each execution runs this repo at the current
# commit, which must be pushed: the container fetches it from GitHub. Usage:
#
#   infra/render-job.sh start <run> <first> <total> <per> [set]  start ceil(total/per) executions
#   infra/render-job.sh status                                  recent executions and their state
#   infra/render-job.sh download <run> <dest>                   copy <run>/ (clips and their truth) to <dest>
#   infra/render-job.sh round <clusters.json> <first> <budget>  Data agent: plan and enqueue a targeted round
#   infra/render-job.sh queue                                   requests waiting and set aside
#
# `round` needs the event-driven job, created once a render commit is pinned:
#   azd env set RENDER_COMMIT <pushed sha or engine tag> && azd provision
#
# Example: 150 clips, 25 per execution (6 in parallel), then 40 crowded clips on later seeds:
#   infra/render-job.sh start v1 1 150 25
#   infra/render-job.sh start v1 1001 40 20 "occlusion=crowded"
# Clip length defaults to 10 s; set NINETY_SECONDS=4 in the environment for shorter clips.
set -euo pipefail

env_value() { azd env get-value "$1"; }
RG=$(env_value AZURE_RESOURCE_GROUP)
JOB=$(env_value RENDER_JOB_NAME)

case "${1:-}" in
  start)
    run=$2 first=$3 total=$4 per=$5 set=${6:-}
    commit=$(git rev-parse HEAD)
    git branch -r --contains "$commit" | grep -q . || { echo "push $commit first: the job fetches it from GitHub"; exit 1; }
    job_id=$(az containerapp job show -g "$RG" -n "$JOB" --query id -o tsv)
    job_json=$(az containerapp job show -g "$RG" -n "$JOB" -o json)
    seed=$first end=$((first + total))
    while [ "$seed" -lt "$end" ]; do
      count=$(( end - seed < per ? end - seed : per ))
      # A start with a template replaces the container definition, so copy the job's own container
      # (image, boot command, size, identity and storage settings) and add this range's variables.
      body=$(JOB_JSON="$job_json" python3 -c '
import json, os, sys
c = json.loads(os.environ["JOB_JSON"])["properties"]["template"]["containers"][0]
names = ["NINETY_COMMIT", "NINETY_RUN", "NINETY_FIRST_SEED", "NINETY_COUNT", "NINETY_SET", "NINETY_SECONDS"]
extra = dict(zip(names, sys.argv[1:]))
c["env"] = [e for e in c.get("env", []) if e["name"] not in extra] + [{"name": k, "value": v} for k, v in extra.items() if v]
print(json.dumps({"containers": [c]}))' "$commit" "$run" "$seed" "$count" "$set" "${NINETY_SECONDS:-}")
      az rest --method post --uri "$job_id/start?api-version=2024-03-01" --body "$body" \
        --query name -o tsv | sed "s/^/seeds $seed-$((seed + count - 1)): /"
      seed=$((seed + count))
    done
    ;;
  status)
    az containerapp job execution list -g "$RG" -n "$JOB" \
      --query "[].{name:name,status:properties.status,start:properties.startTime}" -o table | head -30
    ;;
  download)
    run=$2 dest=$3
    mkdir -p "$dest"
    # Images and clip.json from renders, events.jsonl and frames.jsonl from the sealed truth
    # container (the maintainer reader may read both), into one folder per clip.
    for container in renders truth; do
      az storage blob download-batch --auth-mode login --account-name "$(env_value RENDER_STORAGE_ACCOUNT)" \
        -s "$container" --pattern "$run/*" -d "$dest" -o none
    done
    echo "downloaded $run/ to $dest"
    ;;
  round)
    clusters=$2 first=$3 budget=$4 seconds=${NINETY_SECONDS:-10}
    queue_job=$(az containerapp job list -g "$RG" --query "[?starts_with(name,'job-render-queue-')].name | [0]" -o tsv)
    test -n "$queue_job" || { echo "no event-driven render job: pin a commit first (see the header)"; exit 1; }
    commit=$(az containerapp job show -g "$RG" -n "$queue_job" \
      --query "properties.template.containers[0].env[?name=='NINETY_COMMIT'].value | [0]" -o tsv)
    uv run --group render-job python -m ninety.agents.data_agent "$clusters" \
      --first-seed "$first" --budget "$budget" --commit "$commit" --seconds "$seconds" --enqueue
    ;;
  queue)
    account=$(env_value RENDER_STORAGE_ACCOUNT)
    for q in render-requests render-requests-failed; do
      echo "$q: $(az storage message peek --auth-mode login --account-name "$account" -q "$q" --num-messages 32 --query 'length(@)' -o tsv) message(s) (up to 32 shown)"
    done
    ;;
  *)
    sed -n '2,18p' "$0"; exit 2
    ;;
esac
