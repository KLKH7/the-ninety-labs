"""The score from the broadcast's own scorebug: two digits read from the picture, about once a second.

    uv run python -m ninety.vision.scorebug <staged clip> --out score.jsonl [--events detected.jsonl]

Reads only pixels: the staged clip's `index.jsonl` and `images/` (ninety.vision.stage_live), as the
detector does. Nothing here reads ground truth (tests/test_vision_live_path.py watches it run).

**Where the digits are.** The scorebug is our renderer's (web/render/render.js, `drawBug`): a dark
plate (rgba(12,14,20,0.94)) 196 px wide and 40 px high at a 720-line picture, with a white 2 px
underline, in the top-left corner, its top 24 px down, scaled with the picture height. When a goal's
GOAL panel slides open the plate moves right, so the plate is found on each frame rather than
assumed: the longest run of columns, in the left of the picture, whose middle rows are dark and whose
underline rows are bright. The home digit is drawn from 62 px and the away digit from 104 px into
the plate, 16 px semi-bold sans-serif, centred on the plate's middle row.

**Reading a digit.** Each digit cell is compared, by normalised cross-correlation over a few pixels
of shift, with templates of the ten digits rasterised from the two faces Chromium's `sans-serif`
resolves to where we render: Helvetica Bold on the Mac and Liberation Sans Bold on Linux, whose
digit shapes are Arial Bold's (`scorebug_glyphs.json`, made by `--make-glyphs` from the system's
font files; only the 24 x 16 digit rasters are committed, no font). A reading counts when its best
correlation is at least MIN_NCC and beats the best other digit by MIN_MARGIN.

**A change of score.** The digits are read every SAMPLE_FRAMES frames. A score holds once STABLE
samples in a row agree, so the goal's half-second "pop" of the scorer's digit and the panel's slide
(render.js: 0.5 s and 0.42 s) are never read as a score. A goal adds one to one side (Law 10), so a
held score that differs from the last by exactly one goal on one side is a `score_change`, timed at
the first frame that shows it (found frame by frame back to the sample before). Any other
difference (a digit lost behind a stinger, a misread) changes nothing and is counted.

`confidence` is the new digit's mean correlation over its holding samples: a score, not a
probability.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

FPS = 25
GLYPHS = Path(__file__).with_name("scorebug_glyphs.json")
# render.js `drawBug`, at a 720-line picture (scaled by height / 720, rounded to 0.01 as render.js does).
BUG_TOP, BUG_H, PLATE_W, UNDERLINE = 24, 40, 196, 38
DIGIT_X = {"home": 62, "away": 104}
SEARCH_W = 500  # the plate's left edge lies within the GOAL panel's 96 px plus its own 28 px margin
# The plate's colours (render.js): rgba(12,14,20,0.94) over any picture is at most 27 grey levels,
# and its white underline is 255; JPEG and the digits' own white pixels move a column's median by
# far less than the midway thresholds between them and the picture's sky and stands (design).
DARK, BRIGHT = 70, 170
CELL_H, CELL_W = 24, 16  # a template: one 16 px digit with its margins
# Acceptance (design, stated before any validation score, docs/eval/scorebug-plan.md): on pod-rendered
# training frames a 0 reads at 0.99 with the next digit at 0.87; the goal's pop reads near 0.79.
MIN_NCC, MIN_MARGIN = 0.85, 0.05
SAMPLE_FRAMES = FPS  # about once a second
STABLE = 2  # samples in a row: a reading held for a second outlasts the 0.5 s pop and 0.42 s slide


def scale(height: int) -> float:
    return round(height / 720 * 100) / 100


def load_glyphs(path: Path = GLYPHS) -> dict[str, np.ndarray]:
    raw = json.loads(path.read_text())
    return {face: np.asarray(digits, dtype=float) for face, digits in raw["faces"].items()}


def plate_x(gray: np.ndarray) -> int | None:
    """The plate's left edge in this frame, or None when no plate is drawn (a stinger, a cut)."""
    s = scale(gray.shape[0])
    top, h = round(BUG_TOP * s), round(BUG_H * s)
    under = gray[top + round(UNDERLINE * s): top + h, : round(SEARCH_W * s)].mean(axis=0)
    middle = np.median(gray[top + round(2 * s): top + round(35 * s), : round(SEARCH_W * s)], axis=0)
    plate = (middle < DARK) & (under > BRIGHT)
    best, run, start = (0, None), 0, 0
    for x, p in enumerate(plate):
        run, start = (run + 1, start) if p else (0, x + 1)
        if run > best[0]:
            best = (run, start)
    width = round(PLATE_W * s)
    return best[1] if best[1] is not None and abs(best[0] - width) <= max(3, round(3 * s)) else None


