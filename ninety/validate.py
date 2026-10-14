"""Check a clip of ground-truth data against the data contract (docs/DATA_CONTRACT.md).

Valid is not enough: the events and the frames must tell the same story, the frames must be
physically possible, and the match must be legal football. Every check names its ID in the
register, docs/GROUNDING.md (C consistency, P physics, L Laws of the Game), where its source is.

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
MAX_PLAYER_MPS = 10.5  # P1: peak match sprint speeds
MAX_PLAYER_ACCEL = 8.0  # P2: speeding up; professionals reach about 5.2 m/s² from standing, plus margin
MAX_PLAYER_BRAKE = 10.0  # P2: braking and turning; peak braking about 8.5 m/s² (SD 1.1), plus margin
ACCEL_WINDOW_S = 0.2  # P2: speeds averaged over this window, so frame jitter is not acceleration
MAX_BALL_MPS = 40.0  # P3: above the hardest shots on record
GRAVITY = 9.81  # P5
# P5: air drag adds up to K * speed * vertical speed to the vertical acceleration. K for a
# football with a drag coefficient up to 0.5 (radius 0.11 m, 410 g, air 1.2 kg/m³); verify.
DRAG_K_MAX = 0.5 * 1.2 * 0.5 * math.pi * 0.11**2 / 0.41
POSITION_PRECISION_M = 0.0005  # positions are written to the nearest millimetre

AIRBORNE_M = 0.3  # P5: the ball is in flight above this height
AT_FEET_M = 1.5  # P6: how far the ball may be from the player who has it
IN_HANDS_M = 2.0  # P6: a goalkeeper may hold it at arm's length in their penalty area (Law 12); verify
PENALTY_DEPTH, PENALTY_HALF_WIDTH = 16.5, 20.16  # Law 1
NEAR_M = 2.5  # C6, C7: how close the ball must be to where an event says it happened
ON_BALL = {"pass", "shot", "tackle", "interception", "out_of_play", "goal", "set_piece", "kickoff"}
MAX_SUBSTITUTIONS = 5  # C3: Law 3, top-level competitions
STOPPAGES = {"out_of_play", "goal", "substitution"}  # C3: events after which play has stopped
RESTARTS = {"set_piece", "kickoff"}  # P3: events that put the ball back in play
EXAMPLES = 5

Problems = dict[str, list[str]]


def _load_jsonl(path: Path) -> list[dict]:
    with open(path) as f:
        return [json.loads(line) for line in f if line.strip()]


def check_schema(events: list[dict], frames: list[dict], problems: Problems) -> None:
    """C1: every row matches its published schema."""
    event_schema = Draft202012Validator(json.loads((ROOT / "schemas/match_event.schema.json").read_text()))
    frame_schema = Draft202012Validator(json.loads((ROOT / "schemas/frame.schema.json").read_text()))
    for e in events:
        for err in event_schema.iter_errors(e):
            problems["C1 event schema"].append(f"{e.get('id')}: {err.message}")
        if e.get("source") != "truth":
            problems["C1 event schema"].append(f"{e.get('id')}: ground-truth events must have source 'truth'")
    for f in frames:
        for err in frame_schema.iter_errors(f):
            problems["C1 frame schema"].append(f"frame {f.get('frame')}: {err.message}")


def check_frames(events: list[dict], frames: list[dict], fps: float, problems: Problems) -> None:
    """C2 frame order; C3 the same players throughout, except legal substitutions."""
    for i, f in enumerate(frames):
        if f["frame"] != frames[0]["frame"] + i:
            problems["C2 frame order"].append(f"frame {f['frame']} at position {i}")
        if abs(f["t"] - f["frame"] / fps) > 0.5 / fps:
            problems["C2 frame order"].append(f"frame {f['frame']}: t {f['t']} != frame / fps")

    subs = {e["frame"]: e for e in events if e["type"] == "substitution"}
    made: dict[str, int] = defaultdict(int)
    for prev, f in zip(frames, frames[1:], strict=False):
        before = {p["id"]: p["team"] for p in prev["players"]}
        after = {p["id"]: p["team"] for p in f["players"]}
        if before == after:
            continue
        sub = subs.get(f["frame"])
        expected = None
        if sub:
            expected = {k: v for k, v in before.items() if k != sub["player"]}
            expected[sub["receiver"]] = sub["team"]
        if sub is None or after != expected:
            problems["C3 roster"].append(f"frame {f['frame']}: players change without a substitution")
            continue
        earlier = [e for e in events if e["frame"] < sub["frame"] and e["type"] != "pressure"]
        if not earlier or earlier[-1]["type"] not in STOPPAGES:
            problems["C3 roster"].append(f"{sub['id']}: substitution while the ball is in play")
        made[sub["team"]] += 1
        if made[sub["team"]] > MAX_SUBSTITUTIONS:
            problems["C3 roster"].append(f"{sub['id']}: {sub['team']} over {MAX_SUBSTITUTIONS} substitutions")


def check_physics(events: list[dict], frames: list[dict], fps: float, roster: list[dict],
                  problems: Problems) -> None:
    """P1 to P6: speeds, acceleration, ground, gravity, ball at the possessor's feet."""
    dt = 1 / fps
    # A kickoff restart may move everyone at once: the renderer cuts there.
    restarts = {e["frame"] for e in events if e["type"] == "kickoff"}
    # While the ball is out of play (Law 9) a new ball may be placed for the restart.
    dead: set[int] = set()
    out_at = None
    for e in events:
        if e["type"] == "out_of_play" and out_at is None:
            out_at = e["frame"]
        elif e["type"] in RESTARTS and out_at is not None:
            dead.update(range(out_at, e["frame"] + 1))
            out_at = None

    for prev, f in zip(frames, frames[1:], strict=False):
        if f["frame"] in restarts or prev["frame"] in restarts:
            continue
        before = {p["id"]: p for p in prev["players"]}
        for p in f["players"]:
            if p["id"] not in before:
                continue
            q = before[p["id"]]
            speed = math.hypot(p["x"] - q["x"], p["y"] - q["y"]) / dt
            if speed > MAX_PLAYER_MPS:
                problems["P1 player speed"].append(f"frame {f['frame']}: {p['id']} moved at {speed:.1f} m/s")
        b, a = prev["ball"], f["ball"]
        speed = math.dist((a["x"], a["y"], a["z"]), (b["x"], b["y"], b["z"])) / dt
        if speed > MAX_BALL_MPS and f["frame"] not in dead:
            problems["P3 ball speed"].append(f"frame {f['frame']}: ball moved at {speed:.1f} m/s")

    # P2: acceleration from speeds averaged over a short window, skipping windows with a restart.
    w = max(1, round(ACCEL_WINDOW_S * fps))
    span = w * dt
    for i in range(len(frames) - 2 * w):
        f0, f1, f2 = frames[i], frames[i + w], frames[i + 2 * w]
        if any(f0["frame"] <= r <= f2["frame"] for r in restarts):
            continue
        p0, p1 = {p["id"]: p for p in f0["players"]}, {p["id"]: p for p in f1["players"]}
        for p in f2["players"]:
            if p["id"] not in p0 or p["id"] not in p1:
                continue
            a, b = p0[p["id"]], p1[p["id"]]
            ax = (p["x"] - 2 * b["x"] + a["x"]) / span**2
            ay = (p["y"] - 2 * b["y"] + a["y"]) / span**2
            accel = math.hypot(ax, ay)
            # Split along the run: speeding up is limited far more than braking or turning.
            vx, vy = (p["x"] - a["x"]) / (2 * span), (p["y"] - a["y"]) / (2 * span)
            speed = math.hypot(vx, vy)
            forward = (ax * vx + ay * vy) / speed if speed > 0.5 else accel
            if forward > MAX_PLAYER_ACCEL or accel > MAX_PLAYER_BRAKE:
                problems["P2 player acceleration"].append(
                    f"frame {f1['frame']}: {p['id']} accelerated at {accel:.1f} m/s² "
                    f"({forward:.1f} speeding up)"
                )

    for f in frames:
        if f["ball"]["z"] < 0:
            problems["P4 ball below ground"].append(f"frame {f['frame']}: z {f['ball']['z']}")

    # P5: in flight with nobody touching it, the ball falls under gravity. Rounding each of the
    # three heights by up to POSITION_PRECISION_M moves the measured acceleration by up to
    # 4 * precision / dt², so that is the margin.
    margin = 4 * POSITION_PRECISION_M / dt**2
    for f0, f1, f2 in zip(frames, frames[1:], frames[2:], strict=False):
        if f1["frame"] in restarts or any(f.get("possessor") for f in (f0, f1, f2)):
            continue
        z = (f0["ball"]["z"], f1["ball"]["z"], f2["ball"]["z"])
        if min(z) <= AIRBORNE_M:
            continue
        az = (z[2] - 2 * z[1] + z[0]) / dt**2
        b0, b2 = f0["ball"], f2["ball"]
        v = [(b2[k] - b0[k]) / (2 * dt) for k in ("x", "y", "z")]
        allowed = DRAG_K_MAX * math.hypot(*v) * abs(v[2]) + margin
        if abs(az + GRAVITY) > allowed:
            problems["P5 ball flight"].append(
                f"frame {f1['frame']}: ball in the air accelerates {az:.1f} m/s² vertically; "
                f"gravity and drag allow -{GRAVITY} ± {allowed:.1f}"
            )

    keepers = {p["id"] for p in roster if p.get("role") == "GK"}
    for f in frames:
        pid = f.get("possessor")
        if not pid:
            continue
        holder = next((p for p in f["players"] if p["id"] == pid), None)
        if holder is None:
            problems["P6 ball at feet"].append(f"frame {f['frame']}: possessor {pid} is not on the pitch")
            continue
        gap = math.hypot(f["ball"]["x"] - holder["x"], f["ball"]["y"] - holder["y"])
        in_a_box = (min(holder["x"], 105 - holder["x"]) <= PENALTY_DEPTH
                    and abs(holder["y"] - 34) <= PENALTY_HALF_WIDTH)
        if gap > (IN_HANDS_M if pid in keepers and in_a_box else AT_FEET_M):
            problems["P6 ball at feet"].append(f"frame {f['frame']}: ball {gap:.1f} m from {pid}, who has it")


