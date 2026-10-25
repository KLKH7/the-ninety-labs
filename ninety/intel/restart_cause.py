"""Why a detected free kick was given, as far as tracking can tell (Laws 11 to 14; GROUNDING L10, L12).

    uv run python -m ninety.intel.restart_cause --events detected.jsonl --restarts restarts.jsonl \\
        --tracked tracked.json --out restarts-caused.jsonl

A free kick follows an offence: offside (Law 11, an indirect free kick) or a foul or other offence
(Laws 12 and 13). Tracking sees positions, not contact, so it can rule on offside but never on a
foul. The cause of a detected free kick (`ninety/vision/restarts.py`, `restart: "free_kick"`) is
read from the offside reading (`ninety.intel.offside`) of the last pass before it, since the restart
before (only a completed pass has a reading; play that went on past an offside position was not
stopped for it):

- that pass's receiver was in an offside position (`offside`): cause `offside`;
- the reading was too close to call, or offside with an opponent untracked (`too_close`,
  `unsure`): cause `unknown`, because it might have been either;
- anything else (onside, a pass straight from a restart, no pass read, no pass at all): cause
  `foul_likely`. The other offences that give a free kick are Law 12's, so it was likely one of
  those, but nobody is named: who fouled whom is not visible in tracking.

A penalty kick is given only for a Law 12 offence by a defender in his own penalty area (Law 14):
cause `foul`. Other restarts (kick-off, corner, goal kick, throw-in) follow no offence and carry no
cause.

Nothing here reads ground truth: the detected events and the tracked frames only, as the offside
reading does. The cause's accuracy is measured offline against the answer key's `foul` and
`offside` events, on validation clips (docs/eval/restarts-vision-plan.md).
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Iterable, Mapping
from pathlib import Path

from ninety.intel import offside
from ninety.intel.scene import Frames

CAUSES = ("offside", "foul_likely", "foul", "unknown")
RESTARTS = frozenset({"set_piece", "kickoff"})  # the events that put the ball back in play


def causes(events: Iterable[Mapping], frames: Frames) -> dict[str, str]:
    """The cause of each detected free kick and penalty, by event id."""
    rows = sorted(events, key=lambda e: (e["t"], e["id"]))
    verdict = {r["event"]: r["verdict"] for r in offside.offsides(rows, frames)}
    out: dict[str, str] = {}
    last_pass: Mapping | None = None
    for e in rows:
        if e.get("type") == "pass":
            last_pass = e  # any later pass means play went on: only the last one can explain a stoppage
            continue
        if e.get("type") not in RESTARTS:
            continue
        kind = e.get("restart")
        if kind == "penalty_kick":
            out[e["id"]] = "foul"
        elif kind == "free_kick":
            read = verdict.get(last_pass["id"]) if last_pass else None
            out[e["id"]] = ("offside" if read == "offside"
                            else "unknown" if read in ("too_close", "unsure") else "foul_likely")
        last_pass = None  # a restart starts a new phase: no earlier pass explains the next stoppage
    return out


def annotate(events: Iterable[Mapping], frames: Frames) -> list[dict]:
    """The events, each free kick and penalty with its `cause` (copies; the input is not changed)."""
    rows = [dict(e) for e in events]
    found = causes(rows, frames)
    for e in rows:
        if e["id"] in found:
            e["cause"] = found[e["id"]]
    return rows


def _jsonl(path: Path) -> list[dict]:
    return [json.loads(x) for x in path.read_text().splitlines() if x.strip()]


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Give each detected free kick and penalty its likely cause.")
    ap.add_argument("--events", type=Path, required=True, help="detected.jsonl (ninety.vision.events)")
    ap.add_argument("--restarts", type=Path, required=True, help="restarts.jsonl (ninety.vision.restarts)")
    ap.add_argument("--tracked", type=Path, required=True, help="tracked.json (ninety.vision.tracked_frames)")
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args(argv)
    restarts = _jsonl(a.restarts)
    frames = Frames(json.loads(a.tracked.read_text())["frames"])
    caused = {e["id"]: e for e in annotate(_jsonl(a.events) + restarts, frames)}
    a.out.write_text("".join(json.dumps(caused[e["id"]]) + "\n" for e in restarts), encoding="utf-8")
    print(json.dumps({c: sum(1 for e in caused.values() if e.get("cause") == c) for c in CAUSES}))


__all__ = ["CAUSES", "annotate", "causes"]


if __name__ == "__main__":
    main()
