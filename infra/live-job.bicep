// The live detection job (ninety/vision/live_job.py; docs/TEAM.md, Thu Oct 22): one manual
// execution runs the live path of event detection, on CPU, on the clip and checkpoint built into
// its image (infra/live-job.Dockerfile). Deployed on its own into the environment and registry that
// main.bicep made (infra/live-job.sh deploy), so it changes nothing main.bicep owns; it can move
// into main.bicep once the M2 deploy work there has landed.
//
// The job's identity holds one role: AcrPull on our registry, to pull its image. It holds no
// storage role at all, so the answer key is out of its reach and infra/check_truth_sealed.py, which
// allows storage roles only to the render job and the maintainer, passes on this template too
// (tests/test_live_job_infra.py). Its result is its log: run.json and the detected events, one JSON
// line each (live_job --echo), in the environment's capped Log Analytics workspace.
targetScope = 'resourceGroup'

@description('The azd environment name main.bicep was provisioned with (azd env get-value AZURE_ENV_NAME).')
param environmentName string

param location string = resourceGroup().location

@description('The Container Apps environment main.bicep made (azd env get-value AZURE_CONTAINER_APPS_ENVIRONMENT_ID).')
param containerAppsEnvironmentId string

@description('The live detection image in our registry, by digest: <registry>.azurecr.io/ninety-live@sha256:...')
param image string

// The run's length grows with the clip: about frames x the measured seconds per frame (run.json,
// detect_seconds_per_frame, plus observe). Set it from a measured run on a short window of the
// demo clip, with headroom, never from a guess (infra/live-job.sh, "Sizing").
@description('Seconds one execution may run before Azure stops it.')
@minValue(300)
param replicaTimeoutSeconds int = 3600

@description('vCPUs for the job; on the Consumption profile memory is twice this in GiB.')
@allowed(['2', '4'])
param cpu string = '2'

var token = uniqueString(subscription().id, resourceGroup().id, environmentName)
var tags = { 'azd-env-name': environmentName }
var acrPull = '7f951dda-4ed3-4680-a7ca-43fe172d538d'

// main.bicep names its registry crninety<token> from the same token.
resource registry 'Microsoft.ContainerRegistry/registries@2023-07-01' existing = {
  name: 'crninety${token}'
}

resource liveIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: 'id-live-${token}'
  location: location
  tags: tags
}

resource livePull 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: registry
  name: guid(registry.id, liveIdentity.id, acrPull)
  properties: {
    principalId: liveIdentity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', acrPull)
  }
}

resource liveJob 'Microsoft.App/jobs@2024-03-01' = {
  name: 'job-live-${token}'
  location: location
  tags: tags
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: { '${liveIdentity.id}': {} }
  }
  dependsOn: [livePull]
  properties: {
    environmentId: containerAppsEnvironmentId
    workloadProfileName: 'Consumption'
    configuration: {
      triggerType: 'Manual'
      replicaTimeout: replicaTimeoutSeconds
      // No retry: a failed run of a whole match is looked at and started again by hand, not repeated
      replicaRetryLimit: 0
      manualTriggerConfig: { parallelism: 1, replicaCompletionCount: 1 }
      registries: [{ server: registry.properties.loginServer, identity: liveIdentity.id }]
    }
    template: {
      containers: [
        {
          name: 'live'
          image: image
          resources: { cpu: json(cpu), memory: '${int(cpu) * 2}Gi' }
        }
      ]
    }
  }
}

output LIVE_JOB_NAME string = liveJob.name
output LIVE_IDENTITY_PRINCIPAL_ID string = liveIdentity.properties.principalId
