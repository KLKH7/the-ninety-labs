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


def scripted_run(grader=None, **kw):
    # The single agent writes a true claim in minute 1 and a false number in minute 2, in both its
    # arms (each minute runs the arms in order: one agent, one agent + fact-checker, graph); checked,
    # it keeps writing the false number when sent back. The graph's Tactician does the same.
    replies = iter([reply(true_claim(FIRST))] * 2 + [reply(false_claim(MAIN))] * 4)

    async def one_agent(prompt: str) -> str:
        return next(replies)

    graph = Models.scripted(
        {"analyst": [picks(FIRST), picks(MAIN)],
         "tactician": [reply(true_claim(FIRST))] + [reply(false_claim(MAIN))] * 4,
         "challenger": ['{"agree": true}'] * 2},
        judge=Judge(),
    )
    return asyncio.run(ab.run(graph, one_agent, grader or Judge(), {SEED: EVENTS}, minutes=2, **kw))


BODY = scripted_run()


def test_the_single_agent_airs_its_false_number_and_the_checked_arms_do_not():
    one, checked, graph = (BODY["arms"][a] for a in ("one agent", "one agent + fact-checker", "graph"))
    assert (one["aired"], one["false_aired"], one["false_by_code"]) == (2, 1, 1)
    assert (checked["aired"], checked["false_aired"]) == (1, 0)
    assert (graph["aired"], graph["false_aired"]) == (1, 0)
    assert graph["model_calls"] > one["model_calls"]  # the graph's checks cost calls, and the table says so
    # Checked: minute 1 by the agent and the Judge; minute 2's three drafts, all rejected by the code.
    assert checked["model_calls"] == 2 + 3
    assert (checked["held"], checked["rejected"], checked["rewritten"]) == (0, 1, 0)
    assert graph["rejected"] == 1


def test_a_claim_aired_after_a_rewrite_is_counted():
    replies = iter([reply(false_claim(MAIN)), reply(true_claim(FIRST))])

    async def agent(prompt: str) -> str:
        return next(replies)

    from ninety.agents import workflow
    from ninety.match.facts import compact

    known = {e["id"]: compact(e) for e in workflow.agent_events(EVENTS)}
    checker: dict = {}
    aired, calls, why = asyncio.run(
        ab.checked_agent_minute(agent, Judge(), SEED, "x-inline", 1, known, checker)
    )
    assert [c.text for c in aired] == [ab.parse_claim(reply(true_claim(FIRST))).text] and why == ""
    assert calls == 3 and checker == {"drafts": 2, "held": 0, "rejected": 0, "rewritten": 1}


def test_a_failed_checked_agent_airs_nothing_and_says_why():
    async def down(prompt):
        raise RuntimeError("injected")

    aired, calls, why = asyncio.run(ab.checked_agent_minute(down, Judge(), SEED, "x-inline", 1, {}))
    assert aired == [] and why


def test_every_aired_claim_is_graded_the_same_way():
    for arm in BODY["minutes_by_arm"].values():
        for minute in arm:
            for claim in minute["aired"]:
                assert set(claim) == {"text", "evidence", "code_ok", "judge_ok", "true", "reasons"}


def test_a_claim_the_judge_fails_counts_as_false_even_if_the_code_passes():
    body = scripted_run(grader=Judge(*[Verdict(False, ["not supported"], "unsupported_claim")] * 10))
    assert body["arms"]["one agent"]["false_by_judge"] == 1  # the true-by-code claim in minute 1
    assert body["arms"]["graph"]["false_by_judge"] == 1


def inline_events(prompt: str) -> list[dict]:
    _, sep, events = prompt.partition("EVENTS: ")
    assert sep, f"no events inline, so the agent read the deployed match tools: {prompt!r}"
    return json.loads(events)


