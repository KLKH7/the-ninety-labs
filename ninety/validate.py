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

from ninety.sim import body as _body

ROOT = Path(__file__).resolve().parents[1]
MAX_PLAYER_MPS = 10.5  # P1: peak match sprint speeds
# P2: speeding up. Professionals reach about 5.2 m/s² (SD 0.46) from standing; 8 allows the
# fastest accelerators and is a design margin, not derived. Braking and turning: peak braking
# about 8.5 m/s² (SD 1.1), so mean plus one SD is about 9.6, rounded to 10.
MAX_PLAYER_ACCEL = 8.0
MAX_PLAYER_BRAKE = 10.0
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
STOPPAGES = {"out_of_play", "goal", "substitution", "offside", "foul"}  # C3: play has stopped after these
DEAD_FROM = {"out_of_play", "offside", "foul"}  # dead from these until the restart (Laws 9, 11, 12)
RESTARTS = {"set_piece", "kickoff"}  # P3: events that put the ball back in play
TOUCHES = {"pass", "shot", "deflection", "interception", "tackle", "possession_change"}  # P5
# C8: events that are a touch of the ball by their player (who then touched it last)
GOAL_TOUCHES = {"pass", "shot", "deflection", "interception", "tackle", "possession_change"}
# P14: a touch by someone other than the carrier must be physically possible: the player within
# reach of the ball, which was not moving away from him. Reach is a foot (1 m) or a diving
# keeper in his box (1.48 m: P11, his centre of mass to his stretched fingertips), plus one frame of
# the ball's and the player's motion.
CONTACTS = {"deflection", "interception"}
FOOT_REACH_M, KEEPER_REACH_M, FRAME_SLACK_M = 1.0, 1.48, 0.6
# P14 (P11): no player plays a ball higher than a jumping keeper's hands reach (the ball's lowest
# point): no header goes that high, and a keeper's hands no higher.
TOUCH_HEIGHT_MAX_M = _body.KEEPER_STATURE_M * _body.STANDING_REACH_SHARE + _body.KEEPER_JUMP_M  # about 3.0 m
# P5: the goal frame (Law 1: posts 7.32 m apart, bar 2.44 m high) is a contact too; a ball
# within this distance of it may rebound without an event.
WOODWORK_NEAR_M = 0.6
APPROACH_TOLERANCE_M = 0.04  # P14: per frame; a ball at 1 m/s relative to him can still be met
# L9 (Law 17): over the goal line, last touched by a defender, the attacking team takes a corner
# with the ball in the corner area: within the 1 m arc, where a ball resting on the arc or a line
# is in (Law 1: lines belong to the areas they mark), so its centre may be up to a ball radius
# beyond them. The ball is stationary until it is kicked, and opponents stay 9.15 m from the arc
# until then. The largest legal ball (Law 2: 70 cm round) has a radius of 0.1114 m.
CORNER_ARC_M, CORNER_DISTANCE_M, BALL_RADIUS_M = 1.0, 9.15, 0.70 / (2 * math.pi)
# Law 2: 68 to 70 cm round. Whether the whole ball is over or inside is judged with the smallest
# legal ball (the lenient choice); whether it could be past a line, with the largest.
BALL_RADIUS_MIN_M = 0.68 / (2 * math.pi)
GOAL_HALF_WIDTH_M, CROSSBAR_M = 3.66, 2.44  # L6: Law 1, posts 7.32 m apart, bar 2.44 m high
POST_WIDTH_M = 0.12  # P17: Law 1, posts and crossbar at most 12 cm wide
# Rounding: a point rounded to 0.5 mm in x and y lies within √2 × 0.5 mm of where it was, so its
# distance to an exact point (the flag) is off by at most that. Two positions of the same still
# ball, each rounded in x, y and z, differ by at most 2 × √3 × 0.5 mm.
POINT_PRECISION_M = math.sqrt(2) * POSITION_PRECISION_M
STILL_PRECISION_M = 2 * math.sqrt(3) * POSITION_PRECISION_M
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
        if e["type"] in DEAD_FROM and out_at is None:
            out_at = e["frame"]
        elif e["type"] in RESTARTS and out_at is not None:
            dead.update(range(out_at, e["frame"] + 1))
            out_at = None
    if out_at is not None and frames:  # the clip ends before the restart: the ball is still dead
        dead.update(range(out_at, frames[-1]["frame"] + 1))

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
            # Speeding up is limited far more than braking or turning, so measure the actual change
            # in speed between the two half-windows, then the total change against the grip limit.
            v1 = math.hypot(b["x"] - a["x"], b["y"] - a["y"]) / span
            v2 = math.hypot(p["x"] - b["x"], p["y"] - b["y"]) / span
            forward = (v2 - v1) / span
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
    # Free flight only: frames where a player touched the ball are not judged against gravity.
    touched = {e["frame"] + k for e in events if e["type"] in TOUCHES for k in (-1, 0, 1)}
    for f0, f1, f2 in zip(frames, frames[1:], frames[2:], strict=False):
        if f1["frame"] in restarts or f1["frame"] in touched or any(f.get("possessor") for f in (f0, f1, f2)):
            continue
        if any(near_woodwork(f["ball"]) for f in (f0, f1, f2)):
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
    check_contacts(events, frames, keepers, problems)
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


