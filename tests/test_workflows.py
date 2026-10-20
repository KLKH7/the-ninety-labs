"""Every shell script in our GitHub workflows parses (lesson 113).

A workflow's `run:` block is a shell script inside YAML: the YAML can load while the script is not
valid shell. The `agents-live` publish run for the Describer was approved, signed in to Azure,
and then failed on `syntax error near unexpected token ')'`, because a merge dropped the `;;`
closing one `case` branch. Nothing had run the script until a person approved a live run.
"""

import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

WORKFLOWS = sorted((Path(__file__).resolve().parents[1] / ".github" / "workflows").glob("*.yml"))
BASH = shutil.which("bash")


def scripts(path: Path) -> list[tuple[str, str]]:
    """(job and step name, script) for every `run:` step whose shell is bash (GitHub's default)."""
    workflow = yaml.safe_load(path.read_text())
    found = []
    for job_name, job in workflow.get("jobs", {}).items():
        default = (job.get("defaults") or {}).get("run", {}).get("shell", "bash")
        for i, step in enumerate(job.get("steps", [])):
            if "run" in step and step.get("shell", default).split()[0] == "bash":
                found.append((f"{job_name}/{step.get('name', i)}", step["run"]))
    return found


def bash_errors(script: str) -> str:
    done = subprocess.run([BASH, "-n"], input=script, capture_output=True, text=True)
    return done.stderr.strip() if done.returncode else ""


@pytest.mark.skipif(BASH is None, reason="bash is not installed")
@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
def test_every_workflow_script_is_valid_bash(path):
    errors = {name: e for name, script in scripts(path) if (e := bash_errors(script))}
    assert errors == {}


@pytest.mark.skipif(BASH is None, reason="bash is not installed")
def test_a_case_branch_without_its_double_semicolon_is_caught():
    # The defect as it shipped: one branch's `;;` lost in a merge.
    broken = 'case "$TASK" in\n  a)\n    echo a\n  b)\n    echo b\n    ;;\nesac\n'
    assert "syntax error" in bash_errors(broken)
    assert bash_errors(broken.replace("echo a\n", "echo a\n    ;;\n")) == ""


def test_the_agents_live_task_script_is_checked():
    names = [name for name, _ in scripts(next(p for p in WORKFLOWS if p.name == "agents-live.yml"))]
    assert any("Run the task" in name for name in names), names
