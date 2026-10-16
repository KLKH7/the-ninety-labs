"""Measure what `--scenario corner` produces, beside published figures. A report, never a gate:
nothing in the routine is tuned to hit these numbers (docs/GROUNDING.md, S rows and R9).

    uv run python -m ninety.sim.corner_report --seeds 200     # writes docs/eval/sim-corners.md

First contact is the first player other than the taker to touch the ball after the kick: a
touch event (deflection, interception, tackle, possession change, pass, shot) or having the ball
at the end of a frame, whichever comes first. A clean reception has no event of its own, so
counting events alone undercounts the attackers.
"""

from __future__ import annotations

import argparse
import json
import math
import tempfile
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from statistics import median, quantiles

from ninety.sim.body import FOOT_REACH_Z
from ninety.sim.engine import FPS, corner_seed, simulate
from ninety.validate import validate

ROOT = Path(__file__).resolve().parents[2]
MINUTES = 0.75  # after the corner is given: long enough for the set-up, the kick and 10 s after it
AFTER_S = 10.0  # outcomes counted within this long of the kick
TOUCHES = {"deflection", "interception", "tackle", "possession_change", "pass", "shot"}


def measure(seed: int) -> dict:
    m = simulate(seed, MINUTES, "corner")
    ev, frames = m.events, m.frames
    keepers = {r["id"]: r["team"] for r in m.roster if r.get("role") == "GK"}
    out = next(e for e in ev if e["type"] == "out_of_play" and e["x"] in (0.0, 105.0))
    ready = next(e for e in ev if e["type"] == "set_piece" and e["frame"] > out["frame"])
    kick = next(e for e in ev if e["type"] == "pass" and e["frame"] >= ready["frame"])
    end = kick["frame"] + int(AFTER_S * FPS)
    first = None
    for f in frames[kick["frame"] + 1:end]:
        hit = [e for e in ev if e["frame"] == f["frame"] and e["type"] in TOUCHES
               and e.get("player") not in (None, kick["player"])]
        if hit:
            first = hit[0]["player"]
            break
        if f["possessor"] and f["possessor"] != kick["player"]:
            first = f["possessor"]
            break
    after = [e for e in ev if kick["frame"] < e["frame"] <= end]
    headed = [e for e in after if e["type"] in ("pass", "shot")
              and frames[e["frame"]]["ball"]["z"] > FOOT_REACH_Z]
    lofted = any(f["ball"]["z"] > 0.5 for f in frames[kick["frame"]:kick["frame"] + 10])
    landed = next((f["t"] for f in frames[kick["frame"] + 2:end] if f["ball"]["z"] < 0.15), None)
    with tempfile.TemporaryDirectory() as d:
        clip = Path(d)
        (clip / "events.jsonl").write_text("".join(json.dumps(e) + "\n" for e in ev))
        (clip / "frames.jsonl").write_text("".join(json.dumps(f) + "\n" for f in frames))
        (clip / "meta.json").write_text(json.dumps({"fps": FPS, "score": m.score, "roster": m.roster}))
        problems = validate(clip)
    team = "attackers" if first and first.startswith("h") else "defenders" if first else "nobody"
    return {
        "seed": seed, "valid": not problems,
        "first": "defending keeper" if first in keepers and keepers[first] == "away" else team,
        "goal": any(e["type"] == "goal" and e["team"] == "home" for e in after),
        "heads": (sum(e["team"] == "home" for e in headed), sum(e["team"] == "away" for e in headed),
                  sum(e["type"] == "shot" and e["team"] == "home" for e in headed)),
        "shot": any(e["type"] == "shot" and e["team"] == "home" for e in after),
        "lofted": lofted, "flight": (landed - kick["t"]) if (landed and lofted) else None,
        "ready_to_kick": kick["t"] - ready["t"], "out_to_kick": kick["t"] - out["t"],
        "attack_to_out": out["t"], "attempts": m.seed - corner_seed(seed, 0), "base_t": m.opening_t,
        "cause": cause(ev, out, frames),
        "end": (kick.get("end_x"), kick.get("end_y")),
    }


PRESSED_M = 3.0  # design: an attacker this close to the defender as he kicks it counts as pressing him


