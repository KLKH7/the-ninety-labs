# infra

Bicep for everything the public demo runs on, deployed with the Azure Developer CLI (`azd`).
All of it goes into the existing `ninety-labs` resource group, in North Central US (the
subscription allows five regions; that one has our models).

| Resource | Why |
|---|---|
| Container Apps environment + `api` app | the whole public demo over HTTPS from one image: the viewer at `/`, the Replay bundle at `/bundle/`, the API, Live mode behind the passcode, and the MCP server at `/mcp`; scales to zero, at most one replica |
| Container Registry (Basic) | holds the API image; admin user off |
| User-assigned managed identity | the app pulls its image with it (AcrPull); no registry password |
| Log Analytics workspace | container logs; 30-day retention, 0.2 GB/day cap |
| Container Apps job `render` + its identity | renders training clips in parallel executions (2 vCPU, 4 GiB each), on the public Playwright image |
| Storage account + `renders` container | the rendered clips (images and `clip.json`); shared keys and public access off, Entra roles only |
| `truth` container | the answer key of every clip (`events.jsonl`, `frames.jsonl`): only the render job and the maintainer reader hold a role that reaches it, and CI checks that ([check_truth_sealed.py](check_truth_sealed.py)) |
| `truth-test` container | the frozen test set's answer key (`docs/eval/test-set-frozen.json`), kept out of `truth` because training machines get a read link to `truth`; no role is scoped to it and no training link names it (CI: [check_truth_sealed.py](check_truth_sealed.py)) |
| Queues `render-requests`, `render-requests-failed` + job `render-queue` | the data factory: the Data agent queues requests, Azure starts one execution per request (up to six), failed requests are set aside with the error |
| Application Insights + a Foundry project connection (`appinsights-tracing`) | agent traces, shown in Foundry's tracing view; stored in the capped workspace above |
| Key Vault (RBAC) + the `mcp-key` and `demo-passcode` secrets | the key Foundry uses to call the match MCP server at `/mcp`, and the passcode that gates Live mode; the API reads both through its managed identity (Key Vault Secrets User) |
| Budget `budget-ninety-<env>` | the $20 monthly alert on this resource group: emails `BUDGET_EMAIL` at 50% and 100% actual and at a forecast over 100%; it alerts, it never stops anything |
| Foundry project connection `ninety-match-mcp` | the MCP server as a Foundry tool connection, holding the key; the published Analyst names it |
| Foundry content-safety policy `ninety-guardrail` | attached to every published agent: Microsoft's default filters plus Prompt Shields for jailbreaks and indirect attacks |

