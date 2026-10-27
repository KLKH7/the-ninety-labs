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

# The most common absolute sprint threshold in match analysis (docs/GROUNDING.md I22): the one
# constant every sprint count reads (ninety/intel/physical.py too).
SPRINT_THRESHOLD_KMH = 25.2
# Pre-registered (docs/EVALUATION.md, "Shot speed facts"): a team's or a player's shot speed is stated
# only when more than half of its shots carry a speed that may be said (factcheck.sayable_speed), so
# the figure describes most of its shots, never one reading standing in for all of them.
SHOT_SPEED_COVERAGE = 0.5
# A detector that writes none of these cannot count them as none (lesson 292): a count of them is
# stated only when the events hold at least one (window_facts's rule for PPDA).
PRESSING_TYPES = frozenset({"pressure", "tackle", "interception"})
# The longest a goal may follow the scoring side's shot for that shot to be its strike (GROUNDING I28):
# the longest shot-to-goal gap in the engine's ground truth, 2.16 s (42 goals over the 11 freeze-SHA
# matches, runs/f*-65247ba3), plus the 1.0 s event-time tolerance (EVALUATION, Vision scoring) for each
# of the two detected events. On seed 8324 the detected gaps are 0.52 to 2.12 s.
STRIKE_GAP_S = 2.16 + 2 * 1.0


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


def _distance(event: Mapping) -> float | None:
    """Compute pass distance from the event contract rather than a model-written field."""
    end_x, end_y = event.get("end_x"), event.get("end_y")
    if end_x is None or end_y is None:
        return None
    return math.hypot(float(end_x) - float(event["x"]), float(end_y) - float(event["y"]))


