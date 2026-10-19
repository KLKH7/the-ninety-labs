# Vision report v1: ours-v2 on the frozen test set

The first measurement of our fine-tuned detector on footage it never saw. The numbers are in
[vision-report-v1.json](vision-report-v1.json), built from the committed detections by:

```bash
uv run python -m ninety.eval.vision_report --test runs/test-frozen-cca498c/test \
  --detections docs/eval/vision-report-v1/detections --out docs/eval/vision-report-v1.json
```

The builder refuses any clip whose labels, events or images differ from
[test-set-frozen.json](test-set-frozen.json), scores each clip with main's
[vision_score](../../ninety/eval/vision_score.py) under the rules in
[EVALUATION.md](../EVALUATION.md#vision-scoring), and sums the counts.

## What was measured

| | |
|---|---|
| Detector | RF-DETR Small (rfdetr 1.11.2, Apache-2.0), checkpoint `ours-v2`, sha256 `ef478f09…eb9fa5`, trained at commit `5725e99` (its manifest: [train-manifest.json](vision-report-v1/train-manifest.json)) |
| Training data | 253 training and 25 validation clips from render runs v2 (`1e4db3c`, clear day) and v2los (`416430d`, line-of-sight crowding); 30 epochs from COCO weights on a rented GPU |
| Test set | `engine-v1`, re-frozen at `cca498c` (renderer 0.3.2): seeds 900001 to 900005, 10 s each, every frame (1,250 frames, 9,610 player and 1,137 ball labels) |
| Detection | every frame, at the trained input size (640), every detection kept down to the score floor; the scorer applies the 0.5 threshold |
| Rules | fixed before the first detector ran: player IoU ≥ 0.50, ball centre ≤ 5 px, one-to-one best-first, only frames the detector ran on, boxes at visibility zero are not labels |

## Results

| | precision | recall | target |
|---|---|---|---|
| Players | 0.996 | 0.990 (9,513 / 9,610) | 0.95: met |
| Ball, all labels | 0.926 | 0.930 (1,057 / 1,137) | |
| Ball, at least half visible | 0.983 | 0.966 (1,026 / 1,062) | 0.90: met |
| Ball, mostly hidden (0 < visibility < 0.5) | 0.596 | 0.413 (31 / 75) | reported |
| Players, mostly hidden | 0.949 | 0.747 (56 / 75) | reported |
| Players touching the image edge | 0.985 | 0.949 | reported |

By the clips' hard-case knobs (`by_knob`), recall for players and ball is:

| Knob | Clips | Players | Ball |
|---|---|---|---|
| occlusion = crowded | 900001, 900002, 900004 | 0.988 | 0.920 |
| occlusion = natural | 900003, 900005 | 0.993 | 0.949 |
| kit contrast = low | 900004 | 0.998 | 0.944 |
| kit contrast = normal | the other four | 0.988 | 0.926 |

Five clips are a small sample: a clip-level difference of a few points is within what one clip's
content can move (ball recall ranges from 0.815 to 1.000 across clips, `by_clip`).

## Findings

1. **Players and visible balls are solved on this footage.** Players at 0.990 recall and balls at
   least half visible at 0.966, both with precision above 0.98.
2. **Mostly hidden objects are the weakness.** A ball less than half visible is found 41% of the
   time, a mostly hidden player 75%. This is where the next round of targeted data goes.
3. **The crowded-scene weakness seen on validation does not show on the test set.** During
   training, ours-v2 scored 0.72 recall on the crowded validation clips. That was scored before
   #119, when objects in shot but fully hidden still counted as misses, and crowded windows hide
   the most. On the test set the three crowded clips score 0.988 (players) and 0.920 (ball)
   against 0.993 and 0.949 for the others. The validation figure was most likely the scorer's
   error, not the model's; it is not re-measured here.
4. **When the ball is hidden, the model reports a ball at a player's feet.** In 45 of the 113
   frames where the ball is in shot but fully hidden, a ball detection at score ≥ 0.5 appears; none
   is on the hidden ball (`hidden_ball_frames.on_the_hidden_ball` = 0, median 43 px away). 44 of
   the 45 are one episode in seed 900003, a dead ball resting behind the far boards while a player
   stands near it. By inspection (not in the builder), 39 of the 45 sit at a player's feet (centre
   within the lower quarter of a player's box). These 45 are over half of the 84 ball false
   positives. A ball tracker must not trust a single-frame ball when the ball was last seen
   going out of view.
5. **The training renders predate the test set's engine.** ours-v2 trained on renders from
   `1e4db3c` and `416430d`; the test set comes from `engine-v1` (`b319f21`, re-frozen at
   `cca498c`). The engine changed in between, so this is a mismatch. vision-report-v2 closes it:
   a short fine-tune from ours-v2 on dataset v1 ([dataset-v1.json](dataset-v1.json)), all of it
   from `engine-v1`.

## How these numbers changed, in order

The test set and the scorer each had a defect found after results were first seen. Both are
recorded here with the numbers they produced, so nothing is hidden by the fix.

| Step | Ball recall | Ball, at least half visible | Why it changed |
|---|---|---|---|
| First freeze (`b319f21`, #109), scorer of the time | 0.846 | 0.875 | |
| Re-frozen test set (`cca498c`, #118), scorer of the time | 0.846 | 0.966 | in seed 900003 a dead ball behind the boards was labelled visible for 110 frames; the detector's misses there led to the defect, now fixed in the renderer (lesson 84) |
| Re-frozen, scorer per the documented rule (#119): **official** | **0.930** | **0.966** | the re-frozen labels mark those balls visibility 0 with their box kept (boxes are amodal); the scorer still counted such boxes as labels, against EVALUATION.md's rule that they are not (lesson 85) |

Player numbers moved only from 0.989 to 0.990 (eight fully hidden player boxes stopped counting).
The images, the detections and the model are identical in all three rows. The rule in the last
row was written in EVALUATION.md before any detector ran; the code was brought in line with it
after the results were seen, and every earlier number is kept above.

## What is not measured yet

Pitch-level strict and lenient matching, the in-the-air and blurred groups, events detected from
pixels, and a comparison with the COCO checkpoint on the same frames. Those come in later reports.
