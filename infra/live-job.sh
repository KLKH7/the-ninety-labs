#!/usr/bin/env bash
# The live detection job: stage a clip window and a checkpoint, build the CPU image, push it to our
# registry, deploy infra/live-job.bicep, run it, read its result. Needs `azd provision` of main.bicep
# first (the environment and the registry). Usage:
#
#   infra/live-job.sh stage <rendered clip> <from s> <to s> <checkpoint folder>   into runs/live-input/
#   infra/live-job.sh build <checkpoint name>      the image, tagged with the current commit (Docker)
#   infra/live-job.sh push                         to our registry; prints the image by digest
#   infra/live-job.sh deploy <image@sha256:...>    the identity (AcrPull only) and the job
#   infra/live-job.sh start                        one execution
#   infra/live-job.sh status                       recent executions and their state
#   infra/live-job.sh logs <execution>             its log: run.json and the detected events
#
# The clip, its window and the checkpoint are always arguments: the demo clip is whatever
# docs/eval/demo-clip.md's rule picked, and the checkpoint the one Kian names (with its record).
#   infra/live-job.sh stage <demo clip> <from s> <to s> <checkpoint folder>
#   infra/live-job.sh build <checkpoint name> && infra/live-job.sh push
#   infra/live-job.sh deploy <the printed image> && infra/live-job.sh start
#
# Sizing. A run takes about frames x seconds per frame, and both grow with the clip (25 fps: 1,500
# frames a minute of footage). Measure before sizing: stage a short window of the demo clip first
# (60 s), deploy with the default limit, run it, and read `detect_seconds_per_frame` and `seconds`
# in its run.json (`logs`). Then stage the whole clip and deploy with a limit of about 1.5 x the
# measured time, and 4 vCPUs if that is too long:
#   LIVE_TIMEOUT_S=<seconds> LIVE_CPU=4 infra/live-job.sh deploy <image>
# Memory does not grow with the clip (observe keeps no decoded frames), so 2 GiB per vCPU holds.
#
# A new clip or checkpoint: stage, build, push and deploy again. Nothing here reads the answer key
# except `stage`, on the maintainer's machine, for each frame's time and image; the image and the
# job get only images, the labels-free index and the checkpoint.
set -euo pipefail

env_value() { azd env get-value "$1"; }
REPO=ninety-live

case "${1:-}" in
  stage)
    rm -rf runs/live-input
    uv run python -m ninety.vision.stage_live "$2" --from "$3" --to "$4" --checkpoint "$5" --out runs/live-input
    ;;
  build)
    commit=$(git rev-parse HEAD)
    registry=$(env_value AZURE_CONTAINER_REGISTRY_ENDPOINT)
    docker buildx build --platform linux/amd64 -f infra/live-job.Dockerfile \
      --build-arg CHECKPOINT="$2" --build-arg NINETY_COMMIT="$commit" \
      -t "$registry/$REPO:$commit" --load .
    ;;
  push)
    commit=$(git rev-parse HEAD)
    registry=$(env_value AZURE_CONTAINER_REGISTRY_ENDPOINT)
    az acr login -n "${registry%%.*}"
    docker push "$registry/$REPO:$commit"
    docker inspect --format '{{index .RepoDigests 0}}' "$registry/$REPO:$commit"
    ;;
  deploy)
    az deployment group create -g "$(env_value AZURE_RESOURCE_GROUP)" -f infra/live-job.bicep \
      -p environmentName="$(env_value AZURE_ENV_NAME)" \
         containerAppsEnvironmentId="$(env_value AZURE_CONTAINER_APPS_ENVIRONMENT_ID)" \
         image="$2" replicaTimeoutSeconds="${LIVE_TIMEOUT_S:-3600}" cpu="${LIVE_CPU:-2}" \
      --query properties.outputs -o json
    ;;
  start|status|logs)
    RG=$(env_value AZURE_RESOURCE_GROUP)
    JOB=$(az containerapp job list -g "$RG" --query "[?starts_with(name,'job-live-')].name | [0]" -o tsv)
    test -n "$JOB" || { echo "no live job: deploy it first"; exit 1; }
    case "$1" in
      start) az containerapp job start -g "$RG" -n "$JOB" --query name -o tsv ;;
      status) az containerapp job execution list -g "$RG" -n "$JOB" \
                --query "[].{name:name,status:properties.status,start:properties.startTime}" -o table | head -20 ;;
      logs) az containerapp job logs show -g "$RG" -n "$JOB" --execution "$2" --container live ;;
    esac
    ;;
  *)
    sed -n '2,30p' "$0"; exit 2
    ;;
esac
