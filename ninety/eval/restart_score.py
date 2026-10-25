"""Grade detected restarts (set pieces, kick-offs and their kind) against the answer key, offline.

    uv run python -m ninety.eval.restart_score --clip <clip dir> --run <live run dir> \\
        [--clip ... --run ...] \\
        --out docs/eval/set-pieces/validation

The rule is docs/eval/set-piece-detection-plan.md's, fixed before any restart was detected. Each
clip is its rendered folder (frames.jsonl, events.jsonl, meta.json: the answer key, read here only)
and a run of the live path on it (observations.jsonl, detected.jsonl with the restarts in it, and
restarts.json, the kinds). Graded:
- type, team, time and spot with ninety.eval.event_score unchanged (1.0 s; strict 1.0 m, lenient
  2.0 m at the detected time), over `set_piece` and `kickoff`, clips pooled, each matched in itself;
- the kind against `restart_kind` (ninety.eval.set_piece_set) on the true restarts matched in time
  and team, as a confusion table, missed restarts in their own column;
- the signed time from each true restart to the nearest detected restart of its team in its clip;
- coverage (lesson 231): a true restart whose frame the live path trusted no camera on is a miss
  like any other, and is listed as "no camera".
"""

from __future__ import annotations

import argparse
import datetime
import json
import math
from pathlib import Path

from ninety.eval import event_score as es
from ninety.eval.set_piece_set import KINDS, restarts

TYPES = ("set_piece", "kickoff")


def _jsonl(path: Path) -> list[dict]:
    return [json.loads(x) for x in path.read_text().splitlines() if x.strip()]


def clip(clip_dir: Path, run_dir: Path) -> dict:
    """One clip's true and detected restarts, matched three ways, with the kinds."""
    name = clip_dir.name
    events = _jsonl(clip_dir / "events.jsonl")
    frames = _jsonl(clip_dir / "frames.jsonl")
    cuts = json.loads((clip_dir / "meta.json").read_text()).get("cuts", [])
    kind_at = {r["frame"]: r["kind"] for r in restarts(events)}
    truth = [{**e, "id": f"{name}/{e['id']}"} for e in events if e["type"] in TYPES]
    side = json.loads((run_dir / "restarts.json").read_text())
    found_kind = {f"{name}/{r['id']}": r["kind"] for r in side["restarts"]}
    detected = [{**e, "id": f"{name}/{e['id']}"} for e in _jsonl(run_dir / "detected.jsonl")
                if e["type"] in TYPES]
    ok = {r["frame"]: r["camera"]["ok"] for r in _jsonl(run_dir / "observations.jsonl")}
    pairs = {"time_only": es.match(truth, detected, es.WINDOW_S, frames, cuts=cuts)}
    for rule, radius in (("strict", es.STRICT_M), ("lenient", es.LENIENT_M)):
        pairs[rule] = es.match(truth, detected, es.WINDOW_S, frames, radius, cuts)
    rows = []
    for t in truth:
        same = [d for d in detected if d["team"] == t["team"]]
        near = min(same, key=lambda d: abs(d["t"] - t["t"]), default=None)
        # Reported only, never a match: the nearest of either side shows a restart found but sided wrong.
        either = min(detected, key=lambda d: abs(d["t"] - t["t"]), default=None)
        paired = {rule: next((p["detected_id"] for p in ps if p["truth_id"] == t["id"]), None)
                  for rule, ps in pairs.items()}
        d = paired["time_only"]
        rows.append({"id": t["id"], "frame": t["frame"], "type": t["type"], "team": t["team"],
                     "kind": kind_at[t["frame"]], "camera_ok": ok.get(t["frame"], False),
                     "strict": paired["strict"] is not None, "lenient": paired["lenient"] is not None,
                     "time_only": d, "found_kind": found_kind.get(d) if d else None,
                     "nearest_dt_s": round(near["t"] - t["t"], 2) if near else None,
                     "nearest_kind": found_kind.get(near["id"]) if near else None,
                     "either_side": None if either is None else
                     {"dt_s": round(either["t"] - t["t"], 2), "team": either["team"],
                      "kind": found_kind.get(either["id"]),
                      "distance_m": round(math.hypot(either["x"] - t["x"], either["y"] - t["y"]), 2)}})
    matched = {p["detected_id"] for p in pairs["time_only"]}
    false = [{"id": d["id"], "frame": d["frame"], "type": d["type"], "team": d["team"],
              "kind": found_kind.get(d["id"]), "x": d["x"], "y": d["y"]}
             for d in detected if d["id"] not in matched]
    return {"clip": name, "truth": truth, "detected": detected, "pairs": pairs, "restarts": rows,
            "false": false}


