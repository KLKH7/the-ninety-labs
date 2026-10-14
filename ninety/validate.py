"""Check a clip of ground-truth data against the data contract (docs/DATA_CONTRACT.md).

Valid is not enough: the events and the frames must tell the same story, and the frames must be
physically possible, because the video is drawn from the frames and graded against the events.

    uv run ninety-validate runs/seed7
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
MAX_PLAYER_MPS = 10.5  # the fastest sprinters reach about 10 m/s
MAX_BALL_MPS = 40.0  # about 145 km/h, above the hardest shots on record
NEAR_M = 2.5  # how close the ball must be to where an event says it happened
ARRIVE_SLACK_S = 0.5  # extra time a pass or shot may take beyond its stated speed
EXAMPLES = 5


def _load_jsonl(path: Path) -> list[dict]:
    with open(path) as f:
        return [json.loads(line) for line in f if line.strip()]


def validate(clip: Path) -> dict[str, list[str]]:
    """Returns failures by check name; an empty dict means the clip meets the contract."""
    problems: dict[str, list[str]] = defaultdict(list)
    for name in ("events.jsonl", "frames.jsonl", "meta.json"):
        if not (clip / name).exists():
            problems["files"].append(f"missing {name}")
    if problems:
        return dict(problems)

    meta = json.loads((clip / "meta.json").read_text())
    events, frames = _load_jsonl(clip / "events.jsonl"), _load_jsonl(clip / "frames.jsonl")
    fps = meta.get("fps")
    if not isinstance(fps, (int, float)) or fps <= 0:
        problems["meta"].append("meta.json needs a positive fps")
        return dict(problems)

    event_schema = Draft202012Validator(json.loads((ROOT / "schemas/match_event.schema.json").read_text()))
    frame_schema = Draft202012Validator(json.loads((ROOT / "schemas/frame.schema.json").read_text()))
    for e in events:
        for err in event_schema.iter_errors(e):
            problems["event schema"].append(f"{e.get('id')}: {err.message}")
        if e.get("source") != "truth":
            problems["event schema"].append(f"{e.get('id')}: ground-truth events must have source 'truth'")
    for f in frames:
        for err in frame_schema.iter_errors(f):
            problems["frame schema"].append(f"frame {f.get('frame')}: {err.message}")
    if problems:
        return dict(problems)

    # Frames: consecutive, timed by fps, the same players throughout.
    roster = {p["id"]: p["team"] for p in frames[0]["players"]}
    for i, f in enumerate(frames):
        if f["frame"] != frames[0]["frame"] + i:
            problems["frame order"].append(f"frame {f['frame']} at position {i}")
        if abs(f["t"] - f["frame"] / fps) > 0.5 / fps:
            problems["frame order"].append(f"frame {f['frame']}: t {f['t']} != frame / fps")
        if {p["id"]: p["team"] for p in f["players"]} != roster:
            problems["roster"].append(f"frame {f['frame']}: players differ from frame {frames[0]['frame']}")
    if problems:
        return dict(problems)

    # Physics. A kickoff restart may move everyone at once (the renderer cuts there).
    restarts = {e["frame"] for e in events if e["type"] == "kickoff" and "frame" in e}
    dt = 1 / fps
    for prev, f in zip(frames, frames[1:], strict=False):
        if f["frame"] in restarts or prev["frame"] in restarts:
            continue
        before = {p["id"]: p for p in prev["players"]}
        for p in f["players"]:
            q = before[p["id"]]
            speed = math.hypot(p["x"] - q["x"], p["y"] - q["y"]) / dt
            if speed > MAX_PLAYER_MPS:
                problems["player speed"].append(f"frame {f['frame']}: {p['id']} moved at {speed:.1f} m/s")
        b, a = prev["ball"], f["ball"]
        speed = math.dist((a["x"], a["y"], a["z"]), (b["x"], b["y"], b["z"])) / dt
        if speed > MAX_BALL_MPS:
            problems["ball speed"].append(f"frame {f['frame']}: ball moved at {speed:.1f} m/s")

    # Events agree with frames.
    by_frame = {f["frame"]: f for f in frames}
    last = frames[-1]["frame"]
    for e in events:
        for role in ("player", "receiver"):
            pid = e.get(role)
            if pid is not None and pid not in roster:
                problems["event players"].append(f"{e['id']}: {role} {pid} is not in the frames")
        if e.get("player") in roster and e["type"] not in ("tackle", "pressure", "interception"):
            if roster[e["player"]] != e["team"]:
                problems["event players"].append(f"{e['id']}: {e['player']} does not play for {e['team']}")
        f = by_frame.get(e.get("frame"))
        if f is None:
            problems["event frame"].append(f"{e['id']}: frame {e.get('frame')} is not in frames.jsonl")
            continue
        if abs(e["t"] - f["t"]) > 1.5 / fps:
            problems["event frame"].append(f"{e['id']}: t {e['t']} but frame {f['frame']} is at {f['t']}")
        if e["type"] in ("pass", "shot", "tackle"):
            ball = f["ball"]
            gap = math.hypot(ball["x"] - e["x"], ball["y"] - e["y"])
            if gap > NEAR_M:
                problems["event location"].append(f"{e['id']} {e['type']}: ball {gap:.1f} m from the event")
        if e["type"] in ("pass", "shot") and e.get("end_x") is not None and e.get("ball_speed_kmh"):
            # When the ball should arrive at its stated speed, plus slack. A clip that ends
            # before then cannot show the arrival, so only then is the check skipped.
            length = math.hypot(e["end_x"] - e["x"], e["end_y"] - e["y"])
            due = e["frame"] + math.ceil((length / (e["ball_speed_kmh"] / 3.6) + ARRIVE_SLACK_S) * fps)
            if due > last:
                continue
            balls = [by_frame[n]["ball"] for n in range(e["frame"], due + 1) if n in by_frame]
            if not any(math.hypot(b["x"] - e["end_x"], b["y"] - e["end_y"]) <= NEAR_M for b in balls):
                where = f"({e['end_x']}, {e['end_y']})"
                problems["ball path"].append(f"{e['id']} {e['type']}: ball never reaches {where}")
    return dict(problems)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("clip", type=Path, help="directory with events.jsonl, frames.jsonl and meta.json")
    args = ap.parse_args()
    problems = validate(args.clip)
    if not problems:
        print(f"{args.clip}: meets the data contract")
        return
    for check, items in problems.items():
        print(f"FAIL {check}: {len(items)}")
        for item in items[:EXAMPLES]:
            print(f"  {item}")
    sys.exit(1)


if __name__ == "__main__":
    main()