def test_both_arms_read_the_match_the_grader_grades():
    # Lesson 90: the one-agent arm once read the deployed match tools, simulated by the deployed
    # image's engine, and aired a goal the grader's match does not have. Both arms now get the
    # minute's events inline, from the same events the grader checks against.
    from dataclasses import replace

    from ninety.agents import workflow
    from ninety.match.facts import compact
    from ninety.mcp import match_server

    prompts = {"one agent": [], "graph": []}

    async def one_agent(prompt: str) -> str:  # both single-agent arms ask it, one prompt each a minute
        prompts["one agent"].append(prompt)
        return reply(true_claim(FIRST))

    graph = Models.scripted({"analyst": [picks(FIRST), picks(MAIN)]}, judge=Judge())

    async def analyst(prompt: str) -> str:
        prompts["graph"].append(prompt)
        return await scripted_analyst(prompt)

    scripted_analyst = graph.analyst
    asyncio.run(ab.run(replace(graph, analyst=analyst), one_agent, Judge(), {SEED: EVENTS}, minutes=2))
    known = {e["id"]: compact(e) for e in workflow.agent_events(EVENTS)}  # what the grader grades
    sent_by_arm = {"one agent": prompts["one agent"][0::2],
                   "one agent + fact-checker": prompts["one agent"][1::2], "graph": prompts["graph"]}
    for arm, sent in sent_by_arm.items():
        assert len(sent) == 2, arm  # one prompt a minute (the true claim needs no rewrite)
        for minute, prompt in enumerate(sent, start=1):
            inline = inline_events(prompt)
            assert inline and {e["id"] for e in inline} <= set(known), arm
            # The same events, field for field: the grader's own, not ones with the same ids.
            assert inline == [e for e in known.values() if e["minute"] == minute], arm
            # Under a match id no server serves, so a tool call cannot return another match.
            served = match_server.match_id(SEED)
            assert f"{served}-inline" in prompt and f"{served} " not in prompt and f"{served}." not in prompt


def test_a_failed_or_unreadable_single_agent_reply_airs_nothing():
    async def down(prompt):
        raise RuntimeError("injected")

    async def prose(prompt):
        return "I think it was a great pass."

    assert asyncio.run(ab.one_agent_minute(down, "seed21", 1, {}))[0] == []
    assert asyncio.run(ab.one_agent_minute(prose, "seed21", 1, {}))[0] == []


def test_the_report_is_strict_json_and_names_the_false_claims():
    text = ab.results(BODY)
    json.loads(text)  # strict: allow_nan=False would have raised on NaN
    md = ab.report({**BODY, "agent_definitions": {}}, "scripted models")
    assert "| one agent | 2 | 1 | 1/2 (50%)" in md and "| graph | 1 | 1 | 0/1 (0%)" in md
    assert "| one agent + fact-checker | 1 | 1 | 0/1 (0%)" in md
    assert "199 km/h" in md
    # The plan's reading rule: the same true and false counts, so arm 2 matches the graph.
    assert "Outcome 1" in md


def reading(graph: tuple[int, int], checked: tuple[int, int]) -> str:
    def arm(true: int, false: int) -> dict:
        return {"aired": true + false, "true_aired": true, "false_aired": false}

    return ab.reading({"graph": arm(*graph), "one agent + fact-checker": arm(*checked)})


def test_the_pre_registered_reading_rule():
    # (true, false) on air for the graph, then for arm 2; exactly one outcome, checked in order.
    assert "Outcome 1" in reading((6, 0), (6, 1))  # within one of each: never a win
    assert "Outcome 1" in reading((5, 1), (6, 2))
    assert "Outcome 2" in reading((6, 0), (6, 2))  # as many true, fewer false
    assert "Outcome 2" in reading((9, 1), (6, 1))  # more true, at a lower false rate
    assert "Outcome 3" in reading((6, 2), (6, 0))  # the same, swapped
    assert "Outcome 3" in reading((6, 1), (9, 1))
    assert "Outcome 4" in reading((9, 4), (3, 1))  # more true but a higher false rate
    assert "Outcome 4" in reading((3, 1), (9, 4))


def test_no_two_outcomes_hold_at_once():
    import itertools

    for counts in itertools.product(range(6), repeat=4):
        text = reading(counts[:2], counts[2:])
        assert sum(f"Outcome {n}" in text for n in range(1, 5)) == 1, counts


