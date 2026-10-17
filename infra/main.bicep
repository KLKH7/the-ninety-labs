// The Ninety Labs on Azure: everything the public demo runs on, in the existing `ninety-labs`
// resource group. Deployed by `azd provision` (infra/README.md). The Foundry and Speech resources
// were created by hand before this file existed and are not managed here yet.
//
// No keys anywhere: the registry has its admin user off, the app pulls its image as a managed
// identity, and GitHub pushes images through OpenID Connect.
targetScope = 'resourceGroup'

@minLength(1)
@maxLength(64)
@description('azd environment name, for example "prod". Part of every resource name.')
param environmentName string

// The subscription only allows five regions; North Central US is the one with our models.
// The resource group itself sits in East US, so its location is not used.
@allowed(['northcentralus', 'spaincentral', 'germanywestcentral', 'denmarkeast', 'switzerlandnorth'])
param location string = 'northcentralus'

@description('Set by azd: true once the api app exists, so a re-provision keeps its current image.')
param apiExists bool = false

@description('Object id of the GitHub Actions service principal, granted image push. Empty to skip.')
param ciPrincipalId string = ''

@description('The Foundry resource and project, created by hand before this file; referenced, not managed.')
param foundryAccountName string = 'ninety-labs-ai'
param foundryProjectName string = 'the-ninety-labs'

var token = uniqueString(subscription().id, resourceGroup().id, environmentName)
var tags = { 'azd-env-name': environmentName }

resource logs 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: 'log-ninety-${token}'
  location: location
  tags: tags
  properties: {
    sku: { name: 'PerGB2018' }
    retentionInDays: 30
    workspaceCapping: { dailyQuotaGb: json('0.2') } // a hard stop on log spend
  }
}

resource registry 'Microsoft.ContainerRegistry/registries@2023-07-01' = {
  name: 'crninety${token}'
  location: location
  tags: tags
  sku: { name: 'Basic' }
  properties: {
    adminUserEnabled: false
  }
}

resource apiIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: 'id-api-${token}'
  location: location
  tags: tags
}

var acrPull = '7f951dda-4ed3-4680-a7ca-43fe172d538d'
var acrPush = '8311e382-0749-4cb8-b61a-304f252e45ec'

resource apiPull 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: registry
  name: guid(registry.id, apiIdentity.id, acrPull)
  properties: {
    principalId: apiIdentity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', acrPull)
  }
}

resource ciPush 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(ciPrincipalId)) {
  scope: registry
  name: guid(registry.id, ciPrincipalId, acrPush)
  properties: {
    principalId: ciPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', acrPush)
  }
}

// Set the mode explicitly: left out, Azure now creates an Express environment, which cannot run
// Container Apps jobs or OpenTelemetry and failed to pull our image with the managed identity.
// Only the 2026-03-02-preview API exposes environmentMode.
resource environment 'Microsoft.App/managedEnvironments@2026-03-02-preview' = {
  name: 'cae-ninety-${token}'
  location: location
  tags: tags
  properties: {
    environmentMode: 'WorkloadProfiles'
    workloadProfiles: [{ name: 'Consumption', workloadProfileType: 'Consumption' }]
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logs.properties.customerId
        sharedKey: logs.listKeys().primarySharedKey
      }
    }
  }
}

module apiImage 'modules/current-image.bicep' = {
  name: 'api-current-image'
  params: { name: 'ca-api-${token}', exists: apiExists }
}

resource api 'Microsoft.App/containerApps@2024-03-01' = {
  name: 'ca-api-${token}'
  location: location
  tags: union(tags, { 'azd-service-name': 'api' })
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: { '${apiIdentity.id}': {} }
  }
  dependsOn: [apiPull]
  properties: {
    managedEnvironmentId: environment.id
    workloadProfileName: 'Consumption'
    configuration: {
      ingress: {
        external: true
        targetPort: 8000
        allowInsecure: false
        transport: 'auto'
      }
      registries: [{ server: registry.properties.loginServer, identity: apiIdentity.id }]
    }
    template: {
      containers: [
        {
          name: 'api'
          // A public placeholder until the first `azd deploy api`; after that, the deployed image.
          image: apiExists ? apiImage.outputs.image : 'mcr.microsoft.com/k8se/quickstart:latest'
          resources: { cpu: json('0.25'), memory: '0.5Gi' }
          probes: apiExists
            ? [
                { type: 'Readiness', httpGet: { path: '/api/health', port: 8000 }, periodSeconds: 10 }
                { type: 'Liveness', httpGet: { path: '/api/health', port: 8000 }, periodSeconds: 30 }
              ]
            : []
        }
      ]
      // Scale to zero between viewers; one replica is plenty for a demo and caps spend.
      scale: { minReplicas: 0, maxReplicas: 1 }
    }
  }
}

