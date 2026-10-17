// The image a container app runs now, so `azd provision` does not roll it back to the
// placeholder. Returns an empty string when the app does not exist yet.
param name string
param exists bool

resource app 'Microsoft.App/containerApps@2024-03-01' existing = if (exists) {
  name: name
}

output image string = exists ? app!.properties.template.containers[0].image : ''