def check_events(events: list[dict], frames: list[dict], fps: float, meta: dict, problems: Problems) -> None:
    """C4 to C9: events agree with frames, come in an order that makes sense, and add up."""
    by_frame = {f["frame"]: f for f in frames}
    first, last = frames[0]["frame"], frames[-1]["frame"]
    team_of = {p["id"]: p["team"] for f in frames for p in f["players"]}

    for e in events:
        for role in ("player", "receiver"):
            pid = e.get(role)
            if pid is not None and pid not in team_of:
                problems["C4 event players"].append(f"{e['id']}: {role} {pid} is not in the frames")
        if e["type"] in ("pass", "shot", "goal") and team_of.get(e.get("player"), e["team"]) != e["team"]:
            problems["C4 event players"].append(f"{e['id']}: {e['player']} does not play for {e['team']}")
        f = by_frame.get(e.get("frame"))
        if f is None:
            problems["C5 event frame"].append(f"{e['id']}: frame {e.get('frame')} is not in frames.jsonl")
            continue
        if abs(e["t"] - f["t"]) > 1.5 / fps:
            problems["C5 event frame"].append(f"{e['id']}: t {e['t']} but frame {f['frame']} is at {f['t']}")
        if e["type"] in ("pass", "shot", "tackle"):
            gap = math.hypot(f["ball"]["x"] - e["x"], f["ball"]["y"] - e["y"])
            if gap > NEAR_M:
                problems["C6 event location"].append(f"{e['id']} {e['type']}: ball {gap:.1f} m away")
        if e["type"] in ("pass", "shot") and e.get("end_x") is not None:
            # The ball reaches the end point before anything else happens to it. No assumption
            # about speed: a rolling ball slows down.
            later = [n["frame"] for n in events if n["frame"] > e["frame"] and n["type"] in ON_BALL]
            until = min(later, default=last)
            balls = [by_frame[n]["ball"] for n in range(e["frame"], until + 1) if n in by_frame]
            if not any(math.hypot(b["x"] - e["end_x"], b["y"] - e["end_y"]) <= NEAR_M for b in balls):
                where = f"({e['end_x']}, {e['end_y']})"
                problems["C7 ball path"].append(f"{e['id']} {e['type']}: ball never reaches {where}")
        if e["type"] in ("pass", "shot") and e["frame"] > first:
            # The player had the ball just before playing it; possession may clear on the
            # frame the ball leaves.
            had = {by_frame[n].get("possessor") for n in (e["frame"] - 1, e["frame"]) if n in by_frame}
            if e.get("player") not in had:
                problems["C8 event order"].append(f"{e['id']} {e['type']}: {e.get('player')} lacked the ball")

    passes = [e for e in events if e["type"] == "pass"]
    shots = [e for e in events if e["type"] == "shot"]
    for e in events:
        if e["type"] == "interception":
            before = [p for p in passes if p["frame"] <= e["frame"]]
            if not before or before[-1]["outcome"] != "fail" or before[-1]["receiver"] != e["player"]:
                problems["C8 event order"].append(f"{e['id']}: {e['player']} intercepted no failed pass")
        if e["type"] == "goal":
            before = [s for s in shots if s["frame"] <= e["frame"]]
            if not before or before[-1]["outcome"] != "goal" or before[-1]["player"] != e["player"]:
                problems["C8 event order"].append(f"{e['id']}: goal by {e['player']} without a scoring shot")

    if isinstance(meta.get("score"), dict):
        goals: dict[str, int] = defaultdict(int)
        for e in events:
            if e["type"] == "goal":
                goals[e["team"]] += 1
        for team in ("home", "away"):
            if meta["score"].get(team, 0) != goals[team]:
                problems["C9 score"].append(
                    f"meta says {team} scored {meta['score'].get(team, 0)}, goal events say {goals[team]}"
                )


