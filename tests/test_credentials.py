"""Every live run signs in with the aio credential before anything slow, and hands that one credential
to Foundry (ninety/agents/credentials.py). A sync DefaultAzureCredential passed to an async client
fetched its token on the event loop, and only after the simulation had run, by which time agents-live's
five-minute sign-in could have expired: the likely cause of 19 of 251 Judge calls failing."""

from __future__ import annotations

import ast
import asyncio
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from ninety.agents import credentials, foundry

ROOT = Path(__file__).resolve().parents[1]


class Token:
    def __init__(self):
        self.token, self.expires_on = "t", time.time() + 3600


class Credential:
    """An async credential that writes each step into the shared `order`."""

    def __init__(self, order: list[str]):
        self.order = order

    async def get_token(self, *scopes, **kwargs):
        self.order.append("token")
        return Token()

    async def close(self):
        self.order.append("closed")


@pytest.fixture
def order(monkeypatch):
    log: list[str] = []
    monkeypatch.setattr(credentials, "new_credential", lambda: credentials.SignedIn(Credential(log)))
    return log


class Agent:
    """A FoundryAgent stand-in: records the credential it was built with."""

    built: list = []

    def __init__(self, **kwargs):
        Agent.built.append(kwargs["credential"])

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


def signed_in(credential) -> bool:
    return isinstance(credential, credentials.SignedIn)


def test_the_chat_client_has_no_default_credential():
    # The old default was a fresh sync DefaultAzureCredential; now the caller passes its own.
    with pytest.raises(TypeError):
        foundry.chat_client()


def test_the_slice_signs_in_before_it_simulates_and_uses_that_credential(monkeypatch, order):
    from ninety.agents import slice as sl

    clients = []
    monkeypatch.setattr(sl, "match_events", lambda seed, minutes: order.append("simulate") or [])
    monkeypatch.setattr(sl, "match_stats", lambda seed, minutes: [])
    monkeypatch.setattr(sl.foundry, "chat_client", lambda credential: clients.append(credential) or object())
    monkeypatch.setattr(sl.foundry, "slice_agents", lambda client: ["analyst", "judge"])
    monkeypatch.setattr(sl.foundry, "pinned", lambda local: (f"ninety-{local}", "1"))
    monkeypatch.setattr(sl, "FoundryAgent", Agent)
    monkeypatch.setattr(sl.telemetry, "flush", lambda: None)

    async def workflow(*args):
        order.append("workflow")
        return "outcome"

    monkeypatch.setattr(sl, "run_workflow", workflow)
    Agent.built = []
    outcome, *_ = asyncio.run(sl.run_slice(2, False, 7, 5, trace_to="none"))
    assert outcome == "outcome"
    assert order[:2] == ["token", "simulate"] and order[-1] == "closed"
    assert clients and all(map(signed_in, clients + Agent.built)) and len(Agent.built) == 2


def test_the_fact_checker_evaluation_signs_in_before_it_builds_its_cases(monkeypatch, order):
    from ninety.eval import factcheck_eval as fe

    clients = []
    monkeypatch.setattr(fe.foundry, "chat_client", lambda credential: clients.append(credential) or object())
    monkeypatch.setattr(fe, "judge_agent", lambda client: "judge")
    monkeypatch.setattr(fe.foundry, "pinned", lambda local: ("ninety-judge", "1"))
    monkeypatch.setattr(fe, "FoundryAgent", Agent)
    monkeypatch.setattr(fe, "events_in", lambda *a: order.append("simulate") or [])
    monkeypatch.setattr(fe, "cases", lambda seed, minutes: [])
    Agent.built = []
    rows, label = asyncio.run(fe.run([21], 1))
    assert rows == [] and label.startswith("`ninety-judge:1`")
    assert order[:2] == ["token", "simulate"] and order[-1] == "closed"
    assert clients and all(map(signed_in, clients + Agent.built)) and len(Agent.built) == 1


def test_the_analyst_evaluation_signs_in_before_it_simulates(monkeypatch, order):
    from ninety.agents import analyst_eval as ae

    given = []
    monkeypatch.setattr(ae, "events_in", lambda *a: order.append("simulate") or [])

    async def drafts(credential, seeds, known):
        given.append(credential)
        return [], "ran"

    monkeypatch.setattr(ae, "_drafts", drafts)
    assert asyncio.run(ae.drafts([21, 33])) == ([], "ran")
    assert order[:3] == ["token", "simulate", "simulate"] and order[-1] == "closed"
    assert given and all(map(signed_in, given))


def test_the_workflow_uses_the_shared_credential():
    from ninety.agents import workflow

    # One implementation: the workflow's names are the credentials module's.
    assert workflow.SignedIn is credentials.SignedIn
    assert workflow.new_credential is credentials.new_credential
    assert workflow.sign_in_then_load is credentials.sign_in_then_load


def test_sign_in_asks_for_the_foundry_token_once_and_keeps_it(order):
    async def go():
        async with credentials.new_credential() as credential:
            await credentials.sign_in(credential)
            await credentials.sign_in(credential)
            await credential.get_token(credentials.FOUNDRY_SCOPE)

    asyncio.run(go())
    assert order == ["token", "closed"]


# foundry.py keeps the sync credential for publishing, through the sync AIProjectClient; its chat
# client has no default (test above).
LIVE = ["ninety/agents/slice.py", "ninety/eval/factcheck_eval.py", "ninety/agents/analyst_eval.py",
        "ninety/agents/workflow.py", "ninety/agents/credentials.py", "ninety/api/companion.py",
        "ninety/agents/describer.py",
        "ninety/personalizer/core.py", "ninety/personalizer/eval.py", "ninety/personalizer/server.py"]


