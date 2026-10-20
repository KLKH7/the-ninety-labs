"""Restart defects (catalogue rows 2, 3 and 5) in simulated matches, per 90 minutes.

    uv run python scripts/defect_sweep/restarts.py runs/base/seed7 runs/base/seed11 ...

A light measurement to size the restart defects before and after a fix, not a rule checker:
- ball jumps: the ball moves more than 3 m in one frame (the sweep's rule; real: never);
- player jumps: a player moves faster than the validator's speed limit in one frame;
- kick-off: seconds from each goal to the kick-off;
- encroachment: at the frame a restart is kicked, an opponent nearer the ball than the Laws allow
  (Laws 13, 15, 17: 9.15 m from a free kick or corner, 2 m from a throw-in) or, at a goal kick,
  inside the kicking side's penalty area (Law 16). The kind of restart is read from the event that
  stopped play and where the ball is placed;
- second touch (Laws 8, 13 to 17): the taker's first pass or shot more than 1 m from where the
  restart was set (he carried the set ball first), or his next touch after it before anyone else's;
- held-out outcomes (never targets): shots and goals a team per 90 with the standard error over
  matches, pass completion, shots within 10 s of the shooting side's own restart, the first pass
  after each kind of restart failing, and the ball lost within 5 s of it.
"""

import json
import math
import statistics as st
import sys
from pathlib import Path

from ninety.validate import MAX_PLAYER_MPS

FPS = 25
PITCH_X, PITCH_Y = 105.0, 68.0
PENALTY_DEPTH, PENALTY_HALF_WIDTH = 16.5, 20.16  # Law 1
DISTANCE = {"free_kick": 9.15, "corner": 9.15, "throw_in": 2.0}  # Laws 13, 15, 17


def kind_of(stopped_by: dict | None, sp: dict) -> str:
    x, y = sp["x"], sp["y"]
    if stopped_by is None or stopped_by["type"] in ("foul", "offside"):
        if abs(y - 34) < 0.5 and min(abs(x - 11), abs(x - 94)) < 0.5:
            return "penalty_kick"
        return "free_kick"
    oy = stopped_by["y"]
    if oy <= 0.01 or oy >= PITCH_Y - 0.01:
        return "throw_in"
    return "goal_kick" if min(x, PITCH_X - x) > 2.0 else "corner"


def measure(run: Path) -> dict:
    frames = [json.loads(line) for line in open(run / "frames.jsonl")]
    events = [json.loads(line) for line in open(run / "events.jsonl")]
    by_frame = {f["frame"]: f for f in frames}
    out = {"minutes": len(frames) / FPS / 60, "ball_jumps": 0, "player_jumps": 0, "jump_m": [],
           "goal_to_kick_s": [], "restarts": {}, "encroached": {}, "encroach_examples": [],
           "shots": sum(e["type"] == "shot" for e in events),
           "goals": sum(e["type"] == "goal" for e in events),
           "passes": 0, "completed": 0, "shots_after_own_restart": 0,
           "set": {}, "first_failed": {}, "lost_5s": {}, "carried_set_ball": 0, "touched_again": 0}
    touches = ("pass", "shot", "deflection", "interception", "tackle")
    for i, e in enumerate(events):
        if e["type"] not in ("set_piece", "kickoff"):
            continue
        kick = next((k for k in events[i + 1:] if k["type"] in ("pass", "shot")), None)
        if kick is None or kick["player"] != e["player"]:
            continue
        if math.hypot(kick["x"] - e["x"], kick["y"] - e["y"]) > 1.0:
            out["carried_set_ball"] += 1
        j = events.index(kick)
        nxt = next((k for k in events[j + 1:] if k["type"] in touches and k.get("player")), None)
        if nxt and nxt["player"] == e["player"]:
            out["touched_again"] += 1
    last = None  # (time, team) of the last restart
    for e in events:
        if e["type"] in ("set_piece", "kickoff"):
            last = (e["t"], e["team"])
        elif e["type"] == "pass":
            out["passes"] += 1
            out["completed"] += e["outcome"] == "success"
        elif e["type"] == "shot" and last and e["t"] - last[0] < 10 and e["team"] == last[1]:
            out["shots_after_own_restart"] += 1
    for prev, f in zip(frames, frames[1:], strict=False):
        b, a = prev["ball"], f["ball"]
        d = math.hypot(a["x"] - b["x"], a["y"] - b["y"])
        if d > 3.0:
            out["ball_jumps"] += 1
            out["jump_m"].append(round(d, 1))
        before = {p["id"]: p for p in prev["players"]}
        if any(math.hypot(p["x"] - before[p["id"]]["x"], p["y"] - before[p["id"]]["y"]) * FPS > MAX_PLAYER_MPS
               for p in f["players"]):
            out["player_jumps"] += 1
    stopped_by = None
    for i, e in enumerate(events):
        if e["type"] in ("out_of_play", "foul", "offside"):
            stopped_by = e
        if e["type"] == "goal":  # the kickoff event is the kick (first frame it is in play)
            kick = next((k for k in events[i + 1:] if k["type"] == "kickoff"), None)
            if kick:
                out["goal_to_kick_s"].append(round(kick["t"] - e["t"], 1))
        if e["type"] != "set_piece":
            continue
        kind = kind_of(stopped_by, e)
        stopped_by = None
        out["set"][kind] = out["set"].get(kind, 0) + 1
        first = next((k for k in events[i + 1:] if k["type"] in ("pass", "shot")), None)
        if first and first["type"] == "pass" and first["outcome"] != "success":
            out["first_failed"][kind] = out["first_failed"].get(kind, 0) + 1
        if any(k["type"] == "possession_change" and k["team"] != e["team"] and k["t"] - e["t"] < 5
               for k in events[i + 1:i + 40]):
            out["lost_5s"][kind] = out["lost_5s"].get(kind, 0) + 1
        kick = next((k for k in events[i + 1:] if k["type"] in ("pass", "shot")), None)
        if kind == "penalty_kick" or kick is None or kick["player"] != e["player"]:
            continue
        out["restarts"][kind] = out["restarts"].get(kind, 0) + 1
        # In play when kicked and it clearly moves (Laws 13, 15 to 17): at the kick, or the first
        # frame the ball has moved from where it was set (by more than the files' rounding), if sooner.
        f = None
        for n in range(e["frame"], kick["frame"] + 1):
            f = by_frame.get(n)
            if f and math.hypot(f["ball"]["x"] - e["x"], f["ball"]["y"] - e["y"]) > 0.05:
                break
        if f is None:
            continue
        bx, by = f["ball"]["x"], f["ball"]["y"]
        bad = []
        for p in f["players"]:
            if p["team"] == e["team"]:
                continue
            if kind == "goal_kick":
                own_line = 0.0 if bx < PITCH_X / 2 else PITCH_X
                if abs(p["x"] - own_line) <= PENALTY_DEPTH and abs(p["y"] - 34) <= PENALTY_HALF_WIDTH:
                    bad.append(p["id"])
            elif math.hypot(p["x"] - bx, p["y"] - by) < DISTANCE[kind]:
                bad.append(p["id"])
        if bad:
            out["encroached"][kind] = out["encroached"].get(kind, 0) + 1
            out["encroach_examples"].append((run.name, kind, round(f["t"], 1), bad))
    return out


