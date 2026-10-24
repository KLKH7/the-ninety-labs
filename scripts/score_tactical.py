"""Score ours-freeze against ours-tactical on the tactical views, as pre-registered
(docs/eval/finetune-tactical/PLAN.md, "Scoring"): one run each, at the commit this file is in.

    uv run python scripts/score_tactical.py detect <clip dirs> --split validation|test \\
        --model ours-freeze --weights <checkpoint> --out runs/tactical1/score
    uv run python scripts/score_tactical.py score <clip dirs> --split validation|test \\
        --out runs/tactical1/score > report.json

`detect` runs the live path's tiled detection (ninety/vision/detect.py with --tiles: tiles.grid and
tiles.merge, #230) on every 5th frame of each view, views/tac-l and views/tac-r, and writes
<out>/<split>/<model>/seed<N>-<view>.jsonl. It reads the images and the frame index only.

`score` grades those detections with vision_score's own rule (vision_score.match at threshold 0.5:
a player at IoU 0.5, the ball within 5 px). Each object is counted once per frame, in the view
whose half holds it (tac-l for x < 52.5), when it is a label there (a box with some of it visible).
Recall is reported overall and by pitch zone: thirds along the pitch (x 0-35, 35-70, 70-105 m) by
halves across it (near y 0-34, far 34-68 m), each with its Wilson 95% interval. Precision is over
every detection at or above 0.5 in either view against every label in that view. Coverage is the
share of on-pitch players and balls that are a label in at least one view.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

VIEWS = ("tac-l", "tac-r")
STRIDE = 5  # every 5th frame, as validation and test are scored (PLAN.md)
THRESHOLD = 0.5
THIRDS = (35.0, 70.0)
HALFWAY_X, HALFWAY_Y = 52.5, 34.0


def zone(x: float, y: float) -> str:
    third = "x0-35" if x < THIRDS[0] else ("x35-70" if x < THIRDS[1] else "x70-105")
    return f"{third}/{'near' if y < HALFWAY_Y else 'far'}"


def own_view(x: float) -> str:
    return "tac-l" if x < HALFWAY_X else "tac-r"


def wilson(k: int, n: int, z: float = 1.96) -> list[float] | None:
    if n == 0:
        return None
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [round(c - h, 4), round(c + h, 4)]


def detect(args) -> None:
    from ninety.vision.detect import detect_rows, frame_rows, labels_for, trained_resolution
    from ninety.vision.detections import write_detections
    from ninety.vision.model import load, model

    det = load(args.weights, resolution=trained_resolution(args.weights))
    label = labels_for(args.model, det.class_names)
    field = model(args.model)
    out = args.out / args.split / args.model
    out.mkdir(parents=True, exist_ok=True)
    for clip in args.clips:
        seed = json.loads((clip / "clip.json").read_text())["seed"]
        for view in VIEWS:
            target = out / f"seed{seed}-{view}.jsonl"
            if target.exists():
                continue
            rows = detect_rows(det, frame_rows(clip / "views" / view, STRIDE), label, field, 8, tiles=True)
            write_detections(target, rows)
            print(json.dumps({"seed": seed, "view": view, "frames": len(rows)}), flush=True)


def _labels(rows: list[dict]) -> list[dict]:
    """Scorer labels with each object's pitch position: players and the ball with something visible."""
    from ninety.eval.vision_score import _visible

    out = []
    for r in rows:
        for p in r["players"]:
            if _visible(p):
                out.append({"frame": int(r["frame"]), "cls": "player", "bbox": p["bbox"],
                            "visibility": float(p["visibility"]), "x": p["x"], "y": p["y"]})
        b = r["ball"]
        if _visible(b):
            out.append({"frame": int(r["frame"]), "cls": "ball", "bbox": b["bbox"],
                        "visibility": float(b["visibility"]), "x": b["x"], "y": b["y"]})
    return out


