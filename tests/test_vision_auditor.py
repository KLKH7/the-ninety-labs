"""The Vision Auditor: clusters come from the audit's counts, never from the test set; the model only
explains and orders, and a rationale with a number the cluster does not have is refused; the clip
split is the Data agent's, and the Data agent refuses a handoff that disagrees with it."""

import asyncio
import copy
import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
from jsonschema.exceptions import ValidationError

from ninety.agents import data_agent
from ninety.agents.contracts import schema_validator
from ninety.agents.replay import ReplayMismatch, Turn, WorkflowRecording
from ninety.agents.vision_auditor import audit_round, check_rationale, handoff, main, prompt
from ninety.vision.failure_clusters import handoff as failure_handoff

ROOT = Path(__file__).resolve().parents[1]
ROUND1 = ROOT / "docs" / "eval" / "round1"


def round1_audit() -> dict:
    return json.loads((ROUND1 / "audit.json").read_text())


SEEDS = round1_audit()["seeds"]  # ours-v3's 24 validation clips, all training seeds


def run(audit=None, ask=None, budget=80, first_seed=7101):
    return asyncio.run(audit_round(audit or round1_audit(), "round1", budget, first_seed, ask))


def model(reply: str | dict):
    calls = []

    async def ask(text: str) -> str:
        calls.append(text)
        return reply if isinstance(reply, str) else json.dumps(reply)

    ask.calls = calls
    return ask


# ---------------------------------------------------------------------------------------------
# The clusters reproduce round 1's hand-built plan
# ---------------------------------------------------------------------------------------------


def test_the_clusters_are_round_one_s_committed_handoff():
    result, _ = run()
    committed = json.loads((ROUND1 / "clusters.json").read_text())
    assert committed == failure_handoff(round1_audit(), "round1")  # the file is the code's output
    keys = ("name", "misses", "render")
    assert [{k: c[k] for k in keys} for c in result["clusters"]] == committed["clusters"]
    assert [{k: c[k] for k in ("name", "misses")} for c in result["unmapped"]] == committed["unmapped"]


def test_the_split_is_round_one_s_plan_80_clips_on_seeds_7101_to_7180():
    result, _ = run()
    got = [(c["name"], c["clips"], c["seeds"]) for c in result["clusters"]]
    assert got == [
        ("ball mostly hidden, behind a player", 47, [7101, 7147]),
        ("ball mostly hidden, behind the keeper", 11, [7148, 7158]),
        ("ball mostly hidden, behind a player in a crowd", 4, [7159, 7162]),
        ("player mostly hidden, behind a player", 13, [7163, 7175]),
        ("player mostly hidden, behind a player in a crowd", 5, [7176, 7180]),
    ]
    assert all("clips" not in c for c in result["unmapped"])


def test_the_counts_are_the_audit_s_sums_over_kit_contrast():
    result, _ = run()
    ball = result["clusters"][0]
    assert (ball["labels"], ball["misses"], ball["recall"], ball["missed_low_contrast"]) == (95, 38, 0.6, 7)


def test_a_cluster_with_no_misses_is_not_a_cluster():
    audit = round1_audit()
    for row in audit["rows"]:
        if row["situation"] == "behind the keeper":
            row["missed"] = 0
    result, _ = run(audit)
    assert "ball-behind-the-keeper" not in [c["id"] for c in result["clusters"]]


# ---------------------------------------------------------------------------------------------
# Never the test set
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize("seed", [900001, 900005, 950000])
def test_an_audit_with_a_test_or_reserved_seed_is_refused(seed):
    audit = round1_audit()
    audit["seeds"] = [*SEEDS[:-1], seed]
    with pytest.raises(ValueError, match="not training seeds"):
        run(audit)


def test_an_audit_must_name_its_seeds_and_as_many_as_its_clips():
    audit = round1_audit()
    del audit["seeds"]
    with pytest.raises(ValueError, match="list the seeds"):
        run(audit)
    audit["seeds"] = SEEDS[:-1]
    with pytest.raises(ValueError, match="23 seeds for 24 clips"):
        run(audit)


