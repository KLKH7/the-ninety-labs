"""How far vision's ball speeds are from the true ones: the speed error (docs/eval/speed-plan.md).

Grading only (AGENTS.md: the answer key is for training labels and grading): this reads the clip's
truth frames and events, so nothing on the live path imports it. The speeds graded are the
detector's own, unchanged (ninety/vision/events.py):

- event speed: `ball_speed_kmh` of each detected pass and shot, paired with the true event by the
  event scorer's strict rule (ninety/eval/event_score.py, `match`), against the true event's
  `ball_speed_kmh` (the engine's launch speed, all three components);
- frame speed: the ball's velocity in every frame vision has it (`ball_path`, `_velocity`),
  against the true ball's 3D speed and its flat (x, y) speed in the same frame, so the part of the
  error that is the missing height reads apart from the rest.

    uv run python -m ninety.eval.speed_score --set docs/eval/finetune-v2freeze/validation-set.json \\
        --clips <folder of seed<N>/> --observations <folder of observations-seed<N>.jsonl> \\
        --detector ours-freeze --out docs/eval/speed-report-freeze

The clip set (its seeds and sha256 digests), the clips and the observations are arguments: a new
checkpoint is a new observations folder and a new --out, scored by the same rule. A clip whose
frames, events or images do not match the set's digests is not scored, and the report says so.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import math
from pathlib import Path

from ninety.eval import event_score, pitch_score
from ninety.eval.attribution_score import observations_file, write_or_check
from ninety.eval.vision_score import IN_AIR_Z, height_group
from ninety.vision import events as ev
from ninety.vision import track as tr

KINDS = ("pass", "shot")
KMH = 3.6
# Relative error only for a struck ball: 5 m/s (design, docs/eval/speed-plan.md); dividing by a
# ball nearly at rest says nothing.
REL_MIN_KMH = 18.0
LOOK_FRAMES = round(ev.SHOT_LOOK_S * tr.FPS)  # vision's own window after a strike
# A summary (median, p90, bias) is claimed for a group only from this many pairs (design, lesson 89:
# fewer is a list, not a rate; docs/eval/speed-plan.md).
MIN_PAIRS = 10


def _quantile(s: list[float], p: float) -> float:
    """The same order statistic as pitch_score's summaries (s sorted)."""
    return s[min(len(s) - 1, int(p * (len(s) - 1)))]


def summarise(rows: list[dict], key: str = "error_kmh", true_key: str = "true_kmh") -> dict:
    """n, median and 90th percentile absolute error, mean signed error (bias) and median relative
    error (true speed at least REL_MIN_KMH), all km/h except the relative one."""
    errs = [r[key] for r in rows]
    if not errs:
        return {"n": 0, "enough": False, "median_abs_kmh": None, "p90_abs_kmh": None, "mean_signed_kmh": None,
                "n_relative": 0, "median_abs_relative": None}
    absolute = sorted(abs(e) for e in errs)
    rel = sorted(abs(r[key]) / r[true_key] for r in rows if r[true_key] >= REL_MIN_KMH)
    return {"n": len(errs), "enough": len(errs) >= MIN_PAIRS,
            "median_abs_kmh": round(_quantile(absolute, 0.5), 2),
            "p90_abs_kmh": round(_quantile(absolute, 0.9), 2),
            "mean_signed_kmh": round(math.fsum(errs) / len(errs), 2),
            "n_relative": len(rel), "median_abs_relative": round(_quantile(rel, 0.5), 3) if rel else None}


def true_ball(frame: dict) -> tuple[float, float, float]:
    """(3D speed km/h, flat speed km/h, height m) of the true ball in a truth frame."""
    b = frame["ball"]
    vx, vy, vz = b.get("vx", 0.0), b.get("vy", 0.0), b.get("vz", 0.0)
    return math.sqrt(vx * vx + vy * vy + vz * vz) * KMH, math.hypot(vx, vy) * KMH, b.get("z", 0.0)


def frame_speeds(rows: list[dict], truth: dict[int, dict]) -> list[dict]:
    """Vision's ball speed in each frame it has one, beside the true ball's in that frame. A frame
    the truth does not hold (a broadcast cut) is left out."""
    path = tr.ball_path(rows)
    out = []
    for i, p in enumerate(path):
        v = ev._velocity(path, i)  # the detector's own velocity, unchanged
        if v is None or p.frame not in truth:
            continue
        speed = math.hypot(*v) * KMH
        true3, flat, z = true_ball(truth[p.frame])
        out.append({"frame": p.frame, "vision_kmh": round(speed, 2), "true_kmh": round(true3, 2),
                    "true_flat_kmh": round(flat, 2), "z_m": z, "height": height_group(z),
                    "on_player": p.on_player, "error_kmh": speed - true3, "error_flat_kmh": speed - flat})
    return out


