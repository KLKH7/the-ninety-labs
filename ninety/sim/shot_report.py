"""Shots by distance and long balls (docs/GROUNDING.md, R3 and R4), judged by the protocol fixed in
docs/EVALUATION.md before any engine change was measured with it: the same 12 seeds every time,
beside the published figures. It also reports what has no published figure (how long balls fail,
how often they are contested, how often a player on the ball shoots and whether the shot was the
option he valued most), to find causes, never to compare. A report, never a gate, and never a
target: no constant is chosen by looking at it (docs/LESSONS.md, lesson 2). It only listens to the
engine's own calls and hands each on unchanged.

    uv run python -m ninety.sim.shot_report     # 12 full matches; writes docs/eval/shots.md
"""

from __future__ import annotations

import argparse
import math
import subprocess
from concurrent.futures import ProcessPoolExecutor
from datetime import date
from pathlib import Path
from statistics import mean, median

from ninety.sim import decisions
from ninety.sim.body import CONTROL_M

ROOT = Path(__file__).resolve().parents[2]
# The protocol (docs/EVALUATION.md, "Shots by distance and long balls"). Fixed before any number
# was measured with it; changing any of these starts a new protocol, it does not tune one.
SEEDS = tuple(range(201, 213))  # 12 matches, never chosen by their result
MINUTES = 90
LONG_BALL_M = 32.0  # Opta: a long ball is a pass of more than 35 yards
BANDS = ((0.0, 11.0), (11.0, 16.5), (16.5, 25.0), (25.0, 32.0), (32.0, math.inf))  # metres from goal
# Published figures, for reading the report only (docs/EVALUATION.md); every one *verify*.
OUTSIDE_SHARE = (0.317, 0.482)  # Premier League, Opta: 2024-25 and 2005-06
OUTSIDE_PER_MATCH = (8.3, 13.3)  # Premier League, Opta: 2024-25 and 2003-04
MEAN_DISTANCE_M = (16.2 * 0.9144, 19.3 * 0.9144)  # Premier League: 16.2 yd (2023-24), 19.3 yd (2006-07)
LONG_COMPLETION = 0.473  # Premier League teams' average, Opta, 2018-19
LONG_SHARE = (0.065, 0.231)  # by team, the same source
KEEP_FRAMES = 500  # frames between clearing the record: the report reads only events


def band_of(d: float) -> int:
    return next(i for i, (lo, hi) in enumerate(BANDS) if lo <= d < hi)


