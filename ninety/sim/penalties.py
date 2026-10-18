"""How penalties end against the keeper, in the form the published studies report them: where the
kick crossed the keeper's line (the middle or a side third of the goal's width, and the third of
its height) against what the keeper did (stayed, or dived toward or away from it). A report, never
a gate: nothing in the engine is tuned to these numbers (docs/GROUNDING.md P15, A2; decision 0002).

    uv run python -m ninety.sim.penalties    # writes docs/eval/penalties.md
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from ninety.sim import ball
from ninety.sim.engine import (
    CROSSBAR,
    FPS,
    GOAL_HALF_WIDTH,
    PENALTY_MARK_M,
    PITCH_Y,
    POST_RADIUS,
    Engine,
    attack_dir,
    goal_x,
    other,
)

ROOT = Path(__file__).resolve().parents[2]
THIRD_WIDE_M = 2 * GOAL_HALF_WIDTH / 3  # Bar-Eli et al. 2007 divide the goal into 3 x 3 cells
THIRD_HIGH_M = CROSSBAR / 3  # Higueras-Herbada et al. 2020: low, middle, high by thirds of 244 cm
WARM_UP_S = 20.0  # play this long first, so the penalty is given in an ordinary state of play
KICK_LIMIT_S = 200.0  # a bound only: the wait before a penalty is 100 to 140 s (D10)

# Published, by the same cells: Bar-Eli et al. 2007, Table 2 (286 penalties on target), stops over kicks.
BAR_ELI = {("side", "toward"): (31, 113), ("side", "away"): (0, 83), ("side", "stay"): (0, 8),
           ("middle", "dive"): (5, 72), ("middle", "stay"): (6, 10)}
BAR_ELI_ALL = (42, 286)
# Higueras-Herbada et al. 2020 (Frontiers in Psychology 11:311): saves by the height of the kick.
HEIGHT_SAVED = {"low": "16.5%", "middle": "33.5%", "high": "9.1%"}


def one(seed: int) -> dict | None:
    """One penalty, given after WARM_UP_S of play to the side's best finisher, with the real wait
    before it: where it crossed the keeper's line, what the keeper did, and how it ended."""
    e = Engine(seed)
    e.kickoff("home")
    for _ in range(int(WARM_UP_S * FPS)):
        e.step()
    e.possessor = None
    e.kicked = None
    team = "home"
    mark = (goal_x(team) - attack_dir(team) * PENALTY_MARK_M, PITCH_Y / 2)
    outfield = [q for q in e.players if q.team == team and q.role != "GK"]
    taker = max(outfield, key=lambda q: q.profile["finishing"])
    keeper = e.keeper(other(team))
    e.stop("penalty_kick", team, mark, taker.id)
    rec: dict = {"seed": seed}
    shot = None
    for _ in range(int(KICK_LIMIT_S * FPS)):
        e.step()
        if shot is None and e.kicked and e.kicked["type"] == "shot":
            shot = e.kicked
        if shot is not None and "cross" not in rec:
            arrival = e.ball_at_x(keeper.x)
            if arrival:
                rec["cross"], rec["z"] = arrival[1] - PITCH_Y / 2, arrival[2]
        if shot is not None and "dive" not in rec and e.dive and e.dive[0] == keeper.id:
            rec["dive"] = e.dive[3]
        if shot is not None and shot.get("outcome"):
            rec["outcome"] = shot["outcome"]
            return rec
    return rec if "outcome" in rec else None


def on_target(cross: float, z: float) -> bool:
    """Whether a kick, by its own flight where it crosses the keeper's line (`cross` from the goal's
    centre, `z` the ball's lowest point), goes in clear of the posts and the crossbar, by the engine's
    own goal (engine.woodwork). Bar-Eli et al. 2007 left out kicks that hit the woodwork or went wide;
    so does this, whatever then happened to the ball (a defender's touch, a save tipped wide)."""
    clear = POST_RADIUS + ball.RADIUS
    return abs(cross) < GOAL_HALF_WIDTH - clear and z + ball.RADIUS < CROSSBAR - clear