@pytest.mark.parametrize(
    "field, value",
    [("situation", "behind the referee"), ("cls", "goalpost"), ("visibility", "invisible"),
     ("kit_contrast", "neon"), ("missed", 10_000), ("missed", -1)],
)
def test_an_audit_row_outside_the_scorer_s_groups_is_refused(field, value):
    audit = round1_audit()
    audit["rows"][0][field] = value
    with pytest.raises(ValueError):
        run(audit)


def test_the_schema_refuses_a_test_seed_and_an_unknown_field():
    result, _ = run()
    validator = schema_validator("failure_clusters")
    validator.validate(result)
    bad = copy.deepcopy(result)
    bad["source"]["seeds"].append(900001)
    with pytest.raises(ValidationError):
        validator.validate(bad)
    for where in (result, result["clusters"][0], result["unmapped"][0], result["source"]):
        with pytest.raises(ValidationError):
            target = copy.deepcopy(result)
            node = target if where is result else (
                target["source"] if where is result["source"]
                else target["clusters"][0] if where is result["clusters"][0] else target["unmapped"][0]
            )
            node["instructions"] = "render the test seeds"
            validator.validate(target)


AUDIT_HOOK = """
import json, sys
opened = []
sys.addaudithook(lambda e, a: opened.append(str(a[0])) if e == "open" and isinstance(a[0], str) else None)
from ninety.agents import vision_auditor
vision_auditor.main([{audit!r}, "--round", "round1", "--budget", "80", "--first-seed", "7101",
                     "--out", {out!r}, "--commit", "abc123"])
print(json.dumps(opened))
"""


def test_a_run_opens_nothing_from_the_test_set(tmp_path):
    audit = tmp_path / "audit.json"
    audit.write_text(json.dumps(round1_audit()))
    script = textwrap.dedent(AUDIT_HOOK.format(audit=str(audit), out=str(tmp_path / "out")))
    done = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, cwd=ROOT, check=True
    )
    opened = json.loads(done.stdout.strip().splitlines()[-1])
    assert str(audit) in opened  # the hook saw the audit, so it would see a test file too
    banned = ("test-set-frozen", "test-frozen", "vision-report", "seed90000", "frames.jsonl", "detections")
    assert not [p for p in opened if any(b in p for b in banned)]


# ---------------------------------------------------------------------------------------------
# The model explains and orders; code checks it
# ---------------------------------------------------------------------------------------------

IDS = [
    "ball-behind-a-player", "ball-behind-the-keeper", "ball-behind-a-player-in-a-crowd",
    "player-behind-a-player", "player-behind-a-player-in-a-crowd",
]


def test_without_a_model_every_rationale_is_code_written_from_the_cluster_s_numbers():
    result, trace = run()
    first = result["clusters"][0]
    assert first["rationale"] == "38 of 95 ball labels missed behind a player, recall 0.6."
    assert {c["explained_by"] for c in result["clusters"] + result["unmapped"]} == {"code"}
    assert [s.action for s in trace] == ["read", "cluster", "explain", "handoff"]


def test_a_rationale_using_only_the_cluster_s_numbers_stands():
    text = "Recall 0.6: 38 of 95 missed, 57 found; 47 clips on seeds 7101 to 7147."
    result, trace = run(ask=model({"order": IDS, "rationales": {"ball-behind-a-player": text}}))
    first = result["clusters"][0]
    assert (first["rationale"], first["explained_by"]) == (text, "model")
    assert result["clusters"][1]["explained_by"] == "code"  # no rationale given: the template stands
    assert trace[2].action == "reject" and "ball-behind-the-keeper: empty" in trace[2].detail