@pytest.mark.parametrize("path", LIVE)
def test_no_live_module_takes_the_sync_credential(path):
    tree = ast.parse((ROOT / path).read_text())
    sync = [n for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module == "azure.identity"
            and any(a.name == "DefaultAzureCredential" for a in n.names)]
    assert not sync, f"{path} imports azure.identity.DefaultAzureCredential: use credentials.new_credential"


class Counting:
    """An inner credential: every request asked, each token lasting `lifetime` seconds."""

    def __init__(self, lifetime: float):
        self.lifetime, self.asked = lifetime, []

    async def get_token(self, *scopes, **kwargs):
        self.asked.append((scopes, tuple(sorted(kwargs))))
        token = Token()
        token.expires_on = time.time() + self.lifetime
        return token

    async def close(self):
        pass


def test_the_token_margin_is_twice_a_model_call():
    from ninety.agents import budgets

    assert credentials.TOKEN_MARGIN_SECONDS == 2 * budgets.MODEL_TIMEOUT_SECONDS


def test_a_token_lasting_less_than_the_margin_is_fetched_again():
    # One model call's budget is inside the margin: such a token is never kept.
    from ninety.agents import budgets

    inner = Counting(budgets.MODEL_TIMEOUT_SECONDS)
    signed = credentials.SignedIn(inner)
    asyncio.run(signed.get_token(credentials.FOUNDRY_SCOPE))
    asyncio.run(signed.get_token(credentials.FOUNDRY_SCOPE))
    assert len(inner.asked) == 2


def test_tokens_are_kept_per_scope():
    inner = Counting(3600)
    signed = credentials.SignedIn(inner)
    for scope in ("a/.default", "b/.default", "a/.default"):
        asyncio.run(signed.get_token(scope))
    assert [s for s, _ in inner.asked] == [("a/.default",), ("b/.default",)]


@pytest.mark.parametrize("kwargs", [{"claims": "challenge"}, {"enable_cae": True}])
def test_a_claims_challenge_never_gets_the_kept_token(kwargs):
    inner = Counting(3600)
    signed = credentials.SignedIn(inner)
    asyncio.run(signed.get_token(credentials.FOUNDRY_SCOPE))
    asyncio.run(signed.get_token(credentials.FOUNDRY_SCOPE, **kwargs))  # asks again
    asyncio.run(signed.get_token(credentials.FOUNDRY_SCOPE))  # the kept one serves ordinary calls
    assert len(inner.asked) == 2 and inner.asked[1][1] == tuple(kwargs)


def test_foundry_scores_signs_in_before_it_evaluates(monkeypatch, order):
    from ninety.agents import analyst_eval as ae

    async def evaluate_traces(**kwargs):
        order.append("evaluate")
        return type("R", (), {"status": "ok", "report_url": "u", "per_evaluator": {}})()

    monkeypatch.setattr("agent_framework.foundry.evaluate_traces", evaluate_traces)
    monkeypatch.setattr(ae.foundry, "chat_client", lambda credential: object())
    assert asyncio.run(ae.foundry_scores(["r1"]))["status"] == "ok"
    assert order[:2] == ["token", "evaluate"]


def test_the_analyst_evaluation_grades_the_events_it_sends_inline(monkeypatch):
    # Lesson 90 (audit row 1): the Analyst read the deployed match over MCP while the grade used this
    # commit's events. Now each prompt carries the minute's events, under an id no server serves.
    from ninety.agents import analyst_eval as ae
    from ninety.agents.factcheck import Verdict

    known = {"e1": {"id": "e1", "minute": 1, "second": 3, "clock": "00:03", "type": "pass", "team": "home",
                    "player": "h7"},
             "e2": {"id": "e2", "minute": 2, "second": 5, "clock": "01:05", "type": "pass", "team": "home",
                    "player": "h8"},
             "e3": {"id": "e3", "minute": 3, "second": 5, "clock": "02:05", "type": "pass", "team": "home",
                    "player": "h9"}}
    prompts = []

    class Reply:
        response_id = "r"

        def __init__(self, text, tool_call=False):
            self.text = text
            call = SimpleNamespace(type=ae.foundry.TOOL_CALL, tool_name="list_events", name=None,
                                   arguments="{}")
            self.messages = [SimpleNamespace(contents=[call])] if tool_call else []

    class Agent:
        def __init__(self, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def run(self, prompt):
            prompts.append(prompt)
            if len(prompts) == 3:  # minute 3 calls the match tools anyway
                return Reply('{"text": "h9 plays a pass.", "evidence": ["e3"]}', tool_call=True)
            return Reply('{"text": "h7 plays a pass.", "evidence": ["e1"]}')

    async def judge(agent, claim, evidence):
        return Verdict(ok=True)

    monkeypatch.setattr(ae, "MINUTES", 3)
    monkeypatch.setattr(ae, "FoundryAgent", Agent)
    monkeypatch.setattr(ae, "judge", judge)
    monkeypatch.setattr(ae.foundry, "chat_client", lambda credential: object())
    monkeypatch.setattr(ae.foundry, "slice_agents", lambda client: ["analyst", "judge"])
    monkeypatch.setattr(ae.foundry, "pinned", lambda local: (f"ninety-{local}", "1"))
    rows, _ = asyncio.run(ae._drafts(None, [7], {7: known}))
    assert "seed7-inline" in prompts[0] and '"e1"' in prompts[0] and '"e2"' not in prompts[0]
    assert '"e2"' in prompts[1] and '"e1"' not in prompts[1]  # each minute's own events only
    verdicts = [r["verdict"] for r in rows]
    # Minute 1 cites what it was shown; minute 2 cites minute 1's event, which it never saw; minute 3
    # called the tools, so what it read is not graded.
    assert verdicts == ["accept", "reject", "reject"]
    assert "called the match tools" in rows[2]["reasons"][0]
