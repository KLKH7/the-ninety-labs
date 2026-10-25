"""Why a detected free kick was given, as far as tracking can tell (Laws 11 to 14, docs/GROUNDING.md L10, L12).

A free kick follows an offence: offside (Law 11, an indirect free kick) or a foul or other offence
(Laws 12 and 13). Tracking sees positions, not contact, so it can rule on offside but never on a
foul. The cause of a detected free kick (`ninety/vision/restarts.py`, `restart: "free_kick"`) is
read from the offside reading (`ninety.intel.offside`) of the last completed pass before it, since
the restart before:

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

from collections.abc import Iterable, Mapping

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
        if e.get("type") == "pass" and e.get("outcome") == "success" and e.get("receiver"):
            last_pass = e
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


__all__ = ["CAUSES", "annotate", "causes"]
