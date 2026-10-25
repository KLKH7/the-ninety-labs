"""Observations re-placed through each frame's true camera: a diagnostic, never the live path.

    uv run python -m ninety.eval.true_camera <observations.jsonl> --frames <clip>/frames.jsonl \\
        --out <observations-true-camera.jsonl>

Reads the answer key (the camera in frames.jsonl), so nothing made from it is a live number. It
keeps everything the live path saw in the pixels (the boxes, their scores, the kit colours) and
replaces only the camera: every frame trusted, every box placed through the frame's true P by
observe's own placing (players at the foot point, the ball one radius up, `observe._ground`). So
what comes after it measures the stages after the camera fit with the fit taken out, as an upper
bound, when the live fit places nothing (docs/eval/set-piece-validation.md). Each
frame's height ratio through the true camera is kept, so the trust test can be judged too.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from ninety.vision import observe


def re_place(rows: list[dict], frames: list[dict]) -> list[dict]:
    truth = {f["frame"]: f for f in frames}
    out = []
    for r in rows:
        P = np.array(truth[r["frame"]]["camera"]["P"])
        cam = {"ok": True, "median_px": None, "points": r["camera"].get("points"), "P": P.tolist(),
               "shot": r["camera"].get("shot", 0), "true_camera": True,
               "height_ratio": observe.height_ratio(r["players"], P)}
        row = {**r, "camera": cam}
        for d in row["players"]:
            x0, _, x1, y1 = d["bbox"]
            xy = observe._ground(P, ((x0 + x1) / 2, y1))
            d["x"], d["y"] = (observe._r(xy[0]), observe._r(xy[1])) if xy else (None, None)
        for b in row["ball"]:
            x0, y0, x1, y1 = b["bbox"]
            xy = observe._ground(P, ((x0 + x1) / 2, (y0 + y1) / 2), observe.BALL_CENTRE_Z)
            b["x"], b["y"] = (observe._r(xy[0]), observe._r(xy[1])) if xy else (None, None)
        out.append(row)
    return out


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Re-place observations through the true camera (diagnostic).")
    ap.add_argument("observations", type=Path)
    ap.add_argument("--frames", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args(argv)
    read = lambda p: [json.loads(x) for x in p.read_text().splitlines() if x.strip()]  # noqa: E731
    rows = re_place(read(a.observations), read(a.frames))
    a.out.write_text("".join(json.dumps(r, separators=(",", ":")) + "\n" for r in rows), encoding="utf-8")
    band = observe.HEIGHT_BAND
    ratios = [r["camera"]["height_ratio"] for r in rows if r["camera"]["height_ratio"] is not None]
    in_band = sum(band[0] <= x <= band[1] for x in ratios)
    print(json.dumps({"frames": len(rows), "height_ratio_in_band": in_band, "with_ratio": len(ratios)}))


if __name__ == "__main__":
    main()
