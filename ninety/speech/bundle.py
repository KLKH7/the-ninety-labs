"""Read-aloud audio for a bundle, made once at build time in the pinned voice (ninety/speech/voice.py).

    uv run ninety-e2e <clip> --out <bundle> --voice-audio       # as the last step of the bundle
    uv run python -m ninety.speech.bundle <bundle>               # or on a bundle already written
    uv run python -m ninety.speech.bundle <bundle> --estimate    # lines and cost first: no call

Every line the phone reads aloud from the bundle gets an MP3: the fixed lines (FIXED, the voice
preview), each audio description line (audio.json), each commentary call (commentary.json), and
each verified insight card (cards.json)
as its spoken form, with and without the "New insight: " the phone says before a new one, and its
"Why?" answer. They are written to
speech/<key>.mp3, and speech.json maps each line's key (voice.key: SHA-256 of the text) to its
file, so the phone finds a line's audio by the text it is about to say (web/phone/src/voice.ts).

A synthesis is cached by voice, rate and text in `--cache` (runs/speech-cache by default), so a
rebuilt bundle pays only for lines it has not said before. A line that fails is left out of
speech.json and counted: the phone falls back for that line, and the build does not fail.
The Speech resource is on the free tier (F0), which allows 20 requests a minute; a 429 waits as
long as Azure's Retry-After says, at most `MAX_RETRIES` times.

This is a live Azure call: off by default in ninety-e2e, run only when agreed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from collections.abc import Callable
from pathlib import Path

from ninety.speech import voice

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / "runs" / "speech-cache"
NEW_INSIGHT = "New insight: "  # the phone's prefix for a card that just arrived (web/phone/src/main.ts)
# Lines the phone says whatever the match: the Listening sheet's voice preview (web/phone/src/main.ts,
# SAMPLE), so the fan previews the voice they will hear. It states no fact about any match: a number
# a fan hears is computed by code (AGENTS.md), and this line is the same in every bundle.
FIXED = ("This is the voice that will read the match to you.",)
MAX_RETRIES = 3
RETRY_WAIT_S = 3.0  # design: when a 429 gives no Retry-After; F0 refills over a minute
# Azure AI Speech S1 neural text to speech: $15 per million characters (Azure Retail Prices API,
# product "Azure Speech", meter "S1 Neural Text To Speech Characters", northcentralus, read
# 2026-10-23). The resource is F0 today, whose first 0.5 M characters a month are free.
USD_PER_CHAR = 15 / 1_000_000

Synth = Callable[[str], tuple[bytes, float]]  # SSML -> (audio, seconds the request took)


def lines(bundle: Path) -> list[tuple[str, str]]:
    """(text, kind) for every line the phone may read aloud from this bundle, each text once."""
    found: dict[str, str] = {}

    def add(text: str | None, kind: str) -> None:
        text = voice.normalise(text or "")
        if text:
            found.setdefault(text, kind)

    for text in FIXED:
        add(text, "fixed")
    audio = bundle / "audio.json"
    if audio.is_file():
        for said in json.loads(audio.read_text()).get("said", []):
            add(said.get("spoken"), "description")
    commentary = bundle / "commentary.json"
    if commentary.is_file():  # the commentary toggle's calls (ninety/speech/commentary.py)
        for line in json.loads(commentary.read_text()).get("lines", []):
            add(line.get("text"), "commentary")
    cards = bundle / "cards.json"
    if cards.is_file():
        for card in json.loads(cards.read_text()):
            if card.get("status") != "verified":
                continue  # only verified cards reach a fan
            add(card.get("spoken"), "insight")
            if card.get("spoken"):
                add(NEW_INSIGHT + card["spoken"], "insight")
            answer = (card.get("why") or {}).get("answer") or {}
            if answer.get("status") == "verified":  # the schema says so; checked here too
                add(answer.get("text"), "why")
    return list(found.items())


def rate_for(kind: str) -> str | None:
    return voice.INSIGHT_RATE if kind == "insight" else None


def cache_name(text: str, rate: str | None) -> str:
    return hashlib.sha256(f"{voice.VOICE}|{voice.FORMAT}|{rate or ''}|{text}".encode()).hexdigest() + ".mp3"


def azure_synth() -> Synth:
    from ninety.speech import tts  # imports the Azure credential: only when asked for

    return lambda document: tts.synthesize_ssml(document, voice.FORMAT)


def _with_retries(synth: Synth, document: str, sleep: Callable[[float], None]) -> tuple[bytes, float]:
    import httpx

    for attempt in range(MAX_RETRIES + 1):
        try:
            return synth(document)
        except httpx.HTTPStatusError as e:
            if e.response.status_code != 429 or attempt == MAX_RETRIES:
                raise
            sleep(float(e.response.headers.get("retry-after") or RETRY_WAIT_S))
    raise AssertionError("unreachable")


def write(bundle: Path, synth: Synth | None = None, cache: Path | None = None,
          sleep: Callable[[float], None] = time.sleep) -> dict:
    """speech/ and speech.json in `bundle`; returns the summary for its manifest."""
    synth = synth or azure_synth()
    cache = cache or CACHE
    cache.mkdir(parents=True, exist_ok=True)
    out = bundle / "speech"
    out.mkdir(exist_ok=True)
    index: dict[str, dict] = {}
    took: list[float] = []
    chars = cached = failed = 0
    wanted = lines(bundle)
    for text, kind in wanted:
        rate = rate_for(kind)
        hit = cache / cache_name(text, rate)
        if hit.is_file():
            audio = hit.read_bytes()
            cached += 1
        else:
            try:
                audio, seconds = _with_retries(synth, voice.ssml(text, rate), sleep)
            except Exception as e:  # noqa: BLE001  one failed line falls back on the phone, recorded
                failed += 1
                print(f"speech: {kind} line not synthesised ({type(e).__name__})")
                continue
            hit.write_bytes(audio)
            took.append(seconds)
            chars += len(text)
        k = voice.key(text)
        (out / f"{k}.mp3").write_bytes(audio)
        index[k] = {"file": f"speech/{k}.mp3", "kind": kind, "bytes": len(audio)}
    body = {"voice": voice.VOICE, "format": voice.FORMAT, "insight_rate": voice.INSIGHT_RATE,
            "key": "sha256 of the text, whitespace collapsed", "lines": index}
    (bundle / "speech.json").write_text(json.dumps(body, indent=1, sort_keys=True) + "\n")
    took.sort()
    return {
        "voice": voice.VOICE,
        "lines": len(index),
        "failed": failed,
        "cached": cached,
        "synth_requests": len(took),
        "synth_chars": chars,
        "synth_p50_s": _quantile(took, 0.5),
        "synth_p95_s": _quantile(took, 0.95),
        "bytes": sum(v["bytes"] for v in index.values()),
        # What the bundle's lines cost from an empty cache: the per-match cost.
        "chars_total": sum(len(t) for t, _ in wanted),
        "usd_at_s1": round(sum(len(t) for t, _ in wanted) * USD_PER_CHAR, 4),
    }


def estimate(bundle: Path, cache: Path | None = None) -> dict:
    """What `write` would synthesise, and its cost at S1, without calling Azure: every line, and
    those the cache does not hold yet (what a run would bill)."""
    cache = cache or CACHE
    wanted = lines(bundle)
    new = [(t, k) for t, k in wanted if not (cache / cache_name(t, rate_for(k))).is_file()]
    by_kind: dict[str, int] = {}
    for _, kind in wanted:
        by_kind[kind] = by_kind.get(kind, 0) + 1
    chars = sum(len(t) for t, _ in wanted)
    new_chars = sum(len(t) for t, _ in new)
    return {"lines": len(wanted), "by_kind": by_kind, "chars": chars,
            "usd_at_s1": round(chars * USD_PER_CHAR, 4), "new_lines": len(new), "new_chars": new_chars,
            "new_usd_at_s1": round(new_chars * USD_PER_CHAR, 4)}


def _quantile(values: list[float], q: float) -> float | None:
    """Nearest-rank quantile (as ninety/speech/describe.py); None with nothing measured."""
    if not values:
        return None
    return round(values[min(len(values) - 1, max(0, round(q * len(values) + 0.5) - 1))], 3)


def add_to_manifest(bundle: Path, summary: dict) -> dict:
    path = bundle / "manifest.json"
    manifest = json.loads(path.read_text())
    manifest["speech"] = summary
    manifest["files"] = [f for f in manifest.get("files", []) if f != "speech.json"] + ["speech.json"]
    path.write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Pre-generate a bundle's read-aloud audio (a live Azure call).")
    ap.add_argument("bundle", type=Path)
    ap.add_argument("--cache", type=Path, default=CACHE)
    ap.add_argument("--estimate", action="store_true",
                    help="count the lines and their cost; call nothing (run this first, and agree the cost)")
    args = ap.parse_args(argv)
    if args.estimate:
        print(json.dumps(estimate(args.bundle, args.cache), indent=1))
        return
    summary = write(args.bundle, cache=args.cache)
    add_to_manifest(args.bundle, summary)
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
