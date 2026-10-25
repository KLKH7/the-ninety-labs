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

## Outcome

### Validation clips rendered

Rendered locally at `cca498c`: 108 to 119 (12 clips). 120 to 122 were not rendered: the laptop's
load (a load average of 30 to 186 on 8 cores, from three tracks at once) made a render take 20 to
40 minutes, and none of them can cut (`camera_cut` false), so they would only have added non-cut
frames. Only **110 (3 cuts) and 111 (2 cuts)** cut inside their 10 seconds: 5 cuts on validation.
112, 113, 115, 117, 118 and 119 may cut but do not within their window (113 and 112 stay on a second
angle most of the clip). The test set's 900003 had not been looked at.

### Step 1: the cut detector (`uv run python tools/choose.py` on the distances; 5 cuts, 2,983 non-cuts)

| Candidate | Smallest at a cut | Largest at a non-cut | Separates | Best interval | Errors (missed, false) | Threshold |
|---|---|---|---|---|---|---|
| H1 colour histogram | 0.245 | 0.567 | no | 0.158 to 0.245 | 2 (0, 2) | 0.197 |
| H2 the same, top third | 0.244 | 0.742 | no | 0.209 to 0.244 | 3 (0, 3) | 0.226 |
| **T1 grey thumbnail 32 x 18 (adopted)** | 26.19 | 29.53 | no | 17.87 to 26.19 | **1 (0, 1)** | **21.634** |

No candidate separates: the whip pan on 111 (frame 4485, behind the goal) changes the picture more
than 111's first cut by every measure. By the plan, the candidate with the fewest errors is
adopted: **T1 at 21.634 grey levels**, missing no cut on validation and finding one false cut, that
whip pan. T1 was listed as a contrast, expected to suffer from pans; on these clips a pan moved it
at most 17.9, which is why it won. Seeds 108, 109 and 112 to 119 have no detected cut, so their
camera fit is exactly the one on main (`test_a_clip_without_a_cut_is_fitted_exactly_as_before`).

### Steps 2 and 3 on validation (`ninety.eval.camera_cuts`, [camera-cuts/validation.md](camera-cuts/validation.md))

Fitted before (one shot, today's fit) and after (shot by shot) on the two clips with cuts, with the
label boxes as detections, both judged by merged main's trust test (B3, then the shot-aware `agree`):

| Seed | Cuts found (missed, false) | Trusted before (good, bad) | Trusted after (good, bad) | Worst after |
|---|---|---|---|---|
| 110 | 3 of 3 (0, 0) | 27 (27, 0) | 134 (39, 95) | 1.344 m |
| 111 | 2 of 2 (0, 1: the whip pan) | 0 | 0 | - |

By shot, on 110: the two gantry shots fit to about 0.1 m, as before. The tight lens beside the
gantry (8 degrees across) gets its own gantry 28 m from the true one along the line of sight, where
distance trades against zoom, and its 99 trusted frames are 0.95 to 1.34 m wrong. The behind-goal
and low net shots (all of 111, 13 frames of 110) never fit: the gantry grid does not cover them, as
the plan said.

Against the bar:
1. Cuts: 5 of 5 found, 1 false (the whip pan). On that whip pan's shot nothing fits either way.
2. **Met:** worst trusted 1.344 m, under MAX_TRUSTED_M 8.5 m.
3. **Not met:** 107 frames newly trusted, of which 12 are good (within 1.0 m). The other 95 are the
   tight shot's, 1.0 to 1.34 m wrong.
4. **Met:** no detected cut on 108, 109, 112 to 119, so their fit is unchanged.

So the change misses its bar and is **not on by default**: `observe --cuts` turns it on, and without
it `observe` fits one shot as on main (`test_observe_fits_each_shot_on_its_own_and_labels_it`).

### The test set, scored once (after b542fa1 froze the detector, [camera-cuts/test.md](camera-cuts/test.md))

ours-v2's committed detections, the re-rendered frozen clips (byte-identical to their digests),
before and after judged by merged main's trust test. Cuts: 4 of 4 found, none false; no cut found on
900001, 900004 or 900005, whose observations are byte-identical before and after.

| Seed | Trusted before (bad) | Trusted after (bad) | Worst after | Players after, median / p90 |
|---|---|---|---|---|
| 900002 | 0 | 9 (0) | 0.27 m | 0.34 / 0.52 m |
| 900003 | 0 | **20 (20)** | **44.8 m** | 32.4 / 46.4 m |

- **900002:** its gantry shot (frames 5326 to 5426) now fits and 9 frames are trusted, all right. The
  shots behind the goal around it never fit.
- **900003:** the old 46 m frames (5970 to 5976, the tight shot) are no longer trusted. But its last
  shot is the **reverse angle** (a camera in the far stand), and it is fitted as the main gantry
  turned half a turn about the centre spot: Law 1's markings are the same after that turn, so the
  markings and the heights both pass, and 20 frames are trusted about 44 m wrong. No check in the
  fit can see it (lesson 243; `test_a_reverse_angle_draws_the_same_markings_as_the_main_camera_turned_about_the_centre_spot`).
- **Events** ([camera-cuts/event-report-after.json](camera-cuts/event-report-after.json)): passes
  strict, all five clips, **2 of 13 found, 1 false, F1 0.25, before and after alike**. Neither cut
  clip makes an event. That is far below event-report-v2's 7 of 13, F1 0.67, and the cause is the
  baseline, not this change (below).

### What the baseline does to the test set (found while scoring; nothing was changed on it)

Merged main's band (0.966, 1.121, #270) was measured on renderer 0.5.15. The frozen test set is
renderer 0.3.2, where a right camera's height ratio with label boxes is about 0.94 to 0.96 (seeds
110 and 118). Re-judging the same fits three ways, trusted frames (bad):

| Seed | Old band (0.901, 1.002), heights | #270 band, heights | #270 band and B3 (main) |
|---|---|---|---|
| 900001 | 190 (3) | 115 (54) | 115 (54) |
| 900004 | 163 (6) | 102 (70) | 30 (0) |
| 900005 | 250 (0) | 9 (0) | 9 (0) |
| 900002 before / after | 109 (8, to 159 m) / 101 (0, worst 0.4 m) | 0 / 13 (4) | 0 / 9 (0) |
| 900003 before / after | 0 / 39 (39) | 8 (8) / 20 (20) | 0 / 20 (20) |

So main's published pass F1 of 0.67 no longer holds on main's code: with #270 it is 0.25 on the same
clips. Under the band the test set's look was measured on, following cuts would take 900002 from 109
trusted frames (8 of them up to 159 m wrong) to 101, none over 0.4 m. That is reported, not adopted:
it was seen after the test score, and choosing a band per look is #270's and R3's call.

### What is still wrong, and what it needs

- **The reverse angle** is the main camera's mirror through the centre spot. Telling them apart
  needs a cue the half turn changes: which side the near stand, the boards or the dugouts are on, or
  the scorebug's side. Then it must be fitted or refused, never placed through the mirror.
- **Cameras behind a goal and at the net** are outside the gantry grid, so they are never placed. A
  search for them needs a sourced camera plan.
- **A tight lens's own gantry** slides 28 m along its line of sight. Its frames could be held to the
  gantry of the clip's other shots when they share a stand, which would need a test on clips with a
  tight cut.
- **Validation has 5 cuts on 2 clips and no reverse angle.** Before any of this is tuned, R2 should
  render validation clips with cuts of every kind (reverse, tight, behind the goal, net), at the
  test set's look and at today's.
