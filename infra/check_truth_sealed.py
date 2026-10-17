"""Fail if anything on the live path could read the ground truth.

The answer key (events.jsonl and frames.jsonl of every clip) lives in the `truth` container of
the render storage account (infra/main.bicep, ninety/render/job.py). Only the render job, which
writes it, and the maintainer reader, who trains and scores with it, may hold a role that reaches
it; a role on the storage account reaches every container in it. This reads the compiled template,
nested modules included, and lists every role assignment scoped to the storage account or one of
its containers whose principal is not one of those two.

    az bicep build --file infra/main.bicep --stdout > arm.json
    python3 infra/check_truth_sealed.py arm.json
"""

from __future__ import annotations

import json
import sys
from collections.abc import Iterator

# How the compiled template names the two principals allowed to read the truth.
ALLOWED = (
    "format('id-render-{0}'",  # the render job's user-assigned identity
    "parameters('renderReaderPrincipalId')",  # the maintainer who trains and scores
)
STORAGE = "Microsoft.Storage/storageAccounts"


def role_assignments(template: dict) -> Iterator[dict]:
    resources = template.get("resources", [])
    for resource in resources.values() if isinstance(resources, dict) else resources:
        if resource.get("type") == "Microsoft.Authorization/roleAssignments":
            yield resource
        nested = resource.get("properties", {}).get("template")
        if resource.get("type") == "Microsoft.Resources/deployments" and nested:
            yield from role_assignments(nested)


def violations(template: dict) -> list[str]:
    found = []
    for assignment in role_assignments(template):
        scope = str(assignment.get("scope", ""))
        if STORAGE not in scope:
            continue
        principal = str(assignment.get("properties", {}).get("principalId", ""))
        if not any(allowed in principal for allowed in ALLOWED):
            found.append(f"{assignment.get('name')}: principal {principal} on {scope}")
    return found


def main() -> None:
    template = json.load(open(sys.argv[1]) if len(sys.argv) > 1 else sys.stdin)
    bad = violations(template)
    for line in bad:
        print(f"truth not sealed: {line}")
    if bad:
        sys.exit(1)
    n = sum(STORAGE in str(a.get("scope", "")) for a in role_assignments(template))
    print(f"truth sealed: {n} storage role assignment(s), all to the render job or the maintainer reader")


if __name__ == "__main__":
    main()
