"""One command for the whole chain on one clip, writing a bundle the viewer opens.

    uv run ninety-e2e runs/test-frozen-cca498c/test/seed900001 --out runs/e2e/seed900001
    uv run ninety-e2e <clip> --out <bundle> --plant           # plant a false number: see a rejection
    npm run dev --prefix web/viewer                           # then open the bundle in the viewer

Stages (the brief's names), each writing one file in the bundle:

1. Ingest: detections. `--detections FILE` reads a detector run that was already made (the
   default is the committed ours-v2 run on the frozen test set, docs/eval/vision-report-v1);
   `--detect live --weights W` runs RF-DETR (ninety.vision.detect, needs `uv sync --group vision`).
2. Interpret: detected events (ninety/match/detected.py: source vision, with a confidence; ground
   truth is refused). `--events-file` names them; by default R3's file for the clip, or until it
   lands the hand-written stand-in, which the bundle and the viewer name as one. `--demo` refuses
   the stand-in. Only the events inside the clip's window go on.
3. Explain and 4. Render: the multi-agent graph (ninety/agents/workflow.py), once per minute:
   template cues for every confident pass and shot first, then the Analyst picks the moments, the
   Tactician explains each, the Challenger offers another reading, the fact-checking agent checks
   both (code checks, the confidence gate, the Judge) and sends a wrong claim back, and the
   Producer airs the verified one in place of its template. `--agents offline` (the default) stands
   deterministic writers in for the models, so the graph and the code checks are real and no Azure
   is needed; `--agents live` calls the published Foundry agents (a live, billed call). When the
   graph fails on a minute, that minute falls back to the single Analyst -> Fact-checker path
   (ninety/agents/live.py), and the trace and manifest say so. `--replay FILE` answers the single
   Analyst path from a slice recording.
5. Personalize: analyst and casual cues side by side; the viewer switches between them. The
   Describer (ninety/speech/describe.py) adds the audio description persona: a spoken line per
   confident event or verified claim, with its stereo position, as `audio` cues, audio.json and
   description.vtt. Offline its timing is estimated and the viewer speaks with the browser's voice;
   `--speech azure` synthesises each line through Azure AI Speech instead (off by default: a live
   Azure call, so run it only when agreed). `--voice-audio` adds the phone's read-aloud audio in
   the pinned voice (ninety/speech/bundle.py: speech.json and speech/), also a live call.

The radar beside the video: `--tracked FILE --observations FILE` (vision's tracked.json and
observations.jsonl for the clip, as ninety/vision/live_job.py writes them) add radar.json
(ninety/radar.py): every tracked player, the ball and the broadcast camera's footprint, from above.

Match mode, for a condensed match (one clip cut from passage to passage): `--match` adds match.json
(ninety/condensed.py): a chapter per segment named from the detected events, the scoreline from
detected goals, and each team's stats from the footage shown. With `--tracked` too, it adds
`territory` (ninety/match/territory.py): where vision's tracked ball was, per five minutes.

Hidden-stat cards for the phone: `--cards FILE` copies the Insight Scout's cards
(`python -m ninety.agents.scout`, schemas/insight_card.schema.json) into the bundle as cards.json.
Every card must be verified and match the schema, or the bundle is not written.

The bundle (manifest.json, cues.jsonl, trace.json, events.jsonl, facts.json, detections.jsonl,
radar.json and match.json when asked for, and the footage as video.webm or frames/) is all the
viewer reads. This module never opens the clip's events.jsonl or frames.jsonl: they are the answer
key (tests/test_e2e.py checks).
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import logging
import re
import shutil
import subprocess
import sys
import warnings
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass
from pathlib import Path

from ninety import condensed, highlights, radar
from ninety.agents import live, telemetry
from ninety.agents.contracts import Models, Review, schema_validator
from ninety.agents.cues import TEMPLATE_TYPES, _text
from ninety.agents.factcheck import MIN_CONFIDENCE, MIN_TEAM_CONFIDENCE, Claim, Verdict, side_known
from ninety.agents.slice import Recording, replayer, tamper
from ninety.intel.scoring import SCOREBUG_MEASURED
from ninety.intel.stats import calculate_facts
from ninety.match import detected, territory
from ninety.match.facts import AGENT_TYPES, compact, minute_of
from ninety.match.timeline import Timeline
from ninety.speech import describe

ROOT = Path(__file__).resolve().parents[1]
RECORDED_DETECTIONS = ROOT / "docs" / "eval" / "vision-report-v1" / "detections"
BUNDLE_FORMAT = 1

# What makes a moment worth the one sentence a minute gets, most first. A goal beats a shot beats a
# turnover beats a pass; among equals, the faster ball.
INTEREST = {"goal": 0, "shot": 1, "interception": 2, "tackle": 3, "pass": 4, "pressure": 5}


@dataclass(frozen=True)
class Clip:
    dir: Path
    meta: dict  # clip.json: id, seed, fps, window and render params; no labels

    @property
    def id(self) -> str:
        return self.meta["clip_id"]

    @property
    def images(self) -> list[Path]:
        return sorted((self.dir / "images").glob("*.jpg"))



def read_scorebug(path: Path) -> list[dict]:
    """The scorebug's readings for the phone (ninety/vision/scorebug.py, #356): its start readings
    (`score_read`) and each change of score (`score_change`, with its side), oldest first. Anything
    else, or a reading without a score, stops the bundle."""
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    for r in rows:
        if r.get("type") not in ("score_read", "score_change") or not isinstance(r.get("score"), dict):
            raise SystemExit(f"{path}: not a scorebug reading: {str(r)[:120]}")
        if r["type"] == "score_change" and r.get("team") not in ("home", "away"):
            raise SystemExit(f"{path}: a score_change names its side: {str(r)[:120]}")
    return sorted(rows, key=lambda r: r["t"])


def read_cards(path: Path) -> list[dict]:
    """The Scout's cards, oldest first, each checked against schemas/insight_card.schema.json. Only
    verified cards reach a fan (the schema says so too); anything else stops the bundle."""
    cards = json.loads(path.read_text())
    if not isinstance(cards, list):
        raise SystemExit(f"{path}: cards.json is a list of cards")
    validate = schema_validator("insight_card")
    for card in cards:
        validate.validate(card)
    return sorted(cards, key=lambda c: c["t"])


def read_team_stats(path: Path) -> dict:
    """The MatchInsights bundle's `team_stats` (insight-scout, #269): each team's tracked distance
    with how much of its players' time was tracked. Only measured rows go on: a team's km must come
    with its coverage (a share, 0 to 1); possession only if the insights wrote it (its gate passed)."""
    body = json.loads(path.read_text())
    stats = body.get("team_stats", body)
    out: dict = {"from_footage": bool(stats.get("from_footage", True)), "bin_min": stats.get("bin_min")}
    within = stats.get("within_pct")  # how close the distance is measured (calibrated, #300)
    if within is not None:
        if not isinstance(within, int) or not 0 < within <= 100:
            raise SystemExit(f"{path}: team_stats.within_pct is a whole percentage from 1 to 100")
        out["within_pct"] = within
    distance = stats.get("distance") or {}
    for side in ("home", "away"):
        d = distance.get(side)
        if d is None:
            raise SystemExit(f"{path}: team_stats.distance has no {side}")
        km, coverage = d.get("km"), d.get("coverage")
        sound_km = isinstance(km, (int, float)) and km >= 0
        if not sound_km or not isinstance(coverage, (int, float)) or not 0 <= coverage <= 1:
            raise SystemExit(f"{path}: team_stats.distance.{side} needs km >= 0 and a coverage from 0 to 1")
    out["distance"] = {side: {"km": distance[side]["km"], "coverage": distance[side]["coverage"]}
                       for side in ("home", "away")}
    if "possession" in stats:
        out["possession"] = {side: {"share": stats["possession"][side]["share"]} for side in ("home", "away")}
    return out


def read_lineup(path: Path) -> list[dict] | None:
    """MatchInsights' team sheet (the line-up tool, insight-scout): per player id a name, shirt and
    position, with whether the tool is confident of it. The phone shows only confident entries. A
    row without an id, or with a name, shirt or position of the wrong type, stops the bundle."""
    rows = json.loads(path.read_text()).get("lineup")
    if rows is None:
        return None
    kinds = {"name": str, "number": int, "position": str, "confident": bool}
    out = []
    for r in rows:
        wrong = [k for k, t in kinds.items() if k in r and not isinstance(r[k], t)]
        if not isinstance(r.get("id"), str) or wrong:
            raise SystemExit(f"{path}: a lineup row needs a string id; wrong types: {wrong}")
        out.append({k: r[k] for k in ("id", *kinds) if k in r})
    return out


GROUPS = ("Attack", "Passing", "Pressing", "Shape", "Physical")


def read_stats(path: Path) -> dict | None:
    """MatchInsights' `stats` block (insight-scout, #269): per-team rows by group, each a series of
    values "so far" to a minute, with whether the value is confident. A row missing its group, key,
    label or series stops the bundle; the block is optional."""
    body = json.loads(path.read_text())
    block = body.get("stats")
    if block is None:
        return None
    rows = []
    for row in block.get("rows", []):
        if row.get("group") not in GROUPS or not row.get("key") or not row.get("label"):
            raise SystemExit(f"{path}: a stats row needs a group in {GROUPS}, a key and a label")
        series = []
        for v in row.get("series", []):
            if not isinstance(v.get("minute_to"), (int, float)) or not isinstance(v.get("confident"), bool):
                raise SystemExit(f"{path}: stats.{row['key']}: each value needs minute_to and confident")
            keep = ("minute_to", "home", "away", "confident", "evidence", "coverage")
            series.append({k: v[k] for k in keep if k in v})
        rows.append({"group": row["group"], "key": row["key"], "label": row["label"],
                     "unit": row.get("unit"), "series": sorted(series, key=lambda v: v["minute_to"])})
    return {"bin_min": block.get("bin_min"), "from_footage": bool(block.get("from_footage", True)),
            "rows": rows}


def teams_of(meta: dict) -> dict | None:
    """The home and away codes the clip was rendered with, or None for a clip without them."""
    params = meta.get("params", {})
    home, away = params.get("home_code"), params.get("away_code")
    return {"home": home, "away": away} if home and away else None

def clubs_of(meta: dict) -> dict[str, str] | None:
    """The sides as the Describer says them ({"home": "London", ...}): the short names of the clubs
    the clip was rendered with (ninety/intel/teamsheet.py), or None for a clip without known codes."""
    from ninety.intel import teamsheet

    teams = teams_of(meta)
    try:
        return {side: teamsheet.short_name(code) for side, code in teams.items()} if teams else None
    except ValueError:  # a code no team sheet knows: the sides are said as "home" and "away"
        return None


PEOPLE = ("player", "receiver", "intended", "interceptor", "deflected_by")


def sides_known(events: list[dict]) -> list[str]:
    """The track ids whose side the screens may name: each one the actor of a detected event whose
    side was told surely (factcheck.side_known), and named in no event that was not. A track id's
    letter is the tracker's side vote, so a screen reading it as a club would name a side the gate
    holds; the viewer and the phone say "a player" for every track id not listed here (fail
    closed: a receiver or an interceptor is someone else, whose side that event did not measure)."""
    actors = {e["player"] for e in events if e.get("player")}
    # Anyone named where that event did not vouch for his side: its actor when the side was unsure,
    # and everyone else it names (a receiver, an interceptor) whatever it said of the actor's side.
    doubted = {e[k] for e in events for k in PEOPLE
               if e.get(k) and (k != "player" or not side_known(e))}
    return sorted(i for i in actors - doubted if "-t" in i)


def load_clip(clip_dir: Path) -> Clip:
    meta = json.loads((clip_dir / "clip.json").read_text())
    return Clip(clip_dir, meta)


# ---------------------------------------------------------------- 1 Ingest: detections


def detections_for(clip: Clip, path: Path | None, live: bool, weights: Path | None, out: Path) -> Path:
    """Where the clip's detections are: a recorded run, or a live RF-DETR run written to `out`."""
    if live:
        if weights is None:
            raise SystemExit("--detect live needs --weights (our fine-tuned checkpoint)")
        cmd = [sys.executable, "-m", "ninety.vision.detect", str(clip.dir), "--checkpoint", "ours-v2",
               "--weights", str(weights), "--out", str(out)]
        subprocess.run(cmd, check=True)
        return out
    path = path or RECORDED_DETECTIONS / f"{clip.id}.jsonl"
    if not path.exists():
        raise SystemExit(f"no detections at {path}: pass --detections FILE, or --detect live")
    return path