def near_woodwork(b: dict) -> bool:
    """P5: within reach of a post or the crossbar, where the ball may rebound."""
    on_line = min(abs(b["x"]), abs(105 - b["x"])) <= WOODWORK_NEAR_M
    in_frame = abs(b["y"] - 34) <= 3.66 + WOODWORK_NEAR_M and b["z"] <= 2.44 + WOODWORK_NEAR_M
    return on_line and in_frame


def check_contacts(events: list[dict], frames: list[dict], keepers: set[str], problems: Problems) -> None:
    """P14: a deflection or interception names a player who could have touched the ball, and no touch
    (those, a pass or a shot) is higher than a player can reach (a jumping keeper's hands)."""
    by_frame = {f["frame"]: f for f in frames}
    for e in events:
        if e["type"] not in CONTACTS | {"pass", "shot"} or not e.get("player"):
            continue
        f = by_frame.get(e["frame"])
        if f is None:
            continue
        if f["ball"]["z"] > TOUCH_HEIGHT_MAX_M + FRAME_SLACK_M:
            problems["P14 touch possible"].append(
                f"{e['id']}: {e['type']} by {e['player']} with the ball {f['ball']['z']:.1f} m up")
    for e in events:
        if e["type"] not in CONTACTS or not e.get("player"):
            continue
        f, before, earlier = (by_frame.get(e["frame"] - k) for k in (0, 1, 2))
        if f is None:
            continue

        me = next((q for q in f["players"] if q["id"] == e["player"]), None)
        if me is None:
            continue
        now = math.hypot(f["ball"]["x"] - me["x"], f["ball"]["y"] - me["y"])
        in_box = min(me["x"], 105 - me["x"]) <= PENALTY_DEPTH and abs(me["y"] - 34) <= PENALTY_HALF_WIDTH
        reach = (KEEPER_REACH_M if e["player"] in keepers and in_box else FOOT_REACH_M) + FRAME_SLACK_M
        if now > reach:
            problems["P14 touch possible"].append(
                f"{e['id']}: {e['type']} by {e['player']}, {now:.1f} m from the ball")
            continue
        if before and earlier:
            # A ball already within his reach can be touched whichever way it moves. One that was
            # out of reach and moving away from him a frame before cannot be back within reach now.
            p1 = next((q for q in before["players"] if q["id"] == e["player"]), None)
            p2 = next((q for q in earlier["players"] if q["id"] == e["player"]), None)
            if p1 is not None and p2 is not None:
                d1 = math.hypot(before["ball"]["x"] - p1["x"], before["ball"]["y"] - p1["y"])
                d2 = math.hypot(earlier["ball"]["x"] - p2["x"], earlier["ball"]["y"] - p2["y"])
                if d1 > reach and d1 - d2 > APPROACH_TOLERANCE_M:
                    problems["P14 touch possible"].append(
                        f"{e['id']}: {e['type']} by {e['player']}, but the ball was moving away from him")


