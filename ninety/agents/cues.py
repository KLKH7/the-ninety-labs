"""Deterministic template graphics that air before model-backed explanations."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from jsonschema import validate

from ninety.agents.factcheck import MIN_CONFIDENCE, Claim, check, side_known
from ninety.agents.ledger import InMemoryLedger, Ledger, load_match
from ninety.match.facts import match_events

DISPLAY_SECONDS = 5.0  # Long enough to read a lower-third without competing with the next event.
ROOT = Path(__file__).resolve().parents[2]
SCHEMA = json.loads((ROOT / "schemas" / "overlay_cue.schema.json").read_text())
TEMPLATE_TYPES = ("pass", "shot", "goal")  # the events a template graphic airs for


# Words that state a result follow the event's outcome field: "finds" only for a completed
# pass, "scores" only for a goal. The number gate in factcheck.check cannot catch a wrong verb.
SHOT_OUTCOME = {"on_target": "on target", "off_target": "off target", "blocked": "blocked", "goal": "goal"}


def _pass_text(event: dict, persona: str) -> str:
    """A pass names who it was for (`intended`), who got it (`receiver`, completed only), who cut it
    out (`interceptor`) and who only touched it (`deflected_by`): different people, never one field
    read as another. A touch is only a touch: "cut out" needs the opponent to have won it."""
    player, outcome = _who(event), event.get("outcome")
    receiver, intended, interceptor = event.get("receiver"), event.get("intended"), event.get("interceptor")
    deflector = event.get("deflected_by")
    target = receiver or intended
    stopped = (f"cut out by {interceptor}" if interceptor
               else f"deflected by {deflector}" if deflector else None)
    if persona == "casual":
        if outcome == "success" and receiver:
            return f"{player} finds {receiver}"
        if outcome == "fail":
            if intended and stopped:
                return f"{player}'s pass for {intended} is {stopped}"
            if stopped:
                return f"{player}'s pass is {stopped}"
            if intended:
                return f"{player} looks for {intended}, but it doesn't arrive"
        if intended:
            return f"{player} looks for {intended}"
        return f"{player} plays a pass"
    parts = [f"{player} → {target}" if target else "a pass" if player == UNNAMED else f"{player} pass"]
    if outcome == "fail":
        parts[0] += f" ({stopped})" if stopped else " (incomplete)"
    elif outcome is None and target:
        parts[0] += " (in flight)"
    if event.get("distance_m") is not None:
        parts.append(f"{event['distance_m']} m")
    if event.get("ball_speed_kmh") is not None:
        parts.append(f"{event['ball_speed_kmh']} km/h")
    return ", ".join(parts)


UNNAMED = "a player"  # who an event is about when neither the player nor, surely, the side is known


def _who(event: dict) -> str:
    """The player, or the team when the detector could not say who it was and its side is known
    (factcheck.side_known); else neither: a graphic never names a side the detector is unsure of."""
    return event.get("player") or (event["team"] if side_known(event) else UNNAMED)


def _shot_text(event: dict, persona: str) -> str:
    player = _who(event)
    if event["type"] == "goal" or (persona == "casual" and event.get("outcome") == "goal"):
        return "a goal" if player == UNNAMED else f"{player} scores"
    if persona == "casual":
        return f"{player} takes a shot"
    if event.get("outcome") == "goal":
        # A shot that went in reads as a goal, not "a player shot, goal" (video-prep, Oct 25).
        parts = ["a goal" if player == UNNAMED else f"{player} scores"]
    else:
        parts = ["a shot" if player == UNNAMED else f"{player} shot"]
        if event.get("outcome") in SHOT_OUTCOME:
            parts.append(SHOT_OUTCOME[event["outcome"]])
    if event.get("ball_speed_kmh") is not None:
        parts.append(f"{event['ball_speed_kmh']} km/h")
    return ", ".join(parts)


def _text(event: dict, persona: str) -> str:
    return _pass_text(event, persona) if event["type"] == "pass" else _shot_text(event, persona)


async def template_cues(ledger: Ledger, min_confidence: float = MIN_CONFIDENCE) -> list[dict]:
    """A cue for every pass, shot and goal, except a detection the detector is unsure of: a
    template airs without the fact-checker's model half, so it airs only on a confident one."""
    events = await ledger.query(kind="event")
    cues = []
    for record in events:
        if record.payload.get("type") not in TEMPLATE_TYPES:
            continue
        if record.confidence is not None and record.confidence < min_confidence:
            continue
        for persona in ("analyst", "casual"):
            text = _text(record.payload, persona)
            # Both personas pass the fact-checker's code half: numbers and player ids alike.
            verdict = check(Claim(text, [record.id]), {record.id: record.payload})
            if not verdict.ok:
                raise ValueError(f"cue {record.id}-{persona}: {verdict.reasons}")
            cue = {
                "id": f"cue-{record.id}-{persona}",
                "t_in": record.t,
                "t_out": round(record.t + DISPLAY_SECONDS, 2),  # event times are to 0.01 s
                "kind": "pass_arc" if record.payload["type"] == "pass" else "shot_speed",
                "slot": "lower_third",
                "anchor": None,
                "persona": persona,
                "lang": "en",
                "text": text,
                "verified": False,
                "replaces": None,
                "evidence": [record.id],
            }
            validate(cue, SCHEMA)
            cues.append(cue)
    return cues


async def build_fixture(seed: int, minutes: float) -> list[dict]:
    ledger = InMemoryLedger()
    events = list(match_events(seed, minutes))
    await load_match(ledger, events, ())
    return await template_cues(ledger)


def write_fixture(cues: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(cue, sort_keys=True, separators=(",", ":")) + "\n" for cue in cues))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--minutes", type=float, default=5)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    write_fixture(asyncio.run(build_fixture(args.seed, args.minutes)), args.out)


if __name__ == "__main__":
    main()
