"""The nightly's reports become committed evidence only if they say what they measured
(ninety/eval/nightly.py, .github/workflows/evals.yml)."""

import json

import pytest
import yaml

from ninety.agents import evidence
from ninety.eval import nightly

DEFS = {"ninety-judge": {"version": "4", "definition_sha": "2b04c8ad1ac3c950"}}


def nightly_output(tmp_path, defs=DEFS):
    src = tmp_path / "runs" / "eval"
    src.mkdir(parents=True)
    (src / "fact-checker.md").write_text(
        f"# Fact-checker evaluation\n\n{evidence.md_line(defs)}\n\n## Every miss\n"
    )
    (src / "fact-checker.json").write_text(json.dumps([{"kind": "x"}]))  # list-shaped: its .md says
    (src / "companion.md").write_text(f"# Companion evaluation\n\n{evidence.md_line(defs)}\n")
    (src / "analyst.md").write_text(f"# Analyst evaluation\n\n{evidence.md_line(defs)}\n")  # INVALID
    return src


def test_reports_are_copied_unedited_to_a_dated_folder_and_the_invalid_one_is_not(tmp_path):
    src = nightly_output(tmp_path)
    copied = nightly.archive(src, "2026-10-24", tmp_path / "nightly")
    assert sorted(p.name for p in copied) == ["companion.md", "fact-checker.json", "fact-checker.md"]
    for p in copied:
        assert p.parent == tmp_path / "nightly" / "2026-10-24"
        assert p.read_bytes() == (src / p.name).read_bytes()
    assert not (tmp_path / "nightly" / "2026-10-24" / "analyst.md").exists()  # lesson 90, until #252
    assert nightly.skipped(src) == ["analyst.md"]
    with pytest.raises(FileExistsError):  # one archive a night, never overwritten
        nightly.archive(src, "2026-10-24", tmp_path / "nightly")


def test_a_report_without_fingerprints_is_not_archived(tmp_path):
    src = nightly_output(tmp_path)
    (src / "companion.md").write_text("agents ninety-companion:1, ninety-judge:4 on gpt-4.1-mini\n")
    with pytest.raises(nightly.NotEvidence, match="companion.md: names agent versions but no definition"):
        nightly.archive(src, "2026-10-24", tmp_path / "nightly")
    (src / "companion.md").write_text("# no agents named\n")
    with pytest.raises(nightly.NotEvidence, match="companion.md: names no agent definition"):
        nightly.archive(src, "2026-10-24", tmp_path / "nightly")
    assert not (tmp_path / "nightly").exists()  # nothing half-copied


def test_a_report_with_a_null_fingerprint_is_not_archived(tmp_path):
    src = nightly_output(tmp_path)
    (src / "companion.json").write_text(
        json.dumps({evidence.KEY: {"ninety-companion": {"version": "1", "definition_sha": None}}})
    )
    with pytest.raises(nightly.NotEvidence, match="companion.json: an agent without a fingerprint"):
        nightly.archive(src, "2026-10-24", tmp_path / "nightly")


def test_a_report_whose_line_omits_an_agent_it_names_is_not_archived(tmp_path):
    src = nightly_output(tmp_path)
    (src / "companion.md").write_text(f"# Companion, judged by `ninety-judge:4`\n\n{evidence.md_line({})}\n")
    with pytest.raises(nightly.NotEvidence, match="companion.md: an agent without a fingerprint"):
        nightly.archive(src, "2026-10-24", tmp_path / "nightly")


def test_an_empty_run_is_not_archived(tmp_path):
    (tmp_path / "empty").mkdir()
    with pytest.raises(nightly.NotEvidence, match="no reports"):
        nightly.archive(tmp_path / "empty", "2026-10-24", tmp_path / "nightly")


def test_the_pr_body_quotes_each_header_and_names_the_skipped_report(tmp_path):
    src = nightly_output(tmp_path)
    copied = nightly.archive(src, "2026-10-24", tmp_path / "nightly")
    text = nightly.body(copied, "2026-10-24", "https://github.com/x/actions/runs/1", nightly.skipped(src))
    assert "# Fact-checker evaluation" in text and "Every miss" not in text
    assert "Not archived: `analyst.md`, invalid:" in text and "lesson 90" in text
    assert "# Analyst evaluation" not in text
    assert "([run](https://github.com/x/actions/runs/1))" in text


def test_an_archived_nightly_passes_the_stale_check_and_one_with_labels_only_does_not(tmp_path):
    root = tmp_path / "repo"
    copied = nightly.archive(nightly_output(tmp_path), "2026-10-24", root / evidence.NIGHTLY)
    old = {"ninety-judge": "0000000000000000"}  # the Judge has changed since that night
    assert copied and evidence.problems(evidence.survey(root, old), stale={}) == []
    (root / evidence.NIGHTLY / "2026-10-24" / "analyst.md").write_text("ninety-analyst:5\n")
    assert len(evidence.problems(evidence.survey(root, old), stale={})) == 1


def test_the_workflow_commits_through_a_pull_request_never_to_main():
    flow = yaml.safe_load((nightly.ROOT / ".github/workflows/evals.yml").read_text())
    commit = flow["jobs"]["commit"]
    assert commit["needs"] == "evals" and commit["if"] == "needs.evals.result == 'success'"
    # The job that can push holds no Azure sign-in, and the job that signs in cannot push.
    assert commit["permissions"] == {"contents": "write", "pull-requests": "write"}
    assert flow["permissions"] == {"id-token": "write", "contents": "read"}
    assert "permissions" not in flow["jobs"]["evals"]
    script = "\n".join(s.get("run", "") for s in commit["steps"])
    assert "azure/login" not in json.dumps(commit)
    assert 'git push origin "$branch"' in script and "gh pr create --base main" in script
    assert "push origin main" not in script and "HEAD:main" not in script


def test_a_night_already_archived_stops_before_any_model_call():
    # A re-run the same night would fail at `git push` after spending on the models (review of #248).
    flow = yaml.safe_load((nightly.ROOT / ".github/workflows/evals.yml").read_text())
    steps = flow["jobs"]["evals"]["steps"]
    first_model = next(i for i, s in enumerate(steps) if "azure/login" in s.get("uses", ""))
    guard = next(
        i for i, s in enumerate(steps) if "git ls-remote --exit-code --heads origin" in s.get("run", "")
    )
    assert guard < first_model and '"nightly/evals-$night"' in steps[guard]["run"]
    assert "exit 1" in steps[guard]["run"]
    assert '[ -e "docs/eval/nightly/$night" ]' in steps[guard]["run"]  # nor one already merged
    # The commit job archives under the night the guard checked, not a date of its own.
    assert flow["jobs"]["commit"]["env"]["NIGHT"] == "${{ needs.evals.outputs.night }}"
    assert flow["jobs"]["evals"]["outputs"]["night"] == "${{ steps.night.outputs.night }}"