def measure(seed: int, minutes: float = MINUTES) -> dict:
    """One match: every shot (distance, inside the box, outcome), every long ball (completed, how it
    failed, contested at its first touch, nearest opponent to the aim at the kick) and every
    on-ball decision (distance band, chosen kind, the shot's value against the best other)."""
    from ninety.sim.engine import FPS, Engine, goal_x

    e = Engine(seed)
    long_balls: dict[int, dict] = {}  # id(pass event) -> what is known about it
    decided: list[tuple[int, str, float | None, float]] = []
    seen_opts: list = []
    kicked = [0]  # passes struck with the foot (not thrown, not headed)

    kick = e.pass_to

    def pass_to(carrier, tx, ty, lofted, throw=False, *args, **kwargs):
        bx, by = e.ball[0], e.ball[1]
        nearest = min(math.hypot(q.x - tx, q.y - ty) for q in e.players if q.team != carrier.team)
        n = len(e.match.events)
        kick(carrier, tx, ty, lofted, throw, *args, **kwargs)
        struck = [ev for ev in e.match.events[n:] if ev["type"] == "pass"]
        header = kwargs.get("header") is not None or (len(args) >= 3 and args[2] is not None)
        if not struck or throw or header:  # not struck yet (he turns first, then this runs again)
            return
        kicked[0] += 1
        if math.hypot(tx - bx, ty - by) > LONG_BALL_M:
            long_balls[id(struck[-1])] = {"event": struck[-1], "nearest": nearest, "contested": None}

    touched = e.touched

    def on_touch(p, x, y, controls):
        k = e.kicked
        if k is not None and id(k) in long_balls and long_balls[id(k)]["contested"] is None:
            long_balls[id(k)]["contested"] = any(
                q.team != p.team and math.hypot(q.x - e.ball[0], q.y - e.ball[1]) <= CONTROL_M
                for q in e.players)
        return touched(p, x, y, controls)

    e.pass_to, e.touched = pass_to, on_touch

    options, choose = decisions.options, decisions.choose

    def listen_options(scene):
        out = options(scene)
        seen_opts[:] = out
        return out

    def listen_choose(scene, rng, *rest):
        o = choose(scene, rng, *rest)
        if not scene.throw:
            shot = next((x.value for x in seen_opts if x.kind == "shoot"), None)
            best = max((x.value for x in seen_opts if x.kind != "shoot"), default=-math.inf)
            d = math.hypot(scene.goal_x - scene.x, decisions.PITCH_Y / 2 - scene.y)
            decided.append((band_of(d), o.kind, shot, best))
        return o

    decisions.options, decisions.choose = listen_options, listen_choose
    try:
        e.kickoff("home")
        for i in range(int(minutes * 60 * FPS)):
            e.step()
            if i % KEEP_FRAMES == 0:
                e.match.frames.clear()
    finally:
        decisions.options, decisions.choose = options, choose

    shots = []
    for ev in e.match.events:
        if ev["type"] != "shot":
            continue
        gx = goal_x(ev["team"])
        shots.append({"d": math.hypot(gx - ev["x"], decisions.PITCH_Y / 2 - ev["y"]),
                      "inside": decisions.in_box(ev["x"], ev["y"], gx), "outcome": ev.get("outcome")})
    balls = []
    for lb in long_balls.values():
        ev = lb["event"]
        if ev.get("outcome") == "success":
            how = "completed"
        elif ev.get("interceptor"):
            how = "an opponent got to it"
        else:
            how = "no opponent touched it (a touch failed, or it went out)"
        balls.append({"how": how, "contested": lb["contested"], "nearest": lb["nearest"]})
    return {"seed": seed, "shots": shots, "long_balls": balls, "passes": kicked[0], "decided": decided,
            "events": len(e.match.events)}


def pct(x: float) -> str:
    return f"{x * 100:.1f}%"