def validate(clip: Path) -> Problems:
    """Returns failures by check; an empty dict means the clip meets the contract."""
    problems: Problems = defaultdict(list)
    for name in ("events.jsonl", "frames.jsonl", "meta.json"):
        if not (clip / name).exists():
            problems["C1 files"].append(f"missing {name}")
    if problems:
        return dict(problems)

    meta = json.loads((clip / "meta.json").read_text())
    events, frames = _load_jsonl(clip / "events.jsonl"), _load_jsonl(clip / "frames.jsonl")
    fps = meta.get("fps")
    if not isinstance(fps, (int, float)) or fps <= 0:
        problems["C1 files"].append("meta.json needs a positive fps")
        return dict(problems)

    # Later checks assume well-formed rows and ordered frames, so stop early if not.
    check_schema(events, frames, problems)
    if problems:
        return dict(problems)
    check_frames(events, frames, fps, problems)
    if any(k.startswith("C2") for k in problems):
        return dict(problems)
    check_physics(events, frames, fps, meta.get("roster", []), problems)
    check_events(events, frames, fps, meta, problems)
    return dict(problems)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("clip", type=Path, help="directory with events.jsonl, frames.jsonl and meta.json")
    args = ap.parse_args()
    problems = validate(args.clip)
    if not problems:
        print(f"{args.clip}: meets the data contract")
        return
    for check, items in sorted(problems.items()):
        print(f"FAIL {check}: {len(items)}")
        for item in items[:EXAMPLES]:
            print(f"  {item}")
    sys.exit(1)


if __name__ == "__main__":
    main()
