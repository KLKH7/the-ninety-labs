"""The phone's "attacking now" layer against the answer key, offline (docs/eval/possession.md).

Grading, so it reads the answer key; nothing on the live path imports it. Two steps, in order:

    uv run python -m ninety.eval.possession_score calibrate --observations <val obs dir> \\
        --truth <render v1>/train --seeds 108,... --out docs/eval/possession-calibration
    uv run python -m ninety.eval.possession_score grade --observations tests/fixtures \\
        --observations docs/eval/attribution --truth runs/test-frozen-cca498c/test \\
        --seeds 900001,... --out docs/eval/possession

`calibrate` sets SHOW and SURE on validation clips only: the lowest confidence at which the team
agreement of what would be drawn reaches SHOW_TARGET and SURE_TARGET (design choices, set before
any test clip was graded, GROUNDING). `grade` then scores the test clips once with them.

The truth at a frame: the team of the latest player the answer key names as the ball's possessor
(carried until the next), and the true ball's third along that team's attacking direction. A
sample is graded only where the truth names a team. Samples within one true possession spell
are not independent, so the intervals count spells, not samples (Wilson), with a bootstrap over
clips beside them.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import math
import random
from pathlib import Path

from ninety.eval.event_score import git_commit
from ninety.intel import possession as ps
from ninety.vision import track as tr

COMMAND = "uv run python -m ninety.eval.possession_score"
SHOW_TARGET = 0.75  # design (GROUNDING): below it, the phone shows nothing
SURE_TARGET = 0.90  # design (GROUNDING): below it, the phone says "likely"
Z = 1.96  # 95 %
BOOTSTRAP = 2000
SEED = 7  # the bootstrap's random draws, fixed so the report is byte for byte


def truth_samples(frames_file: Path, phases: list[ps.Phase]) -> list[dict | None]:
    """For each phase, the true team in possession and the true ball's third, or None before the
    answer key has named anyone."""
    frames = [json.loads(line) for line in frames_file.read_text().splitlines()]
    by_frame = {f["frame"]: f for f in frames}
    t_frame = {round(f["t"], 2): f["frame"] for f in frames}
    team = None
    holder_at: dict[int, str | None] = {}
    for f in frames:
        if f.get("possessor"):
            team = "home" if f["possessor"].startswith("h") else "away"
        holder_at[f["frame"]] = team
    out = []
    for p in phases:
        frame = t_frame.get(p.t)
        if frame is None or holder_at.get(frame) is None:
            out.append(None)
            continue
        side = holder_at[frame]
        third, _ = ps.third_of(by_frame[frame]["ball"]["x"], side)
        out.append({"team": side, "third": third, "spell": None})
    # Number the true possession spells, the unit the intervals count.
    spell, last = 0, None
    for s in out:
        if s is None:
            last = None
            continue
        if s["team"] != last:
            spell, last = spell + 1, s["team"]
        s["spell"] = spell
    return out


def clip_samples(seed: int, obs_dirs: list[Path], truth_dir: Path) -> list[dict]:
    obs = next((d / f"observations-seed{seed}.jsonl" for d in obs_dirs
                if (d / f"observations-seed{seed}.jsonl").exists()), None)
    if obs is None:
        raise FileNotFoundError(f"no observations for seed {seed} in {[str(d) for d in obs_dirs]}")
    phases = ps.timeline(tr.read_observations(obs))
    truth = truth_samples(truth_dir / f"seed{seed}" / "frames.jsonl", phases)
    return [{"seed": seed, "t": p.t, "team": p.team, "third": p.third, "plainly": p.plainly,
             "confidence": p.confidence, "truth": t} for p, t in zip(phases, truth, strict=True)]


def drawn(samples: list[dict], cut: float) -> list[dict]:
    """The graded samples the phone would draw at this cut-off."""
    return [s for s in samples if s["truth"] is not None and s["team"] is not None and s["confidence"] >= cut]


def agreement(rows: list[dict]) -> float | None:
    return sum(s["team"] == s["truth"]["team"] for s in rows) / len(rows) if rows else None


def lowest_cut(samples: list[dict], target: float) -> float | None:
    """The lowest confidence at which what would be drawn agrees on the team at least `target`."""
    cuts = sorted({s["confidence"] for s in samples if s["team"] is not None and s["confidence"] > 0})
    return next((c for c in cuts if (a := agreement(drawn(samples, c))) is not None and a >= target), None)


def wilson(k: float, n: int) -> list[float] | None:
    if n == 0:
        return None
    p = k / n
    centre = (p + Z * Z / (2 * n)) / (1 + Z * Z / n)
    half = Z * math.sqrt(p * (1 - p) / n + Z * Z / (4 * n * n)) / (1 + Z * Z / n)
    return [round(max(0.0, centre - half), 3), round(min(1.0, centre + half), 3)]


def by_spell(rows: list[dict], right) -> tuple[float, int]:
    """Agreement counted over true possession spells: each spell weighs one, scored by the share
    of its drawn samples that are right."""
    spells: dict[tuple, list[bool]] = {}
    for s in rows:
        spells.setdefault((s["seed"], s["truth"]["spell"]), []).append(right(s))
    return sum(sum(v) / len(v) for v in spells.values()), len(spells)


def bootstrap(rows: list[dict], right) -> list[float] | None:
    seeds = sorted({s["seed"] for s in rows})
    if not seeds:
        return None
    rng = random.Random(SEED)
    per = {seed: [right(s) for s in rows if s["seed"] == seed] for seed in seeds}
    stats = []
    for _ in range(BOOTSTRAP):
        pick = [per[rng.choice(seeds)] for _ in seeds]
        flat = [x for clip in pick for x in clip]
        if flat:
            stats.append(sum(flat) / len(flat))
    stats.sort()
    return [round(stats[int(0.025 * len(stats))], 3), round(stats[int(0.975 * len(stats)) - 1], 3)]


def measure(rows: list[dict], right) -> dict:
    k, n = by_spell(rows, right)
    samples = sum(right(s) for s in rows)
    share = round(samples / len(rows), 3) if rows else None
    return {"samples": len(rows), "right": samples, "agreement": share, "spells": n,
            "by_spell": round(k / n, 3) if n else None, "wilson_95_spells": wilson(k, n),
            "bootstrap_95_clips": bootstrap(rows, right)}


def team_right(s: dict) -> bool:
    return s["team"] == s["truth"]["team"]


def third_right(s: dict) -> bool:
    return team_right(s) and s["third"] == s["truth"]["third"]


def grade(samples: list[dict], show: float | None, sure: float | None) -> dict:
    graded = [s for s in samples if s["truth"] is not None]
    shown = drawn(samples, show) if show is not None else []
    sure_rows = [s for s in shown if sure is not None and s["confidence"] >= sure]
    likely = [s for s in shown if s not in sure_rows]
    attacking = [s for s in sure_rows if s["third"] == "final" and s["plainly"]]
    return {
        "graded_samples": len(graded),
        "shown": len(shown),
        "coverage": round(len(shown) / len(graded), 3) if graded else None,
        "team": {"all shown": measure(shown, team_right), "sure": measure(sure_rows, team_right),
                 "likely": measure(likely, team_right)},
        "third": {"all shown": measure(shown, third_right), "sure": measure(sure_rows, third_right)},
        "attacking": {"shown": len(attacking),
                      "right": sum(third_right(s) and s["truth"]["third"] == "final" for s in attacking)},
        "per_clip": [{"seed": seed, "graded": sum(1 for s in graded if s["seed"] == seed),
                      "shown": sum(1 for s in shown if s["seed"] == seed),
                      "team_right": sum(team_right(s) for s in shown if s["seed"] == seed)}
                     for seed in sorted({s["seed"] for s in samples})],
    }


def bands(samples: list[dict]) -> list[dict]:
    """Team agreement by confidence band: the reliability table."""
    out = []
    for lo in (0.0, 0.2, 0.4, 0.6, 0.8):
        rows = [s for s in samples if s["truth"] is not None and s["team"] is not None
                and lo <= s["confidence"] < lo + 0.2 + (0.001 if lo == 0.8 else 0)]
        out.append({"band": f"{lo:.1f}-{lo + 0.2:.1f}", "samples": len(rows),
                    "team_agreement": round(agreement(rows), 3) if rows else None})
    return out


CUTS = tuple(round(0.1 * i, 1) for i in range(10))  # the curve's cut-offs, reported only


def curve(samples: list[dict]) -> list[dict]:
    """Team agreement of what would be drawn at each cut-off: what the gate is chosen from."""
    out = []
    for cut in CUTS:
        rows = drawn(samples, cut)
        share = None if not rows else round(agreement(rows), 3)
        out.append({"cut": cut, "samples": len(rows), "team_agreement": share})
    return out


def per_clip(samples: list[dict]) -> list[dict]:
    """Each clip's samples with a team, how many name it right, and their confidences."""
    out = []
    for seed in sorted({s["seed"] for s in samples}):
        rows = [s for s in samples if s["seed"] == seed and s["team"] is not None and s["truth"] is not None]
        conf = sorted(s["confidence"] for s in rows)
        out.append({"seed": seed, "with_a_team": len(rows), "team_right": sum(team_right(s) for s in rows),
                    "confidence": [conf[0], conf[-1]] if conf else None})
    return out


