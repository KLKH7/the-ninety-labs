"""Where the Azure resources are. Endpoints are not secrets: every call is authenticated with
Entra ID (az login locally, managed identity in Azure), and key auth is disabled on both resources."""

import os

FOUNDRY_PROJECT = os.environ.get(
    "NINETY_FOUNDRY_PROJECT", "https://ninety-labs-ai.services.ai.azure.com/api/projects/the-ninety-labs"
)
MODEL = os.environ.get("NINETY_MODEL", "gpt-4.1-mini")

SPEECH_REGION = os.environ.get("NINETY_SPEECH_REGION", "northcentralus")
# Full resource id of the Speech resource, needed for Entra auth on the TTS endpoint:
#   az cognitiveservices account show -n ninety-labs-speech -g ninety-labs --query id -o tsv
SPEECH_RESOURCE_ID = os.environ.get("NINETY_SPEECH_RESOURCE_ID", "")

# Full resource id of the Foundry resource, needed to attach the guardrail when publishing agents:
#   az cognitiveservices account show -n ninety-labs-ai -g ninety-labs --query id -o tsv
FOUNDRY_RESOURCE_ID = os.environ.get("NINETY_FOUNDRY_RESOURCE_ID", "")

# The match MCP server Foundry's agents call (ninety/api/app.py at /mcp). Not a secret: calls need
# the key that only Key Vault and the Foundry connection hold.
MATCH_MCP_URL = os.environ.get(
    "NINETY_MATCH_MCP_URL", "https://ca-api-icrxiozwmmxmg.blackmoss-2f143091.northcentralus.azurecontainerapps.io/mcp"
)
