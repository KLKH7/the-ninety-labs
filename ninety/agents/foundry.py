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
same thing in CI). Tools stay ours: the Analyst's tools are the MCP server's, declared on the
published agent and executed here, so the agent still reads the match only through MCP.
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

from agent_framework import Agent, FunctionTool, MCPStdioTool
from agent_framework.foundry import FoundryChatClient, to_prompt_agent
from azure.ai.projects.models import PromptAgentDefinition, RaiConfig

from ninety import config

REGISTRY = Path(__file__).with_name("foundry_agents.json")
GUARDRAIL = "ninety-guardrail"  # Microsoft.CognitiveServices/accounts/raiPolicies in infra/main.bicep
PREFIX = "ninety-"

# to_prompt_agent is marked experimental; we pin agent-framework-foundry in uv.lock and test it.
warnings.filterwarnings("ignore", message=r"\[TO_PROMPT_AGENT\]")


class RegistryDrift(RuntimeError):
    """The code's definition of an agent differs from the version pinned in foundry_agents.json."""


def foundry_name(agent: Agent) -> str:
    return PREFIX + agent.name


def definition(agent: Agent, guardrail: str = GUARDRAIL) -> PromptAgentDefinition:
    """The prompt agent for `agent`. Fingerprints use the guardrail's name; publishing passes the
    full resource id Foundry requires, which holds our subscription id and stays out of the repo."""
    defn = to_prompt_agent(agent, rai_config=RaiConfig(rai_policy_name=guardrail))
    for tool in defn.get("tools") or []:
        tool["parameters"] = strict_schema(tool["parameters"])
        if tool.get("description"):
            # MCP tool descriptions are docstrings, which Python 3.13 dedents at compile time and
            # 3.11/3.12 do not; clean them so every interpreter publishes and pins the same text.
            tool["description"] = inspect.cleandoc(tool["description"])
    return defn


def strict_schema(schema: dict) -> dict:
    """Foundry declares function tools strict, so the model must send valid arguments; a strict
    schema lists every property as required (optional ones are nullable) and allows no others.
    The MCP server's schemas are not written that way, so declare them so here."""
    schema = {k: v for k, v in schema.items() if k != "default"}  # strict mode has no defaults
    if schema.get("type") == "object" and "properties" in schema:
        schema["properties"] = {k: strict_schema(v) for k, v in schema["properties"].items()}
        schema["required"] = list(schema["properties"])
        schema["additionalProperties"] = False
    for key in ("anyOf", "items"):
        if isinstance(schema.get(key), list):
            schema[key] = [strict_schema(s) for s in schema[key]]
        elif isinstance(schema.get(key), dict):
            schema[key] = strict_schema(schema[key])
    return schema


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


def analyst_agent(client: FoundryChatClient, tools: list[FunctionTool]) -> Agent:
    from ninety.agents.slice import INSTRUCTIONS

    return Agent(client=client, name="analyst", instructions=INSTRUCTIONS, tools=tools)


def build_agents(client: FoundryChatClient, match_tools: list[FunctionTool]) -> list[Agent]:
    """Every agent we publish, built exactly as the live workflow builds them."""
    from ninety.agents.judge import judge_agent

    return [analyst_agent(client, match_tools), judge_agent(client)]


def match_mcp(seed: int = 7, minutes: float = 5) -> MCPStdioTool:
    return MCPStdioTool(
        name="match",
        command=sys.executable,
        args=["-m", "ninety.mcp.match_server"],
        env={"NINETY_SEED": str(seed), "NINETY_MINUTES": str(minutes)},
    )


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
    async with match_mcp() as tools:
        agents = build_agents(chat_client(credential), tools.functions)
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
