"""The published Foundry agents and the code that defines them must not drift apart.

No Azure needed: definitions are built from the code (with the real MCP server's tool schemas) and
compared with the versions pinned in ninety/agents/foundry_agents.json; publishing runs against a
fake project client.
"""

import asyncio
from types import SimpleNamespace

import pytest
from azure.identity import DefaultAzureCredential

from ninety.agents import foundry


def _definitions():
    async def build():
        async with foundry.match_mcp() as tools:
            agents = foundry.build_agents(foundry.chat_client(DefaultAzureCredential()), tools.functions)
            shas = {foundry.foundry_name(a): foundry.fingerprint(foundry.definition(a)) for a in agents}
            return agents, shas

    return asyncio.run(build())


AGENTS, SHAS = _definitions()


def test_every_agent_matches_its_pinned_version():
    # Fails when a prompt, output schema, tool or guardrail changes without `ninety-agents publish`.
    registry = foundry.load_registry()
    assert set(registry) == set(SHAS), "publish every agent the workflow uses, and only those"
    for agent in AGENTS:
        name, version = foundry.pinned(agent, registry)
        assert registry[name]["version"] == version


def test_a_changed_prompt_refuses_to_run_under_the_old_version():
    analyst = AGENTS[0]
    tools = analyst.default_options["tools"]
    changed = foundry.Agent(client=analyst.client, name=analyst.name, instructions="Anything.", tools=tools)
    with pytest.raises(foundry.RegistryDrift, match="changed since version"):
        foundry.pinned(changed)


def test_an_unpublished_agent_refuses_to_run():
    with pytest.raises(foundry.RegistryDrift, match="never been published"):
        foundry.pinned(AGENTS[1], registry={})


def test_every_agent_is_published_with_the_guardrail():
    for agent in AGENTS:
        assert foundry.definition(agent)["rai_config"]["rai_policy_name"] == foundry.GUARDRAIL


def test_tool_schemas_are_strict():
    tools = foundry.definition(AGENTS[0])["tools"]
    assert {t["name"] for t in tools} == {"list_events", "match_info"}
    for tool in tools:
        params = tool["parameters"]
        assert tool["strict"] is True
        assert params["additionalProperties"] is False
        assert set(params["required"]) == set(params["properties"])
        assert "default" not in str(params)


def test_the_fingerprint_does_not_depend_on_docstring_indentation():
    # Python 3.13 dedents docstrings at compile time and 3.11/3.12 do not, and the MCP tools'
    # descriptions are docstrings: the same code must pin the same version on every interpreter.
    analyst = AGENTS[0]

    def described(text):
        tools = [
            foundry.FunctionTool(name=t.name, description=text, input_model=t.parameters())
            for t in analyst.default_options["tools"]
        ]
        agent = foundry.Agent(client=analyst.client, name=analyst.name, instructions="x", tools=tools)
        return foundry.definition(agent)

    kept = described("First line.\n    second line,\n    third line.")  # 3.11 and 3.12
    stripped = described("First line.\nsecond line,\nthird line.")  # 3.13
    assert foundry.fingerprint(kept) == foundry.fingerprint(stripped)
    assert {t["description"] for t in kept["tools"]} == {"First line.\nsecond line,\nthird line."}


def test_strict_schema_reaches_nested_objects():
    schema = {
        "type": "object",
        "properties": {
            "a": {"anyOf": [{"type": "object", "properties": {"b": {"type": "integer", "default": 1}}}]}
        },
    }
    nested = foundry.strict_schema(schema)["properties"]["a"]["anyOf"][0]
    assert nested["required"] == ["b"] and nested["additionalProperties"] is False
    assert "default" not in nested["properties"]["b"]


class FakeAgents:
    def __init__(self, latest=None):
        self.latest, self.created = latest, []

    def list_versions(self, name, limit, order):
        return [self.latest] if self.latest else []

    def create_version(self, name, definition, metadata, description):
        self.created.append((name, definition, metadata))
        return SimpleNamespace(version=str(len(self.created) + 1))


def test_publish_reuses_a_version_published_from_the_same_definition(tmp_path, monkeypatch):
    monkeypatch.setattr(foundry.config, "FOUNDRY_RESOURCE_ID", "/subscriptions/s/providers/x/accounts/a")
    judge = AGENTS[1]
    same = SimpleNamespace(version="4", metadata={"definition_sha": SHAS[foundry.foundry_name(judge)]})
    project = SimpleNamespace(agents=FakeAgents(latest=same))
    registry = foundry.publish(project, [judge], tmp_path / "r.json")
    assert project.agents.created == [] and registry["ninety-judge"]["version"] == "4"


def test_publish_creates_a_version_when_the_definition_changed(tmp_path, monkeypatch):
    monkeypatch.setattr(foundry.config, "FOUNDRY_RESOURCE_ID", "/subscriptions/s/providers/x/accounts/a")
    stale = SimpleNamespace(version="4", metadata={"definition_sha": "old"})
    project = SimpleNamespace(agents=FakeAgents(latest=stale))
    registry = foundry.publish(project, [AGENTS[1]], tmp_path / "r.json")
    (name, defn, metadata), = project.agents.created
    assert metadata == {"definition_sha": SHAS["ninety-judge"]} and registry[name]["version"] == "2"
    # Foundry needs the policy's full resource id; the fingerprint uses only its name.
    policy = "/subscriptions/s/providers/x/accounts/a/raiPolicies/ninety-guardrail"
    assert defn["rai_config"]["rai_policy_name"] == policy


def test_publish_needs_the_foundry_resource_id(tmp_path, monkeypatch):
    monkeypatch.setattr(foundry.config, "FOUNDRY_RESOURCE_ID", "")
    with pytest.raises(RuntimeError, match="NINETY_FOUNDRY_RESOURCE_ID"):
        foundry.publish(SimpleNamespace(agents=FakeAgents()), [AGENTS[1]], tmp_path / "r.json")