def _ncc(a: np.ndarray, b: np.ndarray) -> float:
    a, b = a - a.mean(), b - b.mean()
    n = float(np.sqrt((a * a).sum() * (b * b).sum()))
    return float((a * b).sum() / n) if n else 0.0


Reading = tuple[int | None, float, float, int]


def read_digit(gray: np.ndarray, x0: int, glyphs: dict[str, np.ndarray]) -> Reading:
    """(digit, best correlation, margin over the best other digit, best digit) for the cell drawn
    from x0; digit is None when the reading is not accepted (MIN_NCC, MIN_MARGIN)."""
    s = scale(gray.shape[0])
    top = round(BUG_TOP * s)
    cell = gray[top + round(4 * s): top + round(36 * s), x0 - round(6 * s): x0 + round(16 * s)]
    if s != 1:  # back to the templates' 720-line size
        from PIL import Image
        cell = np.asarray(Image.fromarray(cell.astype(np.uint8)).resize(
            (round(cell.shape[1] / s), round(cell.shape[0] / s))), dtype=float)
    best = np.full(10, -1.0)
    for faces in glyphs.values():
        for dy in range(cell.shape[0] - CELL_H + 1):
            for dx in range(cell.shape[1] - CELL_W + 1):
                win = cell[dy:dy + CELL_H, dx:dx + CELL_W]
                for d in range(10):
                    best[d] = max(best[d], _ncc(win, faces[d]))
    order = np.argsort(-best)
    top_d, top_v, second = int(order[0]), float(best[order[0]]), float(best[order[1]])
    ok = top_v >= MIN_NCC and top_v - second >= MIN_MARGIN
    return (top_d if ok else None), round(top_v, 3), round(top_v - second, 3), top_d


def read_frame(gray: np.ndarray, glyphs: dict[str, np.ndarray]) -> dict | None:
    """{home: (digit, ncc, margin), away: ...} for a frame with the plate drawn, else None."""
    x = plate_x(gray)
    if x is None:
        return None
    s = scale(gray.shape[0])
    return {side: read_digit(gray, x + round(off * s), glyphs) for side, off in DIGIT_X.items()}


@dataclass
class Sample:
    frame: int
    t: float
    home: int | None
    away: int | None
    ncc: dict


def changes(samples: list[Sample], first_frame_showing=None) -> tuple[list[dict], dict]:
    """The score changes the held readings show, and a summary. `first_frame_showing(lo, hi, side,
    value)` gives the first frame in (lo, hi] whose reading of `side` is `value` (frame-accurate
    timing); without it a change is timed at the first sample that shows it."""
    held: tuple[int, int] | None = None
    run: list[Sample] = []
    out, odd = [], 0
    for smp in samples:
        key = (smp.home, smp.away)
        if None in key:
            run = []
            continue
        run = run + [smp] if run and (run[-1].home, run[-1].away) == key else [smp]
        if len(run) == STABLE and key != held:
            if held is not None:
                dh, da = key[0] - held[0], key[1] - held[1]
                if sorted((dh, da)) == [0, 1]:
                    side = "home" if dh else "away"
                    first = run[0]
                    frame, t = first.frame, first.t
                    if first_frame_showing and prev_before(samples, first) is not None:
                        lo = prev_before(samples, first)
                        found = first_frame_showing(lo.frame, first.frame, side, key[0] if dh else key[1])
                        if found is not None:
                            frame, t = found
                    conf = float(np.mean([r.ncc[side] for r in run]))
                    out.append({"frame": frame, "t": t, "team": side,
                                "score": {"home": key[0], "away": key[1]}, "confidence": round(conf, 3)})
                else:
                    odd += 1
            held = key
    return out, {"samples": len(samples), "unread": sum(1 for s in samples if None in (s.home, s.away)),
                 "inconsistent": odd, "first_held": None}


def prev_before(samples: list[Sample], smp: Sample) -> Sample | None:
    i = samples.index(smp)
    return samples[i - 1] if i > 0 else None


