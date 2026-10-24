# Tactical fine-tune: results

The pre-registered scoring of [PLAN.md](PLAN.md), run once with `scripts/score_tactical.py` at
`bf42c45` (the code frozen before any detection; the run folder records it).

- **Detection:** tiled detection on every 5th frame of each view.
- **Matching:** `vision_score.match` at threshold 0.5.
- **Counting:** each object is counted once, in the view whose half holds it.
- **Intervals:** Wilson 95%.

## Validation decides: ours-tactical becomes the tactical detector

The rule: adopt ours-tactical if its recall on balls and on players are each at least ours-freeze's.
Both are higher, so it is adopted.

| 23 clips | Ball recall | Player recall | Ball precision | Player precision |
|---|---|---|---|---|
| ours-freeze | 653/1149 = 0.568 (0.540-0.597) | 0.983 (0.981-0.985) | 0.828 | 0.996 |
| **ours-tactical** | **858/1149 = 0.747 (0.721-0.771)** | **0.988 (0.986-0.989)** | **0.983** | **0.997** |

## Test set, scored once (28 clips)

| | Ball recall | Player recall | Ball precision | Player precision |
|---|---|---|---|---|
| ours-freeze | 877/1392 = 0.630 (0.604-0.655) | 0.996 (0.996-0.997) | 0.799 | 0.996 |
| **ours-tactical** | **963/1392 = 0.692 (0.667-0.716)** | **0.998 (0.998-0.999)** | **0.979** | **0.998** |

By pitch zone, on test (x along the pitch in metres; near and far halves across it):

| Zone | ours-freeze | ours-tactical | 95% (ours-tactical) | n |
|---|---|---|---|---|
| ball:x0-35/far | 0.888 | 0.910 | 0.833-0.954 | 89 |
| ball:x0-35/near | 0.518 | 0.560 | 0.484-0.633 | 166 |
| ball:x35-70/far | 0.576 | 0.605 | 0.552-0.656 | 337 |
| ball:x35-70/near | 0.726 | 0.823 | 0.789-0.852 | 559 |
| ball:x70-105/far | 0.241 | 0.271 | 0.202-0.352 | 133 |
| ball:x70-105/near | 0.741 | 0.824 | 0.742-0.884 | 108 |
| player:x0-35/far | 0.986 | 0.987 | 0.982-0.990 | 2871 |
| player:x0-35/near | 0.998 | 1.000 | 0.998-1.000 | 3548 |
| player:x35-70/far | 0.998 | 1.000 | 0.999-1.000 | 7671 |
| player:x35-70/near | 0.998 | 1.000 | 0.999-1.000 | 8659 |
| player:x70-105/far | 0.997 | 0.999 | 0.998-1.000 | 3483 |
| player:x70-105/near | 0.997 | 1.000 | 0.998-1.000 | 4568 |

- **Coverage on test:** every on-pitch player (30,755 of 30,755) and 99.5% of balls (1,338 of 1,345)
  are inside some view's picture.
- **Weakest zone:** the ball in tac-r's far corner (`x70-105/far`), at 0.27 on
  test against 0.89 on validation. That gap is wider than either interval and is not explained
  here; it is reported, not tuned for.

## Deviations

- **Validation:** 23 clips, not 24. Seed 118 failed `player_feet_in_boxes` at render and is
  excluded ([#281](https://github.com/KLKH7/the-ninety-labs/pull/281)).
- **Test:** 28 clips, not 30. 900004 and 900030 failed the same check in tac-r and are excluded.
  The cause is not diagnosed.
- **The interrupted run (Oct 24):** the run was stopped once to free the Mac for #285. Its last
  detection pass finished after the stop; every file holds all 50 frames. The restart detected
  nothing new and only scored. The same weights (sha256 `0fafe959…` and `d7b6f0be…`, printed in
  the log) and the same code made every file.
