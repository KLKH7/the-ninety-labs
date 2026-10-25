"""Grade judged broadcast observations against each clip's true camera (offline, the answer key):
per clip, the frames trusted (good and bad by the 1.0 m ground mapping error, GOOD_M), the good
frames kept of all good frames, and the median, p95 and worst error of the trusted frames.

    uv run python docs/eval/band-032/grade.py --clips <dir with seed<N>/> --obs <dir> \\
        --pattern 'seed{seed}.jsonl' --seeds 108 109 ... --out <json>
"""
import argparse
import json
from pathlib import Path

import numpy as np

from ninety.eval.detector_derive import GOOD_M, camera_errors
from ninety.eval.vision_score import load_jsonl


def grade(clips: Path, obs: Path, pattern: str, seeds: list[int]) -> dict:
    per, allerr, good_all, good_kept = {}, [], 0, 0
    for seed in seeds:
        rows = load_jsonl(obs / pattern.format(seed=seed))
        frames = {int(r["frame"]): r for r in load_jsonl(clips / f"seed{seed}" / "frames.jsonl")}
        errs = camera_errors(rows, frames)
        trusted = [e["error_m"] for e in errs if e["ok"] and e["error_m"] is not None]
        good = sum(1 for e in errs if e["error_m"] is not None and e["error_m"] <= GOOD_M)
        kept = sum(1 for x in trusted if x <= GOOD_M)
        good_all, good_kept = good_all + good, good_kept + kept
        allerr += trusted
        per[seed] = {"frames": len(rows), "trusted": len(trusted), "trusted_good": kept,
                     "trusted_bad": len(trusted) - kept, "good_frames": good, **stats(trusted)}
    return {"seeds": seeds, "clips": per,
            "all": {"trusted": len(allerr), "good_frames": good_all, "good_kept": good_kept,
                    "good_kept_share": round(good_kept / good_all, 4) if good_all else None,
                    **stats(allerr)},
            "clips_with_trusted_over_1m": {s: {"frames": c["trusted_bad"],
                                               "worst_m": c["worst_m"]}
                                           for s, c in per.items() if c["trusted_bad"]}}


def stats(x: list[float]) -> dict:
    if not x:
        return {"median_m": None, "p95_m": None, "worst_m": None}
    return {"median_m": round(float(np.median(x)), 3), "p95_m": round(float(np.percentile(x, 95)), 3),
            "worst_m": round(float(max(x)), 3)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--clips", type=Path, required=True)
    ap.add_argument("--obs", type=Path, required=True)
    ap.add_argument("--pattern", default="seed{seed}.jsonl")
    ap.add_argument("--seeds", type=int, nargs="+", required=True)
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()
    body = grade(a.clips, a.obs, a.pattern, a.seeds)
    a.out.write_text(json.dumps(body, indent=2) + "\n")
    print(json.dumps(body["all"]))


if __name__ == "__main__":
    main()
