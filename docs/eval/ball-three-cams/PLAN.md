# The ball from three cameras: pre-registered plan

Status: **pre-registered.** Written Oct 23, before any clip of run `tactical1` was detected or
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

None yet.