def _frame_span(frame_ids: Iterable[int]) -> tuple[str, ...]:
    """Cite frames as one inclusive range, so a 90-minute fact does not carry 135,000 ids."""
    ids = list(frame_ids)
    if not ids:
        return ()
    return (f"frames:{min(ids)}-{max(ids)}",)


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
    groups: dict[str, list[Mapping]] = defaultdict(list)
    groups.update({"team:home": [], "team:away": []})
    for event in passes:
        groups[f"team:{_team(event)}"].append(event)
        if _player(event):
            groups[f"player:{_player(event)}"].append(event)

    facts: list[Fact] = []
    for scope, group in sorted(groups.items()):
        completed = [event for event in group if event.get("outcome") == "success"]
        distances = [distance for event in group if (distance := _distance(event)) is not None]
        speeds = [
            float(event["ball_speed_kmh"])
            for event in group
            if event.get("ball_speed_kmh") is not None
        ]
        ids = [str(event["id"]) for event in group]
        facts.extend(
            (
                _fact("passes_attempted", len(group), "passes", scope, ids),
                _fact("passes_completed", len(completed), "passes", scope,
                      [str(event["id"]) for event in completed]),
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


def goal_moments(events: Iterable[Mapping]) -> list[tuple[Mapping, Mapping | None]]:
    """Each detected goal once, as (goal, its shot or None), in time order.

    A goal is a detected `goal` event (GROUNDING I24, Law 10). Its shot is the detected event just
    before it when that is a shot that went in, as scoring.goals pairs them: the strike and the ball
    over the line are one goal, and the goal event carries its side and confidence. A shot that went
    in with no goal event just after it is a goal on its own (a detector that writes no goal events);
    a goal with no shot just before it is a goal whose strike was not seen. An `out_of_play` between a
    shot and its goal is the ball crossing the goal line, the goal itself (Law 9 against Law 10), so it
    neither parts them nor makes them two goals (lesson 292)."""
    rows = [e for e in sorted(events, key=lambda e: (float(e["t"]), str(e["id"])))
            if e.get("type") != "out_of_play"]
    went_in = [e.get("type") == "shot" and e.get("outcome") == "goal" for e in rows]
    out: list[tuple[Mapping, Mapping | None]] = []
    for k, e in enumerate(rows):
        if e.get("type") == "goal":
            out.append((e, rows[k - 1] if k > 0 and went_in[k - 1] else None))
        elif went_in[k] and not (k + 1 < len(rows) and rows[k + 1].get("type") == "goal"):
            out.append((e, e))
    return out


def goal_strikes(events: Iterable[Mapping]) -> list[tuple[Mapping, Mapping | None]]:
    """Each goal (goal_moments) with the shot that struck it, or None when no shot of the scoring
    side was seen just before it. A goal is the whole ball over the line between the posts (Law 10,
    GROUNDING I24), so its strike was on target whatever outcome the detector gave it: the shot
    goal_moments pairs, else the event just before the goal when that is the scoring side's shot (on
    seed 8324 the 85th-minute goal follows a shot read `off_target`). An `out_of_play` between them is
    looked past, as goal_moments does. A shot more than STRIKE_GAP_S before the goal is not its strike
    (another passage of play, or a cut between them), so that goal is an implied shot instead."""
    rows = sorted(events, key=lambda e: (float(e["t"]), str(e["id"])))
    before: dict[str, Mapping] = {}
    last: Mapping | None = None
    for e in rows:
        if e.get("type") == "goal" and last is not None:
            before[str(e["id"])] = last
        if e.get("type") != "out_of_play":
            last = e
    out: list[tuple[Mapping, Mapping | None]] = []
    for goal, shot in goal_moments(rows):
        strike = shot if shot is not None else before.get(str(goal["id"]))
        if (strike is None or strike.get("type") != "shot" or strike.get("team") != goal.get("team")
                or float(goal["t"]) - float(strike["t"]) > STRIKE_GAP_S):
            strike = None
        out.append((goal, strike))
    return out


def shot_facts(events: Iterable[Mapping]) -> list[Fact]:
    """Return shot volume, accuracy, goals, and speed facts by team and player.

    Goals <= shots on target <= shots in every scope (lesson 292): a goal's strike counts on target
    (goal_strikes), and a goal whose strike was not seen is one implied shot on target for the scoring
    side, cited by the goal's own id. Shot speed is stated only from the shots whose speed may be said
    (factcheck.sayable_speed), citing those alone, when they are more than half the scope's shots
    (SHOT_SPEED_COVERAGE), with their count as `shot_speeds_measured`."""
    from ninety.agents.factcheck import sayable_speed  # the one rule for a speed that may be said

    event_list = _events(events)
    shots = [event for event in event_list if event.get("type") == "shot"]
    groups: dict[str, list[Mapping]] = defaultdict(list)
    groups.update({"team:home": [], "team:away": []})
    for event in shots:
        groups[f"team:{_team(event)}"].append(event)
        if _player(event):
            groups[f"player:{_player(event)}"].append(event)
    # Goals by the goal event's side (goal_moments); a player's only when his shot scored it for
    # that side (I24's scorer).
    scored: dict[str, list[Mapping]] = defaultdict(list)
    for goal, shot in goal_moments(event_list):
        scored[f"team:{_team(goal)}"].append(goal)
        if shot is not None and _player(shot) and shot.get("team") == goal.get("team"):
            scored[f"player:{_player(shot)}"].append(goal)
    for scope in scored:
        groups.setdefault(scope, [])
    # Each goal's strike is on target; a goal with no strike seen is an implied shot, cited by the goal.
    struck: set[str] = set()
    implied: dict[str, list[Mapping]] = defaultdict(list)
    for goal, strike in goal_strikes(event_list):
        if strike is None:
            implied[f"team:{_team(goal)}"].append(goal)
        else:
            struck.add(str(strike["id"]))

    facts: list[Fact] = []
    for scope, group in sorted(groups.items()):
        all_shots = group + implied.get(scope, [])
        ids = [str(event["id"]) for event in all_shots]
        on_target = [
            event for event in group
            if event.get("outcome") in {"on_target", "goal"} or str(event["id"]) in struck
        ] + implied.get(scope, [])
        goals = scored.get(scope, [])
        measured = [event for event in group if sayable_speed(dict(event))]
        speeds = [float(event["ball_speed_kmh"]) for event in measured]
        facts.extend(
            (
                _fact("shots", len(all_shots), "shots", scope, ids),
                _fact("shots_on_target", len(on_target), "shots", scope,
                      [str(event["id"]) for event in on_target]),
                _fact("shot_accuracy", len(on_target) / len(all_shots) if all_shots else 0,
                      "ratio", scope, ids),
                _fact("goals", len(goals), "goals", scope,
                      [str(event["id"]) for event in goals]),
            )
        )
        if speeds and len(speeds) > SHOT_SPEED_COVERAGE * len(group):
            cited = [str(event["id"]) for event in measured]
            facts.append(_fact("shot_speed_mean", sum(speeds) / len(speeds), "km/h", scope, cited))
            facts.append(_fact("shot_speed_max", max(speeds), "km/h", scope, cited))
            facts.append(_fact("shot_speeds_measured", len(speeds), "shots", scope, cited))
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
    source_ids = _frame_span(int(frame["frame"]) for frame in frames_list if frame.get("possessor"))
    home_share = _round(counts["h"] / total)
    return [
        _fact("possession_share", home_share, "ratio", "team:home", source_ids),
        _fact("possession_share", 1 - home_share, "ratio", "team:away", source_ids),
        _fact("possession_frames", counts["h"], "frames", "team:home", source_ids),
        _fact("possession_frames", counts["a"], "frames", "team:away", source_ids),
    ]


def detects_pressing(events: Iterable[Mapping]) -> bool:
    """Whether the events' source detects pressing at all: one pressure, tackle or interception among
    them. Vision writes none of these yet (#386), so its count of them is unmeasured, never zero."""
    return any(event.get("type") in PRESSING_TYPES for event in events)


def pressure_facts(events: Iterable[Mapping]) -> list[Fact]:
    """Count pressure events by team; nothing when the source detects no pressing (a side's zero is
    stated only when the source could have seen one)."""
    event_list = _events(events)
    if not detects_pressing(event_list):
        return []
    pressure = [event for event in event_list if event.get("type") == "pressure"]
    facts: list[Fact] = []
    for team in ("away", "home"):
        ids = [str(event["id"]) for event in pressure if _team(event) == team]
        facts.append(_fact("pressure_events", len(ids), "events", f"team:{team}", ids))
    return facts


@dataclass(frozen=True)
class Step:
    """One player's move from one frame to the next: where from and to, in pitch metres."""

    player: str
    team: str | None
    t: float  # when the step ends
    frame: int  # the frame it ends on
    previous_frame: int
    x0: float
    y0: float
    x1: float
    y1: float
    dt: float


def player_steps(frames: Iterable[Mapping], restarts: Iterable[int] = ()) -> dict[str, list[Step]]:
    """Each player's frame-to-frame steps, oldest first: what every movement statistic reads.

    `restarts` are the frames of kickoff events. A kickoff resets everyone to their own half at
    once (a legal case of the data contract, which the validator's P1 skips too), so the step into
    a kickoff frame is not movement; every other step counts, uncapped, so a teleport still shows."""
    reset = {int(frame) for frame in restarts}
    by_player: dict[str, list[tuple[float, float, float, int, str | None]]] = defaultdict(list)
    for frame in _frames(frames):
        for player in frame.get("players", []):
            by_player[str(player["id"])].append(
                (float(frame["t"]), float(player["x"]), float(player["y"]), int(frame["frame"]),
                 player.get("team"))
            )
    steps: dict[str, list[Step]] = {}
    for player, samples in sorted(by_player.items()):
        steps[player] = [
            Step(player, current[4], current[0], current[3], previous[3],
                 previous[1], previous[2], current[1], current[2], current[0] - previous[0])
            for previous, current in zip(samples, samples[1:], strict=False)
            if current[0] - previous[0] > 0 and current[3] not in reset
        ]
    return steps


def player_movement_facts(frames: Iterable[Mapping], restarts: Iterable[int] = ()) -> list[Fact]:
    """Compute player distance, peak speed, and sprint frames from tracking frames, over
    `player_steps` (so a kickoff reset in `restarts` is not movement)."""
    frames_list = _frames(frames)
    if len(frames_list) < 2:
        return []
    facts: list[Fact] = []
    for player, steps in player_steps(frames_list, restarts).items():
        distance = 0.0
        peak = 0.0
        sprint_frames = 0
        cited: list[int] = []
        for step in steps:
            speed_kmh = math.hypot(step.x1 - step.x0, step.y1 - step.y0) / step.dt * 3.6
            distance += speed_kmh / 3.6 * step.dt
            peak = max(peak, speed_kmh)
            if speed_kmh >= SPRINT_THRESHOLD_KMH:
                sprint_frames += 1
            cited += [step.previous_frame, step.frame]
        source_ids = _frame_span(cited)
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
    """Compute the documented experimental control-vs-chaos index per team. Its chaos is pressure and
    recoveries, so a source that detects no pressing gets no index (it would be pass completion under
    another name)."""
    if window_seconds <= 0:
        raise ValueError("window_seconds must be positive")
    event_list = _events(events)
    if not event_list or not detects_pressing(event_list):
        return []
    max_time = max(float(event.get("t", 0)) for event in event_list)
    window_count = int(max_time // window_seconds) + 1
    facts: list[Fact] = []
    for index in range(window_count):
        start, end = index * window_seconds, (index + 1) * window_seconds
        window = [event for event in event_list if start <= float(event.get("t", 0)) < end]
        for team in ("home", "away"):
            passes = [e for e in window if _team(e) == team and e.get("type") == "pass"]
            completed = sum(event.get("outcome") == "success" for event in passes)
            opponent = [e for e in window if _team(e) != team]
            pressure = [e for e in opponent if e.get("type") == "pressure"]
            recoveries = [e for e in opponent if _is_recovery(e)]
            denominator = max(len(passes), 1)
            control = completed / denominator
            chaos = min(1.0, (len(pressure) + len(recoveries)) / denominator)
            index_value = control - chaos
            ids = [str(event["id"]) for event in passes + pressure + recoveries]
            if not ids:
                continue
            facts.append(_fact("control_vs_chaos", index_value, "index",
                               f"team:{team}:window:{index}", ids))
    return facts


def _is_recovery(event: Mapping) -> bool:
    """An interception, or a tackle that won the ball. A failed tackle recovers nothing."""
    if event.get("type") == "interception":
        return True
    return event.get("type") == "tackle" and event.get("outcome") == "success"


def _frames(frames: Iterable[Mapping]) -> list[Mapping]:
    return sorted(list(frames), key=lambda frame: (float(frame["t"]), int(frame["frame"])))


def calculate_facts(events: Iterable[Mapping], frames: Iterable[Mapping] = ()) -> list[Fact]:
    """Return all deterministic facts in stable order for agent and overlay consumers."""
    event_list = _events(events)
    frame_list = _frames(frames)
    facts = pass_facts(event_list) + shot_facts(event_list) + pressure_facts(event_list)
    if frame_list:
        kickoffs = [int(e["frame"]) for e in event_list if e.get("type") == "kickoff" and "frame" in e]
        facts += possession_facts(frame_list) + player_movement_facts(frame_list, kickoffs)
    facts += control_vs_chaos(event_list)
    from ninety.intel.windows import territory_shifts, window_facts  # it builds on this module

    facts += window_facts(event_list) + territory_shifts(event_list)
    return sorted(facts, key=lambda fact: fact.id)
