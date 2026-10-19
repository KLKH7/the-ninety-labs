"""infra/check_truth_sealed.py: only the render job and the maintainer reader may reach the storage
holding the ground truth. Templates here are small compiled-ARM shapes, so no Bicep is needed."""

import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "check_truth_sealed", Path(__file__).parents[1] / "infra" / "check_truth_sealed.py"
)
check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check)

STORAGE = "[resourceId('Microsoft.Storage/storageAccounts', format('stninety{0}', variables('token')))]"
REGISTRY = "[resourceId('Microsoft.ContainerRegistry/registries', format('crninety{0}', variables('token')))]"


def identity(name):
    kind = "Microsoft.ManagedIdentity/userAssignedIdentities"
    resource = f"resourceId('{kind}', format('{name}-{{0}}', variables('token')))"
    return f"[reference({resource}, '2023-01-31').principalId]"


def role(scope, principal, name="r"):
    return {
        "type": "Microsoft.Authorization/roleAssignments",
        "name": name,
        "scope": scope,
        "properties": {"principalId": principal},
    }


def template(*resources):
    return {"resources": list(resources)}


def test_the_render_job_and_the_maintainer_may_reach_the_truth():
    t = template(
        role(STORAGE, identity("id-render")), role(STORAGE, "[parameters('renderReaderPrincipalId')]")
    )
    assert check.violations(t) == []


def test_the_api_may_not_reach_the_truth():
    assert len(check.violations(template(role(STORAGE, identity("id-api"))))) == 1


def test_a_role_elsewhere_is_not_about_the_truth():
    assert check.violations(template(role(REGISTRY, identity("id-api")))) == []


def test_a_role_hidden_in_a_module_is_found():
    module = {
        "type": "Microsoft.Resources/deployments",
        "properties": {"template": template(role(STORAGE, "[parameters('someoneElse')]"))},
    }
    assert len(check.violations(template(module))) == 1


TEST_TRUTH = {
    "type": "Microsoft.Storage/storageAccounts/blobServices/containers",
    "name": "[format('{0}/{1}/{2}', format('stninety{0}', variables('token')), 'default', 'truth-test')]",
    "properties": {"publicAccess": "None"},
}


def test_the_test_truth_is_a_private_container_of_its_own(tmp_path):
    assert check.test_truth_violations(template(TEST_TRUTH), tmp_path) == []
    assert check.test_truth_violations(template(), tmp_path) == ["no 'truth-test' container in the template"]
    public = {**TEST_TRUTH, "properties": {"publicAccess": "Blob"}}
    assert len(check.test_truth_violations(template(public), tmp_path)) == 1


def test_no_role_is_scoped_to_the_test_truth(tmp_path):
    kind = "Microsoft.Storage/storageAccounts/blobServices/containers"
    scope = f"[resourceId('{kind}', 'x', 'default', 'truth-test')]"
    t = template(TEST_TRUTH, role(scope, "[parameters('renderReaderPrincipalId')]"))
    assert len(check.test_truth_violations(t, tmp_path)) == 1


def test_a_training_file_naming_the_test_truth_fails(tmp_path):
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "train.sh").write_text("link truth\n")
    assert check.test_truth_violations(template(TEST_TRUTH), tmp_path) == []
    (tmp_path / "scripts" / "train.sh").write_text("link truth-test\n")
    assert len(check.test_truth_violations(template(TEST_TRUTH), tmp_path)) == 1


def test_this_repo_has_no_training_link_to_the_test_truth():
    root = Path(__file__).parents[1]
    assert [v for v in check.test_truth_violations(template(TEST_TRUTH), root) if "names" in v] == []
