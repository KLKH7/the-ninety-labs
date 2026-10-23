"""A live evaluation that measured an outage writes no report (lesson 131), so the nightly cannot
archive one: the fact-checker's and the Analyst's, like the Personalizer's."""

import sys

import pytest

from ninety.agents import analyst_eval as ae
from ninety.agents import evidence
from ninety.agents.factcheck import Claim
from ninety.eval import factcheck_eval as fe

DEFS = {"ninety-judge": {"version": "4", "definition_sha": "2b04c8ad1ac3c950"}}


def claim_row(category=None, code_ok=True):
    return {
        "kind": "false: wrong number",
        "true": False,
        "claim": Claim("h7 passes.", ["e1"]),
        "evidence": [],
        "seed": 21,
        "code_ok": code_ok,
        "judge_ok": None if not code_ok else False,
        "reasons": [],
        "category": category,
    }


def run_fact_checker(monkeypatch, tmp_path, rows):
    async def run(seeds, minutes, concurrency, local):
        return rows, "`ninety-judge:4` on `gpt-4.1-mini`", DEFS

    monkeypatch.setattr(fe, "run", run)
    monkeypatch.setattr(sys, "argv", ["factcheck_eval", "--seeds", "21", "--out", str(tmp_path / "f.md")])
    fe.main()


def test_a_fact_checker_run_in_which_the_judge_never_answered_writes_nothing(monkeypatch, tmp_path):
    rows = [claim_row("service") for _ in range(8)] + [claim_row(code_ok=False)] * 4
    with pytest.raises(evidence.NothingMeasured, match="did not answer 8 of 8 claims sent to the Judge"):
        run_fact_checker(monkeypatch, tmp_path, rows)
    assert not (tmp_path / "f.md").exists() and not (tmp_path / "f.json").exists()


def test_a_fact_checker_run_with_a_few_service_holds_still_reports(monkeypatch, tmp_path):
    # One timeout in ten is under the threshold (four answers in five), and is counted apart.
    rows = [claim_row("timeout")] + [claim_row("unsupported_claim") for _ in range(9)]
    run_fact_checker(monkeypatch, tmp_path, rows)
    assert evidence.read(tmp_path / "f.md", tmp_path) == (
        [evidence.Ran("ninety-judge", "4", "2b04c8ad1ac3c950")],
        "recorded",
    )
    assert "held by a service/timeout error, not judged: 1" in (tmp_path / "f.md").read_text()


def test_the_threshold_is_four_answers_in_five_and_nothing_asked_is_nothing_measured():
    evidence.refuse_outage(2, 10, "x")  # exactly 20% unanswered: reported
    with pytest.raises(evidence.NothingMeasured):
        evidence.refuse_outage(3, 10, "x")
    with pytest.raises(evidence.NothingMeasured):
        evidence.refuse_outage(0, 0, "x")  # every claim stopped by the code: the Judge was not measured


def draft(text="{}", category=None):
    return {
        "seed": 21,
        "minute": 1,
        "response_id": "r",
        "text": text,
        "claim": "c",
        "verdict": "reject",
        "reasons": [],
        "category": category,
    }


def run_analyst(monkeypatch, tmp_path, rows):
    async def drafts(seeds):
        return rows, "ninety-analyst:5, ninety-judge:4", DEFS

    monkeypatch.setattr(ae, "drafts", drafts)
    monkeypatch.setattr(sys, "argv", ["analyst_eval", "--seeds", "21", "--out", str(tmp_path / "a.md")])
    ae.main()


def test_an_analyst_run_in_which_the_models_never_answered_writes_nothing(monkeypatch, tmp_path):
    rows = [draft(category="service")] * 5 + [draft(text="")] * 5  # Judge down, Analyst silent
    with pytest.raises(evidence.NothingMeasured, match="did not answer 10 of 10 minutes"):
        run_analyst(monkeypatch, tmp_path, rows)
    assert not (tmp_path / "a.md").exists()
    run_analyst(monkeypatch, tmp_path, [draft()] * 9 + [draft(text="")])  # one silent minute in ten
    assert (tmp_path / "a.md").exists()


def test_a_live_writer_cannot_leave_out_its_definitions():
    with pytest.raises(ValueError, match="which agent definitions"):
        evidence.md_line(None)
    with pytest.raises(TypeError):
        fe.report([claim_row("unsupported_claim")], "21", "`ninety-judge:4`")  # defs is required
