"""Latency from an event to its graphic, and model and speech spend per clip and per match.

    uv run python -m ninety.eval.latency_cost                  # rebuild docs/eval/latency-cost.md
    uv run python -m ninety.eval.latency_cost --check          # fail if the report is out of date
    uv run python -m ninety.eval.latency_cost --measure <clip> # time the chain again, re-count tokens
    uv run python -m ninety.eval.latency_cost --recount        # re-count tokens only, keep the timings

The report is rendered only from docs/eval/latency-cost.json, so rebuilding it is byte for byte
the same (tests/test_latency_cost.py). `--measure` and `--recount` are the only steps that run
anything, and they call no Azure service. `--recount` is for a change that moves the token counts
(an agent's instructions, an MCP tool's description, the recording) but not the chain's timing: it
rebuilds the counts and keeps the timings, with the commit they were measured at:

- Latency: ninety-e2e offline on one clip, and the committed slice replay, `--runs` times each in
  this process. Every stage records a `ninety.stage` span (ninety/agents/telemetry.py); the spans
  are caught in memory and summed per stage per run. Offline and in replay the models answer at
  once, so these are the chain's own costs; the models' time comes from live traces (planned).
- Tokens: rebuilt from the recorded replay's turns: the text each model call would have been sent
  and what it answered, counted at OpenAI's published rule of thumb (PRICES["tokens"]).
- Prices: the Azure Retail Prices API, quoted with the date they were read (PRICES). Never typed
  from memory: re-read them with the query in PRICES and change the date.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import platform
import subprocess
import sys
import tempfile
import time
import warnings
from collections import defaultdict
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from ninety.agents import telemetry

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "docs" / "eval" / "latency-cost.json"
REPORT = ROOT / "docs" / "eval" / "latency-cost.md"
RECORDING = ROOT / "replays" / "slice-minute2-plant.json"
# The template cues for seed 7's first five minutes (docs/EVALUATION.md: 108 cues for seed 7, five
# minutes): what the casual persona's graphics say, a floor for what a spoken description says.
CUES = ROOT / "tests" / "fixtures" / "cues-seed7.jsonl"
CUES_MINUTES = 5

BUDGET_USD = Decimal("0.50")  # docs/PLAN.md: model and speech spend per match
MATCH_MINUTES = 90  # one claim a minute (ninety/e2e.py: the one sentence a minute gets)
TARGET_GRAPHIC_P95_S = 8.0  # docs/PLAN.md
TARGET_SPEECH_P50_S, TARGET_SPEECH_P95_S = 2.0, 4.0  # docs/PLAN.md

# Read from https://prices.azure.com/api/retail/prices on the date below (USD, pay as you go,
# armRegionName 'northcentralus', where the Foundry and Speech resources are: ninety/config.py).
PRICES = {
    "read": "2026-10-19",
    "source": "Azure Retail Prices API, https://prices.azure.com/api/retail/prices",
    "query": "armRegionName eq 'northcentralus' and contains(meterName, '4.1 mini'), "
    "and contains(meterName, 'Neural')",
    "model": "gpt-4.1-mini",
    "items": {
        # meterName: (USD, per units, effectiveStartDate)
        "gpt 4.1 mini Inp glbl Tokens": (0.0004, 1_000, "2025-04-01"),
        "gpt 4.1 mini cached Inp glbl Tokens": (0.0001, 1_000, "2025-04-01"),
        "gpt 4.1 mini Outp glbl Tokens": (0.0016, 1_000, "2025-04-01"),
        "gpt 4.1 mini Inp Data Zone Tokens": (0.00044, 1_000, "2025-04-01"),
        "gpt 4.1 mini Outp Data Zone Tokens": (0.00176, 1_000, "2025-04-01"),
        "S1 Neural Text To Speech Characters": (15.0, 1_000_000, "2024-02-01"),
        "Neural HD Text to Speech Characters": (22.0, 1_000_000, "2026-03-01"),
    },
    # OpenAI, "What are tokens and how to count them" (help.openai.com): about 4 characters of
    # English text per token. An estimate, used until recordings carry the service's token usage.
    "tokens": {"chars_per_token": 4, "source": "OpenAI, What are tokens and how to count them"},
}
INPUT, OUTPUT = "gpt 4.1 mini Inp glbl Tokens", "gpt 4.1 mini Outp glbl Tokens"
INPUT_DZ, OUTPUT_DZ = "gpt 4.1 mini Inp Data Zone Tokens", "gpt 4.1 mini Outp Data Zone Tokens"
SPEECH, SPEECH_HD = "S1 Neural Text To Speech Characters", "Neural HD Text to Speech Characters"


def price(meter: str) -> Decimal:
    """USD for one unit (a token, a character), exactly. Money is Decimal throughout, so a total
    does not depend on the order it was summed in or on the Python version's float sum."""
    usd, per, _ = PRICES["items"][meter]
    return Decimal(str(usd)) / per


