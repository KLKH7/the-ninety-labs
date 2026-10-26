"""Editorial watchability scorer: the footage hunt that re-cut the seed-8080 condensed match (Oct 26).

EDITORIAL ONLY (docs/eval/demo-match-hunt.md). It reads the simulator's answer key (events.jsonl and
frames.jsonl of a 90-minute run) to choose which stretches of the match to render, as a broadcast
director picks highlights. Nothing it writes goes on the live path: vision sees only the rendered
pixels, and the chapters made from its picks are the edit's chapters, never detections, never an
agent's input. It decides what is shown, never what happened: the engine is not touched.

    uv run ninety-sim --seed 8080 --minutes 90 --out <run>
    uv run python scripts/footage_hunt.py <run> <out dir>   -> candidates.json, picks.json

Every weight here is *design*, by eye, aimed at Kian's three complaints about the first cut (Oct 26):
poor passing and keeper distribution, keepers catching with no dive or clear contact, and cuts that
landed on the worst bits. A window with a flagged moment (an aimless long ball, a lost keeper pass,
a long ball out, an odd catch) is never picked; goals are always in, with their build-up.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np

from ninety.render import edit as _edit  # the renderer's own dead-ball cuts: what is on screen

FPS = 25
ACTIONS = [
    "walk",
    "stand",
    "run",
    "foot",
    "strike",
    "down",
    "hands",
    "thigh",
    "throw",
    "chest",
    "bowl",
    "head",
    "dive",
]
RUN, OUT = Path(sys.argv[1]), Path(sys.argv[2])
OUT.mkdir(parents=True, exist_ok=True)

ev = [json.loads(x) for x in (RUN / "events.jsonl").read_text().splitlines() if x.strip()]
_ball, _xy, _act, ids = [], [], [], None
with open(RUN / "frames.jsonl") as fh:
    for line in fh:
        f = json.loads(line)
        b = f["ball"]
        _ball.append((f["t"], b["x"], b["y"], b["z"], b["vx"], b["vy"], b["vz"]))
        ids = ids or [p["id"] for p in f["players"]]
        _xy.append([(p["x"], p["y"]) for p in f["players"]])
        _act.append([ACTIONS.index(p["action"]) for p in f["players"]])
ball = np.array(_ball, dtype=np.float32)
xy = np.array(_xy, dtype=np.float32)
act = np.array(_act, dtype=np.int8)
END_S = float(ball[-1, 0])
HALF_S = next(e["t"] for e in ev if e["type"] == "half_time")
HANDS, DIVE = ACTIONS.index("hands"), ACTIONS.index("dive")
bspeed = np.hypot(ball[:, 4], ball[:, 5])


def attack_x(team: str) -> float:  # home attacks x=105, away x=0, no change of ends (demo-match.md)
    return 105.0 if team == "home" else 0.0


def gain(e) -> float:
    if e["end_x"] is None:
        return 0.0
    return (e["end_x"] - e["x"]) * (1 if e["team"] == "home" else -1)


def in_box(team, x, y) -> bool:
    gx = attack_x(team)
    return abs(x - gx) <= 16.5 and 13.84 <= y <= 54.16


def in_final_third(team, x) -> bool:
    return abs(x - attack_x(team)) <= 35


def keeper_of(team_shooting: str) -> int:
    return ids.index("a1" if team_shooting == "home" else "h1")


# ---- per-event values -------------------------------------------------------------------------
vals: list[tuple[float, float, str]] = []  # (t, value, tag)
bad_ts: list[tuple[float, str]] = []  # hard-bad moments (a window should not contain these)
shot_info = {}
for i, e in enumerate(ev):
    t, ty = e["t"], e["type"]
    nxt = ev[i + 1] if i + 1 < len(ev) else None
    if ty == "pass":
        L = math.hypot((e["end_x"] or e["x"]) - e["x"], (e["end_y"] or e["y"]) - e["y"])
        gk_pass = e["player"] in ("h1", "a1")
        if e["outcome"] == "success":
            v = 0.35
            g = gain(e)
            if g >= 10:
                v += 0.6
            if in_final_third(e["team"], e["end_x"]) and not in_final_third(e["team"], e["x"]):
                v += 0.8
            if in_box(e["team"], e["end_x"], e["end_y"]):
                v += 1.5
            vals.append((t, v, "pass+"))
        else:
            aimless = e.get("intended") is None
            v = -1.5
            if aimless and L > 25:
                v = -4.0
                bad_ts.append((t, "aimless long ball"))
            if gk_pass:
                v = min(v, -4.0)
                bad_ts.append((t, "keeper distribution lost"))
            # a dangerous through ball that just misses is fine-ish
            if not aimless and in_box(e["team"], e["end_x"] or 0, e["end_y"] or 0):
                v = -0.3
            vals.append((t, v, "pass-"))
        # straight out of play off a pass with nobody touching it
        if nxt and nxt["type"] == "out_of_play" and nxt["t"] - t < 4 and L > 25:
            vals.append((t, -2.5, "ball out"))
            bad_ts.append((t, "long ball out"))
    elif ty == "shot":
        v = 4.0 + (3.0 if e["outcome"] == "on_target" else 0) + (1.0 if e["outcome"] == "blocked" else 0)
        if in_box(e["team"], e["x"], e["y"]):
            v += 1.0
        gi = keeper_of(e["team"])
        f = e["frame"]
        seg = act[f : f + 75, gi]
        hands = np.where(seg == HANDS)[0]
        dives = (seg == DIVE).sum()
        kind = "none"
        if e["outcome"] == "on_target":
            if dives:
                v += 8.0
                kind = "dive save"
            elif len(hands):
                h = f + hands[0]
                dist = float(np.hypot(*(xy[h, gi] - ball[h, 1:3])))
                z = float(ball[h, 3])
                if 0.3 <= z <= 1.8 and dist <= 1.2:
                    v += 1.5
                    kind = f"clean catch z={z:.1f}"
                else:
                    v -= 9.0
                    kind = f"odd catch z={z:.1f} d={dist:.1f}"
                    bad_ts.append((t + hands[0] / FPS, kind))
        shot_info[e["id"]] = kind
        vals.append((t, v, f"shot {e['outcome']} {kind}"))
    elif ty == "goal":
        vals.append((t, 25.0, "goal"))
    elif ty in ("tackle", "interception") and e.get("outcome") != "fail":
        vals.append((t, 0.4, ty))
    elif ty == "foul":
        vals.append((t, -0.5, "foul"))
    elif ty == "set_piece":
        # a corner or a final-third free kick is an event; a throw-in in midfield is not
        if in_final_third(e["team"], e["x"]) and (
            e["y"] not in (0, 68) or abs(e["x"] - attack_x(e["team"])) < 3
        ):
            vals.append((t, 1.0, "set piece fwd"))

vals.sort()
VT = np.array([v[0] for v in vals])
VV = np.array([v[1] for v in vals])

# ---- in-play and idle -------------------------------------------------------------------------
# dead stretches: from out_of_play/foul/offside/goal to the next set_piece/kickoff
dead = np.zeros(len(ball), bool)
stop_types = {"out_of_play", "foul", "offside", "goal", "half_time"}
restart_types = {"set_piece", "kickoff"}
stop_t = None
for e in ev:
    if e["type"] in stop_types and stop_t is None:
        stop_t = e["t"]
    elif e["type"] in restart_types and stop_t is not None:
        dead[int(stop_t * FPS) : int(e["t"] * FPS)] = True
        stop_t = None
slow = (bspeed < 1.5) & ~dead
CUTS = _edit.cuts(ev, FPS)
cut_mask = np.zeros(len(ball), bool)
for _c in CUTS:
    cut_mask[_c.first_frame : _c.last_frame + 1] = True
dead &= ~cut_mask  # a dead ball the renderer cuts is not on screen


def window_score(a: float, b: float):
    m = (VT >= a) & (VT <= b)
    s = VV[m].sum()
    fa, fb = int(a * FPS), int(b * FPS)
    idle = slow[fa:fb].sum() / FPS
    deadt = dead[fa:fb].sum() / FPS
    s -= 0.25 * idle + 0.15 * deadt
    hard = [x for x in bad_ts if a <= x[0] <= b]
    return s, idle, deadt, hard


def shown_s(a, b):
    return (~cut_mask[int(a * FPS) : int(b * FPS)]).sum() / FPS


# ---- candidate windows ------------------------------------------------------------------------
# starts: a side gains the ball (possession_change, interception, set_piece, kickoff) - a clean
# moment to cut in; ends: the play ends (shot+3 s, out_of_play+1 s, possession lost +1 s, goal+12 s).
starts = sorted(
    {
        round(e["t"] - 1.5, 2)
        for e in ev
        if e["type"] in ("possession_change", "set_piece", "kickoff", "interception")
    }
    | {round(e["t"] - 1.0, 2) for e in ev if e["type"] == "pass" and e["outcome"] == "success"}
)
ends = []
for e in ev:
    if e["type"] == "shot":
        ends.append(e["t"] + 3.5)
    elif e["type"] in ("out_of_play", "foul", "offside"):
        ends.append(e["t"] + 1.0)
    elif e["type"] == "possession_change":
        ends.append(e["t"] + 1.0)
    elif e["type"] == "goal":
        ends.append(e["t"] + 12.0)
    if e["type"] == "pass":
        ends.append(
            e["t"] - 0.3
        )  # cut just before a pass is struck (a director cuts before a play breaks down)
        if e["outcome"] == "success" and e["end_x"] is not None:
            ends.append(e["t"] + 2.0)
ends = sorted(set(round(x, 2) for x in ends))

cands = []
for a in starts:
    if a < 0:
        a = 0.0
    for b in ends:
        if b - a < 10:
            continue
        if b - a > 200:
            break
        L = shown_s(a, b)
        if L < 10:
            continue
        if L > 40:
            continue
        if a < HALF_S < b:  # never straddle half-time (its own segment)
            continue
        s, idle, deadt, hard = window_score(a, b)
        cands.append(
            {
                "start": round(a, 2),
                "end": round(b, 2),
                "len": round(float(L), 2),
                "score": round(float(s), 2),
                "density": round(float(s) / L, 3),
                "idle": round(idle, 1),
                "dead": round(deadt, 1),
                "bad": [h[1] for h in hard],
            }
        )

goals = [e for e in ev if e["type"] == "goal"]


# ---- selection --------------------------------------------------------------------------------
def overlaps(a, b, chosen, gap=12.0):
    return any(not (b + gap <= c["start"] or a - gap >= c["end"]) for c in chosen)


chosen = []
# 1) every goal: the best window ending at goal+12 that starts at a clean gain of the ball 15-40 s before
for g in goals:
    opts = [c for c in cands if abs(c["end"] - (g["t"] + 12.0)) < 0.05 and c["len"] >= 12]
    opts.sort(key=lambda c: (len(c["bad"]) > 0, -c["score"]))
    pick = (
        dict(opts[0])
        if opts
        else {"start": g["t"] - 25, "end": g["t"] + 12, "len": 37, "score": 25, "bad": []}
    )
    pick["why"] = f"goal {g['team']} {int(g['t'] // 60):02d}:{int(g['t'] % 60):02d}"
    chosen.append(pick)
# 2) fixed: kick-off, half-time (whistle + card), full time (whistle + card)
chosen.append({"start": 0.0, "end": 14.0, "len": 14.0, "score": 0, "bad": [], "why": "kick-off"})
chosen.append(
    {"start": HALF_S - 10, "end": HALF_S + 9, "len": 19.0, "score": 0, "bad": [], "why": "half-time"}
)
chosen.append({"start": END_S - 12, "end": END_S, "len": 12.0, "score": 0, "bad": [], "why": "full-time"})

# 3) the rest by density, clean windows only, until 18 min (+ a reserve list for the contact sheet)
TARGET = 18 * 60
MIN_SCORE = 4.0
RESERVE_SCORE = 1.5
pool = [c for c in cands if not c["bad"] and c["score"] >= RESERVE_SCORE and c["dead"] <= 4]
pool.sort(key=lambda c: -c["density"] * math.sqrt(c["score"]))
reserve = []
for c in pool:  # first the picks (score >= MIN_SCORE) until TARGET
    if (
        c["score"] < MIN_SCORE
        or sum(x["len"] for x in chosen) >= TARGET
        or overlaps(c["start"], c["end"], chosen)
    ):
        continue
    c = dict(c)
    c["why"] = "play"
    chosen.append(c)
for c in pool:  # then a reserve for the contact sheet
    if len(reserve) >= 70 or overlaps(c["start"], c["end"], chosen + reserve):
        continue
    c = dict(c)
    c["why"] = "reserve"
    reserve.append(c)

chosen.sort(key=lambda c: c["start"])
reserve.sort(key=lambda c: c["start"])
for c in chosen + reserve:
    m = (VT >= c["start"]) & (VT <= c["end"])
    c["tags"] = [vals[i][2] for i in np.where(m)[0] if vals[i][2] not in ("pass+",)]
    c["passes_ok"] = sum(1 for i in np.where(m)[0] if vals[i][2] == "pass+")
    c["clock"] = f"{int(c['start'] // 60):02d}:{int(c['start'] % 60):02d}"

(OUT / "candidates.json").write_text(json.dumps(cands))
(OUT / "picks.json").write_text(
    json.dumps({"picked": chosen, "reserve": reserve, "shots": shot_info, "bad_moments": bad_ts}, indent=1)
)
tot = sum(c["len"] for c in chosen)
print(f"candidates {len(cands)}  picked {len(chosen)} segments, {tot / 60:.1f} min; reserve {len(reserve)}")
for c in chosen:
    print(
        f"{c['clock']} {c['len']:5.1f}s score {c.get('score', 0):6.1f} {c['why']:9}",
        f"bad={c['bad']} {c['tags'][:6]}",
    )
print("bad moments:", len(bad_ts))
