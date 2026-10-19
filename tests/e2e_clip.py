"""A tiny clip on disk for the ninety-e2e and viewer tests: three seconds, a shot and two passes.

The events are written here, by hand, in the match_event schema; nothing comes from the engine, so
the tests pin the pipeline, not a seed's football.
"""

from __future__ import annotations

import json
from pathlib import Path

FPS, SECONDS, T_START, W, H = 25, 3, 60.0, 320, 180
MODEL = {"name": "rf-detr", "size": "small", "version": "fixture", "checkpoint": "ours-v2"}

EVENTS = [
    {"id": "e1", "t": 60.4, "frame": 1510, "type": "pass", "team": "home", "player": "h4", "receiver": "h8",
     "intended": "h8", "interceptor": None, "deflected_by": None, "x": 40.0, "y": 30.0, "end_x": 52.0,
     "end_y": 35.0, "outcome": "success", "ball_speed_kmh": 48.0, "source": "truth", "confidence": None},
    {"id": "e2", "t": 61.2, "frame": 1530, "type": "shot", "team": "home", "player": "h8", "receiver": None,
     "x": 80.0, "y": 34.0, "end_x": 104.0, "end_y": 33.0, "outcome": "on_target", "ball_speed_kmh": 101.4,
     "source": "truth", "confidence": None},
    {"id": "e3", "t": 62.3, "frame": 1557, "type": "pass", "team": "away", "player": "a1", "receiver": "a5",
     "intended": "a5", "interceptor": None, "deflected_by": None, "x": 100.0, "y": 34.0, "end_x": 80.0,
     "end_y": 20.0, "outcome": "success", "ball_speed_kmh": 55.0, "source": "truth", "confidence": None},
]


def write_clip(root: Path, jpeg: bytes = b"not a real jpeg") -> tuple[Path, Path]:
    """The clip directory and its detections file. `jpeg` is every frame's bytes."""
    clip = root / "clip"
    (clip / "images").mkdir(parents=True)
    frames = FPS * SECONDS
    meta = {"clip_id": "seed42", "seed": 42, "fps": FPS, "frames": frames, "t_start": T_START,
            "t_end": T_START + (frames - 1) / FPS, "params": {"width": W, "height": H}}
    (clip / "clip.json").write_text(json.dumps(meta))
    (clip / "events.jsonl").write_text("".join(json.dumps(e) + "\n" for e in EVENTS))
    rows = []
    for i in range(frames):
        (clip / "images" / f"{i:05d}.jpg").write_bytes(jpeg)
        boxes = [{"cls": "player", "bbox": [100.0 + i, 60.0, 112.0 + i, 90.0], "score": 0.9},
                 {"cls": "ball", "bbox": [150.0, 80.0, 154.0, 84.0], "score": 0.7}]
        rows.append({"clip": "seed42", "frame": 1500 + i, "t": round(T_START + i / FPS, 2), "model": MODEL,
                     "detections": boxes})
    detections = root / "detections.jsonl"
    detections.write_text("".join(json.dumps(r) + "\n" for r in rows))
    return clip, detections
