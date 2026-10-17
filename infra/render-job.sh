#!/usr/bin/env bash
# Render training clips on Azure: one Container Apps job execution per range of seeds, in parallel.
# Needs `azd provision` first (infra/README.md). Usage:
#
#   infra/render-job.sh build                                  build and push the image, point the job at it
#   infra/render-job.sh start <run> <first> <total> <per> [set]  start ceil(total/per) executions
#   infra/render-job.sh status                                  recent executions and their state
#   infra/render-job.sh download <run> <dest>                   copy <run>/ from Blob Storage to <dest>
#
# Example: 150 clips, 25 per execution (6 in parallel), then 40 crowded clips on later seeds:
#   infra/render-job.sh start v1 1 150 25
#   infra/render-job.sh start v1 1001 40 20 "occlusion=crowded"
set -euo pipefail

env_value() { azd env get-value "$1"; }
RG=$(env_value AZURE_RESOURCE_GROUP)
JOB=$(env_value RENDER_JOB_NAME)

case "${1:-}" in
  build)
    registry=$(env_value AZURE_CONTAINER_REGISTRY_ENDPOINT)
    commit=$(git rev-parse --short HEAD)
    image="$registry/ninety-render:$commit"
    # amd64 pinned in Dockerfile.render; Container Apps runs nothing else
    docker buildx build --platform linux/amd64 -f Dockerfile.render \
      --build-arg NINETY_COMMIT="$commit" -t "$image" --push .
    azd env set RENDER_IMAGE "$image"  # so a later `azd provision` keeps this image
    az containerapp job update -g "$RG" -n "$JOB" --image "$image" -o none
    echo "job $JOB now runs $image"
    ;;
  start)
    run=$2 first=$3 total=$4 per=$5 set=${6:-}
    # A start with overrides replaces the container definition, so carry the job's own settings
    # (identity, storage URL, size) into every execution explicitly.
    read -r -a base_env <<< "$(az containerapp job show -g "$RG" -n "$JOB" \
      --query "properties.template.containers[0].env[].join('=', [name, value])" -o tsv | tr '\n' ' ')"
    seed=$first end=$((first + total))
    while [ "$seed" -lt "$end" ]; do
      count=$(( end - seed < per ? end - seed : per ))
      az containerapp job start -g "$RG" -n "$JOB" --container-name render \
        --image "$(env_value RENDER_IMAGE)" --cpu 2 --memory 4Gi \
        --env-vars "${base_env[@]}" NINETY_RUN="$run" NINETY_FIRST_SEED="$seed" NINETY_COUNT="$count" ${set:+NINETY_SET="$set"} \
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
    az storage blob download-batch --auth-mode login --account-name "$(env_value RENDER_STORAGE_ACCOUNT)" \
      -s renders --pattern "$run/*" -d "$dest" -o none
    echo "downloaded $run/ to $dest"
    ;;
  *)
    sed -n '2,13p' "$0"; exit 2
    ;;
esac
