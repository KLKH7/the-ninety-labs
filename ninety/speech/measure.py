"""Read-aloud latency and cost, measured against our Speech resource (docs/eval/speech-latency.md).

    uv run python -m ninety.speech.measure --bundle runs/replay --out docs/eval/speech-latency.json

Two paths, both in the pinned voice (ninety/speech/voice.py):
- build time: `bundle.write` on a bundle (every line it holds, from an empty cache), and on LINES,
  a fixed set of lines shaped like the phone's (audio description, insight cards with their
  "New insight: " form, Why? answers), each synthesised once: request seconds per line;
- Live: the /api/live/speak route in process (ninety/api/speak.py, its own aio credential and async
  client), with each of ANSWERS given as an answer first, then spoken: seconds from request to
  audio, the route's own work included. A first request also signs in; it is reported apart.

A live Azure call, run by hand, never in CI. The resource is F0 (20 requests a minute), so the
script spaces its requests (`SPACING_S`) and the numbers are not inflated by 429 waits.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import tempfile
import time
from pathlib import Path

from ninety.speech import bundle, voice

SPACING_S = 3.1  # 60 s / 20 requests on F0, with a margin
# Shaped like the phone's lines (fictional clubs and players only), written for this measurement.
LINES = [
    "Home 4 passes to Home 9 on the left.",
    "Away 6 wins it back in the middle.",
    "Home 9 shoots from the right, 22 metres out.",
    "Goal! Home 9 scores. Oakfield lead 1-0.",
    "Away 2 clears it, far side.",
    "Home's back line has pushed up 8 metres.",
    "Fenwick's number nine is through on goal, one on one with the keeper.",
    "Away 11 crosses from the right; Home 1 claims it.",
    "Oakfield won it back in three seconds and broke down the right.",
    "New insight: Oakfield won it back in three seconds and broke down the right.",
    "Home 8's pass took four Fenwick players out of the game, the most by any pass so far.",
    "New insight: Home 8's pass took four Fenwick players out of the game, the most by any pass so far.",
    "Fenwick had three players spare on the left for twelve seconds before the chance.",
    "New insight: Fenwick had three players spare on the left for twelve seconds before the chance.",
    "Because Home 6 dropped between the centre-backs, the full-backs could push on.",
    "Home 4 lost it with two teammates open ahead of him.",
    "Fenwick's press won the ball back within five seconds four times this half.",
    "The line break came after Oakfield moved it wide twice to pull Fenwick's midfield across.",
    "Away 9 is offside by about a metre as the pass is played.",
    "Half-time: Oakfield 1, Fenwick 0.",
]
ANSWERS = [
    "Home 9 has run 4.2 km so far, 0.6 km more than anyone else on the pitch.",
    "Home 9's top speed is 31.4 km/h, at 23:10, chasing the ball down the left.",
    "Oakfield have had the ball in Fenwick's half for 58% of the last five minutes.",
    "Home 4 has completed 27 of 30 passes, 90%.",
    "Fenwick's back line sits 34 metres from their goal on average, 6 deeper than Oakfield's.",
    "Away 6 has won the ball back 7 times, the most on the pitch.",
    "The best chance so far was Home 9's shot at 31:02, from 11 metres, central.",
    "Home 8 has played 5 passes that took out three or more players.",
    "Fenwick switched play 4 times in the first half, all from left to right.",
    "Oakfield's shape is a back four with Home 6 dropping in when they have the ball.",
]


def quantiles(values: list[float]) -> dict:
    values = sorted(values)
    return {"n": len(values), "p50_s": bundle._quantile(values, 0.5), "p95_s": bundle._quantile(values, 0.95),
            "max_s": round(max(values), 3) if values else None}


def spaced(synth):
    last = [0.0]

    def call(document: str):
        wait = last[0] + SPACING_S - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        last[0] = time.monotonic()
        return synth(document)

    return call


def measure_build(bundle_dir: Path | None) -> dict:
    synth = spaced(bundle.azure_synth())
    out = {}
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        if bundle_dir is not None:
            out["bundle"] = bundle.write(bundle_dir, synth, cache=tmp / "cache-bundle")
        lines_dir = tmp / "lines"
        lines_dir.mkdir()
        (lines_dir / "audio.json").write_text(json.dumps({"said": [{"spoken": t} for t in LINES]}))
        summary = bundle.write(lines_dir, synth, cache=tmp / "cache-lines")
        out["lines"] = summary
    return out


async def measure_live() -> dict:
    from ninety.api.speak import Speaker

    spoken = {voice.key(a) for a in ANSWERS}
    speaker = Speaker(lambda k: k in spoken)

    class Request:  # what Speaker.speak reads of a Starlette request
        def __init__(self, text):
            self.headers = {}
            self.client = None
            self._body = json.dumps({"text": text}).encode()

        async def stream(self):
            yield self._body

    seconds, first = [], None
    for n, text in enumerate(ANSWERS):
        if n:
            await asyncio.sleep(SPACING_S)
        started = time.perf_counter()
        response = await speaker.speak(Request(text))
        took = time.perf_counter() - started
        if response.status_code != 200:
            raise SystemExit(f"live speak failed: {response.status_code} {response.body[:200]!r}")
        if first is None:
            first = round(took, 3)  # includes the managed identity / az sign-in
        else:
            seconds.append(took)
    return {"first_request_s": first, "after_sign_in": quantiles(seconds),
            "speech_request": quantiles(speaker.timings[1:]),
            "chars": sum(len(a) for a in ANSWERS)}


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Measure read-aloud latency and cost (a live Azure call).")
    ap.add_argument("--bundle", type=Path, default=None, help="a bundle whose lines to synthesise")
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args(argv)
    body = {"voice": voice.VOICE, "format": voice.FORMAT, "measured": time.strftime("%Y-%m-%d"),
            "build": measure_build(args.bundle), "live": asyncio.run(measure_live()),
            "usd_per_char_s1": bundle.USD_PER_CHAR}
    args.out.write_text(json.dumps(body, indent=1) + "\n")
    print(json.dumps(body, indent=1))


if __name__ == "__main__":
    main()