# ---------------------------------------------------------------- 2 Interpret: detected events


def detected_events(clip: Clip, path: Path | None, demo: bool) -> tuple[list[dict], str]:
    """The clip's detected events inside its window, and where they came from."""
    path = path or detected.m1_path(clip.id)
    if not path.exists():
        raise SystemExit(f"no detected events at {path}: pass --events-file")
    if demo and detected.is_standin(path):
        raise SystemExit(f"--demo refuses {path.name}: a hand-written stand-in, not the detector's output")
    t0, t1 = clip.meta["t_start"], clip.meta["t_end"]
    events = [e for e in detected.load(path) if t0 <= e["t"] <= t1]
    label = f"hand-written stand-in ({path.name}), not the detector's output" if detected.is_standin(path) \
        else f"detected ({path.name})"
    return events, label


# ---------------------------------------------------------------- 3 Explain and 4 Render: the live path


def most_interesting(events: list[dict]) -> dict | None:
    """The one event a minute's sentence is about (INTEREST), or None in a quiet minute."""
    ranked = [e for e in events if e["type"] in INTEREST and e.get("player")]
    if not ranked:
        return None
    speed = lambda e: e.get("ball_speed_kmh") or 0  # noqa: E731
    return min(ranked, key=lambda e: (INTEREST[e["type"]], -speed(e), e["second"], e["id"]))


