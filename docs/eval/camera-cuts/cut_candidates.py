"""Plan step 1 on validation (docs/eval/camera-cuts-plan.md): each candidate's distance between
consecutive frames, and which frames are true cuts (from frames.jsonl, for grading only).

    uv run python docs/eval/camera-cuts/cut_candidates.py <clip> ... > distances-validation.json
"""

import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image


def hist(rgb: np.ndarray, bins: int = 8) -> np.ndarray:
    q = (rgb.astype(np.int32) * bins) // 256
    idx = (q[..., 0] * bins + q[..., 1]) * bins + q[..., 2]
    h = np.bincount(idx.ravel(), minlength=bins ** 3).astype(float)
    return h / h.sum()


def thumb(rgb: np.ndarray) -> np.ndarray:
    g = rgb.astype(float).mean(-1)
    H, W = g.shape
    return g[: H // 18 * 18, : W // 32 * 32].reshape(18, H // 18, 32, W // 32).mean((1, 3))


def truth_cuts(clip: Path) -> list[bool]:
    rows = [json.loads(x) for x in open(clip / "frames.jsonl")]
    cut = []
    for a, b in zip(rows[:-1], rows[1:], strict=True):
        ca, cb = a["camera"], b["camera"]
        moved = max(abs(x - y) for x, y in zip(ca["position"], cb["position"], strict=True))
        cut.append(ca["angle"] != cb["angle"] or moved > 1.0)
    return cut


def main() -> None:
    out = {}
    for clip in map(Path, sys.argv[1:]):
        feats = []
        for p in sorted((clip / "images").glob("*.jpg")):
            rgb = np.asarray(Image.open(p).convert("RGB"))
            feats.append((hist(rgb), hist(rgb[: rgb.shape[0] // 3]), thumb(rgb)))
        d = {"H1": [], "H2": [], "T1": []}
        for (a1, a2, a3), (b1, b2, b3) in zip(feats[:-1], feats[1:], strict=True):
            d["H1"].append(0.5 * float(np.abs(a1 - b1).sum()))
            d["H2"].append(0.5 * float(np.abs(a2 - b2).sum()))
            d["T1"].append(float(np.abs(a3 - b3).mean()))
        out[clip.name] = {"cut": truth_cuts(clip), **d}
    print(json.dumps(out))


if __name__ == "__main__":
    main()
