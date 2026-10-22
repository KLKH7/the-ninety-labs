# Bounding how wrong a trusted camera can be: the plan (written before any run)

Written on branch `vision/camera-bound`, stacked on #187 (`vision/detector-rederive` at 159a63c),
before any of the runs below. Results go to the end of this file, under "Outcome", without editing
what is above. Lesson 159.

## Why

#187 replaced the marking test with a players'-height test (`ninety/vision/observe.py`, `place`),
adopted by a rule that counted frames. Lesson 149 says a gate must also bound how large the errors
it lets through are, and this one does not:
- **Validation:** 32 frames newly trusted on clips the marking test had rejected entirely (114,
  122, 3041, 3042), the worst 55 m wrong.
- **Test set:** 1 and 7 frames, 46 to 80 m wrong, on the two clips with camera cuts (900002,
  900003).
- **Undetectable by heights:** a camera in the wrong place with the right scale passes. Seed 108's
  gantry is about 2 m wrong along the line of sight in every frame.

## Data

- **Validation only:** the 13 observed clips of [detector-plan.md](detector-plan.md) (render run
  v1, ours-v2). Observations are on `pr-assets/detector-validation-observations`, sha256 in
  [detector-derive-observations.sha256](detector-derive-observations.sha256).
- **No camera fit is re-run**, so no slot.sh job is needed. Every candidate below reads a frame's
  stored camera and detections, and `observe --regate` applies the adopted one.
- **Test set:** scored once, at the end, after every constant is frozen.

The truth measure is #187's: each frame's ground mapping error (`detector_derive.ground_error`),
the median over pitch points every 5 m that the true camera sees.

## The bound, set before any candidate is measured

The candidates below judge each frame against its neighbours and the pitch, so they cannot see an
error every frame of a clip shares (seed 108's gantry). Their target is the rest: the frames whose
error no clip-wide offset explains.

**MAX_TRUSTED_M** is the largest ground error among seed 108's frames that the height test trusts
today, rounded up to the next 0.5 m. It is measured once, first, and written below before any
candidate is scored. It stands for "as wrong as a whole-clip offset makes a frame", and anything
trusted beyond it is a frame-level failure.

**Seen before this was written:** #187's report shows the worst error among frames trusted by
markings and heights together was 6.6 m, all on seed 108. The height test alone trusts more of
108's frames, so MAX_TRUSTED_M may be larger. Neither number was used to choose the candidates or
the 95% bar.

## Candidates (each in addition to the height test)

From the observations only (the live path):

| Name | Check |
|---|---|
| C1 on the pitch | the median of the frame's player foot points, placed through its camera, lies inside the pitch widened by 5 m on every side (players stay near the field of play; design) |
| C2 agrees with its neighbours | the frame's camera maps the image centre to within 2 m of where the nearest other height-trusted frame within 5 frames (0.2 s) maps it (a broadcast camera pans continuously, under 0.02 rad a frame, `pitch.STEP_SD`; design); a frame with no such neighbour fails |
| C3 markings, loosely | the frame's marking median within 5 px (`pitch.JOINT_MAX_MEDIAN_PX`, the fit's own limit for an anchor it believes) |
| C4 | C1 and C2 |

## Adoption rule

A candidate qualifies when, on validation:
1. the worst ground error of the frames it trusts is at most MAX_TRUSTED_M; and
2. it keeps at least 95% of the good frames (error within 1.0 m) that the height test alone keeps.

Among qualifying candidates, the one keeping the most good frames is adopted (ties: the earlier in
the table). If none qualifies, nothing is adopted: the height test stays as it is and the outcome
says so.

## The tests

The wrong-place camera test of #187 (`tests/test_vision_observe.py`, a strict expected failure)
plants a single frame 10 m wrong. It is replaced by what the adopted check does and does not do:
- **Must pass:** a frame whose camera is more than MAX_TRUSTED_M from its trusted neighbours' (or
  places its players off the pitch) is not trusted.
- **Stays a strict expected failure, by design:** a whole clip offset by less than MAX_TRUSTED_M
  is trusted. The tests say which is which.

## Then

- The test set's observations (900001 to 900005) are re-judged with `--regate`.
- The test set is scored once (`ninety.eval.event_report`, `attribution_score`), and
  `docs/eval/companion-tracked.json` is re-graded.
- EVALUATION, CHALLENGE_MAP and lesson 149's "Not yet met here" are updated, and lesson 159 added.
- READY goes to the Coordinator with the before/after table of bad frames trusted per clip.

## Amendment (after the candidates were scored, before anything below them)