def check_events(events: list[dict], frames: list[dict], fps: float, meta: dict, problems: Problems) -> None:
    """C4 to C9: events agree with frames, come in an order that makes sense, and add up."""
    keepers = {p["id"] for p in meta.get("roster", []) if p.get("role") == "GK"}
    lines = defended_lines(frames, keepers)
    by_frame = {f["frame"]: f for f in frames}
    first, last = frames[0]["frame"], frames[-1]["frame"]
    team_of = {p["id"]: p["team"] for f in frames for p in f["players"]}

    for e in events:
        for role in ("player", "receiver", "intended", "interceptor"):
            pid = e.get(role)
            if pid is not None and pid not in team_of:
                problems["C4 event players"].append(f"{e['id']}: {role} {pid} is not in the frames")
        if e["type"] == "pass":  # who a pass reached, who it was for and who cut it out are three people
            for role, same in (("receiver", True), ("intended", True), ("interceptor", False)):
                pid = e.get(role)
                if pid in team_of and (team_of[pid] == e["team"]) != same:
                    side = "the passer's team" if same else "the other team"
                    problems["C4 event players"].append(f"{e['id']}: pass {role} {pid} is not on {side}")
            if e.get("receiver") and e.get("outcome") != "success":
                problems["C4 event players"].append(f"{e['id']}: a pass with a receiver did not succeed")
            if e.get("interceptor") and e.get("outcome") != "fail":
                problems["C4 event players"].append(f"{e['id']}: an intercepted pass did not fail")
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
            # The player had the ball just before playing it (possession may clear on the frame the
            # ball leaves), or played it first time: the ball within his reach (P14) as he struck it.
            had = {by_frame[n].get("possessor") for n in (e["frame"] - 1, e["frame"]) if n in by_frame}
            me = next((q for q in f["players"] if q["id"] == e.get("player")), None)
            before = by_frame.get(e["frame"] - 1)
            loose = before is not None and before.get("possessor") is None  # nobody had it a frame before
            first_time = loose and me is not None and \
                math.hypot(f["ball"]["x"] - me["x"], f["ball"]["y"] - me["y"]) <= FOOT_REACH_M + FRAME_SLACK_M
            if e.get("player") not in had and not first_time:
                problems["C8 event order"].append(f"{e['id']} {e['type']}: {e.get('player')} lacked the ball")

    passes = [e for e in events if e["type"] == "pass"]
    order = {e["id"]: k for k, e in enumerate(events)}
    for e in passes:
        if e.get("receiver") and e["receiver"] == e["player"]:
            problems["C8 event order"].append(f"{e['id']}: a pass received by its own passer")
    for e in events:
        if e["type"] == "interception":
            # the passes recorded before it: in the order recorded, since an interceptor may play
            # the ball on in the same frame (a header, P18), after his interception
            before = [p for p in passes if order[p["id"]] < order[e["id"]]]
            if not before or before[-1]["outcome"] != "fail" or before[-1].get("interceptor") != e["player"]:
                problems["C8 event order"].append(f"{e['id']}: {e['player']} intercepted no failed pass")
        if e["type"] == "goal":
            why = goal_credit_problem(e, events, frames, team_of)
            if why:
                problems["C8 event order"].append(f"{e['id']}: {why}")
            crossing = goal_crossing_problem(e, events, by_frame, fps, lines)
            if crossing:
                problems["L6 goal"].append(f"{e['id']}: {crossing}")

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


def defended_lines(frames: list[dict], keepers: set[str]) -> dict[str, float]:
    """The goal line each team defends: the one nearer its keeper's mean position over the clip.
    One frame can mislead (a keeper up for a late corner, or off his line after a cross); the
    whole clip does not."""
    xs: dict[str, list[float]] = defaultdict(list)
    for f in frames:
        for p in f["players"]:
            if p["id"] in keepers:
                xs[p["team"]].append(p["x"])
    return {team: 0.0 if sum(v) / len(v) < 52.5 else 105.0 for team, v in xs.items()}


