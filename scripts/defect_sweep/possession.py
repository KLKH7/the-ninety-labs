"""Possession spells, how they end, and how far a dribbler's touches go (the possession-churn
measurement, lesson 170).

    uv run python scripts/defect_sweep/possession.py runs/new/seed7 runs/new/seed11 ...

From each run's frames.jsonl and events.jsonl (simulated matches, ground truth):

- **Who has the ball.** Each frame's toucher is the possessor, or else a player whose body is on the
  ball that frame (action foot, strike, chest, thigh, hands, throw or dive, within 1 m of it). The
  team of the last toucher owns the ball; a restart gives it to the restarting side.
- **Possessions.** A spell of one team owning the ball, counted two ways: broken at every stoppage,
  or carried through a stoppage the same team restarts. Only in-play time counts toward a spell's
  length; passes are the owner's completed passes in it.
- **How spells end in play** (the other side becomes owner without a stoppage): by the event that
  gave the ball away. A tackle or poke on the owner; an interception of a pass; a pass that reached
  nobody of his side (overhit or underhit, not intercepted); a loose ball after a deflection or a
  duel; a keeper's distribution. Separately, whether the owner was dribbling when it happened (his
  own last touch was a dribble touch, with the ball loose between his touches).
- **Dribble touches.** Two touches in a row by the same player with nobody else touching between
  them, the second within 3 s of the first and no pass or shot between: the ball's travel from the
  one to the other, the farthest it got from him meanwhile, and his speed at the first, by speed.
"""

import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path

FPS = 25
TOUCH_ACTIONS = {"foot", "strike", "chest", "thigh", "hands", "throw", "dive"}
REACH_M = 1.0  # a body on the ball is within this of it (precision: wider than any contact)
STOPS = {"out_of_play", "foul", "offside", "goal"}
RESTARTS = {"set_piece", "kickoff"}
SPEED_BINS = ((0.0, 2.0, "under 2 m/s"), (2.0, 4.0, "2 to 4 m/s"), (4.0, 6.0, "4 to 6 m/s"),
              (6.0, 99.0, "over 6 m/s"))


def toucher(f: dict) -> dict | None:
    if f["possessor"]:
        return next(p for p in f["players"] if p["id"] == f["possessor"])
    b = f["ball"]
    on = [p for p in f["players"] if p["action"] in TOUCH_ACTIONS
          and math.hypot(p["x"] - b["x"], p["y"] - b["y"]) <= REACH_M]
    return min(on, key=lambda p: math.hypot(p["x"] - b["x"], p["y"] - b["y"])) if on else None


def measure(run: Path) -> dict:
    meta = json.loads((run / "meta.json").read_text())
    role = {r["id"]: r["role"] for r in meta["roster"]}
    events = [json.loads(line) for line in open(run / "events.jsonl")]
    by_frame = defaultdict(list)
    for e in events:
        by_frame[e["frame"]].append(e)
    out = {"minutes": 0.0, "spells_broken": [], "spells_through": [], "ends": Counter(),
           "ends_dribbling": Counter(), "touches": []}
    owner, dead = None, False
    spell = None  # [team, in-play frames, completed passes, start frame]
    through = None
    last = None  # the last toucher: (player id, team, frame, was it a dribble touch)
    open_touch = None  # a dribbler's last touch: (player id, frame, ball x, y, his speed, farthest)
    n = 0
    prev_holder = None
    was_dribbling = False

    def close(reason: str) -> None:
        nonlocal spell
        if spell and spell[1] > 0:
            out["spells_broken"].append({"team": spell[0], "s": spell[1] / FPS, "passes": spell[2],
                                         "end": reason, "start": spell[4]})
        spell = None

    def close_through() -> None:
        nonlocal through
        if through and through[1] > 0:
            out["spells_through"].append({"team": through[0], "s": through[1] / FPS, "passes": through[2]})
        through = None

    for line in open(run / "frames.jsonl"):
        f = json.loads(line)
        n += 1
        evs = by_frame.get(f["frame"], [])
        for e in evs:
            if e["type"] in STOPS:
                dead = True
                close(e["type"])
            elif e["type"] in RESTARTS:
                dead = False
                owner = e["team"]
                if through and through[0] != owner:
                    close_through()
                spell = [owner, 0, 0, f["frame"], "restart"]
                if through is None:
                    through = [owner, 0, 0, f["frame"]]
                last, open_touch, prev_holder = (e["player"], e["team"], f["frame"]), None, None
            elif e["type"] == "pass" and e.get("outcome") == "success" and e["team"] == owner:
                if spell:
                    spell[2] += 1
                if through:
                    through[2] += 1
        if dead:
            continue
        t = toucher(f)
        b = f["ball"]
        holder = f["possessor"]
        struck = any(e["type"] in ("pass", "shot") and e.get("player") == prev_holder
                     for e in evs_before(by_frame, f["frame"], 0.2))
        if prev_holder and holder is None and not struck:  # he has pushed it on: a dribble touch
            p = next(q for q in f["players"] if q["id"] == prev_holder)
            open_touch = [prev_holder, f["frame"], b["x"], b["y"], math.hypot(p["vx"], p["vy"]), 0.0]
        if open_touch and holder is None:  # the ball between his touches: how far from him it gets
            p = next(q for q in f["players"] if q["id"] == open_touch[0])
            open_touch[5] = max(open_touch[5], math.hypot(b["x"] - p["x"], b["y"] - p["y"]))
        if open_touch and holder == open_touch[0]:
            if f["frame"] - open_touch[1] <= 3 * FPS:
                out["touches"].append({"length": math.hypot(b["x"] - open_touch[2], b["y"] - open_touch[3]),
                                       "farthest": open_touch[5], "speed": open_touch[4]})
            open_touch = None
        dribbling = open_touch is not None and holder is None
        if t is not None:
            team = t["team"]
            if open_touch and t["id"] != open_touch[0]:
                open_touch = None  # someone else got to it
            controls = f["possessor"] == t["id"] or any(
                e["type"] in ("pass", "shot") and e.get("player") == t["id"] for e in evs)
            # A momentary touch by the other side (a block, a poke) does not make the ball theirs.
            if controls or team == owner:
                if owner is not None and team != owner:
                    cause = end_cause(evs_before(by_frame, f["frame"]), owner, role, last)
                    out["ends"][cause] += 1
                    if was_dribbling:
                        out["ends_dribbling"][cause] += 1
                    close(cause)
                    close_through()
                    spell = [team, 0, 0, f["frame"], "open play"]
                    through = [team, 0, 0, f["frame"]]
                owner = team
                last = (t["id"], team, f["frame"])
        if spell:
            spell[1] += 1
        if through:
            through[1] += 1
        prev_holder = holder
        was_dribbling = dribbling
    close("end")
    close_through()
    out["minutes"] = n / FPS / 60
    return out