def offline_analyst(events: list[dict], plant: bool):
    """A deterministic Analyst with the published one's reply format, written from the same events.
    It stands in for the model when there is no Azure: the workflow and the code checks are real.
    With `plant`, its first draft carries a false number (slice.tamper) for the checker to catch."""
    by_minute: dict[int, list[dict]] = {}
    for event in events:
        by_minute.setdefault(event["minute"], []).append(event)
    calls = 0

    async def ask(prompt: str) -> str:
        nonlocal calls
        calls += 1
        minute = int(prompt.split("minute ")[1].split(".")[0])
        event = most_interesting(by_minute.get(minute, []))
        if event is None:
            return json.dumps({"text": "", "evidence": []})
        claim = Claim(describe.as_sentence(_text(event, "analyst") + "."), [event["id"]])
        if plant and calls == 1:
            claim = tamper(claim)
        return json.dumps({"text": claim.text, "evidence": claim.evidence})

    return ask


async def judge_not_run(claim: Claim, evidence: list[dict]) -> Verdict:
    """Offline there is no Judge model: the code checks alone decide, and the trace says so."""
    return Verdict(ok=True, reasons=[])


TOOK = re.compile(r" \((?:(?P<s>[0-9.]+)s|replayed)\)$")


def trace_step(line: str, moment: str, judged: bool) -> dict:
    """One workflow trace line as an agent_trace step (schemas/agent_trace.schema.json):
    {role, moment, action, ms, detail}. Offline, the Judge is named as not run."""
    role, _, detail = line.partition(": ")
    took = TOOK.search(detail)
    ms = round(float(took["s"]) * 1000, 1) if took and took["s"] else 0.0
    detail = TOOK.sub("", detail)
    if role == "analyst":
        action = "tamper" if detail.startswith("draft tampered") else "draft"
    elif role == "judge":
        action = "verify" if detail.startswith("supported") else "reject"
        if not judged:
            action, detail = "skip", "not run offline: the code checks alone decided"
    elif detail.startswith("rejected, out of rewrites: "):
        action, detail = "hold", detail.removeprefix("rejected, out of rewrites: ")
    elif detail.startswith("rejected: "):
        action, detail = "reject", detail.removeprefix("rejected: ")
    else:
        action = "verify"
    return {"role": role, "moment": moment, "action": action, "ms": ms, "detail": detail}


