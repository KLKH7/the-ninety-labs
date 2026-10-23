"""Render checks from docs/guides/broadcast-render.md section 6, computed from the saved files only.

They read `frames.jsonl` the way any consumer would (saved camera matrix, saved pixel labels), so
they test the data we ship, not the code that wrote it.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

from ninety.render.camera import project_with
from ninety.validate import validate

PROJECTION_TOL_PX = 1.0  # guide: ground truth projects onto its pixels within 1 px
EDGE_MARGIN_PX = 2  # objects cut by the image border have a shifted centroid; skip them


def load_clip(d: Path) -> tuple[dict, list[dict], list[dict]]:
    d = Path(d)
    clip = json.loads((d / "clip.json").read_text())
    frames = [json.loads(line) for line in open(d / "frames.jsonl")]
    events = [json.loads(line) for line in open(d / "events.jsonl")]
    return clip, frames, events


def _inside(b: list[int], w: int, h: int) -> bool:
    return (
        b[0] >= EDGE_MARGIN_PX
        and b[1] >= EDGE_MARGIN_PX
        and b[2] <= w - EDGE_MARGIN_PX
        and b[3] <= h - EDGE_MARGIN_PX
    )


def _reaching(frames: list[dict], events: list[dict] | None, heights: dict[str, float]
              ) -> dict[tuple[int, str], float]:
    """(frame index, player) -> how far from his tracked point, on the ground, his foot is drawn to
    the ball he touches: the renderer's own touches (scene.contacts) over the frames it draws each
    (scene._touch_window), the distance from where he stood to the ball he met, never more than his
    leg reaches ((LEG_M + HIP_SIDE_M) at his scale, scene.py). Frames outside a touch are absent."""
    from ninety.render.meshpose import ASSET_STATURE_M
    from ninety.render.scene import HIP_SIDE_M, LEG_M, _touch_window, contacts
    from ninety.sim.engine import FPS

    out: dict[tuple[int, str], float] = {}
    for pid, mine in contacts(frames, events).items():
        reach = (LEG_M + HIP_SIDE_M) * heights.get(pid, ASSET_STATURE_M) / ASSET_STATURE_M
        for c in mine:
            # A saved row has no ball velocity, which tells a kick's longer window from a touch's,
            # so the wider of the two is taken: still only the frames round this touch.
            kick, touch = _touch_window({**c, "part": "strike"}), _touch_window({**c, "part": "chest"})
            lo, hi = min(kick[0], touch[0]), max(kick[1], touch[1])
            d = min(math.dist(c["at"], c["ball"][:2]), reach)
            first = max(0, c["frame"] + math.floor(lo * FPS))
            for i in range(first, min(len(frames), c["frame"] + math.ceil(hi * FPS) + 1)):
                out[(i, pid)] = max(out.get((i, pid), 0.0), d)
    return out


def _ground_span(P: list[list[float]], x: float, y: float, r: float
                 ) -> tuple[float, float, float, float] | None:
    """The picture's span (u0, v0, u1, v1) of the ground disc of radius r round (x, y), from its rim."""
    pts = [project_with(P, (x + r * math.cos(a), y + r * math.sin(a), 0.0))
           for a in (k * math.pi / 8 for k in range(16))]
    if any(p is None for p in pts):
        return None
    us, vs = [p[0] for p in pts], [p[1] for p in pts]
    return min(us), min(vs), max(us), max(vs)


