"""Record an evaluation we computed in Microsoft Foundry, so every run sits in the project's
Evaluations page next to the agents it measured, and runs of the same evaluation build a history.

Our evaluations decide right and wrong in code (a planted false claim must be rejected); Foundry's
`string_check` grader then compares each item's outcome with its expected one, so the pass counts
in Foundry are the same numbers as in our report, not a second opinion.
"""

from __future__ import annotations

import hashlib
import json
import time

from ninety import config


def criteria_key(criteria: list[dict], schema: dict) -> str:
    body = json.dumps({"criteria": criteria, "schema": schema}, sort_keys=True)
    return hashlib.sha256(body.encode()).hexdigest()[:16]


def equals(name: str, field: str, reference: str) -> dict:
    """A grader that passes an item when `item.<field>` equals `item.<reference>`."""
    return {
        "type": "string_check",
        "name": name,
        "input": "{{item." + field + "}}",
        "reference": "{{item." + reference + "}}",
        "operation": "eq",
    }


def string_schema(fields: list[str]) -> dict:
    return {
        "type": "object",
        "properties": {f: {"type": "string"} for f in fields},
        "required": fields,
    }


def find_or_create_eval(openai_client, name: str, criteria: list[dict], schema: dict):
    """Reuse the evaluation with this name and these graders, so its runs form one history; a
    change to the graders or the item shape starts a new evaluation rather than mixing them."""
    key = criteria_key(criteria, schema)
    for existing in openai_client.evals.list(limit=100):
        if existing.name == name and (existing.metadata or {}).get("criteria_key") == key:
            return existing
    return openai_client.evals.create(
        name=name,
        metadata={"criteria_key": key},
        data_source_config={"type": "custom", "item_schema": schema, "include_sample_schema": False},
        testing_criteria=criteria,
    )


def record(
    name: str,
    run_name: str,
    items: list[dict[str, str]],
    criteria: list[dict],
    poll_seconds: float = 3,
    timeout_seconds: float = 600,
    project=None,
) -> dict:
    """Upload `items` as one run of evaluation `name`, wait for Foundry to grade it, and return
    the counts per grader and the link to the run."""
    if project is None:
        from azure.ai.projects import AIProjectClient
        from azure.identity import DefaultAzureCredential

        project = AIProjectClient(endpoint=config.FOUNDRY_PROJECT, credential=DefaultAzureCredential())
    schema = string_schema(sorted({k for item in items for k in item}))
    client = project.get_openai_client()
    evaluation = find_or_create_eval(client, name, criteria, schema)
    run = client.evals.runs.create(
        eval_id=evaluation.id,
        name=run_name,
        data_source={
            "type": "jsonl",
            "source": {"type": "file_content", "content": [{"item": item} for item in items]},
        },
    )
    deadline = time.monotonic() + timeout_seconds
    while run.status not in ("completed", "failed", "canceled"):
        if time.monotonic() > deadline:
            raise TimeoutError(f"Foundry evaluation run {run.id} still {run.status}")
        time.sleep(poll_seconds)
        run = client.evals.runs.retrieve(run_id=run.id, eval_id=evaluation.id)
    if run.status != "completed":
        raise RuntimeError(f"Foundry evaluation run {run.id} {run.status}: {run.error}")
    return {
        "report_url": run.report_url,
        "total": run.result_counts.total,
        "per_criterion": {
            c.testing_criteria: {"passed": c.passed, "failed": c.failed, "errored": c.errored}
            for c in run.per_testing_criteria_results or []
        },
    }
