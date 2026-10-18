"""Render one seeded clip: simulate the match, film it, write images and ground truth.

Output directory layout:

    clip.json       seed, split, window, every render parameter, player looks, tool versions
    meta.json       the data contract's clip metadata: fps, seed, roster (id, team, role), score
    events.jsonl    ground-truth match events inside the clip window (match_event schema)
    frames.jsonl    one row per frame (frame schema): positions, camera, boxes, visibility, keypoints
    images/NNNNN.jpg
    clip.mp4        only with --mp4 and ffmpeg on PATH (viewing copy; training reads the JPEGs)
"""

from __future__ import annotations

import base64
import functools
import http.server
import json
import math
import random
import shutil
import subprocess
import threading
from collections import Counter
from contextlib import contextmanager
from pathlib import Path

from ninety.match.clock import match_clock
from ninety.render import RENDERER_VERSION
from ninety.render.camera import Camera, Director, blur_vector
from ninety.render.params import RenderParams, sample_params
from ninety.render.scene import (
    Gait,
    advance_gaits,
    ball_parts,
    body_parts,
    crowded_start,
    drawn_ball,
    parts_box,
    project_keypoints,
    sample_looks,
)
from ninety.render.splits import split_of
from ninety.sim.engine import FORMATION, FPS, PITCH_X, PITCH_Y, simulate

ROOT = Path(__file__).resolve().parents[2]
WEB = ROOT / "web"
THREE_MODULE = WEB / "node_modules" / "three" / "build" / "three.module.js"
CHROMIUM_ARGS = [
    "--use-gl=angle",
    "--use-angle=swiftshader",
    "--enable-unsafe-swiftshader",
    "--disable-gpu-driver-bug-workarounds",
]
WARMUP = 2 * FPS  # frames simulated before the window so the camera and gaits settle
WINDOW_DRAWS = 50  # seeded windows tried for one with the ball on the pitch (choose_start)


class RenderUnavailable(RuntimeError):
    """three.js or Chromium is missing; the message says how to install them."""


class _Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args) -> None:  # noqa: D401 - silence the access log
        pass


@contextmanager
def _serve(directory: Path):
    handler = functools.partial(_Quiet, directory=str(directory))
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_address[1]}"
    finally:
        httpd.shutdown()
        httpd.server_close()


@contextmanager
def browser_page(gpu: bool = False):
    """A Chromium page with the renderer loaded. Software GL by default, so pixels are reproducible."""
    if not THREE_MODULE.exists():
        raise RenderUnavailable("three.js is not installed: run `npm ci --prefix web`")
    try:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import sync_playwright
    except ImportError as e:  # pragma: no cover - playwright is a project dependency
        raise RenderUnavailable("playwright is not installed: run `uv sync`") from e
    with _serve(WEB) as base, sync_playwright() as pw:
        try:
            browser = pw.chromium.launch(args=[] if gpu else CHROMIUM_ARGS)
        except PlaywrightError as e:
            raise RenderUnavailable(
                f"Chromium did not start ({e.message.splitlines()[0]}): "
                "run `uv run playwright install chromium`"
            ) from e
        try:
            page = browser.new_page()
            errors: list[str] = []
            page.on("pageerror", lambda exc: errors.append(str(exc)))
            page.goto(f"{base}/render/index.html")
            page.wait_for_function("window.ninety && window.ninety.ready", timeout=30_000)
            if errors:
                raise RuntimeError(f"renderer page error: {errors[0]}")
            yield page, browser.version
        finally:
            browser.close()


BOOT = "#1a1a1a"


def kit_colors(p: RenderParams, team: str, role: str) -> dict:
    kit = {
        ("home", False): p.home_kit,
        ("away", False): p.away_kit,
        ("home", True): p.home_gk,
        ("away", True): p.away_gk,
    }[(team, role == "GK")]
    return {"shirt": kit.shirt, "shorts": kit.shorts, "socks": kit.socks, "boots": BOOT}


def _appearance(lk, p: RenderParams) -> dict:
    """What the page needs to draw one player. Keepers stay solid, so they never match a team pattern."""
    pattern = "solid" if lk.role == "GK" else (p.home_pattern if lk.team == "home" else p.away_pattern)
    return {
        "id": lk.id,
        "colors": {**kit_colors(p, lk.team, lk.role), "skin": lk.skin, "hair": lk.hair},
        "pattern": pattern,
        "number": int(lk.id[1:]),
    }


