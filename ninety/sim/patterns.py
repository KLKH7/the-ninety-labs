"""Measure what a simulated match produced, beside published figures. A report, never a gate:
these patterns are held out, so nothing in the engine is tuned to hit them (docs/ENGINE.md,
'Using the research'; docs/GROUNDING.md, R rows).

    uv run python -m ninety.sim.patterns --seeds 7,11,21     # writes docs/eval/sim-patterns.md
"""

from __future__ import annotations

import argparse
import math
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from statistics import mean

from ninety.sim.body import D0
from ninety.sim.engine import FPS, Engine

ROOT = Path(__file__).resolve().parents[2]
HIGH_INTENSITY = 5.5  # m/s, 19.8 km/h: the usual high-intensity running threshold
SPRINT = 7.0  # m/s, about 25 km/h
GROUPS = {"RCB": "centre-back", "LCB": "centre-back", "RB": "full-back", "LB": "full-back",
          "RCM": "central midfield", "CM": "central midfield", "LCM": "central midfield",
          "RW": "winger", "LW": "winger", "ST": "centre-forward"}
# Published comparisons, for reading the report only (sources in docs/GROUNDING.md, R2 and R6).
PUBLISHED_KM = {"centre-back": 9.1, "full-back": 10.1, "central midfield": 10.7, "winger": 9.6,
                "centre-forward": 9.6}
PUBLISHED_TOP = {"centre-back": 7.9, "full-back": 8.1, "central midfield": 7.9, "winger": 8.6,
                 "centre-forward": 8.0}
# One Premier League team's outfield players over 38 matches (GROUNDING R2; Kavanagh et al. 2024),
# for reading the report only. Table 2: 3.140 + 4.689 km with the ball in play (own team, then the
# opponents, in possession) and 2.839 km out of play, in a 95.5-minute match. Table 4: 142.9 and
# 152.7 m a minute in those two phases, which last 21.9 and 30.6 minutes, and 65.4 out of play.
PUBLISHED_IN_PLAY_KM, PUBLISHED_OUT_KM = 3.140 + 4.689, 2.839
PUBLISHED_IN_PLAY_MPM = (142.9 * 21.9 + 152.7 * 30.6) / (21.9 + 30.6)
PUBLISHED_OUT_MPM = 65.4


def run(seed: int, minutes: float) -> tuple[Engine, set[int]]:
    """Play the match exactly as Engine.run does, also noting each frame in which players moved with
    the ball out of play: a restart still to be taken when they moved (they move last in a frame, so
    the frame the ball goes out counts as out, the frame the restart is taken as in play)."""
    engine = Engine(seed)
    engine.kickoff("home")
    dead = set()
    for _ in range(int(minutes * 60 * FPS)):
        engine.step()
        if engine.restart:
            dead.add(engine.frame - 1)
    return engine, dead


def measure(seed: int, minutes: float = 90) -> dict:
    engine, dead = run(seed, minutes)
    out = tally(engine.match, dead, minutes)
    out["seed"] = seed
    # The slow store's share left at the final whistle (P10), averaged over outfield players.
    out["store_left"] = mean(p.physique.ceiling / D0 for p in engine.players if p.role != "GK")
    return out


def tally(m, dead: set[int], minutes: float) -> dict:
    """What the frames show, per outfield player: distance (split by whether the ball was in play
    in the frame moved to), high intensity, sprints, top speed; the late drop; team shape."""
    role = {r["id"]: r["role"] for r in m.roster}
    resets = {e["frame"] for e in m.events if e["type"] == "kickoff"}  # positions reset: not running
    dist = defaultdict(float)
    dist_out = defaultdict(float)  # of which while the ball was out of play
    high = defaultdict(float)
    sprint_m = defaultdict(float)
    sprints = defaultdict(int)
    top = defaultdict(float)
    early_high = late_high = 0.0
    sprinting = defaultdict(bool)
    team_of = {r["id"]: r["team"] for r in m.roster}
    shape = defaultdict(list)  # (in or out of possession) -> [(length, width)]
    for prev, f in zip(m.frames, m.frames[1:], strict=False):
        if f["frame"] in resets or prev["frame"] in resets:
            continue
        before = {p["id"]: p for p in prev["players"]}
        minute = f["t"] / 60
        holder = team_of.get(f.get("possessor"))
        if holder and f["frame"] % 25 == 0:  # once a second is plenty for shape
            for team in ("home", "away"):
                xs = [p["x"] for p in f["players"] if team_of[p["id"]] == team and role[p["id"]] != "GK"]
                ys = [p["y"] for p in f["players"] if team_of[p["id"]] == team and role[p["id"]] != "GK"]
                shape["in" if team == holder else "out"].append((max(xs) - min(xs), max(ys) - min(ys)))
        for p in f["players"]:
            q = before[p["id"]]
            step = math.hypot(p["x"] - q["x"], p["y"] - q["y"])
            if role[p["id"]] == "GK":
                continue
            speed = step * FPS
            dist[p["id"]] += step
            if f["frame"] in dead:
                dist_out[p["id"]] += step
            top[p["id"]] = max(top[p["id"]], speed)
            if speed > HIGH_INTENSITY:
                high[p["id"]] += step
                if minute < 15:
                    early_high += step
                elif minute >= minutes - 15:
                    late_high += step
            if speed > SPRINT:
                sprint_m[p["id"]] += step
                if not sprinting[p["id"]]:
                    sprints[p["id"]] += 1
            sprinting[p["id"]] = speed > SPRINT
    per_group = defaultdict(list)
    for pid, r in role.items():
        if r in GROUPS:
            scale = 90 / minutes
            per_group[GROUPS[r]].append({
                "km": dist[pid] / 1000 * scale, "out_km": dist_out[pid] / 1000 * scale,
                "high_m": high[pid] * scale, "sprint_m": sprint_m[pid] * scale,
                "sprints": sprints[pid] * scale, "top": top[pid],
            })
    late_drop = 1 - late_high / early_high if early_high else None
    team_shape = {k: (mean(v[0] for v in vals), mean(v[1] for v in vals)) for k, vals in shape.items()}
    in_play_min = sum(1 for f in m.frames[1:] if f["frame"] not in dead) / FPS / 60 * 90 / minutes
    return {"groups": dict(per_group), "late_drop": late_drop, "shape": team_shape,
            "early_high": early_high, "late_high": late_high, "in_play_min": in_play_min}


