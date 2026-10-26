"""Match mode: a condensed match's chapters, goals and team stats, from the detected events.

    uv run ninety-e2e <clip> --out <bundle> --match        # writes match.json into the bundle

A condensed match is one clip whose picture cuts from one passage of play to the next (its segments,
ninety/match/timeline.py): played back to back at real speed, the match clock jumping at each cut.
The viewer's match mode (web/viewer/src/match.ts) shows what this computes:

- `chapters`: one per segment, from its first frame to its last. Its `kind` is the most telling
  confident detected event in it: a goal, then a save (a shot on target that was not a goal), then
  a shot, then a set piece or kick-off; with none of those it is build-up. The segments are the
  broadcast's own timecode; what a chapter is called comes only from the detected events, never
  from the answer key.
- `goals`: one entry per confident detected goal (a `goal` event, merged with the shot that scored
  it: stats.goal_moments, GROUNDING I24), in time order, each with the goal event's side only when
  told surely. What
  vision saw, never a scoreline: vision misses goals, so a count of these would contradict the
  scorebug; the score is the scorebug's reading (ninety/intel/scoring.py, GROUNDING I24).
- `highlights`: the reel (ninety/highlights.py): every confident detected goal, the saves that
  beat a keeper's dive once that filter is measured, and a fan's label for each once vision's
  errors are measured.
- `stats`: each team's passes, shots and goals so far, from the footage shown: after every confident
  event on a side told surely, the same team facts the agents read (ninety/intel/stats.py), over
  those events up to it.

Confident means at or above the fact-checker's MIN_CONFIDENCE, the gate every graphic passes
(ninety/agents/cues.py): a number on screen never rests on a detection the agents would hold.
Reads the detected events and the clip's segments only; nothing here opens the answer key.
"""

from __future__ import annotations

from ninety import highlights
from ninety.agents.factcheck import MIN_CONFIDENCE, SCOREBUG_SIDE, side_known
from ninety.intel.scoring import SCOREBUG_MEASURED
from ninety.intel.stats import goal_moments, pass_facts, shot_facts
from ninety.match.timeline import Timeline
from ninety.vision.scorebug import W_S  # the reconciler's window: how far a score change may be from its goal

FORMAT = 1
TEAMS = ("home", "away")
# The team facts shown, by their metric in ninety/intel/stats.py.
STATS = ("passes_attempted", "passes_completed", "shots", "shots_on_target", "goals")
# Chapter kinds, most telling first.
KINDS = ("goal", "save", "shot", "set_piece", "build_up")
LABEL = {"goal": "Goal", "save": "Shot saved", "shot": "Shot", "set_piece": "Set piece",
         "build_up": "Build-up"}


def confident(events: list[dict]) -> list[dict]:
    return sorted((e for e in events if (e.get("confidence") or 0.0) >= MIN_CONFIDENCE),
                  key=lambda e: (e["t"], e["id"]))


def is_goal(e: dict) -> bool:
    """A goal event, or a shot that went in (stats.goal_moments merges the two into one goal)."""
    return e["type"] == "goal" or (e["type"] == "shot" and e.get("outcome") == "goal")


def kind_of(e: dict) -> str | None:
    if is_goal(e):
        return "goal"
    if e["type"] == "shot":
        return "save" if e.get("outcome") == "on_target" else "shot"
    if e["type"] in ("set_piece", "kickoff"):
        return "set_piece"
    return None


def team_stats(events: list[dict]) -> dict[str, dict[str, float]]:
    """The team facts the agents read (ninety/intel/stats.py), for these events."""
    out = {team: dict.fromkeys(STATS, 0) for team in TEAMS}
    for fact in pass_facts(events) + shot_facts(events):
        scope, metric = fact.scope, fact.metric
        if metric in STATS and scope.startswith("team:") and scope.count(":") == 1:
            team = scope.split(":")[1]
            if team in out:
                out[team][metric] = int(fact.value)
    return out


