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

Not managed here yet: the Foundry (`ninety-labs-ai`) and Speech (`ninety-labs-speech`)
resources, created by hand earlier, and the $20 monthly budget alert. Cosmos DB, the Personalizer
app and Application Insights are added with the code that uses them
([ARCHITECTURE.md](../docs/ARCHITECTURE.md#deployment-on-azure)).

Rough cost: the registry is the only fixed charge (Basic, about $5 a month). The app and logs sit
inside the monthly free grants at demo traffic.

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
