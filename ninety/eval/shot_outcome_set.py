"""The shot-outcome set's clips (docs/eval/shot-outcome-set.md), from the full matches' answer keys.

    uv run python -m ninety.eval.shot_outcome_set --sims <dir of seed<N>/{events.jsonl,meta.json}> \\
        --out docs/eval/shot-outcome-set.json

Every shot of a match gets a window from BEFORE_S before it to AFTER_S after it; windows that
overlap are joined, up to MAX_S. Then a fixed subset is kept (the set's render budget): every
window with a goal, the first MAX_SAVE_WINDOWS windows in time with a save (a shot the answer key
calls `on_target`), and the first OTHER_WINDOWS with neither. Nothing is chosen by hand. The
output lists each clip's split, seed, start and length only; which outcome a clip holds is not
written, so the test split's outcomes stay unread until it is scored.
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
# The plan's offsets (shot-outcomes-plan.md): 3 s of the build-up, so the strike and its spell are
# seen, and 7 s after it, for the ball to reach the goal and rest in the net or for the keeper to
# hold it and play to go on (design). A 10 s window, as every dataset clip.
BEFORE_S = 3.0
AFTER_S = 7.0
# A run of shots (rebounds) joins into one window of at most MAX_S; the next shot starts a new one
# (design: two windows' length).
MAX_S = 20.0
# The subset (design, for a render of about an hour on one machine): all goals, the first six save
# windows of a match, and the first two windows with neither, for false goals and saves.
MAX_SAVE_WINDOWS = 6
OTHER_WINDOWS = 2


def _frame(t: float) -> float:
    return round(t * FPS) / FPS


def windows(events: list[dict], match_s: float) -> list[dict]:
    """[{start, seconds, shots: [(t, outcome)]}] in match seconds, on whole frames, joined where
    they overlap up to MAX_S, inside the match."""
    out: list[dict] = []
    for e in sorted((e for e in events if e["type"] == "shot"), key=lambda e: e["t"]):
        start = max(0.0, _frame(e["t"] - BEFORE_S))
        end = min(match_s, _frame(e["t"] + AFTER_S))
        last = out[-1] if out else None
        if last and start <= last["start"] + last["seconds"] and end - last["start"] <= MAX_S:
            last["seconds"] = round(end - last["start"], 2)
            last["shots"].append((e["t"], e.get("outcome")))
        else:
            out.append({"start": round(start, 2), "seconds": round(end - start, 2),
                        "shots": [(e["t"], e.get("outcome"))]})
    return out


def kind(w: dict) -> str:
    outcomes = {o for _, o in w["shots"]}
    return "goal" if "goal" in outcomes else "save" if "on_target" in outcomes else "other"


def subset(ws: list[dict]) -> list[dict]:
    """Every goal window, the first MAX_SAVE_WINDOWS save windows and the first OTHER_WINDOWS other
    windows, in time order."""
    saves = [w for w in ws if kind(w) == "save"][:MAX_SAVE_WINDOWS]
    others = [w for w in ws if kind(w) == "other"][:OTHER_WINDOWS]
    keep = {id(w) for w in ws if kind(w) == "goal"} | {id(w) for w in saves + others}
    return [w for w in ws if id(w) in keep]


def build(sims: Path) -> dict:
    clips = []
    for split, seeds in (("validation", VALIDATION), ("test", TEST)):
        for s in seeds:
            d = sims / f"seed{s}"
            events = [json.loads(x) for x in (d / "events.jsonl").read_text().splitlines() if x.strip()]
            match_s = json.loads((d / "meta.json").read_text())["minutes"] * 60
            for w in subset(windows(events, match_s)):
                clips.append({"split": split, "seed": s, "start": w["start"], "seconds": w["seconds"]})
    render = {"views": None, "set": ["stadium=broadcast"], "dead_ball_cut": False}
    count = {k: sum(1 for c in clips if c["split"] == k) for k in ("validation", "test")}
    return {"name": NAME, "render_commit": RENDER_COMMIT, "render": render, "before_s": BEFORE_S,
            "after_s": AFTER_S, "max_s": MAX_S, "max_save_windows": MAX_SAVE_WINDOWS,
            "other_windows": OTHER_WINDOWS, "splits": {"validation": list(VALIDATION), "test": list(TEST)},
            "clips": clips, "count": count,
            "seconds": round(sum(c["seconds"] for c in clips), 2)}


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="The shot-outcome set's clips, from its matches' answer keys.")
    ap.add_argument("--sims", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args(argv)
    m = build(a.sims)
    a.out.write_text(json.dumps(m, indent=1) + "\n")
    print(json.dumps({"count": m["count"], "seconds": m["seconds"]}))


if __name__ == "__main__":
    main()
