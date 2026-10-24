"""Grade the broadcast camera fit on clips with camera cuts, offline (docs/eval/camera-cuts-plan.md).

    uv run python -m ninety.eval.camera_cuts --clips <dir with seed<N>/frames.jsonl> \\
        --run before=<dir>/before-seed{seed}.jsonl --run after=<dir>/after-seed{seed}.jsonl \\
        --seeds 110 111 ... --out docs/eval/camera-cuts-validation

Reads the answer key (each clip's frames.jsonl) to grade observations the live path wrote; nothing
here is on the live path. Per clip and run:
- the true cuts (a frame whose camera position moves over 1 m or whose angle changes from the frame
  before) and the cuts the live path found (`shots` on the first observation line), matched to the
  frame;
- the frames trusted, and among them the good (ground error within GOOD_M) and the bad, with the
  worst trusted error; the error is detector_derive.ground_error, the camera-bound plan's measure.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from ninety.eval.detector_derive import GOOD_M, MAX_TRUSTED_M, camera_errors

MOVED_M = 1.0  # a camera that moves this far between two frames has cut (a pan does not move it)


def true_cuts(frames: list[dict]) -> list[int]:
    """Frames whose camera is not the one of the frame before (position or named angle)."""
    out = []
    for a, b in zip(frames[:-1], frames[1:], strict=True):
        ca, cb = a["camera"], b["camera"]
        if ca.get("angle") != cb.get("angle") or math.dist(ca["position"], cb["position"]) > MOVED_M:
            out.append(b["frame"])
    return out


def found_cuts(rows: list[dict]) -> list[int]:
    """The live path's cuts: every shot's first frame after the first."""
    return [s["frame"] for s in rows[0].get("shots", [])][1:]


def grade(rows: list[dict], frames: list[dict]) -> dict:
    by_frame = {f["frame"]: f for f in frames}
    errs = camera_errors(rows, by_frame)
    trusted = [e for e in errs if e["ok"]]
    measured = [e["error_m"] for e in trusted if e["error_m"] is not None]
    truth, found = true_cuts(frames), found_cuts(rows)
    return {
        "frames": len(rows),
        "trusted": len(trusted),
        "good": sum(e <= GOOD_M for e in measured),
        "bad": sum(e > GOOD_M for e in measured),
        "unmeasured": len(trusted) - len(measured),
        "worst_m": round(max(measured), 3) if measured else None,
        "bad_frames": [e["frame"] for e in trusted if e["error_m"] is not None and e["error_m"] > GOOD_M],
        "true_cuts": truth,
        "found_cuts": found,
        "missed": sorted(set(truth) - set(found)),
        "false": sorted(set(found) - set(truth)),
    }


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(x) for x in path.read_text().splitlines() if x.strip()]


def report(clips: Path, runs: dict[str, str], seeds: list[int]) -> dict:
    body: dict = {"max_trusted_m": MAX_TRUSTED_M, "good_m": GOOD_M, "clips": {}}
    for s in seeds:
        frames = read_jsonl(clips / f"seed{s}" / "frames.jsonl")
        body["clips"][str(s)] = {name: grade(read_jsonl(Path(pat.format(seed=s))), frames)
                                 for name, pat in runs.items()}
    body["totals"] = {}
    for name in runs:
        per = [c[name] for c in body["clips"].values()]
        worst = [p["worst_m"] for p in per if p["worst_m"] is not None]
        body["totals"][name] = {k: sum(p[k] for p in per) for k in ("trusted", "good", "bad", "unmeasured")}
        body["totals"][name]["worst_m"] = max(worst) if worst else None
        body["totals"][name]["missed"] = sum(len(p["missed"]) for p in per)
        body["totals"][name]["false"] = sum(len(p["false"]) for p in per)
    return body


def to_md(body: dict, runs: list[str]) -> str:
    head = "| Seed | True cuts | " + " | ".join(
        f"{r}: found cuts (missed, false) | {r}: trusted (good, bad) | {r}: worst" for r in runs) + " |"
    lines = [head, "|" + "---|" * (2 + 3 * len(runs))]
    for s, c in body["clips"].items():
        first = c[runs[0]]
        cells = [s, str(first["true_cuts"] or "none")]
        for r in runs:
            g = c[r]
            cells += [f"{g['found_cuts'] or 'none'} ({len(g['missed'])}, {len(g['false'])})",
                      f"{g['trusted']} ({g['good']}, {g['bad']})",
                      "-" if g["worst_m"] is None else f"{g['worst_m']} m"]
        lines.append("| " + " | ".join(cells) + " |")
    cells = ["all", ""]
    for r in runs:
        t = body["totals"][r]
        cells += [f"({t['missed']}, {t['false']})", f"{t['trusted']} ({t['good']}, {t['bad']})",
                  "-" if t["worst_m"] is None else f"{t['worst_m']} m"]
    lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Grade the camera fit on clips with cuts (offline).")
    ap.add_argument("--clips", type=Path, required=True)
    ap.add_argument("--run", action="append", required=True, metavar="NAME=PATTERN",
                    help="observations per seed, {seed} in the path (repeatable)")
    ap.add_argument("--seeds", type=int, nargs="+", required=True)
    ap.add_argument("--out", type=Path, required=True, help="writes <out>.json and <out>.md")
    a = ap.parse_args(argv)
    runs = dict(r.split("=", 1) for r in a.run)
    body = report(a.clips, runs, a.seeds)
    a.out.with_suffix(".json").write_text(json.dumps(body, indent=2, allow_nan=False) + "\n")
    a.out.with_suffix(".md").write_text(to_md(body, list(runs)))
    print(to_md(body, list(runs)))


if __name__ == "__main__":
    main()