def split_table(results: list[dict]) -> list[str]:
    """Distance and pace per outfield player with the ball in play and out of play (a restart still
    to be taken), beside the published figures. Pace is distance over the minutes in that state."""
    in_play = mean(r["in_play_min"] for r in results)
    out_min = 90 - in_play
    lines = [
        "",
        f"**Ball in play and out of play.** The ball was in play {in_play:.1f} of 90 minutes on average "
        f"({in_play / 90:.0%}; published {(21.9 + 30.6) / 95.5:.0%} of a 95.5-minute match).",
        "",
        "| Position | In play, km | In play, m/min | Out of play, km | Out of play, m/min |",
        "|---|---|---|---|---|",
    ]

    def row(label: str, rows: list[dict]) -> str:
        live = mean(x["km"] - x["out_km"] for x in rows)
        out = mean(x["out_km"] for x in rows)
        return (f"| {label} | {live:.1f} | {live * 1000 / in_play:.0f} | {out:.1f} "
                f"| {out * 1000 / out_min:.0f} |")
    for group in PUBLISHED_KM:
        lines.append(row(group, [x for r in results for x in r["groups"].get(group, [])]))
    lines.append(row("all outfield", [x for r in results for rows in r["groups"].values() for x in rows]))
    lines.append(f"| published (one Premier League team, all outfield) | {PUBLISHED_IN_PLAY_KM:.1f} "
                 f"| {PUBLISHED_IN_PLAY_MPM:.0f} | {PUBLISHED_OUT_KM:.1f} | {PUBLISHED_OUT_MPM:.0f} |")
    return lines


def report(results: list[dict]) -> str:
    lines = [
        "# Simulated running patterns",
        "",
        f"Generated by `uv run python -m ninety.sim.patterns` on seeds "
        f"{', '.join(str(r['seed']) for r in results)}, 90 minutes each, outfield players. "
        "A report beside published figures, never a target: nothing in the engine is tuned to "
        "these numbers.",
        "",
        "| Position | Distance, km | Published, km | High-intensity, m | Sprints | Top speed, m/s "
        "| Published top speed, m/s |",
        "|---|---|---|---|---|---|---|",
    ]
    for group in PUBLISHED_KM:
        rows = [x for r in results for x in r["groups"].get(group, [])]
        lines.append(
            f"| {group} | {mean(x['km'] for x in rows):.1f} | {PUBLISHED_KM[group]} "
            f"| {mean(x['high_m'] for x in rows):.0f} | {mean(x['sprints'] for x in rows):.0f} "
            f"| {mean(x['top'] for x in rows):.1f} | {PUBLISHED_TOP[group]} |"
        )
    lines += split_table(results)
    lines += ["", "| Team shape (outfield) | Length, m | Width, m |", "|---|---|---|"]
    for key, label in (("in", "in possession"), ("out", "out of possession")):
        rows = [r["shape"][key] for r in results if key in r["shape"]]
        if rows:
            lines.append(f"| {label} | {mean(x[0] for x in rows):.0f} | {mean(x[1] for x in rows):.0f} |")
    lines.append("| published (professional teams) | 31 to 46 | 35 to 48 |")
    drops = [r["late_drop"] for r in results if r["late_drop"] is not None]

    def change(d: float) -> str:
        return f"{d * 100:.0f}% lower" if d >= 0 else f"{-d * 100:.0f}% higher"
    lines += [
        "",
        f"**High-intensity running, last 15 minutes against the first 15:** "
        f"{change(mean(drops)) if drops else 'n/a'} (per seed: {', '.join(change(d) for d in drops)}). "
        "Published: about 20 to 45% lower.",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--seeds", default="7,11,21")
    ap.add_argument("--out", type=Path, default=ROOT / "docs/eval/sim-patterns.md")
    args = ap.parse_args()
    seeds = [int(s) for s in args.seeds.split(",")]
    with ProcessPoolExecutor() as pool:
        results = list(pool.map(measure, seeds))
    text = report(results)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(text)
    print(text)


if __name__ == "__main__":
    main()