def frame_axes(line: float) -> list[tuple[tuple[float, float, float], tuple[float, float, float]]]:
    """Law 1: the goal frame on this goal line as three axes (x, y, height): both posts from the
    ground to the bar, and the crossbar between them. Inner edges 7.32 m apart and 2.44 m high,
    posts and bar POST_WIDTH_M wide, so each axis is half that further out."""
    half = POST_WIDTH_M / 2
    lo, hi, top = 34.0 - GOAL_HALF_WIDTH_M - half, 34.0 + GOAL_HALF_WIDTH_M + half, CROSSBAR_M + half
    return [((line, lo, 0.0), (line, lo, top)), ((line, hi, 0.0), (line, hi, top)),
            ((line, lo, top), (line, hi, top))]


def segment_gap(p0: tuple, p1: tuple, q0: tuple, q1: tuple) -> float:
    """Closest distance between segments p0-p1 and q0-q1 in 3D."""
    d1 = [b - a for a, b in zip(p0, p1, strict=True)]
    d2 = [b - a for a, b in zip(q0, q1, strict=True)]
    r = [a - b for a, b in zip(p0, q0, strict=True)]
    dot = lambda u, v: sum(x * y for x, y in zip(u, v, strict=True))  # noqa: E731
    a, e, f = dot(d1, d1), dot(d2, d2), dot(d2, r)
    if a <= 1e-12:
        s = 0.0
        t = min(1.0, max(0.0, f / e))
    else:
        c, b = dot(d1, r), dot(d1, d2)
        denom = a * e - b * b
        s = min(1.0, max(0.0, (b * f - c * e) / denom)) if denom > 1e-12 else 0.0
        t = (b * s + f) / e
        if t < 0.0:
            t, s = 0.0, min(1.0, max(0.0, -c / a))
        elif t > 1.0:
            t, s = 1.0, min(1.0, max(0.0, (b - c) / a))
    return math.dist([x + s * y for x, y in zip(p0, d1, strict=True)],
                     [x + t * y for x, y in zip(q0, d2, strict=True)])


def centre(b: dict) -> tuple[float, float, float]:
    """The ball's centre from a frame (its z is the lowest point), with the smallest legal ball."""
    return b["x"], b["y"], b["z"] + BALL_RADIUS_MIN_M


def frame_distance(a: dict, b: dict, line: float) -> float:
    """How close the ball's centre came to the goal frame on this line, moving from a to b."""
    return min(segment_gap(centre(a), centre(b), q0, q1) for q0, q1 in frame_axes(line))


def off_woodwork(a: dict, b: dict, line: float) -> bool:
    """Did the ball, moving from a to b, come within touching distance of the goal frame (its
    radius plus the woodwork's half-width, with the largest legal ball, plus rounding)? Then a
    rebound may have changed its path there, which no event records. The engine stops a ball at
    the point where it touches, so a touch shows within the step that reaches it."""
    touching = BALL_RADIUS_M + POST_WIDTH_M / 2 + POINT_PRECISION_M + (BALL_RADIUS_M - BALL_RADIUS_MIN_M)
    return frame_distance(a, b, line) <= touching


