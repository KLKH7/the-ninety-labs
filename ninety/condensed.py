"""Match mode: a condensed match's chapters, scoreline and team stats, from the detected events.

    uv run ninety-e2e <clip> --out <bundle> --match        # writes match.json into the bundle

A condensed match is one clip whose picture cuts from one passage of play to the next (its segments,
ninety/match/timeline.py): played back to back at real speed, the match clock jumping at each cut.
The viewer's match mode (web/viewer/src/match.ts) shows what this computes:

- `chapters`: one per segment, from its first frame to its last. Its `kind` is the most telling
  confident detected event in it: a goal, then a save (a shot on target that was not a goal), then
  a shot, then a set piece or kick-off; with none of those it is build-up. The segments are the
  broadcast's own timecode; what a chapter is called comes only from the detected events, never
  from the answer key.
- `goals`: the scoreline over time, one entry per confident detected goal (a shot whose outcome is
  a goal, as ninety/intel/stats.py counts goals).
- `highlights`: the reel (ninety/highlights.py): every confident detected goal, the saves that
  beat a keeper's dive once that filter is measured, and a fan's label for each once vision's
  errors are measured.
- `stats`: each team's passes, shots and goals so far, from the footage shown: after every confident
  event, the same team facts the agents read (ninety/intel/stats.py), over the events up to it.

Confident means at or above the fact-checker's MIN_CONFIDENCE, the gate every graphic passes
(ninety/agents/cues.py): a number on screen never rests on a detection the agents would hold.
Reads the detected events and the clip's segments only; nothing here opens the answer key.
"""

from __future__ import annotations

from ninety import highlights
from ninety.agents.factcheck import MIN_CONFIDENCE, side_known
from ninety.intel.stats import pass_facts, shot_facts
from ninety.match.timeline import Timeline

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
    return e["type"] == "shot" and e.get("outcome") == "goal"


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
            if k and (best is None or KINDS.index(k) < KINDS.index(best[0])):
                best = (k, e)
        kind, event = best if best else ("build_up", None)
        label = LABEL[kind]
        if event is not None and event.get("team") in TEAMS:
            label += f", {event['team']}"
        if event is not None and event["type"] == "kickoff":
            label = f"Kick-off, {event['team']}" if event.get("team") in TEAMS else "Kick-off"
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


def build(clip_meta: dict, events: list[dict], verdict: highlights.Verdict | None = None) -> dict:
    """match.json for a clip (its clip.json) and its detected events; `verdict` is what the
    highlights measurement decided (ninety/highlights.py), none until it has run."""
    timeline = Timeline.of_clip(clip_meta)
    sure = confident(events)
    # A goal counts for a side only when that side was told surely (factcheck.side_known, lesson
    # 245); otherwise it is a goal with no team, in no club's score.
    goals = [{"t": e["t"], "team": e.get("team") if side_known(e) else None, "event": e["id"]}
             for e in sure if is_goal(e)]
    stats = [{"t": round(timeline.segs[0].frame / timeline.fps, 2), "event": None, **team_stats([])}]
    for i, e in enumerate(sure):
        now = team_stats(sure[: i + 1])
        if any(now[team] != stats[-1][team] for team in TEAMS):
            stats.append({"t": e["t"], "event": e["id"], **now})
    return {
        "format": FORMAT,
        "min_confidence": MIN_CONFIDENCE,
        "chapters": chapters(timeline, sure),
        "goals": goals,
        "stats": stats,
        "highlights": highlights.reel(sure, verdict),
    }
