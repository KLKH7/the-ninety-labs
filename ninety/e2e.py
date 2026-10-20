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
3. Explain and 4. Render: R4's live path (ninety/agents/live.py), the one place cues are built:
   template cues for every confident pass and shot, and the Analyst -> Fact-checker workflow, whose
   verified claim airs as an insight cue and whose claims on unsure detections are held. The models
   are offline: a deterministic Analyst writes from the events and the code checks gate it, or
   `--replay FILE` answers with a Foundry recording. No Azure, no live model call.
5. Personalize: analyst and casual cues side by side; the viewer switches between them. The
   Describer (ninety/speech/describe.py) adds the audio description persona: a spoken line per
   confident event or verified claim, with its stereo position, as `audio` cues, audio.json and
   description.vtt. Offline its timing is estimated and the viewer speaks with the browser's voice;
   `--speech azure` synthesises each line through Azure AI Speech instead (off by default: a live
   Azure call, so run it only when agreed).

The bundle (manifest.json, cues.jsonl, trace.json, events.jsonl, facts.json, detections.jsonl and
the footage as video.webm or frames/) is all the viewer reads. This module never opens the clip's
events.jsonl or frames.jsonl: they are the answer key (tests/test_e2e.py checks).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import shutil
import subprocess
import sys
import warnings
from dataclasses import dataclass
from pathlib import Path

from ninety.agents import live, telemetry
from ninety.agents.cues import _text
from ninety.agents.factcheck import Claim, Verdict
from ninety.agents.slice import Recording, replayer, tamper
from ninety.intel.stats import calculate_facts
from ninety.match import detected
from ninety.match.facts import AGENT_TYPES, compact, minute_of
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
        claim = Claim(_text(event, "analyst") + ".", [event["id"]])
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
    events: list[dict], clip: str, plant: bool, recording: Recording | None
) -> tuple[list[dict], list[dict], list[str]]:
    """live.run once per minute the clip covers: its cues (merged by id), one claim trace per
    minute that had something to say, and the detections too unsure to air."""
    agent_events = [compact(e) for e in events if e["type"] in AGENT_TYPES]
    cues: dict[str, dict] = {}
    claims: list[dict] = []
    held: set[str] = set()
    minutes = sorted({minute_of(e) for e in events}) or [None]
    for minute in minutes:
        if minute is None or (recording is None and most_interesting(
                [e for e in agent_events if e["minute"] == minute]) is None):
            ask = judge = None  # a quiet minute: template cues only
        elif recording is not None:
            ask, judge = replayer(recording.turns)
        else:
            ask, judge = offline_analyst(agent_events, plant), judge_not_run
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            result = await live.run(events, clip, ask, judge, minute if ask else None)
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
                "planted": plant and recording is None,
                "mode": "replay" if recording is not None else "offline",
                "text": outcome.claim.text,
                "evidence": outcome.claim.evidence,
                "steps": [trace_step(line, moment, recording is not None) for line in outcome.trace],
            }
        )
    return sorted(cues.values(), key=lambda c: (c["t_in"], c["id"])), claims, sorted(held)


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
    cues, claims, held = await explain_and_render(events, clip.id, args.plant, recording)
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
            upgrades, unavailable = None, f"{type(e).__name__}: {e}"
    voice = describe.Voice() if args.speech == "azure" else None
    track, refused = describe.describe(events, cues, voice or describe.estimate, upgrades)
    if voice is not None:
        voice.save(track, out)
    cues = sorted(cues + describe.audio_cues(track), key=lambda c: (c["t_in"], c["id"]))
    audio = describe.write_track(track, refused, out, clip.meta["t_start"])
    audio["describer"] = {"mode": args.describer, "calls": model_calls, "tokens": tokens,
                          "unavailable": unavailable}
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
        "events": {"source": events_source, "count": len(events), "standin": "stand-in" in events_source,
                   "held": held},
        "facts": len(facts),
        "agents": {"mode": "replay" if recording else "offline", "planted": args.plant and not recording,
                   "claims": len(claims), "accepted": sum(c["status"] == "accepted" for c in claims)},
        "cues": len(cues),
        "audio": audio,
        "files": ["detections.jsonl", "events.jsonl", "facts.json", "trace.json", "cues.jsonl", "audio.json",
                  "description.vtt"],
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
    ap.add_argument("--events-file", type=Path, default=None,
                    help="detected events (default: R3's for the clip, else the hand-written stand-in)")
    ap.add_argument("--demo", action="store_true", help="the demo path: refuse the hand-written stand-in")
    ap.add_argument("--replay", type=Path, default=None, help="a slice recording to answer for the models")
    ap.add_argument("--plant", action="store_true", help="plant a false number in the first draft")
    ap.add_argument("--speech", choices=("none", "azure"), default="none",
                    help="audio description voice: none (estimated timing, the viewer's browser voice) or "
                         "azure (synthesise every line through Azure AI Speech: a live call)")
    ap.add_argument("--describer", choices=("code", "foundry"), default="code",
                    help="audio description lines: code only, or foundry (the published Describer "
                         "agent words each verified moment, checked like any line: a live call)")
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
        f"{manifest['audio']['lines']} described ({manifest['audio']['mode']}), "
        f"footage {manifest['footage']['kind']} -> {args.out}"
    )


if __name__ == "__main__":
    main()