def tokens(text: str) -> int:
    return math.ceil(len(text) / PRICES["tokens"]["chars_per_token"])


def percentile(values: list[float], q: float) -> float:
    """Nearest rank: the smallest value with at least q of the values at or below it."""
    ordered = sorted(values)
    return ordered[max(0, math.ceil(q * len(ordered)) - 1)]


# ---------------------------------------------------------------- tokens from the recording


async def _tool_definitions() -> str:
    from ninety.mcp import match_server

    # Only the tools the published Analyst may call reach its context (Foundry's allowed_tools).
    tools = [t for t in await match_server.server.list_tools() if t.name in match_server.TOOLS]
    return json.dumps([{"name": t.name, "description": t.description, "parameters": t.inputSchema}
                       for t in tools])


def model_calls(recording) -> list[dict]:
    """Each recorded turn as the model calls it took, with the text each was sent and answered.

    The Analyst is a Foundry prompt agent with the match MCP tool: one call that asks for the
    minute's events (list_events), then one that answers with them in context. The Judge is one
    call with a response schema. The Judge's answer is recorded as its verdict, shorter than the
    statements it wrote, so its output is a lower bound."""
    from ninety.agents import judge as judge_module
    from ninety.agents.slice import INSTRUCTIONS
    from ninety.mcp import match_server

    tools = asyncio.run(_tool_definitions())
    schema = json.dumps(judge_module.Judgement.model_json_schema())
    known = {e["id"]: e for e in recording.events}
    match = match_server.match_id(recording.seed)
    args = json.dumps({"match": match, "minute_from": recording.minute, "minute_to": recording.minute,
                       "event_type": None})
    rows = [e for e in recording.events if e["minute"] == recording.minute][: match_server.MAX_EVENTS]
    result = json.dumps(rows)
    calls = []
    for n, turn in enumerate(recording.turns, 1):
        if turn.role == "analyst":
            first = INSTRUCTIONS + tools + turn.prompt
            calls.append({"turn": n, "role": "analyst", "call": "tool request",
                          "input": tokens(first), "output": tokens(args)})
            calls.append({"turn": n, "role": "analyst", "call": "answer",
                          "input": tokens(first + args + result), "output": tokens(turn.response)})
        else:
            claim = json.loads(turn.prompt)
            sent = json.dumps({"claim": claim["text"], "evidence": [known[i] for i in claim["evidence"]]},
                              separators=(",", ":"))
            calls.append({"turn": n, "role": "judge", "call": "verdict",
                          "input": tokens(judge_module.INSTRUCTIONS + schema + sent),
                          "output": tokens(turn.response)})
    return calls


# ---------------------------------------------------------------- latency


