# The merge gate of the tactical camera's two views

`ninety/vision/fuse.py` merges a player or the ball seen by both lenses of the fixed tactical
camera (they share about 5 m around halfway). Two detections from different views are one object
when their pitch positions differ by no more than the two measurements can miss by. This note says
where that comes from.

## What was measured

How far the detector puts a ground point from the true one, in the image: for each player, the
box's bottom centre (where `observe` puts his feet) against the label's `foot_px` (where the
renderer projects his ground point); for each ball, the box centre against the label's
`center_px`. Each error is divided by the label's height (players) or width (ball), so one number
serves a 27 px far player and a 78 px near one.

- Detector: ours-freeze, the demo detector (sha256 `0fafe959…d5e5`, docs/eval/finetune-v2freeze).
- Clips: the 24 validation clips of dataset v2 at the look freeze, every 5th frame, with the
  detections already scored there (`pr-assets/finetune-v2freeze-detections`). No test clip.
- Matching: the scorer's own rule (`vision_score.match`, score 0.5).
- Statistic, chosen before reading the numbers: the 99th percentile of the absolute error, per axis.

```
uv run python -m ninety.eval.foot_precision --clips <v2freeze renders>/train \
    --detections <v2freeze detections>/validation/ours-freeze \
    --seeds 108 109 110 112 113 114 115 116 117 118 119 120 121 122 2041 2042 2043 2044 2045 \
            3041 3042 3043 3044 3045 --out docs/eval/fuse-gate/foot-precision.json
```

| Class | Matched | 99th pct across | 99th pct down | Median across | Median down |
|---|---|---|---|---|---|
| player (share of box height) | 13,641 | 0.155 | 0.082 | 0.022 | 0.024 |
| ball (share of box width) | 1,073 | 0.403 | 0.256 | 0.038 | 0.025 |

[foot-precision.json](fuse-gate/foot-precision.json). The matched counts equal the true positives
in [validation-ours-freeze.json](finetune-v2freeze/validation-ours-freeze.json), so every match was
used.

## The gate

For each detection, its pixel error is taken as that 99th percentile of its own box, plus the
camera fit's residual on that frame (`camera.median_px`), plus one pixel (the labels measured
against are whole pixels), in quadrature. The pixel ellipse is carried to the pitch through the
view's own camera, so a far player, one of whose pixels spans half a metre of pitch in depth, gets a
long ellipse, and a near one a small round one. Two detections are the same object when their
difference lies inside the sum of the two ellipses. With normal errors at the 99th percentile per
axis that keeps about 96% of true pairs.

On a stand-in of the rig (both lenses at (52.5, -32, 28) m, 60 degrees across; `tests/tactical_rig.py`)
and a perfect fit, the two views' combined 99th-percentile reach on halfway is about 0.3 m near the
camera, and 0.37 m across by 0.79 m in depth at the far touchline. So two players 0.6 m apart near
the camera stay two, and 1.2 m apart in depth at the far side stay two (tests/test_vision_fuse.py).

## Limits

- **Measured on the broadcast camera** (players 30 to 120 px tall, 1280 x 720). The tactical
  renders' far players are smaller; the error is taken as a share of the box, which carries over
  only if the detector's error scales with the box. Re-measured by the same command on the tactical
  renders once they exist, and the constants replaced by what it gives.
- **The camera fit's residual stands in for its error.** A fit that is wrong in a way its residual
  does not show (lesson 148) moves both views' points apart and splits a pair; that shows up as a
  player counted twice in the band, which the zone scoring of the zero-shot baseline counts.

## Re-measured on the tactical renders (pre-registered Oct 26, before any number below)

On the 8080 demo each player in the seam band (x 45 to 60 m) is two tracks about 0.29 m apart:
tac-l places him +0.29 m in x from tac-r, across 3,128 cross-view pairs, so `same_place` reads 1.2
to 1.4 and the pair stays split (11.5 home tracks a frame, Law 3 trips, nothing team-named airs).
A fixed offset between the lenses is the second limit above. This section re-measures the gate's
inputs on the tactical renders and scores the result once. Nothing is read from the 8080 demo.

**Clips.** The 23 validation clips of dataset tactical (run tactical1; 118 excluded, as in its
scoring), split in two before anything is measured:
- *derive* (15): 117 119 120 121 122 2041 2042 2043 2044 2045 3041 3042 3043 3044 3045, with the
  ours-tactical detections of the pre-registered scoring (every 5th frame, both views);
- *score* (8): 108 109 110 112 113 114 115 116, the clips with each view's live observations
  (`runs/tactical1/join`, ours-tactical, tiled, at 716014c). Re-fused from those observations, so
  no detection is re-run.
No test clip (900001 to 900030, 910009 to 910016) is read.

**Step 1, measure (derive clips only).** `ninety.eval.foot_precision`, per lens, as above, plus
the *signed* error. The correction's form is fixed now: per lens and class, the signed error
(across and down, as a share of the box) is fitted by least squares as `a + b*c`, where `c` is the
box's bottom-centre column relative to the image centre, as a share of half the width (-1 at the
left edge, +1 at the right). That is the shape the suspected cause has: a standing body leans away
from the image centre in perspective, more the nearer the edge. Then:
- observe's ground point is moved by minus the fitted bias (the box's own size times `a + b*c`);
- `PRECISION` for the tactical views becomes the 99th percentile of the absolute error *left after*
  that correction, on the same clips;
- the broadcast camera keeps its constants: it is not measured here.

**Step 2, score (score clips, once).** Two arms on the same observations: *baseline* (fuse as on
main) and *candidate* (the correction and the re-measured precision). Each is tracked by the live
path (`ninety.vision.tracked_frames`), and graded offline against the union of both views'
`frames.jsonl` players (the answer key, read only here):
- **tracks per side per frame**: the mean, and the mean absolute difference from the side's true
  number on the pitch;
