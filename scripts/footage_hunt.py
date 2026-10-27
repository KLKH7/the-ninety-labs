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

import argparse
import json
import math
from pathlib import Path

import numpy as np

from ninety.render import edit as _edit  # the renderer's own dead-ball cuts: what is on screen

FPS = 25
_ap = argparse.ArgumentParser(
    description="Editorial watchability scorer for a condensed demo match (offline)."
)
_ap.add_argument("run", type=Path, help="a 90-minute ninety-sim run: events.jsonl, frames.jsonl")
_ap.add_argument("out", type=Path, help="where candidates.json, picks.json and carries.json go")
_args = _ap.parse_args()
RUN, OUT = _args.run, _args.out
OUT.mkdir(parents=True, exist_ok=True)

ev = [json.loads(x) for x in (RUN / "events.jsonl").read_text().splitlines() if x.strip()]
ACTIONS: dict[str, int] = {}  # every action the engine draws, numbered as met (seed- and engine-agnostic)
_ball, _xy, _act, _dive, _poss, ids, roles, teams = [], [], [], [], [], None, None, None
with open(RUN / "frames.jsonl") as fh:
    for line in fh:
        f = json.loads(line)
        b = f["ball"]
        _ball.append((f["t"], b["x"], b["y"], b["z"], b["vx"], b["vy"], b["vz"]))
        if ids is None:
            ids = [p["id"] for p in f["players"]]
            roles = [p.get("role") for p in f["players"]]
            teams = [p["team"] for p in f["players"]]
        _xy.append([(p["x"], p["y"]) for p in f["players"]])
        _act.append([ACTIONS.setdefault(p["action"], len(ACTIONS)) for p in f["players"]])
        _dive.append([p.get("dive", 0.0) for p in f["players"]])
        _poss.append(ids.index(f["possessor"]) if f.get("possessor") in ids else -1)
ball = np.array(_ball, dtype=np.float32)
xy = np.array(_xy, dtype=np.float32)
act = np.array(_act, dtype=np.int16)
dive_amt = np.array(_dive, dtype=np.float32)
poss = np.array(_poss, dtype=np.int16)
touch = poss >= 0  # frames where a player touches the ball (the engine's possessor)
END_S = float(ball[-1, 0])
HALF_S = next((e["t"] for e in ev if e["type"] == "half_time"), END_S / 2)  # a short run has none
HANDS = ACTIONS.get("hands", -99)
SAVE_ACTIONS = [ACTIONS[k] for k in ("dive", "parry", "punch", "tip") if k in ACTIONS]
KEEPERS = {teams[i]: i for i in range(len(ids)) if roles[i] == "GK"}
GK_IDS = {ids[i] for i in KEEPERS.values()}
bspeed = np.hypot(ball[:, 4], ball[:, 5])
SIDE = {"home": 1.0, "away": -1.0}  # the direction each side attacks along x


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
    return KEEPERS["away" if team_shooting == "home" else "home"]


def next_event_t(i: int) -> float:
    """When the ball's flight from event i ends: the first touch by any player after it is struck,
    or the next event if that comes first (the ball going out, a goal); the match's end if none."""
    f0 = ev[i]["frame"] + 3
    nxt = next(
        (e["frame"] for e in ev[i + 1 :] if e["type"] != "pressure" and e["frame"] > ev[i]["frame"]),
        len(touch),
    )
    hit = np.flatnonzero(touch[f0 : max(f0, nxt)])
    return (f0 + hit[0]) / FPS if len(hit) else min(nxt, len(touch) - 1) / FPS


def opponents(team: str) -> list[int]:
    return [k for k in range(len(ids)) if teams[k] != team and roles[k] != "GK"]


def spectacular(e) -> tuple[float, list[str]]:
    """Extra value of a completed pass a viewer notices: long, a switch of play, through the lines,
    or in behind the defence (all measured at the frame it is struck)."""
    f, side = e["frame"], SIDE[e["team"]]
    L = math.hypot(e["end_x"] - e["x"], e["end_y"] - e["y"])
    v, tags = 0.0, []
    if L >= 30:
        v += 1.5
        tags.append("long")
    if abs(e["end_y"] - e["y"]) >= 30:
        v += 1.5
        tags.append("switch")
    opp = opponents(e["team"])
    ox = xy[f, opp, 0] * side
    lo, hi = e["x"] * side, e["end_x"] * side
    broken = int(((ox > lo + 1) & (ox < hi - 1)).sum())
    if broken >= 5:  # most forward passes pass two to four opponents; five or more go through a line
        v += 2.0
        tags.append(f"breaks {broken}")
    elif broken == 4:
        v += 1.0
    if len(ox) >= 2 and hi > np.sort(ox)[-2] + 1 and gain(e) >= 8:  # beyond the second-last defender
        v += 2.5
        tags.append("through ball")
    return v, tags