def lofted(t: float, truth: dict[int, dict]) -> bool:
    """The true ball is in the air in any frame of vision's window after the true strike."""
    k = round(t * tr.FPS)
    return any(height_group(truth[f]["ball"].get("z", 0.0)) == "in the air"
               for f in range(k, k + LOOK_FRAMES + 1) if f in truth)


def event_speeds(true_events: list[dict], detected: list[dict], frames: list[dict],
                 cuts: list[dict] | None = None) -> list[dict]:
    """Each detected pass or shot paired with a true one by the strict rule, with both speeds."""
    truth = [e for e in true_events if e["type"] in KINDS]
    found = [e for e in detected if e["type"] in KINDS]
    by_frame = {f["frame"]: f for f in frames}
    t_of, d_of = {e["id"]: e for e in truth}, {e["id"]: e for e in found}
    out = []
    for p in event_score.match(truth, found, event_score.WINDOW_S, frames, event_score.STRICT_M, cuts):
        t, d = t_of[p["truth_id"]], d_of[p["detected_id"]]
        row = {"truth_id": t["id"], "detected_id": d["id"], "type": p["type"],
               "true_kmh": t.get("ball_speed_kmh"), "vision_kmh": d.get("ball_speed_kmh"),
               "lofted": lofted(t["t"], by_frame)}
        if row["true_kmh"] is not None and row["vision_kmh"] is not None:
            row["error_kmh"] = round(row["vision_kmh"] - row["true_kmh"], 2)
            row["relative"] = round(row["error_kmh"] / row["true_kmh"], 3) if row["true_kmh"] else None
        out.append(row)
    return out


def frame_groups(rows: list[dict]) -> dict:
    """Frame speed against the 3D truth and the flat truth, overall and by group."""
    def both(rs):
        return {"vs_3d": summarise(rs), "vs_flat": summarise(rs, "error_flat_kmh", "true_flat_kmh")}
    out = {"all": both(rows)}
    for g in ("on the ground", "in the air"):
        out[g] = both([r for r in rows if r["height"] == g])
    out["drawn over a player"] = both([r for r in rows if r["on_player"]])
    out["not over a player"] = both([r for r in rows if not r["on_player"]])
    return out


def _lf_sha256(path: Path) -> str:
    """sha256 of a text file with its line endings as committed (\\n): a checkout or a copy on
    Windows may write \\r\\n, which changes the bytes and not the data."""
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def mismatched(root: Path, digest: dict) -> list[str]:
    """Which of a clip's files differ from the test set's digests (render/checks.py `digest`)."""
    images = hashlib.sha256()
    files = sorted((root / "images").glob("*.jpg"))
    for f in files:
        images.update(f.read_bytes())
    text = {k: _lf_sha256(root / name) if (root / name).exists() else None
            for k, name in (("frames_jsonl", "frames.jsonl"), ("events_jsonl", "events.jsonl"))}
    got = text | {"images": images.hexdigest(), "image_count": len(files)}
    return [k for k in ("frames_jsonl", "events_jsonl", "images", "image_count") if got[k] != digest[k]]


def check_detections(folder: Path, clip_set: dict, checkpoint: str) -> list[str]:
    """What is wrong with a folder of detections (seed<N>.jsonl, ninety/vision/detections.py) for
    this clip set: a seed missing or extra, a line from another checkpoint or clip, or not one line
    per frame of the clip, in order. Empty when it is the scored run's (docs/eval/speed-plan.md)."""
    problems = []
    want = {e["seed"]: e["digest"]["image_count"] for e in clip_set["clips"]}
    have = {int(f.stem.removeprefix("seed")) for f in folder.glob("seed*.jsonl")}
    problems += [f"seed{s}: missing" for s in sorted(want.keys() - have)]
    problems += [f"seed{s}: not in the set" for s in sorted(have - want.keys())]
    for seed in sorted(want.keys() & have):
        rows = [json.loads(x) for x in (folder / f"seed{seed}.jsonl").read_text().splitlines() if x.strip()]
        names = {r["model"]["checkpoint"] for r in rows}
        if names != {checkpoint}:
            problems.append(f"seed{seed}: checkpoint {sorted(names)}, not {checkpoint}")
        if {r["clip"] for r in rows} != {f"seed{seed}"}:
            problems.append(f"seed{seed}: lines of another clip")
        frames = [r["frame"] for r in rows]
        if len(frames) != want[seed] or frames != sorted(set(frames)):
            problems.append(f"seed{seed}: {len(frames)} lines for {want[seed]} frames, or not in order")
    return problems


