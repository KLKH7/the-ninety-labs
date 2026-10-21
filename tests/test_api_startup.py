"""The API's start-up loads no model SDK (lesson 104: checked in a fresh interpreter).

The live API scales to zero, and its cold start was about 50 s, about 33 s of it Python start-up
on a fractional vCPU. `import ninety.api.app` loaded the agent framework, the Foundry project
client, the OpenAI client and the blob storage SDK through ninety.agents.contracts -> slice; they
now load on first use (lesson 153). Measured on the dev Mac (Darwin arm64, Python 3.12), five fresh
interpreters each: 3.24 to 3.66 s (median 3.28) before, 0.97 to 1.17 s (median 1.00) after.
"""

import json
import subprocess
import sys

SDKS = ("agent_framework", "azure.ai.projects", "openai", "azure.storage.blob")


def loaded_after(statement: str) -> list[str]:
    code = f"import json, sys\n{statement}\nprint(json.dumps(sorted(sys.modules)))"
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


def test_importing_the_api_loads_no_model_sdk():
    modules = loaded_after("import ninety.api.app")
    assert "ninety.api.app" in modules
    assert [m for m in modules if any(m == sdk or m.startswith(sdk + ".") for sdk in SDKS)] == []


def test_the_check_sees_an_sdk_when_one_is_imported():
    # The same check goes red when the import is eager (the mutation lesson 104 asks for).
    modules = loaded_after("import ninety.api.app\nimport ninety.agents.slice")
    assert "agent_framework" in modules and "azure.ai.projects" in modules
