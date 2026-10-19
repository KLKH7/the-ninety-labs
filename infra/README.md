# infra

Bicep for everything the public demo runs on, deployed with the Azure Developer CLI (`azd`).
All of it goes into the existing `ninety-labs` resource group, in North Central US (the
subscription allows five regions; that one has our models).

| Resource | Why |
|---|---|
| Container Apps environment + `api` app | serves `ninety/api` over HTTPS; scales to zero, at most one replica |
| Container Registry (Basic) | holds the API image; admin user off |
| User-assigned managed identity | the app pulls its image with it (AcrPull); no registry password |
| Log Analytics workspace | container logs; 30-day retention, 0.2 GB/day cap |
| Container Apps job `render` + its identity | renders training clips in parallel executions (2 vCPU, 4 GiB each), on the public Playwright image |
| Storage account + `renders` container | the rendered clips (images and `clip.json`); shared keys and public access off, Entra roles only |
| `truth` container | the answer key of every clip (`events.jsonl`, `frames.jsonl`): only the render job and the maintainer reader hold a role that reaches it, and CI checks that ([check_truth_sealed.py](check_truth_sealed.py)) |
| `truth-test` container | the frozen test set's answer key (`docs/eval/test-set-frozen.json`), kept out of `truth` because training machines get a read link to `truth`; no role is scoped to it and no training link names it (CI: [check_truth_sealed.py](check_truth_sealed.py)) |
| Queues `render-requests`, `render-requests-failed` + job `render-queue` | the data factory: the Data agent queues requests, Azure starts one execution per request (up to six), failed requests are set aside with the error |
| Application Insights + a Foundry project connection (`appinsights-tracing`) | agent traces, shown in Foundry's tracing view; stored in the capped workspace above |
| Key Vault (RBAC) + the `mcp-key` secret | the key Foundry uses to call the match MCP server at `/mcp`; the API reads it through its managed identity (Key Vault Secrets User) |
| Foundry project connection `ninety-match-mcp` | the MCP server as a Foundry tool connection, holding the key; the published Analyst names it |
| Foundry content-safety policy `ninety-guardrail` | attached to every published agent: Microsoft's default filters plus Prompt Shields for jailbreaks and indirect attacks |

