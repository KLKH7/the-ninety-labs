"""Broadcast contact sheet: one rendered frame every 0.5 s of a clip, tiled 5 wide.

usage: python bsheet.py <clip_dir> <out_png>
"""

import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from ninety.match.timeline import Timeline

clip_dir, out = Path(sys.argv[1]), Path(sys.argv[2])
clip = json.loads((clip_dir / "clip.json").read_text())
imgs = sorted((clip_dir / "images").glob("*.jpg"))
fps = clip.get("fps", 25)
timeline = Timeline.of_clip(clip)  # the broadcast may cut from a dead ball to its restart
pick = [round(k * fps / 2) for k in range(int(len(imgs) / (fps / 2)))]
pick = [i for i in pick if i < len(imgs)]
cols = 3
tw, th = 960, 540
try:
    font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial.ttf", 18)
except OSError:
    font = ImageFont.load_default()
# six frames a sheet, so feet and board text stay readable
for part in range(0, len(pick), 6):
    sel = pick[part: part + 6]
    rows = (len(sel) + cols - 1) // cols
    sheet = Image.new("RGB", (tw * cols, th * rows))
    for k, i in enumerate(sel):
        im = Image.open(imgs[i]).convert("RGB").resize((tw, th))
        d = ImageDraw.Draw(im)
        t = timeline.to_match(i / fps)
        d.rectangle([0, 0, 260, 24], fill=(0, 0, 0))
        stamp = f"s{clip['seed']} {int(t // 60):02d}:{t % 60:04.1f} f{i}"
        d.text((4, 2), stamp, fill=(255, 255, 0), font=font)
        sheet.paste(im, ((k % cols) * tw, (k // cols) * th))
    p = out.with_name(f"{out.stem}_p{part // 6}.png")
    sheet.save(p, optimize=True)
    print(p)
