# Targeted data round 1: result

**Verdict: on the mesh test set, round 1's targeted clips did no better than 80 untargeted clips
from the same commit.** Both raised recall on hidden objects over ours-v3 by the same amount.
That gain came from adapting to the mesh look and main's engine, not from targeting. The
ablation was planned for exactly this question ([PLAN.md](PLAN.md) section 5), and this is its
answer.

## The three models

All three are scored on the frozen mesh test set ([test-set-frozen-91d1e3b.json](../test-set-frozen-91d1e3b.json)),
with the same scorer, threshold 0.5, every frame, detected on the same Mac.

| Model | Trained on | Report |
|---|---|---|
| ours-v3 (before) | dataset v1 (308 capsule clips) | [vision-report-v2-mesh](../vision-report-v2-mesh.md) |
| ours-v4-ctrl | ours-v3 plus dataset v1 and 80 **untargeted** clips at `91d1e3b` | [vision-report-v3ctrl-mesh.json](../vision-report-v3ctrl-mesh.json) |
| ours-v4 | ours-v3 plus dataset v1 and the 80 **round-1** clips at `91d1e3b` | [vision-report-v3-mesh.json](../vision-report-v3-mesh.json) |

Precision / recall:

| | Labels | ours-v3 | ours-v4-ctrl | ours-v4 |
|---|---|---|---|---|
| Players | 11,759 | 0.992 / 0.993 | 0.997 / 0.994 | 0.998 / 0.995 |
| Ball, all labels | 1,249 | 0.978 / 0.909 | 0.991 / 0.932 | 0.991 / 0.931 |
| Ball, at least half visible | 1,167 | 0.985 / 0.937 | 0.994 / 0.956 | 0.993 / 0.956 |
| Ball, partly hidden | 186 | 0.940 / 0.763 | 0.962 / 0.817 | 0.962 / 0.817 |
| **Ball, mostly hidden** | 82 | 0.837 / 0.500 | 0.923 / **0.585** | 0.940 / **0.573** |
| Players, mostly hidden | 32 | 0.929 / 0.812 | 1.000 / 0.969 | 1.000 / 0.938 |
| False positives, all | | 125 | 41 | 35 |

**What it shows**
- **New-look data helps, targeted or not.** Both fine-tunes beat ours-v3 on every hidden group:
  - mostly hidden balls rise from 0.500 to about 0.58;
  - partly hidden balls from 0.763 to 0.817;
  - false positives fall from 125 to about 40.
- **Targeting adds nothing measurable.** On mostly hidden balls, v4 finds 47 of 82 and v4-ctrl
  finds 48. One standard error is about 0.055 (82 labels), so a difference of one label is noise.
  The crowded test clips agree: v4 found 677 balls and v4-ctrl 678.
- v4 has a few fewer false positives (35 against 41). That gap is too small to credit to
  targeting.

## Why targeting did not separate

1. **The contrast between the two training sets was small.**
   - Round 1's training labels were 9.8% mostly hidden balls (390); the control's were 7.4% (275).
   - The control's seeds drew `crowded` at their own 30% rate (22 of 80 clips).
   - Its natural windows hid more balls than the planning sample suggested (5.8% against 2.4%).
   - In all, 115 extra hidden-ball labels in a training set of about 19,000 ball labels.
2. **The new look dominates.** ours-v3 had never seen a mesh player. Any 80 mesh clips teach it
   the look, and that is most of the gain.
3. **The test set is small** where it counts: 82 mostly hidden balls and 32 mostly hidden
   players. A gain under about 0.1 cannot be told apart on it.

## Caveats

- **Different numbers of epochs.** ours-v4 ran all 8 epochs; ours-v4-ctrl stopped early after 5.
  Both used the same config and early-stopping rule, fixed before either run
  ([finetune-round1.json](../../../ninety/vision/finetune-round1.json)). Each keeps its best
  validation checkpoint. The best validation mAP came at epoch 4 for v4 and epoch 3 for v4-ctrl,
  so the extra epochs did not decide the comparison.
- **Validation is still capsules.** Validation stayed on dataset v1's 24 capsule clips, so early
  stopping judged both runs on the old look.

## What this means for round 2

- **The claim we can make now:** synthetic data from the engine that makes the demo footage
  lifted hidden-ball recall from 0.500 to about 0.58 and cut false positives by two thirds,
  measured on a frozen test set.
- **The claim we cannot make:** that the *targeting* did it. Do not publish round 1 as a
  targeting win.
- **For a targeting effect to show, round 2 needs:**
  - a control with the hard-case draws turned off, so the contrast is real;
  - more targeted clips, or a stronger lever than window choice. On the mesh, `crowded` gives
    about 10% mostly hidden balls against about 6% natural;
  - a mesh validation set;
  - and, ideally, a larger test slice of hidden objects. That means more test seeds, frozen
    before round 2 renders.
- **Re-measure `occlusion=keeper` on main after #141** before using it (the Coordinator's note).

## Provenance

| | ours-v4 | ours-v4-ctrl |
|---|---|---|
| Checkpoint sha256 | `95d36154…` | `35107105…` |
| Dataset list | [dataset-v2-round1.json](../dataset-v2-round1.json) | [dataset-v2-ctrl.json](../dataset-v2-ctrl.json) |
| Commit | `60529af` | `60529af` |
| Initialized from | ours-v3 `3b2d5cf4…` | ours-v3 `3b2d5cf4…` |
| Trained | 03:56–05:19 UTC | 05:19–06:11 UTC |
| Machine | RunPod, RTX PRO 6000 Blackwell MIG 1g.24gb | same |

Each run's manifest and `machine.json` are in [vision-report-v3-mesh/](../vision-report-v3-mesh/)
and [vision-report-v3ctrl-mesh/](../vision-report-v3ctrl-mesh/).

**Checks**
- All 10 files copied back match the pod's sha256, and each manifest's checkpoint hash matches its
  file.
- The pod was stopped after the copies were verified.
- Only our renders went to the pod, with read links to `renders` and `truth` only.
- Both reports rebuild from the committed detections:

      uv run python -m ninety.eval.vision_report --test runs/test-frozen-91d1e3b/test \
          --detections docs/eval/vision-report-v3-mesh/detections \
          --freeze docs/eval/test-set-frozen-91d1e3b.json --out docs/eval/vision-report-v3-mesh.json

  The control rebuilds the same way, from `vision-report-v3ctrl-mesh`.
