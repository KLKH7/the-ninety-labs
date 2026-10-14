"""Measure the simulator against published Premier League per-match averages.

    uv run python -m ninety.sim.realism                 # 10 seeds, writes docs/eval/sim-realism.{md,json}
    uv run python -m ninety.sim.realism --seeds 3 --no-write

Real data is used only as these published averages, to tune the simulator's rates. No real
match data is read or committed.
"""

from __future__ import annotations

import argparse
import datetime
import json
import math
import subprocess
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from ninety.sim.engine import FPS, SPRINT_MS, Match, simulate

ROOT = Path(__file__).resolve().parents[2]
PL_TACTICS = "https://www.premierleague.com/news/4271974"
FOOTYSTATS_CORNERS = "https://footystats.org/england/premier-league/corner-stats"

# key: (label, low, high, real average, source). The band is what one simulated 90-minute match
# must land in. Rows without a source are working bands: the real average is still to be cited.
BANDS: dict[str, tuple[str, float, float, str, str | None]] = {
    "shots": ("Shots", 14, 40, "26.1 per 90 (2024/25)", PL_TACTICS),
    "ball_in_play": ("Ball in play, share of match time", 0.52, 0.66, "57.1% (2024/25)", PL_TACTICS),
    "corners": ("Corners", 2, 22, "about 9.3", FOOTYSTATS_CORNERS),
    "passes": ("Passes (throw-ins excluded)", 800, 1150, "", None),
    "pass_completion": ("Pass completion", 0.78, 0.90, "", None),
    "pass_length_m": ("Average completed pass length (m)", 17, 23, "", None),
    "shots_on_target": ("Shots on target (goals included)", 3, 16, "", None),
    "throw_ins": ("Throw-ins", 28, 62, "", None),
    "goal_kicks": ("Goal kicks", 5, 28, "", None),
    "fouls": ("Fouls", 10, 34, "", None),
    "tackles": ("Tackles (won and lost)", 15, 60, "", None),
    "interceptions": ("Interceptions", 8, 35, "", None),
    "saves": ("Saves", 2, 15, "", None),
    "home_possession": ("Home possession share", 0.40, 0.60, "", None),
    "distance_km": ("Distance per outfield player (km)", 8.5, 12.0, "", None),
    "top_speed_ms": ("Top player speed (m/s)", 8.0, 10.0, "", None),
}
# Goals vary too much in one match for a band; the mean over the report's 10 seeds is checked instead.
GOALS_MEAN = ("Goals, mean over seeds", 1.8, 4.2, "2.99 (2024/25, mid-season)", PL_TACTICS)


def measure(m: Match, minutes: float = 90) -> dict:
    ev = m.events
    c = Counter(e["type"] for e in ev)
    sp = Counter(e["kind"] for e in ev if e["type"] == "set_piece")
    passes = [e for e in ev if e["type"] == "pass" and e["kind"] != "throw_in"]
    done = [e for e in passes if e["outcome"] == "success"]
    shots = [e for e in ev if e["type"] == "shot"]
    frames = m.frames
    held = Counter(f["possessor"][0] for f in frames if f["possessor"])
    n = len(frames[0]["players"])
    dist = [0.0] * n
    top = 0.0
    sprints = [0] * n
    fast = [False] * n
    crowded = 0
    ball_step = 0.0
    for a, b in zip(frames, frames[1:], strict=False):
        bx, by = b["ball"]["x"], b["ball"]["y"]
        ball_step = max(ball_step, math.hypot(bx - a["ball"]["x"], by - a["ball"]["y"]))
        near = 0
        for i, (p, q) in enumerate(zip(a["players"], b["players"], strict=True)):
            d = math.hypot(q["x"] - p["x"], q["y"] - p["y"])
            dist[i] += d
            v = d * FPS
            top = max(top, v)
            if v > SPRINT_MS and not fast[i]:
                sprints[i] += 1
            fast[i] = v > SPRINT_MS
            if abs(q["x"] - bx) < 3 and abs(q["y"] - by) < 3 and math.hypot(q["x"] - bx, q["y"] - by) < 3:
                near += 1
        crowded += near >= 3
    outfield = [i for i, p in enumerate(frames[0]["players"]) if p["id"] not in ("h1", "a1")]
    return {
        "goals": m.score["home"] + m.score["away"],
        "shots": len(shots),
        "shots_on_target": sum(1 for e in shots if e["outcome"] in ("on_target", "goal")),
        "ball_in_play": round(m.in_play_s / (minutes * 60), 3),
        "corners": sp["corner"],
        "throw_ins": sp["throw_in"],
        "goal_kicks": sp["goal_kick"],
        "passes": len(passes),
        "pass_completion": round(len(done) / max(1, len(passes)), 3),
        "pass_length_m": round(sum(math.hypot(e["end_x"] - e["x"], e["end_y"] - e["y"]) for e in done)
                               / max(1, len(done)), 1),
        "fouls": c["foul"],
        "tackles": c["tackle"],
        "interceptions": c["interception"],
        "saves": c["save"],
        "home_possession": round(held["h"] / max(1, held["h"] + held["a"]), 3),
        "distance_km": round(sum(dist[i] for i in outfield) / len(outfield) / 1000, 2),
        "top_speed_ms": round(top, 2),
        "max_ball_step_m": round(ball_step, 2),
        "sprints_per_player": round(sum(sprints[i] for i in outfield) / len(outfield), 1),
        "crowded_share": round(crowded / len(frames), 4),
        "clearances": c["clearance"],
        "free_kicks": sp["free_kick"],
        "penalties": sp["penalty"],
    }


