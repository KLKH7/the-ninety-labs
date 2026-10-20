"""One-row example strip: 4 tactical panels, `step` seconds apart, from a match time.

usage: python strip.py <seed> <mm:ss> <out_png> [step_s]
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import tactical as T  # noqa: E402
from PIL import Image  # noqa: E402

seed, mmss, out = int(sys.argv[1]), sys.argv[2], Path(sys.argv[3])
step = float(sys.argv[4]) if len(sys.argv) > 4 else 2.0
m, s = mmss.split(":")
t0 = int(m) * 60 + float(s)
run = Path("runs/sweep/m") / f"seed{seed}"  # run from the repo root
frames = [json.loads(line) for line in open(run / "frames.jsonl")]
events = [json.loads(line) for line in open(run / "events.jsonl")]


def label(t):
    t = round(t)
    return f"s{seed} {t // 60:02d}:{t % 60:02d}"


strip = Image.new("RGB", (T.W * 4, T.H))
for k in range(4):
    a = t0 + k * step
    i = min(len(frames) - 1, int(round((a + 1) * T.FPS)) - 1)
    evs = [e for e in events if a <= e["t"] < a + step]
    strip.paste(T.panel(frames, i, evs, label(frames[i]["t"])), (k * T.W, 0))
strip = strip.resize((strip.width * 2 // 3, strip.height * 2 // 3))
out.parent.mkdir(parents=True, exist_ok=True)
strip.save(out, optimize=True)
print(out, out.stat().st_size)
