// A Foundry project connection for the match MCP server, holding its key. Foundry adds the key as
// the `x-api-key` header on every call; agents and their callers never see it.
param foundryAccountName string
param foundryProjectName string
param target string

@secure()
param key string

resource foundry 'Microsoft.CognitiveServices/accounts@2025-06-01' existing = {
  name: foundryAccountName
}

resource project 'Microsoft.CognitiveServices/accounts/projects@2025-06-01' existing = {
  parent: foundry
  name: foundryProjectName
}

resource connection 'Microsoft.CognitiveServices/accounts/projects/connections@2025-06-01' = {
  parent: project
  name: 'ninety-match-mcp'
  properties: {
    category: 'RemoteTool'
    target: target
    authType: 'CustomKeys'
    isSharedToAll: false
    credentials: { keys: { 'x-api-key': key } }
    metadata: { type: 'custom_MCP' }
  }
}
