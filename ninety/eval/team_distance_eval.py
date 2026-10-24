"""How far the phone's team distance is from the truth: graded on simulated, spoiled tracks.

The answer key is read here only to grade (AGENTS.md). Each team's distance is computed on the
simulator's own positions (the truth, one step a second) and on the same match spoiled as the
tracker spoils it (ninety/eval/roles_eval.spoil: fragmented tracks, a persistent position error,
players missing, identity swaps), by the same code (ninety/intel/team_stats.distance), per five
minutes. Reported: the tracked distance over the truth, and over the truth scaled by coverage
(what the footage could show), median and range over the bins.

    uv run python -m ninety.eval.team_distance_eval runs/f7-65247ba3 runs/f11-65247ba3 runs/f21-65247ba3 \\
        runs/f8076-65247ba3 --minutes 30 --calibrate --out docs/eval/team-distance.json
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
from pathlib import Path

from ninety.eval import roles_eval
from ninety.intel import team_stats

# The step is chosen before any held-out grading (pre-registered, Oct 24): the smallest of CANDIDATES
# whose noise share on the development matches is at most NOISE_SHARE. The noise share is how far the
# tracked position's error moves over a step, as a share of how far the players truly move: the
# part of each step that is the tracker's error walking, not running. 5% is *design*, fixed before
# any share was seen.
CANDIDATES_S = (1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 8.0, 10.0)
NOISE_SHARE = 0.05
SWAP_M = 4.0  # *design*: an error past this is a track following another player (a swap), not noise


def noise_share(run: Path, minutes: float, step_s: float, fragment_s: float, seed: int = 1) -> dict:
    """Over every step of every track: the error's movement over the true movement, summed."""
    frames, _ = roles_eval.load(run, step=25)
    frames = [f for f in frames if f["t"] <= minutes * 60]
    spoilt, owner = roles_eval.spoil(frames, seed, fragment_s)
    every = round(step_s)
    err_m = true_m = 0.0
    last: dict[str, tuple] = {}
    for k, (f, g) in enumerate(zip(frames, spoilt, strict=True)):
        if k % every:
            continue
        truth = {p["id"]: (p["x"], p["y"]) for p in f["players"]}
        for p in g["players"]:
            tx, ty = truth[owner[p["id"]]]
            ex, ey = p["x"] - tx, p["y"] - ty
            prev = last.get(p["id"])
            last[p["id"]] = (k, tx, ty, ex, ey)
            if prev is None or k - prev[0] != every:
                continue
            if max(abs(ex), abs(ey), abs(prev[3]), abs(prev[4])) > SWAP_M:
                continue
            dex, dey, dtx, dty = ex - prev[3], ey - prev[4], tx - prev[1], ty - prev[2]
            err_m += math.sqrt(dex * dex + dey * dey)  # sqrt is exact in IEEE: the same on every machine
            true_m += math.sqrt(dtx * dtx + dty * dty)
    return {"step_s": step_s, "error_m": round(err_m), "true_m": round(true_m),
            "share": round(err_m / true_m, 4) if true_m else None}


def pick(rows: list[dict]) -> float | None:
    """The rule: the smallest step whose noise share is at most NOISE_SHARE; None when none is."""
    return next((r["step_s"] for r in rows if r["share"] is not None and r["share"] <= NOISE_SHARE), None)


def label_pct(cases: list[dict]) -> int:
    """The phone's label: the worst a five-minute bin read against the truth, any case, rounded up."""
    worst = max(max(abs(c["ratio"]["min"] - 1), abs(c["ratio"]["max"] - 1)) for c in cases)
    return math.ceil(round(worst * 100, 6))


def step_lines(path: Path) -> list[str]:
    """What the pre-registered step rule found on the development matches, when it was run."""
    if not path.exists():
        return []
    got = json.loads(path.read_text())
    shares = ", ".join(f"{r['step_s']:g} s {r['share']:.1%}" for r in got["shares"])
    found = "chose no step, so the stat stays at one second"
    if got["chosen_s"]:
        found = f"chose {got['chosen_s']:g} s"
    return [
        "",
        f"Step: the rule fixed before any share was seen ({got['rule']}, on {', '.join(got['runs'])}) "
        f"{found}. "
        f"Noise share by step: {shares}. The error is a walk that a longer step does not average away.",
    ]


def choose(runs: list[Path], minutes: float, fragment_s: float = 30.0) -> dict:
    """The pre-registered rule on the development matches: the smallest step with a small noise share."""
    rows = []
    for step_s in CANDIDATES_S:
        got = [noise_share(r, minutes, step_s, fragment_s) for r in runs]
        err, true = sum(g["error_m"] for g in got), sum(g["true_m"] for g in got)
        rows.append({"step_s": step_s, "share": round(err / true, 4) if true else None})
    chosen = pick(rows)
    return {"runs": [str(r) for r in runs], "rule": f"smallest step with noise share <= {NOISE_SHARE}",
            "shares": rows, "chosen_s": chosen}


