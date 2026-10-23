"""Fail if anything on the live path could read the ground truth.

The answer key (events.jsonl and frames.jsonl of every clip) lives in the `truth` container of
the render storage account (infra/main.bicep, ninety/render/job.py). Only the render job, which
writes it, and the maintainer reader, who trains and scores with it, may hold a role that reaches
it; a role on the storage account reaches every container in it. This reads the compiled template,
nested modules included, and lists every role assignment scoped to the storage account or one of
its containers whose principal is not one of those two.

The frozen test set's answer key lives apart, in `truth-test`: training machines get a read link to
`truth`, so the test labels must never be in it. This also fails if the template has no private
`truth-test` container, if any role is scoped to that container itself, or if a training file
(scripts/, ninety/vision/) names it, which is how a link to it would be made.

The render job decides which files go to `truth`: this also runs its upload (`upload_dir` in
ninety/render/job.py, read from the source so this needs nothing installed) on a planted clip with
the answer key at the top and under views/<name>/, and fails if any answer-key file lands in
`renders`, where the live path reads (lesson 192).

    az bicep build --file infra/main.bicep --stdout > arm.json
    python3 infra/check_truth_sealed.py arm.json
"""

from __future__ import annotations

import ast
import json
import sys
import tempfile
from collections.abc import Iterator
from pathlib import Path

# How the compiled template names the two principals allowed to read the truth.
ALLOWED = (
    "format('id-render-{0}'",  # the render job's user-assigned identity
    "parameters('renderReaderPrincipalId')",  # the maintainer who trains and scores
)
STORAGE = "Microsoft.Storage/storageAccounts"
CONTAINERS = "Microsoft.Storage/storageAccounts/blobServices/containers"
TEST_TRUTH = "truth-test"
# Where training links are made: a file here naming the test truth could hand it to a training machine.
TRAINING = ("scripts", "ninety/vision")


def role_assignments(template: dict) -> Iterator[dict]:
    resources = template.get("resources", [])
    for resource in resources.values() if isinstance(resources, dict) else resources:
        if resource.get("type") == "Microsoft.Authorization/roleAssignments":
            yield resource
        nested = resource.get("properties", {}).get("template")
        if resource.get("type") == "Microsoft.Resources/deployments" and nested:
            yield from role_assignments(nested)


def resources(template: dict) -> Iterator[dict]:
    items = template.get("resources", [])
    for resource in items.values() if isinstance(items, dict) else items:
        yield resource
        nested = resource.get("properties", {}).get("template")
        if resource.get("type") == "Microsoft.Resources/deployments" and nested:
            yield from resources(nested)


def test_truth_violations(template: dict, root: Path | None = None) -> list[str]:
    """The test set's answer key: a private container of its own, no role on it, no training link to it."""
    found = []
    containers = [
        r for r in resources(template) if r.get("type") == CONTAINERS and TEST_TRUTH in str(r.get("name"))
    ]
    if not containers:
        found.append(f"no '{TEST_TRUTH}' container in the template")
    for c in containers:
        access = c.get("properties", {}).get("publicAccess")
        if access != "None":
            found.append(f"'{TEST_TRUTH}' is not private: publicAccess {access}")
    for assignment in role_assignments(template):
        if TEST_TRUTH in str(assignment.get("scope", "")):
            found.append(f"{assignment.get('name')}: a role scoped to '{TEST_TRUTH}' itself")
    if root is not None:
        for top in TRAINING:
            for f in sorted((root / top).rglob("*")):
                if f.suffix not in (".py", ".sh", ".json") or not f.is_file():
                    continue
                if TEST_TRUTH in f.read_text(errors="ignore"):
                    found.append(f"{f.relative_to(root)} names '{TEST_TRUTH}': no training link to it")
    return found


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


UPLOAD = Path("ninety/render/job.py")
# Where a clip's answer key sits: its own, and each view's (ninety/render/clip.py views/<name>/).
PLANTED = ("frames.jsonl", "events.jsonl", "views/tac-l/frames.jsonl", "views/tac-l/events.jsonl",
           "views/tac-r/frames.jsonl", "views/tac-r/events.jsonl", "images/00000.jpg",
           "views/tac-l/images/00000.jpg", "clip.json")


class _Container:
    def __init__(self):
        self.names: list[str] = []

    def upload_blob(self, name, data, overwrite=False):
        self.names.append(name)


def upload_violations(root: Path) -> list[str]:
    """Run the render job's upload on a planted clip; list every answer-key file it sends to `renders`."""
    tree = ast.parse((root / UPLOAD).read_text())
    keep = [
        n for n in tree.body
        if (isinstance(n, ast.FunctionDef) and n.name in ("upload_dir", "blob_name"))
        or (isinstance(n, ast.Assign) and any(getattr(t, "id", "") == "TRUTH_FILES" for t in n.targets))
    ]
    if len(keep) != 3:
        return [f"{UPLOAD}: no TRUTH_FILES, blob_name and upload_dir to check"]
    namespace: dict = {"Path": Path}
    exec(compile(ast.Module(body=keep, type_ignores=[]), str(UPLOAD), "exec"), namespace)  # noqa: S102
    renders, truth = _Container(), _Container()
    with tempfile.TemporaryDirectory() as tmp:
        clip = Path(tmp) / "seed1"
        for rel in PLANTED:
            (clip / rel).parent.mkdir(parents=True, exist_ok=True)
            (clip / rel).write_text("{}")
        namespace["upload_dir"](renders, truth, "check", 1, clip)
    key = tuple(namespace["TRUTH_FILES"])
    found = [f"{UPLOAD} uploads the answer key {n} to renders" for n in renders.names if n.endswith(key)]
    sealed = [rel for rel in PLANTED if rel.endswith(key)]
    missing = [rel for rel in sealed if not any(n.endswith(rel) for n in truth.names)]
    found += [f"{UPLOAD} does not seal {rel}" for rel in missing]
    return found


def main() -> None:
    template = json.load(open(sys.argv[1]) if len(sys.argv) > 1 else sys.stdin)
    root = Path(__file__).resolve().parents[1]
    bad = violations(template) + test_truth_violations(template, root) + upload_violations(root)
    for line in bad:
        print(f"truth not sealed: {line}")
    if bad:
        sys.exit(1)
    n = sum(STORAGE in str(a.get("scope", "")) for a in role_assignments(template))
    print(f"truth sealed: {n} storage role assignment(s), all to the render job or the maintainer reader; "
          f"'{TEST_TRUTH}' private, with no role of its own and no training link; "
          f"the render job seals every answer-key file of a clip and its views")


if __name__ == "__main__":
    main()
