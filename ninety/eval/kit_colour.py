"""Kit colour readers compared on validation clips (docs/eval/kit-colour-plan.md).

    uv run --group vision python -m ninety.eval.kit_colour --clips <render run v1>/train \\
        --observations <validation observations> --seeds <the validation seeds> --work <scratch dir> \\
        --out docs/eval/kit-colour

Grading, offline. For each reader, every player detection's shirt is read again from the clip's
images and boxes (the live path's own `observe.read_kit`; the camera fit is not re-run). Then:
cluster soundness and side accuracy (as docs/eval/side-decision.md), teams right on matched passes,
and the colour error against the true shirt colour, which the render settings give and which is read
here only. Refuses test seeds.
"""

from __future__ import annotations

import argparse
import datetime
import json
from pathlib import Path

import numpy as np
from PIL import Image

from ninety.eval import attribution_score as at
from ninety.eval import detector_derive as dd
from ninety.eval import side_decision as sd
from ninety.eval.event_score import git_commit
from ninety.vision import observe
from ninety.vision import track as tr

READERS = ("R0", "R1", "R2", "R3", "R4")
COMMAND = ("uv run --group vision python -m ninety.eval.kit_colour --clips <render run v1>/train "
           "--observations <validation observations> --seeds <the validation seeds> --work <scratch> "
           "--out docs/eval/kit-colour")


def reread(seed: int, clips: Path, observations: Path, reader: str) -> list[dict]:
    """The clip's observations with every player's shirt read again by `reader`."""
    path = observations / f"observations-seed{seed}.jsonl"
    rows = [json.loads(x) for x in path.read_text().splitlines()]
    images = sorted((clips / f"seed{seed}" / "images").glob("*.jpg"))
    for r, img in zip(rows, images, strict=True):
        if reader == "R0":
            continue
        rgb = np.asarray(Image.open(img).convert("RGB"))
        boxes = [d["bbox"] for d in r["players"] + r["ball"]]
        P = np.array(r["camera"]["P"]) if r["camera"].get("P") is not None else None
        turf = observe.grass(rgb, P, boxes)
        for d in r["players"]:
            if d["score"] >= tr.SCORE_MIN:
                d["rgb"] = observe.read_kit(rgb, d["bbox"], reader, turf)
    return rows


