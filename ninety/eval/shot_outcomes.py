"""Shot outcomes from video, measured offline (docs/eval/shot-outcomes-plan.md).

    # the position errors the rules use, on validation clips only
    uv run python -m ninety.eval.shot_outcomes precision --clips <render run>/train \\
        --observations <dir of observations-seed<N>.jsonl or seed<N>.jsonl> --seeds 108 109 ... \\
        --out docs/eval/shot-outcomes.json

    # goals and saves, scored once at a frozen commit
    uv run python -m ninety.eval.shot_outcomes score --clips <test clips> --detected <dir of
        detected-seed<N>.jsonl> --out <report.json>

The answer key is read here, offline, and nowhere on the live path. A true save is a shot whose
outcome is `on_target` (the engine's `close_shot`: the keeper stopped a ball going in); a detected
save is a detected shot with that outcome. A detected goal matches a true goal of the same team
within the event scorer's window (WINDOW_S); a detected save a true save the same way.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from ninety.eval.event_score import WINDOW_S, git_commit, wilson
from ninety.vision.track import ball_path, read_observations

GOAL_BAND_M = 25.0  # the plan: within 25 m of a goal line
CENTRE_BAND_M = 15.0  # within 15 m of the centre spot
IN_AIR_Z = 0.5  # the scorers' cut-off (ninety/eval/vision_score.py, IN_AIR_Z)
MIN_NEAR_GOAL = 200  # fewer matched frames near the goals than this, and all on-ground frames are pooled
CONFIDENCE_GATE = 0.5  # the fact-checker's MIN_CONFIDENCE (ninety/agents/factcheck.py)


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(x) for x in path.read_text().splitlines() if x.strip()]


def _p95(xs: list[float]) -> float | None:
    if not xs:
        return None
    s = sorted(xs)
    return round(s[min(len(s) - 1, math.ceil(0.95 * len(s)) - 1)], 3)


def errors(rows: list[dict], frames: list[dict]) -> list[dict]:
    """For each frame where the live path places a ball, its error against the true ball."""
    truth = {f["frame"]: f["ball"] for f in frames}
    out = []
    for p in ball_path(rows):
        b = truth.get(p.frame)
        if b is None:
            continue
        out.append({"frame": p.frame, "dx": p.x - b["x"], "dy": p.y - b["y"], "x": b["x"], "y": b["y"],
                    "z": b["z"], "on_player": p.on_player})
    return out


def precision(clips: Path, observations: Path, seeds: list[int]) -> dict:
    near, ground, centre = [], [], []
    per_seed = {}
    for s in seeds:
        obs = next((p for p in (observations / f"observations-seed{s}.jsonl", observations / f"seed{s}.jsonl")
                    if p.is_file()), None)
        if obs is None:
            per_seed[s] = "no observations"
            continue
        errs = errors(read_observations(obs), _read_jsonl(clips / f"seed{s}" / "frames.jsonl"))
        per_seed[s] = len(errs)
        for e in errs:
            if e["z"] > IN_AIR_Z or e["on_player"]:
                continue
            ground.append(e)
            if min(e["x"], 105.0 - e["x"]) <= GOAL_BAND_M:
                near.append(e)
            if math.dist((e["x"], e["y"]), (52.5, 34.0)) <= CENTRE_BAND_M:
                centre.append(e)
    pool = near if len(near) >= MIN_NEAR_GOAL else ground
    return {
        "commit": git_commit(), "seeds": seeds, "matched_by_seed": per_seed,
        "frames": {"on_ground": len(ground), "near_goal": len(near), "near_centre": len(centre)},
        "pooled": "near_goal" if pool is near else "all_on_ground",
        "E_X": _p95([abs(e["dx"]) for e in pool]), "E_Y": _p95([abs(e["dy"]) for e in pool]),
        "E_C": _p95([math.hypot(e["dx"], e["dy"]) for e in centre]),
    }


def _pairs(truth: list[dict], detected: list[dict]) -> list[tuple[int, int]]:
    """One-to-one pairs, same team within WINDOW_S, nearest in time first."""
    cands = sorted((abs(t["t"] - d["t"]), i, j) for i, t in enumerate(truth) for j, d in enumerate(detected)
                   if t["team"] == d["team"] and abs(t["t"] - d["t"]) <= WINDOW_S + 1e-9)
    used_t, used_d, out = set(), set(), []
    for _, i, j in cands:
        if i not in used_t and j not in used_d:
            used_t.add(i)
            used_d.add(j)
            out.append((i, j))
    return out


def shown(event: dict, frames: list[dict]) -> bool:
    """A true goal or save the clip shows: its frame among the clip's frames (not cut, not after
    the end). A goal's frame is the one before its time, as the scorer reads it."""
    k = round(event["t"] * 25) - (1 if event["type"] == "goal" else 0)
    return any(f["frame"] == k for f in frames)


