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
# C8: the farthest a ball at rest can appear to move between two frames from rounding alone: up to
# 2 * POSITION_PRECISION_M on each of three axes.
ROUNDING_STEP_M = 2 * math.sqrt(3) * POSITION_PRECISION_M

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
# C2: a broadcast cuts away from a dead ball only between a stoppage and its restart (Laws 9, 10, 11,
# 12: the ball is out of play from these until the restart).
CUT_FROM = {"out_of_play", "offside", "foul", "goal"}
TOUCHES = {"pass", "shot", "deflection", "interception", "tackle", "possession_change"}  # P5
# P14: a touch by someone other than the carrier must be physically possible: the player within
# reach of the ball, which was not moving away from him. Reach is a foot (1 m) or a diving
# keeper in his box (1.48 m: P11, his centre of mass to his stretched fingertips), plus one frame of
# the ball's and the player's motion.
CONTACTS = {"deflection", "interception"}
FOOT_REACH_M, KEEPER_REACH_M, FRAME_SLACK_M = 1.0, 1.48, 0.6
# P5: the goal frame (Law 1: posts 7.32 m apart, bar 2.44 m high) is a contact too; a ball
# within this distance of it may rebound without an event.
WOODWORK_NEAR_M = 0.6
# P5: so is a goal's net, as the renderer draws it (web/render/render.js, buildNet; Law 1 allows
# nets without shaping them): its back 2 m behind the goal line and 2 m high, its sides, and its
# roof sloping down to the back from the crossbar. A ball inside the goal touching it (lesson 184):
# its centre a radius from the back or a side (Law 2: 0.11 m), or its top (its lowest point z plus
# its diameter) at the roof.
# measurement precision (lesson 10): each of two written positions is off by up to
# POSITION_PRECISION_M, so a contact is within two of those roundings.
NET_DEPTH_M, NET_BACK_M, BALL_RADIUS_M = 2.0, 2.0, 0.11
NET_TOUCH_SLACK_M = 2 * POSITION_PRECISION_M
# P18, design: a fouled player is on his feet at least this long before the restart is taken.
# The engine aims at 1.5 s (FALL_UP_BEFORE_S). This floor is the requirement.
FOUL_UP_BEFORE_S = 1.0
APPROACH_TOLERANCE_M = 0.04  # P14: per frame; a ball at 1 m/s relative to him can still be met
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


def loose_from_the_cut(frames: list[dict], upto: int) -> bool:
    """In a window that opens after the kickoff, nobody held the ball from its first frame until frame
    `upto`, so play that began before the cut (a pass in the air, a dead ball) may still be running.
    A window is never excused a judgement just because the event that settles it is missing."""
    return frames[0]["frame"] > 0 and not any(f.get("possessor") for f in frames if f["frame"] < upto)


def in_flight_from_the_cut(frames: list[dict], upto: int) -> bool:
    """Loose from the cut (above) and moving every frame up to frame `upto`: a pass or shot struck
    before the cut is still travelling. Moving is farther than rounding alone can move it, so a
    ball at rest is never taken for one in flight: each of the two positions is rounded by up to
    POSITION_PRECISION_M on each of three axes, so a ball at rest can appear to move by up to
    2 * POSITION_PRECISION_M per axis, sqrt(3) times that in space."""
    seen = [f for f in frames if f["frame"] <= upto]
    if not all(consecutive(a, b) for a, b in zip(seen, seen[1:], strict=False)):
        return False  # across a broadcast cut (C2) the ball's flight is not shown
    pos = [(f["ball"]["x"], f["ball"]["y"], f["ball"]["z"]) for f in seen]
    return loose_from_the_cut(frames, upto) and all(
        math.dist(a, b) > ROUNDING_STEP_M for a, b in zip(pos, pos[1:], strict=False))


def consecutive(a: dict, b: dict) -> bool:
    """Two frames of a clip that follow each other in the match, not two sides of a cut."""
    return b["frame"] == a["frame"] + 1


