#!/bin/sh
# Runs before every `azd provision` and `azd up` (azure.yaml hooks). Stops a provision that would
# leave the demo half-deployed: the API reads two secrets from Key Vault at start (mcp-key, and
# demo-passcode for Live mode), and a revision whose secret is missing never starts. Also refuses to
# provision without the budget alert's address (docs/PLAN.md, Budget). Reads only; changes nothing.
set -eu

fail() { echo "preprovision: $1" >&2; exit 1; }

: "${AZURE_ENV_NAME:?azd env new <name> first}"
[ -n "${AZURE_RESOURCE_GROUP:-}" ] || fail "azd env set AZURE_RESOURCE_GROUP <group> (the demo uses ninety-labs)"
[ -n "${BUDGET_EMAIL:-}" ] || [ "${BUDGET_AMOUNT:-20}" = 0 ] || fail "azd env set BUDGET_EMAIL <address>: the \$20 budget alert emails it (infra/README.md)"

vault=$(az keyvault list -g "$AZURE_RESOURCE_GROUP" \
  --query "[?tags.\"azd-env-name\"=='$AZURE_ENV_NAME'].id | [0]" -o tsv 2>/dev/null || true)

for pair in mcp-key:MCP_KEY demo-passcode:DEMO_PASSCODE; do
  secret=${pair%%:*}
  var=${pair#*:}
  eval "value=\${$var:-}"
  [ -n "$value" ] && continue
  # Management-plane metadata only: whether the secret exists, never its value.
  if [ -z "$vault" ] || ! az resource show --ids "$vault/secrets/$secret" --query id -o tsv >/dev/null 2>&1; then
    fail "no '$secret' in Key Vault yet: azd env set $var \"\$(openssl rand -hex 32)\" for this one provision, then azd env set $var \"\" (infra/README.md)"
  fi
done
echo "preprovision: secrets in Key Vault, budget alert to be set; provisioning $AZURE_ENV_NAME into $AZURE_RESOURCE_GROUP"
