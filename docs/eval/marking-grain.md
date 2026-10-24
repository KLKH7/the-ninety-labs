# The marking detector on grainy renders: before and after the 3 x 3 blur

The camera fit's marking pixels (`ninety/vision/pitch.py`, `line_mask`) on dataset v2's 24
validation clips (renderer 0.5.9, `params.noise` 0.006 to 0.02), graded offline against each
frame's true camera. No test clip was used.

**Marking pixels** (frames 0, 50, 100, 150 and 200 of each clip, no player boxes): the share within
2 px of a true marking, and how many are.

| Detector | On a marking | Pixels on a marking |
|---|---|---|
| unfiltered (main) | 0.391 | 611,605 |
| 3 x 3 blur first (this change) | 0.819 | 789,950 |
| blur, then a neighbour count (7 x 7, at least 5; not kept, see `pitch.py`) | 0.842 | 785,762 |

The rule was fixed before the numbers: the most pixels on a marking, keeping at least 80% of the
unfiltered detector's on-marking pixels, a 1 px line surviving.

**The camera fit** (`fit_clip`, the first 100 frames, ours-freeze's player boxes), against the
true camera: the median over frames of the median ground error over a pixel grid.

| Seed | Main: fitted gantry | Main: frames passing the markings test | This change: gantry (true) | Passing | Ground error, median (p90) |
|---|---|---|---|---|---|
| 108 | (52.5, -20, 5.4), a grid corner | 0 / 250 | (48.8, -36.3, 15.9) ((48.7, -38.8, 16.5)) | 100 / 100 | 0.11 m (0.11) |
| 110 | (37.5, -55, 22.2), a grid corner | 0 / 250 | (56.0, -29.3, 12.7) ((55.4, -30.4, 12.9)) | 100 / 100 | 0.08 m (0.28) |
| 112 | (37.5, -20, 5.4), a grid corner | 0 / 250 | (39.4, -49.9, 14.3) ((50.9, -38.9, 16.5)) | 98 / 100 | 44.6 m (45.6) |

Seed 112 is a wrong camera that lines its markings up (lesson 148): the players' heights are the
test that must reject it, and their band is being re-derived for the current renders.

## The older look and the tactical lenses (the merge bar)

The same fit (`fit_clip`, first 100 frames; `fit_fixed` for a lens), main against this change, with
no player boxes for either (so they compare; the published runs had boxes), graded against the true
camera: frames passing the markings test, the median residual, and the ground error (median, p90).
Software GL is the frozen test set's renderer (0.3.2); GPU GL the pod's (0.5.15). A third variant,
a raw marking pixel kept only where the blurred image marks it within 1 px (no line widened), is
shown for comparison and not adopted: it is no better on either look.

| Clip (GL) | Main | This change (blur) | Raw confirmed by blur |
|---|---|---|---|
| test 900001 (software) | 100 ok, 1.02 px, **0.11 m** (0.26) | 100 ok, 1.26 px, **0.34 m** (0.78) | 100 ok, 1.16 px, 0.24 m (0.50) |
| test 900004 (software) | 0 ok, 8.1 px, 33.9 m (34.9) | 100 ok, 0.98 px, 0.16 m (0.57) | 100 ok, 0.93 px, 0.20 m (0.50) |
| test 900005 (software) | 9 ok, 10.4 px, 0.02 m (0.33) | 100 ok, 1.17 px, 0.055 m (0.17) | 100 ok, 1.10 px, 0.06 m (0.12) |
| test 900002, 900003 (software, camera cuts) | 0 ok, about 60 m | 0 ok, about 60 m | not run |
| v2 validation 108 (GPU, broadcast) | grid corner, 0 ok | 100 ok, 0.95 px, 0.11 m (0.11) | 100 ok, 0.75 px, 0.16 m (0.17) |
| tactical validation 108, tac-l (GPU, `fit_fixed`) | 0 ok, **54.7 px**, 0.046 m | 100 ok, 0.96 px, 0.024 m | 100 ok, 0.82 px, 0.011 m |

What it says:
- On the GPU look the change is what makes the camera usable, and on a fixed lens it brings the
  residual (which `fuse.py` adds to its merge gate) from 55 px back to 1 px; the lens was already
  placed well.
- On the older look it rescues 900004 and keeps 900005, and **it costs 900001 precision**: 0.11 m
  to 0.34 m median, 0.26 m to 0.78 m at p90, still inside the strict 1.0 m an event is graded by.
  Its frames all passed before and after, so the trust tests do not see the change. This is one
  clip, and the fit's position along the line of sight is known to wander there (lesson 97's
  clip); it is reported, not explained away.
- 900002 and 900003, the clips with camera cuts, fail before and after (EVALUATION.md: no events).

The frozen test set's published numbers were measured with the detector of their day and are not
re-scored here.
