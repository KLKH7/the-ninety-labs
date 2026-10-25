"""Possession changes from video on the frozen test set, scored once (docs/eval/possession-change-plan.md).

    uv run python -m ninety.eval.possession_report --test-dir <rebuilt answer key> \\
        --observations docs/eval/attribution --observations tests/fixtures --out docs/eval/possession-change

The answer key is rebuilt from engine-v1 by scripts/rebuild_test_truth.py, which refuses a clip
whose events.jsonl is not the frozen digest; its frame rows hold the ball and the players, not the
drawn boxes, so only events are graded here (event_score's rules, unchanged). As a second check
that the rebuilt frames are the match the test set was drawn from, every clip's pass counts under
every rule must equal event-report-v2's, which was graded on the frozen files; otherwise nothing is
written. Grading, so it reads the answer key; nothing on the live path imports it.

It also writes `docs/eval/event-report-v3.json` (and `.md`): every detected event of the current
detector on the same five clips, graded by the same rules, in event-report-v2's per-clip shape.
event-report-v2 names the events of the detector before possession changes, and a detected id is
only a place in the clip's order (lesson 243), so a reader that needs to know which of today's
detected events are real (ninety/eval/describe_eval.py) reads v3. No positions: the rebuilt frames
hold no boxes.
"""

from __future__ import annotations

import argparse
import datetime
import json
from pathlib import Path

from ninety.eval import event_report, event_score
from ninety.eval.attribution_score import observations_file, ratio, write_or_check
from ninety.eval.event_report import DEVELOPED_ON, SEEDS
from ninety.eval.event_score import wilson
from ninety.vision import events as ev
from ninety.vision import track as tr

ROOT = Path(__file__).resolve().parents[2]
REFERENCE = ROOT / "docs" / "eval" / "event-report-v2.json"
RULES = ("strict", "lenient", "time_only")
KIND = "possession_change"
NEAR_S = 1.5  # true events listed beside a false detection: the match window plus half a second
COMMAND = ("uv run python -m ninety.eval.possession_report --test-dir <rebuilt answer key> "
           "--observations docs/eval/attribution --observations tests/fixtures "
           "--out docs/eval/possession-change")


def _counts(row: dict | None) -> list[int]:
    return [0, 0, 0] if row is None else [row["tp"], row["fp"], row["fn"]]


def clip(seed: int, test_dir: Path, dirs: list[Path], reference: dict) -> dict:
    root = test_dir / f"seed{seed}"
    rows = tr.read_observations(observations_file(seed, dirs))
    frames = [json.loads(x) for x in (root / "frames.jsonl").read_text().splitlines() if x.strip()]
    if [r["frame"] for r in rows] != [f["frame"] for f in frames]:
        raise SystemExit(f"seed {seed}: the observations' frames are not the answer key's window")
    truth = event_score.load_events(root / "events.jsonl", "truth")
    detected, summary = ev.detect(rows)
    report = event_score.score(truth, detected, frames)
    want = next(c for c in reference["clips"] if c["seed"] == seed)["events"]
    for rule in RULES:
        got, was = _counts(report[rule]["per_type"].get("pass")), _counts(want[rule]["per_type"].get("pass"))
        if got != was:
            raise SystemExit(f"seed {seed}, {rule}: passes {got} against event-report-v2's {was}: "
                             "the rebuilt frames are not the frozen ones, or the pass rule changed")
    matched = {p["detected_id"] for p in report["strict"]["pairs"] if p["type"] == KIND}
    found = {p["truth_id"] for p in report["strict"]["pairs"] if p["type"] == KIND}
    restart = event_score.at_restart(truth)
    false = [{"id": d["id"], "t": d["t"], "team": d["team"], "x": d["x"], "y": d["y"],
              "confidence": d["confidence"],
              "truth_near": [{"id": e["id"], "type": e["type"], "team": e["team"],
                              "dt_s": round(e["t"] - d["t"], 2)}
                             for e in truth if abs(e["t"] - d["t"]) <= NEAR_S]}
             for d in detected if d["type"] == KIND and d["id"] not in matched]
    missed = [{"id": e["id"], "t": e["t"], "team": e["team"],
               "phase": "at_restart" if e["id"] in restart else "open_play"}
              for e in truth if e["type"] == KIND and e["id"] not in found]
    return {"seed": seed, "camera_ok": summary["frames_camera_ok"], "frames": summary["frames"],
            "spells": summary["spells"], "events": {r: report[r]["per_type"].get(KIND) for r in RULES},
            "false": false, "missed": missed,
            "graded": {"seed": seed, "summary": summary, "events": {r: report[r] for r in RULES}}}


def pooled(clips: list[dict], rule: str) -> dict:
    rows = [c["events"][rule] for c in clips if c["events"][rule]]
    tp, fp, fn = (sum(r[k] for r in rows) for k in ("tp", "fp", "fn"))
    p, r = ratio(tp, tp + fp), ratio(tp, tp + fn)
    phases = {}
    for phase in ("open_play", "at_restart"):
        t = sum(r["by_phase"][phase]["true"] for r in rows)
        k = sum(r["by_phase"][phase]["tp"] for r in rows)
        phases[phase] = {"true": t, "tp": k, "recall": ratio(k, t), "recall_95": wilson(k, t)}
    return {"true": tp + fn, "detected": tp + fp, "tp": tp, "fp": fp, "fn": fn, "precision": p, "recall": r,
            "precision_95": wilson(tp, tp + fp), "recall_95": wilson(tp, tp + fn), "by_phase": phases}