def projection_errors(frames: list[dict], events: list[dict] | None = None,
                      heights: dict[str, float] | None = None) -> dict:
    """Ball: saved-matrix projection of its centre against the centroid of its drawn pixels.

    Players: saved-matrix projection of their foot point must sit inside their pixel box, and the
    keypoint pixels must equal the saved-matrix projection of the pitch points they name.

    The box's bottom is the sole of his lowest foot, within V6's 0.45 m of the tracked point. While
    he touches the ball the foot is drawn at the ball (scene.touch_at), as far out as his leg reaches,
    so on those frames the bottom may lie anywhere over that stretch of ground as the saved matrix
    projects it: from a high lens a reach toward the camera is a long way down the picture, which a
    side-on scale did not allow for (lesson 212).
    """
    from ninety.render.scene import KEYPOINTS

    kp_xy = {name: (x, y) for name, x, y in KEYPOINTS}
    ball_err, kp_err, foot_outside, foot_checked = [], [], 0, 0
    reaching = _reaching(frames, events, heights or {}) if events is not None else {}
    for i, fr in enumerate(frames):
        cam = fr["camera"]
        P, w, h = cam["P"], cam["width"], cam["height"]
        b = fr["ball"]
        if b["bbox"] and b["centroid_px"] and _inside(b["bbox"], w, h) and b["pixels"] >= 9:
            uv = project_with(P, (b["x"], b["y"], b["z"] + 0.11))
            ball_err.append(math.dist(uv, b["centroid_px"]))
        for pl in fr["players"]:
            if pl["bbox"] and _inside(pl["bbox"], w, h):
                foot_checked += 1
                u, v = project_with(P, (pl["x"], pl["y"], 0.0))
                x0, y0, x1, y1 = pl["bbox"]
                if pl.get("fall"):
                    # a body lying over its feet (lesson 173) is not 1.8 m tall and its feet may be
                    # at any edge of the box, so the ground point must be inside the box, with the
                    # same 0.45 m slack taken from the camera's scale at the feet
                    top = project_with(P, (pl["x"], pl["y"], 1.0))
                    slack = 0.45 * math.dist((u, v), top)
                    if not (x0 - slack <= u <= x1 + slack and y0 - slack <= v <= y1 + slack):
                        foot_outside += 1
                    continue
                # feet swing about 0.4 m either side of the tracked point, and the bottom of the
                # box is the sole of the lowest foot, so allow that much slack in metres-as-pixels
                slack = 0.45 * (y1 - y0) / 1.8
                if x0 - slack <= u <= x1 + slack and y1 - slack <= v <= y1 + slack:
                    continue
                r = reaching.get((i, pl["id"]))
                span = _ground_span(P, pl["x"], pl["y"], r) if r else None
                if span is not None:
                    u0, v0, u1, v1 = span
                    # the box spans from his tracked point to the foot at the ball: the two overlap
                    # across, and its bottom is on that stretch of ground, the same slack either side
                    if x0 - slack <= u1 and u0 <= x1 + slack and v0 - slack <= y1 <= v1 + slack:
                        continue
                foot_outside += 1
        for k in fr["keypoints"]:
            uv = project_with(P, (*kp_xy[k["name"]], 0.0))
            kp_err.append(math.dist(uv, (k["px"], k["py"])))

    def stats(xs: list[float]) -> dict:
        if not xs:
            return {"n": 0, "mean": None, "max": None}
        return {"n": len(xs), "mean": round(sum(xs) / len(xs), 4), "max": round(max(xs), 4)}

    return {
        "ball_px": stats(ball_err),
        "keypoint_px": stats(kp_err),
        "player_foot_outside_box": foot_outside,
        "player_foot_checked": foot_checked,
    }


def label_completeness(clip: dict, frames: list[dict], clip_dir: Path | None = None) -> dict:
    """Every frame has an image, a camera, all 22 players and the ball; every drawn object has a box."""
    problems = []
    expected_ids = None
    for i, fr in enumerate(frames):
        ids = {p["id"] for p in fr["players"]}
        expected_ids = expected_ids or ids
        if len(fr["players"]) != 22 or ids != expected_ids:
            problems.append(f"frame {i}: player set changed")
        if "camera" not in fr or "P" not in fr["camera"]:
            problems.append(f"frame {i}: no camera")
        if clip_dir is not None and not (Path(clip_dir) / fr["image"]).exists():
            problems.append(f"frame {i}: image missing")
        for obj in [*fr["players"], fr["ball"]]:
            if obj["pixels"] > 0 and obj["bbox"] is None:
                problems.append(f"frame {i}: drawn object without a box")
            if obj["pixels"] == 0 and (obj["bbox"] is not None or obj["visibility"] != 0):
                problems.append(f"frame {i}: box or visibility on an undrawn object")
            if not 0 <= obj["visibility"] <= 1:
                problems.append(f"frame {i}: visibility out of range")
    if len(frames) != clip["frames"]:
        problems.append(f"{len(frames)} rows for {clip['frames']} frames")
    return {"frames": len(frames), "problems": problems[:20], "ok": not problems}