def chapters(timeline: Timeline, events: list[dict]) -> list[dict]:
    fps = timeline.fps
    out = []
    for n, seg in enumerate(timeline.segs):
        t0, t1 = seg.frame / fps, (seg.frame + seg.frames - 1) / fps
        inside = [e for e in events if t0 <= e["t"] <= t1]
        best = None
        for e in inside:
            k = kind_of(e)
            # A goal's own event, not its shot, names the chapter: it carries the goal's side.
            rank = None if k is None else (KINDS.index(k), e["type"] != "goal")
            if rank is not None and (best is None or rank < best[0]):
                best = (rank, k, e)
        kind, event = best[1:] if best else ("build_up", None)
        label = LABEL[kind]
        # A chapter names a side only when it was told surely (factcheck.side_known, lesson 245), as
        # match.json's goals do: the scrubber never says a club the goal list leaves out.
        sided = event is not None and event.get("team") in TEAMS and side_known(event)
        if sided:
            label += f", {event['team']}"
        if event is not None and event["type"] == "kickoff":
            label = f"Kick-off, {event['team']}" if sided else "Kick-off"
        out.append({
            "n": n + 1,
            "index": seg.index,  # the clip image it starts on
            "frames": seg.frames,
            "t": round(t0, 2),  # match time of its first and last frames
            "t_end": round(t1, 2),
            "kind": kind,
            "label": label,
            "event": None if event is None else event["id"],
            "event_t": None if event is None else event["t"],
        })
    return out


def cut_between(timeline: Timeline):
    """Whether the broadcast cut between match times t0 and t1: they are in different segments."""
    fps = timeline.fps

    def seg(t: float) -> int:
        i = 0
        for n, s in enumerate(timeline.segs):
            if s.frame <= t * fps + 1e-6:
                i = n
        return i

    return lambda t0, t1: seg(t0) != seg(t1)


def scorebug_sides(events: list[dict], readings: list[dict] | None) -> list[dict]:
    """The events with each goal that a score change confirms sided by the scorebug: the club whose
    digit changed, `team_source` "scorebug", which factcheck.side_known accepts as told surely.

    Why that is sure: on the scorebug's validation (docs/eval/scorebug-validation.json, #356) the
    reader found 16 of 16 goals with no false change and every change on the right side: precision
    16/16, Wilson 95% interval 0.81 to 1.0 (the lower bound is under the tracker's 0.96 side gate;
    16 goals cannot show more). Only while the reader is measured (scoring.SCOREBUG_MEASURED) and
    only from a change at or above the fact-checker's confidence gate, as the phone shows the score.
    Every other event keeps the tracker's side and its 0.96 gate."""
    if not readings or not SCOREBUG_MEASURED:
        return events
    changes = [c for c in readings if c["type"] == "score_change" and c.get("team") in TEAMS
               and (c.get("confidence") or 0.0) >= MIN_CONFIDENCE]
    sided, used = {}, set()
    for goal, _ in goal_moments(events):
        near = sorted((c for c in changes if c["id"] not in used and abs(c["t"] - goal["t"]) <= W_S),
                      key=lambda c: abs(c["t"] - goal["t"]))
        if near:
            used.add(near[0]["id"])
            sided[goal["id"]] = {**goal, "team": near[0]["team"], "team_source": SCOREBUG_SIDE}
    return [sided.get(e["id"], e) for e in events]


def build(clip_meta: dict, events: list[dict], verdict: highlights.Verdict | None = None,
          scorebug: list[dict] | None = None) -> dict:
    """match.json for a clip (its clip.json) and its detected events; `verdict` is what the
    highlights measurement decided (ninety/highlights.py), none until it has run; `scorebug` the
    broadcast scorebug's readings (scorebug.jsonl), which side the goals they confirm."""
    timeline = Timeline.of_clip(clip_meta)
    events = scorebug_sides(events, scorebug)
    sure = confident(events)
    # A goal counts for a side only when that side was told surely (factcheck.side_known, lesson
    # 245); otherwise it is a goal with no team, in no club's score.
    goals = [{"t": g["t"], "team": g.get("team") if side_known(g) else None, "event": g["id"]}
             for g, _ in goal_moments(events) if (g.get("confidence") or 0.0) >= MIN_CONFIDENCE]
    # A club's stats count only the events whose side was told surely (the same gate, UI inventory #7):
    # an event on an unsure side is in no club's numbers, as it is under no club's name.
    sided = [e for e in sure if side_known(e)]
    stats = [{"t": round(timeline.segs[0].frame / timeline.fps, 2), "event": None, **team_stats([])}]
    for i, e in enumerate(sided):
        now = team_stats(sided[: i + 1])
        if any(now[team] != stats[-1][team] for team in TEAMS):
            stats.append({"t": e["t"], "event": e["id"], **now})
    return {
        "format": FORMAT,
        "min_confidence": MIN_CONFIDENCE,
        "chapters": chapters(timeline, sure),
        "goals": goals,
        "stats": stats,
        "highlights": highlights.reel(sure, verdict, cut_between(timeline)),
    }