def clip(seed: int, root: Path, dirs: list[Path]) -> dict:
    rows = tr.read_observations(observations_file(seed, dirs))
    frames = [json.loads(x) for x in (root / "frames.jsonl").read_text().splitlines() if x.strip()]
    meta = root / "meta.json"
    cuts = json.loads(meta.read_text()).get("cuts", []) if meta.exists() else []
    event_score.check_frames(frames, cuts)
    true_events = event_score.load_events(root / "events.jsonl", "truth")
    detected, _ = ev.detect(rows)
    pos = pitch_score.score(frames, rows)
    return {"seed": seed,
            "true": {k: sum(1 for e in true_events if e["type"] == k) for k in KINDS},
            "detected": {k: sum(1 for e in detected if e["type"] == k) for k in KINDS},
            "events": event_speeds(true_events, detected, frames, cuts),
            "frames": frame_speeds(rows, {f["frame"]: f for f in frames}),
            "positions": {"camera_ok": pos["frames"]["camera_ok"], "observed": pos["frames"]["observed"],
                          "ball_on_ground": pos["ball_on_ground"]}}


def pooled(clips: list[dict]) -> dict:
    events = [e for c in clips for e in c["events"]]
    scored = [e for e in events if "error_kmh" in e]
    groups = {k: summarise([e for e in scored if e["type"] == k]) for k in KINDS}
    for k in KINDS:
        for g, lo in (("along the ground", False), ("lofted", True)):
            groups[f"{k}, {g}"] = summarise([e for e in scored if e["type"] == k and e["lofted"] == lo])
    return {
        "true": {k: sum(c["true"][k] for c in clips) for k in KINDS},
        "detected": {k: sum(c["detected"][k] for c in clips) for k in KINDS},
        "matched": {k: sum(1 for e in events if e["type"] == k) for k in KINDS},
        "event_speed": groups,
        "frame_speed": frame_groups([r for c in clips for r in c["frames"]]),
    }


HEAD = "| n | Median abs (km/h) | p90 abs (km/h) | Mean signed (km/h) | Median abs relative (n) |"


def _f(v) -> str:
    return "-" if v is None else f"{v}"


def stat_cells(s: dict) -> str:
    """A summary's table cells, or "too few" below MIN_PAIRS."""
    if not s["enough"]:
        return f"{s['n']} | too few (under {MIN_PAIRS}) | | | "
    return (f"{s['n']} | {_f(s['median_abs_kmh'])} | {_f(s['p90_abs_kmh'])} | {_f(s['mean_signed_kmh'])} | "
            f"{_f(s['median_abs_relative'])} ({s['n_relative']})")


