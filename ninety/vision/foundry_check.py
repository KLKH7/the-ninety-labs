"""Foundry event check: code proposes moments from positions, our Foundry model says what it sees.

The rules were stated before any scored run (docs/eval/foundry-event-check-plan.md). Event counts
from the video are weak while positions are strong, so:

1. **Candidates** (`candidates`), from live-path outputs only: the tracked ball (`tracked.json`),
   the shown frames (`observations.jsonl`, line i is video frame i), the segments (`clip.json`) and
   vision's own detected shots and outs (`detected.jsonl`). Nothing here reads ground truth.
2. **Frames** (`frame_indices`, `crop`): three frames a candidate, by video index, cropped around the
   ball and downscaled to 512 x 288, sent with `detail: low`.
3. **The model** (`foundry_classifier`): gpt-4.1-mini on our own Foundry project (config.FOUNDRY_PROJECT),
   through the same chat client as every agent (ninety/agents/foundry.py), signed in with the run's
   Entra credential. It answers one label, a confidence and a few words of what it saw. It is given
   no number, no side, no time and no viewer input: only the fixed instructions and the frames.
4. **Code counts** (`events_from`): a label at confidence >= ACCEPT counts; one event per moment;
   the side from the end the ball is at (Laws 14, 16, 17), never from the model.

Offline prototype: nothing on the live path calls it (the coordinator decides after the numbers).

    uv run python -m ninety.vision.foundry_check <run> --frames <images dir | hls dir> --out <file>
        [--dry-run] [--cap-usd 0.50]
"""

from __future__ import annotations

import argparse
import asyncio
import io
import json
import math
import subprocess
import sys
import tempfile
import time
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from ninety.intel.scene import PITCH_X
from ninety.vision.events import RIVAL_M
from ninety.vision.restarts import MIN_STILL_S

PITCH_Y = 68.0
GOAL_HALF_M = 3.66  # Law 1: 7.32 m between the posts
GOAL_AREA_DEPTH_M, GOAL_AREA_HALF_M = 5.5, 9.16  # Law 1: 5.5 m deep, 18.32 m wide
FPS = 25

# Design values, stated in the plan before any score; none may change to fit a result.
LINE_M = RIVAL_M  # within the camera's measured ground error of a line, or beyond it
SET_BALL_LINE_M = 3.0  # a still ball this close to a line can be a throw-in or a corner being set
STILL_M = RIVAL_M
SHOT_KMH = 45.0
SHOT_RANGE_M = 35.0
SHOT_WIDE_M = GOAL_HALF_M + 5.0
SPEED_FRAMES = 5  # 0.2 s
MERGE_S = 3.0
OFFSETS_S = {"restart": (0.0, 1.5, 3.0), "shot": (-0.4, 0.4, 1.2)}
CROP_W, CROP_H, OUT_W, OUT_H, JPEG_Q = 768, 432, 512, 288, 80
DETAIL = "low"  # 85 input tokens an image (OpenAI vision guide)
IMAGE_TOKENS = 85
# Input tokens one call reported on 2026-10-27 (a smoke call on a blank frame): the schema and the
# message framing add about 600 to the rule-of-thumb count. The estimate takes the larger.
MEASURED_CALL_IN = 990
ACCEPT = 0.6
DEDUPE_S = {"corner": 10.0, "goal_kick": 10.0, "throw_in": 10.0, "shot": 2.0}
LABELS = ("corner", "goal_kick", "throw_in", "shot", "none")

INSTRUCTIONS = """You are shown three frames, in time order about a second apart, from a synthetic \
football broadcast (computer-rendered players, not a real match). Say which ONE of these the \
frames show:
- corner: the ball placed in or at a corner arc, a player about to kick it, others in the box
- goal_kick: the ball placed in the small goal area, the goalkeeper or a defender about to kick it
- throw_in: a player at the touchline holding the ball with both hands, about to throw it
- shot: a player striking the ball toward the goal, or the ball flying at the goal or the keeper
- none: anything else (open play, a pass, a free kick, a kick-off, a replay, unclear)
Answer only from what is visible in the frames. Reply as JSON: {"label": one of corner, goal_kick, \
throw_in, shot, none; "confidence": 0 to 1, how sure you are; "seen": at most 12 words}."""


