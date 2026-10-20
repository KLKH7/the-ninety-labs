"""Our agents as versioned Microsoft Foundry prompt agents.

Each agent is defined once in code (model, instructions, output schema, tools) and published to
the Foundry project as a prompt agent with the `ninety-guardrail` content-safety policy
(infra/main.bicep). Live runs call the published version by name and version, so what ran is
visible in Foundry: the agent, its version, its guardrail and its traces.

    uv run ninety-agents publish   # create a new version of any agent whose definition changed
    uv run ninety-agents status    # does the code still match the pinned versions?

`foundry_agents.json` pins each agent to a version and to the fingerprint of the definition it was
published from. A live run refuses to start when the code no longer matches its pinned version, so
a changed prompt cannot run under an old version's name (tests/test_foundry_agents.py checks the
same thing in CI). The Analyst reads the match only through our MCP server, which Foundry calls
itself at /mcp on the API (ninety/mcp/match_server.py), with the key held in the project connection
`ninety-match-mcp` (infra/main.bicep).
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import inspect
import json
import sys
import warnings
from pathlib import Path

from agent_framework import Agent
from agent_framework.foundry import FoundryChatClient, to_prompt_agent
from azure.ai.projects.models import PromptAgentDefinition, RaiConfig

from ninety import config
from ninety.mcp import match_server

REGISTRY = Path(__file__).with_name("foundry_agents.json")
MCP_CONNECTION = "ninety-match-mcp"  # Foundry project connection holding the MCP key (infra/main.bicep)
GUARDRAIL = "ninety-guardrail"  # Microsoft.CognitiveServices/accounts/raiPolicies in infra/main.bicep
PREFIX = "ninety-"
DESCRIPTIONS = {"description", "server_description"}  # keys whose text can come from a docstring

# to_prompt_agent is marked experimental; we pin agent-framework-foundry in uv.lock and test it.
warnings.filterwarnings("ignore", message=r"\[TO_PROMPT_AGENT\]")


class RegistryDrift(RuntimeError):
    """The code's definition of an agent differs from the version pinned in foundry_agents.json."""


def foundry_name(agent: Agent) -> str:
    return PREFIX + agent.name


def definition(agent: Agent, guardrail: str = GUARDRAIL) -> PromptAgentDefinition:
    """The prompt agent for `agent`. Fingerprints use the guardrail's name; publishing passes the
    full resource id Foundry requires, which holds our subscription id and stays out of the repo.

    Tool descriptions come from docstrings, which Python 3.13 dedents at compile time and 3.11 and
    3.12 do not; they are cleaned here so the fingerprint and what is published agree on every
    Python we support."""
    defn = to_prompt_agent(agent, rai_config=RaiConfig(rai_policy_name=guardrail))
    return PromptAgentDefinition(_clean_descriptions(defn.as_dict()))


def _clean_descriptions(node):
    if isinstance(node, dict):
        return {
            k: inspect.cleandoc(v) if k in DESCRIPTIONS and isinstance(v, str) else _clean_descriptions(v)
            for k, v in node.items()
        }
    if isinstance(node, list):
        return [_clean_descriptions(v) for v in node]
    return node


def guardrail_id() -> str:
    if not config.FOUNDRY_RESOURCE_ID:
        raise RuntimeError("set NINETY_FOUNDRY_RESOURCE_ID to publish (see ninety/config.py)")
    return f"{config.FOUNDRY_RESOURCE_ID}/raiPolicies/{GUARDRAIL}"


