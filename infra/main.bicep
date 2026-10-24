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

@description('Object id of a maintainer allowed to read rendered clips (Storage Blob Data Reader). Empty to skip.')
param renderReaderPrincipalId string = ''

@description('Commit the event-driven render job renders with: a pushed sha or an engine tag. Empty: no queue job.')
param renderCommit string = ''

@secure()
@description('Only to create or rotate the MCP key: written to Key Vault when set; left alone when empty.')
param mcpKey string = ''

@secure()
@description('Only to create or rotate the demo passcode that gates Live mode: written to Key Vault when set; left alone when empty.')
param demoPasscode string = ''

@description('Replicas the demo app keeps running. 0 scales to zero between viewers (the default; a first request then waits for a cold start, about 50 s measured on 0.25 vCPU). 1 keeps one warm, for the judging window only: infra/README.md has the cost.')
@minValue(0)
@maxValue(1)
param apiMinReplicas int = 0

@description('Monthly cost budget for this resource group, in the billing currency (USD). 0: no budget.')
param budgetAmount int = 20

@description('Where the budget alert emails go. Kept in the azd environment, never in the repo. Empty: no budget.')
param budgetEmail string = ''

@description('First day of the budget\'s first month. Azure refuses a change after creation, so it is fixed, not today.')
param budgetStart string = '2026-10-01'

@description('The Foundry resource and project, created by hand before this file; referenced, not managed.')
param foundryAccountName string = 'ninety-labs-ai'
param foundryProjectName string = 'the-ninety-labs'

@description('The Speech resource, created by hand: the API speaks Live answers with it (ninety/api/speak.py).')
param speechAccountName string = 'ninety-labs-speech'

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
// Key Vault holds the key Foundry's agents use to call the match MCP server at /mcp. The API reads
// it through its managed identity; the Foundry connection gets it at deployment. Never in the repo.
resource vault 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: 'kv-ninety-${take(token, 13)}'
  location: location
  tags: tags
  properties: {
    tenantId: subscription().tenantId
    sku: { family: 'A', name: 'standard' }
    enableRbacAuthorization: true
    enabledForTemplateDeployment: true
  }
}

resource mcpKeySecret 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = if (!empty(mcpKey)) {
  parent: vault
  name: 'mcp-key'
  properties: { value: mcpKey }
}

resource passcodeSecret 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = if (!empty(demoPasscode)) {
  parent: vault
  name: 'demo-passcode'
  properties: { value: demoPasscode }
}

var vaultReaderRole = '4633458b-17de-408a-b874-0445c86b69e6' // built-in role "Key Vault Secrets User" (az role definition list)

resource apiReadsSecrets 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: vault
  name: guid(vault.id, apiIdentity.id, vaultReaderRole)
  properties: {
    principalId: apiIdentity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', vaultReaderRole)
  }
}

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
  dependsOn: [apiPull, apiReadsSecrets, apiSpeaks, mcpKeySecret, passcodeSecret]
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
      secrets: [
        { name: 'mcp-key', keyVaultUrl: '${vault.properties.vaultUri}secrets/mcp-key', identity: apiIdentity.id }
        { name: 'demo-passcode', keyVaultUrl: '${vault.properties.vaultUri}secrets/demo-passcode', identity: apiIdentity.id }
      ]
    }
    template: {
      containers: [
        {
          name: 'api'
          // A public placeholder until the first `azd deploy api`; after that, the deployed image.
          image: apiExists ? apiImage.outputs.image : 'mcr.microsoft.com/k8se/quickstart:latest'
          // Half a vCPU: most of a cold start is our own Python start-up (about 33 of 50 s on a quarter
          // vCPU, from the Container Apps system log on Oct 20), which scales with CPU. Billed per
          // active second only, so scale to zero still costs nothing between viewers.
          resources: { cpu: json('0.5'), memory: '1Gi' }
          env: [
            { name: 'NINETY_MCP_KEY', secretRef: 'mcp-key' }
            { name: 'NINETY_DEMO_PASSCODE', secretRef: 'demo-passcode' }
            // DefaultAzureCredential signs in as this user-assigned identity only when told its id.
            { name: 'AZURE_CLIENT_ID', value: apiIdentity.properties.clientId }
            { name: 'NINETY_SPEECH_RESOURCE_ID', value: speech.id }
            { name: 'NINETY_SPEECH_REGION', value: speech.location }
          ]
          probes: apiExists
            ? [
                { type: 'Readiness', httpGet: { path: '/api/health', port: 8000 }, periodSeconds: 10 }
                { type: 'Liveness', httpGet: { path: '/api/health', port: 8000 }, periodSeconds: 30 }
              ]
            : []
        }
      ]
      // Scale to zero between viewers by default; one replica is plenty for a demo and caps spend.
      // The price of zero is a cold start on the first request (about 50 s measured on 0.25 vCPU,
      // Oct 20), which Foundry's first MCP call also waits for; apiMinReplicas 1 removes it.
      scale: { minReplicas: apiMinReplicas, maxReplicas: 1 }
    }
  }
}

