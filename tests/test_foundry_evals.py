"""Recording our evaluations in Foundry: the items say what should have happened and what did,
and Foundry's graders compare the two. Runs against a fake Foundry client, no Azure needed."""

from types import SimpleNamespace

import pytest

from ninety.agents import foundry_evals
from ninety.agents.analyst_eval import report as analyst_report
from ninety.agents.factcheck import Claim
from ninety.eval.factcheck_eval import FOUNDRY_CRITERIA, foundry_item
from ninety.eval.factcheck_eval import report as factcheck_report


def row(true: bool, code_ok: bool, judge_ok, category=None):
    return {
        "kind": "k",
        "seed": 21,
        "true": true,
        "claim": Claim("h7 passes to h9.", ["e1"]),
        "code_ok": code_ok,
        "judge_ok": judge_ok,
        "reasons": [] if judge_ok else ["why"],
        "category": category,
    }


def test_a_caught_false_claim_is_correct_and_a_rejected_true_claim_is_not():
    caught = foundry_item(row(true=False, code_ok=True, judge_ok=False))
    assert caught["expected"] == caught["verdict"] == "reject" and caught["code_alone"] == "accept"
    wrongly = foundry_item(row(true=True, code_ok=True, judge_ok=False))
    assert wrongly["expected"] == "accept" and wrongly["verdict"] == "reject"


def test_a_judge_outage_holds_the_claim_back():
    # Fail closed: a held claim is a rejection, so a true claim held by a timeout counts as wrong.
    held = foundry_item(row(true=True, code_ok=True, judge_ok=False, category="timeout"))
    assert held["verdict"] == "reject" and held["expected"] == "accept"


def test_a_code_rejection_never_reaches_the_judge_and_is_a_rejection():
    item = foundry_item(row(true=False, code_ok=False, judge_ok=None))
    assert item["code_alone"] == item["verdict"] == "reject"


def test_graders_compare_each_verdict_with_the_expected_one():
    names = {c["name"]: c for c in FOUNDRY_CRITERIA}
    assert names["fact-checker correct"]["input"] == "{{item.verdict}}"
    assert names["code checks alone correct"]["input"] == "{{item.code_alone}}"
    assert all(c["reference"] == "{{item.expected}}" and c["operation"] == "eq" for c in FOUNDRY_CRITERIA)


class FakeEvals:
    def __init__(self, existing=(), status="completed"):
        self.existing, self.created, self.status = list(existing), [], status
        self.runs = SimpleNamespace(create=self._create_run, retrieve=self._retrieve)

    def list(self, limit):
        return self.existing

    def create(self, name, metadata, data_source_config, testing_criteria):
        made = SimpleNamespace(id=f"eval{len(self.created)}", name=name, metadata=metadata)
        self.created.append((made, data_source_config, testing_criteria))
        return made

    def _create_run(self, eval_id, name, data_source):
        self.last_run = (eval_id, name, data_source)
        return SimpleNamespace(id="run1", status="in_progress")

    def _retrieve(self, run_id, eval_id):
        return SimpleNamespace(
            id=run_id,
            status=self.status,
            report_url="https://ai.azure.com/x",
            error="boom",
            result_counts=SimpleNamespace(total=2),
            per_testing_criteria_results=[
                SimpleNamespace(testing_criteria="c", passed=1, failed=1, errored=0)
            ],
        )


def project_with(evals):
    return SimpleNamespace(get_openai_client=lambda: SimpleNamespace(evals=evals))


ITEMS = [{"verdict": "accept", "expected": "accept"}, {"verdict": "reject", "expected": "accept"}]
CRITERIA = [foundry_evals.equals("c", "verdict", "expected")]


def test_record_uploads_every_item_and_returns_foundrys_counts():
    evals = FakeEvals()
    out = foundry_evals.record(
        "ninety-x", "run", ITEMS, CRITERIA, poll_seconds=0, project=project_with(evals)
    )
    eval_id, _, source = evals.last_run
    assert eval_id == "eval0" and [c["item"] for c in source["source"]["content"]] == ITEMS
    assert out == {
        "report_url": "https://ai.azure.com/x",
        "total": 2,
        "per_criterion": {"c": {"passed": 1, "failed": 1, "errored": 0}},
    }


def test_runs_of_the_same_evaluation_share_one_history():
    schema = foundry_evals.string_schema(["expected", "verdict"])
    same = SimpleNamespace(
        id="old", name="ninety-x", metadata={"criteria_key": foundry_evals.criteria_key(CRITERIA, schema)}
    )
    evals = FakeEvals(existing=[same])
    foundry_evals.record("ninety-x", "run", ITEMS, CRITERIA, poll_seconds=0, project=project_with(evals))
    assert evals.created == [] and evals.last_run[0] == "old"


def test_changed_graders_start_a_new_evaluation():
    stale = SimpleNamespace(id="old", name="ninety-x", metadata={"criteria_key": "different"})
    evals = FakeEvals(existing=[stale])
    foundry_evals.record("ninety-x", "run", ITEMS, CRITERIA, poll_seconds=0, project=project_with(evals))
    assert len(evals.created) == 1 and evals.last_run[0] == "eval0"


def test_a_failed_foundry_run_is_an_error_not_a_result():
    evals = FakeEvals(status="failed")
    with pytest.raises(RuntimeError, match="failed"):
        foundry_evals.record("ninety-x", "run", ITEMS, CRITERIA, poll_seconds=0, project=project_with(evals))


def test_reports_name_the_agent_versions_and_link_the_foundry_run():
    run = {
        "report_url": "https://ai.azure.com/r",
        "total": 1,
        "per_criterion": {"fact-checker correct": {"passed": 1, "failed": 0, "errored": 0}},
    }
    judge1 = {"ninety-judge": {"version": "1", "definition_sha": "3eea4db1096b7a49"}}
    rows = [row(true=False, code_ok=True, judge_ok=False)]
    text = factcheck_report(rows, "21", "`ninety-judge:1`", run, defs=judge1)
    assert "judge `ninety-judge:1`" in text and "(https://ai.azure.com/r)" in text
    assert "fact-checker correct 1/1" in text

    drafts = [{"seed": 21, "minute": 1, "claim": "a | b", "verdict": "reject", "reasons": ["x"]}]
    analyst2 = {"ninety-analyst": {"version": "2", "definition_sha": "ac3506fea4a55bf5"}, **judge1}
    text = analyst_report(drafts, "21", "ninety-analyst:2, ninety-judge:1", None, None, defs=analyst2)
    assert "**First drafts that would air:** 0/1." in text and "ninety-analyst:2" in text
    assert "a / b" in text  # a pipe in a claim cannot break the table