def percent(v: float | None) -> str:
    return "n/a" if v is None else f"{v:.0%}"


def calibration_md(body: dict) -> str:
    unset = "**unset** (no cut-off reached its target: the phone shows nothing)"

    def gate(v):
        return f"**{v}**" if v is not None else unset

    lines = [
        "# The possession layer's gate, set on validation clips",
        "",
        f"Generated by `{COMMAND} calibrate` at commit `{body['commit']}`, {body['date']}. Validation seeds",
        f"{', '.join(str(s) for s in body['seeds'])}; one sample per phone frame ({ps.STEP_S} s). The test",
        "clips are graded only after the gate is set, and only with it (`grade`).",
        "",
        f"- SHOW, the lowest cut-off where team agreement reaches {body['show_target']:.0%}:",
        f"  {gate(body['show'])}",
        f"- SURE, where it reaches {body['sure_target']:.0%}: {gate(body['sure'])}",
        "",
        "| Cut-off | Samples drawn | Team agreement |",
        "|---|---|---|",
        *[f"| {c['cut']} | {c['samples']} | {percent(c['team_agreement'])} |" for c in body["curve"]],
        "",
        "| Seed | Samples with a team | Team right | Confidence (lowest, highest) |",
        "|---|---|---|---|",
        *[f"| {c['seed']} | {c['with_a_team']} | {c['team_right']} | {c['confidence'] or 'n/a'} |"
          for c in body["per_clip"]],
        "",
        "Reading it: the side (home or away) is decided once per clip, from kit colour and which kit",
        "stands deepest toward one goal (ninety/vision/track.assign_teams). When that is wrong, every",
        "sample of the clip is wrong, and the third flips with it, since the attacking direction comes",
        "from the side. The side's confidence does not see it: a clip can be wrong throughout at 0.9.",
        "A clip whose camera is never trusted gives no ball and no spells, so it has no samples with a",
        "team. Until the side is decided better and the gate opens, the layer stays off.",
        "",
    ]
    return "\n".join(lines)