// Speech: the Live read-aloud route (ninety/api/speak.py) signs in as the API's identity, never a
// key (key auth is off on the resource). "Cognitive Services Speech User" on this resource only,
// looked up with `az role definition list --name "Cognitive Services Speech User"`.
resource speech 'Microsoft.CognitiveServices/accounts@2025-06-01' existing = {
  name: speechAccountName
}

var speechUser = 'f2dc8367-1007-4938-bd23-fe263f013447'

resource apiSpeaks 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: speech
  name: guid(speech.id, apiIdentity.id, speechUser)
  properties: {
    principalId: apiIdentity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', speechUser)
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

// The match MCP server as a Foundry tool connection: the published Analyst names it, and Foundry
// sends the key with every call (ninety/agents/foundry.py, MCP_CONNECTION).
resource vaultForDeployment 'Microsoft.KeyVault/vaults@2023-07-01' existing = {
  name: vault.name
}

module mcpConnection 'modules/mcp-connection.bicep' = {
  name: 'mcp-connection'
  dependsOn: [mcpKeySecret]
  params: {
    foundryAccountName: foundryAccountName
    foundryProjectName: foundryProjectName
    target: 'https://${api.properties.configuration.ingress.fqdn}/mcp'
    key: vaultForDeployment.getSecret('mcp-key')
  }
}

// Render job: renders training clips in parallel executions and writes them to Blob Storage
// (infra/render-job.sh). Shared keys are off, so the job and maintainers reach the blobs with
// Entra identities only.
resource storage 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: 'stninety${token}'
  location: location
  tags: tags
  sku: { name: 'Standard_LRS' }
  kind: 'StorageV2'
  properties: {
    allowSharedKeyAccess: false
    allowBlobPublicAccess: false
    minimumTlsVersion: 'TLS1_2'
    supportsHttpsTrafficOnly: true
  }
}

resource blobs 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' = {
  parent: storage
  name: 'default'
}

resource renders 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: blobs
  name: 'renders'
  properties: { publicAccess: 'None' }
}

// The answer key: events.jsonl and frames.jsonl of every clip (ninety/render/job.py). Written by
// the render job and read by maintainers for training and scoring; nothing on the live path (the
// API, and the live vision job when it lands) is granted it. infra/check_truth_sealed.py, run in CI,
// fails if any role reaches it from an identity that is not on the allowed list.
resource truth 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: blobs
  name: 'truth'
  properties: { publicAccess: 'None' }
}

// The frozen test set's answer key (frames.jsonl, events.jsonl; docs/eval/test-set-frozen.json), kept
// apart from `truth` because training machines get a read link to `truth` (scripts/train-on-gpu.sh).
// No training link names this container and no role is scoped to it: only the maintainer reader,
// who scores, reaches it, through the account-wide read role. infra/check_truth_sealed.py checks all
// three.
resource truthTest 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: blobs
  name: 'truth-test'
  properties: { publicAccess: 'None' }
}

// Render requests from the Data agent (ninety/agents/data_agent.py). The event-driven job starts
// one execution per waiting request; a request that fails twice moves to render-requests-failed.
resource queues 'Microsoft.Storage/storageAccounts/queueServices@2023-05-01' = {
  parent: storage
  name: 'default'
}

resource renderRequests 'Microsoft.Storage/storageAccounts/queueServices/queues@2023-05-01' = {
  parent: queues
  name: 'render-requests'
}

