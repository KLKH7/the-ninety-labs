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

output AZURE_CONTAINER_REGISTRY_ENDPOINT string = registry.properties.loginServer
output AZURE_CONTAINER_APPS_ENVIRONMENT_ID string = environment.id
output API_URL string = 'https://${api.properties.configuration.ingress.fqdn}'
output RENDER_JOB_NAME string = renderJob.name
output RENDER_STORAGE_ACCOUNT string = storage.name
output RENDER_QUEUE_URL string = storage.properties.primaryEndpoints.queue
