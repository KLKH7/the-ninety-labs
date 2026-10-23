"""Pick and cut the live demo's condensed full match by the rule in docs/eval/demo-match.md.

The rule was fixed and merged before any match in its pool was simulated on the final engine.
Every function below except `measure_seed` and `main` is pure: events and numbers in, a choice out.

    # one seed at a time, at most two at once, each through the machine's slot limit:
    runs/slot.sh uv run python scripts/demo_match.py measure 8002
    # once all 40 have a measure.json:
    uv run python scripts/demo_match.py select > runs/demo-match/manifest.json
"""

from __future__ import annotations

import json
import statistics
import subprocess
import sys
from pathlib import Path

FIRST_SEED, LAST_SEED = 8002, 8041  # 8001 was the demo seed for v1 and v2: watched, and fixed on
EXTRA_SEEDS = (8042, 8081)  # the pool's extension, only if no seed in it passes every gate
MINUTES = 90.0
OUT = Path("runs/demo-match")

PITCH_X, PITCH_Y = 105.0, 68.0
FINAL_THIRD_X = PITCH_X / 3  # Law 1 gives the length; the thirds are the usual split (S2)
ATTACKS = {"home": PITCH_X, "away": 0.0}  # the engine plays 90 minutes without changing ends

# Gates. G2: GROUNDING R3, pass completion about 75 to 88 percent. G4: goals in a match.
COMPLETION = (0.75, 0.88)
GOALS = (1, 6)
# G3: the football-sense types with a pass line (GROUNDING FS1 to FS9; FS4 and FS7 are report only,
# FS6's possessions are counted from its passes).
FS_GATED = ("chaser_moves_away", "pass_out_unpressed", "keeper_stays_home", "bunching",
            "own_box_pass", "loose_ball_ignored", "camped_in_own_box")

# The action score. A goal is also a shot on target, and a save is one too.
W_GOAL, W_CONTESTED, W_SAVE, W_ON_TARGET, W_SET_PIECE, W_MOVE = 3.0, 4.0, 1.0, 1.0, 0.5, 0.2
MOVE_PASSES = 5  # a passing move: at least this many completed passes in a row by one side

# The edit: seconds kept before and after each moment (A, B).
WINDOWS = {"goal": (25.0, 20.0), "shot": (12.0, 6.0), "corner": (2.0, 12.0),
           "free_kick": (2.0, 12.0), "move": (2.0, 4.0)}
OPEN_S = CLOSE_S = 20.0  # the kick-off and the last seconds of the match
HALF_S = 10.0  # either side of 45:00 (the engine has no interval: this is the clock, not a whistle)
TOP_MOVES = 8  # N: the longest passing moves kept
MERGE_GAP_S = 5.0  # segments closer than this are joined: a stinger for a shorter jump is noise
TARGET_S = (15 * 60.0, 20 * 60.0)
# Dropped first when the edit runs long; tier 0 is never dropped (see the doc's adjustment).
TIER = {"kickoff": 0, "half": 0, "full_time": 0, "goal": 0, "save": 0,
        "shot": 1, "corner": 2, "free_kick": 2, "move": 3}
# A segment's chapter is named for its most important moment; the kick-off, 45:00 and the end
# are marked as well, wherever they fall.
STRUCTURE = ("kickoff", "half", "full_time")
CHAPTER_ORDER = ("goal", "save", "shot", "corner", "free_kick", "move", "kickoff", "half", "full_time")

STOPS = {"out_of_play", "goal", "foul", "offside"}
# Viewer footage (lesson 185) with the two tactical lenses (views=tactical) beside the broadcast.
RENDER_FLAGS = ("--set dead_ball_cut=true --set kit_contrast=broadcast --set stadium=broadcast "
                "--set views=tactical")


# ---- what happened (from the simulator's events: an editorial choice, never the live path) ----

def restart_kind(stopped_by: dict | None, sp: dict) -> str:
    """The kind of a set piece, from the event that stopped play (Laws 13 to 17), as
    scripts/defect_sweep/restarts.py reads it; offside gives an indirect free kick (Law 11)."""
    x, y = sp["x"], sp["y"]
    if stopped_by is None or stopped_by["type"] in ("foul", "offside"):
        if abs(y - PITCH_Y / 2) < 0.5 and min(abs(x - 11), abs(x - (PITCH_X - 11))) < 0.5:  # the penalty mark
            return "penalty_kick"
        if stopped_by is not None and stopped_by["type"] == "offside":
            return "indirect_free_kick"
        return "free_kick"
    if stopped_by["y"] <= 0.01 or stopped_by["y"] >= PITCH_Y - 0.01:
        return "throw_in"
    return "goal_kick" if min(x, PITCH_X - x) > 2.0 else "corner"


