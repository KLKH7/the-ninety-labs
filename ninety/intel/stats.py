"""Deterministic football statistics and evidence-backed facts.

This module is deliberately model-free. It consumes the typed event and frame records
produced by the simulator (or later by vision) and returns facts with stable identifiers
and source ids. An agent may explain these facts, but must not calculate them.
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

PITCH_SPEED_CAP_KMH = 40.0
SPRINT_THRESHOLD_KMH = 25.0


@dataclass(frozen=True)
class Fact:
    """One computed value that can be cited by a downstream agent."""

    id: str
    metric: str
    value: float
    unit: str
    scope: str
    source_ids: tuple[str, ...] = ()

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "metric": self.metric,
            "value": self.value,
            "unit": self.unit,
            "scope": self.scope,
            "source_ids": list(self.source_ids),
        }


def _events(events: Iterable[Mapping]) -> list[Mapping]:
    return list(events)


def _round(value: float, places: int = 2) -> float:
    return round(float(value), places)


def _team(event: Mapping) -> str:
    return str(event["team"])


def _player(event: Mapping) -> str | None:
    player = event.get("player")
    return str(player) if player is not None else None


def _fact(metric: str, value: float, unit: str, scope: str, source_ids: Iterable[str]) -> Fact:
    safe_scope = scope.replace(":", "_")
    return Fact(
        id=f"{metric}:{safe_scope}",
        metric=metric,
        value=_round(value),
        unit=unit,
        scope=scope,
        source_ids=tuple(str(source_id) for source_id in source_ids),
    )


def pass_facts(events: Iterable[Mapping]) -> list[Fact]:
    """Return pass volume, completion, distance, and speed facts by team and player."""
    event_list = _events(events)
    passes = [event for event in event_list if event.get("type") == "pass"]
    fallback_ids = [str(event["id"]) for event in event_list]
    groups: dict[str, list[Mapping]] = defaultdict(list)
    groups.update({"home": [], "away": []})
    for event in passes:
        groups[_team(event)].append(event)
        if _player(event):
            groups[f"player:{_player(event)}"].append(event)

    facts: list[Fact] = []
    for scope, group in sorted(groups.items()):
        completed = [event for event in group if event.get("outcome") == "success"]
        distances = [float(event["distance_m"]) for event in group if event.get("distance_m") is not None]
        speeds = [
            float(event["ball_speed_kmh"])
            for event in group
            if event.get("ball_speed_kmh") is not None
        ]
        ids = [str(event["id"]) for event in group] or fallback_ids
        facts.extend(
            (
                _fact("passes_attempted", len(group), "passes", scope, ids),
                _fact("passes_completed", len(completed), "passes", scope,
                      [str(event["id"]) for event in completed] or ids),
                _fact(
                    "pass_completion_rate", len(completed) / len(group) if group else 0,
                    "ratio", scope, ids
                ),
            )
        )
        if distances:
            facts.append(_fact("pass_distance_mean", sum(distances) / len(distances), "m", scope, ids))
        if speeds:
            facts.append(_fact("pass_speed_mean", sum(speeds) / len(speeds), "km/h", scope, ids))
    return facts


def shot_facts(events: Iterable[Mapping]) -> list[Fact]:
    """Return shot volume, accuracy, goals, and speed facts by team and player."""
    event_list = _events(events)
    shots = [event for event in event_list if event.get("type") == "shot"]
    fallback_ids = [str(event["id"]) for event in event_list]
    groups: dict[str, list[Mapping]] = defaultdict(list)
    groups.update({"home": [], "away": []})
    for event in shots:
        groups[_team(event)].append(event)
        if _player(event):
            groups[f"player:{_player(event)}"].append(event)

    facts: list[Fact] = []
    for scope, group in sorted(groups.items()):
        ids = [str(event["id"]) for event in group] or fallback_ids
        on_target = [
            event for event in group if event.get("outcome") in {"on_target", "goal"}
        ]
        goals = [event for event in group if event.get("outcome") == "goal"]
        speeds = [
            float(event["ball_speed_kmh"])
            for event in group
            if event.get("ball_speed_kmh") is not None
        ]
        facts.extend(
            (
                _fact("shots", len(group), "shots", scope, ids),
                _fact("shots_on_target", len(on_target), "shots", scope,
                      [str(event["id"]) for event in on_target] or ids),
                _fact("shot_accuracy", len(on_target) / len(group) if group else 0,
                      "ratio", scope, ids),
                _fact("goals", len(goals), "goals", scope,
                      [str(event["id"]) for event in goals] or ids),
            )
        )
        if speeds:
            facts.append(_fact("shot_speed_mean", sum(speeds) / len(speeds), "km/h", scope, ids))
            facts.append(_fact("shot_speed_max", max(speeds), "km/h", scope, ids))
    return facts


def possession_facts(frames: Iterable[Mapping]) -> list[Fact]:
    """Compute possession share from frame-level possessor identities."""
    frames_list = _frames(frames)
    counts = Counter(
        str(frame["possessor"])[0]
        for frame in frames_list
        if frame.get("possessor") and str(frame["possessor"])[0] in {"h", "a"}
    )
    total = counts["h"] + counts["a"]
    if not total:
        return []
    source_ids = [str(frame["frame"]) for frame in frames_list if frame.get("possessor")]
    return [
        _fact("possession_share", counts["h"] / total, "ratio", "team:home", source_ids),
        _fact("possession_share", counts["a"] / total, "ratio", "team:away", source_ids),
        _fact("possession_frames", counts["h"], "frames", "team:home", source_ids),
        _fact("possession_frames", counts["a"], "frames", "team:away", source_ids),
    ]


def pressure_facts(events: Iterable[Mapping]) -> list[Fact]:
    """Count pressure events and recoveries by team."""
    event_list = _events(events)
    pressure = [event for event in event_list if event.get("type") == "pressure"]
    groups: dict[str, list[Mapping]] = defaultdict(list)
    for event in pressure:
        groups[_team(event)].append(event)
    facts: list[Fact] = []
    for team, group in sorted(groups.items()):
        ids = [str(event["id"]) for event in group]
        if not ids:
            continue
        facts.append(_fact("pressure_events", len(group), "events", f"team:{team}", ids))
    return facts


def player_movement_facts(frames: Iterable[Mapping]) -> list[Fact]:
    """Compute player distance, peak speed, and sprint frames from tracking frames."""
    frames_list = _frames(frames)
    if len(frames_list) < 2:
        return []
    by_player: dict[str, list[tuple[float, float, float, str]]] = defaultdict(list)
    for frame in frames_list:
        for player in frame.get("players", []):
            by_player[str(player["id"])].append(
                (float(frame["t"]), float(player["x"]), float(player["y"]), str(frame["frame"]))
            )

    facts: list[Fact] = []
    for player, samples in sorted(by_player.items()):
        distance = 0.0
        peak = 0.0
        sprint_frames = 0
        source_ids: list[str] = []
        for previous, current in zip(samples, samples[1:], strict=False):
            dt = current[0] - previous[0]
            if dt <= 0:
                continue
            speed_kmh = math.hypot(current[1] - previous[1], current[2] - previous[2]) / dt * 3.6
            # A malformed tracker sample should not create a spectacular statistic.
            speed_kmh = min(speed_kmh, PITCH_SPEED_CAP_KMH)
            distance += speed_kmh / 3.6 * dt
            peak = max(peak, speed_kmh)
            if speed_kmh >= SPRINT_THRESHOLD_KMH:
                sprint_frames += 1
            source_ids.append(current[3])
        scope = f"player:{player}"
        facts.extend(
            (
                _fact("distance_run", distance, "m", scope, source_ids),
                _fact("peak_speed", peak, "km/h", scope, source_ids),
                _fact("sprint_frames", sprint_frames, "frames", scope, source_ids),
            )
        )
    return facts


def control_vs_chaos(events: Iterable[Mapping], window_seconds: float = 60.0) -> list[Fact]:
    """Compute a transparent control-vs-chaos index per team.

    The index is the completed-pass share minus the normalized pressure and turnover
    rate in each time window. It is a deterministic descriptive signal, not a rating
    of a team or player.
    """
    if window_seconds <= 0:
        raise ValueError("window_seconds must be positive")
    event_list = _events(events)
    if not event_list:
        return []
    max_time = max(float(event.get("t", 0)) for event in event_list)
    window_count = int(max_time // window_seconds) + 1
    facts: list[Fact] = []
    for index in range(window_count):
        start, end = index * window_seconds, (index + 1) * window_seconds
        window = [event for event in event_list if start <= float(event.get("t", 0)) < end]
        for team in ("home", "away"):
            team_events = [event for event in window if _team(event) == team]
            passes = [event for event in team_events if event.get("type") == "pass"]
            completed = sum(event.get("outcome") == "success" for event in passes)
            pressure = sum(event.get("type") == "pressure" for event in window
                           if _team(event) != team)
            turnovers = sum(
                event.get("type") in {"interception", "tackle"} and _team(event) != team
                for event in window
            )
            denominator = max(len(passes), 1)
            index_value = (completed / denominator) - ((pressure + turnovers) / denominator) * 0.1
            ids = [str(event["id"]) for event in team_events]
            if not ids:
                continue
            facts.append(_fact("control_vs_chaos", index_value, "index",
                               f"team:{team}:window:{index}", ids))
    return facts


def _frames(frames: Iterable[Mapping]) -> list[Mapping]:
    return sorted(list(frames), key=lambda frame: (float(frame["t"]), int(frame["frame"])))


def calculate_facts(events: Iterable[Mapping], frames: Iterable[Mapping] = ()) -> list[Fact]:
    """Return all deterministic facts in stable order for agent and overlay consumers."""
    event_list = _events(events)
    frame_list = _frames(frames)
    facts = pass_facts(event_list) + shot_facts(event_list) + pressure_facts(event_list)
    if frame_list:
        facts += possession_facts(frame_list) + player_movement_facts(frame_list)
    facts += control_vs_chaos(event_list)
    return sorted(facts, key=lambda fact: fact.id)
