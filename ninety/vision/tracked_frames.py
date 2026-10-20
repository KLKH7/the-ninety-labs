"""Tracked positions for the phone companion: observations -> tracks -> frames, `source: tracked`.

The companion's minimap, player cards and wind map read a clip's tracked frames file, one
`frame.schema.json` frame a line (ninety/match/tracking.py, `tracked`). This writes it from the
video, from the observations `ninety.vision.observe` makes, through the same tracks and teams as
event detection (ninety/vision/track.py). Nothing here reads ground truth: this is the live path
(tests/test_vision_live_path.py watches it run).

Three steps on top of track.py:
- **Smoothing.** A player's pitch position jumps by up to about 0.5 m between neighbouring frames
  with the camera fit (track.py, GATE_M), while a sprinter moves 0.34 m a frame. Summed frame to
  frame, that jitter is read as running: a standing player measured 16 km/h. Each position is
  taken from a straight line fitted to the track over SMOOTH_FRAMES around it (`smooth`). One
  second, because the phone's speed is itself a one-second mean (ninety/intel/window.py), so the
  smoothing hides no detail the speed shows. Chosen from that, before measuring;
  docs/eval/companion-tracked.md measures what it does against the ground truth, offline.
- **The ball** where it was not found (up to MAX_GAP_FRAMES) is placed on the straight line between
  the detections either side; outside a gap that short, a frame without a ball is left out. The
  pitch fit is a ground-plane fit, so the ball's height is not known: z is 0 by construction.
- **Ids.** The tracker sees no shirt numbers, so a tracked player is his side and his track, as
  `h-t12`; the phone names him "Home player, track 12".

    uv run python -m ninety.vision.tracked_frames <observations.jsonl> [--clip ID] [--out FILE]

Any clip's observations: the clip id defaults to the file's name (observations-<clip>.jsonl), and
the output to tracked-<clip>.jsonl beside it. The M1 fixture:

    uv run python -m ninety.vision.tracked_frames tests/fixtures/observations-seed900001.jsonl
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ninety.vision import track as tr

SOURCE = "tracked"
SMOOTH_FRAMES = tr.FPS  # one second (see the module docstring)
MAX_GAP_FRAMES = tr.MAX_GAP_FRAMES  # the tracker's own: longer than this, the position is a guess
# A track seen for less than one frame of the phone's 5 fps minimap cannot be drawn as moving, and
# is mostly a fragment of a crossing or a false detection (track.py, MIN_COLOUR_FRAMES).
MIN_TRACK_FRAMES = tr.FPS // 5
PLACES = 2  # cm: finer than the tracker's error, coarser than float noise


def player_id(t: tr.Track) -> str:
    return f"{t.team[0]}-t{t.id}"


def smooth(
    xy: list[tuple[float, float]], frames: list[int], width: int = SMOOTH_FRAMES
) -> list[tuple[float, float]]:
    """Each position from a straight line fitted to the track's positions within width/2 frames of
    it. Inside a track that is the plain average; at its ends, where the frames on one side run
    out, an average would lag behind a moving player (at the last frame, by a quarter of a
    second), while the line follows him."""
    half = width // 2
    out = []
    lo = hi = 0
    for f in frames:
        while frames[lo] < f - half:
            lo += 1
        while hi < len(frames) and frames[hi] <= f + half:
            hi += 1
        ts = frames[lo:hi]
        n = len(ts)
        mt = sum(ts) / n
        mx = sum(p[0] for p in xy[lo:hi]) / n
        my = sum(p[1] for p in xy[lo:hi]) / n
        var = sum((t - mt) ** 2 for t in ts)
        if var == 0:
            out.append((mx, my))
            continue
        bx = sum((t - mt) * (p[0] - mx) for t, p in zip(ts, xy[lo:hi], strict=True)) / var
        by = sum((t - mt) * (p[1] - my) for t, p in zip(ts, xy[lo:hi], strict=True)) / var
        out.append((mx + bx * (f - mt), my + by * (f - mt)))
    return out


def ball_positions(rows: list[dict]) -> dict[int, tuple[float, float]]:
    """The ball in every frame from the first detection to the last, gaps up to MAX_GAP_FRAMES
    filled on the straight line between the detections either side."""
    points = tr.ball_path(rows)
    out = {p.frame: (p.x, p.y) for p in points}
    for a, b in zip(points, points[1:], strict=False):
        gap = b.frame - a.frame
        if 1 < gap <= MAX_GAP_FRAMES:
            for k in range(1, gap):
                w = k / gap
                out[a.frame + k] = (a.x + (b.x - a.x) * w, a.y + (b.y - a.y) * w)
    return out


def build(rows: list[dict], clip: str, smooth_frames: int = SMOOTH_FRAMES) -> dict:
    """The tracked frames (each meets schemas/frame.schema.json) and how they were made. Kickoff
    resets are not here: the companion takes them from the clip's detected events."""
    tracks = tr.track_players(rows)
    teams = tr.assign_teams(tracks)
    kept = [t for t in tracks if t.team is not None and len(t.frames) >= MIN_TRACK_FRAMES]
    at: dict[int, list[dict]] = {}
    for t in kept:
        for f, (x, y) in zip(t.frames, smooth(t.xy, t.frames, smooth_frames), strict=True):
            at.setdefault(f, []).append(
                {"id": player_id(t), "team": t.team, "x": round(x, PLACES), "y": round(y, PLACES)}
            )
    ball = ball_positions(rows)
    frames = []
    for row in rows:
        f = row["frame"]
        if not row["camera"]["ok"] or f not in ball:
            continue
        bx, by = ball[f]
        frames.append({
            "frame": f,
            "t": round(f / tr.FPS, 2),
            "source": SOURCE,
            "clip": clip,
            "ball": {"x": round(bx, PLACES), "y": round(by, PLACES), "z": 0.0},
            "players": sorted(at.get(f, []), key=lambda p: p["id"]),
        })
    return {
        "frames": frames,
        "how": {
            "observations": len(rows),
            "tracks": len(tracks),
            "kept": len(kept),
            "smooth_frames": smooth_frames,
            "teams": teams["reason"],
        },
    }


def text(body: dict) -> str:
    """The file: one frame a line."""
    return "".join(json.dumps(f, separators=(",", ":")) + "\n" for f in body["frames"])


def clip_of(observations: Path) -> str:
    stem = observations.stem
    if not stem.startswith("observations-") or stem == "observations-":
        raise SystemExit(f"{observations}: name it observations-<clip>.jsonl, or pass --clip")
    return stem.removeprefix("observations-")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("observations", type=Path, help="observations.jsonl from ninety.vision.observe")
    ap.add_argument("--clip", help="the clip id (default: from observations-<clip>.jsonl)")
    ap.add_argument("--out", type=Path, help="where to write (default: tracked-<clip>.jsonl beside it)")
    args = ap.parse_args(argv)
    clip = args.clip or clip_of(args.observations)
    args.out = args.out or args.observations.with_name(f"tracked-{clip}.jsonl")
    body = build(tr.read_observations(args.observations), clip)
    args.out.write_text(text(body))
    how = body["how"]
    print(f"{args.out}: {len(body['frames'])} frames, {how['kept']} of {how['tracks']} tracks")


if __name__ == "__main__":
    main()