def grade(
    run: Path, minutes: float, missing: float, fragment_s: float, seed: int = 1, step_s: float | None = None
) -> dict:
    step_s = team_stats.STEP_S if step_s is None else step_s
    frames, _ = roles_eval.load(run, step=25)  # spoiled at one second; the stat samples at its own step
    frames = [f for f in frames if f["t"] <= minutes * 60]
    old = roles_eval.MISSING
    roles_eval.MISSING = missing
    try:
        spoilt, _ = roles_eval.spoil(frames, seed, fragment_s)
    finally:
        roles_eval.MISSING = old
    rows = []
    for b0 in range(0, int(minutes), team_stats.BIN_MIN):
        lo, hi = b0 * 60, (b0 + team_stats.BIN_MIN) * 60
        true = [f for f in frames if lo <= f["t"] < hi]
        seen = [f for f in spoilt if lo <= f["t"] < hi]
        for team in ("home", "away"):
            t = team_stats.distance(true, team, step_s)
            s = team_stats.distance(seen, team, step_s)
            rows.append(
                {
                    "bin": b0 // team_stats.BIN_MIN,
                    "team": team,
                    "true_m": round(t["m"]),
                    "tracked_m": round(s["m"]),
                    "coverage": round(s["coverage"], 3),
                    "jumps": s["jumps"],
                    "ratio": round(s["m"] / t["m"], 3) if t["m"] else None,
                    "ratio_shown": round(s["m"] / (t["m"] * s["coverage"]), 3)
                    if t["m"] and s["coverage"]
                    else None,
                }
            )

    def spread(key):
        v = [r[key] for r in rows if r[key] is not None]
        return {"median": round(statistics.median(v), 3), "min": min(v), "max": max(v)} if v else None

    return {
        "missing": missing,
        "fragment_s": fragment_s,
        "ratio": spread("ratio"),
        "ratio_shown": spread("ratio_shown"),
        "rows": rows,
    }


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("runs", type=Path, nargs="+")
    ap.add_argument("--minutes", type=float, default=30.0)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--choose", type=Path, nargs="+", help="dev runs: apply the step rule and stop")
    ap.add_argument("--calibrate", action="store_true", help="write the phone label: worst of all runs")
    args = ap.parse_args(argv)
    if args.choose:
        got = choose(args.choose, args.minutes)
        args.out.write_text(json.dumps(got, indent=1) + "\n")
        print(json.dumps(got))
        return
    report = {
        "minutes": args.minutes,
        "step_s": team_stats.STEP_S,
        "max_step_mps": team_stats.MAX_STEP_MPS,
        "runs": {},
    }
    for run in args.runs:
        cases = []
        for missing in (0.0, 0.05):
            for fragment_s in (30.0, 10.0):
                g = grade(run, args.minutes, missing, fragment_s)
                cases.append(g)
                print(run.name, missing, fragment_s, g["ratio"], g["ratio_shown"])
        report["runs"][run.name] = {"cases": cases, "within_pct": label_pct(cases)}
    # The phone's label: the worst a five-minute bin read against the truth, over every case of every
    # match graded, rounded up to a whole percent.
    report["within_pct"] = max(r["within_pct"] for r in report["runs"].values())
    args.out.write_text(json.dumps(report, indent=1) + "\n")
    if args.calibrate:
        team_stats.CALIBRATION.write_text(
            json.dumps(
                {"within_pct": report["within_pct"], "runs": list(report["runs"]), "source": str(args.out)},
                indent=1,
            )
            + "\n"
        )
    args.out.with_suffix(".md").write_text(markdown(report, args) + "\n")


def markdown(report: dict, args) -> str:
    names = " ".join(f"runs/{n}" for n in report["runs"])
    lines = [
        "# Team distance on the phone, graded against the truth",
        "",
        f"Generated by `uv run python -m ninety.eval.team_distance_eval {names} --minutes "
        f"{report['minutes']:g}`: each simulated match spoiled as the tracker spoils it, one step a second, "
        f"jumps past {team_stats.MAX_STEP_MPS:g} m/s skipped, graded per five minutes and team.",
    ]
    for name, r in report["runs"].items():
        lines += [
            "",
            f"**{name}** (worst bin ±{r['within_pct']}%)",
            "",
            "| Missing a frame | Fragment mean | Tracked / true, median (range) "
            "| Tracked / (true × coverage) |",
            "|---|---|---|---|",
        ]
        for c in r["cases"]:
            q, w = c["ratio"], c["ratio_shown"]
            lines.append(
                f"| {c['missing']:.0%} | {c['fragment_s']:g} s | {q['median']} ({q['min']} to {q['max']}) | "
                f"{w['median']} ({w['min']} to {w['max']}) |"
            )
    full = [c["ratio"] for r in report["runs"].values() for c in r["cases"] if c["missing"] == 0]
    lo, hi = min(q["min"] for q in full), max(q["max"] for q in full)
    lines += [
        "",
        f"The phone labels the distance ±{report['within_pct']}%: the worst five-minute bin of any case of "
        "any match above, rounded up.",
        *step_lines(args.out.with_name("team-distance-step.json")),
        "",
        f"Reading: with every player tracked, the distance reads {lo} to {hi} times the truth per five "
        "minutes. The persistent position error walks, and its walk adds distance (more where players "
        "run less); a track broken often loses its first and last step. A player missing from frames "
        'takes his distance with him, so the phone shows the tracked distance with its coverage, "from '
        "the footage shown\", and does not scale it up. The demo's own tracker is to be graded the same "
        "way against its truth before the number is relied on.",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    main()
