"""One command for the whole chain on one clip, writing a bundle the viewer opens.

    uv run ninety-e2e runs/test-frozen-cca498c/test/seed900001 --out runs/e2e/seed900001
    uv run ninety-e2e <clip> --out <bundle> --plant           # plant a false number: see a rejection
    npm run dev --prefix web/viewer                           # then open the bundle in the viewer

Stages (the brief's names), each writing one file in the bundle:

1. Ingest: detections. `--detections FILE` reads a detector run that was already made (the
   default is the committed ours-v2 run on the frozen test set, docs/eval/vision-report-v1);
   `--detect live --weights W` runs RF-DETR (ninety.vision.detect, needs `uv sync --group vision`).
2. Interpret: events, then stats. `--events vision` calls R3's detector of events from the
   detections. `--events stand-in` (the default until that lands) reads the simulator's events for
   the clip, and says so in the bundle and on screen: ground truth must leave the live path at M1.
   Stats come from ninety.intel.stats: code computes every number.
3. Explain: the Analyst and the Fact-checker (ninety.agents.slice.run_workflow), offline: a
   deterministic Analyst writes the claim from the events, and the real code checks gate it. With
   `--replay FILE` the recorded Foundry answers stand in for the models instead. No Azure, no live
   model call, in either mode.
4. Render: overlay cues (schemas/overlay_cue.schema.json): template cues for every pass and shot,
   and one verified insight per minute, aired only if the Fact-checker accepted it.
5. Personalize: analyst and casual cues side by side; the viewer switches between them.

The bundle (manifest.json, cues.jsonl, trace.json, events.jsonl, facts.json, detections.jsonl and
the footage as video.webm or frames/) is all the viewer reads. Nothing in it but `events.jsonl`
under the stand-in comes from ground truth, and the manifest names that.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import subprocess
import sys
import warnings
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from jsonschema import validate

from ninety.agents.cues import SCHEMA as CUE_SCHEMA
from ninety.agents.cues import _text, template_cues
from ninety.agents.factcheck import Claim, Verdict
from ninety.agents.ledger import InMemoryLedger, load_match
from ninety.agents.slice import Recording, replayer, run_workflow
from ninety.intel.stats import calculate_facts
from ninety.match.facts import AGENT_TYPES, compact, minute_of

ROOT = Path(__file__).resolve().parents[1]
RECORDED_DETECTIONS = ROOT / "docs" / "eval" / "vision-report-v1" / "detections"
EVENT_SCHEMA = json.loads((ROOT / "schemas" / "match_event.schema.json").read_text())
BUNDLE_FORMAT = 1
INSIGHT_SECONDS = 6.0  # an insight is a sentence, not a lower-third tag: a second longer to read
STAND_IN = "stand-in: the simulator's events for this clip (ground truth), until vision events land"

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


# ---------------------------------------------------------------- 2 Interpret: events and stats

EventSource = Callable[[Clip, list], list[dict]]


def stand_in_events(clip: Clip, detections: list) -> list[dict]:
    """The simulator's events for the clip. Ground truth: allowed on the live path only until M1."""
    path = clip.dir / "events.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def vision_events(clip: Clip, detections: list) -> list[dict]:
    """R3's events detected from video (ninety.vision.events); refuses to run until it exists."""
    try:
        from ninety.vision.events import detect_events  # type: ignore[import-not-found]
    except ImportError as e:
        raise SystemExit(f"--events vision needs ninety.vision.events.detect_events ({e})") from e
    return detect_events(detections, clip.meta)


EVENT_SOURCES: dict[str, EventSource] = {"stand-in": stand_in_events, "vision": vision_events}


def checked_events(events: list[dict]) -> list[dict]:
    for event in events:
        validate(event, EVENT_SCHEMA)
    return sorted(events, key=lambda e: (e["t"], e["id"]))


# ---------------------------------------------------------------- 3 Explain: claims, fact-checked


def most_interesting(events: list[dict]) -> dict | None:
    """The one event a minute's sentence is about (INTEREST), or None in a quiet minute."""
    ranked = [e for e in events if e["type"] in INTEREST and e.get("player")]
    if not ranked:
        return None
    speed = lambda e: e.get("ball_speed_kmh") or 0  # noqa: E731
    return min(ranked, key=lambda e: (INTEREST[e["type"]], -speed(e), e["second"], e["id"]))


def offline_analyst(events: list[dict]):
    """A deterministic Analyst with the published one's reply format, written from the same events.
    It stands in for the model when there is no Azure: the workflow and the code checks are real."""
    by_minute: dict[int, list[dict]] = {}
    for event in events:
        by_minute.setdefault(event["minute"], []).append(event)

    async def ask(prompt: str) -> str:
        minute = int(prompt.split("minute ")[1].split(".")[0])
        event = most_interesting(by_minute.get(minute, []))
        if event is None:
            return json.dumps({"text": "", "evidence": []})
        return json.dumps({"text": _text(event, "analyst") + ".", "evidence": [event["id"]]})

    return ask


async def judge_not_run(claim: Claim, evidence: list[dict]) -> Verdict:
    """Offline there is no Judge model: the code checks alone decide, and the trace says so."""
    return Verdict(ok=True, reasons=[])


def trace_steps(lines: list[str], judged: bool) -> list[dict]:
    """The workflow's trace lines as {agent, message}, naming the offline Judge for what it is."""
    steps = []
    for line in lines:
        agent, _, message = line.partition(": ")
        if agent == "judge" and not judged:
            message = "not run offline: the code checks alone decided"
        elif not judged:
            message = message.replace("(replayed)", "(offline analyst)")
        steps.append({"agent": agent, "message": message})
    return steps