def goal_crossing_problem(goal: dict, events: list[dict], by_frame: dict, fps: float,
                          lines: dict[str, float]) -> str | None:
    """L6 (Law 10): the whole ball crossed the goal line the conceding team defends, between the
    posts and under the bar. The goal frame shows the kick-off reset, so the crossing is
    extrapolated from the two frames before it to that goal line, and the crossing point must be
    inside the mouth. Whatever happened in the last frame, the ball can have travelled at most
    one frame at the fastest legal speed, so it must be that close to the mouth itself; if it was
    touched in the last frame (its path changed there), that is all that can be checked."""
    n = goal["frame"]
    b1 = by_frame.get(n - 1, {}).get("ball")
    if b1 is None:
        return "no frame before the goal to check where the ball crossed"
    conceding = "away" if goal["team"] == "home" else "home"
    line = lines.get(conceding, 0.0 if b1["x"] < 52.5 else 105.0)
    inward = 1.0 if line == 0.0 else -1.0  # from that goal line into the field
    dt = 1 / fps
    if (b1["x"] - line) * inward < -BALL_RADIUS_M:
        return f"ball already {abs(b1['x'] - line):.2f} m past the goal line the frame before"
    reach = MAX_BALL_MPS * dt
    if abs(b1["x"] - line) > reach:
        return f"ball {abs(b1['x'] - line):.1f} m from the goal line the frame before"
    # The nearest point where the whole ball is inside the mouth (z is the ball's lowest point).
    inner = GOAL_HALF_WIDTH_M - BALL_RADIUS_MIN_M  # the whole ball inside the posts
    my = min(max(b1["y"], 34.0 - inner), 34.0 + inner)
    mz = min(max(b1["z"], 0.0), CROSSBAR_M - 2 * BALL_RADIUS_MIN_M)
    mouth = math.dist((b1["x"], b1["y"], b1["z"]), (line, my, mz))
    if mouth > reach + 2 * POSITION_PRECISION_M:
        return f"ball {mouth:.1f} m from the goal mouth the frame before"
    beyond = (b1["x"] - line) * inward < 0  # its centre already past the line
    # Past the line but outside a post's axis, or above the bar's: it cannot reach the goal
    # without passing through the woodwork (P17).
    if beyond and abs(b1["y"] - 34.0) > GOAL_HALF_WIDTH_M + POST_WIDTH_M / 2:
        return "ball beside or behind the post the frame before: it cannot enter the goal"
    if beyond and b1["z"] + BALL_RADIUS_MIN_M > CROSSBAR_M + POST_WIDTH_M / 2:
        return "ball on or behind the crossbar the frame before: it cannot enter the goal"
    late = any(e["type"] in GOAL_TOUCHES and n - 1 <= e["frame"] <= n for e in events if e is not goal)
    b0 = by_frame.get(n - 2, {}).get("ball")
    if late or b0 is None or off_woodwork(b0, b1, line):  # its path changed: distances only
        return None
    vx, vy, vz = b1["x"] - b0["x"], b1["y"] - b0["y"], b1["z"] - b0["z"]  # metres per frame
    if vx * inward >= 0:
        return "ball not moving toward the goal line the frame before"
    # Law 10: a goal when the whole ball is over the line, its centre a radius beyond it (a ball
    # rolling along the line may have its centre past the line well before that). The goal frame
    # is the first after that moment, so it comes within one frame of the frame before, allowing
    # for the rounding of the two positions. (The ball cannot be wholly over already: checked above.)
    over = line - inward * BALL_RADIUS_MIN_M
    t = (over - b1["x"]) / vx  # frames until the whole ball is over
    # The rounding of b1 twice and b0 once (the velocity is their difference).
    if t > 1 + 3 * POSITION_PRECISION_M / abs(vx):
        return f"whole ball still {abs(over - b1['x']):.2f} m short of over the line the frame before"
    speed = math.sqrt(vx * vx + vy * vy + vz * vz) / dt
    # Error of a straight-line extrapolation over t frames from a velocity measured half a frame
    # earlier: the largest acceleration over (t + 0.5) frames (drag across the goal; drag and
    # gravity in height), plus the rounding of the two positions.
    drag = DRAG_K_MAX * speed * speed
    rounding = 3 * POSITION_PRECISION_M * (1 + t)
    y = b1["y"] + vy * t
    z = max(0.0, b1["z"] + vz * t - 0.5 * GRAVITY * (t * dt) ** 2)
    outside = abs(y - 34.0) - inner
    if outside > drag * ((t + 0.5) * dt) ** 2 + rounding:
        return f"the whole ball was not inside the posts: {outside:.2f} m of it outside the inner edge"
    above = z + 2 * BALL_RADIUS_MIN_M - CROSSBAR_M
    if above > (drag + GRAVITY) * ((t + 0.5) * dt) ** 2 + rounding:
        return f"the whole ball was not under the bar: {above:.2f} m of it above"
    return None


Touch = tuple[int, int, str, dict | None]  # frame, order within the frame, player, the touch event