# ---- carries and take-ons (from the frames: who has the ball) ---------------------------------
CARRY_MIN_M, TAKE_ON_NEAR_M = 10.0, 2.0
carries = []  # (t0, t1, player index, metres gained toward goal, take-ons, into the box, metres)
# The engine names a possessor only on the frames of a touch: a dribble is touch, run, touch. So a
# carry is the stretch where the same player touched the ball last, until it is struck (a pass or a
# shot leaves the foot) or another player touches it.
struck = np.zeros(len(poss), bool)
for e in ev:
    if e["type"] in ("pass", "shot", "out_of_play", "foul", "offside", "goal", "half_time"):
        struck[min(e["frame"], len(poss) - 1)] = True
last = poss.copy()
for f in range(1, len(last)):
    if last[f] < 0 and not struck[f]:
        last[f] = last[f - 1]
poss = last
k = 0
n = len(poss)
while k < n:
    p = poss[k]
    if p < 0:
        k += 1
        continue
    j = k
    while j + 1 < n and poss[j + 1] == p:
        j += 1
    if j - k >= FPS:  # held at least a second
        side = SIDE[teams[p]]
        gained = float((xy[j, p, 0] - xy[k, p, 0]) * side)
        dist = float(np.hypot(*(xy[j, p] - xy[k, p])))
        takes = 0
        for o in opponents(teams[p]) if gained >= 3.0 else []:  # a take-on goes forward past a man
            rel = (xy[k : j + 1, o, 0] - xy[k : j + 1, p, 0]) * side  # > 0: the defender is goal-side
            near = np.hypot(*(xy[k : j + 1, o] - xy[k : j + 1, p]).T) <= TAKE_ON_NEAR_M
            front = np.where(near & (rel > 0))[0]
            if len(front) and (rel[front[0] :] < -1.0).any():
                takes += 1
        into_box = not in_box(teams[p], *xy[k, p]) and in_box(teams[p], *xy[j, p])
        if dist >= CARRY_MIN_M or takes:
            carries.append((k / FPS, j / FPS, p, gained, takes, into_box, dist))
    k = j + 1


# ---- per-event values -------------------------------------------------------------------------
vals: list[tuple[float, float, str]] = []  # (t, value, tag)
musts: list[tuple[float, float, str]] = []  # (t, priority, what): moments the edit must show, if cleanly
for _t0, t1, p, _gained, takes, into_box, dist in carries:
    if takes:
        musts.append((t1, 5.0 + takes, f"take-on {ids[p]}"))
    v = 1.0 + min(3.0, 0.1 * max(0.0, dist - CARRY_MIN_M)) if dist >= CARRY_MIN_M else 0.0
    v += 3.0 * takes + (2.0 if into_box else 0.0)
    vals.append(
        (
            t1,
            v,
            f"carry {dist:.0f}m"
            + (f" take-on x{takes}" if takes else "")
            + (" into box" if into_box else ""),
        )
    )
bad_ts: list[tuple[float, str]] = []  # hard-bad moments (a window should not contain these)
shot_info = {}
for i, e in enumerate(ev):
    t, ty = e["t"], e["type"]
    nxt = ev[i + 1] if i + 1 < len(ev) else None
    if ty == "pass":
        L = math.hypot((e["end_x"] or e["x"]) - e["x"], (e["end_y"] or e["y"]) - e["y"])
        gk_pass = e["player"] in GK_IDS
        if e["outcome"] == "success":
            v = 0.35
            g = gain(e)
            if g >= 10:
                v += 0.6
            if in_final_third(e["team"], e["end_x"]) and not in_final_third(e["team"], e["x"]):
                v += 0.8
            if in_box(e["team"], e["end_x"], e["end_y"]):
                v += 1.5
            sv, stags = spectacular(e)
            if "through ball" in stags or sv >= 4:
                musts.append((t, sv, "pass " + " ".join(stags)))
            vals.append((t, v + sv, "pass+ " + " ".join(stags) if stags else "pass+"))
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
        dives = int(np.isin(seg, SAVE_ACTIONS).sum()) + int((np.abs(dive_amt[f : f + 75, gi]) > 0.3).sum())
        kind = "none"
        if dives and e["outcome"] != "goal":  # a dive or a parry, whatever the shot's outcome is named
            v += 8.0
            kind = "dive save"
            musts.append((t, 20.0, "dive save"))
        elif e["outcome"] == "on_target":
            if len(hands):
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
# A window never opens or closes while the ball is in flight from a pass or a shot (Kian, Oct 26: a cut
# away as a long ball was struck). Starts: a side gains the ball, a restart, or a completed pass about
# to be played. Ends: after the play resolves: the pass has arrived and possession has settled for
# 2.5 s, the shot is finished, the ball has gone dead, or the goal's celebration.
flights = []  # (struck, ends) for every pass and shot
for i, e in enumerate(ev):
    if e["type"] in ("pass", "shot"):
        flights.append((e["t"], next_event_t(i)))
