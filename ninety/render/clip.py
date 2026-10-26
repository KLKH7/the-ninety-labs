"""Render one seeded clip: simulate the match, film it, write images and ground truth.

Output directory layout:

    clip.json       seed, split, window, every render parameter, player looks, tool versions
    meta.json       the data contract's clip metadata: fps, seed, window, roster (id, team, role), score
    events.jsonl    ground-truth match events inside the clip window (match_event schema)
    frames.jsonl    one row per frame (frame schema): positions, camera, boxes, visibility, keypoints
    images/NNNNN.jpg
    clip.mp4        only with --mp4 and ffmpeg on PATH (viewing copy; training reads the JPEGs)
    views/<name>/   only with views=tactical: each fixed tactical lens (camera.tactical_views) as a
                    complete clip of its own (clip.json with `view`, meta.json, events.jsonl,
                    frames.jsonl, images/), the same match frames as the broadcast, without graphics
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
from contextlib import ExitStack, contextmanager
from dataclasses import replace
from pathlib import Path

from ninety.match.clock import match_clock
from ninety.render import RENDERER_VERSION, audio, edit, fouls
from ninety.render.camera import (
    TACTICAL_VIEWS,
    Camera,
    Director,
    blur_vector,
    corner_waits,
    tactical_views,
)
from ninety.render.params import RenderParams, sample_params, validate
from ninety.render.scene import (
    ACCEL_BOX,
    LEAD_AHEAD_FRAMES,
    Gait,
    advance_gaits,
    ball_parts,
    body_parts,
    contacts,
    crowded_start,
    drawn_ball,
    hold_at,
    holds,
    keeper_start,
    mesh_pose,
    parts_box,
    project_keypoints,
    reach_sign,
    sample_looks,
    throw_at,
    throws,
    touch_at,
)
from ninety.render.splits import split_of
from ninety.sim.engine import FORMATION, FPS, PITCH_X, PITCH_Y, simulate
from ninety.sim.pacing import MATCH_S

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
# The match is simulated this far past the latest frame a clip could need, whatever its start, so
# a clip and its re-render with the same window see the same events: an outcome settled after the
# window (a tackle won once someone controls the ball) is settled in both. It also leaves room for
# the dead balls a clip cuts through (edit.py): a penalty's wait is up to 140 s (R1).
SIM_MARGIN_S = 180.0
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
        "height_m": lk.height_m,
        "build": lk.build,
        "hair_style": lk.hair_style,
    }


def camera_positions(frames: list[dict], p: RenderParams, seed: int) -> list[tuple[float, float, float]]:
    """Where the broadcast lens stands at each frame, from the director the render uses.

    Run from the first frame rather than from the window's warm-up, so a cut's timing can
    differ from the render's by a few frames. Good enough to rank windows; the labels are
    measured on the render itself.
    """
    director = Director(p.camera, p.width, p.height, p.fps, seed, cuts=p.camera_cut)
    out = []
    for fr in frames:
        ball = drawn_ball(fr)
        actors = [(pl["x"], pl["y"], pl.get("action", "")) for pl in fr["players"]]
        out.append(tuple(director.step(ball[0], ball[1], actors, ball_z=ball[2]).position))
    return out


def choose_start(
    frames: list[dict], p: RenderParams, n: int, seed: int, earliest_s: float, latest_s: float
) -> int:
    """A seeded random window, redrawn (from the same seeded sequence, so still reproducible) while
    the ball is off the pitch for all of it: a dead ball lying behind a goal line or touchline
    waiting for a restart is off camera, so such a clip has no ball to label or check."""
    earliest, latest = int(earliest_s * FPS), int(latest_s * FPS)
    if p.occlusion == "crowded":
        cams = camera_positions(frames[: latest + n], p, seed)
        return crowded_start(frames, n, max(earliest, WARMUP), latest, cams)
    if p.occlusion == "keeper":
        return keeper_start(frames, n, max(earliest, WARMUP), latest)
    rng = random.Random(f"window-{seed}")
    for _ in range(WINDOW_DRAWS):
        start = rng.randint(max(earliest, WARMUP), latest)
        if any(_on_pitch(f["ball"]) for f in frames[start : start + n]):
            break
    return start


def _on_pitch(b: dict) -> bool:
    """The ball within the pitch's lines (Law 1)."""
    return 0.0 <= b["x"] <= PITCH_X and 0.0 <= b["y"] <= PITCH_Y


# The final whistle (Law 7: the engine plays two halves of 45 minutes and no added time) is blown
# FT_LEAD_S before the last frame, so a clip ending at full time is heard ending (*design*).
FT_LEAD_S = 1.2