resource renderRequestsFailed 'Microsoft.Storage/storageAccounts/queueServices/queues@2023-05-01' = {
  parent: queues
  name: 'render-requests-failed'
}

resource renderIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: 'id-render-${token}'
  location: location
  tags: tags
}

// Microsoft's public Playwright image at our pinned playwright version, by digest. The container
// fetches this repo at NINETY_COMMIT and runs infra/render-job-start.sh: nothing is built, because
// this subscription does not allow ACR Tasks.
var renderImage = 'mcr.microsoft.com/playwright/python:v1.56.0-noble-amd64@sha256:508b37a524219d210a67a7190beb079efda72553e0dcb9ef21d4dae8f8a7686b'
var renderBoot = 'python3 -c "import io,os,tarfile,urllib.request as u; d=u.urlopen(\'https://codeload.github.com/KLKH7/the-ninety-labs/tar.gz/\' + os.environ[\'NINETY_COMMIT\'], timeout=120).read(); tarfile.open(fileobj=io.BytesIO(d)).extractall(\'/tmp/src\', filter=\'data\'); os.rename(\'/tmp/src/\' + os.listdir(\'/tmp/src\')[0], \'/tmp/repo\')" && exec bash /tmp/repo/infra/render-job-start.sh'

var blobContributor = 'ba92f5b4-2d11-453d-a403-e96b0029c9fe'
var blobReader = '2a2b9908-6ea1-4ae2-8e65-a410df84e7d1'
// Looked up with az role definition list (docs/LESSONS.md, lesson 30).
var queueContributor = '974c5e8b-45b9-4653-ba55-5f855dd0fb88' // take, delete and set aside requests
var queueSender = 'c6a89b2d-59bc-44d0-9896-0f6e12d7b80a' // add requests
var queueReader = '19e7f393-937e-4f77-808e-94535e297925' // see what is waiting

resource renderWrite 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: storage
  name: guid(storage.id, renderIdentity.id, blobContributor)
  properties: {
    principalId: renderIdentity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', blobContributor)
  }
}

resource renderRead 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(renderReaderPrincipalId)) {
  scope: storage
  name: guid(storage.id, renderReaderPrincipalId, blobReader)
  properties: {
    principalId: renderReaderPrincipalId
    principalType: 'User'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', blobReader)
  }
}

resource renderQueues 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: storage
  name: guid(storage.id, renderIdentity.id, queueContributor)
  properties: {
    principalId: renderIdentity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', queueContributor)
  }
}

resource maintainerSends 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(renderReaderPrincipalId)) {
  scope: storage
  name: guid(storage.id, renderReaderPrincipalId, queueSender)
  properties: {
    principalId: renderReaderPrincipalId
    principalType: 'User'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', queueSender)
  }
}

resource maintainerReadsQueues 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(renderReaderPrincipalId)) {
  scope: storage
  name: guid(storage.id, renderReaderPrincipalId, queueReader)
  properties: {
    principalId: renderReaderPrincipalId
    principalType: 'User'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', queueReader)
  }
}

resource renderJob 'Microsoft.App/jobs@2024-03-01' = {
  name: 'job-render-${token}'
  location: location
  tags: tags
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: { '${renderIdentity.id}': {} }
  }
  dependsOn: [renderWrite]
  properties: {
    environmentId: environment.id
    workloadProfileName: 'Consumption'
    configuration: {
      triggerType: 'Manual'
      // 25 ten-second clips at about 5 minutes each, with headroom; a retry resumes, not redoes
      replicaTimeout: 4 * 3600
      replicaRetryLimit: 1
      manualTriggerConfig: { parallelism: 1, replicaCompletionCount: 1 }
    }
    template: {
      containers: [
        {
          name: 'render'
          image: renderImage
          command: ['/bin/bash', '-c', renderBoot]
          resources: { cpu: json('2'), memory: '4Gi' }
          env: [
            { name: 'AZURE_CLIENT_ID', value: renderIdentity.properties.clientId }
            { name: 'AZURE_STORAGE_BLOB_URL', value: storage.properties.primaryEndpoints.blob }
            { name: 'AZURE_STORAGE_CONTAINER', value: renders.name }
            { name: 'AZURE_STORAGE_TRUTH_CONTAINER', value: truth.name }
          ]
        }
      ]
    }
  }
}

