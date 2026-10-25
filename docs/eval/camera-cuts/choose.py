"""The plan's rule for the cut detector and CUT_THRESHOLD (docs/eval/camera-cuts-plan.md, step 1
and its first amendment), on the distances cut_candidates.py wrote.

    uv run python docs/eval/camera-cuts/choose.py docs/eval/camera-cuts/distances-validation.json
"""

import json
import math
import sys


def choose(d: dict, name: str) -> dict:
    cut = [v for c in d.values() for v, t in zip(c[name], c["cut"], strict=True) if t]
    non = [v for c in d.values() for v, t in zip(c[name], c["cut"], strict=True) if not t]
    lo, hi = min(cut), max(non)
    r = {"cuts": len(cut), "non_cuts": len(non), "lo": lo, "hi": hi, "separates": lo > hi}
    if lo > hi:
        return {**r, "margin": lo / hi, "errors": 0, "threshold": round(math.sqrt(lo * hi), 3)}
    vals = sorted(set(cut + non))
    best = None
    for below, above in zip(vals[:-1], vals[1:], strict=True):  # a threshold between two values
        missed = sum(v <= below for v in cut)
        false = sum(v > below for v in non)
        key = (missed + false, missed, below)
        if best is None or key < best[0]:
            best = (key, below, above, missed, false)
    _, below, above, missed, false = best
    return {**r, "errors": missed + false, "missed": missed, "false": false, "below": below,
            "above": above, "threshold": round(math.sqrt(below * above), 3)}


if __name__ == "__main__":
    data = json.load(open(sys.argv[1]))
    print(json.dumps({k: choose(data, k) for k in ("H1", "H2", "T1")}, indent=1))
