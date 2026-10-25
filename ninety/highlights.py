"""The highlights reel: which detected goals and saves make it, and the word fans would use for each
(docs/eval/highlights-plan.md, fixed before any of it was measured).

    reel(events, verdict)    the reel's moments in match time, and how many saves were left out
    record(reel, ...)        each moment recorded from the footage: a still at the strike and a
                             clip of its window, for the phone and the viewer to play

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
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from ninety.agents.factcheck import side_known

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
    # True once `origin` has been graded against the answer key on validation clips (plan, Amendment 2,
    # "Graded"). Until then no moment carries one, so no caption or screen can say how an attack began.
    origins: bool = False

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


# How the attack that led to the shot started (the plan's Amendment 2): the restart, or the ball won
# in open play, that began the shooting side's possession. None when its start was not seen. The
# restart kinds are the detector's own (ninety/vision/restarts.py, `restart` on a set_piece).
#
# The restart events, as their author specifies them (Kian on #324):
#   type        "kickoff" (Law 8) or "set_piece"; `restart` on a set piece only: "corner" |
#               "goal_kick" | "throw_in" | "free_kick" | "penalty_kick" (the answer key's has none)
#   team        the side TAKING it: corner and penalty, the side attacking that end; goal kick, the
#               side defending it; free kick, throw-in and kick-off, the side of the player at the ball
#   team_confidence  the taker's side score, null when no player of that side is within reach;
#               name the side only where factcheck.side_known holds
#   t, frame    the kick (the last frame the ball lay still); the answer key's comes 1 to 2.3 s earlier
#   cause       free kicks and penalties, optional and not on the live path yet; not read here
ORIGINS = ("corner", "throw_in", "goal_kick", "free_kick", "penalty_kick", "kick_off", "open_play")
RESTART_KINDS = frozenset({"corner", "throw_in", "goal_kick", "free_kick", "penalty_kick"})
PITCH_Y = 68.0
# A restart taken by the strike itself (a direct free kick, a penalty) can be timed a frame after
# the shot: the broadcast's 25 frames a second (docs/DATA_CONTRACT.md) are its precision.
FRAME_S = 1 / 25


def _is_goal(e: dict) -> bool:
    return e["type"] == "goal" or (e["type"] == "shot" and e.get("outcome") == "goal")


def restart(out: dict, team: str, attacks: float, before: dict | None) -> str | None:
    """The restart after a detected ball out of play, if it is `team`'s (Laws 15 to 17), seen from a
    side attacking the goal line at x = `attacks`. `out` names the side that touched it last. A ball
    over a line by more along y than along x went over a touchline (at a corner flag, the line it is
    further over, as the engine judges it: ninety/sim/decisions.py, restart_cost). A ball out over a
    goal line straight after a goal is that goal: the kick-off is the side's that conceded (Law 8)."""
    x, y = out["x"], out["y"]
    over_x, over_y = max(-x, x - PITCH_X, 0.0), max(-y, y - PITCH_Y, 0.0)
    if over_y >= over_x:  # Law 15: a throw-in to the side that did not touch it last
        return "throw_in" if out["team"] != team else None
    if before is not None and _is_goal(before):
        return "kick_off" if before["team"] != team else None
    crossed = PITCH_X if x > PITCH_X / 2 else 0.0
    if crossed == attacks:  # Law 17: a corner when a defender touched it last
        return "corner" if out["team"] != team else None
    return "goal_kick" if out["team"] != team else None  # Law 16: over its own line by an attacker


def _restart_detected(e: dict) -> bool:
    return e["type"] == "kickoff" or e["type"] == "set_piece"


# Events that change nobody's possession: a press on the carrier, a touch that does not take the ball
# (StatsBomb's possession runs on through both; who has it next says whether it changed).
NO_CHANGE = frozenset({"pressure", "deflection"})
# Events that end a stoppage's dead ball: what restarted play after them is the side's restart.
DEAD = frozenset({"out_of_play", "foul", "offside", "goal", "set_piece", "kickoff", "half_time"})