The Foundry resource (`ninety-labs-ai`) and its project were created by hand earlier: the Bicep
references them to add the connection and the policy, but does not manage them. Also not managed
here yet: Speech (`ninety-labs-speech`). Cosmos DB and the
Personalizer app are added with the code that uses them
([ARCHITECTURE.md](../docs/ARCHITECTURE.md#deployment-on-azure)).

The agents themselves are published from code, not Bicep: `uv run ninety-agents publish`
(ninety/agents/foundry.py) creates a new Foundry version of any agent whose definition changed.

Rough cost: the registry is the only fixed charge (Basic, about $5 a month). The app, logs and
traces sit inside the monthly free grants at demo traffic. Costs in detail, and why everything
scales to zero: [The deployed demo](#the-deployed-demo-m2).

## Who runs what

| Command | Run by | Changes |
|---|---|---|
| `azd provision` (or `azd up`) | a maintainer, locally, with Owner on the resource group | resources and role assignments |
| `azd deploy api` | GitHub Actions ([deploy.yml](../.github/workflows/deploy.yml)) after CI passes on `main`, then the live smoke test | a new image and revision only |
| live smoke test | [live-smoke.yml](../.github/workflows/live-smoke.yml), twice a day, against `NINETY_LIVE_URL` | nothing: reads the public site |

The split is deliberate: the GitHub OIDC identity is only Contributor, which cannot create role
assignments, so it cannot grant itself or anything else more access.

## Live agent steps from GitHub (`agents-live`)

Sessions without Azure credentials run their live steps (publishing agents, recording replays,
the evaluations) through [agents-live.yml](../.github/workflows/agents-live.yml): started by hand,
it waits for a reviewer's approval, signs in with OIDC, runs the task at the chosen `ref`, and
uploads the agent registry, `replays/`, `runs/eval/` and the commit as an artifact. It never
pushes.

Runs are grouped by `ref`: each branch has its own queue, so a dispatch from one branch never
cancels another branch's run while it waits for approval (GitHub keeps one pending run per group).
The trade-off: two branches can publish at the same time, and if both changed the same agent each
creates a version. Each branch commits the registry its own run returned, and `pinned()` refuses
to run an agent whose code differs from its pinned version, so nothing runs under the wrong one.

One-time setup, by Kian:

1. In the repo's Settings, Environments, create `agents-live` and add yourself as a required
   reviewer, so no run reaches Azure without your approval.
2. Add a federated credential to the deploy app registration (the `AZURE_CLIENT_ID` repo
   variable) that trusts that environment. This repo's OIDC subjects carry the owner and repo
   ids (`repo:KLKH7@210092633/the-ninety-labs@1417939631:...`), so copy the prefix of the
   existing `main` credential rather than writing `repo:KLKH7/the-ninety-labs:...`, which Azure
   would never match:

   ```bash
   CLIENT_ID=$(gh variable get AZURE_CLIENT_ID -R KLKH7/the-ninety-labs)
   az ad app federated-credential list --id "$CLIENT_ID" --query "[].subject" -o tsv  # the format in use
   az ad app federated-credential create --id "$CLIENT_ID" --parameters '{
     "name": "github-agents-live",
     "issuer": "https://token.actions.githubusercontent.com",
     "subject": "repo:KLKH7@210092633/the-ninety-labs@1417939631:environment:agents-live",
     "audiences": ["api://AzureADTokenExchange"]
   }'
   ```

   Done when the list shows both subjects with the same `repo:...@...` prefix, and the first
   approved run passes its `azure/login` step.

3. For `publish`, add the repo variable `NINETY_FOUNDRY_RESOURCE_ID` (a resource id, not a
   secret: `az cognitiveservices account show -n ninety-labs-ai -g ninety-labs --query id -o tsv`).

The identity is the same one deploy.yml and evals.yml use: Contributor on the resource group and
Foundry User on the Foundry resource, so it cannot grant itself more access. `eval` already runs
nightly as this identity; `publish` has not run as it yet, so the first `publish` run is the check
that Foundry User may create agent versions.

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

## The deployed demo (M2)

One container app serves everything a judge opens, from one image ([Dockerfile](../Dockerfile)):

- **Replay mode** (`/`): the viewer plays one clip that has already been through the whole chain
  (`ninety-e2e`). It is files only: no model call, no compute beyond serving them, so a view costs
  nothing. The bundle is synthetic and public, packed to the same bytes every time by
  [replay.py](replay.py), published as a release asset, and pinned in the Dockerfile by URL and
  SHA-256; a different asset fails the build. The image never needs Azure Storage, so the API's
  identity holds no role on the account that keeps the answer key ([check_truth_sealed.py](check_truth_sealed.py)).
- **Live mode** (`/api/live/...`): anything that costs a model call or speech, behind the demo
  passcode (`x-demo-passcode`), read from Key Vault. Without a configured passcode it refuses
  everyone.
- **Headers:** a same-origin Content Security Policy (the viewer cannot be pointed at another site
  or framed), `nosniff`, no referrer.
- **Checks:** CI builds the image on every pull request with a fixture bundle, runs it and runs
  [the live smoke test](../tests/test_live_smoke.py) against it; the deploy runs the same test on
  the public URL, and [live-smoke.yml](../.github/workflows/live-smoke.yml) runs it twice a day
  until judging ends.

### Deploy from a clean clone

The subscription is **Azure for Students**: a credit with a spending limit, and when the credit
runs out Azure disables the subscription and the demo goes down until Nov 10 is over. So everything
scales to zero by default and the budget alert fires at $20 (half the alert at $10).

Use the environment name `prod` and the resource group `ninety-labs`. A second environment name
in the same group would create a second registry and app, and repoint the shared Foundry
connection (`ninety-match-mcp`) at the new app.

```bash
git clone https://github.com/KLKH7/the-ninety-labs && cd the-ninety-labs
azd auth login && az login
azd env new prod
azd env set AZURE_SUBSCRIPTION_ID "$(az account show --query id -o tsv)"
azd env set AZURE_RESOURCE_GROUP ninety-labs
azd env set AZURE_LOCATION northcentralus
azd env set CI_PRINCIPAL_ID "$(az ad sp show --id "$(gh variable get AZURE_CLIENT_ID)" --query id -o tsv)"
azd env set RENDER_READER_PRINCIPAL_ID "$(az ad signed-in-user show --query id -o tsv)"
azd env set BUDGET_EMAIL <where the budget alert goes>
# Only when Key Vault lacks the secret (infra/preprovision.sh says which); store the passcode in
# the password manager first, then clear it here after the provision:
azd env set DEMO_PASSCODE "$(openssl rand -hex 12)"
az deployment group what-if -g ninety-labs -f infra/main.bicep -p environmentName=prod \
  ciPrincipalId=... renderReaderPrincipalId=... budgetEmail=...   # read-only preview
azd up                                  # provision, then build the image locally and deploy it
azd env set DEMO_PASSCODE ""
gh variable set NINETY_LIVE_URL --body "$(azd env get-value API_URL)"
NINETY_LIVE_URL="$(azd env get-value API_URL)" uv run pytest -q tests/test_live_smoke.py
```

`azd up` builds the image on this machine with Docker (the subscription does not allow ACR
Tasks), and [preprovision.sh](preprovision.sh) stops it early if a Key Vault secret or the budget
address is missing. Set `RENDER_COMMIT` too if the render queue job should keep its commit.

A new Replay bundle (a better clip, the detector's events, a Foundry recording):

```bash
uv run ninety-e2e <clip> --out runs/replay [--replay <recording>]
python3 infra/replay.py pack runs/replay runs/replay.tar.gz      # prints the sha256
gh release create replay-<clip>-v<N> runs/replay.tar.gz --latest=false --title "Replay bundle <clip> v<N>" \
  --notes "Synthetic demo bundle for the deployed viewer (infra/README.md)"
# then set REPLAY_URL and REPLAY_SHA256 in the Dockerfile, in a pull request
```

### What it costs

Estimates from Azure's published pay-as-you-go rates (Container Apps Consumption: about $0.000024 an
active vCPU-second and $0.000003 a GiB-second), not measured bills; check the
[pricing calculator](https://azure.microsoft.com/pricing/calculator/) and the Cost Management view
after the first week, and replace this table with what it shows.

| Item | Cost | Note |
|---|---|---|
| Container Registry, Basic | about $5 a month | the only fixed charge |
| Container app, scale to zero | about $0.002 a view | 0.25 vCPU and 0.5 GiB for the ~5 minutes a replica stays up after the last request; inside the monthly free grant (180,000 vCPU-seconds, 360,000 GiB-seconds), which the render jobs share |
| Container app kept warm (`minReplicas: 1`) | about $6 a month, $0.20 a day | optional, for the judging window only: no cold start (a few seconds) for the first judge |
| Log Analytics and Application Insights | $0 to about $3 a month | 5 GB a month free; the workspace is capped at 0.2 GB a day |
| Key Vault | cents | secrets are read when a revision starts |
| Storage (renders, truth, queues) | under $1 a month | about 30 MB a clip |
| Outbound data | $0 | 18 MB a view; the first 100 GB a month are free |
| Budget alert, release asset, scheduled smoke test | $0 | |
| Live mode | per run: model tokens and speech | behind the passcode; Replay mode makes no model call |

Expected total with Replay traffic: about $5 to $8 a month, under half the alert.

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