def colour_error(rows: list[dict], frames: dict, params: dict, two: bool) -> float | None:
    """The median over tracks (10 frames or more, paired with a true player) of the chromaticity
    distance from the track's read kit to its true team's shirt colour (for a two-colour reading,
    the nearer of its two)."""
    tracks = tr.track_players(rows)
    obs = {r["frame"]: r for r in rows}
    out = []
    for t in tracks:
        med = tr._median_rgb(t)
        if med is None or len(t.frames) < 10:
            continue
        truth = dd.track_truth(t, obs, frames)
        if not truth:
            continue
        hexc = params[f"{truth.most_common(1)[0][0]}_kit"]["shirt"]
        true = np.array([int(hexc[i:i + 2], 16) for i in (1, 3, 5)], float)
        tc = true / true.sum()
        reads = [np.array(med[k:k + 3]) for k in range(0, 6 if two and len(med) >= 6 else 3, 3)]
        out.append(min(float(np.linalg.norm(c / (c.sum() + 1e-9) - tc)) for c in reads))
    return round(float(np.median(out)), 4) if out else None


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--clips", type=Path, required=True)
    ap.add_argument("--observations", type=Path, required=True)
    ap.add_argument("--seeds", required=True)
    ap.add_argument("--work", type=Path, required=True,
                    help="where each reader's observations are written")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args(argv)
    seeds = [s for s in map(int, a.seeds.split(","))
             if not dd.refused(s) and (a.observations / f"observations-seed{s}.jsonl").exists()]
    if any(dd.refused(int(s)) for s in a.seeds.split(",")):
        raise SystemExit("test seeds: the test clips are for the final score only")
    results = {}
    for reader in READERS:
        work = a.work / reader
        work.mkdir(parents=True, exist_ok=True)
        per = []
        for s in seeds:
            rows = reread(s, a.clips, a.observations, reader)
            (work / f"observations-seed{s}.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
            lines = (a.clips / f"seed{s}" / "frames.jsonl").read_text().splitlines()
            frames = {f["frame"]: f for f in map(json.loads, lines)}
            params = json.loads((a.clips / f"seed{s}" / "clip.json").read_text())["params"]
            side = sd.test_clip(s, a.clips, [work])
            pairs = [p for p in at.clip(s, a.clips, [work])["pairs"] if p["type"] == "pass"]
            per.append({"seed": s, "sound": side["sound"], "named_right": side["named_right"],
                        "right_frames": side["right_frames"], "frames": side["frames"],
                        "passes_right": sum(p["team"]["truth"] == p["team"]["detected"] for p in pairs),
                        "passes": len(pairs),
                        "colour_error": colour_error(rows, frames, params, reader == "R4"),
                        "feature": side["feature"],
                        "confidence": [(p["team"].get("confidence"),
                                        p["team"]["truth"] == p["team"]["detected"]) for p in pairs]})
        rf, fr = sum(p["right_frames"] for p in per), sum(p["frames"] for p in per)
        errs = [p["colour_error"] for p in per if p["colour_error"] is not None]
        conf = [c for p in per for c in p["confidence"] if c[0] is not None]
        results[reader] = {"sound_clips": sum(p["sound"] for p in per),
                           "confidence_ordering": dd.ordering(conf),
                           "accuracy": round(rf / fr, 4) if fr else None,
                           "passes_right": sum(p["passes_right"] for p in per),
                           "passes": sum(p["passes"] for p in per),
                           "colour_error": round(float(np.median(errs)), 4) if errs else None,
                           "per_clip": per}
    base = results["R0"]
    qualifying = [r for r in READERS[1:] if results[r]["sound_clips"] >= base["sound_clips"]
                  and (results[r]["accuracy"] or 0) >= (base["accuracy"] or 0)
                  and (results[r]["colour_error"] or 9) <= (base["colour_error"] or 9)]
    best = max(qualifying, default=None,
               key=lambda r: (results[r]["sound_clips"], results[r]["accuracy"], -READERS.index(r)))
    adopted = best or "R0"
    body = {"command": COMMAND, "commit": git_commit(), "date": datetime.date.today().isoformat(),
            "seeds": seeds, "readers": results, "adopted": adopted,
            "predictive": (results[adopted]["confidence_ordering"] or 0) >= 0.80}
    at.write_or_check(a.out, body, report_md, a.check)
    summary = {r: {k: v for k, v in x.items() if k != "per_clip"} for r, x in results.items()}
    print(json.dumps(summary | {"adopted": adopted, "predictive": body["predictive"]}, indent=1))


def report_md(body: dict) -> str:
    lines = ["# Kit colour readers on validation clips", "",
             f"Generated by `{body['command']}` at commit `{body['commit']}`, {body['date']}. Plan: "
             "[kit-colour-plan.md](kit-colour-plan.md).", "", f"Adopted: **{body['adopted']}**.", "",
             f"The adopted reader's team_confidence predictive at 0.80: **{body['predictive']}**.", "",
             "| Reader | Sound clips | Side accuracy, track-frames | Pass teams right | Median colour error "
             "| Confidence ordering |",
             "|---|---|---|---|---|---|"]
    for r, x in body["readers"].items():
        lines.append(f"| {r} | {x['sound_clips']} | {x['accuracy']} | {x['passes_right']} of {x['passes']} "
                     f"| {x['colour_error']} | {x['confidence_ordering']} |")
    lines += ["", "## Per clip (sound; side accuracy)", "",
              "| Seed | " + " | ".join(body["readers"]) + " |", "|---|" + "---|" * len(body["readers"])]
    for i, s in enumerate(body["seeds"]):
        cells = []
        for x in body["readers"].values():
            c = x["per_clip"][i]
            acc = round(c["right_frames"] / c["frames"], 2) if c["frames"] else None
            cells.append(f"{'sound' if c['sound'] else '-'}; {acc}")
        lines.append(f"| {s} | " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    main()
