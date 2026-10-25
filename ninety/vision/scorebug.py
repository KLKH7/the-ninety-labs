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
the plate, 16 px semi-bold sans-serif, centred on the plate's middle row. Which digit is home's
comes from the renderer's draw order, never from a kit: render.js draws the home code, the home
digit, a dash, the away digit and the away code, left to right, from `score = [home, away]`
(ninety/render/clip.py), so the left digit is home's.

**Reading a digit.** Each digit cell is compared, by normalised cross-correlation over a few pixels
of shift, with templates of the ten digits rasterised from the two faces Chromium's `sans-serif`
resolves to where we render: Helvetica Bold on the Mac; on the Linux render pods most digits are
Arial Bold's shapes but the 1 is DejaVu Sans Bold's (found on the demo's development check, before
any validation score; docs/eval/scorebug-plan.md), so all three faces are compared
(`scorebug_glyphs.json`, made by `--make-glyphs`; only the 24 x 16 digit rasters are committed,
no font). A reading counts when its best
correlation is at least MIN_NCC and beats the best other digit by MIN_MARGIN.

**A change of score.** The digits are read every SAMPLE_FRAMES frames. A score holds once STABLE
samples in a row agree, so the goal's half-second "pop" of the scorer's digit and the panel's slide
(render.js: 0.5 s and 0.42 s) are never read as a score. A goal adds one to one side (Law 10), so a
held score that differs from the last by exactly one goal on one side is a `score_change`, timed at
the first frame that shows it (found frame by frame back to the sample before). Any other
difference (a digit lost behind a stinger, a misread) changes nothing and is counted.

`confidence` is the new digit's mean correlation over its holding samples: a score, not a
probability.

**Reconciling with vision's goals** (`reconcile`; docs/eval/scorebug-plan.md, W stated before any
validation score). A score change with a vision goal of that side within W confirms it, their
confidences combined as independent evidence. A score change with none adds a goal there, the
scorer by look-back: the side's last detected shot before it within LOOKBACK_S with nothing of the
other side between, named only as that shot's `player` (already identity-gated, events.attribute),
the assist the last completed pass to him before it. A vision goal no score change confirms is held
back. A scoreline is shown only from `score_change` events.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field
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
# The clock panel (#ececea) right of the plate is 74 px wide, its time dark text over part of it; at
# least this much of it reads light in every column's median (design).
CLOCK_MIN = 40
CELL_H, CELL_W = 24, 16  # a template: one 16 px digit with its margins
# Acceptance (design, stated before any validation score, docs/eval/scorebug-plan.md): on pod-rendered
# training frames a 0 reads at 0.99 with the next digit at 0.87; the goal's pop reads near 0.79.
MIN_NCC, MIN_MARGIN = 0.85, 0.05
SAMPLE_FRAMES = FPS  # about once a second
STABLE = 2  # samples in a row: a reading held for a second outlasts the 0.5 s pop and 0.42 s slide
W_S = 1.0  # event_score.WINDOW_S: the renderer shows a goal's score from its own frame
LOOKBACK_S = 10.0  # design (not measured): well over a shot's 1 to 3 s flight to the goal
OTHER_SIDE = frozenset({"pass", "shot", "possession_change", "tackle", "interception"})


def scale(height: int) -> float:
    return round(height / 720 * 100) / 100


def load_glyphs(path: Path = GLYPHS) -> dict[str, np.ndarray]:
    raw = json.loads(path.read_text())
    return {face: np.asarray(digits, dtype=float) for face, digits in raw["faces"].items()}


def plate_x(gray: np.ndarray) -> int | None:
    """The plate's left edge in this frame, or None when no plate is drawn (a stinger, a cut).
    The plate is PLATE_W columns that read as plate (dark middle, bright underline) ending where the
    light clock panel begins: render.js always draws the clock right of the plate. Its left edge
    is not looked for, since a dark crowd behind a white board edge can read as plate beside it."""
    s = scale(gray.shape[0])
    top, h = round(BUG_TOP * s), round(BUG_H * s)
    span = round((SEARCH_W + PLATE_W + CLOCK_MIN) * s)
    under = gray[top + round(UNDERLINE * s): top + h, :span].mean(axis=0)
    middle = np.median(gray[top + round(2 * s): top + round(35 * s), :span], axis=0)
    plate = (middle < DARK) & (under > BRIGHT)
    clock = middle > BRIGHT
    width, light = round(PLATE_W * s), round(CLOCK_MIN * s)
    for end in range(width, len(plate) - light + 1):
        if plate[end - width:end].all() and clock[end:end + light].all():
            return end - width
    return None


