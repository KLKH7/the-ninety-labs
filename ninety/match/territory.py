"""Territory: where the ball was, per five minutes of match time, from vision's tracked ball.

The phone's Live tab draws it as a mirrored strip (web/phone/src/momentum.ts). It is territory, not
possession: our data has no measured possession, so the strip says only where the ball was.

For each bin of `BIN_S` seconds of match time:

- `home_s`, `away_s`: seconds the ball spent in that team's attacking half. Which half is whose
  follows the engine's one convention, which the tracker's team assignment also follows
  (ninety/sim/engine.py, ninety/vision/track.py): home attacks toward x = 105 in both halves.
- `seen_s`: seconds of footage in the bin where vision saw the ball. Only those frames count: the
  tracked file fills short gaps on a straight line (ninety/radar.py, `ball_seen`), and a filled-in
  ball is an estimate, not a sighting.
- `home`: home's share of the ball's seen time in an attacking half, or None when there is none.

A condensed match shows passages, not the whole match, so a bin covers only the footage in it;
`seen_s` says how much, and the phone shows it. Reads radar.json (vision's output) only; nothing
here opens the answer key.
"""

from __future__ import annotations

import math

FORMAT = 1
SOURCE = "tracked"
# design: five-minute bins, the grain match-momentum graphics use (the Coordinator's Mobbin round 2).
BIN_S = 300.0
HALF_X = 105.0 / 2  # halfway, Law 1 as the engine plays it (docs/GROUNDING.md, L1)
PLACES = 2


def build(radar: dict, fps: float) -> dict:
    """The territory bins for a radar.json body (ninety/radar.py) whose footage runs at `fps`."""
    if radar.get("source") != SOURCE:
        raise ValueError(f"radar source {radar.get('source')!r}: territory reads only vision's tracked ball")
    seen = {v["frame"] for v in radar.get("views", []) if v.get("ball_seen")}
    dt = 1.0 / fps
    bins: dict[int, dict[str, float]] = {}
    for f in radar["frames"]:
        if f.get("source") != SOURCE:
            raise ValueError(f"frame {f.get('frame')}: source {f.get('source')!r}")
        if f["frame"] not in seen or f.get("ball") is None:
            continue
        b = bins.setdefault(math.floor(f["t"] / BIN_S), {"home_s": 0.0, "away_s": 0.0, "seen_s": 0.0})
        b["seen_s"] += dt
        x = f["ball"]["x"]
        if x > HALF_X:
            b["home_s"] += dt
        elif x < HALF_X:
            b["away_s"] += dt
    out = []
    for n in sorted(bins):
        b = bins[n]
        both = b["home_s"] + b["away_s"]
        out.append({
            "t": n * BIN_S,
            "t_end": (n + 1) * BIN_S,
            "home_s": round(b["home_s"], PLACES),
            "away_s": round(b["away_s"], PLACES),
            "seen_s": round(b["seen_s"], PLACES),
            "home": round(b["home_s"] / both, 3) if both > 0 else None,
        })
    return {"format": FORMAT, "source": SOURCE, "bin_s": BIN_S, "bins": out}
