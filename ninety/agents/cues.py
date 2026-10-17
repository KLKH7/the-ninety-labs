"""Deterministic template graphics that air before model-backed explanations.

Two families, both written by code from cited events and gated by the fact-checker's code half:
per-event cues (passes, shots, goals) and turning-point cues for the match terrain
(`ninety/intel/terrain.py`), one per persona, with no model call.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from jsonschema import validate

from ninety.agents.factcheck import Claim, check
from ninety.agents.ledger import InMemoryLedger, Ledger, load_match
from ninety.match.facts import compact, match_events

DISPLAY_SECONDS = 5.0  # Long enough to read a lower-third without competing with the next event.
ROOT = Path(__file__).resolve().parents[2]
SCHEMA = json.loads((ROOT / "schemas" / "overlay_cue.schema.json").read_text())


# Words that state a result follow the event's outcome field: "finds" only for a completed
# pass, "scores" only for a goal. The number gate in factcheck.check cannot catch a wrong verb.
SHOT_OUTCOME = {"on_target": "on target", "off_target": "off target", "blocked": "blocked", "goal": "goal"}


def _pass_text(event: dict, persona: str) -> str:
    player, receiver, outcome = event["player"], event.get("receiver"), event.get("outcome")
    if persona == "casual":
        if not receiver:
            return f"{player} plays a pass"
        if outcome == "success":
            return f"{player} finds {receiver}"
        if outcome == "fail":
            return f"{player} looks for {receiver}, but it doesn't arrive"
        return f"{player} looks for {receiver}"
    parts = [f"{player} → {receiver}" if receiver else f"{player} pass"]
    if outcome == "fail":
        parts[0] += " (incomplete)"
    if event.get("distance_m") is not None:
        parts.append(f"{event['distance_m']} m")
    if event.get("ball_speed_kmh") is not None:
        parts.append(f"{event['ball_speed_kmh']} km/h")
    return ", ".join(parts)


def _shot_text(event: dict, persona: str) -> str:
    player = event["player"]
    if event["type"] == "goal":
        return f"{player} scores"
    if persona == "casual":
        return f"{player} takes a shot"
    parts = [f"{player} shot"]
    if event.get("outcome") in SHOT_OUTCOME:
        parts.append(SHOT_OUTCOME[event["outcome"]])
    if event.get("ball_speed_kmh") is not None:
        parts.append(f"{event['ball_speed_kmh']} km/h")
    return ", ".join(parts)


def _text(event: dict, persona: str) -> str:
    return _pass_text(event, persona) if event["type"] == "pass" else _shot_text(event, persona)


async def template_cues(ledger: Ledger) -> list[dict]:
    events = await ledger.query(kind="event")
    cues = []
    for record in events:
        if record.payload.get("type") not in {"pass", "shot", "goal"}:
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


# Turning-point cues. A turning point is only known in hindsight (the side must hold on for
# minutes), so these are recap cues: t_in marks the start of the minute they describe.
TURNING_POINT_SECONDS = 8.0  # design: one sentence of story, read at a slower recap pace
LONG_SPELL_MINUTES = 20  # design: a spell this long is "a grip" worth naming when it breaks
SHORT_SPELL_MINUTES = 10  # design: a spell shorter than this is described as brief
SIDE = {"home": "Home", "away": "Away"}


def _other(team: str) -> str:
    return "away" if team == "home" else "home"


def _counted(team: str) -> set[tuple[str, str]]:
    """The (team, type) pairs a turning-point text may state a count of."""
    return {(team, "pass"), (team, "pressure"), (team, "interception"), (team, "shot"),
            (_other(team), "interception")}


def _witness(events: list[dict], minute: int, team: str) -> dict | None:
    """An event that proves a stated minute. It is never of a counted (team, type) pair, so citing
    it cannot change a stated count: the checker counts every cited event by team and type."""
    counted = _counted(team)
    return next((e for e in events if e["minute"] == minute and (e["team"], e["type"]) not in counted), None)


def _cite_minute(minute: int, team: str, events: list[dict], cited: list[dict], evidence: list[str]) -> bool:
    """Make sure a stated minute is in the evidence, adding a witness when no cited event has it."""
    if any(e["minute"] == minute for e in cited):
        return True
    witness = _witness(events, minute, team)
    if witness is None:
        return False
    evidence.append(witness["id"])
    cited.append(witness)
    return True


def _counts(cited: list[dict], team: str) -> dict[str, int]:
    def n(event_team: str, kind: str) -> int:
        return sum(e["team"] == event_team and e["type"] == kind for e in cited)
    return {"passes": n(team, "pass"), "pressures": n(team, "pressure"),
            "interceptions": n(team, "interception"), "shots": n(team, "shot"),
            "lost": n(_other(team), "interception")}


def _count(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


def _turning_text(point: dict, previous: dict | None, minutes: int, c: dict[str, int],
                  until: int | None, peak: int | None, persona: str) -> str:
    side, other = SIDE[point["team"]], SIDE[_other(point["team"])]
    m = point["minute"]
    to_end = until is not None and point["until"] == minutes
    if persona == "analyst":
        span = f"{m}'–{until}'" if until is not None else f"from {m}'"
        head = f"{side} on top {span}" + (f", peak {peak}'" if peak is not None else "")
        parts = [_count(c[k], one, many) for k, one, many in
                 (("passes", "pass", "passes"), ("pressures", "pressure", "pressures"),
                  ("interceptions", "interception", "interceptions"), ("shots", "shot", "shots")) if c[k]]
        tail = f"Previous three minutes: {', '.join(parts)}" if parts else "Quiet build-up"
        lost = f"; {other} intercepted {c['lost']}" if c["lost"] else ""
        return f"{head}. {tail}{lost}."

    if persona == "audio":
        opener = f"{side} take control in minute {m}"
        if to_end:
            opener += f" and keep it until minute {until}, the end of the match"
        elif until is not None:
            opener += f" and keep it until minute {until}"
    elif previous is None:
        opener = f"{side} settle first and take control at {m}'"
    elif previous["held"] >= LONG_SPELL_MINUTES:
        opener = f"{side} finally break {other}'s grip at {m}'"
    else:
        opener = f"{side} wrestle it back at {m}'"
    if persona == "casual":
        if to_end:
            opener += ", staying on top until the end"
        elif until is not None and point["held"] < SHORT_SPELL_MINUTES:
            opener += f", but only until {until}'"
        elif until is not None:
            opener += f", holding on until {until}'"
        if peak is not None and point["held"] >= LONG_SPELL_MINUTES:
            opener += f", strongest at {peak}'"

    if c["shots"]:
        why = "A shot comes in the build-up."
    elif c["interceptions"] >= 2:
        why = f"Going in, they intercept {c['interceptions']} times."
    elif c["pressures"] >= 3:
        why = f"Going in, they press {c['pressures']} times."
    elif c["passes"] >= 3:
        why = f"They play {c['passes']} passes in the three minutes before."
    else:
        why = ""
    return f"{opener}. {why}".strip()


def turning_point_cues(terrain: dict, events: list[dict]) -> list[dict]:
    """One cue per turning point and persona. The template is chosen by the facts (first spell or
    not, how long the previous one held, whether this one runs to the end, what the build-up held),
    so the same match always reads the same, and different matches read differently."""
    known = {e["id"]: e for e in (compact(e) for e in events)}
    by_minute = sorted(known.values(), key=lambda e: e["minute"])
    cues = []
    points = terrain["turning_points"]
    for n, point in enumerate(points):
        evidence = [i for i in point["source_ids"] if i in known]
        cited = [known[i] for i in evidence]
        team = point["team"]

        def cited_minute(minute: int) -> bool:
            return _cite_minute(minute, team, by_minute, cited, evidence)  # noqa: B023 (called in this iteration)

        if not cited_minute(point["minute"]):
            continue  # nothing to cite the minute with: no cue rather than an uncited number
        until = point["until"] if cited_minute(point["until"]) else None
        peak = point["peak_minute"]
        if peak in (point["minute"], point["until"]) or not cited_minute(peak):
            peak = None
        counts = _counts(cited, team)
        previous = points[n - 1] if n else None
        for persona in ("analyst", "casual", "audio"):
            text = _turning_text(point, previous, terrain["minutes"], counts, until, peak, persona)
            verdict = check(Claim(text, evidence), known)
            if not verdict.ok:
                raise ValueError(f"turning point {point['minute']}-{persona}: {verdict.reasons}")
            t_in = (point["minute"] - 1) * 60.0
            cue = {
                "id": f"cue-tp{point['minute']}-{persona}",
                "t_in": t_in,
                "t_out": t_in + TURNING_POINT_SECONDS,
                "kind": "audio_description" if persona == "audio" else "recap",
                "slot": "story",
                "anchor": None,
                "persona": persona,
                "lang": "en",
                "text": text,
                "verified": False,
                "replaces": None,
                "evidence": evidence,
            }
            validate(cue, SCHEMA)
            cues.append(cue)
    return cues


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--minutes", type=float, default=5)
    parser.add_argument("--terrain", type=Path, help="write turning-point cues for this terrain file")
    parser.add_argument("--clip", type=Path, help="clip directory the terrain was built from")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.terrain:
        if not args.clip:
            parser.error("--terrain needs --clip")
        terrain = json.loads(args.terrain.read_text())
        events = [json.loads(line) for line in open(args.clip / "events.jsonl")]
        write_fixture(turning_point_cues(terrain, events), args.out)
    else:
        write_fixture(asyncio.run(build_fixture(args.seed, args.minutes)), args.out)


if __name__ == "__main__":
    main()
