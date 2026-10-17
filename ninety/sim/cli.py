import argparse
import json
from collections import Counter
from pathlib import Path

from ninety.sim.engine import FPS, simulate


def main() -> None:
    ap = argparse.ArgumentParser(description="Simulate a synthetic match and write its ground-truth data.")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--minutes", type=float, default=90)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--scenario", choices=("corner",), default=None,
                    help="corner: an attack from a moment open play reaches that play turns into a "
                         "corner, run on for --minutes after the corner is given (targeted data)")
    args = ap.parse_args()

    match = simulate(args.seed, args.minutes, args.scenario)
    args.out.mkdir(parents=True, exist_ok=True)
    with open(args.out / "events.jsonl", "w") as f:
        for ev in match.events:
            f.write(json.dumps(ev) + "\n")
    with open(args.out / "frames.jsonl", "w") as f:
        for fr in match.frames:
            f.write(json.dumps(fr) + "\n")
    meta = {"seed": args.seed, "engine_seed": match.seed, "base_seed": match.base_seed,
            "opening_t": match.opening_t, "minutes": args.minutes, "scenario": args.scenario,
            "fps": FPS,
            "score": match.score,
            "roster": match.roster, "counts": Counter(e["type"] for e in match.events)}
    (args.out / "meta.json").write_text(json.dumps(meta, indent=2))
    print(json.dumps(meta))


if __name__ == "__main__":
    main()