def check_frames(events: list[dict], frames: list[dict], fps: float, problems: Problems,
                 cut: bool = False, cuts: list[dict] | None = None) -> None:
    """C2 frame order: consecutive, except where the broadcast cut (meta.json `cuts`), and a cut
    only through a dead ball; C3 the same players throughout, except legal substitutions."""
    recorded = {(c.get("first_frame"), c.get("last_frame")) for c in cuts or ()}
    made = set()
    for i, (prev, f) in enumerate(zip(frames, frames[1:], strict=False), start=1):
        if consecutive(prev, f):
            continue
        gap = (prev["frame"] + 1, f["frame"] - 1)
        if f["frame"] > prev["frame"] + 1 and gap in recorded:
            made.add(gap)
            check_cut(gap, events, problems)
        else:
            problems["C2 frame order"].append(
                f"frame {f['frame']} at position {i}, after frame {prev['frame']}")
    for gap in sorted(recorded - made, key=str):
        problems["C2 frame order"].append(f"meta.json cut {gap} is not a gap between two frames")
    for f in frames:
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
        # In a window (cut) that shows the ball loose since its first frame, the stoppage may be before
        # it, if play does not go on without a restart (Law 3: substitutions only at a stoppage).
        after = [e for e in events if e["frame"] > sub["frame"] and e["type"] in ON_BALL]
        before_the_cut = cut and not earlier and loose_from_the_cut(frames, sub["frame"]) \
            and (not after or after[0]["type"] in RESTARTS)
        if not before_the_cut and (not earlier or earlier[-1]["type"] not in STOPPAGES):
            problems["C3 roster"].append(f"{sub['id']}: substitution while the ball is in play")
        made[sub["team"]] += 1
        if made[sub["team"]] > MAX_SUBSTITUTIONS:
            problems["C3 roster"].append(f"{sub['id']}: {sub['team']} over {MAX_SUBSTITUTIONS} substitutions")


def check_cut(gap: tuple[int, int], events: list[dict], problems: Problems) -> None:
    """C2: the broadcast cut away only from a dead ball, and the clip shows it dead at both ends: a
    stoppage before the cut and the restart after it, both events of the clip, and between the two
    no touch of the ball in play (TOUCHES) and no other restart. Nothing that happened is cut: an
    event inside it would be on no frame of the clip (C5). A clip that opens or ends inside a dead
    ball shows that ball dead at one end only, so it is not cut there."""
    first, last = gap
    stops = [e for e in events if e["frame"] < first and e["type"] in CUT_FROM]
    restarts = [e for e in events if e["frame"] > last and e["type"] in RESTARTS]
    if not stops or not restarts:
        problems["C2 frame order"].append(f"cut {gap}: no stoppage before it or no restart after it")
        return
    stop, restart = stops[-1]["frame"], restarts[0]["frame"]
    live = [e for e in events if stop < e["frame"] < restart and (e["type"] in TOUCHES | RESTARTS)]
    inside = [e for e in events if first <= e["frame"] <= last]
    if live:
        e = live[0]
        problems["C2 frame order"].append(f"cut {gap}: the ball was in play ({e['id']} {e['type']})")
    if inside:
        problems["C2 frame order"].append(f"cut {gap}: hides {inside[0]['id']} {inside[0]['type']}")


def check_physics(events: list[dict], frames: list[dict], fps: float, roster: list[dict],
                  problems: Problems, cut: bool = False) -> None:
    """P1 to P6: speeds, acceleration, ground, gravity, ball at the possessor's feet."""
    dt = 1 / fps
    # A kickoff restart may move everyone at once: the renderer cuts there.
    restarts = {e["frame"] for e in events if e["type"] == "kickoff"}
    # While the ball is out of play (Law 9) a new ball may be placed for the restart.
    dead: set[int] = set()
    out_at = None
    # A window that opens on a dead ball: its first event is a restart, and nobody held the ball
    # before it, because the ball went out before the cut.
    first_play = next((e for e in events if e["type"] != "pressure"), None)
    if cut and first_play is not None and first_play["type"] in RESTARTS \
            and loose_from_the_cut(frames, first_play["frame"]):
        out_at = frames[0]["frame"]
    for e in events:
        if e["type"] in DEAD_FROM and out_at is None:
            out_at = e["frame"]
        elif e["type"] in RESTARTS and out_at is not None:
            dead.update(range(out_at, e["frame"] + 1))
            out_at = None

    for prev, f in zip(frames, frames[1:], strict=False):
        if f["frame"] in restarts or prev["frame"] in restarts or not consecutive(prev, f):
            continue  # across a cut (C2) the picture jumps; nothing moved that fast
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
        if any(f0["frame"] <= r <= f2["frame"] for r in restarts) or f2["frame"] - f0["frame"] != 2 * w:
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
        if not (consecutive(f0, f1) and consecutive(f1, f2)):
            continue
        if any(near_woodwork(f["ball"]) or near_net(f["ball"]) for f in (f0, f1, f2)):
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


