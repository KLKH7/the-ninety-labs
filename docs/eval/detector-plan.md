# The M1 event detector, re-derived on validation clips: the plan (written before any run)

Written 2026-10-20, on branch `vision/detector-rederive` from main at 69ad48f, before any of the
runs below. Results go to the end of this file, under "Outcome", without editing what is above.

## Why

The event detector of #143 (`ninety/vision/{pitch,observe,track,events}.py`) was developed while
frozen test seed 900001 was its only clip. So every constant marked *design* there was set while
looking at a test clip, and the published numbers (`docs/EVALUATION.md`, "Event detection from
video": pass F1 0.75 on seed 900001, and the rest) are partly tuned to the test set (lesson 11).
#168's validation runs found two concrete defects:

- **Sides:** on 13 validation clips, the side is wrong on 4 of 14 matched passes.
- **Camera trust:** the gate trusts badly wrong fits. On seed 109, 2 "trusted" frames are 106 to
  146 m off. On seed 108, 114 trusted frames are about 4 m off, with a normal marking error.

## Clips

- **Development:** ours-v2's validation seeds without a camera cut, as in
  [attribution-plan.md](attribution-plan.md): 108 109 114 115 116 120 121 122 2041 2042 2043 2045
  3041 3042 3045. Render run v1, renderer 0.3.0. Never test seeds.
- **Observations:** already computed by #168 (detector ours-v2; `pitch.py` and `observe.py`
  unchanged since #143). The camera fit is not re-run, so its search settings are not re-tuned (below).
- **Test:** the frozen test set's 5 clips (900001 to 900005), scored **once**, at the end, with
  every constant frozen.

## Inventory: every constant on the detector's live path

| Constants | Where | Source | Action |
|---|---|---|---|
| PITCH_X/Y, POST_Y, CIRCLE_R, PENALTY_AREA_X, BALL_R, BALL_CENTRE_Z | events, pitch, track, observe | Laws 1 and 2 (GROUNDING L1) | keep |
| CONTROL_M 1.5 m | events | GROUNDING P6 | keep |
| SCORE_MIN 0.5 | track | the evaluation's detection threshold (EVALUATION, vision scoring) | keep |
| FPS 25 | track | the render's frame rate | keep |
| SIDE_PX, MIN_LUMA_STEP, MIN_BLUE_STEP, BOX_PAD_PX | pitch (marking pixels) | stated as set on frames of a training clip | keep; the statement stands as written |
| The camera search and its optimiser: GANTRY_X/BACK/DOWN_DEG, PANS, TILTS, HFOV_DEG, SEARCH_COARSE_POINTS, GANTRY_FINALISTS, GANTRY_SCORE_FRAMES, JOINT_SCALES_PX, JOINT_MAX_MEDIAN_PX, MODEL_STEP_M, DT_CELL_PX, COARSE_KEEP, COARSE_PX, REFINE_SCALES_PX, MIN_IN_SHOT, CAUCHY_PX, FD_STEP, MAX_DIST_PX, SEARCH_POINTS, STEP_SD | pitch | design, developed on 900001 | **not re-tuned**: each sweep re-runs the camera fit on every clip (about 1.5 h). They decide whether a fit converges, not a threshold on a result. Their effect is measured: the camera error on validation (step B) is reported, and a wrong fit is caught by the gate, not by tuning the search |
| The camera trust gate: MAX_MEDIAN_PX 1.5 px, MIN_POINTS 60 | pitch | design, developed on 900001 | **step B** |
| GATE_M 1.0 m, MAX_GAP_FRAMES 25 | track | design (GATE_M from R6's top speeds plus the fit's jitter) | step C grid |
| The side naming: two kit colours by chromaticity, MIN_COLOUR_FRAMES 10, OUTLIER_FACTOR 3, CHROMA_NOISE 0.01, the depth vote | track | design; chromaticity was chosen on 900001 (track.py says so) | **step A** |
| CARRY_MPS 4, SPEED_FRAMES 2, MIN_SPELL_FRAMES 2, SPELL_GAP_FRAMES 6, SHOT_LOOK_S 0.3, SHOT_MARGIN_M 1.0, SHOT_MAX_M 35, OUT_FRAMES 3 | events | design, developed on 900001 | step C grid |
| RIVAL_M 1.89 m | events | measured on validation (#168): the pooled p90 of the player position error | re-measured by the same rule after step B (the gate changes which frames count) |
| REACH_MPS 10 m/s | events | GROUNDING P9 | keep |
| MIN_TRACK_FRAMES 5 | tracked_frames | the companion's 5 fps minimap | keep |

## Step A: side naming

- **Development metrics:**
  - (a) Side accuracy per track, weighted by frames, over tracks with a side and at least 5 frames.
    A track's true side is the side of the true players its detections overlap (IoU at least 0.5)
    in most of its frames.
  - (b) Team right on matched passes (the attribution scorer's matching).
- **A.1 diagnose:** for each validation clip, are the wrong sides a whole-clip swap (home and away
  named the wrong way round by the depth vote) or single tracks (wrong kit colour)? Recorded with
  the numbers.
- **A.2 fix the cause found:** the change is adopted only if, on validation, (a) rises and (b) does
  not fall. Otherwise the current naming stays and the outcome says so.
- **team_confidence:** changed only if the cause shows the current definition measures the wrong
  thing. How well it separates right sides from wrong ones on validation is reported (the share of
  (wrong, right) pairs it orders correctly). No threshold is set from it.

## Step B: the camera trust gate

- **Truth measure on validation:** each frame's ground mapping error. Take a grid of pitch points
  every 5 m, inside the pitch and in the true image. Project each through the true camera to a
  pixel, back through the estimated camera to the ground, and take the median distance. A frame is
  **bad** when that is over 1.0 m, the strict radius (EVALUATION: above it, the ball can go to the
  wrong player).
- **Candidate gates,** each from the observations only (the live path):
  - B1, today's: median marking error and point count;
  - B2, players' heights: each player box's height in pixels against the projected height of an
    upright player at that foot point, through the frame's camera. The frame's median ratio must
    lie in a band;
  - B3, B1 and B2 together.
- **B2's band:** a player stands 1.80 m tall (design, the middle of the synthetic squads' 1.66 to
  1.89 m in clip.json `looks`). The band's ends are the 1st and 99th percentiles of the ratio on
  the validation frames that are good by the truth measure: set from good frames only, before the
  gates are compared.
- **Adopted gate:** the candidate that rejects the most bad frames among those that keep at least
  90% of good frames trusted. If none rejects more bad frames than B1, B1 stays.
- Then RIVAL_M is re-measured (pooled p90, same rule as #168) with the adopted gate.

## Step C: the event and tracker constants

With A and B adopted, each constant is tried one at a time over a grid listed now. The current
value is first in each list.

| Constant | Grid |
|---|---|
| CARRY_MPS | 4, 3, 5, 6 |
| MIN_SPELL_FRAMES | 2, 1, 3 |
| SPELL_GAP_FRAMES | 6, 3, 12 |
| SHOT_MARGIN_M | 1.0, 0.5, 2.0 |
| SHOT_MAX_M | 35, 30, 40 |
| OUT_FRAMES | 3, 2, 5 |
| GATE_M | 1.0, 1.5, 2.0 |

- **Score:** event_score's strict rule on validation, summed over pass, shot and out of play: true
  positives (TP) and false positives (FP).
- **Change rule:** a value changes only if an alternative gives at least 2 more TP with no more FP.
  The best such alternative is taken, constants in the order listed, each with the earlier changes
  in place. Otherwise the current value stays.
- SPEED_FRAMES and SHOT_LOOK_S are kept: they set velocity windows, not a decision threshold.

## Step D: the test set, once

With every constant frozen and committed, score the 5 test clips once:
- events: `event_score`, strict and lenient;
- positions: `pitch_score`;
- who: `attribution_score`.

These replace the published numbers in EVALUATION and CHALLENGE_MAP, which will say what changed
from the 900001-only figures and why.

## Also in this PR

- EVALUATION, on #168:
  - `attribution_score.truth_role` was added after the validation run. Without it, validation's
    11 of 11 names reads 9 of 11; test numbers are unaffected, since the test truth has the field.
  - The Analyst does **not** see `team_confidence`: `ninety/match/facts.compact` passes `confidence`
    and drops it. This was checked by building the prompt from the fixture.
- Lessons 148 and 149.