def _ncc(a: np.ndarray, b: np.ndarray) -> float:
    a, b = a - a.mean(), b - b.mean()
    n = float(np.sqrt((a * a).sum() * (b * b).sum()))
    return float((a * b).sum() / n) if n else 0.0


Reading = tuple[int | None, float, float, int, list[float]]


def read_digit(gray: np.ndarray, x0: int, glyphs: dict[str, np.ndarray]) -> Reading:
    """(digit, best correlation, margin over the best other digit, best digit, each digit's best
    correlation) for the cell drawn from x0; digit is None when the reading is not accepted
    (MIN_NCC, MIN_MARGIN)."""
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
    return (top_d if ok else None), round(top_v, 3), round(top_v - second, 3), top_d, best.round(3).tolist()


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
    scores: dict = field(default_factory=dict)  # side -> each digit's best correlation
    settled: tuple | None = None  # (home, away) as `changes` read it, the constrained reading included


def settle(smp: Sample, side: str, held: tuple[int, int] | None) -> int | None:
    """The side's digit: the free reading when accepted; otherwise, with a score held, whichever of
    the held digit and one more (a goal adds exactly one, Law 10) clears MIN_NCC and leads the other
    by MIN_MARGIN. Two hypotheses are told apart where ten may not be (a 3 is near an 8)."""
    free = smp.home if side == "home" else smp.away
    if free is not None or held is None or side not in smp.scores:
        return free
    h = held[0] if side == "home" else held[1]
    sc = smp.scores[side]
    a, b = sc[h], (sc[h + 1] if h + 1 < 10 else -1.0)
    digit, top, other = (h, a, b) if a >= b else (h + 1, b, a)
    return digit if top >= MIN_NCC and top - other >= MIN_MARGIN else None


def changes(samples: list[Sample], first_frame_showing=None,
            held_start: tuple[int, int] | None = None) -> tuple[list[dict], dict]:
    """The score changes the held readings show, and a summary. `first_frame_showing(lo, hi, side,
    value)` gives the first frame in (lo, hi] whose reading of `side` is `value` (frame-accurate
    timing); without it a change is timed at the first sample that shows it. `held_start` is the
    score already held when the footage starts (a continuous broadcast read in pieces)."""
    held: tuple[int, int] | None = held_start
    last_held: Sample | None = None  # the last sample that read the held score
    run: list[Sample] = []
    out, odd, read_out = [], 0, False

    def read_event(run: list[Sample], key: tuple[int, int]) -> dict:
        conf = float(np.mean([np.mean(list(r.ncc.values())) for r in run]))
        return {"frame": run[0].frame, "t": run[0].t, "team": None,
                "score": {"home": key[0], "away": key[1]}, "confidence": round(conf, 3)}

    for smp in samples:
        key = (settle(smp, "home", held), settle(smp, "away", held))
        smp.settled = key
        if None in key:
            run = []
            continue
        if key == held:
            last_held = smp
        run = run + [smp] if run and run[-1].settled == key else [smp]
        if len(run) == STABLE and key == held and not read_out:
            out.append(read_event(run, key))  # the score held when the footage starts, as read
            read_out = True
        if len(run) == STABLE and key != held:
            if held is None:  # the first score held: what the bug shows when the footage starts
                out.append(read_event(run, key))
                read_out = True
            else:
                dh, da = key[0] - held[0], key[1] - held[1]
                if sorted((dh, da)) == [0, 1]:
                    side = "home" if dh else "away"
                    first = run[0]
                    frame, t = first.frame, first.t
                    # Searched from the last sample that still read the old score: an unread sample
                    # between (the pop, a stinger) may already be after the goal.
                    if first_frame_showing and last_held is not None:
                        value = key[0] if dh else key[1]
                        found = first_frame_showing(last_held.frame, first.frame, side, value)
                        if found is not None:
                            frame, t = found
                    conf = float(np.mean([r.scores[side][key[0] if dh else key[1]] if r.scores
                                          else r.ncc[side] for r in run]))
                    out.append({"frame": frame, "t": t, "team": side,
                                "score": {"home": key[0], "away": key[1]}, "confidence": round(conf, 3)})
                    held, last_held = key, smp
                else:
                    # Not one goal on one side: a misread (a two-digit score is wider than the cell,
                    # so 10 can read as 1), counted and never adopted, so later goals still count
                    # from the score last held.
                    odd += 1
                continue
            held, last_held = key, smp
    return out, {"samples": len(samples), "unread": sum(1 for s in samples if None in (s.settled or (None,))),
                 "inconsistent": odd, "first_held": None, "last_held": list(held) if held else None}