def near_net(b: dict) -> bool:
    """P5: touching a goal's net, where the net stops the ball: inside the goal against its back, a
    side or its roof, or outside it against a side, the back or lying on the roof."""
    for line, out in ((0.0, -1.0), (105.0, 1.0)):
        depth, off = (b["x"] - line) * out, abs(b["y"] - 34)
        roof = 2.44 + (NET_BACK_M - 2.44) * min(depth, NET_DEPTH_M) / NET_DEPTH_M
        below = roof - (b["z"] + 2 * BALL_RADIUS_M)  # from the ball's top up to the roof
        reach = BALL_RADIUS_M + NET_TOUCH_SLACK_M
        if 0 < depth <= NET_DEPTH_M and off <= 3.66 and below >= -NET_TOUCH_SLACK_M:  # inside this goal
            if NET_DEPTH_M - depth <= reach or 3.66 - off <= reach or below <= NET_TOUCH_SLACK_M:
                return True
            continue
        # Outside it (lesson 200): against a side or the back from beside or behind, below the net's
        # top there, or lying on the roof (the ball's lowest point on it).
        top = roof - b["z"]  # from the ball's lowest point up to the net's top edge above it
        beside = 0 < depth <= NET_DEPTH_M and 0 <= off - 3.66 <= reach and top > -NET_TOUCH_SLACK_M
        behind = off <= 3.66 + reach and 0 <= depth - NET_DEPTH_M <= reach and top > -NET_TOUCH_SLACK_M
        on_roof = 0 < depth <= NET_DEPTH_M and off <= 3.66 and abs(top) <= NET_TOUCH_SLACK_M
        if beside or behind or on_roof:
            return True
    return False


def check_contacts(events: list[dict], frames: list[dict], keepers: set[str], problems: Problems) -> None:
    """P14: a deflection or interception names a player who could have touched the ball."""
    by_frame = {f["frame"]: f for f in frames}
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


def check_foul_fall(events: list[dict], frames: list[dict], problems: Problems) -> None:
    """P18: while a fouled player is down, fall is degrees over his feet (above 0 and at most 90,
    *design*), fall_dir is the way his head goes, and action is down. He is upright for at least
    FOUL_UP_BEFORE_S before the restart. A frame exactly on that instant may still be down
    (*design*, one frame). A foul with no receiver, or with no set piece or kick-off after it,
    is not held to that window (*design*: the clip does not show the restart)."""
    restarts = [e for e in events if e.get("type") in ("set_piece", "kickoff")]
    for f in frames:
        for p in f.get("players", []):
            fall, direction = p.get("fall"), p.get("fall_dir")
            if fall is None and direction is None:
                continue
            if type(fall) not in (int, float) or not 0 < fall <= 90:  # *design*: above 0, at most flat
                problems["P18 foul fall"].append(
                    f"frame {f.get('frame')}: {p.get('id')} fall {fall} is not degrees over his feet")
                continue
            if p.get("action") != "down":
                problems["P18 foul fall"].append(
                    f"frame {f.get('frame')}: {p.get('id')} is at {fall}° with action {p.get('action')}")
            if type(direction) not in (int, float):
                problems["P18 foul fall"].append(
                    f"frame {f.get('frame')}: {p.get('id')} is down with no fall_dir")
    for foul in events:
        if foul.get("type") != "foul" or not foul.get("receiver"):
            continue
        nxt = next((e for e in restarts if e.get("t", 0) >= foul.get("t", 0)), None)
        if nxt is None:
            continue
        who = foul["receiver"]
        for f in frames:
            if not foul.get("t", 0) <= f.get("t", 0) <= nxt.get("t", 0):
                continue
            if f["t"] <= nxt["t"] - FOUL_UP_BEFORE_S:  # *design*: the frame on the floor may be down
                continue
            row = next((p for p in f.get("players", []) if p.get("id") == who), None)
            if row and row.get("fall"):
                problems["P18 foul fall"].append(
                    f"frame {f.get('frame')}: {who} is still down "
                    f"{nxt['t'] - f['t']:.2f} s before the restart")


