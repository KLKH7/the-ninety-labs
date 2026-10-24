"""The possession set's clips (docs/eval/possession-set.md), from its matches' answer keys.

    uv run python -m ninety.eval.possession_set --sims <dir of seed<N>/{events.jsonl,meta.json}> \\
        --out docs/eval/possession-set.json

Each match is cut into consecutive WINDOW_S windows from its first frame, ending by the set-piece
set's LAST_END_S. Each window scores its possession changes, interceptions and tackles; the PER_SEED
highest-scoring windows of each match are kept (ties: more interceptions and tackles, then earlier).
Nothing is chosen by hand. The output lists each clip's split, seed, start and length, and the
totals per split; which clip holds what is not written.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ninety.eval.set_piece_set import LAST_END_S, MINUTES, RENDER_COMMIT, TEST, VALIDATION, load_match
from ninety.sim.engine import FPS

NAME = "possession-set"
WINDOW_S = 10.0  # as every dataset clip
PER_SEED = 2  # the render budget (design): 60 test windows, 30 validation
TYPES = ("possession_change", "interception", "tackle")


def windows(events: list[dict]) -> list[dict]:
    """[{start, seconds, counts}] for every grid window ending by LAST_END_S, in time order."""
    n = round(WINDOW_S * FPS)
    out = [{"first": f, "counts": dict.fromkeys(TYPES, 0)}
           for f in range(0, round(LAST_END_S * FPS) - n + 1, n)]
    for e in events:
        if e["type"] in TYPES and e["frame"] // n < len(out):
            out[e["frame"] // n]["counts"][e["type"]] += 1
    return [{"start": round(w["first"] / FPS, 2), "seconds": WINDOW_S, "counts": w["counts"]} for w in out]


def best(ws: list[dict]) -> list[dict]:
    """The PER_SEED highest-scoring windows, in time order."""
    def rank(i: int) -> tuple:
        c = ws[i]["counts"]
        return (-sum(c.values()), -(c["interception"] + c["tackle"]), i)

    return [ws[i] for i in sorted(sorted(range(len(ws)), key=rank)[:PER_SEED])]


def build(sims: Path) -> dict:
    clips, totals = [], {}
    for split, seeds in (("validation", VALIDATION), ("test", TEST)):
        totals[split] = dict.fromkeys(TYPES, 0)
        for s in seeds:
            events, match_s = load_match(sims / f"seed{s}")
            if match_s < MINUTES * 60:
                raise ValueError(f"seed {s} was simulated for {match_s / 60} minutes, not {MINUTES}")
            for w in best(windows(events)):
                clips.append({"split": split, "seed": s, "start": w["start"], "seconds": w["seconds"]})
                for t in TYPES:
                    totals[split][t] += w["counts"][t]
    render = {"views": None, "set": ["stadium=broadcast", "dead_ball_cut=false"]}
    count = {k: sum(1 for c in clips if c["split"] == k) for k in ("validation", "test")}
    return {"name": NAME, "render_commit": RENDER_COMMIT, "render": render, "minutes": MINUTES,
            "last_end_s": LAST_END_S, "window_s": WINDOW_S, "per_seed": PER_SEED,
            "splits": {"validation": list(VALIDATION), "test": list(TEST)},
            "clips": clips, "count": count, "events": totals,
            "seconds": round(sum(c["seconds"] for c in clips), 2)}


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="The possession set's clips, from its matches' answer keys.")
    ap.add_argument("--sims", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args(argv)
    m = build(a.sims)
    a.out.write_text(json.dumps(m, indent=1) + "\n")
    print(json.dumps({"count": m["count"], "events": m["events"], "seconds": m["seconds"]}))


if __name__ == "__main__":
    main()