class Verdict(BaseModel):
    label: Literal["corner", "goal_kick", "throw_in", "shot", "none"]
    confidence: float = Field(ge=0.0, le=1.0)
    seen: str = Field(max_length=200)


@dataclass
class Clip:
    """A rendered clip as the live path sees it."""

    frames: list[int]  # video index -> match frame
    segments: list[tuple[int, int]]  # [start, end) video indices
    ball_px: dict[int, tuple[float, float]]  # video index -> ball centre in pixels (vision's best)
    ball: dict[int, tuple[float, float]]  # match frame -> tracked ball (x, y) on the pitch
    detected: list[dict]
    size: tuple[int, int] = (1280, 720)

    def index_of(self) -> dict[int, int]:
        return {f: i for i, f in enumerate(self.frames)}

    def segment(self, index: int) -> tuple[int, int]:
        for s, e in self.segments:
            if s <= index < e:
                return s, e
        return index, index + 1


@dataclass
class Candidate:
    family: Literal["restart", "shot"]
    index: int  # video index
    frame: int  # match frame
    why: str
    ball: tuple[float, float] | None


@dataclass
class Checked:
    candidate: Candidate
    indices: list[int]
    label: str | None = None
    confidence: float | None = None
    seen: str = ""
    tokens_in: int = 0
    tokens_out: int = 0
    latency_s: float = 0.0
    cost_usd: float = 0.0
    error: str | None = None


@dataclass
class Spend:
    cap_usd: float
    calls: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    usd: float = 0.0
    latencies: list[float] = field(default_factory=list)


# --- loading ------------------------------------------------------------------------------------

def load_clip(run: Path) -> Clip:
    meta = json.loads((run / "clip.json").read_text())
    starts = [s["index"] for s in meta["segments"]] + [meta["frames"]]
    segments = list(zip(starts[:-1], starts[1:], strict=True))
    frames, ball_px = [], {}
    with (run / "observations.jsonl").open() as fh:
        for i, line in enumerate(fh):
            o = json.loads(line)
            frames.append(int(o["frame"]))
            best = max(o.get("ball") or [], key=lambda b: b.get("score") or 0, default=None)
            if best and (best.get("score") or 0) >= 0.5:
                x0, y0, x1, y1 = best["bbox"]
                ball_px[i] = ((x0 + x1) / 2, (y0 + y1) / 2)
    tracked = json.loads((run / "tracked.json").read_text())
    ball = {int(f["frame"]): (f["ball"]["x"], f["ball"]["y"]) for f in tracked["frames"]
            if f.get("ball") and f["ball"].get("x") is not None}
    detected_path = run / "detected.jsonl"
    detected = [json.loads(x) for x in detected_path.open()] if detected_path.exists() else []
    return Clip(frames, segments, ball_px, ball, detected)


# --- candidates (code, no truth) ----------------------------------------------------------------

def _line_distance(x: float, y: float) -> float:
    """Metres inside the nearest touchline or goal line (negative beyond it)."""
    return min(x, PITCH_X - x, y, PITCH_Y - y)


def _in_goal_area(x: float, y: float) -> bool:
    return abs(y - PITCH_Y / 2) <= GOAL_AREA_HALF_M and min(x, PITCH_X - x) <= GOAL_AREA_DEPTH_M


def _shot_like(p0: tuple[float, float], p1: tuple[float, float], dt: float) -> bool:
    vx, vy = (p1[0] - p0[0]) / dt, (p1[1] - p0[1]) / dt
    if math.hypot(vx, vy) * 3.6 < SHOT_KMH or abs(vx) < 1e-6:
        return False
    goal_x = PITCH_X if vx > 0 else 0.0
    if abs(goal_x - p1[0]) > SHOT_RANGE_M:
        return False
    y_at = p1[1] + vy * (goal_x - p1[0]) / vx
    return abs(y_at - PITCH_Y / 2) <= SHOT_WIDE_M