def report_md(body: dict) -> str:
    f = lambda v: "-" if v is None else f"{v:.2f}"  # noqa: E731
    lines = [
        "# Possession changes from video: the frozen test set, scored once",
        "",
        f"Generated by `{body['command']}` at commit `{body['commit']}`, {body['date']}.",
        "The rule and this measurement were fixed in [possession-change-plan.md](possession-change-plan.md)",
        "before any run; the rule adds no constant. The answer key was rebuilt from engine-v1 and every",
        "clip's events.jsonl matched the frozen digest; every clip's pass counts equal event-report-v2's.",
        "",
        "| Rule | True | Detected | TP | FP | FN | Precision (95%) | Recall (95%) | Open play found "
        "| At a restart found |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    blocks = (("all five", body["pooled"]), (f"without {DEVELOPED_ON}", body["pooled_without_developed_on"]))
    for label, block in blocks:
        for rule in RULES:
            r = block[rule]
            o, s = r["by_phase"]["open_play"], r["by_phase"]["at_restart"]
            lines.append(f"| {rule.replace('_', ' ')}, {label} | {r['true']} | {r['detected']} | {r['tp']} "
                         f"| {r['fp']} | {r['fn']} | {f(r['precision'])} {r['precision_95']} "
                         f"| {f(r['recall'])} {r['recall_95']} "
                         f"| {o['tp']} of {o['true']} | {s['tp']} of {s['true']} |")
    lines += ["", "## Per clip (strict)", "", "| Seed | Camera trusted | True | Detected | TP |",
              "|---|---|---|---|---|"]
    for c in body["clips"]:
        r = c["events"]["strict"] or {"true": 0, "detected": 0, "tp": 0}
        lines.append(f"| {c['seed']} | {c['camera_ok']} of {c['frames']} | {r['true']} | {r['detected']} "
                     f"| {r['tp']} |")
    lines += ["", "## Detected and unmatched (strict), with the true events within 1.5 s", ""]
    for c in body["clips"]:
        for d in c["false"]:
            near = ", ".join(f"{e['type']} {e['team']} ({e['dt_s']:+.2f} s)" for e in d["truth_near"])
            lines.append(f"- {c['seed']} {d['id']} at {d['t']} s, {d['team']}, "
                         f"confidence {d['confidence']}: {near or 'none'}")
    lines += ["", "## True and missed (strict)", ""]
    for c in body["clips"]:
        for m in c["missed"]:
            phase = m["phase"].replace("_", " ")
            lines.append(f"- {c['seed']} {m['id']} at {m['t']} s, {m['team']}, {phase}")
    return "\n".join(lines) + "\n"


def events_md(body: dict) -> str:
    f = lambda v: "-" if v is None else f"{v:.2f}"  # noqa: E731
    lines = ["# Every detected event of the current detector, graded on the frozen test set", "",
             f"Generated by `{body['command']}` at commit `{body['commit']}`, {body['date']}, beside",
             "[possession-change.md](possession-change.md). The detector of",
             "[event-report-v2.md](event-report-v2.md) plus possession changes; its passes, shots and out of",
             "play are graded exactly as there (the run refuses to write otherwise). Events only: the",
             "rebuilt answer key holds no boxes.", ""]
    for rule in RULES:
        lines += [f"## {rule.replace('_', ' ').capitalize()}", "",
                  "| Type | True | Detected | TP | FP | FN | Precision | Recall |",
                  "|---|---|---|---|---|---|---|---|"]
        for kind, r in body["pooled"][rule].items():
            lines.append(f"| {kind} | {r['true']} | {r['detected']} | {r['tp']} | {r['fp']} | {r['fn']} "
                         f"| {f(r['precision'])} | {f(r['recall'])} |")
        lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--test-dir", type=Path, required=True)
    ap.add_argument("--observations", type=Path, action="append", required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--events-out", type=Path, default=ROOT / "docs" / "eval" / "event-report-v3",
                    help="where every detected event's grading goes (.json and .md)")
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args(argv)
    reference = json.loads(REFERENCE.read_text())
    clips = [clip(s, a.test_dir, a.observations, reference) for s in SEEDS]
    graded = [c.pop("graded") for c in clips]
    body = {
        "command": COMMAND, "commit": event_score.git_commit(), "date": datetime.date.today().isoformat(),
        "pooled": {rule: pooled(clips, rule) for rule in RULES},
        "pooled_without_developed_on": {rule: pooled([c for c in clips if c["seed"] != DEVELOPED_ON], rule)
                                        for rule in RULES},
        "clips": clips,
    }
    write_or_check(a.out, body, report_md, a.check)
    events = {"command": COMMAND, "commit": body["commit"], "date": body["date"],
              "pooled": {rule: event_report.pooled(graded, rule) for rule in RULES},
              "clips": graded}
    write_or_check(a.events_out, events, events_md, a.check)
    print(json.dumps({rule: {k: body["pooled"][rule][k] for k in ("true", "detected", "tp", "fp")}
                      for rule in RULES}))


if __name__ == "__main__":
    main()
