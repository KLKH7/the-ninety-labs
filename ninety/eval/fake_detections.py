"""Fake detections: true events copied as vision output, then damaged in known ways, so the score
the harness must give is known before it runs (LESSONS 8: a check must be able to fail).

Every detection is placed where its reference object really was at the detection's own time, as
a perfect camera would see it; the misplace damages then move the spot by a known distance.

Every damage is planted only where it cannot be confused with a neighbouring event: a damaged
event has no other true event of its type and team within ISOLATION_S, and a moved or invented
event lands more than WINDOW_S from every true event of its type and team. Otherwise a shifted
pass could be matched to the next pass along, and the predicted score would be wrong while the
harness was right. When damage cannot be planted cleanly, it is refused, never forced.
"""

from __future__ import annotations

import math
import random
from collections import Counter

from ninety.eval.event_score import (
    EPS,
    FOULED_PLACED,
    LENIENT_M,
    NOT_PLACED,
    PLAYER_PLACED,
    STRICT_M,
    WINDOW_S,
    reference_point,
)
from ninety.sim import fmath
from ninety.sim.engine import FPS

# Misplace distances, one inside each band: within strict, between strict and lenient, beyond both.
MISPLACE_M = {"misplace_small": 0.5, "misplace_medium": 1.5, "misplace_large": 5.0}
assert (MISPLACE_M["misplace_small"] < STRICT_M < MISPLACE_M["misplace_medium"] < LENIENT_M
        < MISPLACE_M["misplace_large"])

DAMAGES = ("near_shift", "far_shift", "delete", "add", "duplicate", "flip_team", "relabel", *MISPLACE_M)

# A near shift moves an event by at most NEAR_MAX_S, still inside the window. A victim needs every
# other true event of its type and team more than NEAR_MAX_S + WINDOW_S away, so its shifted copy
# is within the window of its own event only; 2 x WINDOW_S covers that.
NEAR_MIN_S, NEAR_MAX_S = 0.1, 0.9
ISOLATION_S = 2 * WINDOW_S
DUPLICATE_GAP_S = 0.1
PITCH_X, PITCH_Y = 105.0, 68.0


def as_detection(event: dict, id: str, frames: list[dict], **changes) -> dict:
    """The event as a perfect camera would report it: at its (possibly changed) time, team and type,
    and at the spot where its reference object was at that time."""
    out = {**event, **changes, "id": id, "source": "vision", "confidence": 1.0}
    out["t"] = round(out["t"], 2)
    if "frame" in out:
        out["frame"] = round(out["t"] * FPS)
    point = reference_point(out["type"], out["team"], out["t"], frames, (event["x"], event["y"]))
    if point is not None:
        out["x"], out["y"] = point[0], point[1]
    return out


def clear_of(truth: list[dict], kind: str, team: str, t: float) -> bool:
    """No true event of this type and team within the window of time t."""
    return all(abs(e["t"] - t) > WINDOW_S + EPS for e in truth if (e["type"], e["team"]) == (kind, team))


def isolated(truth: list[dict], event: dict) -> bool:
    return all(abs(e["t"] - event["t"]) > ISOLATION_S + EPS for e in truth
               if (e["type"], e["team"]) == (event["type"], event["team"]) and e["id"] != event["id"])


def free_time(truth: list[dict], kind: str, team: str, end: float, rng: random.Random,
              near: float | None = None) -> float:
    for _ in range(1000):
        if near is None:
            t = rng.uniform(0, end)
        else:
            t = near + rng.choice((-1, 1)) * rng.uniform(2 * WINDOW_S, 5 * WINDOW_S)
        t = round(t, 2)
        if 0 <= t <= end and clear_of(truth, kind, team, t):
            return t
    raise ValueError(f"no free time for a {team} {kind} away from every true one")


def room_near(truth: list[dict], kind: str, team: str, end: float, near: float) -> bool:
    """Is there a time free_time(..., near=near) could return? Checked on the 0.01 s grid it rounds
    to, without drawing, so choosing events by it leaves the random draws as they were."""
    for k in range(round(200 * WINDOW_S), round(500 * WINDOW_S) + 1):
        for t in (round(near - k / 100, 2), round(near + k / 100, 2)):
            if 0 <= t <= end and clear_of(truth, kind, team, t):
                return True
    return False


def misplaced(d: dict, distance: float, rng: random.Random) -> dict:
    """Move a detection's spot exactly `distance` from where it is, staying on the pitch."""
    for _ in range(100):
        a = rng.uniform(0, 2 * math.pi)
        x, y = d["x"] + distance * fmath.cos(a), d["y"] + distance * fmath.sin(a)
        if 0 <= x <= PITCH_X and 0 <= y <= PITCH_Y:
            return {**d, "x": x, "y": y}
    raise ValueError(f"cannot move {d['id']} {distance} m and stay on the pitch")


