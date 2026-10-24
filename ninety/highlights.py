"""The highlights reel: which detected goals and saves make it, and the word fans would use for each
(docs/eval/highlights-plan.md, fixed before any of it was measured).

    reel(events, verdict)    the reel's moments in match time, and how many saves were left out

- Every goal is in. A save is in when the ball beat a keeper's dive: its flight time
  T = d / v at most T_DIVE_S, d the distance from the strike to the centre of the goal it attacks
  and v vision's shot speed. That filter is used only once the measurement has passed the plan's
  gates (`verdict`); until then every save is in, `saves_by_pace` lists them fastest first, and the
  reel says the filter is off. Moments play in match time either way.
- Each moment gets one headline label, the first of LABELS that applies, and only when its number
  clears the threshold by more than vision's measured 95th percentile error of that number. Until
  the errors are measured no label is given: the moment is a plain goal or save.

Reads detected events only (the live path): the confident ones the caller passes, never the
answer key. The errors in `verdict` are a summary of how wrong vision was on validation clips
(ninety/eval/shot_flight.py writes them), not truth about this match.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

PITCH_X, CENTRE_Y = 105.0, 34.0
# Law 1: the penalty area is 16.5 m deep and reaches 16.5 m beyond each post (3.66 + 16.5 across
# from the goal's centre line); the goal area 5.5 m, so 3.66 + 5.5.
AREA_DEPTH_M, AREA_HALF_WIDTH_M = 16.5, 20.16
GOAL_AREA_DEPTH_M, GOAL_AREA_HALF_WIDTH_M = 5.5, 9.16
# The plan's sources: T_DIVE_S, Ibrahim et al. 2019 (an elite keeper's fastest dive to a low ball,
# 0.972 s); ROCKET_KMH, the Bundesliga's "fast" shot (Bundesliga Match Facts, 2023); REFLEX_S, the
# slowest footballer's choice reaction (GROUNDING P12); SCREAMER_M, design (the far end of long range).
T_DIVE_S = 0.97
ROCKET_KMH = 100.0
REFLEX_S = 0.41
SCREAMER_M = 25.0
# The moment's clip, from before the strike (the build-up) to after it (design).
BEFORE_S, AFTER_S = 8.0, 3.0
# Headline labels, the first that applies wins (the plan's table, in its order).
LABELS = ("THUNDERBOLT", "SCREAMER", "LONG-RANGE", "ROCKET", "REFLEX SAVE", "TAP-IN")


@dataclass
class Verdict:
    """What the measurement on validation clips decided: whether the save filter is live, and each
    quantity's 95th percentile error (None: not measured, so no label rests on it)."""
    save_filter: bool = False
    margins: dict[str, float | None] = field(default_factory=dict)

    def margin(self, key: str) -> float | None:
        return self.margins.get(key)


def verdict_from_report(report: dict) -> Verdict:
    """The verdict in the scorer's report (docs/eval/shot-flight.json): its save-filter gate and the
    95th percentile errors over all matched shots."""
    errors = report["errors"]["all"]["all"]
    keys = {"v_kmh": "v_kmh", "d_m": "d_m", "x_m": "x_m", "y_m": "y_m", "T_s": "T_vs_d_over_v_s"}
    return Verdict(save_filter=bool(report["save_filter"]["live"]),
                   margins={k: (errors.get(v) or {}).get("p95_abs") for k, v in keys.items()})


def goal_line(x: float) -> float:
    """The goal line a shot from x attacks: the nearer one. A shot is an option only within 40 m
    of the goal's centre (GROUNDING D3), so it is always struck in the half it attacks."""
    return PITCH_X if x > PITCH_X / 2 else 0.0


def distance_m(x: float, y: float) -> float:
    """d: from where the shot was struck to the centre of the goal it attacks (D3, lesson 138)."""
    return math.hypot(goal_line(x) - x, CENTRE_Y - y)


def flight_time_s(d: float, speed_kmh: float | None) -> float | None:
    """T = d / v, with v in metres a second; None without a speed."""
    if speed_kmh is None or speed_kmh <= 0:
        return None
    return d / (speed_kmh / 3.6)