The Foundry resource (`ninety-labs-ai`) and its project were created by hand earlier: the Bicep
references them to add the connection and the policy, but does not manage them. Also not managed
here yet: Speech (`ninety-labs-speech`) and the $20 monthly budget alert. Cosmos DB and the
Personalizer app are added with the code that uses them
([ARCHITECTURE.md](../docs/ARCHITECTURE.md#deployment-on-azure)).

The agents themselves are published from code, not Bicep: `uv run ninety-agents publish`
(ninety/agents/foundry.py) creates a new Foundry version of any agent whose definition changed.

Rough cost: the registry is the only fixed charge (Basic, about $5 a month). The app, logs and
traces sit inside the monthly free grants at demo traffic.

## Who runs what

| Command | Run by | Changes |
|---|---|---|
| `azd provision` | a maintainer, locally, with Owner on the resource group | resources and role assignments |
| `azd deploy api` | GitHub Actions ([deploy.yml](../.github/workflows/deploy.yml)) after CI passes on `main` | a new image and revision only |

The split is deliberate: the GitHub OIDC identity is only Contributor, which cannot create role
assignments, so it cannot grant itself or anything else more access.

## First-time setup

```bash
brew install azure/azd/azd
azd auth login
azd env new prod
azd env set AZURE_SUBSCRIPTION_ID "$(az account show --query id -o tsv)"
azd env set AZURE_RESOURCE_GROUP ninety-labs
azd env set AZURE_LOCATION northcentralus
# Lets GitHub Actions push images (object id of the deploy service principal):
azd env set CI_PRINCIPAL_ID "$(az ad sp show --id <AZURE_CLIENT_ID repo variable> --query id -o tsv)"
azd provision
azd deploy api
```

`azd` keeps the environment in `.azure/` (gitignored). Nothing in it is a secret, but it stays
out of the repo.

Check a template change without creating anything:

```bash
az deployment group what-if -g ninety-labs -f infra/main.bicep -p environmentName=prod
```

CI compiles the Bicep on every pull request and fails on any warning.

## The MCP key

The key is created once and kept in Key Vault. To create or rotate it, pass a new one for a single
provision, then clear it from the local azd environment so it lives only in Azure:

```bash
azd env set MCP_KEY "$(openssl rand -hex 32)" && azd provision && azd env set MCP_KEY ""
```

Provisions without `MCP_KEY` leave the secret alone. After rotating, restart the API's revision
so it reads the new value.

## Rendering training clips on Azure

`infra/render-job.sh` runs [ninety/render/job.py](../ninety/render/job.py) as a Container Apps
job: one execution per range of training seeds, in parallel. Nothing is built: the job runs
Microsoft's public Playwright image (Chromium at our pinned playwright version, pinned by digest),
fetches this repo at the commit `start` passes, and runs
[render-job-start.sh](render-job-start.sh). This subscription does not allow ACR Tasks, and an
emulated amd64 build of Chromium ran a laptop out of memory. Each execution renders its clips
with software GL, runs the render checks, uploads passing clips to `renders/<run>/train/seed<N>/`
and their ground truth to `truth/<run>/train/seed<N>/` (`clip.json` last, so a retried execution
skips finished seeds) and reports failing ones in
`renders/<run>/failed/`. Test-set seeds are refused: the fixed test set is rendered once,
locally, so its pixels never depend on the machine that drew them.

```bash
azd env set RENDER_READER_PRINCIPAL_ID "$(az ad signed-in-user show --query id -o tsv)"
azd provision                          # storage, identity, job (Owner on the resource group)
git push                               # executions fetch the current commit from GitHub
infra/render-job.sh start v1 1 150 25  # seeds 1-150, 25 per execution, 6 in parallel
infra/render-job.sh status
infra/render-job.sh download v1 runs/dataset
uv run ninety-render-check runs/dataset/v1/train/seed*   # check again after download
```

Measured on render run v1 (220 ten-second clips): 365 to 660 s a clip, about 8 minutes, so about
960 vCPU-seconds and 1,900 GiB-seconds a clip. 200 clips is about 190,000 vCPU-seconds, slightly over
the Consumption plan's monthly free grant of 180,000, so about a dollar beyond it; blobs are about
30 MB a clip.

## The data factory: targeted rounds from the queue

Where vision fails, the Vision Auditor writes failure clusters (`runs/<round>/clusters.json`, the
handoff in [docs/TEAM.md](../docs/TEAM.md)). The Data agent
([ninety/agents/data_agent.py](../ninety/agents/data_agent.py)) turns them into render requests:
the clip budget split by misses, render settings the renderer accepts, training seeds only, one
engine commit for the whole round. It writes the plan to `runs/<round>/requests.json`, then queues
it. The `render-queue` job is started by Azure for each waiting request (the KEDA queue scaler,
reading the queue as the render identity), renders it, and deletes it; a request for another
commit, or with bad settings, is set aside in `render-requests-failed` at once, and a crash gets
one retry.

```bash
azd env set RENDER_COMMIT "$(git rev-parse HEAD)"   # pushed sha or engine tag: what every execution runs
azd provision                                       # creates the queue job on that commit
infra/render-job.sh round runs/round1/clusters.json 2001 40   # Data agent: plan and queue 40 clips
infra/render-job.sh queue                           # waiting and set-aside requests
infra/render-job.sh status
infra/render-job.sh download round1 runs/dataset    # clips and their truth, one folder per clip
```

Change `RENDER_COMMIT` only between rounds: requests made for the old commit are refused by the
new job, by design, so a round never mixes engine versions.
