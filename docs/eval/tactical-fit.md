# Fixed-camera fit: results on drawn scenes

Plan and pass bar, committed before any fit was run: [tactical-fit-plan.md](tactical-fit-plan.md).
Numbers: [tactical-fit.json](tactical-fit.json), from

    uv run python -m ninety.eval.tactical_fit --cameras 20 --seed 193 --out docs/eval/tactical-fit.json

20 lenses (10 a side) drawn from the rig's ranges through the renderer's camera model, 12 frames
each with moving players (one team in white, 10% missed by the "detector"), noise and JPEG. The
fit reads the pixels only; the camera is used for grading afterwards. The fit was developed on
seed 7 (6 lenses); seed 193 was run once, for this table.

## Result: passes

| zone | ground points | reprojection p95 (px) | bar (px) | ground error median (m) | p95 (m) | worst (m) | bar, p95 (m) |
|---|---|---|---|---|---|---|---|
| near | 12,720 | 0.53 | 1.5 | 0.007 | 0.025 | 0.050 | 0.13 |
| centre | 36,000 | 0.36 | 1.5 | 0.008 | 0.023 | 0.085 | 0.28 |
| far | 13,107 | 0.63 | 1.5 | 0.017 | 0.063 | 0.116 | 0.36 |
| near corner | 5,158 | 0.63 | 1.5 | 0.012 | 0.038 | 0.057 | 0.17 |
| far corner | 4,738 | 0.29 | 1.5 | 0.019 | 0.067 | 0.098 | 0.41 |

- **Precision:** every zone's p95 reprojection is under the 1.5 px bar (worst 0.63 px).
- **No gross failure:** all 20 fits `ok` (static markings' median 0.61 to 0.71 px), every frame
  `ok`; the worst ground error on any lens is 0.12 m (bar 2.0 m). The fitted position is
  0.01 to 0.28 m from the true one.
- **Jitter:** none from the camera. Every frame of a clip is placed through the same matrix
  (`tests/test_vision_pitch_fixed.py::test_a_fixed_clip_places_every_frame_through_one_camera`),
  where the broadcast gantry's per-frame fit moves a foot point by up to about 0.5 m (lesson 133).
  What is left is one fixed offset per clip, the error above.

## What it does not show yet

- These are drawn scenes, not the tactical renders: the renderer's own line look, lighting, the
  stands and the real players. The numbers are re-measured on the renders when they exist.
- The players' height test (lesson 148) still judges each frame. Its band was measured on
  broadcast frames; on the tactical camera players are 27 to 78 px tall, so the band must be
  re-measured there before its verdicts are read.
- A whole clip's camera shares one error, so no check of one frame against another can see it
  (lesson 159). On these scenes that error is under 0.12 m.
- Development found the six-parameter step stalling a metre from the camera on one seed-7 lens
  (3.4 px p95); a compass search on the position fixed it (0.24 px), now part of the fit
  (`pitch.settle`, lesson 193).