- **over 11**: the share of side-frames with more than 11 tracks (Law 3);
- **ID switches**: each true player's matched track changes between consecutive matched frames;
- **player recall**: true player-frames with a track within 1.0 m (track.GATE_M, the tracker's own
  gate), matched one to one per frame, nearest first;
- **side accuracy**: of those matches, the share whose track's side is the player's.

**Adoption rule.** The candidate is adopted if, against the baseline, the over-11 share is lower,
the mean absolute count difference is lower, ID switches are no more, and player recall and side
accuracy are each no lower than the baseline's Wilson 95% lower bound. Otherwise main keeps the
current gate, and this section reports the numbers either way.

### Step 1: what the tactical renders measure

```
uv run python -m ninety.eval.foot_precision --clips runs/tactical1/val \
    --detections runs/tactical1/score/validation/ours-tactical --view tac-l \
    --seeds 117 119 120 121 122 2041 2042 2043 2044 2045 3041 3042 3043 3044 3045 \
    --out docs/eval/fuse-gate/foot-precision-tac-l.json      # and the same for tac-r
```

| Player, share of box height | tac-l | tac-r | broadcast (above) |
|---|---|---|---|
| matched | 9,024 | 10,295 | 13,641 |
| 99th pct across | 0.230 | 0.243 | 0.155 |
| 99th pct down | 0.136 | 0.138 | 0.082 |
| bias across, `a + b*c` | 0.026 + 0.062 c | -0.015 + 0.080 c | not measured |
| bias down, `a + b*c` | 0.051 - 0.028 c | 0.039 + 0.014 c | not measured |
| 99th pct across, after the line | 0.172 | 0.182 | |
| 99th pct down, after the line | 0.130 | 0.129 | |

[foot-precision-tac-l.json](fuse-gate/foot-precision-tac-l.json),
[foot-precision-tac-r.json](fuse-gate/foot-precision-tac-r.json) (balls there too: 268 and 445).

- **The lean is real, and it points the way the 8080 split does.** At its own edge each lens's box
  sits outward of the feet by about 0.09 of the box (tac-l +0.088 at c = +1, tac-r -0.095 at
  c = -1). Those point in opposite directions along the pitch, and for a 50 px player near
  halfway that is roughly 0.3 m between the two places. That matches the +0.29 m found on the
  demo.
- **The broadcast precision is too tight for these lenses.** Before the lean is taken out, the
  tactical errors are about 1.5 times wider across and 1.7 times wider down. After it, across is
  1.1 to 1.2 times the broadcast figure, and down is still about 1.6. So the first limit above was
  right to worry.

### Step 2: scored once, on the 8 score clips

```
uv run python -m ninety.eval.fuse_tracks --runs runs/tactical1/join/runs --clips runs/tactical1/val \
    --seeds 108 109 110 112 113 114 115 116 --out docs/eval/fuse-gate/tracks-validation.json
```

| 8 clips, 3,210 side-frames | baseline (main) | candidate |
|---|---|---|
| tracks per side per frame | 9.62 | 9.29 |
| mean absolute difference from the side's true count | 5.78 | 5.50 |
| side-frames with more than 11 tracks | 0.415 | 0.391 |
| ID switches | 414 | **61** |
| player recall (95%) | 0.835 (0.831-0.839) | 0.838 (0.834-0.841) |
| side accuracy (95%) | 0.661 (0.655-0.666) | **0.655** (0.649-0.660) |

[tracks-validation.json](fuse-gate/tracks-validation.json), per clip inside.

**Not adopted.** Four parts of the rule pass. Side accuracy, at 0.6547, falls below the baseline's
lower bound of 0.6552, so main keeps the gate it had. The correction ships switched off
(`fuse.USE_LENS_BIAS = False`), with its constants and its test, the same way
`track.USE_CONSISTENCY` does. Nothing on the 8080 demo changes.

What the clips show, read after the score and changing nothing:
- **Side assignment, not the seam, is most of the count error.** In five clips (110, 112, 113, 115,
  116) the baseline's side accuracy is 0.40 to 0.63, so a side's track count is off by 6 to 11
  whatever fuse does. In 110, 112 and 113 the two arms come out the same.
- **Where sides are right, the result is mixed.** Seed 108 (side accuracy 1.00) goes from over-11
  in 0.54 of side-frames to 0, the count difference from 1.15 to 0.81, and ID switches from 66 to
  3. Seed 114 (side accuracy 0.92 to 0.94) gets worse on counts: over-11 goes from 0.40 to 0.50
  and the count difference from 1.40 to 1.52, while its ID switches fall from 70 to 7. ID switches
  fall in every clip where the arms differ.
- **What cost side accuracy is 109 and 116.** Side accuracy goes 0.79 to 0.68 in 109 and 0.63 to
  0.60 in 116. Fewer, longer tracks change what the kit clustering learns from; that is
  `ninety.vision.sides` and `track`, not the fuse gate.
- **Recall dips in 108 and 109** (0.944 to 0.925, 0.947 to 0.926), even though it rises over all
  8 clips. The wider gate may be merging two near players of one side. Not diagnosed.

Deviation: the pre-registration put the correction in observe. It is in fuse, because fuse is the
only place the tactical views' ground points go on from: the events stage and `tracked.json` read
the fused lines, never a view's own. The candidate's fused lines are what observe-then-fuse would
give.

What it would take to adopt, as a new pre-registration on new clips (this score set has been read):
make the kit clustering stable to the track set first, or take side accuracy out of the fuse's
rule and gate it where sides are decided.