async def explain_and_render(
    events: list[dict], clip: str, plant: bool, recording: Recording | None,
    only: list[int] | None = None, models: tuple | None = None,
) -> tuple[list[dict], list[dict], list[str]]:
    """live.run once per minute the clip covers: its cues (merged by id), one claim trace per
    minute that had something to say, and the detections too unsure to air."""
    agent_events = [compact(e) for e in events if e["type"] in AGENT_TYPES]
    cues: dict[str, dict] = {}
    claims: list[dict] = []
    held: set[str] = set()
    minutes = sorted({minute_of(e) for e in events}) or [None]
    for minute in (only if only is not None else minutes):
        if minute is None or (recording is None and most_interesting(
                [e for e in agent_events if e["minute"] == minute]) is None):
            ask = judge = None  # a quiet minute: template cues only
        elif recording is not None:
            ask, judge = replayer(recording.turns)
        elif models is not None:  # the published single Analyst and Judge (--agents live fallback)
            ask, judge = models
        else:
            ask, judge = offline_analyst(agent_events, plant), judge_not_run
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            result = await live.run(events, clip, ask, judge, minute if ask else None,
                                    inline_events=models is not None)
        cues.update({c["id"]: c for c in result.cues})
        held.update(result.held_detections)
        outcome = result.outcome
        if outcome is None:
            continue
        times = {e["id"]: e["t"] for e in events}
        moment = f"claim-m{minute}"
        claims.append(
            {
                "id": moment,
                "minute": minute,
                "t": max((times[i] for i in outcome.claim.evidence if i in times), default=None),
                "status": "accepted" if outcome.accepted else "held_back",
                "verdict": outcome.status,
                "drafts": outcome.attempts,
                "planted": plant and recording is None and models is None,
                "mode": "replay" if recording is not None else "live" if models is not None else "offline",
                "text": outcome.claim.text,
                "evidence": outcome.claim.evidence,
                # A Judge answered when the run replayed one or called the published one (--agents
                # live's fallback); only the offline stand-in has none to show.
                "steps": [trace_step(line, moment, recording is not None or models is not None)
                          for line in outcome.trace],
            }
        )
    return sorted(cues.values(), key=lambda c: (c["t_in"], c["id"])), claims, sorted(held)


# ---------------------------------------------------------------- the multi-agent graph


def on_air(events: list[dict]) -> list[dict]:
    """The events confident enough to have a graphic on air (the confidence gate's line): the only
    ones the workflow lets a moment be about."""
    return [e for e in events if e.get("confidence") is None or e["confidence"] >= MIN_CONFIDENCE]


def offline_models(events: list[dict]) -> Models:
    """Deterministic stand-ins for the graph's writers, with the published agents' reply formats:
    the Analyst picks the minute's most interesting pass, shot or goal, the Tactician states it
    from the event's own fields, and the Challenger agrees. Offline there is no Judge: the code
    checks and the confidence gate decide. (The workflow itself plants a false number, `plant`.)"""
    by_id = {e["id"]: e for e in events}
    by_minute: dict[int, list[dict]] = {}
    for event in events:
        by_minute.setdefault(event["minute"], []).append(event)

    async def analyst(prompt: str) -> str:
        minute = int(prompt.split("minute ")[1].split(".")[0])
        graphics = [e for e in by_minute.get(minute, []) if e["type"] in TEMPLATE_TYPES]
        event = most_interesting(on_air(graphics))
        picks = [] if event is None else [{"main_event": event["id"], "evidence": [event["id"]]}]
        return json.dumps({"moments": picks})

    async def tactician(prompt: str) -> str:
        # A sentence, as a co-commentator would say it, from the event's own fields; not the graphic's
        # compact form ("h11 → h8, 17 m, 53 km/h"), which the template already shows.
        event = by_id[json.loads(prompt)["moment"]["main_event"]]
        text = describe.as_sentence(_text(event, "analyst") + ".")
        return json.dumps({"text": text, "evidence": [event["id"]]})

    async def challenger(prompt: str) -> str:
        return json.dumps({"agree": True})

    return Models.scripted({}, analyst=analyst, tactician=tactician, challenger=challenger,
                           judge=judge_not_run)


def review_trace(review: Review, result, minute: int, times: dict[str, float], plant: bool,
                 mode: str) -> dict:
    """One moment of the graph as the viewer's claim trace: the claim that aired (else the
    Tactician's last), whose it was, every writer's drafts, and the steps for that moment."""
    claim = review.aired or review.drafted
    main = review.moment_id.removeprefix("m-")
    steps = [{k: v for k, v in asdict(s).items() if k != "fallback" or v}
             for s in result.trace if s.moment == review.moment_id]
    if mode == "graph offline":
        steps = [s if s["role"] != "judge" else {**s, "action": "skip",
                 "detail": "not run offline: the code checks alone decided"} for s in steps]
    return {
        "id": review.moment_id,
        "minute": minute,
        "t": times.get(main),
        "status": "accepted" if review.aired else "held_back",
        "verdict": review.status,
        "drafts": sum(n for _, n in review.attempts) or 1,
        "author": review.author,
        "attempts": dict(review.attempts),
        "planted": plant,
        "mode": mode,
        "text": claim.text if claim else "",
        "evidence": list(claim.evidence) if claim else [],
        "steps": steps,
    }