def origin(shot: dict, events: list[dict], cut=lambda t0, t1: False) -> str | None:
    """How the shooting side's possession began, walking back from the shot through the confident
    detected events (presses and touches that take nobody the ball, NO_CHANGE, are passed over).

    - A restart the detector saw (ninety/vision/restarts.py: a `kickoff`, or a `set_piece` naming
      its `restart`) is that restart when the shooting side took it.
    - A set piece of the side with no kind is read from what stopped play before it: a ball out of
      play (`restart`), or the other side's foul (a penalty inside the area the side attacks, Law 14,
      else a free kick, Law 13) or offside (a free kick, Law 11).
    - Without a restart, a ball out of play is the restart it gives (`restart`), and the other
      side's goal is the kick-off (Law 8).
    - The side's own completed passes and earlier shots keep the possession going. The ball won in
      open play is `open_play`: the other side's failed pass, the side's interception or won
      tackle, or a change of possession to it that no stoppage came just before.

    Anything else, or a broadcast cut (`cut(t0, t1)`: one lies between match times t0 and t1)
    between an event and the shot, means the start was not seen: None. Nothing before a cut is read,
    a ball seen going out included: a condensed match's cut can skip minutes (found on seed 8080's
    answer key, where a throw-in before a cut was taken for a free kick's after it)."""
    team, attacks = shot["team"], goal_line(shot["x"])
    before = [e for e in sorted((e for e in events if e["id"] != shot["id"] and (
        (e["t"], e["id"]) < (shot["t"], shot["id"])
        or (_restart_detected(e) and e["t"] <= shot["t"] + FRAME_S))), key=lambda e: (e["t"], e["id"]))
        if e["type"] not in NO_CHANGE]
    set_piece = False  # the side's set piece of no kind: what stopped play decides it
    for i in range(len(before) - 1, -1, -1):
        e, prev = before[i], before[i - 1] if i else None
        if cut(e["t"], shot["t"]):
            # Nothing is inferred across a cut: in a condensed match it can skip minutes, a foul and
            # possessions with them. A restart after it is the detector's to see (rule 0).
            return None
        if e["type"] == "kickoff":
            return "kick_off" if e["team"] == team else None
        if e["type"] == "set_piece":
            kind = e.get("restart")
            if e["team"] != team or set_piece:
                return None
            if kind is None:
                set_piece = True
                continue
            return kind if kind in RESTART_KINDS else None
        if e["type"] == "out_of_play":
            return restart(e, team, attacks, prev)
        if _is_goal(e):
            return "kick_off" if e["team"] != team else None
        if e["type"] in ("foul", "offside"):
            if not set_piece or e["team"] == team:
                return None  # no free kick of the side's followed it (advantage), or it was the side's
            in_area = abs(attacks - e["x"]) < AREA_DEPTH_M and abs(e["y"] - CENTRE_Y) < AREA_HALF_WIDTH_M
            return "penalty_kick" if e["type"] == "foul" and in_area else "free_kick"
        if set_piece:
            return None  # a set piece with nothing seen that stopped play before it
        kept = e["type"] == "shot" or (e["type"] == "pass" and e.get("outcome") == "success")
        if e["team"] == team and kept:
            continue
        if e["team"] != team and e["type"] == "pass" and e.get("outcome") == "fail":
            return "open_play"
        if e["type"] == "possession_change" and e["team"] == team:
            if prev is not None and prev["type"] in DEAD:
                continue  # the change at a restart: the stoppage before it decides
            return "open_play"
        if e["team"] == team and (e["type"] == "interception"
                                  or (e["type"] == "tackle" and e.get("outcome") == "success")):
            return "open_play"
        return None
    return None


def kind_of(e: dict) -> str | None:
    if e["type"] != "shot":
        return None
    return {"goal": "goal", "on_target": "save"}.get(e.get("outcome"))


