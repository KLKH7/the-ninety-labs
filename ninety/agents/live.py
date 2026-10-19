"""The Milestone 1 live path: detected events -> Ledger and stats -> agents -> overlay cues.

    uv run ninety-live --out runs/m1/cues.jsonl                   # the M1 clip's detected events
    uv run ninety-live --detected detected.jsonl --out cues.jsonl

Everything here reads detected events only (ninety/match/detected.py): never the clip's
events.jsonl or frames.jsonl, never the truth containers, never the simulator.
tests/test_live_reads_no_truth.py runs this path and fails if any of them is touched.

What airs:
- a template cue for every confidently detected pass, shot and goal, the moment it is detected
  (ninety/agents/cues.py); an unsure detection gets none;
- when an Analyst and a Judge are given, the claim the fact-checker verified, as an `insight` cue
  for the analyst persona. A claim resting on an unsure detection is held and never airs.

Without models (the CLI) only the template cues are written: the agents need Foundry, or a
recording made against these same detected events.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import dataclass
from pathlib import Path

from jsonschema import validate

from ninety.agents.cues import DISPLAY_SECONDS, SCHEMA, template_cues, write_fixture
from ninety.agents.ledger import InMemoryLedger, Record, load_match
from ninety.agents.slice import Ask, Judge, Outcome, run_workflow
from ninety.match import detected
from ninety.match.facts import AGENT_TYPES, compact

INSIGHT_SLOT = "top_right"  # apart from the template's lower third, so both can be on screen


@dataclass
class LiveResult:
    cues: list[dict]
    facts: int
    held_detections: list[str]  # passes, shots and goals detected too unsure to air
    outcome: Outcome | None


def insight_cue(outcome: Outcome, times: dict[str, float]) -> dict:
    """The verified claim as an on-screen cue, timed from the last event it cites."""
    t_in = max(times[i] for i in outcome.claim.evidence)
    cue = {
        "id": "insight-" + "-".join(outcome.claim.evidence),
        "t_in": t_in,
        "t_out": round(t_in + DISPLAY_SECONDS, 2),
        "kind": "insight",
        "slot": INSIGHT_SLOT,
        "anchor": None,
        "persona": "analyst",
        "lang": "en",
        "text": outcome.claim.text,
        "verified": True,
        "replaces": None,
        "evidence": list(outcome.claim.evidence),
    }
    validate(cue, SCHEMA)
    return cue


async def run(
    events: list[dict],
    clip: str = detected.M1_CLIP,
    ask: Ask | None = None,
    judge: Judge | None = None,
    minute: int | None = None,
) -> LiveResult:
    events = detected.check([dict(e) for e in events], clip)
    ledger = InMemoryLedger()
    await load_match(ledger, events, ())  # stats from the detected events; no tracking frames yet
    cues = await template_cues(ledger)
    shown = {i for cue in cues for i in cue["evidence"]}
    held = [
        e["id"] for e in events if e["type"] in {"pass", "shot", "goal"} and e["id"] not in shown
    ]
    outcome = None
    if ask is not None and judge is not None and minute is not None:
        # The fact-checker knows what the Analyst can read over MCP: the compact detected events.
        rows = [compact(e) for e in events if e["type"] in AGENT_TYPES]
        times = {e["id"]: e["t"] for e in events}
        outcome = await run_workflow(
            ask, judge, minute, False, int(clip.removeprefix("seed")), 0, False, rows
        )
        await ledger.append(Record(
            id=f"claim-minute{minute}", version=1, kind="claim", t=0.0, source="agents",
            confidence=None, evidence=tuple(i for i in outcome.claim.evidence if i in times),
            payload={"text": outcome.claim.text, "status": outcome.status},
        ))
        if outcome.accepted:
            cues.append(insight_cue(outcome, times))
    for cue in cues:
        await ledger.append(Record(
            id=cue["id"], version=1, kind="cue", t=cue["t_in"], source="agents", confidence=None,
            evidence=tuple(cue["evidence"]), payload=cue,
        ))
    facts = len(await ledger.query(kind="fact"))
    cues.sort(key=lambda c: (c["t_in"], c["id"]))
    return LiveResult(cues, facts, held, outcome)


def main() -> None:
    ap = argparse.ArgumentParser(description="Detected events to overlay cues (the M1 live path).")
    ap.add_argument("--detected", type=Path, help="detected events (default: the M1 clip's)")
    ap.add_argument("--clip", default=detected.M1_CLIP)
    ap.add_argument("--out", type=Path, required=True, help="overlay cues, one per line")
    args = ap.parse_args()
    path = args.detected or detected.m1_path(args.clip)
    if detected.is_standin(path):
        print(f"note: {path.name} is a hand-written stand-in, not the detector's output")
    result = asyncio.run(run(detected.load(path), args.clip))
    write_fixture(result.cues, args.out)
    print(json.dumps({
        "detected": str(path), "cues": len(result.cues), "facts": result.facts,
        "held_detections": result.held_detections,
    }))


if __name__ == "__main__":
    main()
