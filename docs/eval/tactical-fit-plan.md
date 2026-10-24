# Fixed-camera fit: plan (set before any fit was run)

The tactical camera is two fixed lenses high behind the near touchline at halfway, each showing
half the pitch. The live path calibrates each lens once per clip from the pitch markings
(`ninety/vision/pitch.py`, `fit_fixed`) and uses that one camera for every frame. Nothing on the
live path reads a saved camera: the fit sees pixels only.

Until the tactical renders exist, the fit is measured on scenes drawn by
`ninety/eval/tactical_fit.py` through the renderer's camera model (`ninety/render/camera.py`,
`Camera`): 20 lenses drawn from the rig's ranges (seed 193; 24 to 32 m up, 28 to 38 m back,
within 3 m of halfway, 55 to 65 degrees across, tilt 0.46 to 0.58 rad, pan 0.40 to 0.54 rad to
its half, 10 per side), 12 frames each with 23 moving players (one team in white, 10% of players
missed by the "detector", so their kit reaches the line detector), image noise and JPEG. The live
path's own line detector, static vote and `fit_fixed` run on those pixels.

## What is measured

On a 1 m grid of ground points each lens shows on its half: where the true camera draws a point,
taken back to the ground through the fitted camera (metres), and the fitted camera's reprojection
of the point against the true pixel (pixels). By zone: near (y < 17 m), centre, far (y >= 51 m),
near corner and far corner (the 15 m next to the goal line in the near and far bands).

## Pass bar (from measurement precision, before looking)

1. **Precision.** In every zone, the 95th percentile of the reprojection error is at most 1.5 px:
   `MAX_MEDIAN_PX`, the precision the marking fit already claims for a right fit (a line is found
   to about its blur width). In metres that is 1.5 times the zone's ground footprint (metres per
   pixel, worst direction, of the true camera only; `--geometry-only`, measured before any fit):

   | zone | footprint p95 (m/px) | bar, p95 ground error (m) |
   |---|---|---|
   | near | 0.088 | 0.13 |
   | centre | 0.185 | 0.28 |
   | far | 0.238 | 0.36 |
   | near corner | 0.117 | 0.17 |
   | far corner | 0.272 | 0.41 |

2. **No gross failure.** On every scene the fit is `ok` (half the static marking pixels within
   1.5 px) and the worst ground error over the lens's grid is under 2.0 m, the bound the gantry
   tests use for a camera in the wrong place (`tests/test_vision_pitch.py`, `GANTRY_GROSS_M`).

3. **Jitter.** One camera per clip: the projection on every frame is the same matrix, so a
   standing player's ground position does not move between frames from the camera (the gantry's
   per-frame fit moves a foot point by up to about 0.5 m, lesson 133). Checked by a test, not
   measured.

A miss is reported as a miss; the bar is not moved. When the tactical renders land, the same
numbers are re-measured on them, ground truth used for grading only.