async def explain_with_graph(
    events: list[dict], clip: str, plant: bool,
    run_minute: Callable[[int, bool], Awaitable] | None = None,
    single: Callable[[int, bool], Awaitable[tuple[list[dict], list[dict]]]] | None = None,
    mode: str = "graph offline", perceiver=None,
) -> tuple[list[dict], list[dict], list[str], list[dict], list[dict]]:
    """The graph once per minute with a pass, shot or goal to explain. Returns the cues (templates,
    each minute's insights and the templates it badged), the claim traces, the detections too
    unsure to air, each minute the graph failed on, and each minute whose Analyst picked nothing that
    stood (with why). A failed minute runs `single` instead: the
    single Analyst -> Fact-checker path (offline by default), and its trace says so.

    `run_minute(minute, plant)` runs the graph for one minute (default: offline writers);
    `plant` is true only for the first minute explained."""
    from ninety.agents import workflow

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        base = await live.run(events, clip)  # the template cues, and what was too unsure to air
    templates = {c["id"]: c for c in base.cues}
    cues = dict(templates)
    agent_events = [compact(e) for e in events if e["type"] in AGENT_TYPES]
    times = {e["id"]: e["t"] for e in events}

    async def offline_minute(minute: int, planted: bool):
        return await workflow.run_workflow(offline_models(agent_events), events, minute, clip,
                                           plant=planted, inline_events=True, perceiver=perceiver)

    async def offline_single(minute: int, planted: bool) -> tuple[list[dict], list[dict]]:
        new, traced, _ = await explain_and_render(events, clip, planted, None, [minute])
        return new, traced

    run_minute, single = run_minute or offline_minute, single or offline_single
    claims: list[dict] = []
    fallbacks: list[dict] = []
    minute_notes: list[dict] = []
    busy = [m for m in sorted({minute_of(e) for e in events}) if most_interesting(on_air(
        [e for e in agent_events if e["minute"] == m and e["type"] in TEMPLATE_TYPES])) is not None]
    for minute in busy:
        planted = plant and minute == busy[0]
        try:
            with telemetry.stage_span("agents", minute=minute, path="graph"):
                result = await run_minute(minute, planted)
        except Exception as e:  # noqa: BLE001  the graph failed: this minute runs the single Analyst
            why = type(e).__name__  # the type only: no endpoint, token or service text on screen
            fallbacks.append({"minute": minute, "error": why})
            new, traced = await single(minute, planted)
            cues.update({c["id"]: c for c in new if c.get("kind") == "insight"})
            claims += [{**c, "mode": f"fallback: single analyst ({why})"} for c in traced]
            continue
        for cue in result.cues:  # its insights, and the templates it badged (held, rejected)
            if cue.get("kind") == "insight" or cue != templates.get(cue["id"]):
                cues[cue["id"]] = cue
        tampered = any(s.action == "tamper" for s in result.trace)
        claims += [review_trace(r, result, minute, times, tampered, mode) for r in result.reviews]
        # What the Analyst did that belongs to no moment (a pick it dropped, a failed call).
        notes = [f"{s.role} {s.action}: {s.detail}" for s in result.trace if s.moment == "-"
                 and s.role == "analyst"]
        if notes or not result.reviews:
            minute_notes.append({"minute": minute, "moments": len(result.reviews), "notes": notes})
    ordered = sorted(cues.values(), key=lambda c: (c["t_in"], c["id"]))
    return ordered, claims, sorted(base.held_detections), fallbacks, minute_notes


@contextlib.asynccontextmanager
async def published_single(credential, turns: list[dict], pins: dict[str, str]):
    """The published single Analyst and Judge (the slice's agents), as live.run's ask and judge:
    the graph's fallback with --agents live. The minute's events go in the prompt; a call to the
    match tools fails the call. Their answers go to `turns`, their versions to `pins`."""
    from agent_framework.foundry import FoundryAgent

    from ninety import config
    from ninety.agents import foundry
    from ninety.agents.judge import judge as judge_call

    client = foundry.chat_client(credential)
    async with contextlib.AsyncExitStack() as stack:
        agents = []
        for local in foundry.slice_agents(client):
            name, version = foundry.pinned(local)  # refuses a definition that drifted from its pin
            pins[name] = version
            agents.append(await stack.enter_async_context(FoundryAgent(
                project_endpoint=config.FOUNDRY_PROJECT, agent_name=name, agent_version=version,
                credential=credential)))
        analyst, judge_agent = agents

        async def ask(prompt: str) -> str:
            response = foundry.inline_only(await analyst.run(prompt))
            turns.append({"minute": None, "role": "analyst", "prompt": prompt, "response": response})
            return response

        async def judge(claim: Claim, evidence: list[dict]) -> Verdict:
            verdict = await judge_call(judge_agent, claim, evidence)
            turns.append({"minute": None, "role": "judge", "prompt": claim.text,
                          "response": json.dumps(asdict(verdict))})
            return verdict

        yield ask, judge


async def explain_live(events: list[dict], clip: str, plant: bool, log: dict, perceiver=None):
    """The graph on the published Foundry agents (a live, billed call), one sign-in for the whole
    clip; the published single Analyst for any minute the graph fails on. `log` gets the versions
    that ran, every model answer, and the minutes in which a model call failed (the graph then holds
    that minute's claims and the templates stay; it does not raise)."""
    from ninety.agents import workflow
    from ninety.agents.credentials import new_credential, sign_in
    from ninety.mcp import match_server

    turns: list[dict] = []
    pins: dict[str, str] = {}
    failed: list[int] = []
    # An id no server serves (lesson 90): a stray tool call can never read another match's events.
    match = match_server.unserved(clip)
    async with new_credential() as credential:
        await sign_in(credential)

        async def run_minute(minute: int, planted: bool):
            result, said, ran, model_failed, _ = await workflow.run_live(
                lambda: events, minute, match, True, planted, trace_to="none", credential=credential,
                perceiver=perceiver)
            turns.extend({"minute": minute, **asdict(t)} for t in said)
            pins.update(ran)
            if model_failed:
                failed.append(minute)
            return result

        async with published_single(credential, turns, pins) as models:
            async def single(minute: int, planted: bool):
                before = len(turns)
                try:
                    new, traced, _ = await explain_and_render(events, clip, False, None, [minute], models)
                except Exception as e:  # noqa: BLE001  both paths failed: the templates stay
                    return [], [{"id": f"claim-m{minute}", "minute": minute, "t": None,
                                 "status": "held_back", "verdict": "held", "drafts": 0,
                                 "planted": False, "mode": "live", "text": "", "evidence": [],
                                 "steps": [{"role": "analyst", "moment": f"claim-m{minute}",
                                            "action": "fail", "ms": 0.0,
                                            "detail": f"{type(e).__name__}; templates stay"}]}]
                finally:
                    for turn in turns[before:]:  # the fallback's answers belong to this minute
                        turn["minute"] = minute
                return new, traced

            out = await explain_with_graph(events, clip, plant, run_minute, single, mode="graph live",
                                           perceiver=perceiver)
    log.update({"pins": pins, "model_answers": len(turns), "model_failures": failed})
    log["turns"] = turns
    return out