def main() -> None:
    runs = [measure(Path(r)) for r in sys.argv[1:]]
    mins = sum(r["minutes"] for r in runs)
    per90 = lambda n: round(n / mins * 90, 1)  # noqa: E731
    restarts, encroached = {}, {}
    for r in runs:
        for k, n in r["restarts"].items():
            restarts[k] = restarts.get(k, 0) + n
        for k, n in r["encroached"].items():
            encroached[k] = encroached.get(k, 0) + n
    jumps = sorted(j for r in runs for j in r["jump_m"])

    def per_team_90(key: str) -> list[float]:
        xs = [r[key] / r["minutes"] * 90 / 2 for r in runs]
        se = st.stdev(xs) / len(xs) ** 0.5 if len(xs) > 1 else None
        return [round(st.mean(xs), 2), round(se, 2) if se is not None else None]

    def share(key: str) -> dict:
        kinds = ("throw_in", "free_kick", "goal_kick", "corner")
        n = {k: sum(r["set"].get(k, 0) for r in runs) for k in kinds}
        return {k: round(sum(r[key].get(k, 0) for r in runs) / n[k], 2) for k in n if n[k]}
    print(json.dumps({
        "matches": len(runs), "minutes": round(mins, 1),
        "ball_jumps_gt3m_per90": per90(sum(r["ball_jumps"] for r in runs)),
        "ball_jump_median_m": jumps[len(jumps) // 2] if jumps else None,
        "frames_with_a_player_over_speed_limit_per90": per90(sum(r["player_jumps"] for r in runs)),
        "goal_to_kickoff_s": [s for r in runs for s in r["goal_to_kick_s"]],
        "restarts_kicked_by_taker": restarts,
        "encroached_at_the_kick": encroached,
        "taker_carried_the_set_ball": sum(r["carried_set_ball"] for r in runs),
        "taker_touched_it_again_first": sum(r["touched_again"] for r in runs),
        "examples": [x for r in runs for x in r["encroach_examples"]][:12],
        "held_out": {
            "shots_per_team_90_mean_se": per_team_90("shots"),
            "goals_per_team_90_mean_se": per_team_90("goals"),
            "completion": round(sum(r["completed"] for r in runs)
                                / max(1, sum(r["passes"] for r in runs)), 3),
            "shots_within_10s_of_own_restart": sum(r["shots_after_own_restart"] for r in runs),
            "shots_otherwise": sum(r["shots"] - r["shots_after_own_restart"] for r in runs),
            "first_pass_failed_share": share("first_failed"),
            "ball_lost_within_5s_share": share("lost_5s"),
        },
    }, indent=1))


if __name__ == "__main__":
    main()