def share(xs: list[float], lo: float, hi: float) -> float:
    return round(sum(1 for x in xs if lo <= x < hi) / len(xs), 3)


def evs_before(by_frame: dict, frame: int, back_s: float = 3.0) -> list[dict]:
    """The events of the last few seconds up to this frame, latest last."""
    return [e for k in range(frame - int(back_s * FPS), frame + 1) for e in by_frame.get(k, [])]


def end_cause(recent: list[dict], owner: str, role: dict, last) -> str:
    """What gave the ball away: the latest telling event in the last seconds."""
    for e in reversed(recent):
        if e["type"] == "tackle" and e["team"] != owner and e.get("outcome") == "success":
            return "tackle or poke"
        if e["type"] == "interception" and e["team"] != owner:
            return "interception"
        if e["type"] == "pass" and e["team"] == owner:
            if e.get("interceptor"):
                return "interception"
            if role.get(e["player"]) == "GK":
                return "keeper's distribution"
            return "pass to nobody of his side"
        if e["type"] == "shot" and e["team"] == owner:
            return "shot (blocked, saved or off target, kept in play)"
        if e["type"] == "deflection":
            if e["team"] == owner:
                return "loose ball off his own touch (a heavy touch)"
            return "loose ball off an opponent (a block or deflection)"
        if e["type"] == "tackle":
            return "loose ball after a tackle neither side won"
    return "loose ball, no event (dribble touch or first touch lost)"


def main() -> None:
    runs = [measure(Path(r)) for r in sys.argv[1:]]
    mins = sum(r["minutes"] for r in runs)
    per_team_90 = lambda n: round(n / mins * 90 / 2, 1)  # noqa: E731
    report = {"matches": len(runs), "minutes": round(mins, 1)}
    for key in ("spells_broken", "spells_through"):
        spells = [s for r in runs for s in r[key]]
        passes = [s["passes"] for s in spells]
        secs = sorted(s["s"] for s in spells)
        report[key] = {
            "per_team_90": per_team_90(len(spells)),
            "mean_passes": round(sum(passes) / len(passes), 2),
            "mean_s": round(sum(secs) / len(secs), 1),
            "median_s": round(secs[len(secs) // 2], 1),
            "share_by_passes": {k: round(sum(1 for p in passes if (p == k if k < 3 else p >= 3))
                                         / len(passes), 3) for k in (0, 1, 2, 3)},
        }
        if key == "spells_broken":
            open_s = [sp["s"] for sp in spells if sp["start"] == "open play"]
            report[key]["begun_in_open_play"] = round(len(open_s) / len(spells), 3)
            report[key]["open_play_s_shares"] = {
                "0-10": share(open_s, 0, 10), "10-20": share(open_s, 10, 20),
                "20-30": share(open_s, 20, 30), "30+": share(open_s, 30, 1e9)}
            all_s = [sp["s"] for sp in spells]
            report[key]["s_shares"] = {"under 5": share(all_s, 0, 5), "5-12": share(all_s, 5, 12),
                                       "over 12": share(all_s, 12, 1e9)}
    ends = sum((r["ends"] for r in runs), Counter())
    dribbling = sum((r["ends_dribbling"] for r in runs), Counter())
    total = sum(ends.values())
    report["lost_in_play_per_team_90"] = per_team_90(total)
    report["lost_in_play_by_cause"] = {k: {"per_team_90": per_team_90(v), "share": round(v / total, 3),
                                           "while_dribbling": dribbling.get(k, 0)}
                                       for k, v in ends.most_common()}
    touches = [t for r in runs for t in r["touches"]]
    by_speed = {}
    for lo, hi, name in SPEED_BINS:
        ts = sorted(t["length"] for t in touches if lo <= t["speed"] < hi)
        far = sorted(t["farthest"] for t in touches if lo <= t["speed"] < hi)
        if ts:
            by_speed[name] = {"touches": len(ts), "length_median_m": round(ts[len(ts) // 2], 2),
                              "length_p90_m": round(ts[int(0.9 * (len(ts) - 1))], 2),
                              "farthest_median_m": round(far[len(far) // 2], 2),
                              "farthest_p90_m": round(far[int(0.9 * (len(far) - 1))], 2)}
    report["dribble_touches"] = by_speed
    print(json.dumps(report, indent=1))


if __name__ == "__main__":
    main()
