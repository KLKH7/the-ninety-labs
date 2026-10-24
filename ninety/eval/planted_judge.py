"""Records the published Judge's answers to the planted claims no earlier run asked it, once.

    uv run python -m ninety.eval.planted_judge   # calls Foundry: costs model tokens

The planted set's own Judge answers come from the recorded nightly evaluation, which only asked the
Judge about claims the code checks let through. The `no typed facts` ablation sends every claim to
the Judge, so the claims only the code checks ever saw have no answer there. This asks the
published Judge (the version pinned in ninety/agents/foundry_agents.json, the same path as
ninety/eval/factcheck_eval.py) each of those once, and writes the answers, the commit, the version
and the tokens used to docs/eval/planted-claims-v1-judge.json. Nothing reads Foundry after that: the
reports read the file. A failed call is written as failed, and that claim stays unmeasured.
"""

from __future__ import annotations

import asyncio
import datetime
import json
import subprocess
from dataclasses import asdict

from ninety import config
from ninety.agents.evidence import KEY
from ninety.agents.factcheck import Claim
from ninety.agents.judge import judge
from ninety.eval import ablation, planted
from ninety.eval.factcheck_eval import judge_under_test

# gpt-4.1-mini list price, USD per million tokens (Azure OpenAI, global standard), to report cost.
PRICE_PER_MILLION = {"input": 0.40, "output": 1.60}


class CountingAgent:
    """Passes calls through and adds up the tokens each reply reports."""

    def __init__(self, agent):
        self.agent, self.tokens, self.calls = agent, {"input": 0, "output": 0}, 0

    async def run(self, prompt: str):
        self.calls += 1
        response = await self.agent.run(prompt)
        usage = response.usage_details or {}
        self.tokens["input"] += usage.get("input_token_count") or 0
        self.tokens["output"] += usage.get("output_token_count") or 0
        return response


def to_ask(data: dict) -> list[dict]:
    known = ablation.known_events(data["claims"])
    return [
        item for item in data["claims"]
        if ablation.screen(item, known[item["seed"]], "no typed facts")[0] == ablation.UNMEASURED
    ]


async def record(items: list[dict], concurrency: int = 3) -> dict:
    gate = asyncio.Semaphore(concurrency)
    async with judge_under_test(local=False) as (agent, label, defs):
        counting = CountingAgent(agent)

        async def one(item):
            async with gate:
                claim = Claim(item["text"], item["evidence"])
                return item["id"], await judge(counting, claim, item["events"])

        answers = dict(await asyncio.gather(*(one(i) for i in items)))
    sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True,
                         cwd=planted.ROOT).stdout.strip()
    cost = sum(counting.tokens[k] * PRICE_PER_MILLION[k] / 1e6 for k in counting.tokens)
    return {
        "version": planted.VERSION,
        "judge": label.replace("`", ""),
        KEY: defs,  # the Judge's version and definition fingerprint (ninety/agents/evidence.py)
        "model": config.MODEL,
        "commit": sha,
        "recorded_at": datetime.date.today().isoformat(),
        "calls": counting.calls,
        "tokens": counting.tokens,
        "cost_usd_at_list_price": round(cost, 4),
        "price_per_million_usd": PRICE_PER_MILLION,
        "answers": {i: asdict(v) for i, v in sorted(answers.items())},
    }


def main() -> None:
    if planted.JUDGE_PATH.exists():
        raise SystemExit(f"{planted.JUDGE_PATH.name} exists: recorded once; delete it to re-record")
    items = to_ask(planted.load())
    print(f"asking the published Judge about {len(items)} planted claims")
    out = asyncio.run(record(items))
    planted.JUDGE_PATH.write_text(json.dumps(out, indent=1) + "\n")
    print(json.dumps({k: v for k, v in out.items() if k != "answers"}, indent=1))


if __name__ == "__main__":
    main()
