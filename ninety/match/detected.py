"""Detected events: what the live path reads from Milestone 1 onward.

The vision pipeline writes one `match_event` per line with `"source": "vision"` and a `confidence`
(schemas/match_event.schema.json; docs/EVALUATION.md, "Input: detected events"). This module is
the one place the agents, the stats and the MCP server get them from. It refuses anything else:
a ground-truth event (`"source": "truth"`) or a file named like the answer key never loads here,
so the live path cannot be pointed at the truth by mistake (AGENTS.md, "Ground truth is the
answer key").

For the M1 clip, `m1_path` serves R3's detected events (`tests/fixtures/detected-seed900001.jsonl`,
the event detector's output from the clip's video). Only when that file is absent does it fall back
to a stand-in written by hand from the schema. The stand-in is marked as one in its file name and
in every id (`standin-`), and it was never derived from the clip's ground truth.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[2]
SOURCE = "vision"
SCHEMA = json.loads((ROOT / "schemas" / "match_event.schema.json").read_text())
_VALIDATOR = Draft202012Validator(SCHEMA)
FIXTURES = ROOT / "tests" / "fixtures"
M1_CLIP = "seed900001"
# The answer key's file names (docs/DATA_CONTRACT.md): never a detected-events file.
TRUTH_NAMES = frozenset({"events.jsonl", "frames.jsonl"})
# The engine never moves a ball faster than 40 m/s (GROUNDING P3, a design bound: real recorded kicks go
# faster, about 58 m/s, but not in this engine's matches, which is all the live path sees). A detected
# speed above it is a misread, not a measurement: the live path keeps the event and drops the speed,
# so no graphic, line or claim says it (vision's speed estimate is its own to fix).
MAX_BALL_KMH = 40.0 * 3.6


def m1_path(clip: str = M1_CLIP) -> Path:
    """R3's detected events for the clip when they exist, else the hand-written stand-in."""
    detected = FIXTURES / f"detected-{clip}.jsonl"
    return detected if detected.exists() else FIXTURES / f"detected-standin-{clip}.jsonl"


def is_standin(path: Path) -> bool:
    return path.name.startswith("detected-standin-")


def check(events: list[dict], where: str = "detected events") -> list[dict]:
    """Every event a valid match_event from vision, with a confidence, ids unique, in time order."""
    seen: set[str] = set()
    for n, event in enumerate(events, 1):
        errors = sorted(_VALIDATOR.iter_errors(event), key=lambda e: list(e.path))
        if errors:
            raise ValueError(f"{where}, event {n}: not a match_event: {errors[0].message}")
        if event["source"] != SOURCE:
            raise ValueError(
                f"{where}, event {n} ({event['id']}): source {event['source']!r}; the live path reads "
                f"only detected events (source {SOURCE!r}), never ground truth"
            )
        if event.get("confidence") is None:
            raise ValueError(f"{where}, event {n} ({event['id']}): a detected event needs a confidence")
        if event["id"] in seen:
            raise ValueError(f"{where}: duplicate event id {event['id']}")
        seen.add(event["id"])
    return sorted(events, key=lambda e: (e["t"], e["id"]))


def load(path: str | Path) -> list[dict]:
    path = Path(path)
    if path.name in TRUTH_NAMES:
        raise ValueError(f"{path}: that is the answer key's name; the live path reads detected events")
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    return [credible(e) for e in check(rows, str(path))]


def credible(event: dict) -> dict:
    """The event with a ball speed no ball can reach dropped to unknown (MAX_BALL_KMH, GROUNDING P3)."""
    speed = event.get("ball_speed_kmh")
    if speed is not None and speed > MAX_BALL_KMH:
        return {**event, "ball_speed_kmh": None}
    return event


@lru_cache(maxsize=4)
def load_cached(path: str) -> tuple[dict, ...]:
    return tuple(load(path))