// The event-driven render job: Azure starts one execution per request waiting in render-requests
// (the KEDA azure-queue scaler, reading the queue as the render identity), up to six at a time.
// Every execution runs renderCommit; requests for any other commit are refused.
resource renderQueueJob 'Microsoft.App/jobs@2025-01-01' = if (!empty(renderCommit)) {
  name: 'job-render-queue-${token}'
  location: location
  tags: tags
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: { '${renderIdentity.id}': {} }
  }
  dependsOn: [renderWrite, renderQueues]
  properties: {
    environmentId: environment.id
    workloadProfileName: 'Consumption'
    configuration: {
      triggerType: 'Event'
      replicaTimeout: 4 * 3600
      replicaRetryLimit: 0 // a failed request is retried through the queue, which counts attempts
      eventTriggerConfig: {
        parallelism: 1
        replicaCompletionCount: 1
        scale: {
          minExecutions: 0
          maxExecutions: 6
          pollingInterval: 60
          rules: [
            {
              name: 'render-requests'
              type: 'azure-queue'
              metadata: { accountName: storage.name, queueName: renderRequests.name, queueLength: '1' }
              identity: renderIdentity.id
            }
          ]
        }
      }
    }
    template: {
      containers: [
        {
          name: 'render'
          image: renderImage
          command: ['/bin/bash', '-c', renderBoot]
          resources: { cpu: json('2'), memory: '4Gi' }
          env: [
            { name: 'AZURE_CLIENT_ID', value: renderIdentity.properties.clientId }
            { name: 'AZURE_STORAGE_BLOB_URL', value: storage.properties.primaryEndpoints.blob }
            { name: 'AZURE_STORAGE_CONTAINER', value: renders.name }
            { name: 'AZURE_STORAGE_TRUTH_CONTAINER', value: truth.name }
            { name: 'AZURE_STORAGE_QUEUE_URL', value: storage.properties.primaryEndpoints.queue }
            { name: 'NINETY_QUEUE', value: renderRequests.name }
            { name: 'NINETY_COMMIT', value: renderCommit }
          ]
        }
      ]
    }
  }
}

// The $20 alert (docs/PLAN.md, Budget): emails at half, at the full amount, and when Azure forecasts
// the month will pass it. A budget only alerts, it never stops anything; the hard stops are scale to
// zero, one replica, the capped log workspace and the subscription's own credit limit. Covers this
// resource group, which holds everything the demo runs on, the Foundry resource included.
resource budget 'Microsoft.Consumption/budgets@2024-08-01' = if (budgetAmount > 0 && !empty(budgetEmail)) {
  name: 'budget-ninety-${environmentName}'
  properties: {
    category: 'Cost'
    amount: budgetAmount
    timeGrain: 'Monthly'
    timePeriod: { startDate: budgetStart, endDate: '2027-09-30' }
    notifications: {
      actual50: { enabled: true, operator: 'GreaterThanOrEqualTo', threshold: 50, thresholdType: 'Actual', contactEmails: [budgetEmail] }
      actual100: { enabled: true, operator: 'GreaterThanOrEqualTo', threshold: 100, thresholdType: 'Actual', contactEmails: [budgetEmail] }
      forecast100: { enabled: true, operator: 'GreaterThan', threshold: 100, thresholdType: 'Forecasted', contactEmails: [budgetEmail] }
    }
  }
}

output AZURE_CONTAINER_REGISTRY_ENDPOINT string = registry.properties.loginServer
output AZURE_CONTAINER_APPS_ENVIRONMENT_ID string = environment.id
output API_URL string = 'https://${api.properties.configuration.ingress.fqdn}'
output DEMO_URL string = 'https://${api.properties.configuration.ingress.fqdn}/'
output BUDGET_NAME string = budgetAmount > 0 && !empty(budgetEmail) ? budget.name : ''
output FOUNDRY_GUARDRAIL string = guardrail.name
output RENDER_JOB_NAME string = renderJob.name
output RENDER_STORAGE_ACCOUNT string = storage.name
output RENDER_QUEUE_URL string = storage.properties.primaryEndpoints.queue
