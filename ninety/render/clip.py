"""Render one seeded clip: simulate the match, film it, write images and ground truth.

Output directory layout:

    clip.json       seed, split, window, every render parameter, player looks, tool versions
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
import random
import shutil
import subprocess
import threading
from collections import Counter
from contextlib import contextmanager
from pathlib import Path

from ninety.render import RENDERER_VERSION
from ninety.render.camera import Camera, Director, blur_vector
from ninety.render.params import RenderParams, sample_params
from ninety.render.scene import (
    Gait,
    ball_parts,
    body_parts,
    crowded_start,
    drawn_ball,
    parts_box,
    project_keypoints,
    sample_looks,
    update_gait,
)
from ninety.render.splits import split_of
from ninety.sim.engine import FORMATION, FPS, simulate

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


def kit_colors(p: RenderParams, team: str, role: str) -> dict:
    kit = {
        ("home", False): p.home_kit,
        ("away", False): p.away_kit,
        ("home", True): p.home_gk,
        ("away", True): p.away_gk,
    }[(team, role == "GK")]
    return {"shirt": kit.shirt, "shorts": kit.shorts, "socks": kit.socks}


def choose_start(
    frames: list[dict], p: RenderParams, n: int, seed: int, earliest_s: float, latest_s: float
) -> int:
    earliest, latest = int(earliest_s * FPS), int(latest_s * FPS)
    if p.occlusion == "crowded":
        return crowded_start(frames, n, max(earliest, WARMUP), latest)
    return random.Random(f"window-{seed}").randint(max(earliest, WARMUP), latest)


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
    objects = [
        {"id": lk.id, "colors": {**kit_colors(p, lk.team, lk.role), "skin": lk.skin, "hair": lk.hair}}
        for lk in looks
    ]
    objects.append({"id": "ball", "colors": {"ball": "#f2f2f2"}})
    by_id = {lk.id: lk for lk in looks}

    out = Path(out)
    if out.exists():
        shutil.rmtree(out)
    (out / "images").mkdir(parents=True)

    goals = [e for e in match.events if e["type"] == "goal"]
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
        director = Director(p.camera, p.width, p.height, p.fps, seed)
        gaits = {lk.id: Gait() for lk in looks}
        prev_xy: dict[str, tuple[float, float]] = {}
        prev_cam: Camera | None = None
        rows = []
        for fi in range(max(0, start - WARMUP), start + n):
            fr = frames[fi]
            bx, by = fr["ball"]["x"], fr["ball"]["y"]
            for pl in fr["players"]:
                px, py = prev_xy.get(pl["id"], (pl["x"], pl["y"]))
                update_gait(
                    gaits[pl["id"]], pl["x"] - px, pl["y"] - py, 1 / FPS, (bx - pl["x"], by - pl["y"])
                )
                prev_xy[pl["id"]] = (pl["x"], pl["y"])
            carrier = fr.get("possessor")
            ball = drawn_ball(fr, gaits[carrier].heading if carrier else None)
            cam = director.step(ball[0], ball[1])
            blur = blur_vector(prev_cam, cam, p.motion_blur)
            prev_cam = cam
            if fi < start:
                continue
            index = fi - start
            spec_objects, row_players = [], []
            for pl in fr["players"]:
                parts = body_parts(pl["x"], pl["y"], by_id[pl["id"]], gaits[pl["id"]])
                spec_objects.append({"id": pl["id"], "parts": parts, "box": parts_box(cam, parts)})
                row_players.append(pl)
            bparts = ball_parts(*ball)
            spec_objects.append({"id": "ball", "parts": bparts, "box": parts_box(cam, bparts)})
            kps = project_keypoints(cam)
            score = [
                sum(1 for g in goals if g["team"] == team and g["t"] <= fr["t"]) for team in ("home", "away")
            ]
            clock = f"{int(fr['t'] // 60):02d}:{int(fr['t'] % 60):02d}"
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
                    "want_image": write_images,
                },
            )
            image = f"images/{index:05d}.jpg"
            if write_images:
                (out / image).write_bytes(base64.b64decode(res["image"].split(",", 1)[1]))
            rows.append(_frame_row(fr, cam, ball, row_players, res, kps, blur, image, clip["clip_id"]))

    with open(out / "frames.jsonl", "w") as f:
        for r in rows:
            f.write(json.dumps(r, separators=(",", ":")) + "\n")
    events = [e for e in match.events if t0 <= e["t"] <= t1]
    with open(out / "events.jsonl", "w") as f:
        for e in events:
            f.write(json.dumps(e) + "\n")
    clip["event_counts"] = dict(Counter(e["type"] for e in events))
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
        "camera": cam.to_dict(),
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