@pytest.mark.parametrize(
    "text, why",
    [
        ("Recall is 0.45, the worst.", "numbers not in the cluster: 0.45"),
        ("38 of 96 missed.", "numbers not in the cluster: 96"),
        ("Only 9 misses here.", "numbers not in the cluster: 9"),  # the keeper's count, not this one's
        ("x" * 201, "longer than 200 characters"),
        ("Two lines\nof text", "control characters"),
        ("", "empty"),
        (38, "empty"),
    ],
)
def test_a_rationale_with_an_invented_number_falls_back_to_the_template(text, why):
    result, trace = run(ask=model({"order": IDS, "rationales": {"ball-behind-a-player": text}}))
    first = result["clusters"][0]
    assert first["explained_by"] == "code" and first["rationale"].startswith("38 of 95")
    assert f"ball-behind-a-player: {why}" in trace[2].detail


def test_the_model_s_order_moves_the_list_and_only_ties_never_the_counts():
    reverse = list(reversed(IDS))
    result, _ = run(ask=model({"order": reverse, "rationales": {}}))
    assert [c["id"] for c in result["clusters"]] == reverse
    by_id = {c["id"]: c["clips"] for c in result["clusters"]}
    code, _ = run()
    assert by_id == {c["id"]: c["clips"] for c in code["clusters"]}  # largest remainder has no ties here
    assert result["clusters"][0]["seeds"] == [7101, 7105]  # seeds follow the new order


def test_order_breaks_a_tie_and_a_rationale_citing_the_old_count_is_refused():
    audit = round1_audit()
    audit["rows"] = [
        {"cls": "ball", "visibility": "mostly hidden", "situation": s, "kit_contrast": "normal",
         "labels": 10, "missed": 5}
        for s in ("behind a player", "behind the keeper")
    ]
    code, _ = run(audit, budget=3)
    # Equal misses keep failure_clusters' situation order (keeper first); the tie's clip goes to it.
    assert [(c["id"], c["clips"]) for c in code["clusters"]] == [
        ("ball-behind-the-keeper", 2), ("ball-behind-a-player", 1)]
    order = ["ball-behind-a-player", "ball-behind-the-keeper"]
    stale = {"ball-behind-the-keeper": "5 of 10 missed; 2 clips."}  # true before the reorder only
    result, trace = run(audit, ask=model({"order": order, "rationales": stale}), budget=3)
    assert [(c["id"], c["clips"]) for c in result["clusters"]] == [(order[0], 2), (order[1], 1)]
    assert result["clusters"][1]["explained_by"] == "code"
    assert "ball-behind-the-keeper: numbers not in the cluster: 2 after the order" in trace[2].detail


@pytest.mark.parametrize(
    "order",
    [IDS[:-1], [*IDS, IDS[0]], [*IDS[:-1], "ball-behind-the-referee"], "ball-behind-a-player", None],
)
def test_an_order_that_does_not_name_every_cluster_once_is_refused(order):
    result, trace = run(ask=model({"order": order, "rationales": {}}))
    assert [c["id"] for c in result["clusters"]] == IDS
    assert "order must name every cluster exactly once" in trace[2].detail


@pytest.mark.parametrize("reply", ["not json", "[1, 2]", '"text"'])
def test_a_reply_that_is_not_a_json_object_changes_nothing(reply):
    result, trace = run(ask=model(reply))
    code, _ = run()
    assert result == code
    assert trace[2].action == "reject" and "reply is not a JSON object" in trace[2].detail


def test_rationales_for_unknown_clusters_are_refused_and_the_prompt_holds_only_code_numbers():
    ask = model({"order": IDS, "rationales": {"ball-at-the-frame-s-edge": "3 misses."}})
    _, trace = run(ask=ask)
    assert "rationales for unknown clusters: ball-at-the-frame-s-edge" in trace[2].detail
    rows = json.loads(ask.calls[0].split("\n\n", 1)[1])
    assert [r["id"] for r in rows] == IDS and rows[0]["misses"] == 38 and rows[0]["clips"] == 47


def test_check_rationale_allows_found_labels_and_seeds():
    cluster = {"labels": 95, "misses": 38, "recall": 0.6, "missed_low_contrast": 7, "clips": 47,
               "seeds": [7101, 7147]}
    assert check_rationale("57 of 95 found, 7 in low contrast, seeds 7101 to 7147.", cluster) is None
    assert check_rationale("58 of 95 found.", cluster) == "numbers not in the cluster: 58"


