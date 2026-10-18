"""The matchup grid (docs/decisions/0002): every style against every style, and the same style at
growing strength gaps, simulated without rendering. Each team's fingerprint is measured from the
events; the report gives means with 95% intervals beside the predictions written before any styled
match was run. A report, never a gate: nothing in the engine is tuned to it.

    uv run ninety-grid --seeds 20 --minutes 90 --workers 4      # writes docs/eval/sim-styles.md and .json

Each match's result is kept in `--cache` (one JSON line per match), so a run can stop and resume,
or be split across machines and merged.
"""

from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict, dataclass
from itertools import combinations_with_replacement
from pathlib import Path
from statistics import mean, stdev

from ninety.sim.engine import simulate
from ninety.sim.fingerprint import match_fingerprints
from ninety.sim.style import PRESETS

ROOT = Path(__file__).resolve().parents[2]
GRID_PRESETS = ("high_press", "possession", "counter_attack", "low_block", "direct")
STRENGTH_GAPS = (0.0, 0.5, 1.0, 1.5)  # in player-quality SDs (A6)
SWEEP_PRESET = "balanced"
FIRST_SEED = 1000  # grid seeds start here, clear of the dataset's seeds (900001+) and the usual 7, 11, 21
# Two-sided 95% t quantiles by degrees of freedom; beyond 30 the normal 1.96 is close enough.
T95 = {1: 12.71, 2: 4.30, 3: 3.18, 4: 2.78, 5: 2.57, 6: 2.45, 7: 2.36, 8: 2.31, 9: 2.26, 10: 2.23,
       11: 2.20, 12: 2.18, 13: 2.16, 14: 2.14, 15: 2.13, 16: 2.12, 17: 2.11, 18: 2.10, 19: 2.09,
       20: 2.09, 21: 2.08, 22: 2.07, 23: 2.07, 24: 2.06, 25: 2.06, 26: 2.06, 27: 2.05, 28: 2.05,
       29: 2.05, 30: 2.04}
MEASURES = ("shots", "goals", "possession", "ppda", "regain_m", "field_tilt", "forward_m_per_pass",
            "long_share", "completion", "fast_attack_shots")


@dataclass(frozen=True)
class Job:
    kind: str  # "style" or "strength"
    seed: int
    home: str
    away: str
    home_strength: float
    away_strength: float
    minutes: float

    @property
    def key(self) -> str:
        return "|".join(str(v) for v in (self.kind, self.seed, self.home, self.away, self.home_strength,
                                         self.away_strength, self.minutes))


def style_jobs(seeds: int, minutes: float) -> list[Job]:
    """Every pairing of the grid presets once (mirror matches included), both at strength 0. Sides
    swap on alternate seeds so neither end decides a pairing."""
    jobs = []
    for a, b in combinations_with_replacement(GRID_PRESETS, 2):
        for i in range(seeds):
            home, away = (a, b) if i % 2 == 0 else (b, a)
            jobs.append(Job("style", FIRST_SEED + i, home, away, 0.0, 0.0, minutes))
    return jobs


def strength_jobs(seeds: int, minutes: float) -> list[Job]:
    """The same style both sides; the stronger side is gap/2 above average and the weaker gap/2
    below, the stronger at home on even seeds."""
    jobs = []
    for gap in STRENGTH_GAPS:
        for i in range(seeds):
            hi, lo = gap / 2, -gap / 2
            hs, aw = (hi, lo) if i % 2 == 0 else (lo, hi)
            jobs.append(Job("strength", FIRST_SEED + i, SWEEP_PRESET, SWEEP_PRESET, hs, aw, minutes))
    return jobs


def run_job(job: Job) -> dict:
    m = simulate(job.seed, job.minutes, strengths={"home": job.home_strength, "away": job.away_strength},
                 styles={"home": PRESETS[job.home], "away": PRESETS[job.away]})
    fingerprint = match_fingerprints(m.events, m.frames, job.minutes)
    return {"job": asdict(job), "key": job.key, "fingerprint": fingerprint}