def in_final_third(team: str, x: float) -> bool:
    return abs(ATTACKS[team] - x) <= FINAL_THIRD_X


def moments(events: list[dict]) -> list[dict]:
    """Goals, shots (a save is a shot on target not scored), corners and direct free kicks in the
    taking side's final third, in match order: {kind, t, team}."""
    out, stopped_by = [], None
    for e in events:
        k = e["type"]
        if k in STOPS:
            stopped_by = e
        if k == "goal":
            out.append({"kind": "goal", "t": e["t"], "team": e["team"]})
        elif k == "shot" and e.get("outcome") != "goal":
            kind = "save" if e.get("outcome") == "on_target" else "shot"
            out.append({"kind": kind, "t": e["t"], "team": e["team"]})
        elif k == "set_piece":
            kind = restart_kind(stopped_by, e)
            direct = kind in ("free_kick", "penalty_kick") and in_final_third(e["team"], e["x"])
            if kind == "corner" or direct:
                out.append({"kind": "free_kick" if direct else "corner", "t": e["t"],
                            "team": e["team"]})
        if k in ("set_piece", "kickoff"):
            stopped_by = None
    return out


def passing_moves(events: list[dict]) -> list[dict]:
    """Runs of at least MOVE_PASSES completed passes by one side: {team, start, end, passes}. A
    failed pass, a shot, a stop (out of play, foul, offside, goal), or any touch by the other side
    ends a run; pressure and the side's own tackles and deflections do not, and a restart may start one."""
    out, run = [], None

    def close():
        if run and run["passes"] >= MOVE_PASSES:
            out.append(dict(run))

    for e in events:
        k = e["type"]
        if k == "pressure" or k in ("set_piece", "kickoff"):
            continue  # pressure touches nothing; a restart follows a stop, which already ended the run
        if k == "pass" and e.get("outcome") == "success":
            if run is None or run["team"] != e["team"]:
                close()
                run = {"team": e["team"], "start": e["t"], "passes": 0}
            run["passes"] += 1
            run["end"] = e["t"]
            continue
        if run and e["team"] == run["team"] and k in ("tackle", "deflection", "possession_change"):
            continue  # our own touch keeps the ball with us
        close()
        run = None
    close()
    return out


def counts(events: list[dict]) -> dict:
    """What the score and the gates read from one match's events."""
    ms = moments(events)
    goals = {t: sum(m["kind"] == "goal" and m["team"] == t for m in ms) for t in ATTACKS}
    on_target = {t: goals[t] + sum(m["kind"] == "save" and m["team"] == t for m in ms) for t in ATTACKS}
    passes = [e for e in events if e["type"] == "pass"]
    completed = sum(e.get("outcome") == "success" for e in passes)
    return {"goals": goals, "on_target": on_target,
            "saves": sum(m["kind"] == "save" for m in ms),
            "set_pieces": sum(m["kind"] in ("corner", "free_kick") for m in ms),
            "moves": len(passing_moves(events)),
            "passes": len(passes), "completion": completed / len(passes) if passes else 0.0,
            "possession_changes": sum(e["type"] == "possession_change" for e in events)}


def contested(c: dict) -> bool:
    """Both sides scored, or the side with fewer goals had at least two shots on target."""
    h, a = c["goals"]["home"], c["goals"]["away"]
    if h and a:
        return True
    behind = "home" if h < a else "away"
    return h != a and c["on_target"][behind] >= 2


def action_score(c: dict) -> float:
    return (W_GOAL * sum(c["goals"].values()) + W_CONTESTED * contested(c) + W_SAVE * c["saves"]
            + W_ON_TARGET * sum(c["on_target"].values()) + W_SET_PIECE * c["set_pieces"]
            + W_MOVE * c["moves"])


# ---- the choice ----

def ranks(values: list[float]) -> list[float]:
    """1 for the smallest; tied values share the mean of their places."""
    order = sorted(range(len(values)), key=lambda i: values[i])
    out = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        for k in range(i, j + 1):
            out[order[k]] = (i + j) / 2 + 1
        i = j + 1
    return out


