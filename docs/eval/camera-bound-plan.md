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

## Outcome

### MAX_TRUSTED_M (measured first, before any candidate was scored)

Seed 108: 143 frames trusted by the height test, the worst 8.303 m wrong, so **MAX_TRUSTED_M =
8.5 m**.
