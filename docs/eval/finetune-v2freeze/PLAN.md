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
