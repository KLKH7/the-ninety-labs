"""Active perception: when a claim rests on evidence the fact-checker cannot trust, look again.

The fact-checker holds a claim whose cited detection is unsure (its `confidence` below the gate) or
that names a side told unsurely (`factcheck.side_known`). Holding is safe, but it airs nothing. With
a clip seen by more than one camera, the agent can do what a human analyst does: look again, from
another angle. `re_perceive` re-runs R3's own event detection (`ninety.vision.events.detect`, code
over the detector's boxes on the pitch, unchanged) on one camera's observations:

- mode `window`: that camera's frames within WINDOW_S / 2 of the event (a 3 s look);
- mode `track`: that camera's whole clip, so each track's side is voted over every frame it was
  seen in (the per-track side vote), not only the frames around the moment. Only this reading may
  re-read a side: the side threshold was measured on whole-clip votes, and a window's vote is more
  one-sided than the clip's whether it is right or not. A window look may confirm a detection.

The re-perceived event counts only if the same event is found there: the same type, within
MATCH_S of the event and MATCH_M of where it was (the event scorer's own rules,
docs/EVALUATION.md). What it adds is written to the Ledger with `source: re_perceive`, and the
fact-checker decides again on the evidence with the new reading:

- confirmed: the other camera saw the same event, confidently enough to pass the gate (and the same
  side, told surely enough, when the claim names one): the claim goes back through the whole
  fact-checker and airs if it passes;
- contradicted: it saw the same event for the other side: the claim stays held, and says why;
- not found, or found but no surer: held, as before.

Nothing here reads ground truth: only observations, the vision pipeline's own output. A look costs
CPU, not a model call, and is capped at MAX_PER_MINUTE a match minute; every look is logged.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

from ninety.agents.factcheck import MIN_CONFIDENCE, TEAM_NAMED, side_known

# Design (the Coordinator's brief): a look is at most a 3 s window of video.
WINDOW_S = 3.0
# The event scorer's rules for "the same event" (docs/EVALUATION.md, event detection: same type and
# team, within 1.0 s; the lenient spot rule, 2.0 m).
MATCH_S = 1.0
MATCH_M = 2.0
# Design: at most three looks a match minute, the most moments the workflow explains in one
# (workflow.MAX_MOMENTS_PER_MINUTE): one look per held moment. A look is CPU, not a model call, but
# a match minute's re-checks must not hold up its graphics.
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

    def spend(self, minute: int) -> bool:
        """Take one of the minute's looks, if any are left."""
        if self.spent.get(minute, 0) >= MAX_PER_MINUTE:
            return False
        self.spent[minute] = self.spent.get(minute, 0) + 1
        return True


def doubtful(claim_text: str, evidence: Iterable[Mapping]) -> list[Mapping]:
    """The cited detections the gate distrusts: below the detection confidence, or, for a claim that
    names a side, with a side not told surely."""
    names_side = TEAM_NAMED.search(claim_text) is not None
    out = []
    for e in evidence:
        if e.get("confidence") is None or e.get("type") in (None, "stat", "shape"):
            continue  # ground truth, a stat or a shape fact: nothing to look at again
        if e["confidence"] < MIN_CONFIDENCE or (names_side and not side_known(e)):
            out.append(e)
    return out


def recheck(perceiver: Perceiver, claim_text: str, scope: dict[str, dict], minute: int,
            own_camera: str | None = None) -> tuple[dict[str, dict] | None, list[Look]]:
    """Look again at each doubtful cited detection, through each other camera, a window first and
    then the whole track. Returns the scope with the confirmed readings in place (None when a look
    contradicts the side, or nothing was confirmed) and the looks taken."""
    names_side = TEAM_NAMED.search(claim_text) is not None
    updated, looks, confirmed = dict(scope), [], 0
    targets = doubtful(claim_text, scope.values())
    for event in targets:
        done = False
        for camera in sorted(c for c in perceiver.views if c != own_camera):
            for mode in MODES:
                if done or not perceiver.spend(minute):
                    continue
                look = perceiver.re_perceive(event, camera, mode)
                looks.append(look)
                perceiver.looks.append(look)
                found = look.found
                if found is None:
                    continue
                if found["team"] != event["team"]:
                    look.why = f"{camera} saw it for the other side ({found['team']})"
                    return None, looks
                reading = {**event, "confidence": max(event["confidence"], found["confidence"] or 0.0)}
                # Only the whole-clip vote re-reads the side: MIN_TEAM_CONFIDENCE was measured on that
                # reading. A 3 s window's vote is more one-sided than the clip's, whoever is right:
                # on the M1 clip it read the false v00003's side at 1.0 (lesson 227).
                if look.mode == "track" and found.get("team_confidence") is not None:
                    reading["team_confidence"] = max(event.get("team_confidence") or 0.0,
                                                     found["team_confidence"])
                sure = reading["confidence"] >= MIN_CONFIDENCE and (not names_side or side_known(reading))
                look.why = f"{camera} saw it" + (", surely enough" if sure else ", no surer")
                if sure:
                    updated[event["id"]] = {**reading, "re_perceived": look.as_dict()}
                    confirmed += 1
                    done = True
    return (updated if targets and confirmed == len(targets) else None), looks


__all__ = ["MAX_PER_MINUTE", "MODES", "WINDOW_S", "Look", "Perceiver", "doubtful", "recheck"]
