"""How far from the truth event detection puts players and the ball on the pitch.

    uv run python -m ninety.eval.pitch_score --frames <clip>/frames.jsonl \\
        --observations <observations.jsonl> --report <report.json>

Grading, so it reads the answer key. Each player detection at or above the 0.5 score threshold on
a frame whose camera fit is trusted is paired with the true player whose box overlaps it most
(IoU at least 0.5, the pixel scorer's player rule, docs/EVALUATION.md); its pitch position is
compared with that player's. The ball is compared on frames where it is on the ground (centre at
or under 0.5 m, about knee height: EVALUATION.md's "in the air" group is above it), detected within
5 px of its true centre (the pixel scorer's ball rule): an airborne ball is placed on the ground by
design (ninety/vision/observe.py) and is reported apart.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

# The pixel scorer's rule, imported so the two cannot drift apart.
from ninety.eval.vision_score import BALL_DISTANCE_PX as BALL_PX
from ninety.eval.vision_score import DEFAULT_THRESHOLD as SCORE_MIN
from ninety.eval.vision_score import IN_AIR_Z as GROUND_Z  # the one 0.5 m cut-off
from ninety.eval.vision_score import PLAYER_IOU


def _iou(a, b) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - ix * iy
    return ix * iy / union if union > 0 else 0.0


def _summary(errs: list[float]) -> dict:
    if not errs:
        return {"n": 0, "median_m": None, "p90_m": None, "max_m": None}
    s = sorted(errs)
    q = lambda p: round(s[min(len(s) - 1, int(p * (len(s) - 1)))], 3)  # noqa: E731
    return {"n": len(s), "median_m": q(0.5), "p90_m": q(0.9), "max_m": round(s[-1], 3)}


def errors(
    frames: list[dict], observations: list[dict]
) -> tuple[list[float], list[float], list[float], list[int]]:
    """The raw position errors (players, ball on the ground, ball in the air) and the frames whose
    camera was not trusted: what `score` summarises, kept apart so several clips can be pooled."""
    truth = {f["frame"]: f for f in frames}
    players, ball_ground, ball_air = [], [], []
    not_ok = []
    for o in observations:
        t = truth.get(o["frame"])
        if t is None:
            raise ValueError(f"observed frame {o['frame']} is not in the truth frames")
        if not o["camera"]["ok"]:
            not_ok.append(o["frame"])
            continue
        for d in o["players"]:
            if d["score"] < SCORE_MIN or d["x"] is None:
                continue
            labelled = [p for p in t["players"] if p.get("bbox") and p.get("visibility", 0) > 0]
            best = max(labelled, key=lambda p: _iou(p["bbox"], d["bbox"]), default=None)
            if best is not None and _iou(best["bbox"], d["bbox"]) >= PLAYER_IOU:
                players.append(math.hypot(d["x"] - best["x"], d["y"] - best["y"]))
        tb = t["ball"]
        balls = [b for b in o["ball"] if b["score"] >= SCORE_MIN and b["x"] is not None]
        if not balls or not tb.get("bbox") or tb.get("visibility", 0) <= 0:
            continue
        b = max(balls, key=lambda b: b["score"])
        cx, cy = (b["bbox"][0] + b["bbox"][2]) / 2, (b["bbox"][1] + b["bbox"][3]) / 2
        if math.hypot(cx - tb["center_px"][0], cy - tb["center_px"][1]) > BALL_PX:
            continue
        err = math.hypot(b["x"] - tb["x"], b["y"] - tb["y"])
        # The vision scorers' boundary: strictly above the cut-off is in the air (EVALUATION.md).
        (ball_air if tb["z"] > GROUND_Z else ball_ground).append(err)
    return players, ball_ground, ball_air, not_ok


def score(frames: list[dict], observations: list[dict]) -> dict:
    players, ball_ground, ball_air, not_ok = errors(frames, observations)
    return {
        "frames": {"observed": len(observations), "camera_ok": len(observations) - len(not_ok),
                   "camera_not_ok": not_ok},
        "players": _summary(players),
        "ball_on_ground": _summary(ball_ground),
        "ball_in_the_air": _summary(ball_air),
        "rules": {"score_min": SCORE_MIN, "player_iou": PLAYER_IOU, "ball_px": BALL_PX,
                  "ground_z_m": GROUND_Z},
    }


def _read(path: Path) -> list[dict]:
    return [json.loads(x) for x in path.read_text().splitlines() if x.strip()]


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Pitch-position error of event detection's observations.")
    ap.add_argument("--frames", type=Path, required=True)
    ap.add_argument("--observations", type=Path, required=True)
    ap.add_argument("--report", type=Path, required=True)
    a = ap.parse_args(argv)
    report = score(_read(a.frames), _read(a.observations))
    report["inputs"] = {"frames": str(a.frames), "observations": str(a.observations)}
    a.report.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({k: report[k] for k in ("players", "ball_on_ground", "ball_in_the_air")}))


if __name__ == "__main__":
    main()