def periods(events: list[dict]) -> tuple[tuple[float, float] | None, float]:
    """The half-time interval on the match clock (from the engine's half_time event to the next
    kick-off, or None when the match has none), and when the final whistle goes."""
    ht = next((e["t"] for e in events if e["type"] == "half_time"), None)
    if ht is None:
        return None, MATCH_S - FT_LEAD_S
    second = next((e["t"] for e in events if e["type"] == "kickoff" and e["t"] > ht), MATCH_S)
    return (ht, second), MATCH_S - FT_LEAD_S


def period_card(t: float, half: tuple[float, float] | None, final: float) -> str | None:
    """The scorebug's card at match time t: HALF-TIME through the interval, FULL-TIME from the
    final whistle on."""
    if half and half[0] <= t < half[1]:
        return "HALF-TIME"
    return "FULL-TIME" if t >= final else None


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
    views: str | None = None,
) -> dict:
    """Render one clip and return its clip.json content.

    `views` (params.VIEWS) adds streams beside the broadcast without changing it; it is not an
    override, so a test-set seed may have them too."""
    overrides = dict(overrides or {})
    p = sample_params(seed, **overrides)
    if views is not None:
        p = replace(p, views=views)
        validate(p)
    view_cams = dict(zip(TACTICAL_VIEWS, tactical_views(p), strict=True)) if p.views == "tactical" else {}
    n = int(round(seconds * p.fps))
    if p.fps != FPS:
        raise ValueError(f"the simulator runs at {FPS} fps")
    earliest_s, latest_s = 10.0, 240.0
    sim_end_s = max(latest_s, start_s or 0.0) + seconds + SIM_MARGIN_S
    match = simulate(seed, sim_end_s / 60)
    frames = match.frames
    start = (
        int(round(start_s * FPS))
        if start_s is not None
        else choose_start(frames, p, n, seed, earliest_s, latest_s)
    )
    # A broadcast clip cuts from a stoppage to its restart (edit.py): the clip shows n frames, which
    # may span more of the match. It cuts only a dead ball whose stoppage and restart it shows both.
    every_cut = edit.cuts(match.events, FPS) if p.dead_ball_cut else []
    show, made = edit.plan(start, n, every_cut, len(frames))
    if len(show) < n:
        raise ValueError("clip window runs past the simulated match")
    start = show[0]

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
    # Who scored, from each goal to the restart after it: the camera follows his celebration.
    restarts = sorted(e["frame"] for e in match.events if e["type"] in edit.RESTARTS)
    celebrating: dict[int, str] = {}
    for g in goals:
        if g.get("player"):
            until = next((f for f in restarts if f > g["frame"]), len(frames))
            celebrating.update(dict.fromkeys(range(g["frame"], until), g["player"]))
    # The stinger over each edit cut: picture index -> its progress (edit.stingers).
    stinger_at = edit.stingers(show, FPS) if made else {}
    if p.edge_stingers:  # clips joined back to back (the demo's segments): one stinger at each join
        stinger_at = {**edit.edge_stingers(n, FPS), **stinger_at}
    corners = corner_waits(match.events)  # a corner waiting to be taken, framed for it (camera.py)
    half, final_t = periods(match.events)  # the half-time and full-time cards and whistles
    t0, t1 = frames[show[0]]["t"], frames[show[-1]]["t"]
    clip = {
        "clip_id": f"seed{seed}",
        "seed": seed,
        "split": split_of(seed),
        "start_frame": start,
        "frames": n,
        "fps": p.fps,
        "t_start": t0,
        "t_end": t1,
        # The match frames the broadcast cut away from, and the runs of frames it shows: image i of
        # a segment is match frame `frame` + (i - `index`) (edit.py, docs/DATA_CONTRACT.md).
        "cuts": [c.as_dict() for c in made],
        "segments": [s.as_dict() for s in edit.segments(show)],
        # Picture indices a stinger graphic covers (in part), as the scorebug, an occluder that the
        # visibility labels count (web/render).
        "stinger_frames": sorted(stinger_at),
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
    with ctx as (pg, chromium_version), ExitStack() as stack:
        clip["renderer"]["chromium"] = chromium_version
        info = pg.evaluate(
            "cfg => window.ninety.init(cfg)", {"seed": seed, "params": p.to_dict(), "objects": objects}
        )
        clip["scorebug_px"] = info["bugRect"]
        if info.get("look"):  # the broadcast look (web/render/look.js): stadium=broadcast only
            clip["renderer"]["look"] = info["look"]
        # Each tactical lens films the same scene in a page of its own: the same seed, looks and
        # per-frame spec as the broadcast, its own camera and picture size, and no graphics.
        vpages = {}
        for name, vcam in view_cams.items():
            vpg = stack.enter_context(_sibling_page(pg))
            vparams = {**p.to_dict(), "width": vcam.width, "height": vcam.height}
            vpg.evaluate("cfg => window.ninety.init(cfg)",
                         {"seed": seed, "params": vparams, "objects": objects, "graphics": False})
            vpages[name] = vpg
            (out / "views" / name / "images").mkdir(parents=True)
        view_rows: dict[str, list[dict]] = {name: [] for name in view_cams}
        director = Director(p.camera, p.width, p.height, p.fps, seed, cuts=p.camera_cut)
        gaits = {lk.id: Gait() for lk in looks}
        touches = contacts(frames, match.events)
        reacts = fouls.reactions(frames, match.events)  # hands up, heads turned at a foul (lesson 234)
        held = holds(frames)
        thrown = throws(frames, FPS)
        prev_xy: dict[str, tuple[float, float]] = {}
        prev_cam: Camera | None = None
        spin_angle = 0.0
        spin_axis = None
        rows = []
        index = 0
        reopen = False
        for fi, draw, left in _plan(edit.segments(show)):
            if fi is None:
                # A cut: the picture comes back on the restart. Bodies and the camera start afresh
                # there and settle over the warm-up before it, as at the start of the clip.
                gaits = {lk.id: Gait() for lk in looks}
                prev_xy, prev_cam = {}, None
                director.cut()
                reopen = True
                continue
            if draw and reopen:
                director.open_on_restart()
                prev_cam = None  # a new shot: nothing streaks across the cut
                reopen = False
            fr = frames[fi]
            advance_gaits(gaits, prev_xy, fr, 1 / FPS, frames[min(fi + LEAD_AHEAD_FRAMES, len(frames) - 1)],
                          frames[fi + 1:fi + 1 + ACCEL_BOX])
            ball = drawn_ball(fr)
            for pl in fr["players"]:
                g, h = gaits[pl["id"]], by_id[pl["id"]].height_m
                touch_at(g, touches.get(pl["id"], []), fi, h, FPS, pl["x"], pl["y"])
                hold_at(g, held.get(pl["id"], []), fi, ball, h, FPS)
                throw_at(g, thrown.get(pl["id"], []), fi, h, FPS, pl["x"], pl["y"])
                fouls.apply_fall(g, pl)  # the engine's fall and fall_dir (lesson 173)
                mine = reacts.get(pl["id"], [])
                fouls.signal_at(g, mine, fi, FPS, pl["x"], pl["y"], h)
                fouls.look_at(g, mine, fi, FPS, pl["x"], pl["y"], fr)
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
            cut_in = None if left is None else left / FPS
            who = celebrating.get(fr["frame"])
            scorer = next(((q["x"], q["y"]) for q in fr["players"] if q["id"] == who), None)
            cam = director.step(ball[0], ball[1], actors, goal_arg, cut_in, ball_z=ball[2],
                                corner=corners.get(fr["frame"]), scorer=scorer)
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
            if not draw:
                for pl in fr["players"]:  # the feet keep stepping through the warm-up
                    body_parts(pl["x"], pl["y"], by_id[pl["id"]], gaits[pl["id"]])
                continue
            spec_objects, row_players = [], []
            for pl in fr["players"]:
                g = gaits[pl["id"]]
                meet = g.action in ("strike", "foot", "thigh", "chest", "head", "hands")
                parts = body_parts(
                    pl["x"], pl["y"], by_id[pl["id"]], g, ball if meet else None
                )
                reach = reach_sign(pl["x"], pl["y"], g, ball if meet else None)
                spec_objects.append(
                    {
                        "id": pl["id"],
                        "parts": parts,
                        "box": parts_box(cam, parts),
                        "heading": g.heading,
                        "pose": mesh_pose(g, pl["x"], pl["y"], reach),
                    }
                )
                row_players.append(fouls.row(pl, g.fall))
            bparts = ball_parts(*ball, spin)
            spec_objects.append({"id": "ball", "parts": bparts, "box": parts_box(cam, bparts)})
            kps = project_keypoints(cam)
            score = [
                sum(1 for g in goals if g["team"] == team and g["t"] <= fr["t"]) for team in ("home", "away")
            ]
            clock = match_clock(fr["t"])
            recent = [g for g in goals if 0 <= fr["t"] - g["t"] <= 2.5]
            last = recent[-1] if recent else None
            spec = {
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
                "stinger": stinger_at.get(index),
                "period": period_card(fr["t"], half, final_t),
                "want_image": write_images,
            }
            res = pg.evaluate("s => window.ninety.frame(s)", spec)
            image = f"images/{index:05d}.jpg"
            if write_images:
                (out / image).write_bytes(base64.b64decode(res["image"].split(",", 1)[1]))
            rows.append(
                _frame_row(fr, cam, ball, row_players, res, kps, blur, image, clip["clip_id"], director.angle)
            )
            for name, vcam in view_cams.items():
                # The same bodies and ball, boxed and keyed for this lens. It never moves, so nothing
                # smears; the broadcast's stinger is the broadcast's alone.
                vkps = project_keypoints(vcam)
                vspec = {
                    **spec,
                    "camera": {"position": list(vcam.position), "R": vcam.R, "fov_v_deg": vcam.fov_v_deg},
                    "objects": [{**o, "box": parts_box(vcam, o["parts"])} for o in spec_objects],
                    "keypoints": [[k["px"], k["py"]] for k in vkps],
                    "blur": [0.0, 0.0],
                    "stinger": None,
                }
                vres = vpages[name].evaluate("s => window.ninety.frame(s)", vspec)
                if write_images:
                    jpg = base64.b64decode(vres["image"].split(",", 1)[1])
                    (out / "views" / name / image).write_bytes(jpg)
                view_rows[name].append(_frame_row(fr, vcam, ball, row_players, vres, vkps, (0.0, 0.0),
                                                  image, _view_id(clip["clip_id"], name), name))
            index += 1

    with open(out / "frames.jsonl", "w") as f:
        for r in rows:
            f.write(json.dumps(r, separators=(",", ":")) + "\n")
    events = [e for e in match.events if t0 <= e["t"] <= t1]
    with open(out / "events.jsonl", "w") as f:
        for e in events:
            f.write(json.dumps(e) + "\n")
    clip["event_counts"] = dict(Counter(e["type"] for e in events))
    # The referee's whistle on the sound track at each foul the picture shows (lesson 234), by
    # picture index: a foul inside a stretch the edit cut is not heard.
    shown = {f: i for i, f in enumerate(show)}
    fouled = (e["frame"] for e in events if e["type"] == "foul")
    clip["whistles"] = sorted(shown[f] for f in fouled if f in shown)
    # Every call the picture shows, and the crowd's swells (audio.py): picture index and kind.
    calls = [(shown[e["frame"]], e["type"]) for e in events
             if e["type"] in ("foul", "kickoff", "half_time") and e["frame"] in shown]
    final_f = round(final_t * FPS)
    if final_f in shown:
        calls.append((shown[final_f], "full_time"))
    clip["calls"] = sorted([i, k] for i, k in calls)
    clip["crowd"] = {
        "goals": sorted(shown[e["frame"]] for e in events if e["type"] == "goal" and e["frame"] in shown),
        "shots": sorted(shown[e["frame"]] for e in events if e["type"] == "shot" and e["frame"] in shown),
    }
    clip["ball_visibility_lt_0_5"] = round(
        sum(1 for r in rows if r["ball"]["visibility"] < 0.5 and r["ball"]["bbox"])
        / max(1, sum(1 for r in rows if r["ball"]["bbox"])),
        4,
    )
    for name, vcam in view_cams.items():
        _write_view(out, clip, name, vcam, view_rows[name], events)
    (out / "clip.json").write_text(json.dumps(clip, indent=2))
    write_meta(out)
    if mp4:
        _encode_mp4(out, p.fps, n / p.fps, clip)
        for name in view_cams:
            _encode_mp4(out / "views" / name, p.fps)
    return clip


def _view_id(clip_id: str, name: str) -> str:
    return f"{clip_id}-{name}"


def _write_view(out: Path, clip: dict, name: str, cam: Camera, rows: list[dict], events: list[dict]) -> None:
    """One tactical lens as a complete clip folder: the broadcast's clip.json with its own id, size
    and `view`, no graphics; the same events; its own frames; then meta.json from those files."""
    d = out / "views" / name
    with open(d / "frames.jsonl", "w") as f:
        for r in rows:
            f.write(json.dumps(r, separators=(",", ":")) + "\n")
    with open(d / "events.jsonl", "w") as f:
        for e in events:
            f.write(json.dumps(e) + "\n")
    vclip = {
        **clip,
        "clip_id": _view_id(clip["clip_id"], name),
        "params": {**clip["params"], "width": cam.width, "height": cam.height},
        # A fixed lens of the clip in the folder two levels up, filmed frame for frame with it.
        "view": {"name": name, "of": clip["clip_id"], "fixed": True, "camera": cam.to_dict()},
        "stinger_frames": [],
        "scorebug_px": None,
        "ball_visibility_lt_0_5": round(
            sum(1 for r in rows if r["ball"]["visibility"] < 0.5 and r["ball"]["bbox"])
            / max(1, sum(1 for r in rows if r["ball"]["bbox"])),
            4,
        ),
    }
    (d / "clip.json").write_text(json.dumps(vclip, indent=2))
    write_meta(d)


@contextmanager
def _sibling_page(page):
    """Another page with the renderer loaded, in the same browser as `page`."""
    errors: list[str] = []
    sib = page.context.browser.new_page()  # a page of its own: browser.new_page's context owns one
    try:
        sib.on("pageerror", lambda exc: errors.append(str(exc)))
        sib.goto(page.url)
        sib.wait_for_function("window.ninety && window.ninety.ready", timeout=30_000)
        if errors:
            raise RuntimeError(f"renderer page error: {errors[0]}")
        yield sib
    finally:
        sib.close()


def _plan(segs: list[edit.Segment]) -> list[tuple[int | None, bool, int | None]]:
    """The match frames to step through, in order, as (frame, drawn, left): before each segment its
    warm-up (stepped, not drawn), then the segment. `left` counts a drawn frame's segment frames
    still to show, itself included, when a cut follows the segment, else None. (None, False, None)
    marks a cut before a segment."""
    out: list[tuple[int | None, bool, int | None]] = []
    for k, s in enumerate(segs):
        lo = max(0, s.frame - WARMUP)
        if k:
            out.append((None, False, None))
            lo = max(lo, segs[k - 1].frame + segs[k - 1].frames)
        end = s.frame + s.frames
        last = k == len(segs) - 1
        out += [(f, False, None) for f in range(lo, s.frame)]
        out += [(f, True, None if last else end - f) for f in range(s.frame, end)]
    return out


def write_meta(out: Path) -> dict:
    """Write the data contract's meta.json (docs/DATA_CONTRACT.md) from the clip's own files, so
    `ninety-validate` can check it. Also backfills clips rendered before the renderer wrote it."""
    clip = json.loads((out / "clip.json").read_text())
    with open(out / "frames.jsonl") as f:
        frames = [json.loads(line) for line in f if line.strip()]
    with open(out / "events.jsonl") as f:
        events = [json.loads(line) for line in f if line.strip()]
    meta = {
        "fps": clip["fps"],
        "seed": clip["seed"],
        "clip_id": clip["clip_id"],
        # A window cut from a longer match: events before or after it are not in the clip.
        "window": {"first_frame": frames[0]["frame"], "last_frame": frames[-1]["frame"]},
        # Dead balls the broadcast cut away from: their frames are not in the clip (edit.py).
        "cuts": clip.get("cuts", []),
        "roster": [{k: lk[k] for k in ("id", "team", "role")} for lk in clip["looks"]],
        # The goals in this clip's events, the same events the validator adds up (C9).
        "score": {team: sum(1 for e in events if e["type"] == "goal" and e["team"] == team)
                  for team in ("home", "away")},
    }
    (out / "meta.json").write_text(json.dumps(meta, indent=2))
    return meta


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


def _encode_mp4(out: Path, fps: int, seconds: float | None = None, clip: dict | None = None) -> None:
    """clip.mp4 from the JPEGs; a broadcast clip's has the sound track (audio.py): its calls and its
    crowd. A view's has none (its picture is the analysts' and carries no graphics)."""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RenderUnavailable("--mp4 needs ffmpeg on PATH; the JPEG frames are already written")
    cmd = [ffmpeg, "-y", "-loglevel", "error", "-framerate", str(fps), "-i", str(out / "images" / "%05d.jpg")]
    wav = out / "sound.wav"
    if clip is not None and seconds:
        calls = [(i / fps, kind) for i, kind in clip.get("calls", [])]
        crowd = clip.get("crowd", {})
        sound = audio.mix(seconds, calls, [i / fps for i in crowd.get("goals", [])],
                          [i / fps for i in crowd.get("shots", [])])
        audio.write_wav(wav, sound)
        cmd += ["-i", str(wav), "-c:a", "aac", "-b:a", "96k", "-shortest"]
    cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "20", str(out / "clip.mp4")]
    try:
        subprocess.run(cmd, check=True)
    finally:
        wav.unlink(missing_ok=True)
