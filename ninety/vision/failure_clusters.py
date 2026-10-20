"""The Vision Auditor's failure clusters: which situations hide what the detector misses.

    uv run python -m ninety.vision.failure_clusters <val clips>/seed* --detections detections-ours-v3.jsonl \
        --round round1 --out runs/round1/clusters.json

Reads training-side clips only (validation clips are training seeds held out from fitting): every
clip must be a training seed, so the fixed test set's per-frame results never steer what is
rendered next. The test set says how good the detector is; it never says what to render.

Each label the detector could have found (visibility above zero, as the scorer counts) is matched
with the scorer's own rule (ninety.eval.vision_score.match). Each one is then put in exactly one
situation, decided from the ground truth's geometry, first rule that applies:

- "behind the keeper": a goalkeeper whose box overlaps it stands nearer the lens, or (ball only)
  a goalkeeper holding, diving or throwing is within KEEPER_M of the ball.
- "behind a player in a crowd": a player whose box overlaps it stands nearer the lens, and at
  least CROWD players are within CROWD_RADIUS_M of it (ninety.render.scene.crowding's radius).
- "behind a player": a player whose box overlaps it stands nearer the lens.
- "behind the goal frame": (ball only) within the goal mouth's reach of a goal line.
- "off the pitch, by the boards": (ball only) outside the lines, where boards and the scorebug sit.
- "at the frame's edge": its box touches the image border.
- "no occluder found": none of the above; listed, never dropped.

Kit contrast is the clip's own knob, reported beside every situation, not a situation itself.

"Nearer the lens" is the horizontal distance from the camera position recorded in the frame. The
rules use positions and boxes only, so they need no pixels and give the same answer on any machine.

Writes the Data agent's handoff (ninety/agents/data_agent.py): a cluster per situation with misses
among mostly hidden labels, and the render settings the renderer has for it. A situation with no
render setting yet goes under "unmapped", left for a person to decide, so the Data agent never
spends clips on it as ordinary footage.
"""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter, defaultdict
from pathlib import Path

from ninety.eval.vision_score import (
    DEFAULT_THRESHOLD,
    boundary_group,
    flatten,
    frames_run,
    load_jsonl,
    match,
    visibility_group,
)
from ninety.render.splits import split_of

PITCH_X, PITCH_Y = 105.0, 68.0  # ninety/sim/engine.py
GOAL_HALF_M = 3.66  # half the goal's width, 7.32 m (Law 1)
GOAL_REACH_M = 2.0  # the frame's depth plus the net behind it (web/render/render.js draws 2 m)
KEEPER_M = 2.0  # a keeper's reach: arms over the ball, near enough to cover it
KEEPER_ACTIONS = ("hands", "dive", "throw")
CROWD = 3  # three or more players within the radius: the definition `occlusion=crowded` ranks by
CROWD_RADIUS_M = 4.0  # ninety.render.scene.crowding's default radius

SITUATIONS = (
    "behind the keeper",
    "behind a player in a crowd",
    "behind a player",
    "behind the goal frame",
    "off the pitch, by the boards",
    "at the frame's edge",
    "no occluder found",
)

# Situation -> the render settings that make more of it, from what the renderer has today.
# `occlusion=crowded` picks the window where players most often stand on the lens's line to the
# ball (ninety.render.scene.crowded_start): the situation the two player rules describe.
# `occlusion=keeper` picks the window where a goalkeeper most often handles or dives
# (ninety.render.scene.keeper_start). Nothing yet aims a window at the goal frame, the boards or
# the frame's edge.
RENDER = {
    "behind a player in a crowd": {"occlusion": "crowded"},
    "behind a player": {"occlusion": "crowded"},
    "behind the keeper": {"occlusion": "keeper"},
    "behind the goal frame": None,
    "off the pitch, by the boards": None,
    "at the frame's edge": None,
    "no occluder found": None,
}


def _overlap(a, b) -> bool:
    return min(a[2], b[2]) > max(a[0], b[0]) and min(a[3], b[3]) > max(a[1], b[1])


def _reach(camera: dict, x: float, y: float) -> float:
    cx, cy = camera["position"][0], camera["position"][1]
    return math.hypot(x - cx, y - cy)


def labels_with_context(frames: list[dict], run: set[int]) -> list[dict]:
    """Scorer labels (visibility above zero, on frames the detector ran), each with its object."""
    out = []
    for row in frames:
        frame = int(row["frame"])
        if frame not in run:
            continue
        objects = [("player", p) for p in row["players"]] + [("ball", row["ball"])]
        for cls, obj in objects:
            if obj.get("bbox") is None or float(obj.get("visibility", 1.0)) <= 0:
                continue
            out.append(
                {"frame": frame, "cls": cls, "bbox": obj["bbox"], "visibility": float(obj["visibility"]),
                 "obj": obj, "row": row}
            )
    return out