async def explain(events: list[dict], seed: int, plant: bool, recording: Recording | None) -> list[dict]:
    """One claim per minute the clip covers, through the Analyst -> Fact-checker workflow."""
    claims = []
    agent_events = [compact(e) for e in events if e["type"] in AGENT_TYPES]
    minutes = sorted({minute_of(e) for e in events})
    for minute in minutes:
        if recording is not None:
            if recording.minute != minute:
                continue
            ask, judge_fn = replayer(recording.turns)
            known = recording.events
        else:
            ask, judge_fn = offline_analyst(agent_events), judge_not_run
            known = agent_events
            if most_interesting([e for e in agent_events if e["minute"] == minute]) is None:
                continue
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            outcome = await run_workflow(ask, judge_fn, minute, plant, seed, 0, False, known)
        t = min((e["t"] for e in events if e["id"] in set(outcome.claim.evidence)), default=None)
        claims.append(
            {
                "id": f"claim-m{minute}",
                "minute": minute,
                "t": t,
                "status": "accepted" if outcome.accepted else "held_back",
                "drafts": outcome.attempts,
                "planted": plant,
                "mode": "replay" if recording is not None else "offline",
                "text": outcome.claim.text,
                "evidence": outcome.claim.evidence,
                "steps": trace_steps(outcome.trace, judged=recording is not None),
            }
        )
    return claims


# ---------------------------------------------------------------- 4 Render: cues


def insight_cues(claims: list[dict]) -> list[dict]:
    """An accepted claim airs in the top-right slot for both personas; a held-back one never airs."""
    cues = []
    for claim in claims:
        if claim["status"] != "accepted" or claim["t"] is None:
            continue
        for persona in ("analyst", "casual"):
            cue = {
                "id": f"cue-{claim['id']}-{persona}",
                "t_in": claim["t"],
                "t_out": round(claim["t"] + INSIGHT_SECONDS, 2),
                "kind": "insight",
                "slot": "top_right",
                "anchor": None,
                "persona": persona,
                "lang": "en",
                "text": claim["text"],
                "verified": True,
                "replaces": None,
                "evidence": claim["evidence"],
            }
            validate(cue, CUE_SCHEMA)
            cues.append(cue)
    return cues


async def build_cues(events: list[dict]) -> list[dict]:
    ledger = InMemoryLedger()
    await load_match(ledger, events, ())
    return await template_cues(ledger)


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

    det_path = detections_for(clip, args.detections, args.detect == "live", args.weights,
                              out / "detections.jsonl")
    from ninety.vision.detections import read_detections

    detections = read_detections(det_path)
    if det_path != out / "detections.jsonl":
        shutil.copyfile(det_path, out / "detections.jsonl")

    events = checked_events(EVENT_SOURCES[args.events](clip, detections))
    facts = [f.as_dict() for f in calculate_facts(events)]
    recording = Recording.load(args.replay) if args.replay else None
    claims = await explain(events, clip.meta["seed"], args.plant, recording)
    cues = sorted(await build_cues(events) + insight_cues(claims), key=lambda c: (c["t_in"], c["id"]))
    footage = write_footage(clip, out, encode=not args.frames)

    write_jsonl(out / "events.jsonl", events)
    write_jsonl(out / "cues.jsonl", cues)
    (out / "facts.json").write_text(json.dumps(facts, indent=2) + "\n")
    (out / "trace.json").write_text(json.dumps({"claims": claims}, indent=2) + "\n")
    model = detections[0].model if detections else None
    manifest = {
        "format": BUNDLE_FORMAT,
        "clip": clip.id,
        "fps": clip.meta["fps"],
        "width": clip.meta["params"]["width"],
        "height": clip.meta["params"]["height"],
        "t_start": clip.meta["t_start"],
        "footage": footage,
        "detector": None if model is None else f"{model.name} {model.size} {model.checkpoint}",
        "detections": {"source": "live" if args.detect == "live" else "recorded", "frames": len(detections)},
        "events": {"source": STAND_IN if args.events == "stand-in" else "vision", "count": len(events)},
        "facts": len(facts),
        "agents": {"mode": "replay" if recording else "offline", "planted": args.plant,
                   "claims": len(claims), "accepted": sum(c["status"] == "accepted" for c in claims)},
        "cues": len(cues),
        "files": ["detections.jsonl", "events.jsonl", "facts.json", "trace.json", "cues.jsonl"],
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Run the chain on one clip and write a bundle for the viewer.")
    ap.add_argument("clip", type=Path, help="a rendered clip directory (clip.json and images/)")
    ap.add_argument("--out", type=Path, required=True, help="the bundle directory")
    ap.add_argument("--detect", choices=("recorded", "live"), default="recorded")
    ap.add_argument("--detections", type=Path, default=None, help="a detections.jsonl to use (recorded)")
    ap.add_argument("--weights", type=Path, default=None, help="our checkpoint, for --detect live")
    ap.add_argument("--events", choices=tuple(EVENT_SOURCES), default="stand-in")
    ap.add_argument("--replay", type=Path, default=None, help="a slice recording to answer for the models")
    ap.add_argument("--plant", action="store_true", help="plant a false number in the first draft")
    ap.add_argument("--frames", action="store_true", help="ship JPEG frames instead of encoding video.webm")
    return ap


def main(argv: list[str] | None = None) -> None:
    args = parser().parse_args(argv)
    manifest = asyncio.run(run(args))
    a = manifest["agents"]
    print(
        f"{manifest['clip']}: {manifest['detections']['frames']} frames detected, "
        f"{manifest['events']['count']} events ({manifest['events']['source']}), {manifest['facts']} facts, "
        f"{a['accepted']}/{a['claims']} claims accepted ({a['mode']}), {manifest['cues']} cues, "
        f"footage {manifest['footage']['kind']} -> {args.out}"
    )


if __name__ == "__main__":
    main()