def choose_start(
    frames: list[dict], p: RenderParams, n: int, seed: int, earliest_s: float, latest_s: float
) -> int:
    """A seeded random window, redrawn (from the same seeded sequence, so still reproducible) while
    the ball is off the pitch for all of it: a dead ball lying behind a goal line or touchline
    waiting for a restart is off camera, so such a clip has no ball to label or check."""
    earliest, latest = int(earliest_s * FPS), int(latest_s * FPS)
    if p.occlusion == "crowded":
        return crowded_start(frames, n, max(earliest, WARMUP), latest)
    rng = random.Random(f"window-{seed}")
    for _ in range(WINDOW_DRAWS):
        start = rng.randint(max(earliest, WARMUP), latest)
        if any(_on_pitch(f["ball"]) for f in frames[start : start + n]):
            break
    return start


def _on_pitch(b: dict) -> bool:
    """The ball within the pitch's lines (Law 1)."""
    return 0.0 <= b["x"] <= PITCH_X and 0.0 <= b["y"] <= PITCH_Y


def render_clip(
    seed: int,
    out: Path,
    seconds: float = 10.0,
    start_s: float | None = None,
    overrides: dict | None = None,
    mp4: bool = False,
    gpu: bool = False,
    write_images: bool = True,
    page=None,
) -> dict:
    """Render one clip and return its clip.json content."""
    overrides = dict(overrides or {})
    p = sample_params(seed, **overrides)
    n = int(round(seconds * p.fps))
    if p.fps != FPS:
        raise ValueError(f"the simulator runs at {FPS} fps")
    earliest_s, latest_s = 10.0, 240.0
    sim_end_s = (start_s if start_s is not None else latest_s) + seconds + 1
    match = simulate(seed, sim_end_s / 60)
    frames = match.frames
    start = (
        int(round(start_s * FPS))
        if start_s is not None
        else choose_start(frames, p, n, seed, earliest_s, latest_s)
    )
    if start + n > len(frames):
        raise ValueError("clip window runs past the simulated match")

    roles = {
        f"{team[0]}{i + 1}": role for team in ("home", "away") for i, (role, _, _) in enumerate(FORMATION)
    }
    players0 = [{**pl, "role": roles[pl["id"]]} for pl in frames[0]["players"]]
    looks = sample_looks(players0, seed)
    objects = [_appearance(lk, p) for lk in looks]
    objects.append({"id": "ball", "colors": {"ball": "#f2f2f2"}})
    by_id = {lk.id: lk for lk in looks}

    out = Path(out)
    if out.exists():
        shutil.rmtree(out)
    (out / "images").mkdir(parents=True)

    goals = [e for e in match.events if e["type"] == "goal"]
    goal_at = {e["frame"]: e for e in goals}
    t0, t1 = frames[start]["t"], frames[start + n - 1]["t"]
    clip = {
        "clip_id": f"seed{seed}",
        "seed": seed,
        "split": split_of(seed),
        "start_frame": start,
        "frames": n,
        "fps": p.fps,
        "t_start": t0,
        "t_end": t1,
        "renderer": {
            "version": RENDERER_VERSION,
            "three": _three_version(),
            "gl": "swiftshader" if not gpu else "gpu",
        },
        "params": p.to_dict(),
        "overrides": overrides,
        "looks": [lk.__dict__ for lk in looks],
        "pixel_convention": "origin at the top-left image corner; pixel (i, j) covers [i, i+1] x [j, j+1]",
    }

    ctx = browser_page(gpu) if page is None else _nullctx(page)
    with ctx as (pg, chromium_version):
        clip["renderer"]["chromium"] = chromium_version
        info = pg.evaluate(
            "cfg => window.ninety.init(cfg)", {"seed": seed, "params": p.to_dict(), "objects": objects}
        )
        clip["scorebug_px"] = info["bugRect"]
        director = Director(p.camera, p.width, p.height, p.fps, seed, cuts=p.camera_cut)
        gaits = {lk.id: Gait() for lk in looks}
        prev_xy: dict[str, tuple[float, float]] = {}
        prev_cam: Camera | None = None
        spin_angle = 0.0
        spin_axis = None
        rows = []
        for fi in range(max(0, start - WARMUP), start + n):
            fr = frames[fi]
            advance_gaits(gaits, prev_xy, fr, 1 / FPS)
            ball = drawn_ball(fr)
            actors = [(pl["x"], pl["y"], pl.get("action", "")) for pl in fr["players"]]
            # The snapshot of a goal already has the ball on the centre spot. The event
            # carries the mouth it crossed, and the frame before it carries the pace.
            ev = goal_at.get(fr["frame"])
            goal_arg = None
            if ev is not None and fi > 0:
                prevb = frames[fi - 1]["ball"]
                side = "L" if ev["x"] < 52.5 else "R"
                z = min(max(prevb["z"] + 0.11, 0.25), 2.15)
                speed = math.hypot(prevb["vx"], prevb["vy"], prevb.get("vz", 0.0))
                goal_arg = (side, ev["y"], z, speed)
            cam = director.step(ball[0], ball[1], actors, goal_arg)
            blur = blur_vector(prev_cam, cam, p.motion_blur)
            prev_cam = cam
            bvx, bvy = fr["ball"].get("vx", 0.0), fr["ball"].get("vy", 0.0)
            spd = math.hypot(bvx, bvy)
            # v/r is the true roll, and at 25 fps it aliases into a flicker. Cap it, and
            # do not let a touch that reverses the velocity flip the panels.
            if spd > 0.4:
                ax, ay = -bvy / spd, bvx / spd
                if spin_axis is not None and ax * spin_axis[0] + ay * spin_axis[1] < 0:
                    ax, ay = -ax, -ay
                if spin_axis is None:
                    spin_axis = (ax, ay)
                else:
                    sx = spin_axis[0] * 0.75 + ax * 0.25
                    sy = spin_axis[1] * 0.75 + ay * 0.25
                    nrm = math.hypot(sx, sy) or 1.0
                    spin_axis = (sx / nrm, sy / nrm)
                spin_angle += min(spd / 0.11, 9.0) / FPS
            spin = (
                (round(spin_axis[0], 4), round(spin_axis[1], 4), round(spin_angle, 4))
                if spin_axis is not None
                else None
            )
            if fi < start:
                continue
            index = fi - start
            spec_objects, row_players = [], []
            for pl in fr["players"]:
                g = gaits[pl["id"]]
                meet = g.action in ("strike", "foot", "thigh", "chest", "head", "hands")
                parts = body_parts(
                    pl["x"], pl["y"], by_id[pl["id"]], g, ball if meet else None
                )
                spec_objects.append(
                    {
                        "id": pl["id"],
                        "parts": parts,
                        "box": parts_box(cam, parts),
                        "heading": gaits[pl["id"]].heading,
                    }
                )
                row_players.append(pl)
            bparts = ball_parts(*ball, spin)
            spec_objects.append({"id": "ball", "parts": bparts, "box": parts_box(cam, bparts)})
            kps = project_keypoints(cam)
            score = [
                sum(1 for g in goals if g["team"] == team and g["t"] <= fr["t"]) for team in ("home", "away")
            ]
            clock = match_clock(fr["t"])
            recent = [g for g in goals if 0 <= fr["t"] - g["t"] <= 2.5]
            last = recent[-1] if recent else None
            res = pg.evaluate(
                "s => window.ninety.frame(s)",
                {
                    "index": index,
                    "camera": {"position": list(cam.position), "R": cam.R, "fov_v_deg": cam.fov_v_deg},
                    "objects": spec_objects,
                    "keypoints": [[k["px"], k["py"]] for k in kps],
                    "blur": list(blur),
                    "score": score,
                    "clock": clock,
                    "goal_age": round(fr["t"] - last["t"], 3) if last else None,
                    "goal_side": 0 if last and last["team"] == "home" else (1 if last else None),
                    "net": director.net_view(),
                    "want_image": write_images,
                },
            )
            image = f"images/{index:05d}.jpg"
            if write_images:
                (out / image).write_bytes(base64.b64decode(res["image"].split(",", 1)[1]))
            rows.append(
                _frame_row(fr, cam, ball, row_players, res, kps, blur, image, clip["clip_id"], director.angle)
            )

    with open(out / "frames.jsonl", "w") as f:
        for r in rows:
            f.write(json.dumps(r, separators=(",", ":")) + "\n")
    events = [e for e in match.events if t0 <= e["t"] <= t1]
    with open(out / "events.jsonl", "w") as f:
        for e in events:
            f.write(json.dumps(e) + "\n")
    clip["event_counts"] = dict(Counter(e["type"] for e in events))
    # The data contract's metadata (docs/DATA_CONTRACT.md), so `ninety-validate` can check the clip.
    # The score counts the goals in this clip's events, the same events the validator adds up (C9).
    meta = {
        "fps": p.fps,
        "seed": seed,
        "clip_id": clip["clip_id"],
        # A window cut from a longer match: events before or after it are not in the clip.
        "window": {"first_frame": rows[0]["frame"], "last_frame": rows[-1]["frame"]},
        "roster": [{k: r[k] for k in ("id", "team", "role")} for r in match.roster],
        "score": {team: sum(1 for e in events if e["type"] == "goal" and e["team"] == team)
                  for team in ("home", "away")},
    }
    (out / "meta.json").write_text(json.dumps(meta, indent=2))
    clip["ball_visibility_lt_0_5"] = round(
        sum(1 for r in rows if r["ball"]["visibility"] < 0.5 and r["ball"]["bbox"])
        / max(1, sum(1 for r in rows if r["ball"]["bbox"])),
        4,
    )
    (out / "clip.json").write_text(json.dumps(clip, indent=2))
    if mp4:
        _encode_mp4(out, p.fps)
    return clip