def score_clip(truth: list[dict], frames: list[dict], detected: list[dict], gate: float | None) -> dict:
    out = {}
    for kind in ("goal", "save"):
        if kind == "goal":
            tr = [e for e in truth if e["type"] == "goal" and shown(e, frames)]
            de = [e for e in detected if e["type"] == "goal" and (gate is None or e["confidence"] >= gate)]
        else:
            tr = [e for e in truth if e["type"] == "shot" and e.get("outcome") == "on_target"
                  and shown(e, frames)]
            de = [e for e in detected if e["type"] == "shot" and e.get("outcome") == "on_target"
                  and (gate is None or e["confidence"] >= gate)]
        pairs = _pairs(tr, de)
        hit_t, hit_d = {i for i, _ in pairs}, {j for _, j in pairs}
        out[kind] = {"tp": len(pairs), "fp": len(de) - len(pairs), "fn": len(tr) - len(pairs),
                     "missed": [{"t": tr[i]["t"], "team": tr[i]["team"]}
                                for i in range(len(tr)) if i not in hit_t],
                     "false": [{"t": de[j]["t"], "team": de[j]["team"], "confidence": de[j]["confidence"]}
                               for j in range(len(de)) if j not in hit_d]}
    return out


def score(clips: list[Path], detected: Path) -> dict:
    report = {"commit": git_commit(), "clips": [c.name for c in clips], "gate": CONFIDENCE_GATE, "by": {}}
    for gate_name, gate in (("gated", CONFIDENCE_GATE), ("all", None)):
        totals = {k: {"tp": 0, "fp": 0, "fn": 0, "failures": []} for k in ("goal", "save")}
        for c in clips:
            truth = _read_jsonl(c / "events.jsonl")
            frames = _read_jsonl(c / "frames.jsonl")
            det_file = detected / f"detected-{c.name}.jsonl"
            det = _read_jsonl(det_file) if det_file.is_file() else []
            for kind, r in score_clip(truth, frames, det, gate).items():
                t = totals[kind]
                t["tp"], t["fp"], t["fn"] = t["tp"] + r["tp"], t["fp"] + r["fp"], t["fn"] + r["fn"]
                t["failures"] += [{"clip": c.name, "missed": m} for m in r["missed"]]
                t["failures"] += [{"clip": c.name, "false": f} for f in r["false"]]
        for t in totals.values():
            tp, fp, fn = t["tp"], t["fp"], t["fn"]
            t["precision"] = round(tp / (tp + fp), 3) if tp + fp else None
            t["recall"] = round(tp / (tp + fn), 3) if tp + fn else None
            t["precision_95"], t["recall_95"] = wilson(tp, tp + fp), wilson(tp, tp + fn)
        report["by"][gate_name] = totals
    return report


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Shot outcomes from video: input precision, and the score.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("precision")
    p.add_argument("--clips", type=Path, required=True)
    p.add_argument("--observations", type=Path, required=True)
    p.add_argument("--seeds", type=int, nargs="+", required=True)
    p.add_argument("--out", type=Path, required=True)
    s = sub.add_parser("score")
    s.add_argument("--clips", type=Path, nargs="+", required=True)
    s.add_argument("--detected", type=Path, required=True)
    s.add_argument("--out", type=Path, required=True)
    a = ap.parse_args(argv)
    if a.cmd == "precision":
        if any(seed >= 900000 for seed in a.seeds):
            raise SystemExit("precision is measured on validation seeds only, never a test seed")
        result = precision(a.clips, a.observations, a.seeds)
    else:
        result = score(a.clips, a.detected)
    a.out.write_text(json.dumps(result, indent=1) + "\n")
    print(json.dumps({k: v for k, v in result.items() if k not in ("by",)} | (
        {"by": {g: {k: {m: v[m] for m in ("tp", "fp", "fn", "precision", "recall")} for k, v in t.items()}
                for g, t in result["by"].items()}} if "by" in result else {}), indent=1))


if __name__ == "__main__":
    main()
