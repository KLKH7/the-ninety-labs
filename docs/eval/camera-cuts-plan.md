# Following camera cuts in the broadcast fit: the plan (written before any run)

Written on branch `claude/vision-camera-cuts-track-b-a31ba8`, based on `origin/main` at `ac21ccc`
(#250 merged), before any of the measurements below. Results go to the end of this file, under
"Outcome", without editing what is above. Lessons 148, 149, 159.

## Why

The broadcast fit (`ninety/vision/pitch.py`, `fit_clip`) finds one gantry for the whole clip from
every 25th frame, then tracks pan, tilt and zoom from the last frame that fit. A camera cut breaks
both: the anchors mix two cameras, so the gantry fits neither, and after the cut the tracker starts
from a camera that is no longer there. On the frozen test set the two clips with cuts (900002,
900003) have 0 and 4 trusted frames, and those 4 are about 46 m wrong (lesson 159). Their committed
observations show why: not one frame of either clip has its markings within 1.5 px; the marking
median sits at 4 to 40 px throughout (`docs/eval/attribution/observations-seed90000{2,3}.jsonl`).

Rubric: technological implementation (the live path places players on clips with cuts, and set
pieces mostly follow a cut).

## Seen before this was written

- The committed test observations above (marking medians, gantries, trust verdicts).
- While checking that a local re-render of the test set matches its frozen digests (it does, byte
  for byte, `test-set-frozen.json`), I read 900002's camera list: it opens on a camera behind the
  goal, cuts to the gantry at frame 5326 and back behind the goal at 5427. Nothing else from the
  test set's answer key was read, and no test number with the change was computed.
- The renderer's second angles at the test set's renderer (0.3.2, `cca498c`,
  `ninety/render/camera.py`): behind each goal, a low angle at the net, a tighter lens beside the
  gantry, and the far stand. Read to understand what a cut can be, not used on the live path.

## Data

- **Validation:** the bulk validation seeds of ours-v2 (`vision-report-v1/train-manifest.json`,
  `val_seeds`): 108 to 122, never trained on. The ones whose sampled render parameters allow a cut
  (`camera_cut`) are 110, 111, 112, 113, 115, 117, 118, 119; the rest are clips without a cut, where
  the change must do nothing. They are rendered locally at `cca498c`, the test set's renderer, so
  they have its look. Which frames are cuts is read from each clip's `frames.jsonl` (the camera's
  position or angle changes between two frames) for grading only.
- **Detections on validation:** ours-v2's checkpoint is not on this machine, so the validation
  clips use their drawn labels copied as detections (score 1, players and ball). The fit reads boxes
  only to mask players out of the marking pixels; the height test reads them too, and will be
  kinder with exact boxes than with the detector's. So validation measures the cut detector and the
  fit, and its trusted counts are an upper bound on what the detector gives. The test set uses
  ours-v2's committed detections (`docs/eval/vision-report-v1/detections`), as before.
- **Test:** the frozen five (900001 to 900005), scored once at the end, every constant frozen.

## The rule

### 1. Finding a cut, from the pixels

A cut is a frame whose picture is not a continuation of the last one. Between consecutive frames
of one shot a broadcast camera pans and zooms smoothly, so the picture's colour content moves
little; across a cut it changes at once. The measure is the classic shot-boundary one (Zhang,
Kankanhalli and Smoliar 1993, "Automatic partitioning of full-motion video"; Lienhart 1999,
"Comparison of automatic shot boundary detection algorithms"): the distance between the colour
histograms of consecutive frames.

Candidates, each a distance between frame t-1 and frame t, computed from the image alone:

| Name | Distance |
|---|---|
| H1 | half the L1 distance between the frames' RGB histograms, 8 bins a channel (512 bins), normalised to sum 1 (0 the same, 1 disjoint) |
| H2 | H1 on the top third of the frame only (stands and sky, which change most when the viewpoint does) |
| T1 | mean absolute difference of the two frames' greyscale thumbnails, 32 x 18 (pan-sensitive, kept as a contrast) |

A frame t is a cut when its distance is at least CUT_THRESHOLD.