def check_events(events: list[dict], frames: list[dict], fps: float, meta: dict, problems: Problems,
                 cut: bool = False) -> None:
    """C4 to C9: events agree with frames, come in an order that makes sense, and add up.

    In a window cut from a longer match (cut), what happened beyond the cut is not in the clip, so a
    judgement that needs it is not made, and only when the frames show it: a pass nobody has held
    since it was played, still heading for its end point at the last frame with nothing after it,
    and an interception or goal with the ball loose and moving from the first frame to it. Every
    judgement whose evidence lies inside the clip is made exactly as for a whole match."""
    by_frame = {f["frame"]: f for f in frames}
    first, last = frames[0]["frame"], frames[-1]["frame"]
    team_of = {p["id"]: p["team"] for f in frames for p in f["players"]}

    for e in events:
        for role in ("player", "receiver", "intended", "interceptor", "deflected_by"):
            pid = e.get(role)
            if pid is not None and pid not in team_of:
                problems["C4 event players"].append(f"{e['id']}: {role} {pid} is not in the frames")
        if e["type"] == "pass":  # who got a pass, who it was for, who won it, who touched it: own fields
            for role, same in (("receiver", True), ("intended", True), ("interceptor", False),
                               ("deflected_by", False)):
                pid = e.get(role)
                if pid in team_of and (team_of[pid] == e["team"]) != same:
                    side = "the passer's team" if same else "the other team"
                    problems["C4 event players"].append(f"{e['id']}: pass {role} {pid} is not on {side}")
            if e.get("receiver") and e.get("outcome") != "success":
                problems["C4 event players"].append(f"{e['id']}: a pass with a receiver did not succeed")
            if e.get("interceptor") and e.get("outcome") != "fail":
                problems["C4 event players"].append(f"{e['id']}: an intercepted pass did not fail")
            if e.get("deflected_by") and e.get("outcome") != "fail":
                problems["C4 event players"].append(f"{e['id']}: a deflected pass did not fail")
            if e.get("interceptor") and e.get("deflected_by"):
                problems["C4 event players"].append(f"{e['id']}: a pass both won and only touched")
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
            # The clip ends before anything else happens to it: nobody has held the ball since it was
            # played, and its last frame's motion, carried on in a straight line, passes within NEAR_M
            # of the end point ahead of it. A pass struck on the last frame has no flight in the clip
            # at all (its last motion is the touch before the kick), so there is nothing to judge.
            final = by_frame[last]["ball"]
            prior = by_frame.get(last - 1, by_frame[last])["ball"]
            vx, vy = final["x"] - prior["x"], final["y"] - prior["y"]
            wx, wy = e["end_x"] - final["x"], e["end_y"] - final["y"]
            ahead = (wx * vx + wy * vy) / ((vx * vx + vy * vy) or math.inf)
            closing = ahead > 0 and math.hypot(wx - ahead * vx, wy - ahead * vy) <= NEAR_M
            held = any(by_frame[n].get("possessor") for n in range(e["frame"] + 1, last + 1) if n in by_frame)
            struck_at_the_cut = e["frame"] == last
            still_going = cut and not later and (struck_at_the_cut or (not held and closing))
            if not still_going and \
                    not any(math.hypot(b["x"] - e["end_x"], b["y"] - e["end_y"]) <= NEAR_M for b in balls):
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
    for e in passes:
        if e.get("receiver") and e["receiver"] == e["player"]:
            problems["C8 event order"].append(f"{e['id']}: a pass received by its own passer")
    shots = [e for e in events if e["type"] == "shot"]
    for e in events:
        if e["type"] == "interception":
            before = [p for p in passes if p["frame"] <= e["frame"]]
            if not before and cut and in_flight_from_the_cut(frames, e["frame"]):
                continue
            if not before or before[-1]["outcome"] != "fail" or before[-1].get("interceptor") != e["player"]:
                problems["C8 event order"].append(f"{e['id']}: {e['player']} intercepted no failed pass")
        if e["type"] == "goal" and e.get("player"):  # an own goal (no scorer) needs no shot
            before = [s for s in shots if s["frame"] <= e["frame"]]
            if not before and cut and in_flight_from_the_cut(frames, e["frame"]):
                continue
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
    # A window cut from a longer match names the match frames it covers, and must cover exactly them.
    window = meta.get("window")
    if window is not None:
        span = (frames[0]["frame"], frames[-1]["frame"]) if frames else None
        if not isinstance(window, dict) or span != (window.get("first_frame"), window.get("last_frame")):
            problems["C1 files"].append(f"meta.json window {window} does not match the frames {span}")
            return dict(problems)
    cut = window is not None
    cuts = meta.get("cuts", [])
    frame_number = lambda v: type(v) is int  # noqa: E731  (80.0 is not frame 80, nor True frame 1)
    if not isinstance(cuts, list) or not all(
            isinstance(c, dict) and frame_number(c.get("first_frame")) and frame_number(c.get("last_frame"))
            for c in cuts):
        problems["C1 files"].append("meta.json cuts must be a list of {first_frame, last_frame} numbers")
        return dict(problems)
    check_frames(events, frames, fps, problems, cut, cuts)
    if any(k.startswith("C2") for k in problems):
        return dict(problems)
    check_physics(events, frames, fps, meta.get("roster", []), problems, cut)
    check_events(events, frames, fps, meta, problems, cut)
    check_foul_fall(events, frames, problems)
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