def fingerprint(defn: PromptAgentDefinition) -> str:
    """Stable hash of everything that shapes the agent's behaviour: model, instructions, output
    schema, tools and guardrail."""
    body = json.dumps(defn.as_dict(), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(body.encode()).hexdigest()[:16]


def load_registry(path: Path = REGISTRY) -> dict[str, dict[str, str]]:
    return json.loads(path.read_text()) if path.exists() else {}


def pinned(agent: Agent, registry: dict[str, dict[str, str]] | None = None) -> tuple[str, str]:
    """The Foundry name and version to call for this agent. Raises RegistryDrift when the code's
    definition is not the one that version was published from."""
    registry = load_registry() if registry is None else registry
    name = foundry_name(agent)
    entry = registry.get(name)
    sha = fingerprint(definition(agent))
    if entry is None:
        raise RegistryDrift(f"{name} has never been published: run `uv run ninety-agents publish`")
    if entry["definition_sha"] != sha:
        raise RegistryDrift(
            f"{name} changed since version {entry['version']} was published "
            f"({entry['definition_sha']} -> {sha}): run `uv run ninety-agents publish`"
        )
    return name, entry["version"]


def match_tool():
    """Our MCP server as a Foundry-hosted tool: Foundry calls it, with the key from the project
    connection; no approval step, and only the server's own read-only tools."""
    return FoundryChatClient.get_mcp_tool(
        name="match",
        url=config.MATCH_MCP_URL,
        description="Read-only events of a synthetic match, by match id and minute.",
        approval_mode="never_require",
        allowed_tools=list(match_server.TOOLS),
        project_connection_id=MCP_CONNECTION,
    )


def analyst_agent(client: FoundryChatClient) -> Agent:
    from ninety.agents.slice import INSTRUCTIONS

    return Agent(client=client, name="analyst", instructions=INSTRUCTIONS, tools=[match_tool()])


def moment_analyst_agent(client: FoundryChatClient) -> Agent:
    """The workflow's Analyst: picks the moments of a minute, through the same MCP tools. Its own
    agent, so the slice's Analyst (and its recorded prompts) stay exactly as they are."""
    from ninety.agents.workflow import MOMENT_ANALYST_INSTRUCTIONS

    return Agent(
        client=client, name="moment-analyst", instructions=MOMENT_ANALYST_INSTRUCTIONS, tools=[match_tool()]
    )


def tactician_agent(client: FoundryChatClient) -> Agent:
    from ninety.agents.contracts import TACTICIAN_INSTRUCTIONS

    return Agent(client=client, name="tactician", instructions=TACTICIAN_INSTRUCTIONS)


def challenger_agent(client: FoundryChatClient) -> Agent:
    from ninety.agents.contracts import CHALLENGER_INSTRUCTIONS

    return Agent(client=client, name="challenger", instructions=CHALLENGER_INSTRUCTIONS)


def slice_agents(client: FoundryChatClient) -> list[Agent]:
    """The slice's agents, in the order it runs them: the Analyst, then the Judge."""
    from ninety.agents.judge import judge_agent

    return [analyst_agent(client), judge_agent(client)]


def workflow_agents(client: FoundryChatClient) -> dict[str, Agent]:
    """The workflow's agents by role (ninety/agents/workflow.py). The Judge is the slice's."""
    from ninety.agents.judge import judge_agent

    return {
        "analyst": moment_analyst_agent(client),
        "tactician": tactician_agent(client),
        "challenger": challenger_agent(client),
        "judge": judge_agent(client),
    }


def build_agents(client: FoundryChatClient) -> list[Agent]:
    """Every agent we publish, once each, built exactly as the live runs build them. The
    Personalizer runs in its own service (ninety/personalizer/server.py)."""
    from ninety.agents.describer import describer_agent
    from ninety.personalizer.core import personalizer_agent

    agents = [*slice_agents(client), *workflow_agents(client).values(), personalizer_agent(client),
              describer_agent(client)]
    return list({a.name: a for a in agents}.values())


def chat_client(credential=None) -> FoundryChatClient:
    from azure.identity import DefaultAzureCredential

    return FoundryChatClient(
        project_endpoint=config.FOUNDRY_PROJECT,
        model=config.MODEL,
        credential=credential or DefaultAzureCredential(),
    )


def publish(project, agents: list[Agent], path: Path = REGISTRY) -> dict[str, dict[str, str]]:
    """Create a new Foundry version for each agent whose definition changed; reuse the latest
    version when it was published from the same definition. Writes the registry file."""
    registry, policy = load_registry(path), guardrail_id()
    for agent in agents:
        name, sha = foundry_name(agent), fingerprint(definition(agent))
        latest = _latest_version(project, name)
        if latest is not None and (latest.metadata or {}).get("definition_sha") == sha:
            version = latest.version
        else:
            created = project.agents.create_version(
                name,
                definition=definition(agent, policy),
                metadata={"definition_sha": sha},
                description=(agent.description or f"The Ninety Labs {agent.name}"),
            )
            version = created.version
        registry[name] = {"version": str(version), "definition_sha": sha}
        print(f"{name}: version {version} ({sha})")
    path.write_text(json.dumps(registry, indent=2, sort_keys=True) + "\n")
    return registry


def _latest_version(project, name: str):
    from azure.core.exceptions import ResourceNotFoundError

    try:
        return next(iter(project.agents.list_versions(name, limit=1, order="desc")), None)
    except ResourceNotFoundError:
        return None


async def _with_agents(action) -> int:
    from azure.ai.projects import AIProjectClient
    from azure.identity import DefaultAzureCredential

    credential = DefaultAzureCredential()
    agents = build_agents(chat_client(credential))
    if action == "status":
        registry, stale = load_registry(), 0
        for agent in agents:
            try:
                name, version = pinned(agent, registry)
                print(f"{name}: version {version}, matches the code")
            except RegistryDrift as e:
                print(e)
                stale += 1
        return 1 if stale else 0
    with AIProjectClient(endpoint=config.FOUNDRY_PROJECT, credential=credential) as project:
        publish(project, agents)
    return 0


def main() -> None:
    ap = argparse.ArgumentParser(description="Publish our agents to Foundry as versioned prompt agents.")
    ap.add_argument("action", choices=["publish", "status"])
    sys.exit(asyncio.run(_with_agents(ap.parse_args().action)))
