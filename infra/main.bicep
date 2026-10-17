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
var acrPush = '8311e382-0749-4cb8-b61a-753f48f6e0af'

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

resource environment 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: 'cae-ninety-${token}'
  location: location
  tags: tags
  properties: {
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

output AZURE_CONTAINER_REGISTRY_ENDPOINT string = registry.properties.loginServer
output AZURE_CONTAINER_APPS_ENVIRONMENT_ID string = environment.id
output API_URL string = 'https://${api.properties.configuration.ingress.fqdn}'
