"""Team match stats for the phone: distance covered, from tracked positions only (GROUNDING I16).

Distance is summed per track at the stat's own time scale, one step a second (the tracked frames are
already a one-second line fit, ninety/vision/tracked_frames.SMOOTH_FRAMES; summing every frame
would read what jitter is left as running, docs/LESSONS.md lesson 133). A step faster than
MAX_STEP_MPS is a track jumping between players (an identity switch, a lost and found track), not
running, and is skipped, as is any gap of more than a step. What the footage does not show is not
guessed: the number is the distance of the players tracked, with its coverage, the share of the
team's player-seconds that were tracked ("from the footage shown"). How far it sits from the truth
is measured on simulated tracks (ninety/eval/team_distance_eval.py, docs/eval/team-distance.md).

Possession share is not here: no confidence for it has passed a measured gate (the possession
layer's calibration, docs/eval/possession-calibration.md, opened no bar), so the field is left out
and the phone hides the row.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Mapping, Sequence

from ninety.intel.scene import FPS, TEAM_SIZE, TEAMS, minute_of

STEP_S = 1.0  # the stat's time scale, the tracked frames' smoothing (see the module docstring)
# Players' match peak speeds are about 8 to 9 m/s (docs/GROUNDING.md R6); a step past 12 m/s
# (*design*: past that with the position error to spare) is a track jumping, not a player running.
MAX_STEP_MPS = 12.0
BIN_MIN = 5  # the phone's strips: one bar per five match minutes (*design*)


def _sampled(frames: Sequence[Mapping]) -> list[Mapping]:
    step = round(STEP_S * FPS)
    return [f for f in frames if int(f["frame"]) % step == 0]


def distance(frames: Sequence[Mapping], team: str) -> dict:
    """The team's tracked distance over the frames: metres, coverage, steps skipped as jumps."""
    sampled = _sampled(frames)
    last: dict[str, tuple[float, float, float]] = {}
    metres = 0.0
    jumps = 0
    seen = 0
    for f in sampled:
        t = float(f["t"])
        for p in f["players"]:
            if p["team"] != team:
                continue
            seen += 1
            x, y = float(p["x"]), float(p["y"])
            prev = last.get(p["id"])
            last[p["id"]] = (t, x, y)
            if prev is None or t - prev[0] > STEP_S * 1.5:
                continue
            step = math.hypot(x - prev[1], y - prev[2])
            if step > MAX_STEP_MPS * (t - prev[0]):
                jumps += 1
                continue
            metres += step
    coverage = seen / (TEAM_SIZE * len(sampled)) if sampled else 0.0
    return {"m": metres, "coverage": coverage, "jumps": jumps, "samples": len(sampled)}


def team_stats(frames: Sequence[Mapping]) -> dict:
    """The phone's team stats: each team's distance over the clip and in BIN_MIN-minute bins."""
    by_bin: dict[int, list[Mapping]] = defaultdict(list)
    for f in frames:
        by_bin[(minute_of(float(f["t"])) - 1) // BIN_MIN].append(f)
    out: dict = {"from_footage": True, "bin_min": BIN_MIN, "distance": {}}
    for team in TEAMS:
        whole = distance(frames, team)
        bins = []
        for b in sorted(by_bin):
            d = distance(by_bin[b], team)
            bins.append(
                {
                    "minute_from": b * BIN_MIN + 1,
                    "minute_to": (b + 1) * BIN_MIN,
                    "km": round(d["m"] / 1000, 1),
                    "coverage": round(d["coverage"], 2),
                }
            )
        out["distance"][team] = {
            "km": round(whole["m"] / 1000, 1),
            "coverage": round(whole["coverage"], 2),
            "bins": bins,
        }
    return out


__all__ = ["BIN_MIN", "MAX_STEP_MPS", "STEP_S", "distance", "team_stats"]
