"""How useful the audio description is, measured: what it says, how late, and what it leaves out.

    uv run python -m ninety.eval.describe_eval            # writes docs/eval/describe.md (offline)
    uv run python -m ninety.eval.describe_eval --check    # fails if that file is stale

The Describer (ninety/speech/describe.py) schedules one voice: every line starts within MAX_LAG_S of
its event, shortens or is dropped rather than run late. It computed all of that and reported only
the worst lag (audit row 11). This reads its output on the committed detected-event fixtures, with
the cues the offline single Analyst path makes (templates and its verified claim), and
reports per clip:

- coverage: the confident passes, shots and goals (the events a graphic airs for) that a line was
  said for, in its own line or inside a verified insight it cites;
- lag from each event to its line (p50 and max; a p95 only from 20 lines, as elsewhere);
- lines said in their short form, and lines dropped (the voice was busy), with why;
- talk share: the seconds spoken over the clip's span of events.

Offline only: the timing is the word-count estimate (`describe.estimate`), not measured speech, and
the Describer model's line is not used (it stays off in the demo until a live run passes).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import sys
import warnings
from collections import Counter
from pathlib import Path

from ninety.agents.cues import TEMPLATE_TYPES as GRAPHIC_TYPES
from ninety.agents.factcheck import MIN_CONFIDENCE
from ninety.match import detected
from ninety.speech import describe

ROOT = Path(__file__).resolve().parents[2]
REPORT = ROOT / "docs" / "eval" / "describe.md"
# The committed detected-event fixtures: the M1 clip's pixel-detected events, and the hand-written
# stand-in for the same clip (named as one).
CLIPS = {
    "seed900001 (detected from the pixels)": detected.FIXTURES / "detected-seed900001.jsonl",
    # The whole stand-in file (0 to 101.5 s), not windowed to the clip as ninety-e2e would.
    "seed900001 (hand-written stand-in, whole file)": detected.FIXTURES / "detected-standin-seed900001.jsonl",
}
# Which detected events on the M1 clip are real: those the committed event report matched to the
# answer key (grading is its allowed use). The others are false detections (v00004, the shot read as
# a pass; v00005, an out of play), and a line about one describes something that did not happen.
# The report grades the detector that made the fixture: v3 (with possession changes), not v2, whose
# ids are another order's (lesson 243).
EVENT_REPORT = ROOT / "docs" / "eval" / "event-report-v3.json"
MIN_FOR_P95 = 20  # nearest rank: below 20 values a p95 is the maximum


def _rank(values: list[float], q: float) -> float:
    return values[max(0, math.ceil(q * len(values)) - 1)]


async def _cues(events: list[dict], clip: str) -> list[dict]:
    from ninety import e2e  # the bundle builder's own explain step, offline

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        cues, _, _ = await e2e.explain_and_render(events, clip, False, None)
    return cues


def real_detections(seed: int = 900001) -> set[str] | None:
    """The detected event ids the committed event report matched to a true event, or None when the
    report has no such clip."""
    report = json.loads(EVENT_REPORT.read_text())
    clip = next((c for c in report["clips"] if c["seed"] == seed), None)
    if clip is None:
        return None
    # The report names detected events by id: trust an id only while it is still the same event in
    # the committed fixture (same type), or a regenerated fixture
    # would be graded by another event's match.
    fixture = {e["id"]: e for e in detected.load(detected.FIXTURES / f"detected-seed{seed}.jsonl")}
    out = set()
    for p in clip["events"]["time_only"]["pairs"]:
        e = fixture.get(p["detected_id"])
        if e is None or e["type"] != p["type"]:
            raise ValueError(f"{EVENT_REPORT.name}: {p['detected_id']} is not the event it matched")
        out.add(p["detected_id"])
    return out


def measure(path: Path) -> dict:
    events = detected.load(path)
    clip = "seed900001"
    cues = asyncio.run(_cues(events, clip))
    track, refused = describe.describe(events, cues)
    confident = [e for e in events if e["type"] in GRAPHIC_TYPES
                 and (e.get("confidence") is None or e["confidence"] >= MIN_CONFIDENCE)]
    covered = {i for s in track.said for i in s.evidence}
    lags = sorted(s.lag_s for s in track.said)
    spoken = sum(s.t_out - s.t_in for s in track.said)
    # From the first event to whichever ends last: the last event or the last line said about it.
    end = max([e["t"] for e in events] + [s.t_out for s in track.said], default=0.0)
    span = (end - min(e["t"] for e in events)) if events else 0.0
    return {
        "events": len(events),
        "confident": len(confident),
        "covered": sum(e["id"] in covered for e in confident),
        "covered_ids": sorted(e["id"] for e in confident if e["id"] in covered),
        "confident_ids": sorted(e["id"] for e in confident),
        "lines": len(track.said),
        "short": sum(s.short for s in track.said),
        "dropped": len(track.dropped),
        "dropped_why": Counter(d["reason"].split(" until")[0] for d in track.dropped),
        "refused": len(refused),
        "lags": lags,
        "spoken_s": round(spoken, 1),
        "span_s": round(span, 1),
        "sources": Counter(s.source for s in track.said),
    }


def report() -> str:
    lines = [
        "# Audio description: what it says, how late, what it leaves out",
        "",
        "Generated by `uv run python -m ninety.eval.describe_eval` (offline; `--check` fails if this file "
        "is stale, as `tests/test_describe_eval.py` does). Timing is the word-count estimate, not measured "
        "speech; the Describer model's line is off. Cues come from the offline single Analyst path "
        "(`ninety/e2e.explain_and_render`: templates and the offline Analyst's verified claim). Talk share "
        "is the seconds spoken over the time from the first event to the end of the last event or line. "
        "Small numbers: each clip is one fixture.",
        "",
        "| Clip | Confident graphic events covered | of them real (event report) | Lines said (short form) "
        "| Dropped | Refused | Lag p50 / p95 / max (s) | Talk share |",
        "|---|---|---|---|---|---|---|---|",
    ]
    notes = []
    for name, path in CLIPS.items():
        m = measure(path)
        lags = m["lags"]
        if lags:
            p95 = f"{_rank(lags, 0.95):.2f}" if len(lags) >= MIN_FOR_P95 else "not shown"
            lag = f"{_rank(lags, 0.5):.2f} / {p95} / {lags[-1]:.2f}"
        else:
            lag = "no lines"
        share = f"{m['spoken_s']} s of {m['span_s']} s" if m["span_s"] else "-"
        real = real_detections() if "pixels" in name else None
        graded = ("-" if real is None else
                  f"{len(set(m['covered_ids']) & real)} of {len(set(m['confident_ids']) & real)} real")
        lines.append(f"| {name} | {m['covered']} of {m['confident']} | {graded} | "
                     f"{m['lines']} ({m['short']}) | {m['dropped']} | {m['refused']} | {lag} | {share} |")
        why = ", ".join(f"{n} x {r}" for r, n in sorted(m["dropped_why"].items())) or "none"
        said = ", ".join(f"{n} {s}" for s, n in sorted(m["sources"].items())) or "none"
        notes.append(f"- {name}: {m['events']} events; lines by source: {said}; dropped: {why}.")
    lines += ["", "Coverage counts *detected* events, false ones included: on the pixel clip a line about a "
              "false detection describes something that did not happen. The real column grades them against "
              "the answer key through the committed event report (`docs/eval/event-report-v2.json`, "
              "time-only matches); the stand-in has none.", "",
              f"Every line must start within {describe.MAX_LAG_S} s of its event (the brief's limit); "
              "a line that cannot is shortened, then dropped, never said late.", "", *notes]
    return "\n".join(lines) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="fail if the committed report is stale")
    args = ap.parse_args()
    text = report()
    if args.check:
        if REPORT.read_text() != text:
            sys.exit(f"{REPORT} is stale: run uv run python -m ninety.eval.describe_eval")
        return
    REPORT.write_text(text)
    print(text)


if __name__ == "__main__":
    main()
