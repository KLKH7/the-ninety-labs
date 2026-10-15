"""Deterministic template graphics that air before model-backed explanations."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from jsonschema import validate

from ninety.agents.factcheck import Claim, check
from ninety.agents.ledger import InMemoryLedger, Ledger, load_match
from ninety.match.facts import match_events

DISPLAY_SECONDS = 5.0  # Long enough to read a lower-third without competing with the next event.
ROOT = Path(__file__).resolve().parents[2]
SCHEMA = json.loads((ROOT / "schemas" / "overlay_cue.schema.json").read_text())


def _text(event: dict, persona: str) -> str:
    player = event["player"]
    receiver = event.get("receiver")
    if persona == "casual":
        if event["type"] == "pass":
            return f"{player} finds {receiver}" if receiver else f"{player} plays a pass"
        return f"{player} scores" if event["type"] == "goal" else f"{player} takes a shot"
    if event["type"] == "pass":
        parts = [f"{player} → {receiver}" if receiver else f"{player} pass"]
        if event.get("distance_m") is not None:
            parts.append(f"{event['distance_m']} m")
        if event.get("ball_speed_kmh") is not None:
            parts.append(f"{event['ball_speed_kmh']} km/h")
        return ", ".join(parts)
    parts = [f"{player} scores" if event["type"] == "goal" else f"{player} shot"]
    if event.get("ball_speed_kmh") is not None:
        parts.append(f"{event['ball_speed_kmh']} km/h")
    return ", ".join(parts)


async def template_cues(ledger: Ledger) -> list[dict]:
    events = await ledger.query(kind="event")
    await ledger.query(kind="fact")  # Keep facts part of the template-cue read path.
    cues = []
    for record in events:
        if record.payload.get("type") not in {"pass", "shot", "goal"}:
            continue
        for persona in ("analyst", "casual"):
            text = _text(record.payload, persona)
            if persona == "analyst":
                verdict = check(Claim(text, [record.id]), {record.id: record.payload})
                if not verdict.ok:
                    raise ValueError(f"cue {record.id}-{persona}: {verdict.reasons}")
            cue = {
                "id": f"cue-{record.id}-{persona}",
                "t_in": record.t,
                "t_out": record.t + DISPLAY_SECONDS,
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
