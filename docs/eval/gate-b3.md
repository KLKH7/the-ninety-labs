# The broadcast trust gate on current renders: heights and markings (B3)

Chosen on validation before any test score (the Coordinator's decision, Oct 24): a broadcast
frame's camera is trusted when its players' height ratio lies in `HEIGHT_BAND` **and** its marking
fit's own verdict holds (half the marking pixels within 1.5 px), and then when it agrees with a
trusted neighbour (`agree`). A fixed lens keeps the heights alone (its markings test was measured
only before the grain fix, where it failed most good frames).

tactical1's 23 validation clips (renderer 0.5.15), broadcast, session D's observations at #250's
`pitch.py`, re-judged; ground error against the true camera, graded offline:

| Gate, then `agree` | Trusted frames | Good frames kept (of 4,563) | Median | p95 | Worst | Clips with frames over 1 m |
|---|---|---|---|---|---|---|
| heights | 5,116 | 4,471 (98.0%) | 0.157 m | 3.93 m | 48.9 m | 115 (4, to 48.9 m), 117 (247, to 3.9 m), 2044 (250, to 14.1 m), 3043 (144, to 3.5 m) |
| **heights and markings (B3)** | 4,819 | 4,461 (97.8%) | 0.141 m | 11.75 m | **14.1 m** | 117 (116, to 3.5 m), 2044 (242, to 14.1 m) |

What B3 does not fix: seed 2044's camera is about 14 m wrong in every frame and lines its markings
up anyway (lesson 148); its frames agree with each other, so no check of one frame against another
sees it (lesson 159). It needs an absolute reference, not another per-frame test.

Reproduce: `python -m ninety.vision.observe --regate <D's observation> --out <file>` for each clip,
then grade each trusted frame's matrix against the clip's `frames.jsonl` (offline).

**Seed 112** (the camera #250 fits 45 m wrong): 0 of 250 frames trusted under B3, on both its
dataset v2 and its tactical1 validation clip. **Not measured here:** the frozen test set's older
look (900001 and the rest of renderer 0.3's test clips); their published numbers stand as measured.
**Left for the failure table:** seed 2044 (about 14 m wrong, markings lined up), no fix before the
freeze.