class _Spans:
    """Catches `ninety.stage` spans in memory while the chain runs."""

    def __enter__(self):
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import SimpleSpanProcessor
        from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

        self.exporter = InMemorySpanExporter()
        provider = TracerProvider()
        provider.add_span_processor(SimpleSpanProcessor(self.exporter))
        self.saved, telemetry.TRACER_PROVIDER = telemetry.TRACER_PROVIDER, provider
        return self

    def __exit__(self, *exc):
        telemetry.TRACER_PROVIDER = self.saved

    def take(self) -> dict[str, float]:
        """Milliseconds per stage since the last take."""
        per_stage: dict[str, float] = defaultdict(float)
        for span in self.exporter.get_finished_spans():
            if span.name == "ninety.stage":
                per_stage[span.attributes["ninety.stage"]] += (span.end_time - span.start_time) / 1e6
        self.exporter.clear()
        return {stage: per_stage.get(stage, 0.0) for stage in telemetry.STAGES}


def _quiet(fn):
    import logging

    logging.disable(logging.INFO)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            return fn()
    finally:
        logging.disable(logging.NOTSET)


def measure_latency(clip: Path, runs: int) -> dict:
    from ninety import e2e
    from ninety.agents.slice import Recording, replay_slice

    recording = Recording.load(RECORDING)
    scenarios: dict[str, list[dict[str, float]]] = {"e2e": [], "replay": []}
    with _Spans() as spans, tempfile.TemporaryDirectory() as tmp:
        # The single Analyst path: the committed timings and "What runs" describe it, not the graph.
        args = e2e.parser().parse_args([str(clip), "--out", str(Path(tmp) / "bundle"), "--frames",
                                        "--single-analyst"])
        for n in range(runs + 1):  # the first run warms imports and caches, and is not counted
            _quiet(lambda: asyncio.run(e2e.run(args)))
            stages = spans.take()
            _quiet(lambda: asyncio.run(replay_slice(recording)))
            replay = spans.take()
            if n:
                scenarios["e2e"].append(stages)
                scenarios["replay"].append(replay)
    return {
        "clip": clip.name,
        "runs": runs,
        "e2e": [{k: round(v, 3) for k, v in r.items()} for r in scenarios["e2e"]],
        "replay": [{k: round(v, 3) for k, v in r.items()} for r in scenarios["replay"]],
    }


def describe_clip(clip: Path) -> dict:
    """What the e2e run had to work with (from the bundle it writes)."""
    from ninety import e2e

    with tempfile.TemporaryDirectory() as tmp:
        args = e2e.parser().parse_args([str(clip), "--out", str(Path(tmp) / "b"), "--frames",
                                        "--single-analyst"])
        manifest = _quiet(lambda: asyncio.run(e2e.run(args)))
    return {"frames": manifest["detections"]["frames"], "events": manifest["events"]["count"],
            "events_source": manifest["events"]["source"], "facts": manifest["facts"],
            "claims": manifest["agents"]["claims"], "cues": manifest["cues"]}


def measure(clip: Path, runs: int) -> dict:
    from ninety.agents.slice import Recording

    recording = Recording.load(RECORDING)
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True,
                            cwd=ROOT).stdout.strip()
    accepted = [t for t in recording.turns if t.role == "analyst"][-1]
    return {
        "commit": commit,
        "machine": f"{platform.system()} {platform.machine()}, Python {platform.python_version()}",
        "measured": time.strftime("%Y-%m-%d"),
        "clip": describe_clip(clip),
        "latency": measure_latency(clip, runs),
        "recording": {"file": str(RECORDING.relative_to(ROOT)), "model": recording.model,
                      "recorded_at": recording.recorded_at, "minute": recording.minute,
                      "plant": recording.plant,
                      "spoken_claim": json.loads(accepted.response)["text"]},
        "calls": model_calls(recording),
        "graphics_text": graphics_text(),
        # The recording's agent definitions (ninety/agents/evidence.py), when it records them; an
        # older recording names its versions in `model` only.
        **({"agent_definitions": recording.agent_definitions} if recording.agent_definitions else {}),
    }


