"""T1 of docs/eval/sides-tactical/PLAN.md: each lens's saved observations, judged with the fixed band,
kits re-read by #202's R4 (observe.recolour) from that lens's images, fused; then sides scored."""
import json, sys
from pathlib import Path
import numpy as np
from PIL import Image
from ninety.vision import fuse, observe
from ninety.vision.track import read_observations

raw, out, val = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
seeds = [int(s) for s in sys.argv[4:]]
load = lambda p: np.asarray(Image.open(p).convert("RGB"))
(out).mkdir(parents=True, exist_ok=True)
for s in seeds:
    placed = {}
    for v in ("tac-l", "tac-r"):
        rows = read_observations(raw / f"view-{v}-ours-freeze" / f"seed{s}.jsonl")
        rows = observe.agree([observe.place(r, observe.FIXED_HEIGHT_BAND) for r in rows])
        imgs = sorted((val / f"seed{s}" / "views" / v / "images").glob("*.jpg"))
        placed[v] = observe.recolour(rows, imgs, load)
    with open(out / f"seed{s}.jsonl", "w") as f:
        for r in fuse.fuse(placed):
            f.write(json.dumps(r, separators=(",", ":")) + "\n")
    print(s, flush=True)