def report(results: list[dict], commit: str) -> str:
    n = len(results)
    shots = [s for r in results for s in r["shots"]]
    outside = [s for s in shots if not s["inside"]]
    goals = sum(s["outcome"] == "goal" for s in shots)
    share = len(outside) / max(1, len(shots))
    dist = [s["d"] for s in shots]
    lines = [
        "# Shots by distance and long balls (R3, R4)",
        "",
        f"Generated by `uv run python -m ninety.sim.shot_report` on {date.today().isoformat()}, engine "
        f"commit `{commit}`, by the protocol in [EVALUATION.md](../EVALUATION.md#shots-by-distance-and-"
        f"long-balls-r3-r4): seeds {SEEDS[0]} to {SEEDS[-1]} ({n} matches, {MINUTES} minutes each). "
        "Per match, both teams. A report beside published figures, never a target.",
        "",
        "| Measure | Engine | Published (*verify*) |",
        "|---|---|---|",
        f"| shots per match | {len(shots) / n:.1f} | |",
        f"| goals per match | {goals / n:.2f} | |",
        f"| share of shots from outside the box | {pct(share)} | {pct(OUTSIDE_SHARE[0])} to "
        f"{pct(OUTSIDE_SHARE[1])} |",
        f"| shots from outside the box per match | {len(outside) / n:.1f} | {OUTSIDE_PER_MATCH[0]} to "
        f"{OUTSIDE_PER_MATCH[1]} |",
        f"| mean shot distance | {mean(dist):.1f} m (median {median(dist):.1f}) | "
        f"{MEAN_DISTANCE_M[0]:.1f} to {MEAN_DISTANCE_M[1]:.1f} m |" if dist else "| mean shot distance | | |",
    ]
    balls = [b for r in results for b in r["long_balls"]]
    passes = sum(r["passes"] for r in results)
    done = sum(b["how"] == "completed" for b in balls)
    lines += [
        f"| long balls, share of kicked passes | {pct(len(balls) / max(1, passes))} | "
        f"{pct(LONG_SHARE[0])} to {pct(LONG_SHARE[1])} by team |",
        f"| long-ball completion | {pct(done / max(1, len(balls)))} | {pct(LONG_COMPLETION)} |",
        "",
        "## Shots by distance (per match)",
        "",
        "| Distance from goal | Shots | On target | Goals | Goals per shot |",
        "|---|---|---|---|---|",
    ]
    for i, (lo, hi) in enumerate(BANDS):
        b = [s for s in shots if band_of(s["d"]) == i]
        on = sum(s["outcome"] in ("on_target", "goal") for s in b)
        g = sum(s["outcome"] == "goal" for s in b)
        name = f"{lo:g} to {hi:g} m" if hi < math.inf else f"over {lo:g} m"
        lines.append(f"| {name} | {len(b) / n:.1f} | {on / n:.1f} | {g / n:.2f} | "
                     f"{g / len(b) if b else 0:.3f} |")
    lines += ["", "## Long balls: how they ended (not compared)", "",
              "| Outcome | Share |", "|---|---|"]
    for how in ("completed", "an opponent got to it",
                "no opponent touched it (a touch failed, or it went out)"):
        lines.append(f"| {how} | {pct(sum(b['how'] == how for b in balls) / max(1, len(balls)))} |")
    touched = [b for b in balls if b["contested"] is not None]
    near = sorted(b["nearest"] for b in balls)
    lines += [
        "",
        f"Contested at the first touch (an opponent within {CONTROL_M:g} m of the ball): "
        f"{pct(sum(b['contested'] for b in touched) / max(1, len(touched)))} of {len(touched)} long balls "
        "that someone touched. Nearest opponent to where it was aimed, at the kick: median "
        f"{median(near):.1f} m." if near else "",
        "",
        "## On-ball decisions by distance (not compared)",
        "",
        "| Distance from goal | Decisions per match | Shot chosen | Shot was the best-valued option | "
        "Shot chosen when it was not the best |",
        "|---|---|---|---|---|",
    ]
    decided = [d for r in results for d in r["decided"]]
    for i, (lo, hi) in enumerate(BANDS):
        b = [d for d in decided if d[0] == i]
        if not b:
            continue
        offered = [d for d in b if d[2] is not None]
        best = [d for d in offered if d[2] > d[3]]
        worse = [d for d in offered if d[2] <= d[3]]
        name = f"{lo:g} to {hi:g} m" if hi < math.inf else f"over {lo:g} m"
        lines.append(f"| {name} | {len(b) / n:.0f} | {pct(sum(d[1] == 'shoot' for d in b) / len(b))} | "
                     f"{pct(len(best) / max(1, len(offered)))} | "
                     f"{pct(sum(d[1] == 'shoot' for d in worse) / max(1, len(worse)))} |")
    lines += ["", "## By match", "", "| Seed | Shots | Outside the box | Goals | Long balls | Completed |",
              "|---|---|---|---|---|---|"]
    for r in results:
        lb = r["long_balls"]
        lines.append(f"| {r['seed']} | {len(r['shots'])} | {sum(not s['inside'] for s in r['shots'])} | "
                     f"{sum(s['outcome'] == 'goal' for s in r['shots'])} | {len(lb)} | "
                     f"{sum(b['how'] == 'completed' for b in lb)} |")
    return "\n".join(lines) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=Path, default=ROOT / "docs/eval/shots.md")
    ap.add_argument("--workers", type=int, default=4, help="parallel matches (each holds one engine)")
    args = ap.parse_args()
    with ProcessPoolExecutor(args.workers) as pool:
        results = list(pool.map(measure, SEEDS))
    commit = subprocess.run(["git", "describe", "--always", "--dirty"], capture_output=True, text=True,
                            cwd=ROOT).stdout.strip() or "unknown"
    text = report(results, commit)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(text)
    print(text)


if __name__ == "__main__":
    main()