def run_seed(seed: int) -> dict:
    return {"seed": seed, **measure(simulate(seed, 90))}


def run(seeds: list[int]) -> list[dict]:
    with ProcessPoolExecutor() as pool:
        return list(pool.map(run_seed, seeds))


def out_of_band(rows: list[dict]) -> list[str]:
    bad = []
    for r in rows:
        for key, (label, lo, hi, _, _) in BANDS.items():
            if not lo <= r[key] <= hi:
                bad.append(f"seed {r['seed']}: {label} = {r[key]} outside [{lo}, {hi}]")
    mean_goals = sum(r["goals"] for r in rows) / len(rows)
    if len(rows) >= 10 and not GOALS_MEAN[1] <= mean_goals <= GOALS_MEAN[2]:
        bad.append(f"mean goals {mean_goals:.2f} outside [{GOALS_MEAN[1]}, {GOALS_MEAN[2]}]")
    return bad


def report(rows: list[dict]) -> str:
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True,
                            cwd=ROOT).stdout.strip()
    seeds = ", ".join(str(r["seed"]) for r in rows)
    lines = [
        "# Simulator realism",
        "",
        "Generated by `uv run python -m ninety.sim.realism`. Do not edit by hand.",
        "",
        f"Commit `{commit}`, {datetime.date.today().isoformat()}, {len(rows)} simulated 90-minute matches "
        f"(seeds {seeds}). Values are per match, both teams together. The band is what every simulated "
        "match must land in (`tests/test_sim.py` checks it on three seeds). A row without a source is a "
        "working band whose real average is still to be cited.",
        "",
        "| Measure | Sim min | Sim mean | Sim max | Band | Real average | Source |",
        "|---|---|---|---|---|---|---|",
    ]

    def row(label, key, lo, hi, real, src):
        vals = [r[key] for r in rows]
        mean = sum(vals) / len(vals)
        fmt = (lambda v: f"{v:.3f}") if hi <= 1 else (lambda v: f"{v:.1f}" if hi < 30 else f"{v:.0f}")
        source = f"[link]({src})" if src else "to cite"
        lines.append(f"| {label} | {fmt(min(vals))} | {fmt(mean)} | {fmt(max(vals))} | {lo} to {hi} | "
                     f"{real or 'to cite'} | {source} |")

    label, lo, hi, real, src = GOALS_MEAN
    row(label, "goals", lo, hi, real, src)
    for key, (label, lo, hi, real, src) in BANDS.items():
        row(label, key, lo, hi, real, src)
    lines += [
        "",
        "Not banded yet, recorded for the vision test set and the renderer:",
        "",
        "| Measure | Sim min | Sim mean | Sim max |",
        "|---|---|---|---|",
    ]
    extra = [("sprints_per_player", f"Sprints above {SPRINT_MS} m/s per outfield player"),
             ("crowded_share", "Share of frames with 3+ players within 3 m of the ball"),
             ("clearances", "Clearances"), ("free_kicks", "Free kicks"), ("penalties", "Penalties")]
    for key, label in extra:
        vals = [r[key] for r in rows]
        lines.append(f"| {label} | {min(vals)} | {sum(vals) / len(vals):.3g} | {max(vals)} |")
    bad = out_of_band(rows)
    lines += ["", "Out of band: " + ("none" if not bad else "; ".join(bad)), ""]
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--seeds", type=int, default=10, help="simulate seeds 1..N")
    ap.add_argument("--no-write", action="store_true")
    args = ap.parse_args()
    rows = run(list(range(1, args.seeds + 1)))
    text = report(rows)
    print(text)
    if not args.no_write:
        out = ROOT / "docs/eval"
        out.mkdir(parents=True, exist_ok=True)
        (out / "sim-realism.md").write_text(text)
        (out / "sim-realism.json").write_text(json.dumps(rows, indent=2) + "\n")


if __name__ == "__main__":
    main()
