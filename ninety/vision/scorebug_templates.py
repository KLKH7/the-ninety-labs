"""Digit templates for the scorebug reader, cropped from frames our own renderer draws.

    uv run python -m ninety.vision.scorebug_templates <rendered training clip> --face mac [--gpu]

Offline, never on the live path: it drives the renderer (ninety/render/clip.py `browser_page`). For
each digit d it renders one frame of a training clip's own scene (its seed, its parameters, the
camera of its first frame) with the scorebug showing d - (9 - d), through the renderer's whole
picture path (the bug's canvas, its texture, the overlay, the JPEG), and crops the two digit cells
as the reader sees them (ninety/vision/scorebug.py: the plate found, the cells at DIGIT_X). The
home and away crops of each digit are averaged.

The digits a broadcast shows are drawn in Chromium's `sans-serif`, which is a different face on a Mac
and on a Linux render machine, so each machine that renders gives its own face (`--face`), merged
into scorebug_glyphs.json beside the others, with the clip, frame, renderer commit and machine
recorded. Only training clips are used (ninety/render/splits.py), never a test seed.
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import platform
import subprocess
from pathlib import Path

import numpy as np

from ninety.vision import scorebug as sb


def crop_cells(gray: np.ndarray) -> dict[str, np.ndarray] | None:
    """The two CELL_H x CELL_W digit cells, placed as the reader's templates are (the digit's left
    edge 2 px in, its middle row the plate's), or None when no plate is found."""
    x = sb.plate_x(gray)
    if x is None or sb.scale(gray.shape[0]) != 1:
        return None
    y = sb.BUG_TOP + 20 - sb.CELL_H // 2
    return {side: gray[y:y + sb.CELL_H, x + off - 2: x + off - 2 + sb.CELL_W].copy()
            for side, off in sb.DIGIT_X.items()}


def render_digits(clip: Path, gpu: bool = False) -> tuple[list[np.ndarray], dict]:
    from PIL import Image

    from ninety.render.clip import browser_page
    from ninety.render.splits import split_of

    meta = json.loads((clip / "clip.json").read_text())
    if split_of(int(meta["seed"])) != "train":
        raise SystemExit(f"refused: {clip} is seed {meta['seed']}, not a training seed")
    first = json.loads((clip / "frames.jsonl").read_text().splitlines()[0])
    cam = first["camera"]
    crops: dict[int, list[np.ndarray]] = {d: [] for d in range(10)}
    with browser_page(gpu) as (page, chromium):
        page.evaluate("cfg => window.ninety.init(cfg)",
                      {"seed": meta["seed"], "params": meta["params"], "objects": []})
        camera = {"position": cam["position"], "R": cam["R"], "fov_v_deg": cam["fov_v_deg"]}
        for d in range(10):
            spec = {"index": d, "camera": camera, "objects": [], "keypoints": [], "blur": [0, 0],
                    "score": [d, 9 - d], "clock": "10:00",
                    "goal_age": None, "goal_side": None, "net": None, "stinger": None, "period": None,
                    "want_image": True}
            res = page.evaluate("s => window.ninety.frame(s)", spec)
            data = base64.b64decode(res["image"].split(",", 1)[1])
            gray = np.asarray(Image.open(io.BytesIO(data)).convert("L"), dtype=float)
            cells = crop_cells(gray)
            if cells is None:
                raise SystemExit(f"no scorebug plate found in the rendered frame for {d}")
            crops[d].append(cells["home"])
            crops[9 - d].append(cells["away"])
    commit = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    source = {"clip": clip.name, "seed": meta["seed"], "camera_of_frame": first["frame"],
              "renderer_commit": commit, "chromium": chromium,
              "machine": f"{platform.system()} {platform.machine()}", "gl": "gpu" if gpu else "swiftshader"}
    return [np.mean(crops[d], axis=0) for d in range(10)], source


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Crop the scorebug's digits from frames our renderer draws.")
    ap.add_argument("clip", type=Path, help="a rendered training clip (clip.json, frames.jsonl)")
    ap.add_argument("--face", required=True, help="a name for this machine's sans-serif, e.g. mac or linux")
    ap.add_argument("--gpu", action="store_true")
    ap.add_argument("--out", type=Path, default=sb.GLYPHS)
    a = ap.parse_args(argv)
    digits, source = render_digits(a.clip, a.gpu)
    body = json.loads(a.out.read_text()) if a.out.exists() else {}
    faces = {k: v for k, v in body.get("faces", {}).items() if k in body.get("sources", {})}
    sources = dict(body.get("sources", {}))
    faces[a.face] = [np.round(t).astype(int).tolist() for t in digits]
    sources[a.face] = source
    a.out.write_text(json.dumps({"made_by": "python -m ninety.vision.scorebug_templates",
                                 "size": [sb.CELL_H, sb.CELL_W], "sources": sources, "faces": faces}) + "\n")
    print(json.dumps({"face": a.face, **source}))


if __name__ == "__main__":
    main()
