"""Committed agent evidence says which agent definitions produced it, and still describes the code.

Every report in docs/eval/ and every replay in replays/ that a published agent produced names the
definition of each agent it ran with (ninety/agents/evidence.py). A file whose agents changed
since fails here, unless `evidence.STALE` lists it with why and the run that replaces it (lesson
216). No Azure: the definitions are built from the code, as tests/test_foundry_agents.py does.
"""

import json
import shutil
import subprocess

import pytest

from ninety.agents import evidence, foundry

NOW = evidence.current()
SURVEY = evidence.survey(now=NOW)
BY_PATH = {e.path: e for e in SURVEY}


def test_every_committed_piece_of_agent_evidence_is_fresh_or_listed_as_stale_with_a_reason():
    assert evidence.problems(SURVEY) == []


def test_the_survey_finds_the_reports_and_replays_it_must():
    # The scan is what makes the check bite: a report it skips can never be stale (lesson 41).
    for path in (
        "docs/eval/fact-checker.md",
        "docs/eval/fact-checker.json",
        "docs/eval/analyst.md",
        "docs/eval/personalizer.md",
        "docs/eval/ablation-agents.json",
        "docs/eval/ablation-agents.md",
        "docs/eval/planted-claims-v1-judge.json",
        "replays/slice-minute2-plant.json",
        "replays/workflow-minute2-plant.json",
    ):
        assert path in BY_PATH, path
    # Offline reports with scripted models name no published agent.
    assert "docs/eval/failure-table.json" not in BY_PATH and "docs/eval/companion.json" not in BY_PATH


def test_older_files_are_read_through_the_registry_history():
    # Written before fingerprints: their labels map to the fingerprint each version was published
    # from. The Oct 17 fact-checker run used judge:1; the workflow replay records `pins`.
    assert BY_PATH["docs/eval/fact-checker.md"].ran == [evidence.Ran("ninety-judge", "1", "3eea4db1096b7a49")]
    assert BY_PATH["docs/eval/fact-checker.json"].source == "data of docs/eval/fact-checker.md"
    workflow = BY_PATH["replays/workflow-minute2-plant.json"]
    assert workflow.source == "derived" and workflow.fresh
    assert {r.name for r in workflow.ran} == {
        "ninety-moment-analyst",
        "ninety-tactician",
        "ninety-challenger",
        "ninety-judge",
    }


def test_the_history_agrees_with_the_registry_it_was_read_from():
    # A version the registry pins now must map to the same fingerprint in the history.
    for name, entry in foundry.load_registry().items():
        if (name, entry["version"]) in evidence.HISTORY:
            assert evidence.HISTORY[name, entry["version"]] == entry["definition_sha"], name


# The check must be able to fail (lesson 8): planted in copies, never in the committed files.


def copy_of(tmp_path, *paths):
    for path in paths:
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(evidence.ROOT / path, tmp_path / path)
    return tmp_path


def recorded_report(tmp_path, path, sha):
    body = {"arms": {}, evidence.KEY: {"ninety-judge": {"version": "4", "definition_sha": sha}}}
    (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / path).write_text(json.dumps(body))


def test_a_report_recorded_with_another_definition_fails(tmp_path):
    recorded_report(tmp_path, "docs/eval/new.json", NOW["ninety-judge"])
    assert evidence.problems(evidence.survey(tmp_path, NOW), stale={}) == []
    recorded_report(tmp_path, "docs/eval/new.json", "0123456789abcdef")
    (problem,) = evidence.problems(evidence.survey(tmp_path, NOW), stale={})
    assert "docs/eval/new.json: changed since it ran: ninety-judge:4 (0123456789abcdef)" in problem


def test_a_markdown_report_with_a_changed_definition_fails(tmp_path):
    defs = {"ninety-judge": {"version": "4", "definition_sha": NOW["ninety-judge"]}}
    path = tmp_path / "docs/eval/r.md"
    path.parent.mkdir(parents=True)
    path.write_text(f"# R\n\n{evidence.md_line(defs)}\n")
    assert evidence.read(path, tmp_path) == (
        [evidence.Ran("ninety-judge", "4", NOW["ninety-judge"])],
        "recorded",
    )
    assert evidence.problems(evidence.survey(tmp_path, NOW), stale={}) == []
    path.write_text(path.read_text().replace(NOW["ninety-judge"], "fedcba9876543210"))
    assert len(evidence.problems(evidence.survey(tmp_path, NOW), stale={})) == 1


