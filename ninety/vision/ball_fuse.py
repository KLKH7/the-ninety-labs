"""The ball from three cameras: the broadcast first, the tactical lenses where it has none.

    uv run python -m ninety.vision.ball_fuse --tactical <fused observations.jsonl> \\
        --broadcast <observations.jsonl> --out <observations.jsonl>

The broadcast camera follows the ball, so the ball is large in its picture (about 2.5 to 7.5 px at
the detector's input); on the fixed tactical lenses, which see the whole pitch, it is a few pixels.
Players come from the tactical views (ninety.vision.fuse), which see every one of them; the ball
comes from the broadcast when it can:

- on a frame whose broadcast camera is trusted (`camera.ok`, the per-frame fit of observe) and that
  has a placed broadcast ball at the scorer's 0.5, the ball list is the broadcast's balls. A
  tactical ball within GATE_M of one of them is the same ball seen twice: they merge, one to one,
  nearest first, at the two places weighted by the inverse of each source's mean squared error. The
  other tactical balls are dropped: the source trusted on this frame has spoken;
- on any other frame (a cut, a replay, the ball out of the broadcast's picture, an untrusted fit),
  the ball list is the tactical views' own.

GATE_M and the weights come from each source's measured ball position error (the 99th percentile
and the root mean square, on the validation clips: docs/eval/ball-three-cams/PLAN.md). Two
measurements that each miss by up to r_b and r_t are within sqrt(r_b^2 + r_t^2) of each other.

Each output line is the tactical line with its ball list replaced, so tracking and events read it
unchanged; `camera.ok` is the tactical camera's, or the broadcast's on a frame whose ball it gave.
Each ball names its `source` ("broadcast" or "tactical") and keeps its `view`, so pixel checks
compare boxes from one picture only (track.ball_path). Reads only observations: the live path.
"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from pathlib import Path

from ninety.vision.track import SCORE_MIN

BROADCAST = "broadcast"


@dataclass(frozen=True)
class Precision:
    """A source's measured ball position error on the pitch, metres: 99th percentile and RMS."""

    p99_m: float
    rms_m: float


def gate_m(broadcast: Precision, tactical: Precision) -> float:
    return math.hypot(broadcast.p99_m, tactical.p99_m)


def _placed(balls: list[dict]) -> list[dict]:
    return [b for b in balls if b["score"] >= SCORE_MIN and b.get("x") is not None]


def _merge(b: dict, t: dict, wb: float, wt: float) -> dict:
    x = (wb * b["x"] + wt * t["x"]) / (wb + wt)
    y = (wb * b["y"] + wt * t["y"]) / (wb + wt)
    return b | {"x": round(x, 3), "y": round(y, 3), "merged": t.get("views", [t.get("view")])}


def fuse_ball_frame(tactical: dict, broadcast: dict | None, bp: Precision, tp: Precision) -> dict:
    """One frame: the tactical line (ninety.vision.fuse) with its ball list chosen as the module
    docstring says, from the broadcast line of the same frame (observe), if there is one."""
    out = tactical | {"camera": dict(tactical["camera"])}
    tac = [b | {"source": "tactical"} for b in tactical["ball"]]
    mine = _placed(broadcast["ball"]) if broadcast is not None and broadcast["camera"]["ok"] else []
    out["camera"]["broadcast_ok"] = bool(broadcast is not None and broadcast["camera"]["ok"])
    if not mine:
        out["ball"] = tac
        out["camera"]["ball_from"] = "tactical"
        return out
    gate = gate_m(bp, tp)
    wb, wt = 1 / bp.rms_m ** 2, 1 / tp.rms_m ** 2
    cands = _placed(tac)
    pairs = sorted((math.dist((b["x"], b["y"]), (t["x"], t["y"])), i, j)
                   for i, b in enumerate(mine) for j, t in enumerate(cands))
    used_b, used_t, merged = set(), set(), {}
    for d, i, j in pairs:
        if d > gate or i in used_b or j in used_t:
            continue
        used_b.add(i)
        used_t.add(j)
        merged[i] = _merge(mine[i], cands[j], wb, wt)
    out["ball"] = sorted((merged.get(i, b) | {"source": BROADCAST, "view": BROADCAST}
                          for i, b in enumerate(mine)), key=lambda b: -b["score"])
    out["camera"]["ok"] = True  # the ball's camera is trusted; players keep their own places
    out["camera"]["ball_from"] = BROADCAST
    return out


def fuse_ball(tactical: list[dict], broadcast: list[dict], bp: Precision, tp: Precision) -> list[dict]:
    """Every tactical line with its ball chosen; the broadcast lines are matched by frame (a
    broadcast missing a frame leaves that frame to the tactical views)."""
    by_frame = {r["frame"]: r for r in broadcast}
    return [fuse_ball_frame(r, by_frame.get(r["frame"]), bp, tp) for r in tactical]


def tactical_only(tactical: list[dict]) -> list[dict]:
    """The tactical lines as they are, each ball tagged with its source (source (b) of the plan)."""
    return [r | {"ball": [b | {"source": "tactical"} for b in r["ball"]]} for r in tactical]


def broadcast_ball(tactical: list[dict], broadcast: list[dict]) -> list[dict]:
    """The tactical players with the broadcast's ball alone, never the tactical one (source (a))."""
    by_frame = {r["frame"]: r for r in broadcast}
    out = []
    for r in tactical:
        b = by_frame.get(r["frame"])
        ok = bool(b is not None and b["camera"]["ok"])
        balls = [x | {"source": BROADCAST, "view": BROADCAST} for x in (b["ball"] if ok else [])]
        out.append(r | {"ball": balls, "camera": dict(r["camera"]) | {"ok": r["camera"]["ok"] or ok}})
    return out


def main(argv: list[str] | None = None) -> None:
    from ninety.vision.track import read_observations

    ap = argparse.ArgumentParser(description="Take the ball from the broadcast, else the tactical views.")
    ap.add_argument("--tactical", type=Path, required=True, help="the fused views' observations")
    ap.add_argument("--broadcast", type=Path, required=True, help="the broadcast's observations")
    ap.add_argument("--precision", type=Path, required=True,
                    help="the measured precision.json (docs/eval/ball-three-cams)")
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args(argv)
    m = json.loads(a.precision.read_text())
    bp, tp = (Precision(m[k]["p99_m"], m[k]["rms_m"]) for k in ("broadcast", "tactical"))
    rows = fuse_ball(read_observations(a.tactical), read_observations(a.broadcast), bp, tp)
    with open(a.out, "w", encoding="utf-8", newline="\n") as f:
        for r in rows:
            f.write(json.dumps(r, separators=(",", ":")) + "\n")
    used = sum(r["camera"].get("ball_from") == BROADCAST for r in rows)
    print(json.dumps({"out": str(a.out), "frames": len(rows), "ball_from_broadcast": used,
                      "gate_m": round(gate_m(bp, tp), 3)}))


if __name__ == "__main__":
    main()