# ---------------------------------------------------------------------------------------------
# The handoff to the Data agent, offline, and the trace
# ---------------------------------------------------------------------------------------------


def test_the_data_agent_plans_exactly_the_auditor_s_clips_and_seeds():
    result, trace = run()
    plan = handoff(result, "abc123", trace)
    assert [c["clips"] for c in plan["clusters"]] == [c["clips"] for c in result["clusters"]]
    seeds = [(r["first_seed"], r["first_seed"] + r["count"] - 1) for r in plan["requests"]]
    for c in result["clusters"]:
        inside = [s for s in seeds if c["seeds"][0] <= s[0] and s[1] <= c["seeds"][1]]
        assert sum(b - a + 1 for a, b in inside) == c["clips"]
    assert len(plan["requests"]) == 11 and {r["commit"] for r in plan["requests"]} == {"abc123"}
    assert trace[-1].role == "data_agent" and trace[-1].action == "plan"


def test_the_data_agent_refuses_clips_that_are_not_its_split():
    result, _ = run()
    tampered = copy.deepcopy(result)
    tampered["clusters"][0]["clips"] += 1
    with pytest.raises(ValueError, match="splits as"):
        data_agent.plan(tampered, 80, 7101, "abc123")
    with pytest.raises(ValueError, match="splits as"):
        data_agent.plan(result, 81, 7101, "abc123")  # a different budget than the Auditor's


def recording(tmp_path, reply: dict, audit: dict) -> Path:
    clusters, _ = run(audit)
    path = tmp_path / "rec.json"
    WorkflowRecording("vision-auditor", "abc123", {}, {}, "2026-10-19T00:00:00+00:00",
                      [Turn("vision_auditor", prompt(clusters["clusters"]), json.dumps(reply))]).save(path)
    return path


def test_the_cli_replays_a_recording_offline_and_writes_a_valid_trace(tmp_path):
    audit = round1_audit()
    (tmp_path / "audit.json").write_text(json.dumps(audit))
    text = "Most misses: 38 of 95, recall 0.6."
    rec = recording(tmp_path, {"order": IDS, "rationales": {"ball-behind-a-player": text}}, audit)
    out = tmp_path / "round1"
    main([str(tmp_path / "audit.json"), "--round", "round1", "--budget", "80", "--first-seed", "7101",
          "--out", str(out), "--commit", "abc123", "--replay", str(rec)])
    clusters = json.loads((out / "clusters.json").read_text())
    schema_validator("failure_clusters").validate(clusters)
    assert clusters["clusters"][0]["rationale"] == text
    assert len(clusters["source"]["audit_sha256"]) == 64
    assert (clusters["source"]["checkpoint"], clusters["source"]["detections"]) == (
        "ours-v3", "detections-ours-v3.jsonl")
    assert clusters["source"]["seeds"] == SEEDS
    assert len(json.loads((out / "requests.json").read_text())["requests"]) == 11
    trace = [json.loads(line) for line in (out / "trace.jsonl").read_text().splitlines()]
    validator = schema_validator("agent_trace")
    for row in trace:
        validator.validate(row)
    assert [(r["role"], r["action"]) for r in trace] == [
        ("vision_auditor", "read"), ("vision_auditor", "cluster"), ("vision_auditor", "reject"),
        ("vision_auditor", "handoff"), ("data_agent", "plan"),
    ]
    assert {r["moment"] for r in trace} == {"round1"}


def test_a_replay_refuses_a_prompt_that_changed_since_recording(tmp_path):
    audit = round1_audit()
    rec = recording(tmp_path, {"order": IDS, "rationales": {}}, audit)
    changed = copy.deepcopy(audit)
    changed["rows"][0]["missed"] += 1  # one more miss: a different prompt
    (tmp_path / "audit.json").write_text(json.dumps(changed))
    with pytest.raises(ReplayMismatch):
        main([str(tmp_path / "audit.json"), "--round", "round1", "--budget", "80", "--first-seed", "7101",
              "--out", str(tmp_path / "out"), "--commit", "abc123", "--replay", str(rec)])
