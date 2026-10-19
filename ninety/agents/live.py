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
- when a Personalizer is given too (ninety/personalizer: over A2A, or in-process), that claim
  reworded for the other personas and in Spanish: one more `insight` cue per variant that passes
  the fact-checker again (ninety/personalizer/cues.py). A variant that fails is never shown, and a
  Personalizer that fails takes nothing else down with it.

Without models (the CLI) only the template cues are written: the agents need Foundry, or a
recording made against these same detected events.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from dataclasses import dataclass, field
from pathlib import Path

from jsonschema import validate

from ninety.agents.contracts import Personalize, Profile, TraceStep
from ninety.agents.cues import DISPLAY_SECONDS, SCHEMA, template_cues, write_fixture
from ninety.agents.ledger import InMemoryLedger, Record, load_match
from ninety.agents.slice import Ask, Judge, Outcome, run_workflow
from ninety.match import detected
from ninety.match.facts import AGENT_TYPES, compact
from ninety.personalizer import cues as personal

INSIGHT_SLOT = "top_right"  # apart from the template's lower third, so both can be on screen


@dataclass
class LiveResult:
    cues: list[dict]
    facts: int
    held_detections: list[str]  # passes, shots and goals detected too unsure to air
    outcome: Outcome | None
    # the Personalizer's variants that did not air: (persona, lang, status, reasons)
    refused_variants: list[tuple[str, str, str, list[str]]] = field(default_factory=list)
    trace: list[TraceStep] = field(default_factory=list)


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
    personalize: Personalize | None = None,
    profiles: list[Profile] | None = None,
) -> LiveResult:
    events = detected.check([dict(e) for e in events], clip)
    ledger = InMemoryLedger()
    await load_match(ledger, events, ())  # stats from the detected events; no tracking frames yet
    cues = await template_cues(ledger)
    shown = {i for cue in cues for i in cue["evidence"]}
    held = [
        e["id"] for e in events if e["type"] in {"pass", "shot", "goal"} and e["id"] not in shown
    ]
    outcome, refused, trace = None, [], []
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
            if personalize is not None:
                personalized, refused = await _personalized(
                    outcome.claim, events, rows, times, judge, personalize, profiles, trace
                )
                cues.extend(personalized)
    for cue in cues:
        await ledger.append(Record(
            id=cue["id"], version=1, kind="cue", t=cue["t_in"], source="agents", confidence=None,
            evidence=tuple(cue["evidence"]), payload=cue,
        ))
    facts = len(await ledger.query(kind="fact"))
    cues.sort(key=lambda c: (c["t_in"], c["id"]))
    return LiveResult(cues, facts, held, outcome, refused, trace)


async def _personalized(
    claim, events, rows, times, judge, personalize, profiles, trace
) -> tuple[list[dict], list[tuple[str, str, str, list[str]]]]:
    """The verified claim for every other profile, each variant checked again before it airs."""
    moment = "-".join(claim.evidence)
    if profiles is None:
        profiles = personal.profiles_for(next(e for e in events if e["id"] == claim.evidence[0]))
    known = {r["id"]: r for r in rows}
    started = time.perf_counter()
    try:
        variants = await personalize(claim, [known[i] for i in claim.evidence], profiles)
    except Exception as error:  # a defect in the Personalizer: the analyst insight still airs
        detail = f"{type(error).__name__}: {error}"
        trace.append(TraceStep("personalizer", moment, "error", _ms(started), detail))
        return [], []
    route = getattr(personalize, "last_route", "") or "in_process"  # RemotePersonalizer says which
    trace.append(TraceStep("personalizer", moment, route.split(":")[0], _ms(started), route))
    asked, seen, kept = {(p.persona, p.lang) for p in profiles}, set(), []
    for v in variants:  # only what was asked for, once each
        if (v.persona, v.lang) in asked and (v.persona, v.lang) not in seen:
            seen.add((v.persona, v.lang))
            kept.append(v)
    checked = await personal.verify(claim, kept, known, judge)
    for variant, status, reasons in checked.refused:
        detail = f"{variant.persona}/{variant.lang}: " + "; ".join(reasons)
        trace.append(TraceStep("fact_checker", moment, status, 0.0, detail))
    t_in = max(times[i] for i in claim.evidence)
    shown = [personal.variant_cue(v, t_in) for v in checked.shown]
    trace.append(TraceStep("producer", moment, "air", 0.0, f"{len(shown)} of {len(kept)} variants"))
    return shown, [(v.persona, v.lang, status, reasons) for v, status, reasons in checked.refused]


def _ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 1)


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