def last_touches(goal: dict, events: list[dict], frames: list[dict]) -> list[Touch]:
    """Every touch of the ball since the last kick-off, before the goal, in order: every touch
    event, and each frame where a player has the ball. A frame's possessor is the state at the
    end of that step, so it sorts after the frame's events. The goal frame itself is left out:
    it already shows the kick-off reset (the next kick-off's taker on the centre spot)."""
    k_goal = next(k for k, e in enumerate(events) if e is goal)
    k_start = max((k for k, e in enumerate(events[:k_goal]) if e["type"] == "kickoff"), default=-1)
    start = events[k_start]["frame"] if k_start >= 0 else -1
    end_of_step = len(events) + 1
    touches = [(f["frame"], end_of_step, f["possessor"], None) for f in frames
               if start <= f["frame"] < goal["frame"] and f.get("possessor")]
    for k in range(k_start + 1, k_goal):
        e = events[k]
        if e["type"] in GOAL_TOUCHES and e.get("player"):
            touches.append((e["frame"], k, e["player"], e))
    return sorted(touches, key=lambda t: (t[0], t[1]))


def goal_credit_problem(goal: dict, events: list[dict], frames: list[dict], team_of: dict) -> str | None:
    """C8: who a goal is credited to (Law 10 counts the goal; the scoring convention credits the
    last attacker to touch the ball). A named scorer either touched the ball last (and if that
    touch was a shot, it is recorded as the goal), or struck a shot recorded as the goal that only
    opponents deflected after it (a block or a parry on its way in: no one controlled it). A goal
    with no scorer is an own goal: an opponent of the scoring team touched it last, and no shot
    is recorded as the goal (the shot's record and the goal's must agree). Only touches
    since the last kick-off count, so a shot cannot score twice."""
    touches = last_touches(goal, events, frames)
    if not touches:
        return "goal with no touch of the ball since the kick-off"
    _, _, last, last_event = touches[-1]
    scorer, team = goal.get("player"), goal["team"]
    if scorer is None:
        if team_of.get(last) == team:
            return f"own goal, but {last} of the scoring team touched it last"
        scored = next((ev for _, _, _, ev in touches if ev and ev["type"] == "shot"
                       and ev["outcome"] == "goal"), None)
        if scored:
            return f"own goal, but {scored['player']}'s shot is recorded as the goal"
        return None
    if team_of.get(scorer) != team:
        return f"goal credited to {scorer}, who does not play for {team}"
    if last == scorer:
        if last_event and last_event["type"] == "shot" and last_event["outcome"] != "goal":
            return f"goal by {scorer}, whose shot is recorded as {last_event['outcome']}"
        return None
    k = next((n for n in range(len(touches) - 1, -1, -1)
              if touches[n][3] and touches[n][3]["type"] == "shot" and touches[n][2] == scorer), None)
    if k is None or touches[k][3]["outcome"] != "goal":
        return f"goal by {scorer}, who neither touched it last nor scored with a shot"
    for _, _, pid, ev in touches[k + 1:]:
        if team_of.get(pid) == team:
            return f"goal by {scorer}, but team-mate {pid} touched it after his shot"
        if ev is None or ev["type"] != "deflection":
            return f"goal by {scorer}, but {pid} controlled it after his shot"
    return None


def check_woodwork(frames: list[dict], fps: float, problems: Problems) -> None:
    """P17 (Law 1): the ball never passes through the goal frame (posts, crossbar and the
    corners between them; frame_axes). Between two frames the ball is taken to move in a straight
    line; it is reported if its centre comes closer to the frame's axes than the smallest legal
    ball's radius plus the woodwork's half-width, less every error: the rounding, how far a
    ball's curve can stray from a straight line in one frame at the fastest legal speed (drag and
    gravity), and the uncertainty in its centre height from the ball's size. Frames where the
    ball jumps (a new ball, the kick-off reset) are skipped."""
    dt = 1 / fps
    reach = MAX_BALL_MPS * dt
    curve = (GRAVITY + DRAG_K_MAX * MAX_BALL_MPS ** 2) * dt * dt / 8
    limit = (BALL_RADIUS_MIN_M + POST_WIDTH_M / 2 - POINT_PRECISION_M - curve
             - (BALL_RADIUS_M - BALL_RADIUS_MIN_M))
    for f0, f1 in zip(frames, frames[1:], strict=False):
        a, b = f0["ball"], f1["ball"]
        if math.dist((a["x"], a["y"], a["z"]), (b["x"], b["y"], b["z"])) > reach:
            continue
        for line in (0.0, 105.0):
            if min(abs(a["x"] - line), abs(b["x"] - line)) > BALL_RADIUS_M + POST_WIDTH_M + reach:
                continue
            gap = frame_distance(a, b, line)
            if gap < limit:
                problems["P17 woodwork"].append(f"frame {f1['frame']}: ball through the goal frame at "
                                                f"x = {line:.0f} (centre {gap:.3f} m from its axis)")


