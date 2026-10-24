"""Plan step 1 on validation: each candidate distance at true cuts and at non-cuts."""
import json, sys
from pathlib import Path
import numpy as np
from PIL import Image

def hist(rgb, bins=8):
    q = (rgb.astype(np.int32) * bins) // 256
    idx = (q[..., 0] * bins + q[..., 1]) * bins + q[..., 2]
    h = np.bincount(idx.ravel(), minlength=bins ** 3).astype(float)
    return h / h.sum()

def thumb(rgb):
    g = rgb.astype(float).mean(-1)
    H, W = g.shape
    return g[: H // 18 * 18, : W // 32 * 32].reshape(18, H // 18, 32, W // 32).mean((1, 3))

def truth_cuts(clip):
    rows = [json.loads(l) for l in open(clip / "frames.jsonl")]
    cut = []
    for a, b in zip(rows[:-1], rows[1:]):
        ca, cb = a["camera"], b["camera"]
        moved = max(abs(x - y) for x, y in zip(ca["position"], cb["position"]))
        cut.append(ca["angle"] != cb["angle"] or moved > 1.0)
    return cut

out = {}
for clip in map(Path, sys.argv[1:]):
    imgs = sorted((clip / "images").glob("*.jpg"))
    feats = []
    for p in imgs:
        rgb = np.asarray(Image.open(p).convert("RGB"))
        feats.append((hist(rgb), hist(rgb[: rgb.shape[0] // 3]), thumb(rgb)))
    d = {"H1": [], "H2": [], "T1": []}
    for (a1, a2, a3), (b1, b2, b3) in zip(feats[:-1], feats[1:]):
        d["H1"].append(0.5 * np.abs(a1 - b1).sum())
        d["H2"].append(0.5 * np.abs(a2 - b2).sum())
        d["T1"].append(float(np.abs(a3 - b3).mean()))
    out[clip.name] = {"cut": truth_cuts(clip), **d}
json.dump(out, open(sys.argv[0].replace("cut_candidates.py", "cut_candidates.json"), "w"))
for name, v in out.items():
    cuts = [i + 1 for i, c in enumerate(v["cut"]) if c]
    line = [name, "cuts at", cuts]
    for k in ("H1", "H2", "T1"):
        a = np.array(v[k]); c = np.array(v["cut"])
        line += [k, "cut", np.round(a[c], 3).tolist(), "max non-cut", round(float(a[~c].max()), 3)]
    print(*line)