def situation(label: dict) -> str:
    row, obj, cls = label["row"], label["obj"], label["cls"]
    cam = row["camera"]
    reach = _reach(cam, obj["x"], obj["y"])
    occluders = [
        p for p in row["players"]
        if p is not obj and p.get("bbox") is not None and float(p.get("visibility", 0)) > 0
        and _overlap(p["bbox"], label["bbox"]) and _reach(cam, p["x"], p["y"]) < reach
    ]
    if cls == "ball":
        keepers_near = [
            p for p in row["players"]
            if p["role"] == "GK" and p["action"] in KEEPER_ACTIONS
            and math.hypot(p["x"] - obj["x"], p["y"] - obj["y"]) <= KEEPER_M
        ]
    else:
        keepers_near = []
    if keepers_near or any(p["role"] == "GK" for p in occluders):
        return "behind the keeper"
    if occluders:
        near = sum(
            1 for p in row["players"]
            if p is not obj and math.hypot(p["x"] - obj["x"], p["y"] - obj["y"]) <= CROWD_RADIUS_M
        )
        return "behind a player in a crowd" if near >= CROWD else "behind a player"
    if cls == "ball":
        x, y = obj["x"], obj["y"]
        to_line = min(abs(x), abs(x - PITCH_X))
        if to_line <= GOAL_REACH_M and abs(y - PITCH_Y / 2) <= GOAL_HALF_M + 0.5:
            return "behind the goal frame"
        if not (0 <= x <= PITCH_X and 0 <= y <= PITCH_Y):
            return "off the pitch, by the boards"
    if boundary_group(label["bbox"], cam) == "edge-touching":
        return "at the frame's edge"
    return "no occluder found"


def audit(clips: list[Path], detections_name: str, threshold: float = DEFAULT_THRESHOLD) -> dict:
    """Per class, visibility group, situation and kit contrast: labels and misses."""
    table: dict = defaultdict(lambda: {"labels": 0, "missed": 0})
    seeds, checkpoints = [], set()
    for clip in clips:
        meta = json.loads((clip / "clip.json").read_text())
        seed = int(meta["seed"])
        if split_of(seed) != "train":
            raise ValueError(
                f"{clip}: seed {seed} is in the {split_of(seed)} split; clusters read training seeds only"
            )
        frames = load_jsonl(clip / "frames.jsonl")
        det_rows = load_jsonl(clip / detections_name)
        seeds.append(seed)
        checkpoints.update(str(r.get("model", {}).get("checkpoint")) for r in det_rows)
        run = frames_run(det_rows)
        labels = labels_with_context(frames, run)
        dets = [d for d in flatten(det_rows) if float(d.get("score", 0.0)) >= threshold]
        found = {p["truth"] for p in match(labels, dets, threshold=threshold)}
        contrast = meta["params"]["kit_contrast"]
        for i, label in enumerate(labels):
            key = (label["cls"], visibility_group(label["visibility"]), situation(label), contrast)
            table[key]["labels"] += 1
            table[key]["missed"] += i not in found
    rows = [
        {"cls": c, "visibility": v, "situation": s, "kit_contrast": k, **n}
        for (c, v, s, k), n in sorted(table.items())
    ]
    if len(checkpoints) > 1:
        raise ValueError(f"detections come from more than one checkpoint: {sorted(checkpoints)}")
    return {
        "threshold": threshold, "clips": len(clips), "seeds": sorted(seeds),
        "detections": detections_name, "checkpoint": next(iter(checkpoints), None), "rows": rows,
    }


def summarize(rows: list[dict], cls: str, group: str = "mostly hidden") -> list[dict]:
    """Labels, misses and recall per situation for one class and visibility group, most misses first."""
    by: dict = defaultdict(Counter)
    for r in rows:
        if r["cls"] == cls and r["visibility"] == group:
            by[r["situation"]]["labels"] += r["labels"]
            by[r["situation"]]["missed"] += r["missed"]
            by[r["situation"]][f"missed_{r['kit_contrast']}"] += r["missed"]
    out = []
    for s in SITUATIONS:
        n = by.get(s)
        if not n or not n["labels"]:
            continue
        out.append({
            "situation": s, "labels": n["labels"], "missed": n["missed"],
            "recall": round(1 - n["missed"] / n["labels"], 3),
            "missed_low_contrast": n["missed_low"],
        })
    return sorted(out, key=lambda r: -r["missed"])


def handoff(report: dict, run: str) -> dict:
    """The Data agent's input: one cluster per (class, situation) with mostly hidden misses.

    Only situations with a render setting go in `clusters`, which the Data agent splits the budget
    over. The rest go in `unmapped`: the Data agent would render a cluster with no setting as an
    ordinary clip, which is not more of that situation.
    """
    clusters, unmapped = [], []
    for cls in ("ball", "player"):
        for r in summarize(report["rows"], cls):
            if r["missed"]:
                render = RENDER[r["situation"]]
                entry = {"name": f"{cls} mostly hidden, {r['situation']}", "misses": r["missed"]}
                if render is None:
                    unmapped.append(entry)
                else:
                    clusters.append({**entry, "render": render})
    return {"round": run, "clusters": clusters, "unmapped": unmapped}


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Failure clusters on training-side clips, for the Data agent.")
    ap.add_argument("clips", nargs="+", type=Path)
    ap.add_argument("--detections", required=True, help="detections file name inside each clip folder")
    ap.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD)
    ap.add_argument("--round", required=True)
    ap.add_argument("--out", type=Path, required=True, help="clusters.json (the report goes beside it)")
    a = ap.parse_args(argv)
    report = audit(a.clips, a.detections, a.threshold)
    report["summary"] = {cls: summarize(report["rows"], cls) for cls in ("ball", "player")}
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.with_name("audit.json").write_text(json.dumps(report, indent=2) + "\n")
    h = handoff(report, a.round)
    a.out.write_text(json.dumps(h, indent=2) + "\n")
    for cls, rows in report["summary"].items():
        print(f"{cls}, mostly hidden:")
        for r in rows:
            print(f"  {r['missed']:4d} of {r['labels']:4d} missed  recall {r['recall']:.3f}  {r['situation']}"
                  f"  (low contrast {r['missed_low_contrast']})")
    print(f"{len(h['clusters'])} clusters written to {a.out}")


if __name__ == "__main__":
    main()
