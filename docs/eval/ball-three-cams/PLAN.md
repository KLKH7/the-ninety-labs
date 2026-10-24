# The ball from three cameras: pre-registered plan

Status: **pre-registered, amended Oct 23 (Deviations) before any result.** Written Oct 23, before any clip of run `tactical1` was detected or
placed, and before any of its numbers were read. A change after this commit goes under
"Deviations" with its date and reason, before any result is read.

**Rubric:** technological implementation. The ball is the hardest object for vision and the one
every event hangs on. The broadcast camera follows it, so the ball is large there (about 2.5 to
7.5 px at the detector's input, where ours-freeze has test ball recall 0.884). On the fixed
tactical lenses, which see the whole pitch, the ball is small (tiles: about 6 px near, 3.5 px in
the centre, 2 px far). This plan measures which source puts the ball where it is, and ships the
one that does it best.

## The three ways of placing the ball

Players come from the two tactical lenses in every case: each lens is detected as tiles
(`detect --tiles`), placed through its own fixed camera (`observe --fixed`, `pitch.fit_fixed`),
and the two are merged on the pitch (`fuse.py`). Only the ball differs:

| | Ball from |
|---|---|
| (a) broadcast only | ours-freeze on the whole broadcast frame, placed through the broadcast's own per-frame camera fit (`observe`, `pitch.fit_clip`) |
| (b) tactical only | the fused tactical views' ball, for each detector: ours-freeze tiled, and ours-tactical tiled once the pod delivers it |
| (c) fused (`ninety/vision/ball_fuse.py`) | the broadcast ball when that frame's broadcast camera is trusted and has a ball at the scorer's 0.5; a tactical ball within the gate merges into it. Otherwise the tactical ball (cuts, replays, a ball out of the broadcast frame, an untrusted fit) |

Each source's per-frame ball is the one the tracker takes (`track.ball_path`: the highest-scoring
ball near the last one), so what is scored is what events read. No source reads truth or render
settings: the broadcast camera is the per-frame fit, never `meta.json` or a saved matrix.

### The gate, from measured precision

On the validation clips only (never test), each source's ball position error is measured. Each
detected ball is matched to its label by the pixel scorer's rule (`vision_score.match`: centre
within 5 px, score 0.5), and the error is the distance between where the source places it and the
true ball's ground position, for balls on the ground (true height under `IN_AIR_Z`, 0.5 m). The
statistic, fixed now: the **99th percentile** of that distance for each source, r_b (broadcast) and
r_t (tactical, fused views), and its root mean square for weighting. A tactical ball merges into a
broadcast ball when they are within sqrt(r_b² + r_t²) of each other. The merged place is the two
places weighted by the inverse of each source's mean squared error. Measured by
`ninety.eval.ball_sources --precision`, written to `precision.json` here, then copied into
`ball_fuse.py` with its source.

## What is measured

For every frame of each clip where the true ball is on the pitch (0 ≤ x ≤ 105, 0 ≤ y ≤ 68 m):

- **Recall, strict:** the share of those frames where the source has a ball within **1.0 m** of the
  true ball's ground position. **Lenient:** within **2.0 m**. These are the event scorer's radii
  (`event_score.STRICT_M`, `LENIENT_M`).
- **Precision, strict and lenient:** the share of the source's balls (on any frame) that are within
  the radius of the true ball. A ball reported when the true ball is off the pitch counts as wrong.
- **By zone, across the pitch** (the depth away from the cameras, which all stand on the y < 0
  side): **near** y < 22.67, **centre** 22.67 ≤ y < 45.33, **far** y ≥ 45.33 m, by the true ball's y.
- **In the air** (true height ≥ 0.5 m) as its own group, never left out. Every camera places the
  ball on the ground, so an airborne ball is placed short or long, by a different amount in each.
- Wilson 95% intervals with k/n. Frames of one clip are not independent, so the intervals are
  narrower than the truth.

`ninety.eval.ball_sources` computes all of it from the clips' frames.jsonl (grading data, read
offline) and each source's observations. It refuses a test seed in `--precision` mode.

## The decision (fixed now)

**The primary measure is strict recall over all frames.** The source shipped is the one with the
highest strict recall, among the sources whose strict precision is no more than 0.02 below the best
strict precision of the three. So no source buys recall with wrong balls. If (c) is not best, the
best single source ships, and fusion stays in the code but off in the demo.

## Order

1. **Validation** (the 24 validation clips the pod copies back, every frame): measure r_b and r_t,
   then score (a), (b), (c) on the same clips. The gate's own clips favour (c) slightly. Validation
   numbers are reported as validation, never as the result.
2. **Freeze:** the code, the gate and this plan at one commit, before any detection on a test clip.
3. **Test, once:** the 30 test clips 900001–900030 of run `tactical1` (rendered on the Mac, software
   GL), every frame, at the frozen commit. Each source is scored once, and every result is reported
   whatever it shows.