// Foundry: tracing and the guardrail ------------------------------------------------------

resource foundry 'Microsoft.CognitiveServices/accounts@2025-06-01' existing = {
  name: foundryAccountName
}

resource foundryProject 'Microsoft.CognitiveServices/accounts/projects@2025-06-01' existing = {
  parent: foundry
  name: foundryProjectName
}

// The nightly evaluation workflow (.github/workflows/evals.yml) runs as the GitHub identity: it
// calls the published agents and records evaluation runs, so it needs Foundry User on this
// resource only (looked up with `az role definition list --name "Foundry User"`).
var foundryUser = '53ca6127-db72-4b80-b1b0-d745d6d5456d'

resource ciFoundryUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(ciPrincipalId)) {
  scope: foundry
  name: guid(foundry.id, ciPrincipalId, foundryUser)
  properties: {
    principalId: ciPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', foundryUser)
  }
}

// Agent runs send OpenTelemetry traces here; connected to the project, they show in Foundry's
// tracing view. Shares the capped Log Analytics workspace above.
resource appInsights 'Microsoft.Insights/components@2020-02-02' = {
  name: 'appi-ninety-${token}'
  location: location
  tags: tags
  kind: 'web'
  properties: {
    Application_Type: 'web'
    WorkspaceResourceId: logs.id
  }
}

resource tracingConnection 'Microsoft.CognitiveServices/accounts/projects/connections@2025-06-01' = {
  parent: foundryProject
  name: 'appinsights-tracing'
  properties: {
    category: 'AppInsights'
    target: appInsights.id
    authType: 'ApiKey'
    isSharedToAll: false
    credentials: { key: appInsights.properties.ConnectionString }
    metadata: { ApiType: 'Azure', ResourceId: appInsights.id }
  }
}

// The guardrail every agent is published with (ninety/agents/foundry.py). Microsoft's default
// filters at their default thresholds, plus Prompt Shields for indirect attacks: our agents read
// tool output and, later, viewer input, and both are data that may carry instructions. Thresholds
// are not tuned to football words: false blocks on commentary are to be measured with the agent
// evaluations (planned), and a threshold changes only on that evidence.
resource guardrail 'Microsoft.CognitiveServices/accounts/raiPolicies@2025-06-01' = {
  parent: foundry
  name: 'ninety-guardrail'
  properties: {
    basePolicyName: 'Microsoft.DefaultV2'
    mode: 'Blocking'
    contentFilters: [
      { name: 'Hate', blocking: true, enabled: true, severityThreshold: 'Medium', source: 'Prompt' }
      { name: 'Hate', blocking: true, enabled: true, severityThreshold: 'Medium', source: 'Completion' }
      { name: 'Sexual', blocking: true, enabled: true, severityThreshold: 'Medium', source: 'Prompt' }
      { name: 'Sexual', blocking: true, enabled: true, severityThreshold: 'Medium', source: 'Completion' }
      { name: 'Violence', blocking: true, enabled: true, severityThreshold: 'Medium', source: 'Prompt' }
      { name: 'Violence', blocking: true, enabled: true, severityThreshold: 'Medium', source: 'Completion' }
      { name: 'Selfharm', blocking: true, enabled: true, severityThreshold: 'Medium', source: 'Prompt' }
      { name: 'Selfharm', blocking: true, enabled: true, severityThreshold: 'Medium', source: 'Completion' }
      { name: 'Jailbreak', blocking: true, enabled: true, source: 'Prompt' }
      { name: 'Indirect Attack', blocking: true, enabled: true, source: 'Prompt' }
      { name: 'Protected Material Text', blocking: true, enabled: true, source: 'Completion' }
    ]
  }
}

output AZURE_CONTAINER_REGISTRY_ENDPOINT string = registry.properties.loginServer
output AZURE_CONTAINER_APPS_ENVIRONMENT_ID string = environment.id
output API_URL string = 'https://${api.properties.configuration.ingress.fqdn}'
output FOUNDRY_GUARDRAIL string = guardrail.name