def candidates(clip: Clip) -> list[Candidate]:
    """Every candidate moment, merged per family within MERGE_S of video."""
    index = clip.index_of()
    raw: list[Candidate] = []
    for s, e in clip.segments:
        at_line = False
        still: list[int] = []
        for i in range(s, e):
            f = clip.frames[i]
            b = clip.ball.get(f)
            if b is None:
                at_line = False
                continue
            near = _line_distance(*b) <= LINE_M
            if near and not at_line:
                raw.append(Candidate("restart", i, f, "at a line", b))
            at_line = near
            # still spell: every position within STILL_M of the spell's running start
            if still and math.dist(clip.ball.get(clip.frames[still[0]], b), b) > STILL_M:
                _close_spell(clip, still, raw)
                still = []
            still.append(i)
            j = i + SPEED_FRAMES
            if j < e:
                b2 = clip.ball.get(clip.frames[j])
                dt = (clip.frames[j] - f) / FPS
                if b2 is not None and dt > 0 and _shot_like(b, b2, dt):
                    raw.append(Candidate("shot", i, f, "fast toward goal", b))
        _close_spell(clip, still, raw)
    for d in clip.detected:
        fam = {"shot": "shot", "out_of_play": "restart"}.get(d.get("type"))
        if fam and int(d["frame"]) in index:
            raw.append(Candidate(fam, index[int(d["frame"])], int(d["frame"]), f"vision {d['type']}",
                                 (d.get("x"), d.get("y")) if d.get("x") is not None else None))
    return merge(raw)