def load_cache(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    return {r["key"]: r for r in (json.loads(line) for line in path.read_text().splitlines() if line)}


def run(jobs: list[Job], cache: Path, workers: int) -> list[dict]:
    """Run every job not already in the cache, appending each result as it finishes."""
    done = load_cache(cache)
    todo = [j for j in jobs if j.key not in done]
    cache.parent.mkdir(parents=True, exist_ok=True)
    if todo:
        with ProcessPoolExecutor(workers) as pool, open(cache, "a") as out:
            for result in pool.map(run_job, todo):
                out.write(json.dumps(result) + "\n")
                out.flush()
                done[result["key"]] = result
    return [done[j.key] for j in jobs]


def interval(values: list[float]) -> tuple[float, float]:
    """Mean and the half-width of its 95% interval (t for small samples). Infinite and missing values
    (a team that made no defensive action has no PPDA) are left out."""
    vals = [v for v in values if math.isfinite(v)]
    if not vals:
        return math.nan, math.nan
    if len(vals) < 2:
        return vals[0], math.nan
    t = T95.get(len(vals) - 1, 1.96)
    return mean(vals), t * stdev(vals) / math.sqrt(len(vals))


def by_style(results: list[dict]) -> dict[tuple[str, str], dict[str, list[float]]]:
    """For each (style, opponent style), every measure of that style across its matches."""
    out: dict[tuple[str, str], dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for r in results:
        job = r["job"]
        if job["kind"] != "style":
            continue
        for team, opp in (("home", "away"), ("away", "home")):
            fp = r["fingerprint"][team]
            cell = out[(job[team], job[opp])]
            for k in MEASURES:
                cell[k].append(fp[k])
            cell["goals_against"].append(r["fingerprint"][opp]["goals"])
            cell["shots_against"].append(r["fingerprint"][opp]["shots"])
    return out


def pair_totals(results: list[dict]) -> dict[tuple[str, str], dict[str, list[float]]]:
    """For each unordered pairing, both teams' shots and goals per match."""
    out: dict[tuple[str, str], dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for r in results:
        job = r["job"]
        if job["kind"] != "style":
            continue
        pair = tuple(sorted((job["home"], job["away"])))
        fp = r["fingerprint"]
        out[pair]["shots"].append(fp["home"]["shots"] + fp["away"]["shots"])
        out[pair]["goals"].append(fp["home"]["goals"] + fp["away"]["goals"])
        turnovers = [fp[t]["regain_m"] for t in ("home", "away")]
        out[pair]["high_regains"].append(sum(1 for v in turnovers if math.isfinite(v) and v >= 70.0))
    return out


def strength_table(results: list[dict]) -> dict[float, dict[str, int]]:
    """Wins, draws and losses for the stronger side at each gap (at gap 0, for the home side)."""
    out: dict[float, dict[str, int]] = defaultdict(lambda: {"win": 0, "draw": 0, "loss": 0})
    for r in results:
        job = r["job"]
        if job["kind"] != "strength":
            continue
        gap = round(abs(job["home_strength"] - job["away_strength"]), 3)
        strong = "home" if job["home_strength"] >= job["away_strength"] else "away"
        weak = "away" if strong == "home" else "home"
        g = r["fingerprint"][strong]["goals"] - r["fingerprint"][weak]["goals"]
        out[gap]["win" if g > 0 else "draw" if g == 0 else "loss"] += 1
    return out


def fmt(values: list[float], pct: bool = False, digits: int = 1) -> str:
    m, h = interval(values)
    if math.isnan(m):
        return "n/a"
    if pct:
        return f"{m:.0%} ± {h:.0%}" if math.isfinite(h) else f"{m:.0%}"
    return f"{m:.{digits}f} ± {h:.{digits}f}" if math.isfinite(h) else f"{m:.{digits}f}"


def verdict(lead: float, half_a: float, half_b: float) -> str:
    """A directional prediction against two means with 95% intervals: `lead` is how far the
    predicted side is ahead. When the intervals overlap the direction is reported as within noise."""
    if not math.isfinite(lead):
        return "n/a"
    clear = math.isfinite(half_a) and math.isfinite(half_b) and abs(lead) > half_a + half_b
    if lead > 0:
        return "agrees" if clear else "agrees, within noise"
    return "disagrees" if clear else "disagrees, within noise"


def predictions(styles: dict, pairs: dict, strength: dict) -> list[tuple[str, str, str]]:
    """The directional predictions of decision 0002 that the grid can check, with what was measured.
    Written before any styled match was run; reported whichever way they come out."""
    rows = []

    def overall(style: str, measure: str) -> list[float]:
        return [v for (s, _), cell in styles.items() if s == style for v in cell[measure]]

    gaps = sorted(strength)
    if gaps:
        share = [strength[g]["win"] / max(1, sum(strength[g].values())) for g in gaps]
        rising = all(b >= a for a, b in zip(share, share[1:], strict=False))
        top = strength[gaps[-1]]
        by_gap = ", ".join(f"{g}: {s:.0%}" for g, s in zip(gaps, share, strict=False))
        rows.append(("H1 the stronger side wins more often as the gap grows; the weaker still wins some",
                     f"stronger side's win share by gap {by_gap}; "
                     f"weaker side won {top['loss']} of {sum(top.values())} at the largest gap",
                     "agrees" if rising and top["loss"] > 0 else "disagrees"))
    for hid, a, b, measure, higher, text in (
        ("H2", "high_press", "low_block", "ppda", False, "high press has lower PPDA than low block"),
        ("H2", "high_press", "low_block", "regain_m", True, "high press wins the ball further from its goal"),
        ("H3", "possession", "direct", "possession", True, "possession has more of the ball than direct"),
    ):
        (ma, ha), (mb, hb) = interval(overall(a, measure)), interval(overall(b, measure))
        rows.append((f"{hid} {text}", f"{ma:.2f} ± {ha:.2f} vs {mb:.2f} ± {hb:.2f}",
                     verdict(ma - mb if higher else mb - ma, ha, hb)))
    if pairs:
        fewest = min(pairs, key=lambda p: mean(pairs[p]["shots"]))
        rows.append(("H6 low block v low block has the fewest shots of any pairing",
                     f"fewest: {fewest[0]} v {fewest[1]} ({mean(pairs[fewest]['shots']):.1f} a match)",
                     "agrees" if fewest == ("low_block", "low_block") else "disagrees"))
        most = max(pairs, key=lambda p: mean(pairs[p]["high_regains"]))
        rows.append(("H7 high press v high press has the most turnovers high up the pitch",
                     f"most: {most[0]} v {most[1]}",
                     "agrees" if most == ("high_press", "high_press") else "disagrees"))
        cc = pairs.get(("counter_attack", "counter_attack"))
        if cc:
            rows.append(("H8 counter-attack v counter-attack: no prediction",
                         f"{mean(cc['goals']):.2f} goals and {mean(cc['shots']):.1f} shots a match",
                         "reported"))
    for hid in ("H4", "H5", "H9"):
        rows.append((hid, "not measured by this grid yet", "n/a"))
    return rows


def report(results: list[dict], seeds: int, minutes: float) -> tuple[str, dict]:
    styles, pairs, strength = by_style(results), pair_totals(results), strength_table(results)
    lines = [
        "# Style matchup grid",
        "",
        f"Generated by `uv run ninety-grid --seeds {seeds} --minutes {minutes:g}`: {len(results)} matches, "
        "simulation only. Each style's measures are its mean over its matches with a 95% interval. "
        "Predictions are from [decision 0002](../decisions/0002-styles-and-matchups.md), written before any "
        "styled match was run. A report, never a gate: nothing in the engine is tuned to it.",
        "",
        "**Read with care:** the engine's shots and goals per match are not yet in the published range "
        "(GROUNDING.md R4), so differences in goals between styles are not a finding.",
        "",
        "## Predictions",
        "",
        "| Prediction | Measured | Result |",
        "|---|---|---|",
    ]
    lines += [f"| {p} | {m} | {r} |" for p, m, r in predictions(styles, pairs, strength)]
    lines += ["", "## Each style against each opponent", "",
              "| Style | Opponent | Possession | PPDA | Ball won, m from own goal | Field tilt | "
              "Forward m per pass | Passes 32 m+ | Shots | Shots against | Goals | Fast-attack shots |",
              "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for (s, o), cell in sorted(styles.items()):
        lines.append(f"| {s} | {o} | {fmt(cell['possession'], pct=True)} | {fmt(cell['ppda'])} | "
                     f"{fmt(cell['regain_m'])} | {fmt(cell['field_tilt'], pct=True)} | "
                     f"{fmt(cell['forward_m_per_pass'])} | {fmt(cell['long_share'], pct=True)} | "
                     f"{fmt(cell['shots'])} | {fmt(cell['shots_against'])} | "
                     f"{fmt(cell['goals'], digits=2)} | {fmt(cell['fast_attack_shots'])} |")
    lines += ["", "## Each pairing", "",
              "| Pairing | Matches | Shots a match | Goals a match |", "|---|---|---|---|"]
    for p, cell in sorted(pairs.items()):
        lines.append(f"| {p[0]} v {p[1]} | {len(cell['shots'])} | {fmt(cell['shots'])} | "
                     f"{fmt(cell['goals'], digits=2)} |")
    lines += ["", f"## Strength ({SWEEP_PRESET} both sides)", "",
              "| Gap, SD | Matches | Stronger side won | Drawn | Weaker side won |", "|---|---|---|---|---|"]
    for g in sorted(strength):
        w = strength[g]
        lines.append(f"| {g} | {sum(w.values())} | {w['win']} | {w['draw']} | {w['loss']} |")
    def means(cells: dict) -> dict:
        return {"|".join(key): {k: interval(v)[0] for k, v in cell.items()} for key, cell in cells.items()}

    data = {
        "seeds": seeds, "minutes": minutes, "matches": len(results),
        "styles": means(styles), "pairs": means(pairs),
        "strength": {str(g): w for g, w in strength.items()},
        "predictions": [{"prediction": p, "measured": m, "result": r}
                        for p, m, r in predictions(styles, pairs, strength)],
    }
    return "\n".join(lines) + "\n", data


def main() -> None:
    ap = argparse.ArgumentParser(description="Simulate the style matchup grid; report the fingerprints.")
    ap.add_argument("--seeds", type=int, default=20, help="matches per pairing and per strength gap")
    ap.add_argument("--minutes", type=float, default=90)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--cache", type=Path, default=ROOT / "runs" / "grid" / "results.jsonl")
    ap.add_argument("--out", type=Path, default=ROOT / "docs" / "eval" / "sim-styles.md")
    args = ap.parse_args()
    jobs = style_jobs(args.seeds, args.minutes) + strength_jobs(args.seeds, args.minutes)
    results = run(jobs, args.cache, args.workers)
    text, data = report(results, args.seeds, args.minutes)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(text)
    args.out.with_suffix(".json").write_text(json.dumps(data, indent=1, default=float) + "\n")
    print(f"{len(results)} matches; wrote {args.out} and {args.out.with_suffix('.json')}")


if __name__ == "__main__":
    main()