def occlusion(frames: list[dict]) -> dict:
    in_frame = [f["ball"] for f in frames if f["ball"]["bbox"]]
    hidden = sum(1 for b in in_frame if b["visibility"] < 0.5)
    players = [p for f in frames for p in f["players"] if p["bbox"]]
    return {
        "ball_in_frame": len(in_frame),
        "ball_visibility_lt_0_5_share": round(hidden / len(in_frame), 4) if in_frame else None,
        "player_boxes": len(players),
        "player_visibility_lt_0_5_share": round(
            sum(1 for p in players if p["visibility"] < 0.5) / len(players), 4
        )
        if players
        else None,
        "player_height_px": _height_stats(frames),
    }


def _height_stats(frames: list[dict]) -> dict | None:
    """Box heights of whole, unoccluded players, overall and per camera angle.

    A box cut by any image edge holds only part of a player, so it is no measure of how tall
    players are drawn. The guide's 30 to 120 px is for the main view, hence the split by angle.
    """
    by_angle: dict[str, list[int]] = {}
    for f in frames:
        w, h = f["camera"]["width"], f["camera"]["height"]
        angle = f["camera"].get("angle", "main")
        for p in f["players"]:
            if p["bbox"] and p["visibility"] > 0.9 and _inside(p["bbox"], w, h):
                by_angle.setdefault(angle, []).append(p["bbox"][3] - p["bbox"][1])
    if not by_angle:
        return None

    def q(hs: list[int]) -> dict:
        hs = sorted(hs)
        n = len(hs)
        return {"n": n, "p05": hs[n // 20], "median": hs[n // 2], "p95": hs[n * 19 // 20]}

    every = [x for hs in by_angle.values() for x in hs]
    return {**q(every), "by_angle": {a: q(by_angle[a]) for a in sorted(by_angle)}}


def digest(clip_dir: Path, images: int | None = None) -> dict:
    """Hashes of the ground truth and of the images, for the determinism check."""
    d = Path(clip_dir)
    files = sorted((d / "images").glob("*.jpg"))
    if images is not None:
        files = files[:images]
    h = hashlib.sha256()
    for f in files:
        h.update(f.read_bytes())
    return {
        "frames_jsonl": hashlib.sha256((d / "frames.jsonl").read_bytes()).hexdigest(),
        "events_jsonl": hashlib.sha256((d / "events.jsonl").read_bytes()).hexdigest(),
        "images": h.hexdigest(),
        "image_count": len(files),
    }


def check_clip(clip_dir: Path) -> dict:
    clip, frames, events = load_clip(clip_dir)
    heights = {lk["id"]: lk["height_m"] for lk in clip.get("looks", [])}
    proj = projection_errors(frames, events, heights)
    comp = label_completeness(clip, frames, clip_dir)
    occ = occlusion(frames)
    contract = validate(clip_dir)  # docs/DATA_CONTRACT.md: every clip passes `ninety-validate`
    passed = {
        "projection_ball_lt_1px": proj["ball_px"]["max"] is not None
        and proj["ball_px"]["max"] < PROJECTION_TOL_PX,
        "projection_keypoints_lt_1px": proj["keypoint_px"]["max"] is None
        or proj["keypoint_px"]["max"] < PROJECTION_TOL_PX,
        "player_feet_in_boxes": proj["player_foot_outside_box"] == 0,
        "labels_complete": comp["ok"],
        "data_contract": not contract,
    }
    return {
        "clip": clip["clip_id"],
        "seed": clip["seed"],
        "split": clip["split"],
        "projection": proj,
        "labels": comp,
        "occlusion": occ,
        "data_contract": contract,
        "passed": passed,
    }