def score_events(changes_: list[dict]) -> list[dict]:
    """match_event lines for the changes (type `score_change`). A change has no place on the pitch:
    it is placed at the centre mark, where the restart it brings is taken (Law 8)."""
    return [{"id": f"s{n:05d}", "t": c["t"], "frame": c["frame"], "type": "score_change", "team": c["team"],
             "team_confidence": None, "player": None, "receiver": None, "x": 52.5, "y": 34.0,
             "end_x": None, "end_y": None, "outcome": None, "ball_speed_kmh": None, "score": c["score"],
             "source": "vision", "confidence": c["confidence"]}
            for n, c in enumerate(changes_, start=1)]


def read_clip(clip: Path, glyphs: dict[str, np.ndarray] | None = None) -> tuple[list[dict], dict]:
    """Score changes from a staged clip folder (`index.jsonl` and `images/`), and a summary."""
    from PIL import Image
    glyphs = glyphs or load_glyphs()
    rows = [json.loads(x) for x in (clip / "index.jsonl").read_text().splitlines() if x.strip()]
    by_frame = {r["frame"]: r for r in rows}

    def gray(r: dict) -> np.ndarray:
        return np.asarray(Image.open(clip / r["image"]).convert("L"), dtype=float)

    def sample(r: dict) -> Sample:
        got = read_frame(gray(r), glyphs)
        if got is None:
            return Sample(r["frame"], r["t"], None, None, {})
        return Sample(r["frame"], r["t"], got["home"][0], got["away"][0],
                      {k: got[k][1] for k in ("home", "away")})

    def first_showing(lo: int, hi: int, side: str, value: int):
        # The held readings have settled the new score; here only its first frame is looked for, so
        # the best digit is taken even where the goal's pop keeps it under the acceptance bar.
        for f in range(lo + 1, hi + 1):
            if f in by_frame:
                got = read_frame(gray(by_frame[f]), glyphs)
                if got and got[side][3] == value:
                    return f, by_frame[f]["t"]
        return None

    picks = rows[::SAMPLE_FRAMES]
    samples = [sample(r) for r in picks]
    found, summary = changes(samples, first_showing)
    held = next(((s.home, s.away) for s in samples if None not in (s.home, s.away)), None)
    summary["first_held"] = {"home": held[0], "away": held[1]} if held else None
    summary["readings"] = [[x.frame, x.home, x.away] for x in samples]  # for grading digit accuracy
    return score_events(found), summary


def make_glyphs(out: Path = GLYPHS) -> None:
    """Rasterise the ten digits from the system's font files (run once, on a Mac with Helvetica and
    Arial Bold). Only the 24 x 16 rasters are written."""
    from PIL import Image, ImageDraw, ImageFont
    faces = {"helvetica-bold": ("/System/Library/Fonts/Helvetica.ttc", 1),
             "arial-bold": ("/System/Library/Fonts/Supplemental/Arial Bold.ttf", 0)}
    raster = {}
    for name, (path, index) in faces.items():
        font = ImageFont.truetype(path, 16, index=index)
        digits = []
        for d in range(10):
            im = Image.new("L", (CELL_W, CELL_H), 0)
            ImageDraw.Draw(im).text((2, CELL_H / 2), str(d), fill=255, font=font, anchor="lm")
            digits.append(np.asarray(im).tolist())
        raster[name] = digits
    out.write_text(json.dumps({"made_by": "python -m ninety.vision.scorebug --make-glyphs",
                               "size": [CELL_H, CELL_W], "faces": raster}) + "\n")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Read the score from the broadcast's scorebug.")
    ap.add_argument("clip", type=Path, nargs="?", help="a staged clip folder (index.jsonl, images/)")
    ap.add_argument("--out", type=Path)
    ap.add_argument("--summary", type=Path)
    ap.add_argument("--make-glyphs", action="store_true", help="rasterise the digit templates")
    a = ap.parse_args(argv)
    if a.make_glyphs:
        make_glyphs()
        return
    found, summary = read_clip(a.clip)
    if a.out:
        a.out.write_text("".join(json.dumps(e) + "\n" for e in found), encoding="utf-8")
    if a.summary:
        a.summary.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"changes": len(found), **summary}))


if __name__ == "__main__":
    main()
