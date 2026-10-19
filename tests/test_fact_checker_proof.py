"""The fact-checker's proof (docs/eval/fact-checker-planted.md, ablation.md, failure-table.md):
the committed files are what the code produces, and the ablation's `full` variant is the fact-checker
the live workflow runs, claim by claim."""

import asyncio
import json

from ninety.agents.factcheck import MIN_CONFIDENCE, Claim, Verdict
from ninety.agents.slice import run_workflow
from ninety.eval import ablation, fact_checker_proof, planted

DATA = planted.load()


def test_committed_reports_are_up_to_date():
    assert fact_checker_proof.stale() == [], f"run {fact_checker_proof.COMMAND}"


def test_planted_set_is_what_it_says():
    claims = DATA["claims"]
    assert len({c["id"] for c in claims}) == len(claims)
    for c in claims:
        assert c["evidence"] == [e["id"] for e in c["events"]]
    phantom = [c for c in claims if c["family"] == "phantom detection"]
    confident = [c for c in claims if c["family"] == "confident detection"]
    assert phantom and confident and not any(c["true"] for c in phantom) and all(c["true"] for c in confident)
    assert all(e["confidence"] < MIN_CONFIDENCE for c in phantom for e in c["events"])
    assert all(e["confidence"] >= MIN_CONFIDENCE for c in confident for e in c["events"])
    # A phantom is the same claim as a recorded true one the Judge supported: only the gate can tell.
    supported = {(c["seed"], c["text"]) for c in claims if c["family"] == "recorded" and c["true"]
                 and c["judge"] and c["judge"]["ok"]}
    assert all((c["seed"], c["text"]) in supported for c in phantom)
    frozen = planted.load(judge_path=None)["claims"]  # the set alone, without later Judge answers
    viewer = [c for c in frozen if c["family"] == "viewer input"]
    assert viewer and all(not c["true"] and c["judge"] is None for c in viewer)
    # Later answers fill only claims the set had no answer for, and never replace one.
    for before, after in zip(frozen, claims, strict=True):
        filled = before["judge"] is None and after.get("judge_recorded") == "later"
        assert after["judge"] == before["judge"] or filled


def test_full_variant_is_the_live_fact_checker():
    """Each planted claim through the real Analyst -> fact-checker workflow, the Analyst repeating
    it on every draft: the workflow's status must be the ablation's `full` status."""
    known = ablation.known_events(DATA["claims"])
    rows = ablation.run(DATA)

    async def one(item):
        async def ask(prompt: str) -> str:
            return json.dumps({"text": item["text"], "evidence": item["evidence"]})

        async def judge(claim: Claim, evidence: list[dict]) -> Verdict:
            return ablation.recorded_judge(item)

        events = list(known[item["seed"]].values())
        return await run_workflow(ask, judge, 1, False, item["seed"], 0, False, events)

    checked = 0
    for row in rows:
        status, _ = row["full"]
        if status == ablation.UNMEASURED:
            continue
        outcome = asyncio.run(one(row["item"]))
        assert outcome.status == status, row["item"]["id"]
        checked += 1
    assert checked == len(rows)  # nothing in the full variant is unmeasured


def test_variants_differ_only_by_the_part_removed():
    rows = ablation.run(DATA)
    for row in rows:
        item = row["item"]
        assert row["no fact-checker"][0] == "verified"
        # Removing a check never stops a claim the full fact-checker airs.
        if ablation.aired(row, "full"):
            assert all(ablation.aired(row, v) for v in ablation.VARIANTS)
        if item["family"] == "phantom detection":
            assert row["full"] == ("held", "confidence gate")