def _close_spell(clip: Clip, spell: list[int], out: list[Candidate]) -> None:
    if len(spell) < MIN_STILL_S * FPS:
        return
    pts = [clip.ball[clip.frames[i]] for i in spell if clip.frames[i] in clip.ball]
    mx = sorted(p[0] for p in pts)[len(pts) // 2]
    my = sorted(p[1] for p in pts)[len(pts) // 2]
    if any(math.dist(p, (mx, my)) > STILL_M for p in pts):
        return
    if _line_distance(mx, my) <= SET_BALL_LINE_M or _in_goal_area(mx, my):
        out.append(Candidate("restart", spell[0], clip.frames[spell[0]], "set ball", (mx, my)))


def merge(raw: Iterable[Candidate]) -> list[Candidate]:
    out: list[Candidate] = []
    last: dict[str, int] = {}
    for c in sorted(raw, key=lambda c: (c.index, c.family)):
        if c.family in last and c.index - last[c.family] <= MERGE_S * FPS:
            continue
        out.append(c)
        last[c.family] = c.index
    return out


def frame_indices(clip: Clip, c: Candidate) -> list[int]:
    s, e = clip.segment(c.index)
    return [min(max(c.index + round(o * FPS), s), e - 1) for o in OFFSETS_S[c.family]]


# --- frames -------------------------------------------------------------------------------------

def crop(image, centre: tuple[float, float] | None) -> bytes:
    """A CROP_W x CROP_H window around `centre` (the frame's centre if None), resized, as JPEG."""
    from PIL import Image

    w, h = image.size
    cx, cy = centre if centre else (w / 2, h / 2)
    x0 = int(min(max(cx - CROP_W / 2, 0), max(w - CROP_W, 0)))
    y0 = int(min(max(cy - CROP_H / 2, 0), max(h - CROP_H, 0)))
    box = image.crop((x0, y0, x0 + min(CROP_W, w), y0 + min(CROP_H, h)))
    buf = io.BytesIO()
    box.convert("RGB").resize((OUT_W, OUT_H), Image.Resampling.LANCZOS).save(buf, "JPEG", quality=JPEG_Q)
    return buf.getvalue()


def images_reader(folder: Path) -> Callable[[list[int]], dict]:
    """Frames from a render's images/NNNNN.jpg."""
    from PIL import Image

    def read(indices: list[int]) -> dict:
        return {i: Image.open(folder / f"{i:05d}.jpg").copy() for i in indices}

    return read


def hls_reader(folder: Path, frames_per_segment: int = 100) -> Callable[[list[int]], dict]:
    """Frames from a bundle's fMP4 HLS rendition (init_0.mp4 + segNNNN.m4s), decoded with ffmpeg one
    segment at a time, so memory stays at a few frames."""
    from PIL import Image

    init = (folder / "init_0.mp4").read_bytes()

    def read(indices: list[int]) -> dict:
        out: dict = {}
        by_seg: dict[int, list[int]] = {}
        for i in sorted(set(indices)):
            by_seg.setdefault(i // frames_per_segment, []).append(i)
        for seg, wanted in by_seg.items():
            with tempfile.TemporaryDirectory() as tmp:
                src = Path(tmp) / "s.mp4"
                src.write_bytes(init + (folder / f"seg{seg:04d}.m4s").read_bytes())
                for i in wanted:
                    dst = Path(tmp) / f"{i}.png"
                    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(src), "-vf",
                                    f"select=eq(n\\,{i % frames_per_segment})", "-frames:v", "1", str(dst)],
                                   check=True, timeout=60)
                    out[i] = Image.open(dst).copy()
        return out

    return read


# --- the model ----------------------------------------------------------------------------------

Classify = Callable[[list[bytes]], Awaitable[tuple[Verdict, int, int]]]


def message_contents(images: list[bytes]) -> list:
    """What the model is sent: the fixed instructions and the frames, nothing else."""
    from agent_framework import Content

    return [Content.from_text(INSTRUCTIONS),
            *(Content.from_data(data=b, media_type="image/jpeg", additional_properties={"detail": DETAIL})
              for b in images)]


def foundry_classifier(client) -> Classify:
    """The classifier over our Foundry chat client (ninety/agents/foundry.py `chat_client`)."""
    from agent_framework import Message

    async def classify(images: list[bytes]) -> tuple[Verdict, int, int]:
        reply = await client.get_response(
            [Message("user", message_contents(images))],
            options={"response_format": Verdict, "temperature": 0.0, "max_tokens": 80},
        )
        value = reply.value if isinstance(getattr(reply, "value", None), Verdict) else \
            Verdict.model_validate_json(reply.text)
        usage = getattr(reply, "usage_details", None) or {}
        return value, int(usage.get("input_token_count") or 0), int(usage.get("output_token_count") or 0)

    return classify


def price_per_token() -> tuple[float, float]:
    """USD per input and output token, the Data Zone meter (the higher), latency_cost.PRICES."""
    from ninety.eval.latency_cost import INPUT_DZ, OUTPUT_DZ, PRICES

    (pi, ui, _), (po, uo, _) = PRICES["items"][INPUT_DZ], PRICES["items"][OUTPUT_DZ]
    return pi / ui, po / uo


def prompt_tokens() -> int:
    """The instructions' tokens at OpenAI's rule of thumb (4 characters a token), rounded up."""
    return math.ceil(len(INSTRUCTIONS) / 4) + 20  # + message and schema framing


def estimate(n: int, out_tokens: int = 40) -> dict:
    pin, pout = price_per_token()
    t_in = n * max(prompt_tokens() + 3 * IMAGE_TOKENS, MEASURED_CALL_IN)
    t_out = n * out_tokens
    return {"calls": n, "tokens_in": t_in, "tokens_out": t_out, "usd": round(t_in * pin + t_out * pout, 4)}


async def check(clip: Clip, cands: list[Candidate], read: Callable[[list[int]], dict], classify: Classify,
                spend: Spend, concurrency: int = 4) -> list[Checked]:
    pin, pout = price_per_token()
    gate = asyncio.Semaphore(concurrency)
    worst = MEASURED_CALL_IN * 2 * pin + 80 * pout  # a call's cost at twice the estimate

    async def one(c: Candidate) -> Checked:
        idx = frame_indices(clip, c)
        row = Checked(c, idx)
        async with gate:
            if spend.usd + worst > spend.cap_usd:
                row.error = "cap reached"
                return row
            imgs = await asyncio.to_thread(read, idx)
            frames = [crop(imgs[i], clip.ball_px.get(i)) for i in idx]
            t0 = time.perf_counter()
            try:
                verdict, t_in, t_out = await classify(frames)
            except Exception as e:  # noqa: BLE001  a failed call is logged and counts as no event
                row.error = f"{type(e).__name__}: {str(e)[:120]}"
                row.latency_s = time.perf_counter() - t0
                return row
            row.latency_s = time.perf_counter() - t0
            row.label, row.confidence, row.seen = verdict.label, verdict.confidence, verdict.seen
            row.tokens_in, row.tokens_out = t_in, t_out
            row.cost_usd = t_in * pin + t_out * pout
            spend.calls += 1
            spend.tokens_in += t_in
            spend.tokens_out += t_out
            spend.usd += row.cost_usd
            spend.latencies.append(row.latency_s)
            return row

    return list(await asyncio.gather(*(one(c) for c in cands)))


# --- code counts --------------------------------------------------------------------------------

def _attacking(x: float) -> str:
    return "home" if x > PITCH_X / 2 else "away"


def side(label: str, x: float | None) -> str | None:
    """The club, from the end the ball is at (each club attacks one end all match, home toward
    x = PITCH_X): a corner and a shot the attacking club's, a goal kick the defending club's (Laws
    16, 17); a throw-in's is not known from the end."""
    if x is None or label == "throw_in":
        return None
    att = _attacking(x)
    return att if label in ("corner", "shot") else {"home": "away", "away": "home"}[att]


def events_from(clip: Clip, rows: list[Checked]) -> list[dict]:
    out: list[dict] = []
    last: dict[str, int] = {}
    for r in sorted(rows, key=lambda r: r.candidate.index):
        if r.label in (None, "none") or (r.confidence or 0) < ACCEPT:
            continue
        c = r.candidate
        if r.label in last and c.index - last[r.label] <= DEDUPE_S[r.label] * FPS:
            continue
        last[r.label] = c.index
        x, y = c.ball if c.ball else (None, None)
        typ = "shot" if r.label == "shot" else "set_piece"
        out.append({
            "id": f"fc-{len(out) + 1:04d}", "t": round(c.frame / FPS, 2), "frame": c.frame,
            "video_index": c.index, "type": typ, "restart": None if typ == "shot" else r.label,
            "team": side(r.label, x), "x": x, "y": y, "source": "foundry_check",
            "confidence": r.confidence, "candidate": c.why,
        })
    return out


# --- CLI ----------------------------------------------------------------------------------------

async def _live(clip: Clip, cands: list[Candidate], read, cap: float) -> tuple[list[Checked], Spend]:
    from ninety.agents import credentials, foundry

    spend = Spend(cap)
    async with credentials.new_credential() as credential:
        await credentials.sign_in(credential)
        rows = await check(clip, cands, read, foundry_classifier(foundry.chat_client(credential)), spend)
    return rows, spend


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("run", type=Path)
    ap.add_argument("--frames", type=Path, required=True, help="images/ dir or an HLS rendition dir")
    ap.add_argument("--out", type=Path)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--cap-usd", type=float, default=0.50)
    a = ap.parse_args(argv)
    clip = load_clip(a.run)
    cands = candidates(clip)
    est = estimate(len(cands))
    by = {}
    for c in cands:
        by[c.why] = by.get(c.why, 0) + 1
    print(json.dumps({"candidates": len(cands), "by_reason": by, "estimate": est}))
    if a.dry_run:
        return 0
    if est["usd"] > a.cap_usd:
        print(f"estimate ${est['usd']} is above the cap ${a.cap_usd}: not calling", file=sys.stderr)
        return 1
    hls = (a.frames / "init_0.mp4").exists()
    read = hls_reader(a.frames) if hls else images_reader(a.frames)
    rows, spend = asyncio.run(_live(clip, cands, read, a.cap_usd))
    events = events_from(clip, rows)
    lat = sorted(spend.latencies)
    record = {
        "spend": {"calls": spend.calls, "tokens_in": spend.tokens_in, "tokens_out": spend.tokens_out,
                  "usd": round(spend.usd, 5), "cap_usd": spend.cap_usd,
                  "latency_p50_s": round(lat[len(lat) // 2], 3) if lat else None,
                  "latency_p95_s": round(lat[min(len(lat) - 1, int(0.95 * len(lat)))], 3) if lat else None},
        "estimate": est,
        "rows": [{**asdict(r), "candidate": asdict(r.candidate)} for r in rows],
        "events": events,
    }
    if a.out:
        a.out.parent.mkdir(parents=True, exist_ok=True)
        a.out.write_text(json.dumps(record, indent=1) + "\n")
    print(json.dumps(record["spend"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
