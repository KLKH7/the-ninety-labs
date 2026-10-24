"""Active perception: when a claim rests on evidence the fact-checker cannot trust, look again.

The fact-checker holds a claim whose cited detection is unsure (its `confidence` below the gate) or
that names a side told unsurely (`factcheck.side_known`). Holding is safe, but it airs nothing. With
a clip seen by more than one camera, the agent can do what a human analyst does: look again, from
another angle. `re_perceive` re-runs R3's own event detection (`ninety.vision.events.detect`, code
over the detector's boxes on the pitch, unchanged) on one camera's observations:

- mode `window`: that camera's frames within WINDOW_S / 2 of the event (a 3 s look);
- mode `track`: that camera's whole clip, so each track's side is voted over every frame it was
  seen in (the per-track side vote), not only the frames around the moment. No look re-reads a
  side (lesson 227): the side threshold was measured on the broadcast clip's whole-clip vote, and
  every camera's and window's vote is another reading until it is measured. A whole-clip look that
  tells the other side may still keep a claim held.

The re-perceived event counts only if the same event is found there: the same type, within
MATCH_S of the event and MATCH_M of where it was (the event scorer's own rules,
docs/EVALUATION.md). What it adds is written to the Ledger with `source: re_perceive`, and the
fact-checker decides again on the evidence with the new reading:

- confirmed: the other camera saw the same event, confidently enough to pass the detection gate:
  the claim goes back through the whole fact-checker and airs if it passes. A side is never
  re-read by a look (see `recheck`), so a claim naming a side unsure stays held;
- contradicted: a whole-clip look told the other side: the claim stays held, and says why;
- not found, or found but no surer: held, as before.

Measured on 22 validation clips (docs/eval/re-perceive.md). Nothing here reads ground truth: only
observations, the vision pipeline's own output. A look costs CPU, not a model call, and the
workflow's are capped at MAX_PER_MINUTE a match minute and logged. The MCP tool `re_perceive`
(ninety/mcp/match_server.py) is neither capped nor logged; no published agent may call it yet.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, replace

from ninety.agents.factcheck import MIN_CONFIDENCE, TEAM_NAMED, side_known

# Design (the Coordinator's brief): a look is at most a 3 s window of video.
WINDOW_S = 3.0
# The event scorer's rules for "the same event" (docs/EVALUATION.md, event detection): the same type,
# within 1.0 s, and the lenient spot rule, 2.0 m. Not the team: a look never re-reads a side
# (`recheck`), so a side told differently is still the same event, and can only keep a claim held.
MATCH_S = 1.0
MATCH_M = 2.0
# Design: at most three looks a match minute (CPU, not a model call, but a minute's re-checks must not
# hold up its graphics). One doubtful detection takes a window and a whole-clip look per camera, so
# with two cameras the first held moment of a minute can use them all; a look already taken is reused.
MAX_PER_MINUTE = 3
MODES = ("window", "track")


@dataclass
class Look:
    """One re-perception: what was asked and what came back."""

    event: str
    camera: str
    mode: str
    found: dict | None  # the same event as this camera saw it, or None
    why: str  # what the look decided, in words the trace shows

    def as_dict(self) -> dict:
        return {"event": self.event, "camera": self.camera, "mode": self.mode, "found": self.found,
                "why": self.why}


def _same(a: Mapping, b: Mapping) -> bool:
    return (a["type"] == b["type"] and abs(float(a["t"]) - float(b["t"])) <= MATCH_S
            and math.hypot(float(a["x"]) - float(b["x"]), float(a["y"]) - float(b["y"])) <= MATCH_M)


@dataclass
class Perceiver:
    """The clip's cameras, each as the observation rows the vision pipeline wrote for it
    (`views/<name>/observations.jsonl` from ninety/vision/live_job.py), and the looks taken."""

    views: dict[str, list[dict]]
    looks: list[Look] = field(default_factory=list)
    spent: dict[int, int] = field(default_factory=dict)  # match minute -> looks taken
    memo: dict[tuple[str, str, str], Look] = field(default_factory=dict)

    def re_perceive(self, event: Mapping, camera: str, mode: str) -> Look:
        """Look at `event` again through `camera`, in `mode` (see the module docstring)."""
        from ninety.vision import events as vision_events  # R3's detector, unchanged

        if camera not in self.views:
            return Look(event["id"], camera, mode, None, f"no camera {camera!r} for this clip")
        if mode not in MODES:
            return Look(event["id"], camera, mode, None, f"no mode {mode!r}")
        rows = self.views[camera]
        if mode == "window":
            t = float(event["t"])
            rows = [r for r in rows if abs(float(r["t"]) - t) <= WINDOW_S / 2]
        if not rows:
            return Look(event["id"], camera, mode, None, f"{camera} has no frames there")
        try:
            seen, _ = vision_events.detect(rows)
        except (ValueError, KeyError, ZeroDivisionError) as e:  # too little to read: nothing found
            return Look(event["id"], camera, mode, None, f"{camera} could not be read: {type(e).__name__}")
        same = [e for e in seen if _same(e, event)]
        if not same:
            return Look(event["id"], camera, mode, None, f"{camera} did not see it")
        best = min(same, key=lambda e: (abs(float(e["t"]) - float(event["t"])), e["id"]))
        found = {k: best.get(k) for k in ("type", "t", "team", "team_confidence", "player", "confidence")}
        return Look(event["id"], camera, mode, found, f"{camera} saw it")

    def cached(self, event: Mapping, camera: str, mode: str) -> Look | None:
        """A look already taken at this event through this camera in this mode: looks are
        deterministic, so a second claim on the same moment (the Challenger's) reuses it."""
        return self.memo.get((event["id"], camera, mode))

    def remember(self, look: Look) -> Look:
        self.memo[(look.event, look.camera, look.mode)] = look
        self.looks.append(look)
        return look

    def spend(self, minute: int) -> bool:
        """Take one of the minute's looks, if any are left."""
        if self.spent.get(minute, 0) >= MAX_PER_MINUTE:
            return False
        self.spent[minute] = self.spent.get(minute, 0) + 1
        return True


def doubtful(claim_text: str, cited: Iterable[Mapping]) -> list[Mapping]:
    """The cited detections the gate distrusts: below the detection confidence, or, for a claim that
    names a side, with a side not told surely."""
    names_side = TEAM_NAMED.search(claim_text) is not None
    out = []
    for e in cited:
        if e.get("confidence") is None or e.get("type") in (None, "stat", "shape"):
            continue  # ground truth, a stat or a shape fact: nothing to look at again
        if e["confidence"] < MIN_CONFIDENCE or (names_side and not side_known(e)):
            out.append(e)
    return out


def recheck(perceiver: Perceiver, claim_text: str, evidence: list[str], scope: dict[str, dict],
            located: Mapping[str, Mapping], minute: int,
            own_camera: str | None = None) -> tuple[dict[str, dict] | None, list[Look]]:
    """Look again at each doubtful detection the claim cites (`evidence`), through each other camera,
    a window first and then the whole track. `scope` is what the fact-checker checks (compact
    events); `located` gives each detection's time and place (the full detected events), which a
    look needs to find it. Returns the scope with confirmed readings in place, or None, and the looks.

    What a look may decide, until a camera's own reading is measured (lesson 227):
    - it may confirm a DETECTION (seen there, at or above the detection gate);
    - it never re-reads a SIDE: MIN_TEAM_CONFIDENCE was measured on the broadcast clip's whole-clip
      vote, and a tactical lens's vote is another reading (wrong sides reach 0.994 there, and the
      lenses are the fused reading's own inputs). So a claim naming a side stays held on its side;
    - a whole-clip look that tells the other side, by name, keeps the claim held, with that reason
      (holding is always safe); a window's side, or an unknown one, decides nothing."""
    names_side = TEAM_NAMED.search(claim_text) is not None
    cited = [scope[i] for i in evidence if i in scope]
    if names_side and any(e.get("confidence") is not None and not side_known(e) for e in cited):
        return None, []  # held on its side, which no look can re-read: spend no look on it
    targets = doubtful(claim_text, cited)
    looks: list[Look] = []
    updated, confirmed = dict(scope), 0
    for event in targets:
        where = {**event, **{k: located.get(event["id"], {}).get(k) for k in ("t", "x", "y")}}
        if any(where.get(k) is None for k in ("t", "x", "y")):
            continue  # nowhere to look: the event's time and place are unknown
        seen = None
        for camera in sorted(c for c in perceiver.views if c != own_camera):
            for mode in MODES:
                look = perceiver.cached(where, camera, mode)
                if look is None:
                    if not perceiver.spend(minute):
                        continue
                    look = perceiver.remember(perceiver.re_perceive(where, camera, mode))
                look = replace(look)  # this claim's own copy: its reason is this claim's
                looks.append(look)
                found = look.found
                if found is None:
                    continue
                if mode == "track" and found.get("team") not in (None, event["team"]):
                    look.why = f"{camera} told the other side ({found['team']}) over the whole clip"
                    return None, looks
                if (found.get("confidence") or 0.0) >= MIN_CONFIDENCE:
                    seen = seen or look
        if seen is None:
            continue
        reading = {**event, "confidence": max(event["confidence"], seen.found["confidence"])}
        sure = reading["confidence"] >= MIN_CONFIDENCE and (not names_side or side_known(reading))
        seen.why = f"{seen.camera} saw it" + ("; detection confirmed" if sure else
                                               "; the side stays unsure (a look never re-reads it)")
        if sure:
            updated[event["id"]] = {**reading, "re_perceived": seen.as_dict()}
            confirmed += 1
    return (updated if targets and confirmed == len(targets) else None), looks


__all__ = ["MAX_PER_MINUTE", "MODES", "WINDOW_S", "Look", "Perceiver", "doubtful", "recheck"]