def test_a_replay_whose_agent_changed_fails(tmp_path):
    root = copy_of(tmp_path, "replays/workflow-minute2-plant.json")
    assert evidence.problems(evidence.survey(root, NOW), stale={}) == []
    changed = {**NOW, "ninety-tactician": "0000000000000000"}  # the Tactician's prompt changed
    (problem,) = evidence.problems(evidence.survey(root, changed), stale={})
    assert problem.startswith("replays/workflow-minute2-plant.json: changed since it ran: ninety-tactician:2")


def test_a_version_no_registry_pinned_is_unknown_and_fails(tmp_path):
    path = tmp_path / "docs/eval/old.md"
    path.parent.mkdir(parents=True)
    path.write_text("Generated with `ninety-judge:9` on gpt-4.1-mini.\n")
    (problem,) = evidence.problems(evidence.survey(tmp_path, NOW), stale={})
    assert "no known fingerprint: ninety-judge:9" in problem


def test_a_listed_stale_file_passes_but_a_listing_without_a_reason_or_a_fresh_listing_fails(tmp_path):
    root = copy_of(tmp_path, "docs/eval/fact-checker.md")
    survey = evidence.survey(root, NOW)
    assert len(evidence.problems(survey, stale={})) == 1  # judge:1 is not the Judge now
    listed = {"docs/eval/fact-checker.md": {"why": "x", "rerun": "y"}}
    assert evidence.problems(survey, stale=listed) == []
    assert (
        "without both a reason"
        in evidence.problems(survey, stale={"docs/eval/fact-checker.md": {"why": "x"}})[0]
    )
    # Once re-run on the current Judge, the listing must go.
    now_judge_1 = {**NOW, "ninety-judge": "3eea4db1096b7a49"}
    assert "fresh now: remove it" in evidence.problems(evidence.survey(root, now_judge_1), stale=listed)[0]
    assert "not agent evidence" in evidence.problems([], stale=listed)[0]


def test_a_nightly_archive_is_history_but_must_record_its_definitions(tmp_path):
    recorded_report(tmp_path, "docs/eval/nightly/2026-10-24/fact-checker.json", "0123456789abcdef")
    assert evidence.problems(evidence.survey(tmp_path, NOW), stale={}) == []  # an old run is not stale
    path = tmp_path / "docs/eval/nightly/2026-10-24/analyst.md"
    path.write_text("agents ninety-analyst:5, ninety-judge:4 on gpt-4.1-mini\n")  # labels only
    (problem,) = evidence.problems(evidence.survey(tmp_path, NOW), stale={})
    assert "must record its agent definitions" in problem


def test_the_md_line_and_the_reader_agree_for_local_and_empty_definitions(tmp_path):
    path = tmp_path / "x.md"
    path.write_text(evidence.md_line({}) + "\n")
    assert evidence.read(path, tmp_path) == ([], "recorded")
    path.write_text(evidence.md_line({"ninety-judge": {"version": None, "definition_sha": "a" * 16}}) + "\n")
    assert evidence.read(path, tmp_path) == ([evidence.Ran("ninety-judge", None, "a" * 16)], "recorded")


def test_a_recording_made_before_fingerprints_is_read_from_its_labels(tmp_path):
    root = copy_of(tmp_path, "replays/slice-minute2-plant.json")
    data = json.loads((root / "replays/slice-minute2-plant.json").read_text())
    assert data.get(evidence.KEY) is None
    ran, source = evidence.read(root / "replays/slice-minute2-plant.json", root)
    assert source == "derived" and {r.name for r in ran} == {"ninety-analyst", "ninety-judge"}


@pytest.mark.parametrize("module", ["ninety.agents.evidence"])
def test_the_command_lists_every_file_and_exits_cleanly(module):
    done = subprocess.run(
        ["uv", "run", "python", "-m", module], cwd=evidence.ROOT, capture_output=True, text=True, timeout=300
    )
    assert done.returncode == 0, done.stderr
    assert "docs/eval/fact-checker.md: STALE, listed" in done.stdout
