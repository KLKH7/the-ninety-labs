// PROPOSAL from R4 for R5 (infra/ is R5's): the Personalizer's Container App. Move this file to
// infra/modules/personalizer.bicep and call it from infra/main.bicep as shown at the end; then
// `azd provision`. Not deployed by anything yet.
//
// The Personalizer runs from the API's own image (the Dockerfile already copies ninety/ and installs
// uv.lock, a2a-sdk included) with a different command, so there is no second image to build.
// Ingress is internal: only apps in the same Container Apps environment (the API) can reach it, so
// the A2A endpoint is not on the public internet. It calls Foundry as its own user-assigned managed
// identity, which holds Foundry User on the Foundry resource and AcrPull on the registry, nothing
// else. No key, secret or connection string.

@description('Shared by every resource name, as in infra/main.bicep.')
param token string
param location string
param tags object

@description('The Container Apps environment the API runs in (infra/main.bicep `environment`).')
param environmentId string

@description('The registry the API image is pulled from (infra/main.bicep `registry`).')
param registryName string

@description('The image the API runs now: the Personalizer runs the same image.')
param image string

@description('The Foundry resource, created by hand; referenced, not managed.')
param foundryAccountName string

// Role ids copied from infra/main.bicep, where each was looked up with `az role definition list`
// and is in use (lessons 49 and 93): AcrPull, and Foundry User.
var acrPull = '7f951dda-4ed3-4680-a7ca-43fe172d538d'
var foundryUser = '53ca6127-db72-4b80-b1b0-d745d6d5456d'
var port = 8001
var name = 'ca-personalizer-${token}'

resource registry 'Microsoft.ContainerRegistry/registries@2023-07-01' existing = {
  name: registryName
}

resource foundry 'Microsoft.CognitiveServices/accounts@2025-06-01' existing = {
  name: foundryAccountName
}

resource identity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: 'id-personalizer-${token}'
  location: location
  tags: tags
}

resource pull 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: registry
  name: guid(registry.id, identity.id, acrPull)
  properties: {
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', acrPull)
  }
}

resource callsFoundry 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: foundry
  name: guid(foundry.id, identity.id, foundryUser)
  properties: {
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', foundryUser)
  }
}

resource environment 'Microsoft.App/managedEnvironments@2026-03-02-preview' existing = {
  name: last(split(environmentId, '/'))
}

resource personalizer 'Microsoft.App/containerApps@2024-03-01' = {
  name: name
  location: location
  tags: union(tags, { 'azd-service-name': 'personalizer' })
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: { '${identity.id}': {} }
  }
  dependsOn: [pull, callsFoundry]
  properties: {
    managedEnvironmentId: environmentId
    workloadProfileName: 'Consumption'
    configuration: {
      ingress: {
        external: false // reachable only from inside the environment, by the API
        targetPort: port
        allowInsecure: false
        transport: 'auto'
      }
      registries: [{ server: registry.properties.loginServer, identity: identity.id }]
    }
    template: {
      containers: [
        {
          name: 'personalizer'
          image: image
          command: ['uvicorn']
          args: [
            '--factory', 'ninety.personalizer.server:live_app'
            '--host', '0.0.0.0', '--port', string(port), '--no-server-header'
          ]
          resources: { cpu: json('0.25'), memory: '0.5Gi' }
          env: [
            // DefaultAzureCredential signs in as this user-assigned identity only when told which.
            { name: 'AZURE_CLIENT_ID', value: identity.properties.clientId }
            { name: 'NINETY_PERSONALIZER_URL', value: 'https://${name}.internal.${environment.properties.defaultDomain}/' }
          ]
          probes: [
            { type: 'Readiness', httpGet: { path: '/health', port: port }, periodSeconds: 10 }
            { type: 'Liveness', httpGet: { path: '/health', port: port }, periodSeconds: 30 }
          ]
        }
      ]
      // Scale to zero like the API. A cold start is slower than the budget (ninety/personalizer/
      // core.py BUDGET_S), so the first request after idle falls back to the verified text;
      // set minReplicas to 1 for a live demo session if the trace shows that.
      scale: { minReplicas: 0, maxReplicas: 1 }
    }
  }
}

output url string = 'https://${personalizer.properties.configuration.ingress.fqdn}/'
output principalId string = identity.properties.principalId

// In infra/main.bicep, after `api`:
//
//   module personalizer 'modules/personalizer.bicep' = if (apiExists) {
//     name: 'personalizer'
//     params: {
//       token: token
//       location: location
//       tags: tags
//       environmentId: environment.id
//       registryName: registry.name
//       image: apiImage.outputs.image
//       foundryAccountName: foundryAccountName
//     }
//   }
//
// and give the API its address: { name: 'NINETY_PERSONALIZER_URL', value: personalizer.outputs.url }
// (a module output needs the `if` guarded: apiExists ? personalizer!.outputs.url : '').
