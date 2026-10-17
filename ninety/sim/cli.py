import argparse
import json
import math
from collections import Counter
from pathlib import Path

from ninety.sim.engine import FPS, simulate
from ninety.sim.style import PRESETS


def main() -> None:
    ap = argparse.ArgumentParser(description="Simulate a synthetic match and write its ground-truth data.")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--minutes", type=float, default=90)
    ap.add_argument("--out", type=Path, required=True)
    for team in ("home", "away"):
        ap.add_argument(f"--{team}-style", choices=sorted(PRESETS), default=None,
                        help=f"the {team} team's style preset (docs/decisions/0002-styles-and-matchups.md); "
                             "else a block is drawn for it (T2, T3)")
        ap.add_argument(f"--{team}-strength", type=float, default=None,
                        help=f"the {team} team's strength in player-quality SDs (0 is average); else drawn")
    ap.add_argument("--scenario", choices=("corner",), default=None,
                    help="corner: an attack from a moment open play reaches that play turns into a "
                         "corner, run on for --minutes after the corner is given (targeted data)")
    args = ap.parse_args()
    for team in ("home", "away"):
        s = getattr(args, f"{team}_strength")
        if s is not None and not math.isfinite(s):
            ap.error(f"--{team}-strength must be a finite number")

    strengths = {team: s for team in ("home", "away") if (s := getattr(args, f"{team}_strength")) is not None}
    styles = {team: PRESETS[name] for team in ("home", "away") if (name := getattr(args, f"{team}_style"))}
    match = simulate(args.seed, args.minutes, strengths, styles, args.scenario)
    args.out.mkdir(parents=True, exist_ok=True)
    with open(args.out / "events.jsonl", "w") as f:
        for ev in match.events:
            f.write(json.dumps(ev) + "\n")
    with open(args.out / "frames.jsonl", "w") as f:
        for fr in match.frames:
            f.write(json.dumps(fr) + "\n")
    meta = {"seed": args.seed, "engine_seed": match.seed, "base_seed": match.base_seed,
            "opening_t": match.opening_t, "minutes": args.minutes, "scenario": args.scenario,
            "fps": FPS, "score": match.score, "teams": match.teams, "roster": match.roster,
            "counts": Counter(e["type"] for e in match.events)}
    (args.out / "meta.json").write_text(json.dumps(meta, indent=2))
    print(json.dumps(meta))


if __name__ == "__main__":
    main()
