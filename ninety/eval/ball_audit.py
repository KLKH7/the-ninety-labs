"""Vision Auditor, round 1: ball recall by context: dead or moving, at a line or away from one.

    uv run python -m ninety.eval.ball_audit --pairs pairs.jsonl --out docs/eval/ball-audit.json

`pairs.jsonl` holds one validation clip per line, `{"clip", "frames", "observations"}`: its
answer key's frames.jsonl and the live path's observations.jsonl for it. Grading, so it reads the
answer key; a test seed is refused. The rule is docs/eval/ball-audit-plan.md's, fixed before any
count:
- a ball to find is a frame whose true ball has a visible box (vision_score's own rule);
- it is found when a detected ball at or above the scorer's threshold lies within the scorer's
  5 px of its true centre;
- it is dead when the true ball moves under DEAD_MPS (one frame either side);
- it is at a line when it is within LINE_M of the nearest marking, arcs included.
"""

from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from pathlib import Path

from ninety.eval.attribution_derive import refused
from ninety.eval.event_score import wilson
from ninety.eval.vision_score import BALL_DISTANCE_PX, DEFAULT_THRESHOLD, _visible
from ninety.eval.vision_score import IN_AIR_Z as GROUND_Z
from ninety.vision.pitch import PITCH_X, PITCH_Y, pitch_polylines

DEAD_MPS = 0.1  # the plan's: the answer key is exact, and a ball set for a restart does not move
LINE_M = 2.0  # the plan's
FPS = 25
GROUPS = ("dead at a line", "dead away from lines", "moving at a line", "moving away from lines")


def _segments() -> list[tuple[tuple[float, float], tuple[float, float]]]:
    return [(a, b) for pl in pitch_polylines() for a, b in zip(pl[:-1], pl[1:], strict=True)]


SEGMENTS = _segments()


def line_distance(x: float, y: float) -> float:
    """Metres from (x, y) to the nearest marking."""
    best = math.inf
    for (ax, ay), (bx, by) in SEGMENTS:
        dx, dy = bx - ax, by - ay
        n = dx * dx + dy * dy
        u = 0.0 if n == 0 else max(0.0, min(1.0, ((x - ax) * dx + (y - ay) * dy) / n))
        best = min(best, math.hypot(x - ax - u * dx, y - ay - u * dy))
    return best


def place(x: float, y: float) -> str:
    """Which marking a ball at a line is at, for the engine request."""
    near_x = min(x, PITCH_X - x) <= LINE_M
    near_y = min(y, PITCH_Y - y) <= LINE_M
    if near_x and near_y:
        return "corner arc"
    if near_y:
        return "touchline"
    if near_x:
        return "goal line"
    if abs(x - PITCH_X / 2) <= 9.15 + LINE_M:
        return "halfway and centre circle"
    return "penalty and goal areas"


def found(ball: dict, detections: list[dict]) -> bool:
    cx, cy = ball["center_px"]
    for d in detections:
        if d.get("score", 0) < DEFAULT_THRESHOLD:
            continue
        x0, y0, x1, y1 = d["bbox"]
        if math.hypot((x0 + x1) / 2 - cx, (y0 + y1) / 2 - cy) <= BALL_DISTANCE_PX:
            return True
    return False


def _jsonl(path: Path) -> list[dict]:
    return [json.loads(x) for x in path.read_text().splitlines() if x.strip()]


def audit_clip(frames: list[dict], observations: list[dict]) -> list[dict]:
    """One row per ball to find: its group, place, size and whether it was found."""
    obs = {r["frame"]: r for r in observations}
    by_frame = {f["frame"]: f for f in frames}
    rows = []
    for f in frames:
        b = f["ball"]
        if not _visible(b) or f["frame"] not in obs or "center_px" not in b:
            continue
        before, after = by_frame.get(f["frame"] - 1), by_frame.get(f["frame"] + 1)
        if not before or not after:
            continue
        moved = math.hypot(after["ball"]["x"] - before["ball"]["x"], after["ball"]["y"] - before["ball"]["y"])
        speed = moved * FPS / 2
        dead = speed < DEAD_MPS
        at_line = line_distance(b["x"], b["y"]) <= LINE_M
        group = GROUPS[(0 if dead else 2) + (0 if at_line else 1)]
        x0, y0, x1, y1 = b["bbox"]
        rows.append({"frame": f["frame"], "group": group, "place": place(b["x"], b["y"]) if at_line else None,
                     "px": round(max(x1 - x0, y1 - y0), 1), "grounded": b.get("z", 0.0) <= GROUND_Z,
                     "found": found(b, obs[f["frame"]]["ball"])})
    return rows


def summary(rows: list[dict]) -> dict:
    out = {}
    for g in GROUPS:
        mine = [r for r in rows if r["group"] == g]
        k = sum(r["found"] for r in mine)
        out[g] = {"n": len(mine), "found": k, "recall": round(k / len(mine), 3) if mine else None,
                  "ci95": wilson(k, len(mine))}
    return out


def breakdown(rows: list[dict], key) -> dict:
    by = defaultdict(list)
    for r in rows:
        by[key(r)].append(r)
    return {k: {"n": len(v), "found": sum(r["found"] for r in v),
                "recall": round(sum(r["found"] for r in v) / len(v), 3)} for k, v in sorted(by.items())}


def size_band(r: dict) -> str:
    px = r["px"]
    return "under 10 px" if px < 10 else "10-20 px" if px < 20 else "20 px or more"


def height(r: dict) -> str:
    return f"{r['group']}, {'on the ground' if r['grounded'] else 'held or up'}"


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--pairs", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args(argv)
    pairs = _jsonl(a.pairs)
    seeds = {int(p["clip"].removeprefix("seed").split("-")[0]) for p in pairs}
    if any(refused(s) and not 910001 <= s <= 910008 for s in seeds):
        raise SystemExit(f"refused: a test seed among {sorted(seeds)}")
    rows, per_clip = [], {}
    for p in pairs:
        r = audit_clip(_jsonl(Path(p["frames"])), _jsonl(Path(p["observations"])))
        rows += r
        per_clip[p["clip"]] = len(r)
    dead_line = [r for r in rows if r["group"] == "dead at a line"]
    body = {
        "rule": "docs/eval/ball-audit-plan.md", "dead_mps": DEAD_MPS, "line_m": LINE_M,
        "clips": len(pairs), "balls": len(rows), "groups": summary(rows),
        "dead_at_a_line_by_place": breakdown(dead_line, lambda r: r["place"]),
        "dead_at_a_line_by_size": breakdown(dead_line, size_band),
        "moving_away_by_size": breakdown([r for r in rows if r["group"] == GROUPS[3]], size_band),
        # Post hoc (not in the plan): a dead ball on the ground, set for a restart, against one held
        # by a keeper or otherwise up (above the scorer's 0.5 m), which is a different picture.
        "dead_by_height_post_hoc": breakdown([r for r in rows if r["group"].startswith("dead")], height),
        "dead_at_a_line_by_place_and_height_post_hoc": breakdown(
            dead_line, lambda r: f"{r['place']}, {'on the ground' if r['grounded'] else 'held or up'}"),
        "per_clip": per_clip,
    }
    a.out.write_text(json.dumps(body, indent=1) + "\n")
    print(json.dumps(body["groups"], indent=1))


if __name__ == "__main__":
    main()
