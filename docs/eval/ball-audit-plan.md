# Vision Auditor, round 1: where the ball detector misses (plan, written before any count)

Step 1 of the self-improving loop: the agents find what vision gets wrong, and ask our own engine
for exactly those scenes. This page fixes the question and the rule before the audit runs. Option A,
tonight: free and local only. There is no retrain, so no gain is claimed.

## Why look here

A development check on the demo match (seed 8080, vision-restarts, Oct 24) saw two things:
- A ball at the corner arc, fully visible (~47 px), scored 0.2 to 0.4 for the whole wait, below
  the 0.5 threshold.
- A ball still on the far touchline (~30 px) was detected in 9 of 91 frames.

The hypothesis: the training renders hold few stationary balls at the lines, a distribution gap.
The demo is a development clip, so it only suggests where to look. The audit runs on validation.

## The data (validation only; no test clip)

Broadcast observations made by the live path, ours-freeze, untiled, each beside its clip's answer
key:
- the shot-outcome set's 80 validation clips (seeds 910001 to 910008; render eb6bd41, observe at
  #271's ee4c7423);
- the tactical1 validation clips with a broadcast live run (`runs/tactical1/join/runs`, seeds 108,
  109, 110, 113, 114, 115 and 116).

## The rule (fixed now)

- **A ball to find:** every frame whose true ball has a box with some of it visible
  (`vision_score._visible`).
- **Found:** a detected ball at or above the 0.5 score threshold, within 5 px of the true centre.
  This is the pixel scorer's ball rule (`vision_score`), so the audit and the scorer can't drift.
- **Dead:** the true ball's speed under 0.1 m/s, from its own positions one frame either side. The
  answer key is exact, and a ball set for a restart does not move.
- **At a line:** the true ball within 2 m of the nearest pitch marking, arcs included
  (`pitch.pitch_polylines`).
- **The metric** (the plan's): ball recall on dead balls at a line, against the other three
  groups (dead away from lines, moving at a line, moving away), each with a Wilson 95% interval.
  Also reported, for the request: how the dead-at-line misses split by place (corner arc, touch
  line, goal line, penalty-area lines, centre circle and halfway line) and by the ball's size in
  pixels.

## What counts as a finding

The cluster is real if its recall's interval lies wholly below the moving-away group's. Otherwise
the audit says so, and the engine request is not made on this evidence.