def fake_detections(truth: list[dict], frames: list[dict], seed: int,
                    per_damage: int = 2) -> tuple[list[dict], list[dict]]:
    """Return (detected events, damage log). per_damage of each kind in DAMAGES."""
    rng = fmath.Random(seed)  # the same draws as random.Random; refuses anything platform-dependent
    end = frames[-1]["t"]
    other_team = {"home": "away", "away": "home"}
    victims = [e for e in truth if isolated(truth, e)]
    rng.shuffle(victims)
    damaged: dict[str, str] = {}  # truth id -> damage
    log: list[dict] = []

    def take(damage: str, ok=lambda e: True) -> dict:
        for e in victims:
            if e["id"] not in damaged and ok(e):
                damaged[e["id"]] = damage
                return e
        raise ValueError(f"not enough isolated events to plant {damage} cleanly")

    def new_type(e):
        return "shot" if e["type"] == "pass" else "pass"

    def ball_placed(e):
        # A moved spot near a player-placed event could land by another player and pass by luck.
        return e["type"] not in PLAYER_PLACED | FOULED_PLACED | NOT_PLACED

    detected: list[dict] = []
    for damage in DAMAGES:
        for n in range(per_damage):
            entry = {"damage": damage, "truth_id": None, "type": None, "detected_type": None}
            if damage == "add":
                base = rng.choice(truth)
                t = free_time(truth, base["type"], base["team"], end, rng)
                d = as_detection(base, f"d-add-{n}", frames, t=t)
                entry.update(detected_type=d["type"])
                detected.append(d)
            elif damage == "flip_team":
                e = take(damage, lambda e: clear_of(truth, e["type"], other_team[e["team"]], e["t"]))
                detected.append(as_detection(e, "d" + e["id"], frames, team=other_team[e["team"]]))
                entry.update(truth_id=e["id"], type=e["type"], detected_type=e["type"])
            elif damage == "relabel":
                e = take(damage, lambda e: clear_of(truth, new_type(e), e["team"], e["t"]))
                detected.append(as_detection(e, "d" + e["id"], frames, type=new_type(e)))
                entry.update(truth_id=e["id"], type=e["type"], detected_type=new_type(e))
            elif damage in MISPLACE_M:
                e = take(damage, ball_placed)
                detected.append(misplaced(as_detection(e, "d" + e["id"], frames), MISPLACE_M[damage], rng))
                entry.update(truth_id=e["id"], type=e["type"], detected_type=e["type"])
            else:
                # A far shift needs a free time near the event (in a crowded spell there may be none):
                # chosen so by construction, not left to how busy the match happens to be.
                e = take(damage, (lambda e: room_near(truth, e["type"], e["team"], end, e["t"]))
                         if damage == "far_shift" else (lambda e: True))
                entry.update(truth_id=e["id"], type=e["type"], detected_type=e["type"])
                if damage == "near_shift":
                    shift = rng.choice((-1, 1)) * rng.uniform(NEAR_MIN_S, NEAR_MAX_S)
                    t = min(max(0.0, e["t"] + shift), end)
                    detected.append(as_detection(e, "d" + e["id"], frames, t=t))
                elif damage == "far_shift":
                    t = free_time(truth, e["type"], e["team"], end, rng, near=e["t"])
                    detected.append(as_detection(e, "d" + e["id"], frames, t=t))
                elif damage == "duplicate":
                    detected.append(as_detection(e, "d" + e["id"], frames))
                    t = e["t"] + DUPLICATE_GAP_S
                    detected.append(as_detection(e, "d" + e["id"] + "-dup", frames, t=t))
                # delete: no detection at all
            log.append(entry)

    for e in truth:
        if e["id"] not in damaged:
            detected.append(as_detection(e, "d" + e["id"], frames))
    detected.sort(key=lambda d: d["t"])
    return detected, log


def expected_counts(truth: list[dict], log: list[dict]) -> dict[str, dict[str, tuple[int, int, int]]]:
    """What the harness must report, per rule and type, as (tp, fp, fn), from the log alone."""
    out = {}
    for rule in ("time_only", "strict", "lenient"):
        wrong_place = {"time_only": (), "strict": ("misplace_medium", "misplace_large"),
                       "lenient": ("misplace_large",)}[rule]
        tp = Counter(e["type"] for e in truth)
        fp: Counter = Counter()
        fn: Counter = Counter()
        for entry in log:
            damage, kind, detected_kind = entry["damage"], entry["type"], entry["detected_type"]
            if damage in ("far_shift", "flip_team", "relabel") or damage in wrong_place:
                # the true event is missed, and the detection is a false alarm
                tp[kind] -= 1
                fn[kind] += 1
                fp[detected_kind] += 1
            elif damage == "delete":
                tp[kind] -= 1
                fn[kind] += 1
            elif damage in ("add", "duplicate"):
                fp[detected_kind] += 1
            # near_shift, and a misplace within this rule's radius: still a match
        kinds = set(tp) | set(fp) | set(fn)
        out[rule] = {k: (tp[k], fp[k], fn[k]) for k in sorted(kinds)}
    return out
