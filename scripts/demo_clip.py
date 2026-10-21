"""Pick the demo video's match footage by the rule in docs/eval/demo-clip.md, not by browsing renders.

    uv run python scripts/demo_clip.py            # at the freeze commit, through runs/slot.sh

Prints the chosen seed and window, the events that qualify it, and the render command.
"""

from __future__ import annotations

import json
import sys

FIRST_SEED = 8001  # 8000-8999: no training, validation, round or test run uses them
LAST_SEED = 8050
MINUTES = 45  # the first half: enough for most seeds to hold a goal
WINDOW_S = 60.0
STEP_S = 5.0
BUILD_UP_S = 15.0  # the goal is at least this far into the window, so its build-up is on screen
MIN_PASSES = 3


def first_window(events: list[dict], minutes: float = MINUTES) -> float | None:
    """The earliest start (a multiple of STEP_S) whose window holds a goal at least BUILD_UP_S in,
    a set piece other than a kick-off, and at least MIN_PASSES passes; None if no window does."""
    t0 = 0.0
    while t0 + WINDOW_S <= minutes * 60:
        inside = [e for e in events if t0 <= e["t"] <= t0 + WINDOW_S]
        goal = any(e["type"] == "goal" and e["t"] >= t0 + BUILD_UP_S for e in inside)
        set_piece = any(e["type"] == "set_piece" for e in inside)
        passes = sum(e["type"] == "pass" for e in inside)
        if goal and set_piece and passes >= MIN_PASSES:
            return t0
        t0 += STEP_S
    return None


def main() -> None:
    from ninety.sim.engine import simulate

    for seed in range(FIRST_SEED, LAST_SEED + 1):
        events = simulate(seed, MINUTES).events
        t0 = first_window(events)
        if t0 is None:
            print(json.dumps({"seed": seed, "window": None}), flush=True)
            continue
        qualifying = [{k: e[k] for k in ("id", "t", "type", "team", "player")} for e in events
                      if t0 <= e["t"] <= t0 + WINDOW_S and e["type"] in ("goal", "set_piece")]
        cmd = (f"uv run ninety-render --seed {seed} --start {t0:g} --seconds {WINDOW_S:g} "
               f"--set dead_ball_cut=true --set kit_contrast=broadcast --mp4 --gpu --out runs/demo/seed{seed}")
        print(json.dumps({"seed": seed, "start_s": t0, "events": qualifying, "command": cmd}, indent=1))
        return
    sys.exit(f"no seed in {FIRST_SEED}-{LAST_SEED} has a qualifying window: widen the range in a new commit")


if __name__ == "__main__":
    main()