def recount(data: dict) -> dict:
    """The data with its token counts rebuilt from the recording and the code as they are now; the
    timings and the commit and date they were measured at are kept, and the recount's are added."""
    from ninety.agents.slice import Recording

    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True,
                            cwd=ROOT).stdout.strip()
    return {**data, "calls": model_calls(Recording.load(RECORDING)), "graphics_text": graphics_text(),
            "recounted": {"commit": commit, "date": time.strftime("%Y-%m-%d")}}


def graphics_text() -> dict:
    rows = [json.loads(line) for line in CUES.read_text().splitlines()]
    casual = [r for r in rows if r["persona"] == "casual"]
    return {"file": str(CUES.relative_to(ROOT)), "minutes": CUES_MINUTES, "cues": len(casual),
            "chars": sum(len(r["text"]) for r in casual)}


# ---------------------------------------------------------------- the report


def cost(calls: list[dict], input_meter: str = INPUT, output_meter: str = OUTPUT) -> Decimal:
    return sum(
        (c["input"] * price(input_meter) + c["output"] * price(output_meter) for c in calls),
        Decimal(0),
    )


def clean_claim(calls: list[dict]) -> list[dict]:
    """A claim accepted at its first draft: the first Analyst turn and the last Judge call."""
    first = min(c["turn"] for c in calls if c["role"] == "analyst")
    judge = max(c["turn"] for c in calls if c["role"] == "judge")
    return [c for c in calls if c["turn"] in (first, judge)]


def usd(x: Decimal) -> str:
    """Four places below a cent, three above, rounded half up (a price on the half rounds the way
    a reader expects, whatever its binary neighbours)."""
    places = Decimal("0.0001") if x < Decimal("0.01") else Decimal("0.001")
    return f"${Decimal(x).quantize(places, rounding=ROUND_HALF_UP)}"