def report_md(body: dict) -> str:
    p = body["pooled"]
    lines = [
        "# Ball speed and shot speed from video: the speed error",
        "",
        f"Generated by `{body['command']}` at commit `{body['commit']}`, {body['date']}, by the rule "
        f"pre-registered in [speed-plan.md](speed-plan.md). Detector: {body['detector']}. Speeds are "
        "vision's own (ninety/vision/events.py), flat (2D): the ball's box centre is taken to be on the "
        "ground. A mean signed error below zero is vision reading slow.",
        "",
        f"Clips scored: {len(body['clips'])} of {len(body['seeds'])}.",
    ]
    if body["not_scored"]:
        lines.append("Not scored (files differ from the set's digests): " + ", ".join(
            f"{n['seed']} ({', '.join(n['mismatched'])})" for n in body["not_scored"]) + ".")
    lines += ["", "## Event speed (strict match)", "",
              f"True passes {p['true']['pass']}, detected {p['detected']['pass']}, matched "
              f"{p['matched']['pass']}. True shots {p['true']['shot']}, detected {p['detected']['shot']}, "
              f"matched {p['matched']['shot']}.", "",
              "| Group " + HEAD, "|---|---|---|---|---|---|"]
    lines += [f"| {g} | {stat_cells(s)} |" for g, s in p["event_speed"].items()]
    lines += ["", "Each pair:", "",
              "| Seed | Type | Lofted | True km/h | Vision km/h | Error km/h | Relative |",
              "|---|---|---|---|---|---|---|"]
    for c in body["clips"]:
        for e in c["events"]:
            lines.append(f"| {c['seed']} | {e['type']} | {'yes' if e['lofted'] else 'no'} | "
                         f"{_f(e['true_kmh'])} | {_f(e['vision_kmh'])} | {_f(e.get('error_kmh'))} | "
                         f"{_f(e.get('relative'))} |")
    lines += ["", "## Frame speed (a ball speed badge)", "",
              f"Every frame vision has the ball and a velocity. In the air: true height above {IN_AIR_Z} m. "
              f"Relative error only where the true speed is at least {REL_MIN_KMH:g} km/h. Consecutive "
              "frames are not independent: n counts frames, not balls.", "",
              "| Group | Against " + HEAD, "|---|---|---|---|---|---|---|"]
    for g, both in p["frame_speed"].items():
        for against, s in (("3D", both["vs_3d"]), ("flat", both["vs_flat"])):
            lines.append(f"| {g} | {against} | {stat_cells(s)} |")
    lines += ["", "## Per clip", "", "| Seed | Camera trusted | Ball on ground median / p90 (m) | "
              "Passes true / matched | Shots true / matched | Frame speed vs 3D " + HEAD[1:],
              "|---|---|---|---|---|---|---|---|---|---|"]
    for c in body["clips"]:
        pos, s = c["positions"], c["frame_speed"]["all"]["vs_3d"]
        matched = {k: sum(1 for e in c["events"] if e["type"] == k) for k in KINDS}
        lines.append(f"| {c['seed']} | {pos['camera_ok']} of {pos['observed']} | "
                     f"{_f(pos['ball_on_ground']['median_m'])} / {_f(pos['ball_on_ground']['p90_m'])} | "
                     f"{c['true']['pass']} / {matched['pass']} | {c['true']['shot']} / {matched['shot']} | "
                     f"{stat_cells(s)} |")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--set", dest="clip_set", type=Path, required=True,
                    help="seeds and digests, e.g. docs/eval/finetune-v2freeze/validation-set.json")
    ap.add_argument("--clips", type=Path, required=True, help="folder holding seed<N>/ for each seed")
    ap.add_argument("--observations", type=Path, action="append", required=True)
    ap.add_argument("--detector", required=True, help="the checkpoint the observations came from")
    ap.add_argument("--detections", type=Path, default=None,
                    help="the seed<N>.jsonl detections the observations were made from: checked first")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args(argv)
    clip_set = json.loads(a.clip_set.read_text())
    if a.detections is not None:
        problems = check_detections(a.detections, clip_set, a.detector)
        if problems:
            raise SystemExit("detections refused: " + "; ".join(problems))
    clips, not_scored = [], []
    for entry in clip_set["clips"]:
        root = a.clips / f"seed{entry['seed']}"
        wrong = mismatched(root, entry["digest"])
        if wrong:
            not_scored.append({"seed": entry["seed"], "mismatched": wrong})
            continue
        clips.append(clip(entry["seed"], root, a.observations))
    # The clips are a private copy, never committed: the command names their role, not a local path.
    command = (f"uv run python -m ninety.eval.speed_score --set {a.clip_set.as_posix()} "
               f"--clips <clips> --observations <{a.detector} observations> --detector {a.detector} "
               f"--out {a.out.as_posix()}")
    body = {
        "command": command, "commit": event_score.git_commit(), "date": datetime.date.today().isoformat(),
        "detector": a.detector, "clip_set": clip_set.get("tag"), "seeds": clip_set["seeds"],
        "not_scored": not_scored,
        "rules": {"match": "event_score strict", "relative_min_kmh": REL_MIN_KMH,
                  "in_the_air_above_m": IN_AIR_Z, "lofted_window_frames": LOOK_FRAMES,
                  "min_pairs": MIN_PAIRS},
        "pooled": pooled(clips),
        "clips": [{"seed": c["seed"], "true": c["true"], "detected": c["detected"], "events": c["events"],
                   "positions": c["positions"], "frame_speed": frame_groups(c["frames"])} for c in clips],
    }
    write_or_check(a.out, body, report_md, a.check)
    print(json.dumps({"scored": len(clips), "not_scored": not_scored,
                      "event_speed": body["pooled"]["event_speed"]}, indent=1))


if __name__ == "__main__":
    main()