def load_views(views: Path):
    """A Perceiver over vision's per-camera observations (ninety/vision/live_job.py writes
    `views/<name>/observations.jsonl`): what active perception looks again through."""
    from ninety.agents.perceive import Perceiver

    rows = {}
    for path in sorted(views.glob("*/observations.jsonl")):
        rows[path.parent.name] = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    if not rows:
        raise SystemExit(f"{views}: no <camera>/observations.jsonl to look again through")
    return Perceiver(rows)


# ---------------------------------------------------------------- footage


def write_footage(clip: Clip, out: Path, encode: bool) -> dict:
    """The clip as video.webm (VP9: plays in every browser, Playwright's Chromium included) when
    ffmpeg is there, else the JPEG frames themselves. The viewer plays either."""
    images = clip.images
    if not images:
        raise SystemExit(f"{clip.dir}/images has no frames")
    fps = clip.meta["fps"]
    if encode and shutil.which("ffmpeg"):
        video = out / "video.webm"
        cmd = ["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(fps), "-i",
               str(clip.dir / "images" / "%05d.jpg"), "-c:v", "libvpx-vp9", "-b:v", "0", "-crf", "32",
               "-deadline", "realtime", "-cpu-used", "8", "-row-mt", "1", "-pix_fmt", "yuv420p", str(video)]
        subprocess.run(cmd, check=True)
        return {"kind": "video", "src": video.name, "frames": len(images)}
    frames = out / "frames"
    frames.mkdir(exist_ok=True)
    for image in images:
        shutil.copyfile(image, frames / image.name)
    return {"kind": "frames", "src": "frames/", "pattern": "%05d.jpg", "frames": len(images)}


# ---------------------------------------------------------------- the bundle


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(r, sort_keys=True, separators=(",", ":")) + "\n" for r in rows))


