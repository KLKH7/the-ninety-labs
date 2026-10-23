"""The shot-outcome set's windows (docs/eval/shot-outcome-set.md), from the full matches' events.

    uv run python -m ninety.eval.shot_outcome_set --sims <dir of seed<N>/events.jsonl> \\
        --out docs/eval/shot-outcome-set.json

Every shot of every listed seed gets a window from BEFORE_S before it to AFTER_S after it; windows
that overlap are joined. Nothing is chosen by hand and no shot is left out. Run on matches
simulated at the render commit, so the windows are the matches the renderer will draw.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ninety.sim.engine import FPS

NAME = "shot-outcome-set"
RENDER_COMMIT = "6ea8e37aa7510da6e876f2bbe09d415b7eb5d42f"
VALIDATION = tuple(range(910001, 910009))
TEST = tuple(range(910009, 910017))
# The plan's offsets: 3 s of the build-up, so the strike and its spell are seen, and 7 s after it,
# enough for the ball to reach the goal and rest in the net, or for the keeper to hold it and the
# play to go on (design). A 10 s window, as every clip of the datasets.
BEFORE_S = 3.0
AFTER_S = 7.0


def windows(events: list[dict], match_s: float) -> list[dict]:
    """[{start, seconds, shots}] in match seconds, on whole frames, joined where they overlap."""
    out: list[dict] = []
    for e in sorted((e for e in events if e["type"] == "shot"), key=lambda e: e["t"]):
        start = max(0.0, round(e["t"] * FPS - BEFORE_S * FPS) / FPS)
        end = min(match_s, round(e["t"] * FPS + AFTER_S * FPS) / FPS)
        if out and start <= out[-1]["start"] + out[-1]["seconds"]:
            out[-1]["seconds"] = round(end - out[-1]["start"], 2)
            out[-1]["shots"].append(e["t"])
        else:
            out.append({"start": round(start, 2), "seconds": round(end - start, 2), "shots": [e["t"]]})
    return out


def build(sims: Path) -> dict:
    clips = []
    for split, seeds in (("validation", VALIDATION), ("test", TEST)):
        for s in seeds:
            lines = (sims / f"seed{s}" / "events.jsonl").read_text().splitlines()
            events = [json.loads(x) for x in lines if x.strip()]
            match_s = max(e["t"] for e in events)
            for w in windows(events, match_s):
                clips.append({"split": split, "seed": s} | w)
    render = {"views": "tactical", "set": ["stadium=broadcast"], "dead_ball_cut": False}
    count = {k: sum(1 for c in clips if c["split"] == k) for k in ("validation", "test")}
    return {"name": NAME, "render_commit": RENDER_COMMIT, "render": render, "before_s": BEFORE_S,
            "after_s": AFTER_S, "splits": {"validation": list(VALIDATION), "test": list(TEST)},
            "clips": clips, "count": count}


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Windows around every shot of the shot-outcome set's matches.")
    ap.add_argument("--sims", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args(argv)
    m = build(a.sims)
    a.out.write_text(json.dumps(m, indent=1) + "\n")
    print(json.dumps(m["count"]))


if __name__ == "__main__":
    main()