def tabulate(kicks: list[dict]) -> dict:
    """Group kicks on target (on_target, by their own flight) by the published cells: the third of
    the goal's width the kick crossed in against what the keeper did, and the third of its height (the
    ball's centre); kept out of each: whatever did not end a goal."""
    cells: dict = defaultdict(Counter)
    heights: dict = defaultdict(Counter)
    total = Counter()
    for k in kicks:
        if "cross" not in k or not on_target(k["cross"], k["z"]):
            continue
        kept = k["outcome"] != "goal"
        total["n"] += 1
        total["kept"] += kept
        where = "middle" if abs(k["cross"]) < THIRD_WIDE_M / 2 else "side"
        dive = k.get("dive")
        if dive is None:
            act = "stay"
        elif where == "middle":
            act = "dive"
        else:
            act = "toward" if dive * k["cross"] > 0 else "away"
        cells[(where, act)]["n"] += 1
        cells[(where, act)]["kept"] += kept
        zc = k["z"] + ball.RADIUS
        band = "low" if zc < THIRD_HIGH_M else ("middle" if zc < 2 * THIRD_HIGH_M else "high")
        heights[band]["n"] += 1
        heights[band]["kept"] += kept
    return {"total": total, "cells": cells, "heights": heights}


def share(kept: int, n: int) -> str:
    return f"{kept} of {n} ({kept / n:.1%})" if n else "none"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--kicks", type=int, default=400)
    ap.add_argument("--out", default=str(ROOT / "docs/eval/penalties.md"))
    args = ap.parse_args()
    with ProcessPoolExecutor() as pool:
        ran = list(pool.map(one, range(args.kicks)))
    kicks = [k for k in ran if k]
    t = tabulate(kicks)
    outcomes = Counter(k.get("outcome") for k in kicks)
    uncrossed = sum("cross" not in k for k in kicks)
    wide = sum("cross" in k and not on_target(k["cross"], k["z"]) for k in kicks)
    recorded = dict(sorted(outcomes.items(), key=lambda kv: str(kv[0])))
    lines = ["# Penalties against the keeper", "",
             f"Generated by `uv run python -m ninety.sim.penalties` with {args.kicks} penalties (seeds 0 to "
             f"{args.kicks - 1}): {WARM_UP_S:g} s of play, then a penalty to the home side's best finisher "
             "with the real wait before the kick. Each kick is placed by where its own flight crossed the "
             "keeper's line (at the strike, before anyone touched it): the middle or a side third of the "
             "goal's width, and the third of its height (the ball's centre). On target: clear of the posts "
             "and the crossbar by that flight, as Bar-Eli et al. left out kicks off the woodwork or wide; "
             "kept out: any of those that did not end a goal (saved, tipped wide, or cleared). "
             "\"Stay\" is a keeper who did not dive. In the engine he dives only after seeing the ball, "
             "toward where it really crosses, so he stays when it comes within his reach and never dives "
             "the wrong way; Bar-Eli's keepers chose before the kick (GROUNDING A2, P15). A report, "
             "never a target.", "",
             f"Not taken within {KICK_LIMIT_S:g} s: {len(ran) - len(kicks)} (the taker never reached the "
             f"mark). Taken but no crossing found: {uncrossed}. Off target by their own flight: {wide}. "
             f"Outcomes as the engine recorded them: {recorded}.", "",
             "| Kick crossed | Keeper | Kept out | Bar-Eli et al. 2007, Table 2 |", "|---|---|---|---|"]
    for key in BAR_ELI:
        c = t["cells"][key]
        lines.append(f"| {key[0]} third | {key[1]} | {share(c['kept'], c['n'])} | {share(*BAR_ELI[key])} |")
    total = t["total"]
    lines.append(f"| all on target | | {share(total['kept'], total['n'])} | {share(*BAR_ELI_ALL)} |")
    lines += ["", "| Height | Kept out | Higueras-Herbada et al. 2020, saved |", "|---|---|---|"]
    for band in ("low", "middle", "high"):
        c = t["heights"][band]
        lines.append(f"| {band} | {share(c['kept'], c['n'])} | {HEIGHT_SAVED[band]} |")
    Path(args.out).write_text("\n".join(lines) + "\n")
    print("\n".join(lines[6:]))


if __name__ == "__main__":
    main()
