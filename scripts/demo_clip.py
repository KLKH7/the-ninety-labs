"""Pick the demo video's match footage by the rule in docs/eval/demo-clip.md, not by browsing renders.

SUPERSEDED (Oct 23): the demo plays the condensed full match (docs/eval/demo-match.md,
scripts/demo_match.py). This rule is kept as the record of what was pre-registered and never runs.

    uv run python scripts/demo_clip.py            # at the freeze commit, through runs/slot.sh

Prints the chosen seed and window, the events that qualify it, and the render command.
"""

from __future__ import annotations

import json
import sys

FIRST_SEED = 8002  # 8001 was the demo seed for v1 and v2: watched, and the engine was fixed on it
LAST_SEED = 8050
MINUTES = 45  # the first half: enough for most seeds to hold a goal
WINDOW_S = 60.0
STEP_S = 5.0
BUILD_UP_S = 15.0  # the goal is at least this far into the window, so its build-up is on screen
MIN_PASSES = 3
# Viewer footage needs the broadcast stadium (lesson 185); the default plain stands scored 2/10.
RENDER_FLAGS = "--set dead_ball_cut=true --set kit_contrast=broadcast --set stadium=broadcast"


def render_command(seed: int, start: float) -> str:
    return (f"uv run ninety-render --seed {seed} --start {start:g} --seconds {WINDOW_S:g} "
            f"{RENDER_FLAGS} --mp4 --gpu --out runs/demo/seed{seed}")


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


SUPERSEDED_BY = "docs/eval/demo-match.md"


def main() -> None:
    sys.exit(f"superseded by {SUPERSEDED_BY}: this rule is never applied")
    from ninety.sim.engine import simulate  # the rule as it was registered, kept for the record

    for seed in range(FIRST_SEED, LAST_SEED + 1):
        events = simulate(seed, MINUTES).events
        t0 = first_window(events)
        if t0 is None:
            print(json.dumps({"seed": seed, "window": None}), flush=True)
            continue
        qualifying = [{k: e[k] for k in ("id", "t", "type", "team", "player")} for e in events
                      if t0 <= e["t"] <= t0 + WINDOW_S and e["type"] in ("goal", "set_piece")]
        cmd = render_command(seed, t0)
        print(json.dumps({"seed": seed, "start_s": t0, "events": qualifying, "command": cmd}, indent=1))
        return
    sys.exit(f"no seed in {FIRST_SEED}-{LAST_SEED} has a qualifying window: widen the range in a new commit")


if __name__ == "__main__":
    main()