def gate_table(pool: list[dict]) -> list[dict]:
    """Each measured seed with its gates. A row: {seed, valid, counts, fs_per90: {type: n}}.
    G3 ranks every seed in the pool on each gated football-sense type (fewest defects first) and
    passes a seed whose mean rank is at or below the pool's median mean rank."""
    per_type = [ranks([r["fs_per90"][k] for r in pool]) for k in FS_GATED]
    mean_rank = [statistics.fmean(rs[i] for rs in per_type) for i in range(len(pool))]
    bar = statistics.median(mean_rank)
    rows = []
    for r, mr in zip(pool, mean_rank, strict=True):
        c = r["counts"]
        total = sum(c["goals"].values())
        g = {"G1_contract": r["valid"],
             "G2_completion": COMPLETION[0] <= c["completion"] <= COMPLETION[1],
             "G3_football_sense": mr <= bar,
             "G4_goals": GOALS[0] <= total <= GOALS[1]}
        rows.append({"seed": r["seed"], "gates": g, "passed": all(g.values()), "fs_mean_rank": mr,
                     "fs_bar": bar, "score": action_score(c), "counts": c})
    return rows


def choose(rows: list[dict]) -> dict | None:
    """The gated seed with the highest action score; a tie goes to the lowest seed."""
    passed = [r for r in rows if r["passed"]]
    return min(passed, key=lambda r: (-r["score"], r["seed"])) if passed else None


# ---- the edit ----

def items(events: list[dict], end_s: float, n_moves: int = TOP_MOVES) -> list[dict]:
    """Every moment the edit keeps, as {kind, t, start, end}, before merging."""
    out = [{"kind": "kickoff", "t": 0.0, "start": 0.0, "end": OPEN_S},
           {"kind": "half", "t": 45 * 60.0, "start": 45 * 60.0 - HALF_S, "end": 45 * 60.0 + HALF_S},
           {"kind": "full_time", "t": end_s, "start": end_s - CLOSE_S, "end": end_s}]
    for m in moments(events):
        a, b = WINDOWS["shot" if m["kind"] == "save" else m["kind"]]
        out.append({"kind": m["kind"], "t": m["t"], "start": m["t"] - a, "end": m["t"] + b})
    out += move_items(events, n_moves)
    for it in out:
        it["start"], it["end"] = max(0.0, it["start"]), min(end_s, it["end"])
    return sorted(out, key=lambda it: (it["start"], it["t"]))


def move_items(events: list[dict], n: int) -> list[dict]:
    """The n longest passing moves (most passes; a tie goes to the earlier)."""
    mv = sorted(passing_moves(events), key=lambda m: (-m["passes"], m["start"]))[:n]
    a, b = WINDOWS["move"]
    return [{"kind": "move", "t": m["start"], "start": m["start"] - a, "end": m["end"] + b,
             "passes": m["passes"]} for m in mv]


def merge(its: list[dict]) -> list[dict]:
    """Join overlapping windows, and windows less than MERGE_GAP_S apart."""
    segs: list[dict] = []
    for it in sorted(its, key=lambda it: (it["start"], it["t"])):
        if segs and it["start"] - segs[-1]["end"] < MERGE_GAP_S:
            segs[-1]["end"] = max(segs[-1]["end"], it["end"])
            segs[-1]["items"].append(it)
        else:
            segs.append({"start": it["start"], "end": it["end"], "items": [it]})
    return segs


def total(segs: list[dict]) -> float:
    return sum(s["end"] - s["start"] for s in segs)


def unique_s(it: dict, its: list[dict]) -> float:
    """Seconds of the edit that only this item keeps."""
    return total(merge(its)) - total(merge([o for o in its if o is not it]))