async def run(args: argparse.Namespace) -> dict:
    clip = load_clip(args.clip)
    out: Path = args.out
    out.mkdir(parents=True, exist_ok=True)

    from ninety.vision.detections import read_detections

    with telemetry.stage_span("detect", source=args.detect, frames=len(clip.images)):
        det_path = detections_for(clip, args.detections, args.detect == "live", args.weights,
                                  out / "detections.jsonl")
        detections = read_detections(det_path)
    if det_path != out / "detections.jsonl":
        shutil.copyfile(det_path, out / "detections.jsonl")

    with telemetry.stage_span("events"):
        events, events_source = detected_events(clip, args.events_file, args.demo)
    with telemetry.stage_span("stats", events=len(events)):
        facts = [f.as_dict() for f in calculate_facts(events)]
    recording = Recording.load(args.replay) if args.replay else None
    perceiver = load_views(args.views) if args.views else None
    fallbacks: list[dict] = []
    notes: list[dict] = []
    agents_log: dict = {}
    if recording is not None or args.single_analyst:
        cues, claims, held = await explain_and_render(events, clip.id, args.plant, recording)
        agents_mode = "replay" if recording else "single analyst offline"
    elif args.agents == "live":
        cues, claims, held, fallbacks, notes = await explain_live(events, clip.id, args.plant, agents_log,
                                                                  perceiver)
        agents_mode = "graph live"
        # Every model answer, for audit: what the published agents said, minute by minute.
        (out / "agents.json").write_text(json.dumps(agents_log.pop("turns"), indent=2) + "\n")
    else:
        cues, claims, held, fallbacks, notes = await explain_with_graph(events, clip.id, args.plant,
                                                                        perceiver=perceiver)
        agents_mode = "graph offline"
    upgrades, model_calls, tokens, unavailable = None, [], {}, None
    if args.describer == "foundry":
        from ninety.agents import describer  # Foundry and the agent framework: only behind the flag
        from ninety.agents.foundry import RegistryDrift

        try:
            async with describer.foundry_model(tokens) as (model, judge):
                upgrades, model_calls = await describer.upgrades(events, cues, model, judge)
        except RegistryDrift:
            raise  # a changed prompt must never run under an old version's name
        except Exception as e:  # noqa: BLE001  sign-in or outage: the code lines still air
            upgrades, unavailable = None, type(e).__name__  # the type only: no endpoint or token
    voice = describe.Voice() if args.speech == "azure" else None
    track, refused = describe.describe(events, cues, voice or describe.estimate, upgrades,
                                       clubs=clubs_of(clip.meta))
    if voice is not None:
        voice.save(track, out)
    # The commentary track (ninety/speech/commentary.py): a commentator's calls from the same checked
    # output, for the phone's commentary toggle.
    from ninety.speech import commentary

    commentary_info = commentary.write(
        commentary.commentary(events, cues, clubs_of(clip.meta), Timeline.of_clip(clip.meta)), out)
    cues = sorted(cues + describe.audio_cues(track), key=lambda c: (c["t_in"], c["id"]))
    # The picture may cut from a dead ball to its restart: lines are placed on the clip's timeline.
    timeline = Timeline.of_clip(clip.meta)
    audio = describe.write_track(track, refused, out, clip.meta["t_start"], timeline=timeline)
    audio["describer"] = {"mode": args.describer, "calls": model_calls, "tokens": tokens,
                          "unavailable": unavailable}
    footage = write_footage(clip, out, encode=not args.frames)
    width, height = clip.meta["params"]["width"], clip.meta["params"]["height"]
    radar_info = None
    radar_body = None
    if args.tracked:
        body = radar_body = radar.write(args.tracked, args.observations, width, height, out / "radar.json")
        radar_info = {"source": body["source"], "frames": len(body["frames"]),
                      "footprints": sum(v["footprint"] is not None for v in body["views"])}

    write_jsonl(out / "events.jsonl", events)
    match_info = None
    if args.match:
        verdict = None
        if args.highlights_verdict:
            verdict = highlights.verdict_from_report(json.loads(args.highlights_verdict.read_text()))
        body = condensed.build(clip.meta, events, verdict)
        if radar_body is not None:
            # Where the ball was per five minutes, from vision's tracked ball (the phone's strip).
            body["territory"] = territory.build(radar_body, clip.meta["fps"])
        if args.team_stats:
            body["team_stats"] = read_team_stats(args.team_stats)  # measured per-team facts (#269)
            stats = read_stats(args.team_stats)
            if stats is not None:
                body["insight_stats"] = stats  # match.json's own `stats` is the detected events' series
            lineup = read_lineup(args.team_stats)
            if lineup is not None:
                body["lineup"] = lineup
        body["highlights"]["captioner"] = await caption_reel(body["highlights"], condensed.confident(events),
                                                             args.captioner)
        # Each moment recorded from the footage: a still and, unless --frames, its clip.
        highlights.record(body["highlights"], Timeline.of_clip(clip.meta), clip.images, out, not args.frames)
        (out / "match.json").write_text(json.dumps(body, indent=1) + "\n")
        match_info = {"chapters": len(body["chapters"]), "goals": len(body["goals"]),
                      "min_confidence": body["min_confidence"],
                      "highlights": len(body["highlights"]["moments"])}
    scorebug_info = None
    if args.scorebug:
        readings = read_scorebug(args.scorebug)
        write_jsonl(out / "scorebug.jsonl", readings)
        # One gate for every screen: the phone shows the scorebug's score only once the reader is
        # measured (scoring.SCOREBUG_MEASURED, as the Companion), and only readings at or above the
        # fact-checker's event confidence.
        scorebug_info = {"readings": len(readings), "measured": SCOREBUG_MEASURED,
                         "min_confidence": MIN_CONFIDENCE}
    cards_info = None
    if args.cards:
        cards = read_cards(args.cards)
        (out / "cards.json").write_text(json.dumps(cards, indent=1) + "\n")
        cards_info = {"count": len(cards)}
    write_jsonl(out / "cues.jsonl", cues)
    (out / "facts.json").write_text(json.dumps(facts, indent=2) + "\n")
    (out / "trace.json").write_text(json.dumps({"claims": claims}, indent=2) + "\n")
    model = detections[0].model if detections else None
    manifest = {
        "format": BUNDLE_FORMAT,
        "clip": clip.id,
        "fps": clip.meta["fps"],
        "width": width,
        "height": height,
        "t_start": clip.meta["t_start"],
        # Which match frame each image shows, across the broadcast's cuts (ninety/match/timeline.py).
        "segments": [s.as_dict() for s in timeline.segs],
        # The clubs' fictional codes the scorebug draws (ninety/render/params.py, TEAM_CODES); the
        # viewer and the phone name the clubs from them (web/viewer/src/teams.ts).
        "teams": teams_of(clip.meta),
        # The track ids a screen may name by club (`sides_known`); every other one is "a player".
        "sides_known": sides_known(events),
        "min_team_confidence": MIN_TEAM_CONFIDENCE,  # the phone names an event's side only above it
        "footage": footage,
        "detector": None if model is None else f"{model.name} {model.size} {model.checkpoint}",
        "detections": {"source": "live" if args.detect == "live" else "recorded", "frames": len(detections)},
        "events": {"source": events_source, "count": len(events), "standin": "stand-in" in events_source,
                   "held": held},
        "facts": len(facts),
        "agents": {"mode": agents_mode,
                   "planted": any(c["planted"] for c in claims) if not recording else False,
                   "claims": len(claims), "accepted": sum(c["status"] == "accepted" for c in claims),
                   "fallbacks": fallbacks, "minutes_without_a_moment": notes,
                   "re_perceived": [look.as_dict() for look in perceiver.looks] if perceiver else None,
                   **agents_log},
        "cues": len(cues),
        "audio": audio,
        "radar": radar_info,
        "match": match_info,
        "cards": cards_info,
        "scorebug": scorebug_info,
        "commentary": commentary_info,
        "files": ["detections.jsonl", "events.jsonl", "facts.json", "trace.json", "cues.jsonl", "audio.json",
                  "description.vtt", "commentary.json"] + (["radar.json"] if radar_info else [])
                 + (["agents.json"] if agents_mode == "graph live" else [])
                 + (["match.json"] if match_info else [])
                 + (["cards.json"] if cards_info else [])
                 + (["scorebug.jsonl"] if scorebug_info else []),
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    if args.voice_audio:
        # Last, so it reads every line the bundle holds (audio.json, and cards.json when present).
        from ninety.speech import bundle as speech_bundle

        manifest = speech_bundle.add_to_manifest(out, speech_bundle.write(out))
    return manifest



async def caption_reel(reel: dict, events: list[dict], mode: str) -> dict:
    """Each highlight's caption (ninety/agents/captioner.py): code-written, or with `foundry` the
    published Captioner's line where the fact-checker passes it. Returns the run's record."""
    from ninety.agents import captioner

    tokens, unavailable, results = {}, None, None
    if mode == "foundry":
        from ninety.agents.foundry import RegistryDrift  # the agent framework: only behind the flag

        try:
            async with captioner.foundry_model(tokens) as (model, judge):
                results = await captioner.captions(reel["moments"], events, model, judge)
        except RegistryDrift:
            raise  # a changed or unpublished prompt never runs under an old name
        except Exception as e:  # noqa: BLE001  sign-in or outage: the code captions still air
            unavailable = type(e).__name__  # the type only: no endpoint or token
    if results is None:
        results = await captioner.captions(reel["moments"], events, None, None)
    captioner.apply(reel, results)
    return {"mode": mode, "calls": [{"event": r["event"], **r["call"]} for r in results if "call" in r],
            "tokens": tokens, "unavailable": unavailable}

def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Run the chain on one clip and write a bundle for the viewer.")
    ap.add_argument("clip", type=Path, help="a rendered clip directory (clip.json and images/)")
    ap.add_argument("--out", type=Path, required=True, help="the bundle directory")
    ap.add_argument("--detect", choices=("recorded", "live"), default="recorded")
    ap.add_argument("--detections", type=Path, default=None, help="a detections.jsonl to use (recorded)")
    ap.add_argument("--weights", type=Path, default=None, help="our checkpoint, for --detect live")
    ap.add_argument("--events-file", type=Path, default=None,
                    help="detected events (default: R3's for the clip, else the hand-written stand-in)")
    ap.add_argument("--demo", action="store_true", help="the demo path: refuse the hand-written stand-in")
    ap.add_argument("--replay", type=Path, default=None,
                    help="a slice recording to answer the single Analyst path's models")
    ap.add_argument("--agents", choices=("offline", "live"), default="offline",
                    help="the multi-agent graph's writers: offline stand-ins (no Azure), or the published "
                         "Foundry agents (a live, billed call)")
    ap.add_argument("--views", type=Path, default=None,
                    help="vision's views/ folder for the clip (one observations.jsonl per camera): the "
                         "fact-checker looks again through the other cameras at a claim it would hold")
    ap.add_argument("--single-analyst", action="store_true",
                    help="run the single Analyst -> Fact-checker path instead of the graph (the fallback)")
    ap.add_argument("--plant", action="store_true", help="plant a false number in the first draft")
    ap.add_argument("--speech", choices=("none", "azure"), default="none",
                    help="audio description voice: none (estimated timing, the viewer's browser voice) or "
                         "azure (synthesise every line through Azure AI Speech: a live call)")
    ap.add_argument("--voice-audio", action="store_true",
                    help="pre-generate the phone's read-aloud audio in the pinned voice (speech.json, "
                         "speech/; ninety/speech/bundle.py): a live Azure call")
    ap.add_argument("--describer", choices=("code", "foundry"), default="code",
                    help="audio description lines: code only, or foundry (the published Describer "
                         "agent words each verified moment, checked like any line: a live call)")
    ap.add_argument("--tracked", type=Path, default=None,
                    help="vision's tracked.json for the clip: adds the radar (needs --observations)")
    ap.add_argument("--observations", type=Path, default=None,
                    help="vision's observations.jsonl for the clip: the radar's camera footprint")
    ap.add_argument("--match", action="store_true",
                    help="match mode: chapters, scoreline and team stats for a condensed match (match.json)")
    ap.add_argument("--captioner", choices=("code", "foundry"), default="code",
                    help="highlight captions with --match: code only, or foundry (the published Captioner "
                         "model, each caption fact-checked, the code caption kept when it is refused)")
    ap.add_argument("--highlights-verdict", type=Path, default=None,
                    help="the highlights measurement's report (docs/eval/shot-flight.json): turns on the "
                         "save filter and the labels it passed; without it every save is in, unlabelled")
    ap.add_argument("--cards", type=Path, default=None,
                    help="the Insight Scout's cards.json for the clip: the phone's hidden stats (cards.json)")
    ap.add_argument("--scorebug", type=Path, default=None,
                    help="the scorebug's readings (scorebug.jsonl from ninety/vision/scorebug.py): the phone "
                         "shows the broadcast's score from them, once the reader is measured")
    ap.add_argument("--team-stats", type=Path, default=None,
                    help="with --match: MatchInsights' insights.json, whose team_stats (tracked distance "
                         "with its coverage) go into match.json for the phone's Team Stats")
    ap.add_argument("--frames", action="store_true", help="ship JPEG frames instead of encoding video.webm")
    return ap


def main(argv: list[str] | None = None) -> None:
    logging.getLogger("agent_framework").setLevel(logging.WARNING)  # it logs every superstep at INFO
    ap = parser()
    args = ap.parse_args(argv)
    if (args.tracked is None) != (args.observations is None):
        ap.error("the radar needs both --tracked and --observations")
    if args.agents == "live" and (args.replay or args.single_analyst):
        ap.error("--agents live runs the graph on the published agents: "
                 "not with --replay or --single-analyst")
    manifest = asyncio.run(run(args))
    a = manifest["agents"]
    print(
        f"{manifest['clip']}: {manifest['detections']['frames']} frames detected, "
        f"{manifest['events']['count']} events ({manifest['events']['source']}), {manifest['facts']} facts, "
        f"{a['accepted']}/{a['claims']} claims accepted ({a['mode']}), {manifest['cues']} cues, "
        f"{manifest['audio']['lines']} described ({manifest['audio']['mode']}), "
        f"footage {manifest['footage']['kind']} -> {args.out}"
    )


if __name__ == "__main__":
    main()