def score(args) -> dict:
    from ninety.eval.vision_score import flatten, load_jsonl, match

    models = sorted(d.name for d in (args.out / args.split).iterdir() if d.is_dir())
    report: dict = {"split": args.split, "clips": [], "threshold": THRESHOLD, "stride": STRIDE, "models": {}}
    coverage = {"player": [0, 0], "ball": [0, 0]}
    for m in models:
        counts = {"recall": {}, "zones": {}, "precision": {"player": [0, 0], "ball": [0, 0]}}
        for clip in args.clips:
            seed = json.loads((clip / "clip.json").read_text())["seed"]
            if m == models[0]:
                report["clips"].append(seed)
            views = {}
            for view in VIEWS:
                frames = load_jsonl(clip / "views" / view / "frames.jsonl")[::STRIDE]
                dets = flatten(load_jsonl(args.out / args.split / m / f"seed{seed}-{view}.jsonl"))
                ran = {int(f["frame"]) for f in frames}
                dets = [d for d in dets if d["frame"] in ran]
                labels = _labels(frames)
                pairs = match(labels, dets, THRESHOLD)
                hit = {p["truth"] for p in pairs}
                views[view] = (frames, labels, hit)
                for cls in ("player", "ball"):
                    shown = [d for d in dets if d["cls"] == cls and float(d.get("score", 0)) >= THRESHOLD]
                    tp = sum(1 for p in pairs if p["cls"] == cls)
                    counts["precision"][cls][0] += tp
                    counts["precision"][cls][1] += len(shown)
            for view, (_frames, labels, hit) in views.items():
                for ti, lab in enumerate(labels):
                    if own_view(lab["x"]) != view:
                        continue  # counted once, in the view whose half holds it
                    found = ti in hit
                    for key, table in ((lab["cls"], counts["recall"]),
                                       (f"{lab['cls']}:{zone(lab['x'], lab['y'])}", counts["zones"])):
                        table.setdefault(key, [0, 0])
                        table[key][0] += found
                        table[key][1] += 1
            if m == models[0]:  # coverage is the views', the same for every model
                seen = {v: {(lab["frame"], lab["cls"], lab["x"], lab["y"]) for lab in views[v][1]}
                        for v in VIEWS}
                for r in views["tac-l"][0]:
                    objs = [("player", p["x"], p["y"]) for p in r["players"]]
                    objs.append(("ball", r["ball"]["x"], r["ball"]["y"]))
                    for cls, x, y in objs:
                        if 0 <= x <= 105 and 0 <= y <= 68:
                            key = (int(r["frame"]), cls, x, y)
                            coverage[cls][0] += any(key in seen[v] for v in VIEWS)
                            coverage[cls][1] += 1
        report["models"][m] = {
            "recall": {k: {"k": a, "n": n, "recall": round(a / n, 4) if n else None, "ci95": wilson(a, n)}
                       for k, (a, n) in sorted(counts["recall"].items())},
            "recall_by_zone": {k: {"k": a, "n": n, "recall": round(a / n, 4) if n else None,
                                   "ci95": wilson(a, n)} for k, (a, n) in sorted(counts["zones"].items())},
            "precision": {k: {"tp": a, "shown": n, "precision": round(a / n, 4) if n else None,
                              "ci95": wilson(a, n)} for k, (a, n) in counts["precision"].items()},
        }
    report["coverage"] = {k: {"seen": a, "on_pitch": n, "share": round(a / n, 4) if n else None}
                          for k, (a, n) in coverage.items()}
    return report


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("command", choices=("detect", "score"))
    ap.add_argument("clips", nargs="+", type=Path)
    ap.add_argument("--split", choices=("validation", "test"), required=True)
    ap.add_argument("--model")
    ap.add_argument("--weights")
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args(argv)
    if a.command == "detect":
        if not (a.model and a.weights):
            ap.error("detect needs --model and --weights")
        detect(a)
    else:
        print(json.dumps(score(a), indent=1))


if __name__ == "__main__":
    main()
