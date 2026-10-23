"""Run on PR #202 merged into this branch (observe.recolour, R4), not on this branch alone.

T1b of docs/eval/sides-tactical/PLAN.md: T1a with each lens's colours normalised first.

Normalisation (written down before the run): the pitch markings are white (Law 1), so each lens's
gain per channel is 255 over the median colour of its marking pixels (pitch.line_mask, players and
ball masked), taken over every 25th frame of the clip (a fixed lens under the clip's light: one
gain per lens per clip). Every pixel is multiplied by the gains and clipped to 0..255 before the
kit is read (#202's R4 via observe.recolour). A von Kries scaling: it corrects exposure and white
balance together; no truth is read.
"""
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

from ninety.vision import fuse, observe, pitch
from ninety.vision.track import SCORE_MIN, read_observations

raw, out, val = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
seeds = [int(s) for s in sys.argv[4:]]
def rgb_of(p):
    return np.asarray(Image.open(p).convert("RGB"))
out.mkdir(parents=True, exist_ok=True)
gains_log = {}
for s in seeds:
    placed = {}
    for v in ("tac-l", "tac-r"):
        rows = read_observations(raw / f"view-{v}-ours-freeze" / f"seed{s}.jsonl")
        rows = observe.agree([observe.place(r, observe.FIXED_HEIGHT_BAND) for r in rows])
        imgs = sorted((val / f"seed{s}" / "views" / v / "images").glob("*.jpg"))
        meds = []
        for r, p in list(zip(rows, imgs, strict=False))[::25]:
            img = rgb_of(p)
            m = pitch.line_mask(img, [d["bbox"] for d in r["players"] + r["ball"] if d["score"] >= SCORE_MIN])
            if m.sum() > 100:
                meds.append(np.median(img[m.astype(bool)], axis=0))
        g = 255.0 / np.maximum(np.median(meds, axis=0), 1.0) if meds else np.ones(3)
        gains_log[f"{s}/{v}"] = [round(float(x), 3) for x in g]
        def load(p, g=g):
            return np.clip(rgb_of(p).astype(np.float32) * g, 0, 255).astype(np.uint8)
        placed[v] = observe.recolour(rows, imgs, load)
    with open(out / f"seed{s}.jsonl", "w") as f:
        for r in fuse.fuse(placed):
            f.write(json.dumps(r, separators=(",", ":")) + "\n")
    print(s, gains_log[f"{s}/tac-l"], gains_log[f"{s}/tac-r"], flush=True)
(out / "gains.json").write_text(json.dumps(gains_log, indent=1))