**How CUT_THRESHOLD and the candidate are chosen (fixed now):** on the validation clips, for each
candidate, take the smallest distance at a true cut (`lo`) and the largest at a non-cut (`hi`).
A candidate separates when `lo > hi`; its margin is `lo / hi`. The candidate with the largest margin
is adopted, its threshold the geometric mean `sqrt(lo * hi)`, rounded to 3 decimals. If none
separates, the candidate with the fewest errors at its best threshold is adopted, ties to the
earlier in the table, and the misses and false cuts are reported. If even that misses more than
one cut in four on validation, nothing is adopted and the outcome says so.

### 2. At a cut, start again

The clip is split into shots at the detected cuts. Each shot is fitted as a clip is now, on its own
frames only: its own gantry (`find_gantry` on every 25th frame of the shot, from its first), then
pan, tilt and zoom tracked within it from its first frame. Nothing carries across a cut. The search
is the same as on a clip's first frame (the gantry grid); a shot from a camera that grid does not
cover (behind a goal, the far stand) is not given a new search space here, so it is expected to
fail the fit and stay untrusted. A shot with no frame of at least MIN_POINTS marking pixels gets no
camera.

A clip with no detected cut is fitted exactly as before (one shot): this is checked by a test.

### 3. Trust, unchanged and on every frame

The height test (`observe.place`) and the neighbour test (`observe.agree`) run on every frame with
their constants unchanged. One change to `agree`: a frame's neighbours are looked for within its
own shot only. The test's premise is that a broadcast camera pans continuously (pitch.STEP_SD); a
frame across a cut is a different camera, so comparing with it tests nothing. A frame with no
height-trusted neighbour in its shot within NEIGHBOUR_FRAMES is still not trusted. With no cut,
`agree` is exactly as before. The count of frames this changes is reported.

## The bar, set before measuring

On validation, with the adopted cut rule:
1. **Cuts:** the adopted candidate's misses and false cuts per clip, reported.
2. **Worst trusted:** the worst ground error (`detector_derive.ground_error`) among trusted frames on
   all 15 validation clips is at most MAX_TRUSTED_M = 8.5 m (camera-bound-plan.md), the bound the
   neighbour check was adopted under. If it is exceeded, the change does not go live and the
   outcome says so.
3. **More trusted on cut clips:** trusted frames on the validation clips with a cut rise, with at
   least 95% of the newly trusted frames good (ground error within 1.0 m).
4. **No change without a cut:** the clips with no detected cut give the same observations as on
   `origin/main`.

Then, once, on the test set: trusted frames per clip before and after, players' and ball's
position error (`ninety.eval.event_report`), whether 900003's frames 5970 to 5976 (about 46 m
wrong) are still trusted, and the pass F1 against `event-report-v2.md`. Reported whatever it shows.

## Outcome
### Amendment (2026-10-24, after seeds 110 and 111's distances were seen, before any other validation clip's, and before any fit with cuts)

- **Seen:** on 111 a whip pan of the behind-goal camera (the aim swings across the pitch in two
  frames, the picture smeared between) changes the histogram by 0.567, more than one of 111's true
  cuts (0.478). The plan counts it as a non-cut (its camera neither moves nor changes angle), and
  that stays so: no candidate may separate, and the "fewest errors" branch then decides.
- **What the plan left open:** in that branch, the threshold. It is the geometric mean of the two
  distances either side of the best interval (the largest value at or below it and the smallest
  above), rounded to 3 decimals; when several intervals tie on errors, the one with fewer missed
  cuts, then the lower.
- **Why it matters little for the fit, to be checked, not assumed:** a whip pan moves the aim further
  than tracking follows (pitch.STEP_SD), so starting again there is what the fit needs anyway. Each
  false cut's effect on trusted frames is reported.

### Amendment (2026-10-24, after merging origin/main with #270, before any fit with cuts was graded)

#270 changed the trust test on main: the broadcast band is now (0.966, 1.121) and a frame must also
pass its marking fit (gate B3). It did not touch `pitch.py`, so the camera fits are unchanged. The
baseline is therefore **today's main**: every "before" observation (one shot, fitted by the
unchanged fit) is re-judged with `observe --regate` on the merged code, and every "after" is judged
by the same merged `place` and `agree`. The only difference between the two is the cut handling.
The bar is unchanged.