def digests(seeds: list[int], obs_dirs: list[Path]) -> dict[str, str]:
    out = {}
    for seed in seeds:
        for d in obs_dirs:
            f = d / f"observations-seed{seed}.jsonl"
            if f.exists():
                out[f.name] = hashlib.sha256(f.read_bytes()).hexdigest()
                break
    return out


def report_md(body: dict) -> str:
    g, cal = body["test"], body["calibration"]
    lines = [
        "# The phone's possession layer, against the answer key",
        "",
        f"Generated by `{COMMAND} grade` at commit `{body['commit']}`, {body['date']}. Offline grading:",
        "the live path (ninety/intel/possession.py) never reads this or the answer key. Test clips",
        f"{', '.join(str(s) for s in body['seeds'])}, one sample per phone frame ({ps.STEP_S} s).",
        "",
        "## The gate, set on validation clips before the test clips were graded",
        "",
        f"SHOW = **{cal['show']}** (the lowest confidence where team agreement reaches {SHOW_TARGET:.0%}),",
        f"SURE = **{cal['sure']}** (where it reaches {SURE_TARGET:.0%}). Both targets are design choices",
        f"(GROUNDING). Validation seeds: {', '.join(str(s) for s in cal['seeds'])}.",
        "",
        "## Test clips",
        "",
        f"Graded samples (the answer key names a team): {g['graded_samples']}. Shown on the phone:",
        f"{g['shown']} ({percent(g['coverage'])}).",
        "",
        "| What is shown | Samples | Team right | Over spells | Wilson 95 % (spells) "
        "| Bootstrap 95 % (clips) |",
        "|---|---|---|---|---|---|",
    ]
    for name, m in (("all shown", g["team"]["all shown"]), ("sure", g["team"]["sure"]),
                    ("likely", g["team"]["likely"])):
        lines.append(f"| team, {name} | {m['samples']} | {percent(m['agreement'])} | {m['by_spell']} of "
                     f"{m['spells']} spells "
                     f"| {m['wilson_95_spells']} | {m['bootstrap_95_clips']} |")
    for name, m in (("all shown", g["third"]["all shown"]), ("sure", g["third"]["sure"])):
        lines.append(f"| team and third, {name} | {m['samples']} | {percent(m['agreement'])} | "
                     f"{m['by_spell']} of {m['spells']} spells | {m['wilson_95_spells']} | "
                     f"{m['bootstrap_95_clips']} |")
    a = g["attacking"]
    lines += [
        "",
        f"\"Attacking\" (sure, and the ball plainly in the final third): shown on {a['shown']} samples, "
        f"right on {a['right']}.",
        "",
        "Per clip:",
        "",
        "| Seed | Graded | Shown | Team right |",
        "|---|---|---|---|",
        *[f"| {c['seed']} | {c['graded']} | {c['shown']} | {c['team_right']} |" for c in g["per_clip"]],
        "",
        "Team agreement by confidence band (test clips, every sample with a team):",
        "",
        "| Confidence | Samples | Team agreement |",
        "|---|---|---|",
        *[f"| {b['band']} | {b['samples']} | {b['team_agreement']} |" for b in body["bands"]],
        "",
        "Read with care: a handful of clips and spells, so the intervals are wide. The side is the",
        "detector's (docs/eval/attribution.md); when it is wrong, the third flips with it, since the",
        "attacking direction comes from the side. A clip whose camera is never trusted gives no ball",
        "and no spells, so nothing of it is shown: that lowers coverage, not agreement.",
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("step", choices=["calibrate", "grade"])
    ap.add_argument("--observations", type=Path, action="append", required=True)
    ap.add_argument("--truth", type=Path, required=True)
    ap.add_argument("--seeds", required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args(argv)
    seeds = [int(s) for s in args.seeds.split(",")]
    samples = [s for seed in seeds for s in clip_samples(seed, args.observations, args.truth)]
    stamp = {"commit": git_commit(), "date": datetime.date.today().isoformat(), "seeds": seeds,
             "observations_sha256": digests(seeds, args.observations)}
    if args.step == "calibrate":
        show, sure = lowest_cut(samples, SHOW_TARGET), lowest_cut(samples, SURE_TARGET)
        body = {**stamp, "show_target": SHOW_TARGET, "sure_target": SURE_TARGET, "show": show, "sure": sure,
                "curve": curve(samples), "per_clip": per_clip(samples),
                "validation": grade(samples, show, sure)}
        args.out.with_suffix(".json").write_text(json.dumps(body, indent=1, allow_nan=False) + "\n")
        args.out.with_suffix(".md").write_text(calibration_md(body))
        print(f"wrote {args.out}.json and .md: show {show}, sure {sure}")
        return
    cal = json.loads(ps.CALIBRATION.read_text())
    body = {**stamp, "calibration": {k: cal[k] for k in ("show", "sure", "seeds", "commit")},
            "test": grade(samples, cal["show"], cal["sure"]), "bands": bands(samples)}
    args.out.with_suffix(".json").write_text(json.dumps(body, indent=1, allow_nan=False) + "\n")
    args.out.with_suffix(".md").write_text(report_md(body))
    print(f"wrote {args.out}.json and .md")


if __name__ == "__main__":
    main()