def _depth(x: float) -> float:
    """How far from the goal line it attacks, along the pitch."""
    return abs(goal_line(x) - x)


def outside_area(x: float, y: float, mx: float, my: float) -> bool:
    """Surely outside the penalty area: past its edge by more than the position error."""
    return _depth(x) > AREA_DEPTH_M + mx or abs(y - CENTRE_Y) > AREA_HALF_WIDTH_M + my


def inside_goal_area(x: float, y: float, mx: float, my: float) -> bool:
    return _depth(x) < GOAL_AREA_DEPTH_M - mx and abs(y - CENTRE_Y) < GOAL_AREA_HALF_WIDTH_M - my


def label(kind: str, x: float, y: float, d: float, v: float | None, T: float | None,
          verdict: Verdict) -> tuple[str, str] | None:
    """The headline label and the number that earned it, or None. Each test needs its margin
    measured and the number clear of the threshold by more than it."""
    mv, md, mT = verdict.margin("v_kmh"), verdict.margin("d_m"), verdict.margin("T_s")
    mx, my = verdict.margin("x_m"), verdict.margin("y_m")
    placed = mx is not None and my is not None
    rocket = mv is not None and v is not None and v > ROCKET_KMH + mv
    outside = placed and outside_area(x, y, mx, my)
    far = md is not None and d > SCREAMER_M + md
    near = md is not None and d < SCREAMER_M - md
    speed, metres = f"{v:.0f} km/h" if v is not None else "", f"{d:.0f} m"
    applies = {
        "THUNDERBOLT": kind == "goal" and outside and far and rocket,
        "SCREAMER": kind == "goal" and outside and far,
        "LONG-RANGE": kind == "goal" and outside and near,
        "ROCKET": rocket,
        "REFLEX SAVE": kind == "save" and mT is not None and T is not None and T < REFLEX_S - mT,
        "TAP-IN": kind == "goal" and placed and inside_goal_area(x, y, mx, my),
    }
    because = {"THUNDERBOLT": f"{speed} · {metres}", "SCREAMER": metres, "LONG-RANGE": metres,
               "ROCKET": speed, "REFLEX SAVE": f"{T:.2f} s" if T is not None else "", "TAP-IN": metres}
    for name in LABELS:
        if applies[name]:
            return name, because[name]
    return None


def kind_of(e: dict) -> str | None:
    if e["type"] != "shot":
        return None
    return {"goal": "goal", "on_target": "save"}.get(e.get("outcome"))


def reel(events: list[dict], verdict: Verdict | None = None) -> dict:
    """The reel from confident detected events (the caller applies the fact-checker's gate)."""
    verdict = verdict or Verdict()
    moments, left_out = [], 0
    for e in sorted(events, key=lambda e: (e["t"], e["id"])):
        kind = kind_of(e)
        if kind is None:
            continue
        d = distance_m(e["x"], e["y"])
        v = e.get("ball_speed_kmh")
        T = flight_time_s(d, v)
        if kind == "goal":
            why = "goal"
        elif not verdict.save_filter:
            why = "filter_off"
        elif T is not None and T <= T_DIVE_S:
            why = "beat_the_dive"
        else:
            left_out += 1
            continue
        tag = label(kind, e["x"], e["y"], d, v, T, verdict)
        moments.append({
            "event": e["id"], "t": e["t"], "team": e.get("team"), "player": e.get("player"),
            "kind": kind, "why": why,
            "label": tag[0] if tag else kind.upper(), "label_detail": tag[1] if tag else None,
            "d_m": round(d, 1), "v_kmh": v, "T_s": None if T is None else round(T, 2),
            "clip": [round(max(0.0, e["t"] - BEFORE_S), 2), round(e["t"] + AFTER_S, 2)],
        })
    saves = sorted((m for m in moments if m["kind"] == "save"),
                   key=lambda m: (m["T_s"] is None, m["T_s"] or 0.0, m["t"]))
    return {"save_filter": verdict.save_filter,
            "labels": any(m is not None for m in verdict.margins.values()),
            "moments": moments, "saves_by_pace": [m["event"] for m in saves], "saves_left_out": left_out}
