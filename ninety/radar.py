"""The viewer's radar: vision's tracked positions and its camera fit, as one bundle file.

    uv run python -m ninety.radar <tracked.json> <observations.jsonl> --width W --height H --out radar.json

or through `ninety-e2e <clip> --tracked FILE --observations FILE`, which writes it into the bundle.

The radar beside the broadcast video (web/viewer/src/radar.ts) draws the whole pitch from above:
every tracked player, the ball, and the part of the pitch the broadcast camera shows. All of it is
vision's output on the live path, never the answer key:

- `frames`: the tracked frames as ninety/vision/tracked_frames.py writes them (`source: tracked`),
  unchanged. A frame from anywhere else is refused.
- `views`, one per observed frame:
  - `ball_seen`: whether vision found the ball in that frame (ninety/vision/track.py,
    `ball_path`). The tracked file fills short gaps on a straight line; the radar draws a filled-in
    ball as estimated, not as seen.
  - `footprint`: the ground the broadcast picture covers, in pitch metres: the image's edges taken
    back through vision's own camera fit (observe.py, `camera.P`) onto the ground plane. None when
    that frame's fit is not ok, as the tracker does not trust it either.

Nothing here opens a clip's frames.jsonl or events.jsonl, or the rendered camera.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ninety.vision.track import ball_path

FORMAT = 1
SOURCE = "tracked"
# The footprint's far edge, where the picture reaches the horizon, runs out without end; it is cut
# to this far beyond the pitch, past anything the radar draws (design).
FAR_M = 30.0
PITCH_X, PITCH_Y = 105.0, 68.0  # Law 1 as the engine plays it (docs/GROUNDING.md, L1)
PLACES = 2  # cm, as the tracked file

Point = tuple[float, float]


def _inverse(m: list[list[float]]) -> list[list[float]] | None:
    (a, b, c), (d, e, f), (g, h, i) = m
    det = a * (e * i - f * h) - b * (d * i - f * g) + c * (d * h - e * g)
    if abs(det) < 1e-12:
        return None
    adj = [
        [e * i - f * h, c * h - b * i, b * f - c * e],
        [f * g - d * i, a * i - c * g, c * d - a * f],
        [d * h - e * g, b * g - a * h, a * e - b * d],
    ]
    return [[v / det for v in row] for row in adj]


def _clip(poly: list[tuple[float, ...]], inside, cross) -> list[tuple[float, ...]]:
    """One Sutherland-Hodgman pass: keep the polygon's part where `inside` holds."""
    out: list[tuple[float, ...]] = []
    for k, cur in enumerate(poly):
        prev = poly[k - 1]
        if inside(cur):
            if not inside(prev):
                out.append(cross(prev, cur))
            out.append(cur)
        elif inside(prev):
            out.append(cross(prev, cur))
    return out


def footprint(P: list[list[float]], width: int, height: int) -> list[Point] | None:
    """The ground the picture covers: the image rectangle taken back through the camera P onto the
    pitch plane (z = 0), cut where it would cross the horizon and to FAR_M around the pitch."""
    # Ground point (x, y, 0, 1) -> pixels is the homography H = P's columns 0, 1 and 3.
    hmat = [[row[0], row[1], row[3]] for row in P]
    inv = _inverse(hmat)
    if inv is None:
        return None
    # Pixel (u, v) goes back to the ground point (gx, gy) / gw, and that point's depth in front of
    # the camera is 1 / gw times the sign of det(P[:, :3]) (Hartley and Zisserman, 6.2.3). Where
    # that is not positive the pixel shows sky: the picture's part above the horizon is cut off.
    m3 = [row[:3] for row in P]
    det = (m3[0][0] * (m3[1][1] * m3[2][2] - m3[1][2] * m3[2][1])
           - m3[0][1] * (m3[1][0] * m3[2][2] - m3[1][2] * m3[2][0])
           + m3[0][2] * (m3[1][0] * m3[2][1] - m3[1][1] * m3[2][0]))
    sign = 1.0 if det > 0 else -1.0

    def back(u: float, v: float) -> tuple[float, float, float]:
        return tuple(r[0] * u + r[1] * v + r[2] for r in inv)  # type: ignore[return-value]

    corners = [(0.0, 0.0), (float(width), 0.0), (float(width), float(height)), (0.0, float(height))]
    homog = [back(u, v) for u, v in corners]
    # Keep only what is in front, with a margin so the division below stays finite: a point that
    # far is cut to FAR_M next anyway.
    eps = 1e-6 * max(abs(g[2]) for g in homog)

    def front(g):
        return sign * g[2] > eps

    def at_front(a, b):
        wa, wb = sign * a[2] - eps, sign * b[2] - eps
        s = wa / (wa - wb)
        return tuple(pa + s * (pb - pa) for pa, pb in zip(a, b, strict=True))

    homog = _clip(homog, front, at_front)
    poly: list[tuple[float, ...]] = [(g[0] / g[2], g[1] / g[2]) for g in homog]
    for axis, bound, keep_below in (
        (0, -FAR_M, False), (0, PITCH_X + FAR_M, True), (1, -FAR_M, False), (1, PITCH_Y + FAR_M, True),
    ):
        def inside(p, axis=axis, bound=bound, keep_below=keep_below):
            return p[axis] <= bound if keep_below else p[axis] >= bound

        def cross(a, b, axis=axis, bound=bound):
            s = (bound - a[axis]) / (b[axis] - a[axis])
            return tuple(pa + s * (pb - pa) for pa, pb in zip(a, b, strict=True))

        poly = _clip(poly, inside, cross)
        if not poly:
            return None
    return [(round(p[0], PLACES), round(p[1], PLACES)) for p in poly]


def build(tracked: dict, observations: list[dict], width: int, height: int) -> dict:
    """radar.json: the tracked frames, and for each observed frame whether the ball was seen and the
    picture's footprint."""
    frames = tracked["frames"]
    for f in frames:
        if f.get("source") != SOURCE:
            raise ValueError(f"frame {f.get('frame')}: source {f.get('source')!r}; the radar draws "
                             f"only vision's tracked positions")
    seen = {b.frame for b in ball_path(observations)}
    views = []
    for row in observations:
        cam = row["camera"]
        views.append({
            "frame": row["frame"],
            "ball_seen": row["frame"] in seen,
            # Fused from the fixed tactical views (ninety/vision/fuse.py), a frame has no broadcast
            # camera fit, so the broadcast picture's footprint is unknown, not guessed.
            "footprint": footprint(cam["P"], width, height) if cam["ok"] and "P" in cam else None,
        })
    clip = frames[0].get("clip") if frames else None
    return {"format": FORMAT, "source": SOURCE, "clip": clip, "frames": frames, "views": views}


def read_observations(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def write(tracked: Path, observations: Path, width: int, height: int, out: Path) -> dict:
    body = build(json.loads(tracked.read_text()), read_observations(observations), width, height)
    out.write_text(json.dumps(body, separators=(",", ":")) + "\n")
    return body


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("tracked", type=Path, help="tracked.json (ninety.vision.tracked_frames)")
    ap.add_argument("observations", type=Path, help="observations.jsonl (ninety.vision.observe)")
    ap.add_argument("--width", type=int, required=True, help="the picture's width in pixels")
    ap.add_argument("--height", type=int, required=True, help="the picture's height in pixels")
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args(argv)
    body = write(args.tracked, args.observations, args.width, args.height, args.out)
    shown = sum(v["footprint"] is not None for v in body["views"])
    n = len(body["views"])
    print(f"{args.out}: {len(body['frames'])} tracked frames, {shown} of {n} with a footprint")


if __name__ == "__main__":
    main()
