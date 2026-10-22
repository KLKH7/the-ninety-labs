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


def projection_errors(frames: list[dict]) -> dict:
    """Ball: saved-matrix projection of its centre against the centroid of its drawn pixels.

    Players: saved-matrix projection of their foot point must sit inside their pixel box, and the
    keypoint pixels must equal the saved-matrix projection of the pitch points they name.
    """
    from ninety.render.scene import KEYPOINTS

    kp_xy = {name: (x, y) for name, x, y in KEYPOINTS}
    ball_err, kp_err, foot_outside, foot_checked = [], [], 0, 0
    for fr in frames:
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
                if not (x0 - slack <= u <= x1 + slack and y1 - slack <= v <= y1 + slack):
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
    clip, frames, _ = load_clip(clip_dir)
    proj = projection_errors(frames)
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