RIVAL_M is defined as the players' pooled p90 position error on the frames the camera trust test
passes (#168, #187). Changing the test changes those frames, so RIVAL_M is re-measured by that same
rule with the adopted check in place. Nothing else about it changes.

## Outcome

### MAX_TRUSTED_M (measured first, before any candidate was scored)

Seed 108: 143 frames trusted by the height test, the worst 8.303 m wrong, so **MAX_TRUSTED_M =
8.5 m**.

### Candidates (validation; `uv run python -m ninety.eval.detector_derive`, "The camera trust bound")

| Check, each on top of the height test | Worst trusted | Good frames kept | Bad frames trusted |
|---|---|---|---|
| height alone (#187) | 55.3 m | 1,712 | 175 (108: 143, 114: 6, 122: 8, 3041: 14, 3042: 4) |
| C1 on the pitch | 55.3 m | 1,712 | 173 |
| **C2 agrees with its neighbours (adopted)** | **8.2 m** | 1,712 (100%) | 143 (108: 139, 114: 2, 3041: 2) |
| C3 markings within 5 px | 55.3 m | 1,648 (96.3%) | 142 |
| C4 C1 and C2 | 8.2 m | 1,712 (100%) | 143 |

C2 and C4 qualify: worst trusted at most 8.5 m, with at least 95% of good frames kept. They keep
the same number, and the tie goes to the earlier in the plan's table, so **C2 is adopted**.

What is left is seed 108's whole-clip offset (139 frames, 2 to 8 m) plus 2 frames each on 114 and
3041, all within the bound.

**RIVAL_M** (the amendment): the pooled p90 with C2 in place is 1.256 m, so **1.26 m** (was 1.59 m).

### The test set, scored once (after 2b0aa15 froze every constant)

Far-wrong frames trusted (ground mapping error over 1.0 m is not measured on test; these are the
frames the per-clip position report shows tens of metres off), by check:

| Test clip | Heights alone (#187) | Heights and neighbours (this PR) |
|---|---|---|
| 900001, 900004, 900005 | none far wrong | none far wrong (238, 194, 248 frames trusted, as before) |
| 900002 (camera cut) | 1 frame, about 80 m | **0** |
| 900003 (camera cut) | 7 frames, about 46 m | **4 frames, about 46 m**: a run whose wrong cameras agree with each other |

Everything else is unchanged:
- passes, strict: 7 of 13, F1 0.67;
- teams 7 of 7; names 14 of 14;
- the phone's numbers on 900001 (its tracked frames did not change).

The bound holds on validation (worst 8.2 m against 8.5 m) but not on 900003: the check cannot see
frames that are wrong the same way (lesson 159). They make no event.

### Validation, before and after (bad frames trusted, ground error over 1.0 m)

| Seed | Heights alone | Heights and neighbours |
|---|---|---|
| 108 | 143 | 139 (the whole clip's offset, 2 to 8 m) |
| 114 | 6 | 2 |
| 122 | 8 | 0 |
| 3041 | 14 | 2 |
| 3042 | 4 | 0 |
| Worst trusted | 55.3 m | 8.2 m |
| Good frames kept | 1,712 | 1,712 |

### Corrections after review (#195), recorded here rather than edited above

- **"Everything else is unchanged" was wrong.** RIVAL_M went from 1.59 m to 1.26 m, so the false
  pass v00003 on test seed 900001 (the shot read as a pass) now names its shooter `h-t1`, truly h10.
  The test set's false events naming someone go from 0 of 2 to **1 of 2**, and the demo fixture
  carries the name. On validation, names are now 22 of 24 right, 9 left null, and 2 of 3 false
  events name someone.
- **Is the RIVAL_M re-measure still justified?** RIVAL_M is defined as the position error on the
  frames the trust test passes, measured on validation (#168). The check changed those frames, so
  the amendment re-measured it by the same rule, on validation alone. Its effect on one test event
  is reported here, and is not a reason to change it: that would set a constant from the test set.
- **The neighbour check bounds nothing.** Its 8.2 m is the worst observed on validation. Frames
  wrong the same way agree and pass together, and a wrong frame can make its good neighbour fail.
  The wording is fixed in EVALUATION, the challenge map, observe.py and lessons 149 and 159.
- **Tie-break,** fixed now with the plan's other values and not tuned: when two neighbours are
  equally near, the earlier counts. In the 10 m test clip, frame 6 is judged against wrong frame 5
  and lost with it; the test asserts every frame.
- **Second look at the test set.** This check was planned because #187's test score showed these
  frames, so 900002's 1 → 0 is not held-out evidence. EVALUATION says so.
- **MAX_TRUSTED_M** is now committed data: `candidates.height.worst_by_seed[108]` = 8.303 m in
  detector-derive.json, and a test holds 8.5 m to it. Trusted frames the truth cannot measure are
  counted (0 for every candidate).
- **900003's 4 frames** are frames 5970 to 5976, 4 of those 7, not consecutive.
