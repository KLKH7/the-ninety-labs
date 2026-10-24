"""A stand-in for a tracked match, made from a simulated one, for the insight evaluations only.

The whole-pitch tracked output of the demo match does not exist until the demo is rendered and
tracked. The evaluations of the insight tools, the Companion and the Scout run before that, on a
simulated match spoiled the way the tracker spoils it (ninety/eval/roles_eval.spoil: fragmented
tracks, a persistent position error, players missing from frames), with its events renamed to the
tracks and marked as detections. It reads the answer key, so it is an evaluation (AGENTS.md) and
never served: the live path builds MatchInsights from `tracking.tracked` and `detected.load`.
"""

from __future__ import annotations

import json
from pathlib import Path

from ninety.eval import roles_eval
from ninety.intel.match_insights import MatchInsights
from ninety.intel.teamsheet import Fixture

# Design: every detected event a confidence above the detector's floor, so the evaluation measures
# the insight checks, not the confidence gate (which has its own tests).
STANDIN_CONFIDENCE = 0.9


def events_as_detected(run: Path, minutes: float, owner_at) -> list[dict]:
    rows = []
    for line in (run / "events.jsonl").read_text().splitlines():
        e = json.loads(line)
        if e["t"] > minutes * 60:
            break
        e = {**e, "source": "vision", "confidence": STANDIN_CONFIDENCE, "team_confidence": STANDIN_CONFIDENCE}
        for k in ("player", "receiver", "intended", "interceptor", "deflected_by"):
            if e.get(k):
                e[k] = owner_at(e[k], e["frame"])
        rows.append(e)
    return rows


def build(
    run: Path,
    minutes: float,
    fixture: Fixture,
    fragment_s: float = roles_eval.FRAGMENT_S[0],
    missing: float = roles_eval.MISSING,
    seed: int = 1,
    gate: dict | None = None,
) -> MatchInsights:
    frames, _ = roles_eval.load(run, step=1)
    frames = [f for f in frames if f["t"] <= minutes * 60]
    old = roles_eval.MISSING
    roles_eval.MISSING = missing
    try:
        spoilt, owner = roles_eval.spoil(frames, seed, fragment_s)
    finally:
        roles_eval.MISSING = old
    # Which track each true player was at each frame: the track whose owner he is, seen nearest then.
    tracks_of: dict[str, list[tuple[int, str]]] = {}
    for f in spoilt:
        for p in f["players"]:
            tracks_of.setdefault(owner[p["id"]], []).append((f["frame"], p["id"]))

    def owner_at(pid: str, frame: int) -> str:
        seen = tracks_of.get(pid)
        if not seen:
            return f"{pid[0]}-t0"
        return min(seen, key=lambda s: abs(s[0] - frame))[1]

    events = events_as_detected(run, minutes, owner_at)
    spoilt = [{**f, "source": "tracked"} for f in spoilt]
    return MatchInsights.build(f"standin-{run.name}", spoilt, events, fixture, gate)


__all__ = ["STANDIN_CONFIDENCE", "build", "events_as_detected"]