def pooled(clips: list[dict]) -> dict:
    truth = [e for c in clips for e in c["truth"]]
    detected = [e for c in clips for e in c["detected"]]
    out = {rule: es.grade(truth, detected, [p for c in clips for p in c["pairs"][rule]])["per_type"]
           for rule in ("strict", "lenient", "time_only")}
    rows = [r for c in clips for r in c["restarts"]]
    confusion = {k: dict.fromkeys((*KINDS, "missed"), 0) for k in KINDS}
    for r in rows:
        confusion[r["kind"]][r["found_kind"] or "missed"] += 1
    by_kind = {}
    for k in KINDS:
        mine = [r for r in rows if r["kind"] == k]
        if not mine:
            continue
        right = sum(1 for r in mine if r["strict"] and r["found_kind"] == k)
        by_kind[k] = {"true": len(mine), "strict_and_kind_right": right,
                      "time_only": sum(1 for r in mine if r["time_only"]),
                      "kind_right_of_time_matched": sum(1 for r in mine if r["found_kind"] == k),
                      "no_camera": sum(1 for r in mine if not r["camera_ok"]),
                      "rate": es.ratio(right, len(mine)), "wilson95": es.wilson(right, len(mine))}
    return {"per_type": out, "by_kind": by_kind, "confusion": confusion,
            "false_per_clip": round(sum(len(c["false"]) for c in clips) / len(clips), 3) if clips else None,
            "restarts": rows, "false": [f for c in clips for f in c["false"]]}


def to_md(body: dict) -> str:
    lines = [f"# Restart detection on {body['split']} ({body['date']}, `{body['git_commit']}`)", "",
             body["note"], "", "| Rule | Type | True | Detected | TP | Precision | Recall | F1 |",
             "|---|---|---:|---:|---:|---:|---:|---:|"]
    fmt = lambda v: "-" if v is None else f"{v:.2f}"  # noqa: E731
    for rule in ("strict", "lenient", "time_only"):
        for t, g in body["per_type"][rule].items():
            lines.append(f"| {rule} | {t} | {g['true']} | {g['detected']} | {g['tp']} | "
                         f"{fmt(g['precision'])} | "
                         f"{fmt(g['recall'])} | {fmt(g['f1'])} |")
    lines += ["", "## By kind (strict, with the kind right)", "",
              "| Kind | True | Right | Time-matched | Kind right of those | No camera |",
              "|---|---:|---:|---:|---:|---:|"]
    for k, g in body["by_kind"].items():
        lines.append(f"| {k} | {g['true']} | {g['strict_and_kind_right']} | {g['time_only']} | "
                     f"{g['kind_right_of_time_matched']} | {g['no_camera']} |")
    lines += ["", "## Confusion (true kind by row; matched in time and team)", "",
              "| True \\ found | " + " | ".join((*KINDS, "missed")) + " |",
              "|---|" + "---:|" * (len(KINDS) + 1)]
    for k, row in body["confusion"].items():
        if any(row.values()):
            lines.append(f"| {k} | " + " | ".join(str(row[c]) for c in (*KINDS, "missed")) + " |")
    lines += ["", "## Every true restart", "",
              "| Restart | Kind | Camera | Strict | Found kind | Nearest same-team detection (s) | "
              "Nearest of either side (s, side, kind, m) |", "|---|---|---|---|---|---:|---|"]
    for r in body["restarts"]:
        e = r["either_side"]
        either = "-" if e is None else f"{e['dt_s']}, {e['team']}, {e['kind']}, {e['distance_m']}"
        lines.append(f"| {r['id']} | {r['kind']} | {'ok' if r['camera_ok'] else 'no camera'} | "
                     f"{'yes' if r['strict'] else 'no'} | {r['found_kind'] or '-'} | {r['nearest_dt_s']} | "
                     f"{either} |")
    lines += ["", f"False restarts: {len(body['false'])} ({body['false_per_clip']} a clip)", ""]
    lines += [f"- {f['id']}: {f['type']} {f['team']} {f['kind']} at ({f['x']}, {f['y']})"
              for f in body["false"]]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Grade detected restarts and their kind against the answer key.")
    ap.add_argument("--clip", type=Path, action="append", required=True)
    ap.add_argument("--run", type=Path, action="append", required=True)
    ap.add_argument("--split", default="validation")
    ap.add_argument("--note", default="")
    ap.add_argument("--out", type=Path, required=True, help="writes <out>.json and <out>.md")
    a = ap.parse_args(argv)
    if len(a.clip) != len(a.run):
        ap.error("one --run for each --clip")
    clips = [clip(c, r) for c, r in zip(a.clip, a.run, strict=True)]
    body = {"split": a.split, "date": datetime.date.today().isoformat(), "git_commit": es.git_commit(),
            "note": a.note, "clips": [c["clip"] for c in clips], **pooled(clips)}
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.with_suffix(".json").write_text(json.dumps(body, indent=1, allow_nan=False) + "\n")
    a.out.with_suffix(".md").write_text(to_md(body))
    print(json.dumps({k: body[k] for k in ("by_kind", "false_per_clip")}, indent=1))


if __name__ == "__main__":
    main()
