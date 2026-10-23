"""The shape every insight fact has, so the tools, the fact-checker and the phone read one form.

An insight fact is a dict (it travels as JSON through the MCP server and into the agents' prompts):

- id: `<kind prefix>:<what it is about>`, unique in a match (`lb:v00042` is the line break of
  detected pass v00042);
- kind: line_break, overload, counter_press or pass_options; metric: what `value` measures;
- team: "home" or "away" (the club's name is added where a match is served, from its team sheet,
  ninety/intel/teamsheet.py); minute (football's ordinal) and t (seconds) of the moment;
- value, unit, lo, hi: the count and its bounds (ninety/intel/scene.py); confident: the bounds
  agree on what the fact says;
- tracked: how many of each team the frame had; event: the detected event it rests on, with its
  confidence and the confidence of its side (`team_confidence`), when there is one;
- also: other numbers the fact states, each with its unit ([[3, "players"]]), that a sentence may
  quote with that unit (ninety/agents/insight_check.py);
- visual: what the phone draws for it (schemas/insight_card.schema.json, `visual.geometry`).

It has no `type` key, so the fact-checker's number rule treats it as a computed fact: its value
may be written only with its unit ("4 opponents"), never as a bare number
(ninety/agents/factcheck.py `_is_fact`).
"""

from __future__ import annotations

from collections.abc import Mapping

from ninety.intel.scene import Count, minute_of, tracked_counts

KINDS = ("line_break", "overload", "counter_press", "pass_options")


def fact(
    fid: str,
    kind: str,
    metric: str,
    team: str,
    t: float,
    count: Count,
    unit: str,
    frame: Mapping | None,
    visual: dict,
    event: Mapping | None = None,
    confident: bool | None = None,
    **extra,
) -> dict:
    if kind not in KINDS:
        raise ValueError(f"unknown insight kind {kind!r}")
    out = {
        "id": fid,
        "kind": kind,
        "metric": metric,
        "team": team,
        "minute": minute_of(t),
        "t": round(float(t), 2),
        "value": count.value,
        "unit": unit,
        "lo": count.lo,
        "hi": count.hi,
        "confident": count.sure if confident is None else confident,
        "tracked": tracked_counts(frame) if frame is not None else {"home": 0, "away": 0},
        "event": event["id"] if event else None,
        "event_confidence": event.get("confidence") if event else None,
        "team_confidence": event.get("team_confidence") if event else None,
        "visual": {"kind": kind, **visual},
    }
    out.update(extra)
    return out


def in_minutes(facts, minute_from: int, minute_to: int, team: str | None = None) -> list[dict]:
    return [
        f for f in facts if minute_from <= f["minute"] <= minute_to and (team is None or f["team"] == team)
    ]


__all__ = ["KINDS", "fact", "in_minutes"]