def score_events(changes_: list[dict]) -> list[dict]:
    """match_event lines: the first score held (`score_read`, no side: so a viewer joining at any
    point sees the score) and each change (`score_change`, the side that scored). Neither has a
    place on the pitch: both are placed at the centre mark, where a goal's restart is taken (Law 8).
    `team_confidence` of a change is the reader's: its side is which digit changed, a pixel reading."""
    out = []
    for n, c in enumerate(changes_, start=1):
        e = {"id": f"s{n:05d}", "t": c["t"], "frame": c["frame"],
             "type": "score_read" if c["team"] is None else "score_change"}
        if c["team"] is not None:
            e |= {"team": c["team"], "team_confidence": c["confidence"]}
        e |= {"player": None, "receiver": None, "x": 52.5, "y": 34.0, "end_x": None, "end_y": None,
              "outcome": None, "ball_speed_kmh": None, "score": c["score"], "source": "vision",
              "confidence": c["confidence"]}
        out.append(e)
    return out


def look_back(events: list[dict], team: str, t: float) -> tuple[dict | None, dict | None]:
    """(shot, assist pass): the side's last detected shot before t within LOOKBACK_S with no event of
    the other side between, and the last completed pass to its shooter before it, in that attack."""
    before = sorted((e for e in events if e["t"] <= t), key=lambda e: e["t"])
    shot, cut = None, None
    for e in reversed(before):
        if t - e["t"] > LOOKBACK_S:
            break
        if e.get("team") != team and e["type"] in OTHER_SIDE:
            cut = e
            break
        if e["type"] == "shot" and e.get("team") == team and shot is None:
            shot = e
    if shot is None or not shot.get("player"):
        return shot, None
    start = cut["t"] if cut else t - LOOKBACK_S
    passes = [e for e in before if start < e["t"] < shot["t"] and e["type"] == "pass"
              and e.get("team") == team and e.get("outcome") == "success"
              and e.get("receiver") == shot["player"]]
    return shot, (passes[-1] if passes else None)


def reconcile(events: list[dict], score_events_: list[dict]) -> tuple[list[dict], dict]:
    """The events with each score change confirming, adding or holding back a goal (see above). A
    `score_read` stays in the scorebug's own file: it has no side, which every detected event has."""
    score_changes = [c for c in score_events_ if c["type"] == "score_change"]
    if not any(c["type"] == "score_read" for c in score_events_):
        # No score was ever read (a fixed tactical view draws no bug, or none was legible): the
        # scorebug says nothing, so no goal is confirmed, added or held back.
        return list(events), {"confirmed": 0, "added": 0, "held": [], "scorebug": "unread"}
    goals = [e for e in events if e["type"] == "goal"]
    used: set[str] = set()
    out = [e for e in events if e["type"] != "goal"]
    confirmed, added = 0, 0
    for c in score_changes:
        near = sorted((g for g in goals if g["team"] == c["team"] and g["id"] not in used
                       and abs(g["t"] - c["t"]) <= W_S), key=lambda g: abs(g["t"] - c["t"]))
        if near:
            g = dict(near[0])
            used.add(g["id"])
            a, b = g.get("confidence") or 0.0, c["confidence"] or 0.0
            g["confidence"] = round(1 - (1 - a) * (1 - b), 3)
            out.append(g)
            confirmed += 1
            continue
        shot, assist = look_back(events, c["team"], c["t"])
        added += 1
        out.append({"id": f"g{added:05d}", "t": c["t"], "frame": c["frame"], "type": "goal",
                    "team": c["team"], "team_confidence": c["confidence"],
                    "player": shot.get("player") if shot else None,
                    "receiver": None, "assist": assist.get("player") if assist else None,
                    "x": ev_goal_x(c["team"]), "y": 34.0, "end_x": None, "end_y": None, "outcome": None,
                    "ball_speed_kmh": None, "source": "vision", "confidence": c["confidence"]})
    held = [g["id"] for g in goals if g["id"] not in used]
    out += score_changes
    out.sort(key=lambda e: (e["frame"], e["type"]))
    return out, {"confirmed": confirmed, "added": added, "held": held}


