# The look-freeze fine-tune: pre-registered plan

Status: **pre-registered, nothing trained.** Written before any dataset v2 clip was looked at. A
change after this commit is listed under "Deviations" with its date and reason, before any result
is read.

**Rubric:** Technological implementation. The demo's detector should be trained in the look the
demo shows. Dataset v2 is every training clip re-rendered at the look freeze, so this run is that
detector.

## The run

| | |
|---|---|
| Model | RF-DETR Small (Apache-2.0), rfdetr 1.11.2, as every earlier run |
| Starts from | **ours-v4**: sha256 `95d36154…22d`. It is the latest model trained on mesh renders, and round 2 also starts from it ([round2/PLAN.md](../round2/PLAN.md), section 7) |
| Name | **ours-freeze** |
| Data | **Dataset v2 training clips only**: 280 seeds rendered at `aea01f4` (run `v2freeze`; [dataset-v2-freeze.json](https://github.com/KLKH7/the-ninety-labs/blob/claude/dataset-freeze-renders/docs/eval/dataset-v2-freeze.json) on #194) on one RunPod RTX 4090 pod, less the validation seeds and any clip the render checks exclude. Stride 5: about 256 clips, about 12,800 images. No dataset v1 clip and no test clip |
| Validation | Dataset v1's 24 validation seeds (108–122 except 111, 2041–2045, 3041–3045), re-rendered in v2. The detector derivations use them as validation already. A seed whose v2 clip fails the render checks is removed, not replaced |
| Config | [finetune-v2freeze.json](../../../ninety/vision/finetune-v2freeze.json): `finetune-round2.json` with these validation seeds and a time cap. Resolution 640, batch 4 × 4, lr 5e-5 (encoder 7.5e-5), at most 8 epochs, early stopping with patience 3, seed 7 |
| Time cap | **110 minutes of training**. At the cap the trainer is interrupted and the best validation checkpoint so far is the model; its manifest says `stopped: time cap of 110 minutes` |
| Expected time | 60 to 95 minutes. ours-v2 took about 9 minutes an epoch on a 4090 for 12,650 images; ours-v4-ctrl stopped early after 5 epochs |
| Cost | about $1 of pod time at $0.50 an hour, with the environment prepared during the render |

## What runs where

Nothing secret goes to the pod. Only our synthetic renders are on it, and Kian deletes it after the
run (AGENTS.md, vision models).

1. **Before the hand-over, from the Mac, if the renderer agrees:**
   `scripts/finetune-v2freeze.sh <host> prepare`. It copies this commit's code to
   `/work/finetune/ninety` and ours-v4 (checked against its sha256) to `/work/finetune/init`,
   installs the locked environment, and runs a one-second CUDA check. It reads no clip.
   - The lock's torch 2.14.1 is built for CUDA 13.0, which needs NVIDIA driver 580 or newer.
   - If CUDA fails on the pod's driver, the same torch and torchvision versions are installed from
     PyTorch's CUDA 12.8 build, then 12.6. That is the only fallback, and `machine.json` records
     the build used.
2. **At the hand-over:** `scripts/finetune-v2freeze.sh <host> start <render out>`, in tmux on the
   pod (`scripts/finetune-on-pod.sh run`):
   1. `ninety.vision.pod_clips` checks the render before anything is trained:
      - it refuses a render of another run or commit, and an unfinished one;
      - it takes the manifest's passing **training** clips only;
      - it checks every file against the manifest's sha256 and size;
      - it removes failed validation seeds;
      - it writes the clip list, the run's config and `dataset-list.json`.
   2. `coco_export` links the clips in place, and refuses any test seed.
   3. `train --init ours-v4` runs under the cap. The training manifest records the config used, the
      dataset list, the render manifest's sha256, `initialized_from` (ours-v4's sha256) and the
      checkpoint's sha256.
3. **Afterwards:** `scripts/finetune-v2freeze.sh <host> fetch` copies back:
   - `checkpoint_best_total.pth`;
   - `train-manifest.json`, `metrics.csv`, `training_config.json`, `machine.json` and `train.log`.

   Each is checked against the pod's `SHA256SUMS`, and the checkpoint against its manifest.

## Scoring (on the Mac, after the copy-back)

- **Validation:** `ninety.eval.vision_report` on the 24 v2 validation clips, every 5th frame,
  for ours-v4 and ours-freeze.
  - **ours-freeze becomes the demo's detector if** its recall on balls and on players (the
    scorer's rule, `vision_score.match`, threshold 0.5) is each at least ours-v4's.
  - Both are reported with Wilson 95% intervals.
- **Test set, once:** the 30 v2 test clips (900001–900030 at `aea01f4`). Both models are scored
  with `vision_report --freeze` at a commit that freezes the code. The event pipeline is scored
  by detector-plan's step D. Every result is reported, whatever it shows, and nothing is tuned
  afterwards.

## Deviations

### Amendment (Oct 21, before the hand-over and before any clip was read)

The renderer reported that seeds 105, 111 and 120 crashed to black and that 2014 failed an engine
check. A failed clip is listed in the manifest's `failed` and is excluded, as planned. A clip that
crashed with no report is listed as `missing`, which `pod_clips` reads as an unfinished render.
Those seeds can now be named at the hand-over (`CRASHED=<seeds>`). Exactly those seeds may be
missing, and the dataset list records them as `excluded_crashed`. Like every excluded seed, they are
not replaced. Seed 120 is a validation seed, so it leaves validation by the rule above.

### The hand-over (Oct 21)

Eight training seeds had no report: 4017, 4025, 4033, 4041, 4045, 4049, 4053 and 4057 (two render
workers died on "Error creating WebGL context"). The render was done and no render process was
left, so they were passed as `CRASHED` and excluded, not replaced. The renderer confirmed this list
afterwards. Seeds 2014 and 4054 (data contract C7) and 4037 (black frames) failed the checks. 105,
111 and 120 were re-rendered and passed. All 24 validation seeds passed.

## Outcome

### Training (the checkpoint and its train-manifest.json stay out of git, with the maintainer)

- **Run:** ours-freeze trained on the RTX 4090 pod from 22:16 to 22:46 UTC, at commit 68f0523.
  - It ran all 8 epochs; the time cap was not reached.
  - Data: 245 training clips (12,250 images), validated on 1,200 images.
- **Checkpoint:** sha256 `0fafe959ec2e08279e5741261ac4e639f2b87f0c11384a2d0e976dda6ef5d5e5`.
  - Copied back to the Mac, and every file was checked against the pod's `SHA256SUMS`.
  - Initialised from ours-v4 (`95d36154…`).
  - The render manifest it read has sha256 `1570bed2…`.
- **Validation mAP 50:95 during training:** 0.712 after epoch 1, 0.731 after epoch 8.

### Scored (code and both sets frozen at 0561656 before any detection; one run each, on the Mac)

Recall and precision use the scorer's rule (`vision_score.match`, threshold 0.5). Brackets give
the Wilson 95% interval, with k/n. Frames within a clip are not independent, so these intervals are
narrower than the truth.

**Validation:** 24 clips, every 5th frame. [ours-v4](validation-ours-v4.json),
[ours-freeze](validation-ours-freeze.json).

| Model | Ball recall | Player recall | Mostly hidden ball recall | Ball precision | Player precision |
|---|---|---|---|---|---|
| ours-v4 | 0.649 (0.621–0.675; 776/1196) | 0.991 (0.989–0.992) | 0.069 (0.027–0.164; 4/58) | 0.980 | 0.995 |
| ours-freeze | **0.897** (0.879–0.913; 1073/1196) | **0.994** (0.993–0.995) | 0.345 (0.236–0.473; 20/58) | 0.988 | 0.998 |

- **ours-freeze becomes the demo's detector.** By the rule set above, its ball and player recall are
  each at least ours-v4's.
- Its checkpoint was chosen on these same clips (early stopping), which favours it slightly. The
  test set is the fair comparison.

**Test set, scored once:** 30 clips, 900001–900030, every frame (7,500 frames).
[ours-v4](test-ours-v4.json), [ours-freeze](test-ours-freeze.json).

| Model | Ball recall | Player recall | Mostly hidden ball recall | Ball precision | Player precision |
|---|---|---|---|---|---|
| ours-v4 | 0.687 (0.676–0.697; 5109/7437) | 0.995 (0.995–0.996) | 0.265 (0.230–0.304; 143/539) | 0.975 | 0.994 |
| ours-freeze | **0.884** (0.877–0.891; 6575/7437) | **0.997** (0.996–0.997) | **0.425** (0.384–0.467; 229/539) | **0.989** | **0.998** |

- **Ball recall rises by 0.20 on the held-out test set,** and the intervals are far apart.
- **Mostly hidden balls rise from 0.27 to 0.43.** Precision rises as well, so the model is not
  buying recall with false positives.
- **Why:** ours-v4 had never seen the look-freeze renders, and its ball recall falls on them (0.69
  here). Training in the demo's look recovers it.

The detections are kept on `pr-assets/finetune-v2freeze-detections` (42b2a07), as
`finetune-v2freeze-detections.tar.gz`, sha256 `1b0e3ac69a7df9fd62c07f1cceef6d2af7f4db858b00ed85183cd57e5b4fc1e0`.
`vision_report --freeze docs/eval/finetune-v2freeze/<set>-set.json [--stride 5]` rebuilds each
report from them.