def render(data: dict) -> str:
    lat, calls, rec = data["latency"], data["calls"], data["recording"]
    clip = data["clip"]
    p = PRICES
    out = [
        "# Latency and cost",
        "",
        "Generated by `uv run python -m ninety.eval.latency_cost` from `docs/eval/latency-cost.json`;",
        "do not edit by hand. `--measure <clip>` re-times the chain and re-counts the tokens; it calls",
        "no Azure service.",
        "",
        f"Measured {data['measured']} at commit `{data['commit']}` on {data['machine']}."
        + (f" Tokens re-counted {data['recounted']['date']} at commit `{data['recounted']['commit']}`."
           if "recounted" in data else ""),
        "",
        "## Latency, stage by stage",
        "",
        f"`ninety-e2e` offline on clip `{lat['clip']}` ({clip['frames']} frames, {clip['events']} "
        f"events: {clip['events_source']}; {clip['facts']} facts, {clip['claims']} claim, "
        f"{clip['cues']} cues), and the slice replay `{rec['file']}` ({rec['model']}), each "
        f"{lat['runs']} times after one warm-up run. Every stage is a `ninety.stage` OpenTelemetry span "
        "(`ninety/agents/telemetry.py`), the same spans the live app sends to Application Insights.",
        "",
        "| Stage | e2e p50 ms | e2e p95 ms | replay p50 ms | replay p95 ms | What runs |",
        "|---|---:|---:|---:|---:|---|",
    ]
    what = {
        "detect": "read the clip's recorded detections (RF-DETR itself is not run here)",
        "events": "load the detected events inside the clip's window",
        "stats": "stats engine facts, and the ledger the live path reads",
        "agents": "the Analyst: offline a deterministic writer, in replay the recorded answers",
        "fact_check": "code checks, confidence gate, Judge (offline: not run; replay: recorded)",
        "cue": "template cues, the insight cue, cues into the ledger",
    }
    for stage in telemetry.STAGES:
        e = [r[stage] for r in lat["e2e"]]
        r = [x[stage] for x in lat["replay"]]
        cells = [f"{percentile(e, 0.5):.2f}", f"{percentile(e, 0.95):.2f}"]
        cells += [f"{percentile(r, 0.5):.2f}", f"{percentile(r, 0.95):.2f}"] if any(r) else ["n/a", "n/a"]
        out.append(f"| {stage} | " + " | ".join(cells) + f" | {what[stage]} |")
    template = [sum(r[s] for s in ("detect", "events", "stats", "cue")) for r in lat["e2e"]]
    insight = [sum(r.values()) for r in lat["e2e"]]
    out += [
        "",
        "## Event to graphic on screen",
        "",
        "The e2e run handles the clip in one pass, so each total below is the chain's time from the",
        "clip's detections to its last cue: no event in the clip waits longer for it.",
        "",
        "| Graphic | p50 ms | p95 ms | Stages |",
        "|---|---:|---:|---|",
        f"| template (pass, shot, goal) | {percentile(template, 0.5):.1f} | {percentile(template, 0.95):.1f} "
        "| detect, events, stats, cue |",
        f"| verified insight | {percentile(insight, 0.5):.1f} | {percentile(insight, 0.95):.1f} | all six |",
        "",
        f"Against docs/PLAN.md (event to verified graphic p95 ≤ {TARGET_GRAPHIC_P95_S:g} s): the chain's own "
        f"share is {percentile(insight, 0.95) / 1000:.3f} s. Not in it yet, so the target is not yet shown:",
        "",
        "- RF-DETR's inference per frame (`--detect live`; the `detect` span times it when run);",
        "- the detector's wait for the frames that confirm an event (a pass is known when it arrives);",
        "- the Analyst's and the Judge's model time on Foundry, which a live run's `ninety.stage`",
        "  spans record in Application Insights.",
        "",
        f"Event to spoken description (p50 ≤ {TARGET_SPEECH_P50_S:g} s, p95 ≤ {TARGET_SPEECH_P95_S:g} s): "
        "not measured. It needs Azure Speech synthesis, which this report does not call.",
        "",
        "## Cost",
        "",
        f"Prices read {p['read']} from the {p['source']} (pay as you go, USD, `northcentralus`, where",
        "our Foundry and Speech resources are):",
        "",
        "| Meter | Price | Effective from |",
        "|---|---:|---|",
    ]
    for meter, (amount, per, since) in p["items"].items():
        out.append(f"| {meter} | ${amount:g} per {per:,} | {since} |")
    out += [
        "",
        f"Tokens are not in the recording, so they are counted from the text each call was sent and "
        f"answered, at {p['tokens']['chars_per_token']} characters a token ({p['tokens']['source']}).",
        "An Analyst turn is two model calls (the agent asks the match MCP tool for the minute's events,",
        "then answers with them in context); a Judge turn is one call. The Judge's recorded answer is its",
        "verdict, shorter than the statements it writes, so its output tokens are a lower bound.",
        "",
        f"Calls in `{rec['file']}` (minute {rec['minute']}, {'planted' if rec['plant'] else 'clean'}, "
        f"recorded {rec['recorded_at']}):",
        "",
        "| Turn | Agent | Call | Input tokens | Output tokens | Cost (global) |",
        "|---:|---|---|---:|---:|---:|",
    ]
    for c in calls:
        out.append(f"| {c['turn']} | {c['role']} | {c['call']} | {c['input']:,} | {c['output']:,} | "
                   f"{usd(cost([c]))} |")
    worst, best = cost(calls), cost(clean_claim(calls))
    worst_dz = cost(calls, INPUT_DZ, OUTPUT_DZ)
    spoken = len(rec["spoken_claim"])
    claim_speech = spoken * price(SPEECH)
    per_match = {
        "best": MATCH_MINUTES * (best + claim_speech),
        "worst": MATCH_MINUTES * (worst + claim_speech),
        "worst_dz": MATCH_MINUTES * (worst_dz + spoken * price(SPEECH_HD)),
    }
    left = {case: BUDGET_USD - per_match[case] for case in ("best", "worst")}
    out += [
        "",
        "| Per claim | Model | Speaking the claim | Total |",
        "|---|---:|---:|---:|",
        f"| accepted first time (first Analyst turn, last Judge call) | {usd(best)} | {usd(claim_speech)} "
        f"| {usd(best + claim_speech)} |",
        f"| as recorded (planted number: three drafts, two Judge calls) | {usd(worst)} | {usd(claim_speech)} "
        f"| {usd(worst + claim_speech)} |",
        "",
        f"Speaking the claim: the accepted claim's {spoken} characters at the S1 neural voice price.",
        f"A clip is one minute's claim: {usd(best + claim_speech)} to {usd(worst + claim_speech)} per clip.",
        "",
        f"| Per {MATCH_MINUTES}-minute match (one claim a minute) | Spend | Budget ${BUDGET_USD:.2f} |",
        "|---|---:|---|",
        f"| every claim accepted first time | {usd(per_match['best'])} | "
        f"{'within' if per_match['best'] <= BUDGET_USD else 'over'} |",
        f"| every claim takes three drafts, as recorded | {usd(per_match['worst'])} | "
        f"{'within' if per_match['worst'] <= BUDGET_USD else 'over'} |",
        f"| three drafts, Data Zone model prices, HD voice | {usd(per_match['worst_dz'])} | "
        f"{'within' if per_match['worst_dz'] <= BUDGET_USD else 'over'} |",
        "",
        "No prompt caching is assumed; the instructions and tool definitions repeat on every call, and",
        "cached input is a quarter of the price. Three drafts is the most a claim gets (two rewrites); the",
        "planted replay forces one, a draft the code checks reject never reaches the Judge, and",
        "docs/eval/analyst.md finds about half of first drafts would air.",
        "",
        "### Audio description",
        "",
        "The Describer's own lines (one per described event) are not in this count: it is not merged.",
        "What the budget leaves for them, in characters of the S1 neural voice:",
        "",
        "| After | Left | Characters a match | A minute |",
        "|---|---:|---:|---:|",
    ]
    for case, label in (("best", "every claim accepted first time"), ("worst", "every claim three drafts")):
        chars = max(left[case], 0) / price(SPEECH)
        out.append(f"| {label} | {usd(left[case])} | {chars:,.0f} | {chars / MATCH_MINUTES:,.0f} |")
    out += [
        "",
    ]
    g = data["graphics_text"]
    per_minute = g["chars"] / g["minutes"]
    out += [
        f"For scale: the casual persona's graphics in `{g['file']}` say {g['chars']:,} characters in "
        f"{g['minutes']} minutes ({g['cues']} cues), {per_minute:,.0f} a minute, and a spoken line is longer",
        "(\"Home 10\" for h10, units in full). Speaking every described event in the Azure voice fits only",
        "when the claims rarely need rewriting. The viewer's browser voice costs nothing; the Azure voice",
        "can be kept for shots, goals and verified claims.",
        "When the Describer lands, its `audio.json` gives the characters it says, and this report",
        "should count them.",
        "",
    ]
    return "\n".join(out)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Build docs/eval/latency-cost.md (latency and cost).")
    ap.add_argument("--measure", type=Path, metavar="CLIP", help="re-measure on this clip, then rebuild")
    ap.add_argument("--runs", type=int, default=30, help="timed runs per scenario with --measure")
    ap.add_argument("--recount", action="store_true", help="re-count the tokens, keep the timings, rebuild")
    ap.add_argument("--check", action="store_true", help="fail if the report is not what the data gives")
    args = ap.parse_args(argv)
    if args.measure:
        DATA.write_text(json.dumps(measure(args.measure, args.runs), indent=2) + "\n")
    elif args.recount:
        DATA.write_text(json.dumps(recount(json.loads(DATA.read_text())), indent=2) + "\n")
    text = render(json.loads(DATA.read_text()))
    if args.check:
        if REPORT.read_text() != text:
            sys.exit(f"{REPORT.name} is out of date: run python -m ninety.eval.latency_cost")
        return
    REPORT.write_text(text)
    print(f"wrote {REPORT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
