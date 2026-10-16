"""Fake detections: true events copied as vision output, then damaged in known ways, so the score
the harness must give is known before it runs (LESSONS 8: a check must be able to fail).

Every damage is planted only where it cannot be confused with a neighbouring event: a damaged
event has no other true event of its type and team within ISOLATION_S, and a moved or invented
event lands more than WINDOW_S from every true event of its type and team. Otherwise a shifted
pass could be matched to the next pass along, and the predicted score would be wrong while the
harness was right. When damage cannot be planted cleanly, it is refused, never forced.
"""

from __future__ import annotations

import random
from collections import Counter

from ninety.eval.event_score import EPS, WINDOW_S

DAMAGES = ("near_shift", "far_shift", "delete", "add", "duplicate", "flip_team", "relabel")

# A near shift moves an event by at most NEAR_MAX_S, still inside the window. A victim needs every
# other true event of its type and team more than NEAR_MAX_S + WINDOW_S away, so its shifted copy
# is within the window of its own event only; 2 x WINDOW_S covers that.
NEAR_MIN_S, NEAR_MAX_S = 0.1, 0.9
ISOLATION_S = 2 * WINDOW_S
DUPLICATE_GAP_S = 0.1
FPS = 25


def as_detection(event: dict, id: str, **changes) -> dict:
    out = {**event, **changes, "id": id, "source": "vision", "confidence": 1.0}
    out["t"] = round(out["t"], 2)
    if "frame" in out:
        out["frame"] = round(out["t"] * FPS)
    return out


def clear_of(truth: list[dict], kind: str, team: str, t: float) -> bool:
    """No true event of this type and team within the window of time t."""
    return all(abs(e["t"] - t) > WINDOW_S + EPS for e in truth if (e["type"], e["team"]) == (kind, team))


def isolated(truth: list[dict], event: dict) -> bool:
    return all(abs(e["t"] - event["t"]) > ISOLATION_S + EPS for e in truth
               if (e["type"], e["team"]) == (event["type"], event["team"]) and e["id"] != event["id"])


def free_time(truth: list[dict], kind: str, team: str, rng: random.Random,
              near: float | None = None) -> float:
    end = max(e["t"] for e in truth) + WINDOW_S
    for _ in range(1000):
        if near is None:
            t = rng.uniform(0, end)
        else:
            t = near + rng.choice((-1, 1)) * rng.uniform(2 * WINDOW_S, 5 * WINDOW_S)
        t = round(t, 2)
        if t >= 0 and clear_of(truth, kind, team, t):
            return t
    raise ValueError(f"no free time for a {team} {kind} away from every true one")


def fake_detections(truth: list[dict], seed: int, per_damage: int = 2) -> tuple[list[dict], list[dict]]:
    """Return (detected events, damage log). per_damage of each kind in DAMAGES."""
    rng = random.Random(seed)
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

    detected: list[dict] = []
    for damage in DAMAGES:
        for n in range(per_damage):
            entry = {"damage": damage, "truth_id": None, "type": None, "detected_type": None}
            if damage == "add":
                base = rng.choice(truth)
                t = free_time(truth, base["type"], base["team"], rng)
                d = as_detection(base, f"d-add-{n}", t=t)
                entry.update(type=None, detected_type=d["type"])
                detected.append(d)
            elif damage == "flip_team":
                e = take(damage, lambda e: clear_of(truth, e["type"], other_team[e["team"]], e["t"]))
                detected.append(as_detection(e, "d" + e["id"], team=other_team[e["team"]]))
                entry.update(truth_id=e["id"], type=e["type"], detected_type=e["type"])
            elif damage == "relabel":
                def new_type(e):
                    return "shot" if e["type"] == "pass" else "pass"
                e = take(damage, lambda e: clear_of(truth, new_type(e), e["team"], e["t"]))
                detected.append(as_detection(e, "d" + e["id"], type=new_type(e)))
                entry.update(truth_id=e["id"], type=e["type"], detected_type=new_type(e))
            else:
                e = take(damage)
                entry.update(truth_id=e["id"], type=e["type"])
                if damage == "near_shift":
                    shift = rng.choice((-1, 1)) * rng.uniform(NEAR_MIN_S, NEAR_MAX_S)
                    detected.append(as_detection(e, "d" + e["id"], t=max(0.0, e["t"] + shift)))
                    entry["detected_type"] = e["type"]
                elif damage == "far_shift":
                    t = free_time(truth, e["type"], e["team"], rng, near=e["t"])
                    detected.append(as_detection(e, "d" + e["id"], t=t))
                    entry["detected_type"] = e["type"]
                elif damage == "duplicate":
                    detected.append(as_detection(e, "d" + e["id"]))
                    detected.append(as_detection(e, "d" + e["id"] + "-dup", t=e["t"] + DUPLICATE_GAP_S))
                    entry["detected_type"] = e["type"]
                # delete: no detection at all
            log.append(entry)

    for e in truth:
        if e["id"] not in damaged:
            detected.append(as_detection(e, "d" + e["id"]))
    detected.sort(key=lambda d: d["t"])
    return detected, log


def expected_counts(truth: list[dict], log: list[dict]) -> dict[str, tuple[int, int, int]]:
    """What the harness must report, per type, as (tp, fp, fn), worked out from the log alone."""
    tp = Counter(e["type"] for e in truth)
    fp: Counter = Counter()
    fn: Counter = Counter()
    for entry in log:
        damage, kind, detected_kind = entry["damage"], entry["type"], entry["detected_type"]
        if damage in ("far_shift", "flip_team", "relabel"):
            # the true event is missed, and the detection is a false alarm
            tp[kind] -= 1
            fn[kind] += 1
            fp[detected_kind] += 1
        elif damage == "delete":
            tp[kind] -= 1
            fn[kind] += 1
        elif damage in ("add", "duplicate"):
            fp[detected_kind] += 1
        # near_shift: still a match
    kinds = set(tp) | set(fp) | set(fn)
    return {k: (tp[k], fp[k], fn[k]) for k in sorted(kinds)}