def check_corners(events: list[dict], frames: list[dict], roster: list[dict], problems: Problems) -> None:
    """L9: after the ball goes out over a goal line off a defender, the attacking team takes a
    corner from the corner area on that side, and every opponent stands at least 9.15 m from
    the arc from the set-piece event (the corner ready to be taken: placed, the taker starting
    his run-up) until the frame before it is kicked.

    Which team defends a goal line is read from where its keeper stands over the clip. An exit is over a goal
    line when the out-of-play point is on that line and strictly between the touchlines; at the
    corner point itself the line cannot be told, so it is skipped."""
    by_frame = {f["frame"]: f for f in frames}
    lines = defended_lines(frames, {p["id"] for p in roster if p.get("role") == "GK"})
    for i, out in enumerate(events):
        if out["type"] != "out_of_play" or out["x"] not in (0.0, 105.0) or not 0.0 < out["y"] < 68.0:
            continue
        defending = next((team for team, line in lines.items() if line == out["x"]), None)
        if defending is None:
            problems["L9 corner"].append(f"{out['id']}: no roster keeper defends that line to check it")
            continue
        if out["team"] != defending:
            continue  # off an attacker: a goal kick (L8)
        restart = next((e for e in events[i + 1:] if e["type"] in ("set_piece", "kickoff")), None)
        if restart is None:
            continue  # the clip ends before the corner is taken
        if restart["type"] != "set_piece" or restart["team"] == defending:
            problems["L9 corner"].append(f"{out['id']}: no corner for the attacking team")
            continue
        g = by_frame.get(restart["frame"])
        if g is None:
            continue
        b = g["ball"]
        # Law 17: the corner area nearest where it crossed; exactly between the two (within the
        # precision of the positions), either is.
        flags = [(out["x"], 0.0), (out["x"], 68.0)]
        nearest = min(abs(out["y"] - fy) for _, fy in flags)
        allowed = [fl for fl in flags if abs(out["y"] - fl[1]) <= nearest + POINT_PRECISION_M]
        flag = min(allowed, key=lambda fl: math.hypot(b["x"] - fl[0], b["y"] - fl[1]))
        slack = BALL_RADIUS_M + POINT_PRECISION_M
        in_arc = math.hypot(b["x"] - flag[0], b["y"] - flag[1]) <= CORNER_ARC_M + slack
        in_field = -slack <= b["x"] <= 105.0 + slack and -slack <= b["y"] <= 68.0 + slack
        if not (in_arc and in_field):
            problems["L9 corner"].append(f"{restart['id']}: ball not placed in the corner area")
        later = events[events.index(restart) + 1:]
        strike = next((n for n in later if n["type"] in ("pass", "shot")), None)
        until = strike["frame"] if strike else restart["frame"] + 1  # positions before the kick
        moved = False
        for n in range(restart["frame"], until):
            h = by_frame.get(n)
            if h is None:
                continue
            hb = h["ball"]
            shift = math.dist((hb["x"], hb["y"], hb["z"]), (b["x"], b["y"], b["z"]))
            if not moved and shift > STILL_PRECISION_M:
                problems["L9 corner"].append(f"{restart['id']}: ball moved before the kick (frame {n})")
                moved = True
            near = [p for p in h["players"] if p["team"] == defending and
                    math.hypot(p["x"] - flag[0], p["y"] - flag[1]) - CORNER_ARC_M
                    < CORNER_DISTANCE_M - POINT_PRECISION_M]
            if near:
                problems["L9 corner"].append(f"{restart['id']}: {near[0]['id']} inside 9.15 m at frame {n}")
                break


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
    check_woodwork(frames, fps, problems)
    check_events(events, frames, fps, meta, problems)
    check_corners(events, frames, meta.get("roster", []), problems)
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