def cause(ev: list[dict], out: dict, frames: list[dict]) -> str:
    """What sent the ball out for the corner: the last kick before it (a home shot or pass, or an
    away pass or clearance, and whether an attacker was pressing him), and whether a defender
    deflected it on its way."""
    before = [e for e in ev if e["frame"] <= out["frame"] and e is not out]
    kick = next((e for e in reversed(before) if e["type"] in ("pass", "shot")), None)
    if kick is None:
        return "no kick (carried out)"
    if kick["team"] == "away":
        f = frames[kick["frame"]]
        me = next(p for p in f["players"] if p["id"] == kick["player"])
        near = min(math.hypot(p["x"] - me["x"], p["y"] - me["y"])
                   for p in f["players"] if p["team"] == "home")
        how = "headed" if f["ball"]["z"] > FOOT_REACH_Z else "kicked"
        pressed = "pressed" if near <= PRESSED_M else "unpressed"
        return f"a defender's pass or clearance, {how}, {pressed}"
    deflected = any(e["type"] == "deflection" and e["team"] == "away" and e["frame"] >= kick["frame"]
                    for e in before)
    how = "deflected by a defender" if deflected else "touched out by a defender"
    return f"a home {kick['type']}, {how}"


def spread(xs: list[float]) -> str:
    if len(xs) < 2:
        return "n/a"
    q = quantiles(xs, n=10)
    return f"{median(xs):.1f} s (10th to 90th percentile {q[0]:.1f} to {q[-1]:.1f})"


def report(rows: list[dict]) -> str:
    n = len(rows)
    first = Counter(r["first"] for r in rows)
    goals, shots = sum(r["goal"] for r in rows), sum(r["shot"] for r in rows)
    flights = [r["flight"] for r in rows if r["flight"] is not None]
    lines = [
        "# Corner scenario report",
        "",
        f"`uv run python -m ninety.sim.corner_report --seeds {n}`: seeds 0 to {n - 1}, "
        f"each an attack from a moment open play reached (the home side on the ball in its final "
        f"third) that play turned into a corner, run on {MINUTES} minutes after it "
        "was given (S9). A report, never a gate (docs/GROUNDING.md, R9).",
        "",
        "| Measure | Result | Published |",
        "|---|---|---|",
        f"| Clips meeting the data contract | {sum(r['valid'] for r in rows)} / {n} | all |",
        f"| Goals within {AFTER_S:.0f} s of the kick | {goals} / {n} ({100 * goals / n:.1f}%) | "
        "about 2% (R9) |",
        f"| Attacking shots within {AFTER_S:.0f} s | {shots} / {n} | |",
        f"| First contact: attackers / defenders (keeper) / nobody | {first['attackers']} / "
        f"{first['defenders'] + first['defending keeper']} ({first['defending keeper']}) / "
        f"{first['nobody']} | |",
        f"| Lofted deliveries | {sum(r['lofted'] for r in rows)} / {n} | |",
        f"| Headers within {AFTER_S:.0f} s (P17): attackers / defenders; attackers' headers at goal | "
        f"{sum(r['heads'][0] for r in rows)} / {sum(r['heads'][1] for r in rows)}; "
        f"{sum(r['heads'][2] for r in rows)} | |",
        f"| Lofted delivery, kick to first bounce or touch below 0.15 m | {spread(flights)} | |",
        f"| Ready (set-piece event) to kick | {spread([r['ready_to_kick'] for r in rows])} | |",
        f"| Out of play to kick | {spread([r['out_to_kick'] for r in rows])} | |",
        f"| Opening to the ball going out for the corner | "
        f"{spread([r['attack_to_out'] for r in rows])} | |",
        f"| Attacks played per corner (selection, not a rate) | "
        f"median {median(r['attempts'] for r in rows):.0f}, most {max(r['attempts'] for r in rows)} | |",
        f"| Distinct delivery end points (to 1 m) | "
        f"{len({(round(x), round(y)) for x, y in (r['end'] for r in rows) if x is not None})} / {n} | |",
    ]
    causes = Counter(r["cause"] for r in rows)
    lines += ["", "What sent the ball out for the corner (the opening and the selection shape this mix; "
              "it is not how corners arise in matches):", "", "| Cause | Corners |", "|---|---|"]
    lines += [f"| {k} | {v} |" for k, v in causes.most_common()]
    bad = [r["seed"] for r in rows if not r["valid"]]
    if bad:
        lines += ["", f"Seeds failing the contract: {bad}"]
    return "\n".join(lines) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--seeds", type=int, default=200)
    ap.add_argument("--out", type=Path, default=ROOT / "docs" / "eval" / "sim-corners.md")
    args = ap.parse_args()
    with ProcessPoolExecutor() as pool:
        rows = list(pool.map(measure, range(args.seeds)))
    text = report(rows)
    args.out.write_text(text)
    print(text)


if __name__ == "__main__":
    main()
