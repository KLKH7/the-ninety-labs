"""Spells of possession for the spoken tracks: a run of passes said as one line, not one line each.

A spell is a chain of completed passes in which each pass's receiver plays the next one: the same
tracked player, so the chain rests on what vision followed, not on a side it may have misread. Every
pass in it is a vision detection at or above the confidence gate (`factcheck.MIN_CONFIDENCE`). A
chain shorter than MIN_PASSES is no spell: its passes are said one by one, as before.

The line counts the passes it cites ("Six passes in a row, on the right."), which the fact-checker
allows as a count of the cited events, and names the side only when every pass's side was told
surely (`factcheck.side_known`), else it says no side. Nothing here reads ground truth.
"""

from __future__ import annotations

from ninety.agents.factcheck import MIN_CONFIDENCE, side_known

MIN_PASSES = 4  # design: three passes are a move a listener can follow pass by pass; four are a spell


def _sure(event: dict) -> bool:
    return event.get("confidence") is not None and event["confidence"] >= MIN_CONFIDENCE


def spells(events: list[dict]) -> list[list[dict]]:
    """Every spell in the events, in time order: completed passes chained receiver to passer."""
    passes = sorted((e for e in events if e["type"] == "pass"), key=lambda e: (e["t"], e["id"]))
    found: list[list[dict]] = []
    run: list[dict] = []
    for event in passes:
        completed = event.get("outcome") == "success" and event.get("player") and event.get("receiver")
        if completed and _sure(event) and run and event["player"] == run[-1]["receiver"]:
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