FL = np.array(flights) if flights else np.zeros((0, 2))


def in_flight(t: float) -> bool:
    return bool(((FL[:, 0] < t) & (t < FL[:, 1])).any())


PLAYS = [
    e for e in ev if e["type"] in ("pass", "shot", "possession_change", "out_of_play", "foul", "offside")
]
PT = np.array([e["t"] for e in PLAYS])


def settled(t: float, hold: float = 2.5) -> bool:
    """Nobody plays the ball on (and it does not change hands) for `hold` seconds after t."""
    return not (
        (PT > t + 0.05) & (PT < t + hold + 0.5)
    ).any()  # and nobody strikes it within 0.5 s of the cut


starts = set()
for e in ev:
    if e["type"] in ("possession_change", "interception", "kickoff"):
        starts.add(round(e["t"] - 1.5, 2))
    elif e["type"] == "set_piece":
        starts.add(round(e["t"] - 2.0, 2))
    elif e["type"] == "pass" and e["outcome"] == "success":
        starts.add(round(e["t"] - 1.0, 2))
starts = {a for a in starts if not in_flight(a)}
# ... and the moment a side receives the ball that it won, even off a long ball: the play starts there
starts |= {round(e["t"] - 0.3, 2) for e in ev if e["type"] == "possession_change"}
starts = sorted(starts)
ends = set()
for i, e in enumerate(ev):
    t = e["t"]
    if e["type"] == "shot":
        ends.add(max(t + 3.5, next_event_t(i) + 2.5))
    elif e["type"] in ("out_of_play", "foul", "offside"):
        ends.add(t + 1.5)
    elif e["type"] == "goal":
        ends.add(t + 12.0)
    elif e["type"] == "possession_change" and settled(t):
        ends.add(t + 2.5)
    elif e["type"] == "pass" and e["outcome"] == "success":
        arrive = next_event_t(i)
        if settled(arrive):
            ends.add(arrive + 2.5)
ends = sorted(round(b, 2) for b in ends if not in_flight(b))

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

# 3) the moments a viewer should see (dive saves, take-ons, through balls), each in its best clean window
for t, _, what in sorted(musts, key=lambda m: -m[1]):
    if any(c["start"] <= t <= c["end"] for c in chosen):
        continue
    opts = [
        c
        for c in cands
        if not c["bad"]
        and c["score"] >= 3.0
        and c["start"] <= t - 3
        and c["end"] >= t + 2
        and not overlaps(c["start"], c["end"], chosen)
    ]
    if opts:
        c = dict(max(opts, key=lambda c: c["score"]))
        c["why"] = f"must: {what}"
        chosen.append(c)

# 4) the rest by density, clean windows only, until 18 min (+ a reserve list for the contact sheet)
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
long_carries = [c for c in carries if c[6] >= CARRY_MIN_M]
take_ons = sum(c[4] for c in carries)
picked_t = [(c["start"], c["end"]) for c in chosen]
shown = [c for c in carries if any(a <= c[0] and c[1] <= b for a, b in picked_t)]
report = {
    "long_carries": len(long_carries),
    "long_carries_20m": sum(1 for c in carries if c[6] >= 20),
    "take_ons": take_ons,
    "carries_into_box": sum(1 for c in carries if c[5]),
    "in_the_picks": {
        "long_carries": sum(1 for c in shown if c[6] >= CARRY_MIN_M),
        "take_ons": sum(c[4] for c in shown),
    },
    "best": [
        {
            "clock": f"{int(c[0] // 60):02d}:{int(c[0] % 60):02d}",
            "player": ids[c[2]],
            "metres": round(c[6], 1),
            "take_ons": c[4],
            "into_box": bool(c[5]),
        }
        for c in sorted(carries, key=lambda c: -(c[4] * 10 + c[6]))[:15]
    ],
}
(OUT / "carries.json").write_text(json.dumps(report, indent=1))
print("carries:", json.dumps({k: v for k, v in report.items() if k != "best"}))