def ev_goal_x(team: str) -> float:
    """The goal line a side scores on (home attacks x = 105, ninety/vision/events.py): a goal is the
    ball over that line between the posts (Law 10), where an added goal is placed."""
    return 105.0 if team == "home" else 0.0


def read_clip(clip: Path, glyphs: dict[str, np.ndarray] | None = None,
              held: tuple[int, int] | None = None) -> tuple[list[dict], dict]:
    """Score changes from a staged clip folder (`index.jsonl` and `images/`), and a summary. `held`:
    the score held at the end of the footage just before this (a continuous broadcast in pieces)."""
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
                      {k: got[k][1] for k in ("home", "away")}, {k: got[k][4] for k in ("home", "away")})

    def first_showing(lo: int, hi: int, side: str, value: int):
        # The held readings have settled the new score; here only its first frame is looked for, so
        # the best digit is taken even where the goal's pop keeps it under the acceptance bar.
        for f in range(lo + 1, hi + 1):
            if f in by_frame:
                got = read_frame(gray(by_frame[f]), glyphs)
                if got and got[side][3] == value:
                    return f, by_frame[f]["t"]
        return None

    # A sample every SAMPLE_FRAMES match frames, and the first frame after each cut (the frame
    # numbers jump there), so a clip with cuts is sampled by time, not by picture count.
    picks, last, prev = [], None, None
    for r in rows:
        if last is None or r["frame"] - last >= SAMPLE_FRAMES or r["frame"] != prev + 1:
            picks.append(r)
            last = r["frame"]
        prev = r["frame"]
    samples = [sample(r) for r in picks]
    found, summary = changes(samples, first_showing, held)
    first = next((x.settled for x in samples if x.settled and None not in x.settled), None)
    summary["first_held"] = {"home": first[0], "away": first[1]} if first else None
    # For grading digit accuracy: each sample as read, the constrained reading included.
    summary["readings"] = [[x.frame, *(x.settled or (None, None))] for x in samples]
    return score_events(found), summary


def make_glyphs(out: Path = GLYPHS, dejavu: str | None = None) -> None:
    """Rasterise the ten digits from font files (run once, on a Mac with Helvetica and Arial Bold,
    and DejaVu Sans Bold from matplotlib's wheel, the vision group's: `--dejavu <path>`). Only the
    24 x 16 rasters are written."""
    from PIL import Image, ImageDraw, ImageFont
    faces = {"helvetica-bold": ("/System/Library/Fonts/Helvetica.ttc", 1),
             "arial-bold": ("/System/Library/Fonts/Supplemental/Arial Bold.ttf", 0)}
    if dejavu:
        faces["dejavu-bold"] = (dejavu, 0)
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
    ap.add_argument("--dejavu", help="with --make-glyphs: matplotlib's DejaVuSans-Bold.ttf")
    ap.add_argument("--held", help="the score held when this footage starts, home-away (e.g. 2-1)")
    ap.add_argument("--events", type=Path, help="detected.jsonl: reconcile its goals with the score changes")
    ap.add_argument("--reconciled", type=Path, help="where to write the reconciled events (with --events)")
    a = ap.parse_args(argv)
    if a.make_glyphs:
        make_glyphs(dejavu=a.dejavu)
        return
    held = tuple(int(v) for v in a.held.split("-")) if a.held else None
    found, summary = read_clip(a.clip, held=held)
    if a.out:
        a.out.write_text("".join(json.dumps(e) + "\n" for e in found), encoding="utf-8")
    if a.events:
        detected = [json.loads(x) for x in a.events.read_text().splitlines() if x.strip()]
        merged, summary["reconcile"] = reconcile(detected, found)
        if a.reconciled:
            a.reconciled.write_text("".join(json.dumps(e) + "\n" for e in merged), encoding="utf-8")
    if a.summary:
        a.summary.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"changes": len(found), **summary}))


if __name__ == "__main__":
    main()
