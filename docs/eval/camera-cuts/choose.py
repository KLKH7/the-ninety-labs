"""The plan's rule for the cut candidate and CUT_THRESHOLD (camera-cuts-plan.md, step 1 and amendment)."""
import json, math, sys
d = json.load(open(sys.argv[1]))
res = {}
for k in ("H1", "H2", "T1"):
    cut = [v for c in d.values() for v, t in zip(c[k], c["cut"]) if t]
    non = [v for c in d.values() for v, t in zip(c[k], c["cut"]) if not t]
    lo, hi = min(cut), max(non)
    r = {"cuts": len(cut), "non_cuts": len(non), "lo": lo, "hi": hi, "separates": lo > hi}
    if lo > hi:
        r["margin"] = lo / hi
        r["threshold"] = round(math.sqrt(lo * hi), 3)
        r["errors"] = 0
    else:
        vals = sorted(set(cut + non))
        best = None
        # a threshold just above each value, and at the smallest: the intervals between values
        for i in range(len(vals)):
            below = vals[i]; above = vals[i + 1] if i + 1 < len(vals) else None
            if above is None:
                continue
            missed = sum(v <= below for v in cut); false = sum(v > below for v in non)
            key = (missed + false, missed, below)
            if best is None or key < best[0]:
                best = (key, below, above, missed, false)
        (_, below, above, missed, false) = best
        r.update(errors=missed + false, missed=missed, false=false, below=below, above=above,
                 threshold=round(math.sqrt(below * above), 3))
    res[k] = r
print(json.dumps(res, indent=1))