def condense(events: list[dict], end_s: float) -> dict:
    """The edit: windows round every moment, merged, then adjusted into TARGET_S by the stated
    steps. Returns {segments, chapters, total_s, adjust}."""
    its, adjust = items(events, end_s), []
    if total(merge(its)) < TARGET_S[0]:  # too short: the next-longest moves, one at a time
        all_moves = move_items(events, 10 ** 6)
        for m in all_moves[TOP_MOVES:]:
            if total(merge(its)) >= TARGET_S[0]:
                break
            its.append(m)
            adjust.append(f"added move of {m['passes']} at {clock(m['t'])}")
    while total(merge(its)) > TARGET_S[1]:  # too long: drop from the highest tier down
        tier = max(TIER[it["kind"]] for it in its)
        if tier == 0:
            adjust.append("only tier 0 left: over the target, kept")
            break
        cand = [it for it in its if TIER[it["kind"]] == tier]
        if tier == 3:  # moves: the fewest passes first, a tie the later
            drop = min(cand, key=lambda it: (it["passes"], -it["t"]))
        else:  # the one that frees most time, a tie the later
            drop = max(cand, key=lambda it: (unique_s(it, its), it["t"]))
        its.remove(drop)
        adjust.append(f"dropped {drop['kind']} at {clock(drop['t'])}")
    segs = merge(its)
    video, chapters = 0.0, []
    for s in segs:
        s["video_start"] = video
        play = [it for it in s["items"] if it["kind"] not in STRUCTURE]
        if play:  # the segment's chapter, named for its most important moment
            top = min(play, key=lambda it: (CHAPTER_ORDER.index(it["kind"]), it["t"]))
            chapters.append(chapter(top["kind"], top["t"], video))
        for it in s["items"]:  # the kick-off, 45:00 and the end are marked wherever they fall
            if it["kind"] in STRUCTURE:
                at = it["start"] if it["kind"] == "full_time" else it["t"]
                chapters.append(chapter(it["kind"], at, video + at - s["start"]))
        video += s["end"] - s["start"]
    chapters.sort(key=lambda c: (c["video_s"], CHAPTER_ORDER.index(c["type"])))
    return {"segments": [{"start_s": round(s["start"], 2), "end_s": round(s["end"], 2),
                          "video_start_s": round(s["video_start"], 2)} for s in segs],
            "chapters": chapters, "total_s": round(total(segs), 2), "adjust": adjust}


def chapter(kind: str, t: float, video: float) -> dict:
    return {"type": kind, "clock": clock(t), "match_s": round(t, 2), "video_s": round(video, 2)}


def clock(t: float) -> str:
    return f"{int(t // 60):02d}:{int(t % 60):02d}"


def render_command(seed: int, start: float, end: float, i: int) -> str:
    return (f"uv run ninety-render --seed {seed} --start {start:g} --seconds {end - start:g} "
            f"{RENDER_FLAGS} --mp4 --gpu --out runs/demo-match/seed{seed}/seg{i:02d}")


# ---- running it (impure) ----

def measure_seed(seed: int) -> None:
    """Simulate one seed for 90 minutes, validate it, count its football sense, keep the counts
    and the events, and delete the frames (the match is re-made from its seed)."""
    from ninety.eval import football_sense as fs

    run = OUT / f"seed{seed}"
    subprocess.run(["uv", "run", "ninety-sim", "--seed", str(seed), "--minutes", f"{MINUTES:g}",
                    "--out", str(run)], check=True)
    valid = subprocess.run(["uv", "run", "ninety-validate", str(run)]).returncode == 0
    found = fs.check(fs.load(run))
    events = [json.loads(line) for line in open(run / "events.jsonl")]
    row = {"seed": seed, "valid": valid, "counts": counts(events),
           "fs_per90": {k: fs.per90(len(found["findings"][k]), found["minutes"]) for k in FS_GATED}}
    (run / "measure.json").write_text(json.dumps(row, indent=1))
    (run / "frames.jsonl").unlink()


def main() -> None:
    if len(sys.argv) == 3 and sys.argv[1] == "measure":
        measure_seed(int(sys.argv[2]))
        return
    if sys.argv[1:] != ["select"]:
        sys.exit(__doc__)
    pool = [json.loads(p.read_text()) for p in sorted(OUT.glob("seed*/measure.json"))]
    seeds = {r["seed"] for r in pool}
    missing = sorted(set(range(FIRST_SEED, LAST_SEED + 1)) - seeds)
    if missing:
        sys.exit(f"not measured yet: {missing}")
    rows = gate_table(pool)
    best = choose(rows)
    if best is None:
        sys.exit(f"no seed passes every gate: extend the pool to {EXTRA_SEEDS[0]}-{EXTRA_SEEDS[1]} "
                 "under the same rule")
    run = OUT / f"seed{best['seed']}"
    events = [json.loads(line) for line in open(run / "events.jsonl")]
    meta = json.loads((run / "meta.json").read_text())
    edit = condense(events, float(meta["minutes"]) * 60)
    top5 = sorted([r for r in rows if r["passed"]], key=lambda r: (-r["score"], r["seed"]))[:5]
    print(json.dumps({"seed": best["seed"], "score": best["score"], "top5": top5, "edit": edit,
                      "render": [render_command(best["seed"], s["start_s"], s["end_s"], i)
                                 for i, s in enumerate(edit["segments"])],
                      "gates": rows}, indent=1))


if __name__ == "__main__":
    main()
