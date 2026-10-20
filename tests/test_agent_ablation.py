"""The agent ablation (ninety/eval/agent_ablation.py) on scripted models and W1's built match: the
harness counts what each arm airs and grades it the same way. Live numbers come from agents-live."""

from __future__ import annotations

import asyncio
import json

import pytest

from ninety.agents.contracts import Models
from ninety.agents.factcheck import Verdict
from ninety.eval import agent_ablation as ab
from tests.test_workflow import EVENTS, MAIN, Judge, false_claim, picks, reply, true_claim

FIRST = EVENTS[0]["id"]  # minute 1's pass
SEED = 21


def scripted_run(grader=None):
    # The single agent writes a true claim in minute 1 and a false number in minute 2. The graph's
    # Tactician writes the same false number in minute 2, and keeps writing it when sent back.
    replies = iter([reply(true_claim(FIRST)), reply(false_claim(MAIN))])

    async def one_agent(prompt: str) -> str:
        return next(replies)

    graph = Models.scripted(
        {"analyst": [picks(FIRST), picks(MAIN)],
         "tactician": [reply(true_claim(FIRST))] + [reply(false_claim(MAIN))] * 4,
         "challenger": ['{"agree": true}'] * 2},
        judge=Judge(),
    )
    return asyncio.run(ab.run(graph, one_agent, grader or Judge(), {SEED: EVENTS}, minutes=2))


BODY = scripted_run()


def test_the_single_agent_airs_its_false_number_and_the_graph_does_not():
    one, graph = BODY["arms"]["one agent"], BODY["arms"]["graph"]
    assert (one["aired"], one["false_aired"], one["false_by_code"]) == (2, 1, 1)
    assert (graph["aired"], graph["false_aired"]) == (1, 0)
    assert graph["model_calls"] > one["model_calls"]  # the graph's checks cost calls, and the table says so


def test_every_aired_claim_is_graded_the_same_way():
    for arm in BODY["minutes_by_arm"].values():
        for minute in arm:
            for claim in minute["aired"]:
                assert set(claim) == {"text", "evidence", "code_ok", "judge_ok", "true", "reasons"}


def test_a_claim_the_judge_fails_counts_as_false_even_if_the_code_passes():
    body = scripted_run(grader=Judge(*[Verdict(False, ["not supported"], "unsupported_claim")] * 10))
    assert body["arms"]["one agent"]["false_by_judge"] == 1  # the true-by-code claim in minute 1
    assert body["arms"]["graph"]["false_by_judge"] == 1


def test_a_failed_or_unreadable_single_agent_reply_airs_nothing():
    async def down(prompt):
        raise RuntimeError("injected")

    async def prose(prompt):
        return "I think it was a great pass."

    assert asyncio.run(ab.one_agent_minute(down, "seed21", 1))[0] == []
    assert asyncio.run(ab.one_agent_minute(prose, "seed21", 1))[0] == []


def test_the_report_is_strict_json_and_names_the_false_claims():
    text = ab.results(BODY)
    json.loads(text)  # strict: allow_nan=False would have raised on NaN
    md = ab.report(BODY, "scripted models")
    assert "| one agent | 2 | 1/2 (50%)" in md and "| graph | 1 | 0/1 (0%)" in md
    assert "199 km/h" in md


def test_the_live_command_refuses_to_run_offline(monkeypatch):
    import sys

    monkeypatch.setattr(sys, "argv", ["agent_ablation"])
    with pytest.raises(SystemExit):
        ab.main()


def test_the_live_command_runs_both_arms_on_the_published_agents(monkeypatch, tmp_path):
    # agents-live task=ablation, with W1's fake Foundry and a fake sign-in: no Azure.
    import sys

    from ninety.agents import credentials, workflow
    from tests.test_workflow import SUPPORTED, Credential, FakeFoundry

    fake = FakeFoundry({
        "analyst": [reply(true_claim(FIRST)), reply(false_claim(MAIN))],  # the slice's: one agent
        "moment-analyst": [picks(FIRST), picks(MAIN)],
        "tactician": [reply(true_claim(FIRST))] + [reply(false_claim(MAIN))] * 4,
        "challenger": ['{"agree": true}'] * 2,
        "judge": [SUPPORTED] * 12,
    })
    order: list[str] = []

    class Signed(Credential):
        async def get_token(self, *scopes, **kwargs):
            order.append("token")
            return await super().get_token(*scopes, **kwargs)

    monkeypatch.setattr("agent_framework.foundry.FoundryAgent", fake)
    monkeypatch.setattr(credentials, "new_credential", lambda: credentials.SignedIn(Signed(3600)))
    monkeypatch.setattr(workflow, "simulated_events",
                        lambda seed, minutes: order.append("simulate") or EVENTS)
    monkeypatch.setattr(ab, "MINUTES", 2)
    monkeypatch.setattr(sys, "argv", ["agent_ablation", "--live", "--seeds", "21", "--out", str(tmp_path)])
    ab.main()
    body = json.loads((tmp_path / "ablation-agents.json").read_text())
    assert body["arms"]["one agent"]["false_aired"] == 1 and body["arms"]["graph"]["false_aired"] == 0
    assert "ninety-analyst" in body["ran"] and "ninety-tactician" in body["ran"]
    assert (tmp_path / "ablation-agents.md").read_text().startswith("# Ablation: one agent")
    assert order[:2] == ["token", "simulate"] and order.count("token") == 1  # signed in once, first
    assert len(body["commit"]) == 40 and body["commit"] in (tmp_path / "ablation-agents.md").read_text()
