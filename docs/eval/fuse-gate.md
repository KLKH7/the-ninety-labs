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