def reel(events: list[dict], verdict: Verdict | None = None, cut=lambda t0, t1: False) -> dict:
    """The reel from confident detected events (the caller applies the fact-checker's gate). `cut`
    says whether the broadcast cut between two match times (condensed.py passes the clip's)."""
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
        sure = side_known(e)
        moments.append({
            # A side, and so a player's track (`h-t12`), is named only when it was told surely
            # (factcheck.side_known); origin still compares the detector's sides.
            "event": e["id"], "t": e["t"], "team": e.get("team") if sure else None,
            "player": e.get("player") if sure else None,
            "kind": kind, "why": why, "origin": origin(e, events, cut) if verdict.origins else None,
            "label": tag[0] if tag else kind.upper(), "label_detail": tag[1] if tag else None,
            "d_m": round(d, 1), "v_kmh": v, "T_s": None if T is None else round(T, 2),
            "clip": [round(max(0.0, e["t"] - BEFORE_S), 2), round(e["t"] + AFTER_S, 2)],
        })
    saves = sorted((m for m in moments if m["kind"] == "save"),
                   key=lambda m: (m["T_s"] is None, m["T_s"] or 0.0, m["t"]))
    return {"save_filter": verdict.save_filter,
            "labels": any(m is not None for m in verdict.margins.values()),
            "origins": verdict.origins,
            "moments": moments, "saves_by_pace": [m["event"] for m in saves], "saves_left_out": left_out}


# The recording's VP9 settings: the bundle's own video.webm's (ninety/e2e.py, write_footage), so a
# clip plays wherever the footage does. Never H.264: its usual encoder, x264, is GPL (AGENTS.md).
VP9 = ["-c:v", "libvpx-vp9", "-b:v", "0", "-crf", "32", "-deadline", "realtime", "-cpu-used", "8",
       "-row-mt", "1", "-pix_fmt", "yuv420p"]
DIR = "highlights"


def _name(event_id: str) -> str:
    """A file name from an event id: letters, digits, - and _ only."""
    return re.sub(r"[^A-Za-z0-9_-]", "_", event_id)


def record(reel: dict, timeline, images: list[Path], out: Path, encode: bool) -> dict:
    """Records each moment from the clip's own images into out/highlights/: a still of the image at
    the strike (`<event>.jpg`) and, with `encode` and ffmpeg there, its window as `<event>.webm`.
    Each moment gets `recording`: the images it covers [first, end), their video times, the strike's
    image and the files, relative to the bundle; a moment wholly outside the footage gets none.
    `timeline` maps match time to the footage (ninety/match/timeline.py), across its cuts."""
    fps, n = timeline.fps, len(images)
    folder = out / DIR
    can_encode = encode and shutil.which("ffmpeg") is not None
    for m in reel["moments"]:
        v0, v1 = timeline.to_video(m["clip"][0]), timeline.to_video(m["clip"][1])
        first, end = max(0, math.floor(v0 * fps)), min(n, math.ceil(v1 * fps))
        if end <= first:
            m["recording"] = None
            continue
        shot = min(end - 1, max(first, math.floor(timeline.to_video(m["t"]) * fps)))
        folder.mkdir(parents=True, exist_ok=True)
        name = _name(m["event"])
        shutil.copyfile(images[shot], folder / f"{name}.jpg")
        clip = None
        if can_encode:
            clip = f"{DIR}/{name}.webm"
            pattern = str(images[0].parent / "%05d.jpg")  # the clip's images, numbered from 0
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(fps),
                            "-start_number", str(first), "-i", pattern, "-frames:v", str(end - first),
                            *VP9, str(out / clip)], check=True)
        m["recording"] = {"images": [first, end], "video_t": [round(first / fps, 2), round(end / fps, 2)],
                          "shot_image": shot, "poster": f"{DIR}/{name}.jpg", "clip": clip}
    return reel
