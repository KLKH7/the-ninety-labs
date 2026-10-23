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

The frozen test set's older look (renderer 0.3.2) was not re-scored: its published numbers stand as
they were measured, with the detector of their day.
