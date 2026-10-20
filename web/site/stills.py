"""Copy one rendered frame into the project page and draw the renderer's ground-truth boxes on it.

    uv run ninety-render --seed 7 --seconds 2 --gpu --out runs/site-still
    uv run python web/site/stills.py runs/site-still --frame 1970

Writes stills/seed<seed>-<frame>.jpg, an SVG of the frame's ground-truth boxes to lay over it,
and provenance.json (the command, the renderer and the commit), so the stills can be remade.
The boxes are the answer key the renderer writes, shown here to explain grading; nothing on the
live path reads them.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
COLORS = {"home": "#ffd166", "away": "#7ce0ff", "ball": "#ff5fa2"}


def _rect(box: list[float], color: str) -> str:
    x0, y0, x1, y1 = box
    return (
        f'<rect x="{x0:g}" y="{y0:g}" width="{x1 - x0:g}" height="{y1 - y0:g}" '
        f'fill="none" stroke="{color}" stroke-width="3"/>'
    )


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("clip", type=Path, help="a directory written by ninety-render")
    ap.add_argument("--frame", type=int, required=True, help="match frame number")
    a = ap.parse_args()

    clip = json.loads((a.clip / "clip.json").read_text())
    row = next(
        r
        for r in map(json.loads, (a.clip / "frames.jsonl").read_text().splitlines())
        if r["frame"] == a.frame
    )
    width, height = clip["params"]["width"], clip["params"]["height"]
    stem = f"seed{clip['seed']}-{a.frame}"
    out = HERE / "stills"
    out.mkdir(exist_ok=True)
    shutil.copyfile(a.clip / row["image"], out / f"{stem}.jpg")

    rects = [_rect(p["bbox"], COLORS[p["team"]]) for p in row["players"] if p["bbox"]]
    if row["ball"]["bbox"]:
        rects.append(_rect(row["ball"]["bbox"], COLORS["ball"]))
    (out / f"{stem}-truth.svg").write_text(
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}">'
        + "".join(rects)
        + "</svg>\n"
    )
    commit = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, cwd=HERE
    ).stdout.strip()
    (out / "provenance.json").write_text(
        json.dumps(
            {
                "image": f"{stem}.jpg",
                "truth_overlay": f"{stem}-truth.svg",
                "seed": clip["seed"],
                "frame": a.frame,
                "renderer": clip["renderer"],
                "commit": commit,
                "command": f"uv run ninety-render --seed {clip['seed']} --seconds 2 --gpu "
                f"--out runs/site-still && uv run python web/site/stills.py runs/site-still "
                f"--frame {a.frame}",
                "boxes": {
                    "players": len(rects) - bool(row["ball"]["bbox"]),
                    "ball": bool(row["ball"]["bbox"]),
                },
            },
            indent=2,
        )
        + "\n"
    )


if __name__ == "__main__":
    main()
