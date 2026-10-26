"""Spells of possession for the spoken tracks: a run of passes said as one line, not one line each.

A spell is a chain of completed passes in a row: each pass's receiver plays the next one (the same
tracked player, so the chain rests on what vision followed, not on a side it may have misread), no
other event comes between two of them (a shot, a tackle, the ball going out: the move is over), and
none is more than MAX_GAP_S after the last. Every pass in it is a vision detection at or above the
confidence gate (`factcheck.MIN_CONFIDENCE`). A chain shorter than MIN_PASSES is no spell: its
passes are said one by one, as before.

The line counts the passes it cites ("Six passes in a row, on the right."), which the fact-checker
allows as a count of the cited events, and names the side only when every pass's side was told
surely (`factcheck.side_known`), else it says no side. Nothing here reads ground truth.
"""

from __future__ import annotations

from ninety.agents.factcheck import MIN_CONFIDENCE, side_known

MIN_PASSES = 4  # design: three passes are a move a listener can follow pass by pass; four are a spell
MAX_GAP_S = 10.0  # design: longer between two passes and nothing seen of the move between them


def _sure(event: dict) -> bool:
    return event.get("confidence") is not None and event["confidence"] >= MIN_CONFIDENCE


def spells(events: list[dict]) -> list[list[dict]]:
    """Every spell in the events, in time order: completed passes chained receiver to passer."""
    found: list[list[dict]] = []
    run: list[dict] = []
    for event in sorted(events, key=lambda e: (e["t"], e["id"])):
        if event["type"] != "pass":
            if len(run) >= MIN_PASSES:
                found.append(run)
            run = []  # any other event between two passes ends the run
            continue
        completed = event.get("outcome") == "success" and event.get("player") and event.get("receiver")
        if (completed and _sure(event) and run and event["player"] == run[-1]["receiver"]
                and event["t"] - run[-1]["t"] <= MAX_GAP_S):
            run.append(event)
            continue
        if len(run) >= MIN_PASSES:
            found.append(run)
        run = [event] if completed and _sure(event) else []
    if len(run) >= MIN_PASSES:
        found.append(run)
    return found


def versions(spell: list[dict], place: str) -> list[str]:
    """The spell's line, full form first: the count of its passes, the side when it was told surely,
    and where the last pass went."""
    n = len(spell)
    team = spell[-1]["team"]
    sure = team in ("home", "away") and all(side_known(e) and e["team"] == team for e in spell)
    head = f"{n} passes in a row for {team}" if sure else f"{n} passes in a row"
    return [f"{head}, {place}.", f"{head}."]
