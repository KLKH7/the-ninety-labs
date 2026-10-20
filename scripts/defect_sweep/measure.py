"""Data rates for the verified defect mechanisms, over every match in runs/sweep/m.

Light checks to size each type, not a rule checker (football-sense owns that).
"""

import json
import math
import statistics as st
from pathlib import Path

FPS = 25
OUT_FIELD = {"RB", "RCB", "LCB", "LB", "RCM", "CM", "LCM"}
BACK = {"RB", "RCB", "LCB", "LB"}
res = {k: 0 for k in ("frames", "in_play", "pinned_back4", "own_box_collapse_poss", "poss_frames",
                      "ball_jumps", "kickoffs_after_goal", "stack_pairs_2s", "dead_frames",
                      "dead_frozen", "shots", "shots_gt35", "goals")}
jumps = []
for run in sorted(Path("runs/sweep/m").glob("seed*")):  # run from the repo root
    frames = [json.loads(line) for line in open(run / "frames.jsonl")]
    events = [json.loads(line) for line in open(run / "events.jsonl")]
    res["frames"] += len(frames)
    res["goals"] += sum(e["type"] == "goal" for e in events)
    for e in events:
        if e["type"] == "shot":
            res["shots"] += 1
            gx = 105 if e["team"] == "home" else 0
            if math.hypot(gx - e["x"], 34 - e["y"]) > 35:
                res["shots_gt35"] += 1
    # dead-ball intervals: out_of_play / foul-type stops until the next set_piece or kickoff
    pinned_run = {"home": 0, "away": 0}
    close_run = {}
    prev = None
    for f in frames:
        b = f["ball"]
        if prev is not None:
            d = math.hypot(b["x"] - prev["ball"]["x"], b["y"] - prev["ball"]["y"])
            if d > 3.0:
                res["ball_jumps"] += 1
                jumps.append(d)
        by_team = {"home": [], "away": []}
        for p in f["players"]:
            by_team[p["team"]].append(p)
        moving = [math.hypot(p["vx"], p["vy"]) for p in f["players"] if p["role"] != "GK"]
        for team, ps in by_team.items():
            xs = [p["x"] for p in ps if p["role"] in BACK]
            if max(xs) - min(xs) < 0.3 and prev is not None:
                pxs = [p["x"] for p in prev["players"] if p["team"] == team and p["role"] in BACK]
                if abs(st.mean(xs) - st.mean(pxs)) < 0.02:
                    pinned_run[team] += 1
                else:
                    pinned_run[team] = 0
            else:
                pinned_run[team] = 0
            if pinned_run[team] >= 10 * FPS:
                res["pinned_back4"] += 1
            poss = f.get("possessor")
            if poss and poss[0] == team[0]:
                res["poss_frames"] += 1
                own = [p for p in ps if p["role"] in OUT_FIELD]
                near = sum((p["x"] if team == "home" else 105 - p["x"]) < 17.5 for p in own)
                if near >= 6:
                    res["own_box_collapse_poss"] += 1
        # dead ball proxy: nobody possesses and ball still and all slow
        if f.get("possessor") is None and math.hypot(b["vx"], b["vy"]) < 0.05 and b["z"] < 0.05:
            res["dead_frames"] += 1
            if st.mean(moving) < 0.3:
                res["dead_frozen"] += 1
        # stacked pairs (any two players under 0.5 m), counted when a pair stays 2 s
        ids = f["players"]
        now = set()
        for i in range(len(ids)):
            for j in range(i + 1, len(ids)):
                a, b = ids[i], ids[j]
                if abs(a["x"] - b["x"]) < 0.5 and math.hypot(a["x"] - b["x"], a["y"] - b["y"]) < 0.5:
                    key = (ids[i]["id"], ids[j]["id"])
                    now.add(key)
                    close_run[key] = close_run.get(key, 0) + 1
                    if close_run[key] == 2 * FPS:
                        res["stack_pairs_2s"] += 1
        for k in list(close_run):
            if k not in now:
                del close_run[k]
        prev = f
mins = res["frames"] / FPS / 60
per90 = lambda n: round(n / mins * 90, 1)  # noqa: E731
out = {
    "matches": 30, "minutes": round(mins, 1),
    "back_four_pinned_share": round(res["pinned_back4"] / (2 * res["frames"]), 3),
    "own_box_collapse_share_of_possession":
        round(res["own_box_collapse_poss"] / max(1, res["poss_frames"]), 3),
    "ball_jumps_gt3m_per90": per90(res["ball_jumps"]),
    "ball_jump_median_m": round(st.median(jumps), 1) if jumps else None,
    "stacked_pairs_2s_per90": per90(res["stack_pairs_2s"]),
    "goals_per90": per90(res["goals"]),
    "shots_per90": per90(res["shots"]),
    "shots_gt35m_share": round(res["shots_gt35"] / max(1, res["shots"]), 2),
    "still_ball_frames_share": round(res["dead_frames"] / res["frames"], 3),
    "still_ball_and_frozen_share": round(res["dead_frozen"] / max(1, res["dead_frames"]), 3),
}
print(json.dumps(out, indent=1))
json.dump(out, open("runs/sweep/measure.json", "w"), indent=1)