@contextmanager
def _nullctx(page):
    yield page, page.context.browser.version


def _three_version() -> str | None:
    pkg = THREE_MODULE.parents[1] / "package.json"
    return json.loads(pkg.read_text())["version"] if pkg.exists() else None


def _r(v: float, nd: int = 3) -> float:
    return round(v, nd)


def _frame_row(
    fr: dict,
    cam: Camera,
    ball: tuple[float, float, float],
    players: list[dict],
    res: dict,
    kps: list[dict],
    blur: tuple[float, float],
    image: str,
    clip_id: str,
    angle: str,
) -> dict:
    objs = res["objects"]

    def labels(oid: str) -> dict:
        o = objs[oid]
        full, vis = o["full"], o["visible"]
        return {
            "bbox": o["bbox"],
            "visibility": _r(vis / full, 4) if full else 0.0,
            "pixels": full,
        }

    row_players = []
    for pl in players:
        foot = cam.project((pl["x"], pl["y"], 0.0))
        row_players.append(
            {**pl, **labels(pl["id"]), "foot_px": [_r(foot[0]), _r(foot[1])] if foot else None}
        )
    centre = cam.project((ball[0], ball[1], ball[2] + 0.11))
    ball_row = {
        "x": _r(ball[0]),
        "y": _r(ball[1]),
        "z": _r(ball[2]),
        **labels("ball"),
        "center_px": [_r(centre[0]), _r(centre[1])] if centre else None,
        "centroid_px": [_r(v) for v in objs["ball"]["centroid"]] if objs["ball"]["centroid"] else None,
    }
    return {
        "frame": fr["frame"],
        "t": fr["t"],
        "clip": clip_id,
        "image": image,
        "ball": ball_row,
        "possessor": fr.get("possessor"),
        "players": row_players,
        "camera": {**cam.to_dict(), "angle": angle},
        "blur_px": list(blur),
        "keypoints": [{**k, "visible": bool(v)} for k, v in zip(kps, res["keypoints"], strict=True)],
    }


def _encode_mp4(out: Path, fps: int) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RenderUnavailable("--mp4 needs ffmpeg on PATH; the JPEG frames are already written")
    subprocess.run(
        [
            ffmpeg,
            "-y",
            "-loglevel",
            "error",
            "-framerate",
            str(fps),
            "-i",
            str(out / "images" / "%05d.jpg"),
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-crf",
            "20",
            str(out / "clip.mp4"),
        ],
        check=True,
    )