If the validation clips do not come back with their broadcast images, the gate is measured on the
broadcast of dataset v2's validation clips (same seeds, renderer 0.5.9, `runs/v2freeze`) and on the
tactical views alone, and this is recorded as a deviation.

## Deviations

### Oct 23, before any clip of run `tactical1` was detected for this plan or any number read

**The ball comes only from the broadcast** (Kian's decision, relayed by the Coordinator). The
tactical lenses are for players only. Sources (b) and (c) are no longer candidates. The tactical
ball may be reported as context, never chosen. The decision rule above is withdrawn. What is
measured and reported, on validation and then once on test:

- the broadcast ball (ours-freeze, whole frame, the broadcast's per-frame fit), per frame, as the
  tracker takes it: strict (1.0 m) and lenient (2.0 m) recall and precision, by zone and by height,
  as above;
- **coverage:** the share of frames with the true ball on the pitch where the broadcast places a
  ball at all (any distance), by zone. Cuts and frames with no ball count against it; the tracker
  bridges them downstream, and that is not scored here.

The gate measurement (r_b, r_t) is dropped with (c). `ball_fuse.py` and the fused variant are
removed from the PR.

**The camera trust test is re-derived first.** On current renders the height band (0.901 to
1.002, measured before renderer 0.5.3 drew players at their own heights) trusts almost no frame.
With true boxes and true cameras the median ratio is 1.048 on dataset v2's validation clips (0.5.9),
where 1.2% of frames are inside the band, and 1.077 (broadcast) and 1.10 (tactical lens) on a
0.5.15 training clip. Without a trusted frame nothing is placed. The band is re-derived by its own
rule (docs/eval/detector-plan.md, step B; `ninety.eval.detector_derive.gates`: the 1st to 99th
percentile of the ratio on validation frames whose ground mapping is within 1.0 m), on `tactical1`'s
24 validation clips (0.5.15), separately for the broadcast and for the fixed lens. It is frozen with
the code before any test detection. Detection and camera fits do not depend on the band:
saved observations are re-judged with `observe --regate`.

**Ball height later.** PR #226 (`ninety.vision.flight.heights`) re-places balls in the air from
their flight. It takes and returns observe's lines, so the same scorer can score its output as a
second row once #226 lands. That row is not part of this plan's result.

### Oct 23, 17:40 ET, before any test clip was detected

**Detection and camera fits on test start before the band is frozen; nothing on test is judged or
read until it is.** Measured on a training clip (seed 3), one clip through every stage takes 867 s
on the Mac. The broadcast's per-frame camera fit alone takes 444 s; the tactical tiles and their
fixed fit take 400 s. Done in sequence after validation, 54 clips do not finish before the deadline.
So:

- **Frozen now, at this commit:** detection (ours-freeze, whole frame), the broadcast camera fit
  and placing (`observe`, `pitch.fit_clip`), and the driver (`scripts/ball_three_cams.py raw
  --skip-tactical`). The test clips' detections and fits are made with this code as they render.
  The band does not enter detection or the fit. It only judges each frame afterwards
  (`ball_three_cams.py rejudge`, `observe.place` and `agree`).
- The band is derived on validation only (`band_derive`), set in `observe.py`, and committed.
  Then the test observations are re-judged and scored once, at that commit. No test file
  (observations, detections, scores) is opened for reading before that commit exists.
- **On test, the broadcast only:** the ball comes from the broadcast. The tactical lenses (for
  players, and the fixed band) run on validation only.

### Oct 23, evening (see the commit time), before any test result was read

**The broadcast camera fit is #250's** (PR #250, `claude/marking-grain` at `43ef1d2d`: the marking
pixels are blurred 3 x 3 before the fit, because sensor grain read as markings broke the fit on
GPU-rendered clips). The validation clips are GPU-rendered, so the broadcast band is derived at
#250's `pitch.py`. The test clips' detections and fits are made with the same code (4ae7357's
driver and detection, #250's `pitch.py`) so the band is applied to fits made the way it was
derived. The one test clip fitted at 4ae7357 before this (900001) is fitted again. Its first
observations were never read.

**A clip with no placeable camera** (observe raises "no frame shows enough pitch markings"; met on
validation seed 112) is counted, not dropped: every frame untrusted, nothing placed, so its frames
count against coverage and recall. The driver change (`_observed`) only handles that case. It
applies to the test run too, before any test result is read.


### Oct 24, before any test clip was detected at this commit (session C takes the plan over)

**The broadcast band is (0.966, 1.121)** (PR #270), derived by step B on the clips this plan names
(tactical1's 23 validation clips, broadcast, at #250's `pitch.py`), from session D's validation
observations; the same run reproduces D's fixed band (1.002, 1.151). Validation, scored with it:
`validation.json` here. **The freeze is this commit:** detection (ours-freeze, whole frame), #250's
camera fit, both bands, the driver and the scorer. The 30 test clips are detected, fitted, judged and
scored once at it; the one test clip fitted before (900001, at 4ae7357, unread) is fitted again and
its earlier file is never read.
