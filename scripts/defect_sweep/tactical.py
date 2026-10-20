"""Top-down tactical contact sheets from a run's frames.jsonl and events.jsonl.

One panel per second (the frame at the start of each second, with 1 s trails of the
previous positions), tiled 4x4 per 16 s window. Passes struck inside the panel's second
are drawn as arrows from strike point to end point.

usage: python tactical.py <run_dir> <out_dir>
"""

import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

FPS = 25
PX = 5.2  # pixels per metre
MARGIN = 14
W = int(105 * PX) + 2 * MARGIN
H = int(68 * PX) + 2 * MARGIN + 18
HOME = (220, 40, 40)
AWAY = (40, 90, 230)
GK_HOME = (255, 170, 0)
GK_AWAY = (0, 200, 200)


def P(x, y):
    return MARGIN + x * PX, MARGIN + 18 + (68 - y) * PX


def font(size):
    for f in ("/System/Library/Fonts/Supplemental/Arial.ttf", "/System/Library/Fonts/Helvetica.ttc"):
        try:
            return ImageFont.truetype(f, size)
        except OSError:
            pass
    return ImageFont.load_default()


F_NUM = font(10)
F_HDR = font(13)


def pitch(d):
    g = (40, 120, 50)
    d.rectangle([0, 0, W, H], fill=(30, 95, 40))
    lc = (235, 235, 235)
    d.rectangle([*P(0, 68), *P(105, 0)], outline=lc, width=1)
    d.line([*P(52.5, 0), *P(52.5, 68)], fill=lc)
    cx, cy = P(52.5, 34)
    r = 9.15 * PX
    d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=lc)
    for x0, x1 in ((0, 16.5), (105 - 16.5, 105)):
        d.rectangle([*P(x0, 34 + 20.16), *P(x1, 34 - 20.16)], outline=lc)
    for x0, x1 in ((0, 5.5), (105 - 5.5, 105)):
        d.rectangle([*P(x0, 34 + 9.16), *P(x1, 34 - 9.16)], outline=lc)
    for x0, x1 in ((-1.5, 0), (105, 106.5)):
        d.rectangle([*P(x0, 34 + 3.66), *P(x1, 34 - 3.66)], outline=(255, 255, 0), width=2)
    _ = g


def arrow(d, a, b, col, w=2):
    d.line([*a, *b], fill=col, width=w)
    import math

    ang = math.atan2(b[1] - a[1], b[0] - a[0])
    for s in (2.6, -2.6):
        d.line([*b, b[0] + 8 * math.cos(ang + s), b[1] + 8 * math.sin(ang + s)], fill=col, width=w)


def panel(frames, i, events_in, label):
    im = Image.new("RGB", (W, H))
    d = ImageDraw.Draw(im)
    pitch(d)
    f = frames[i]
    # trails over previous second
    hist = frames[max(0, i - FPS): i + 1: 5]
    for pl_i, pl in enumerate(f["players"]):
        pts = [P(h["players"][pl_i]["x"], h["players"][pl_i]["y"]) for h in hist]
        if len(pts) > 1:
            col = HOME if pl["team"] == "home" else AWAY
            d.line(pts, fill=tuple(c // 2 + 60 for c in col), width=2)
    bh = [P(h["ball"]["x"], h["ball"]["y"]) for h in hist]
    if len(bh) > 1:
        d.line(bh, fill=(255, 255, 255), width=1)
    for ev in events_in:
        if ev["type"] in ("pass", "shot", "clearance", "cross") and ev.get("end_x") is not None:
            col = {"success": (255, 255, 0)}.get(ev.get("outcome"), (255, 120, 255))
            if ev["type"] == "shot":
                col = (255, 255, 255)
            arrow(d, P(ev["x"], ev["y"]), P(ev["end_x"], ev["end_y"]), col)
    poss = f.get("possessor")
    for pl in f["players"]:
        x, y = P(pl["x"], pl["y"])
        gk = pl["role"] == "GK"
        col = (GK_HOME if gk else HOME) if pl["team"] == "home" else (GK_AWAY if gk else AWAY)
        r = 6
        ring = pl["id"] == poss
        d.ellipse([x - r, y - r, x + r, y + r], fill=col, outline=(255, 255, 255) if ring else (0, 0, 0),
                  width=3 if ring else 1)
        num = pl["id"][1:]
        d.text((x - 3 * len(num), y - 6), num, fill=(255, 255, 255), font=F_NUM)
    b = f["ball"]
    bx, by = P(b["x"], b["y"])
    rb = 3 + min(6, b["z"] * 1.5)
    d.ellipse([bx - rb, by - rb, bx + rb, by + rb], fill=(255, 255, 255), outline=(0, 0, 0))
    acts = " ".join(sorted({e["type"] for e in events_in if e["type"] not in ("pressure",)}))
    d.rectangle([0, 0, W, 17], fill=(0, 0, 0))
    d.text((4, 2), f"{label}  poss={poss or '-'}  z={b['z']:.1f}  {acts}", fill=(255, 255, 255), font=F_HDR)
    return im


def mmss(t):
    # the reviewed sheets printed f"{t % 60:04.1f}", which showed 59.96 s as "01:60.0"
    t = round(t, 1)
    return f"{int(t // 60):02d}:{t % 60:04.1f}"


def main():
    run, out = Path(sys.argv[1]), Path(sys.argv[2])
    out.mkdir(parents=True, exist_ok=True)
    seed = json.loads((run / "meta.json").read_text())["seed"]
    frames = [json.loads(line) for line in open(run / "frames.jsonl")]
    events = [json.loads(line) for line in open(run / "events.jsonl")]
    n_sec = len(frames) // FPS
    for w0 in range(0, n_sec - 15, 16):
        sheet = Image.new("RGB", (W * 4, H * 4))
        for k in range(16):
            s = w0 + k
            i = min(len(frames) - 1, s * FPS + FPS - 1)  # end of second s, trail covers second s
            evs = [e for e in events if s <= e["t"] < s + 1]
            pn = panel(frames, i, evs, f"s{seed} {mmss(frames[i]['t'])}")
            sheet.paste(pn, ((k % 4) * W, (k // 4) * H))
        sheet = sheet.resize((sheet.width * 3 // 4, sheet.height * 3 // 4))
        sheet.save(out / f"seed{seed}_t{w0:04d}.png", optimize=True)


if __name__ == "__main__":
    main()
