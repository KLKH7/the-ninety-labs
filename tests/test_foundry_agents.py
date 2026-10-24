"""The published Foundry agents and the code that defines them must not drift apart.

No Azure needed: definitions are built from the code and compared with the versions pinned in
ninety/agents/foundry_agents.json; publishing runs against a fake project client.
"""

import asyncio
from types import SimpleNamespace

import pytest
from azure.identity import DefaultAzureCredential

from ninety import config
from ninety.agents import foundry
from ninety.mcp import match_server

AGENTS = foundry.build_agents(foundry.chat_client(DefaultAzureCredential()))
SHAS = {foundry.foundry_name(a): foundry.fingerprint(foundry.definition(a)) for a in AGENTS}


def test_every_agent_matches_its_pinned_version():
    # Fails when a prompt, output schema, tool or guardrail changes without `ninety-agents publish`.
    registry = foundry.load_registry()
    assert set(registry) == set(SHAS), "publish every agent the workflow uses, and only those"
    for agent in AGENTS:
        name, version = foundry.pinned(agent, registry)
        assert registry[name]["version"] == version


def test_a_changed_prompt_refuses_to_run_under_the_old_version():
    analyst = AGENTS[0]
    changed = foundry.Agent(
        client=analyst.client, name=analyst.name, instructions="Anything.", tools=[foundry.match_tool()]
    )
    with pytest.raises(foundry.RegistryDrift, match="changed since version"):
        foundry.pinned(changed)


def test_an_unpublished_agent_refuses_to_run():
    with pytest.raises(foundry.RegistryDrift, match="never been published"):
        foundry.pinned(AGENTS[1], registry={})


def test_every_agent_is_published_with_the_guardrail():
    for agent in AGENTS:
        assert foundry.definition(agent)["rai_config"]["rai_policy_name"] == foundry.GUARDRAIL


def test_the_analyst_reads_the_match_only_through_our_mcp_server():
    (tool,) = foundry.definition(AGENTS[0]).as_dict()["tools"]
    assert tool["type"] == "mcp" and tool["server_url"] == config.MATCH_MCP_URL
    # Foundry sends the key from this connection; no call waits for a human approval.
    assert tool["project_connection_id"] == foundry.MCP_CONNECTION and tool["require_approval"] == "never"
    assert tool["allowed_tools"] == list(match_server.TOOLS)


def test_the_allowed_tools_are_the_servers_tools():
    served = asyncio.run(match_server.server.list_tools())
    assert sorted(t.name for t in served) == sorted(match_server.SERVED)
    # The published Analyst may call a subset; team_shape joins it when the Analyst is republished.
    assert set(match_server.TOOLS) <= set(match_server.SERVED)
    assert set(match_server.SERVED) - set(match_server.TOOLS) == {"team_shape"}


def test_the_team_shape_tool_describes_its_typed_facts():
    (tool,) = [t for t in asyncio.run(match_server.server.list_tools()) if t.name == "team_shape"]
    assert set(tool.inputSchema["properties"]) == {"match", "minute_from", "minute_to"}
    for word in ("width", "line_height", "area", "behind_ball", "confident", "change", "tracked"):
        assert word in tool.description


def test_the_judge_has_no_tools():
    assert "tools" not in foundry.definition(AGENTS[1]).as_dict()


def test_the_companion_has_no_tools_and_answers_in_the_reply_format():
    # It reads only the facts in its prompt: no match tools, no way to fetch anything else.
    companion = next(a for a in AGENTS if a.name == "companion")
    defn = foundry.definition(companion).as_dict()
    assert "tools" not in defn
    assert defn["text"]["format"]["type"] == "json_schema"


WORKFLOW = foundry.workflow_agents(foundry.chat_client(DefaultAzureCredential()))


def test_the_workflow_analyst_reads_the_match_only_through_our_mcp_server():
    (tool,) = foundry.definition(WORKFLOW["analyst"]).as_dict()["tools"]
    assert tool["type"] == "mcp" and tool["server_url"] == config.MATCH_MCP_URL
    assert tool["allowed_tools"] == list(match_server.TOOLS)


@pytest.mark.parametrize("role", ["tactician", "challenger"])
def test_the_writers_have_no_tools(role):
    # They read only the moment they are given, as data in the prompt.
    assert "tools" not in foundry.definition(WORKFLOW[role]).as_dict()


def test_every_workflow_agent_is_published_and_the_judge_is_the_slices():
    names = {foundry.foundry_name(a) for a in AGENTS}
    assert {foundry.foundry_name(a) for a in WORKFLOW.values()} <= names
    assert foundry.foundry_name(WORKFLOW["judge"]) == foundry.foundry_name(AGENTS[1])
    assert len(names) == len(AGENTS)  # published once each


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


def _probe(doc: str) -> foundry.Agent:
    def look(minute: int) -> str:
        return ""

    look.__doc__ = doc
    return foundry.Agent(client=AGENTS[0].client, name="probe", instructions="x", tools=[look])


def test_the_fingerprint_does_not_depend_on_docstring_indentation():
    # Python 3.13 dedents docstrings at compile time and 3.11 and 3.12 do not, so the same source
    # gives either text; a pin made on one Python must hold on the others.
    indented = _probe("Look at a minute.\n\n    Returns its events.\n    ")
    dedented = _probe("Look at a minute.\n\nReturns its events.\n")
    shas = {foundry.fingerprint(foundry.definition(a)) for a in (indented, dedented)}
    assert len(shas) == 1
    # What is published is the cleaned text the fingerprint hashed.
    (tool,) = foundry.definition(indented).as_dict()["tools"]
    assert tool["description"] == "Look at a minute.\n\nReturns its events."


def test_an_mcp_tool_description_is_cleaned_too():
    mcp = foundry.FoundryChatClient.get_mcp_tool(
        name="match", url="https://example.invalid/mcp", description="Read events.\n\n    Read-only.\n    "
    )
    agent = foundry.Agent(client=AGENTS[0].client, name="probe", instructions="x", tools=[mcp])
    (tool,) = foundry.definition(agent).as_dict()["tools"]
    assert tool["server_description"] == "Read events.\n\nRead-only."
