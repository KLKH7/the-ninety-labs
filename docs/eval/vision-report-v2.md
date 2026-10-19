# Vision report v2: ours-v3 against ours-v2 on the frozen test set

The second detector, `ours-v3`, is measured on the same frozen test set, by the same builder, with
the same rules as [vision report v1](vision-report-v1.md). The numbers are in
[vision-report-v2.json](vision-report-v2.json), built from the committed detections by:

```bash
uv run python -m ninety.eval.vision_report --test runs/test-frozen-cca498c/test \
  --detections docs/eval/vision-report-v2/detections --out docs/eval/vision-report-v2.json
```

The builder refuses any clip whose labels, events or images differ from
[test-set-frozen.json](test-set-frozen.json), and any detections file that skips a frame. Every
v2 column below comes from [vision-report-v1.json](vision-report-v1.json) and every v3 column from
[vision-report-v2.json](vision-report-v2.json).

## What changed between the two models

| | ours-v2 (report v1) | ours-v3 (this report) |
|---|---|---|
| Started from | COCO weights | ours-v2 (sha256 `ef478f09…`), checked against its manifest |
| Training data | 253 clips from render runs v2 (`1e4db3c`) and v2los (`416430d`), before `engine-v1` | dataset v1 ([dataset-v1.json](dataset-v1.json), sha256 `81fcf81a…`): 284 training clips, all from `engine-v1`, the test set's engine |
| Validation | 25 clips | 24 clips: seed 111 removed (below) |
| Schedule | 30 epochs, lr 1e-4 ([finetune.json](../../ninety/vision/finetune.json)) | 8 epochs, patience 3, lr 5e-5 ([finetune-short.json](../../ninety/vision/finetune-short.json)) |
| GPU | RTX 4090, 24 GB | RTX PRO 6000 Blackwell, a MIG 2g.48gb slice (47.4 GiB), RunPod ([machine.json](vision-report-v2/machine.json)) |
| Trained at | `5725e99` | `4a6f26e` ([train-manifest.json](vision-report-v2/train-manifest.json)); 37 minutes |
| Checkpoint | `ef478f09…eb9fa5` | `3b2d5cf4…c014c9` |
| Detection | this Mac, every frame, batch 8 | the same |

Several things changed at once, so the differences below belong to the whole change, not to any
one of them. In particular they do not show that matching the engine alone caused them.

**Validation, 25 to 24 clips.** Seed 111 failed the render checks twice (`b319f21` and
`cca498c`), so dataset v1 excludes it. It was removed from the pinned validation seeds rather than
replaced, because picking a substitute after seeing results would mean choosing validation by
them. Validation only picks the best epoch; every number here is on the test set, which did not
change.

**The GPU.** The GPU changes training speed and floating-point order, not the method; a rerun
on any GPU gives the same model only up to GPU nondeterminism (finetune.json, `seed`).

## Results on the frozen test set

| | ours-v2 precision | recall | ours-v3 precision | recall |
|---|---|---|---|---|
| Players | 0.996 | 0.990 | **0.999** | **0.994** (9,556 / 9,610) |
| Ball, all labels | 0.926 | 0.930 | **0.987** | 0.933 (1,061 / 1,137) |
| Ball, at least half visible | 0.983 | 0.966 | **0.994** | 0.964 (1,024 / 1,062) |
| Players, partly hidden | 0.923 | 0.870 | **1.000** | **0.949** (131 / 138) |
| Players, mostly hidden | 0.949 | 0.747 | **0.985** | **0.893** (67 / 75) |
| Ball, partly hidden | 0.957 | 0.928 | 0.968 | 0.916 (153 / 167) |
| Ball, mostly hidden | 0.596 | 0.413 | **0.841** | 0.493 (37 / 75) |
| Players touching the image edge | 0.985 | 0.949 | 0.988 | 0.964 |
| False positives, all classes | 121 | | **27** | |

| Knob (test clips) | ours-v2 recall, players / ball | ours-v3 recall, players / ball |
|---|---|---|
| occlusion = crowded (900001, 900002, 900004) | 0.988 / 0.920 | 0.993 / 0.921 |
| occlusion = natural (900003, 900005) | 0.993 / 0.949 | 0.996 / 0.956 |
| kit contrast = low (900004) | 0.998 / 0.944 | 0.998 / 0.956 |

The targets still hold: players above 0.95 recall and balls at least half visible above 0.90.

## Findings

1. **Precision is where ours-v3 gained.** False positives fell from 121 to 27, and ball false
   positives from 84 to 14. Recall moved little where it was already high: players 0.990 to
   0.994, balls at least half visible 0.966 to 0.964 (two fewer of 1,062, within noise).
2. **The phantom ball at a player's feet is gone.** In the 113 frames where the ball is in shot
   but fully hidden, a confident ball detection appears in 1, against 45 for ours-v2, and
   neither model's lands on the hidden ball (`hidden_ball_frames`). For ours-v2, 44 of the 45
   came from one episode in seed 900003 (report v1, finding 4). Dataset v1 also replaced the
   training clips whose ball rests behind the boards with relabelled ones (`v3boards`). That
   may be why, but this report does not test it.
3. **Hidden players improved most.** Mostly hidden players went from 0.747 to 0.893 recall and
   partly hidden from 0.870 to 0.949.
4. **Mostly hidden balls are still the weakness.** Recall 0.493 (37 of 75) against 0.413 (31 of
   75); precision rose from 0.596 to 0.841. With 75 labels, a difference of six balls is about one
   standard error (√(0.45 × 0.55 / 75) ≈ 0.057). The gain is suggestive, not measured, so the
   next targeted round still goes here.
5. **Crowded scenes are not a separate weakness on this test set.** That was already the case for
   ours-v2 (report v1, finding 3), and ours-v3 keeps it. Seed 900001, a crowded clip, has the
   lowest ball recall (0.806). That is one clip, so it marks where to look, not a rate.

## Training run

Validation (24 clips, every 5th frame, rfdetr's own mAP50 on the EMA weights) rose from 0.967
after the first epoch to 0.976 at epoch 4, the best. Epochs 5 to 7 did not beat it, so with
patience 3 the run ended at its 8-epoch cap ([train-manifest.json](vision-report-v2/train-manifest.json)).
The run fetched exactly the 308 listed clips (4.35 GB) from Blob Storage, with labels from the
sealed `truth` container. The checkpoint's sha256 matches on the GPU machine, the local copy and
the manifest.

## Not measured yet

As in v1: pitch-level strict and lenient matching, the in-the-air and blurred groups, events
detected from pixels, and the COCO checkpoint on the same frames.