def test_the_cost_stop_starts_no_further_minute():
    body = scripted_run(budget_usd=0.000001)  # spent after minute 1, so minute 2 never starts
    assert {len(minutes) for minutes in body["minutes_by_arm"].values()} == {1}
    assert body["stopped"].startswith("cost stop") and "minute 2" in body["stopped"]
    assert body["estimated_usd"] > 0 and body["grader_calls"] >= 1
    md = ab.report({**body, "agent_definitions": {}}, "scripted models")
    assert "cost stop" in md
    assert BODY["stopped"] == ""  # the default budget is not reached on two scripted minutes


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
        # The slice's Analyst, for both single-agent arms: minute 1, then minute 2 with two rewrites.
        "analyst": [reply(true_claim(FIRST))] * 2 + [reply(false_claim(MAIN))] * 4,
        "moment-analyst": [picks(FIRST), picks(MAIN)],
        "tactician": [reply(true_claim(FIRST))] + [reply(false_claim(MAIN))] * 4,
        "challenger": ['{"agree": true}'] * 2,
        "judge": [SUPPORTED] * 16,
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
    # Each agent's version and definition fingerprint, in the data and in the report (lesson 216).
    from ninety.agents import evidence, foundry

    roles = {"ninety-analyst", "ninety-moment-analyst", "ninety-tactician", "ninety-challenger",
             "ninety-judge"}
    assert body[evidence.KEY] == {n: e for n, e in foundry.load_registry().items() if n in roles}
    md = evidence.read(tmp_path / "ablation-agents.md")
    data = evidence.read(tmp_path / "ablation-agents.json")
    assert md[1] == "recorded" and data[0] == md[0]
    assert (tmp_path / "ablation-agents.md").read_text().startswith("# Ablation: one agent")
    assert order[:2] == ["token", "simulate"] and order.count("token") == 1  # signed in once, first
    assert len(body["commit"]) == 40 and body["commit"] in (tmp_path / "ablation-agents.md").read_text()


def test_a_live_arm_that_calls_the_match_tools_fails_that_call(monkeypatch, tmp_path):
    # Both arms get the minute inline; an agent that reads the tools anyway (the deployed image's
    # match, lesson 90) airs nothing for that minute, and says why.
    import sys

    from ninety.agents import credentials, workflow
    from tests.test_workflow import SUPPORTED, Credential, FakeFoundry, tool_reply

    fake = FakeFoundry({
        "analyst": [tool_reply(reply(true_claim(FIRST))), reply(false_claim(MAIN))],
        "moment-analyst": [tool_reply(picks(FIRST)), picks(MAIN)],
        "tactician": [reply(false_claim(MAIN))] * 4,
        "challenger": ['{"agree": true}'] * 2,
        "judge": [SUPPORTED] * 12,
    })
    monkeypatch.setattr("agent_framework.foundry.FoundryAgent", fake)
    monkeypatch.setattr(credentials, "new_credential", lambda: credentials.SignedIn(Credential(3600)))
    monkeypatch.setattr(workflow, "simulated_events", lambda seed, minutes: EVENTS)
    monkeypatch.setattr(ab, "MINUTES", 2)
    monkeypatch.setattr(sys, "argv", ["agent_ablation", "--live", "--seeds", "21", "--out", str(tmp_path)])
    ab.main()
    body = json.loads((tmp_path / "ablation-agents.json").read_text())
    first = {arm: minutes[0] for arm, minutes in body["minutes_by_arm"].items()}
    assert first["one agent"]["aired"] == [] and "ReadTheTools" in first["one agent"]["why_none"]
    assert first["graph"]["aired"] == [] and "ReadTheTools" in first["graph"]["why_none"]
    # Counted per arm, in the data and in the report a reader sees.
    assert [body["arms"][a]["minutes_read_the_tools"] for a in ("one agent", "graph")] == [1, 1]
    md = (tmp_path / "ablation-agents.md").read_text()
    minutes = body["arms"]["one agent"]["minutes"]
    assert "Minutes lost to a tool call" in md and md.count(f"| 1 of {minutes} |") == 2
