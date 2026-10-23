# Learning curve: pre-registered plan

Status: **pre-registered, nothing run.** Every choice below is fixed before any learning-curve
model exists. A deviation is recorded in section 8 with its date and reason before results are
read; it is never made silently.

**Rubric:** Technological implementation. [EVALUATION.md](../../EVALUATION.md) says the training
data floors do not prove the data is enough: "the learning curve decides that". This is that
measurement.

## 1. The question

Does the detector keep improving as more clips in the demo's look (players on the skinned mesh)
are added, or has it levelled off by 80 clips?
- **Still rising:** more data, of any kind, is worth rendering.
- **Flat:** the gains from here have to come from something else: different data (round 2's
  targeting), the model, or the input size.

It is separate from [round 2](../round2/PLAN.md), which asks whether targeted clips beat ordinary
ones. It changes nothing in round 2's plan and uses none of round 2's seeds.

## 2. Design

| | |
|---|---|
| Start | **ours-v3** (`3b2d5cf4…c014c9`), which has never seen a mesh clip, for every run. ours-v4 and ours-v4-ctrl started from it too ([round1/RESULT.md](../round1/RESULT.md)) |
| Data | dataset v1 ([dataset-v1.json](../dataset-v1.json): 308 capsule clips, 284 training and 24 validation, unchanged) **plus the first k** of the 160 mesh clips round 1 rendered at `91d1e3b`: round1 7101–7180 and round1ctrl 7201–7280 |
| k | **20, 40, 80, 160** |
| Order | the mesh clips are sorted by sha256 of `ninety-train-order-<seed>` (`coco_export.clip_order`), fixed before any run. The lists are nested: the 20 are inside the 40, the 40 inside the 80, the 80 inside the 160 |
| Lists | [dataset-lc020.json](dataset-lc020.json), [dataset-lc040.json](dataset-lc040.json), [dataset-lc080.json](dataset-lc080.json), [dataset-lc160.json](dataset-lc160.json): dataset v1's `clips_list` followed by the first k mesh entries, copied unchanged from [dataset-v2-round1.json](../dataset-v2-round1.json) and [dataset-v2-ctrl.json](../dataset-v2-ctrl.json). Mesh clips per list: 20 = 10 round1 + 10 round1ctrl; 40 = 18 + 22; 80 = 36 + 44; 160 = 80 + 80 |
| Config | [finetune-round1.json](../../../ninety/vision/finetune-round1.json), **unchanged**: up to 8 epochs, early stopping with patience 3, lr 5e-5 (encoder 7.5e-5), batch 4 × 4, seed 7, 640 px, dataset v1's 24 validation clips |
| Models | `ours-lc020`, `ours-lc040`, `ours-lc080`, `ours-lc160` |
| k = 0 | **ours-v3 itself**, already scored on this test set ([vision-report-v2-mesh](../vision-report-v2-mesh.md)). Caveat: it did not get the up to 8 extra epochs on dataset v1 that the other points get |
| Test set | the frozen mesh test set ([test-set-frozen-91d1e3b.json](../test-set-frozen-91d1e3b.json): 5 clips, 1,250 frames), every frame, threshold 0.5, the scorer's rules ([EVALUATION.md](../../EVALUATION.md#vision-scoring)). If round 2's 30-clip test set is frozen before the curve is scored, every point is also scored on it, reported beside the 5-clip numbers, not instead of them |

**Why start from ours-v3, not from COCO weights.** From COCO, each run would need about 30 epochs
(ours-v2 took 4.5 h on an RTX 4090), roughly 20 GPU hours for the four. Starting from ours-v3 asks
the practical question, "how much new-look data does adapting take?", in about 5.5 hours. The
from-COCO curve is a different question and is not planned.

## 3. Built-in check

`ours-lc080` is trained the same way as ours-v4 and ours-v4-ctrl, except that its 80 mesh clips
are about half round1 and half round1ctrl (36 + 44), where theirs were all one kind. Those two
models are therefore two more 80-clip points, from different subsets.
- **Before the curve is read,** lc080 is compared with each of them: the paired 95% interval of
  lc080 minus each, on ball recall (all labels), should contain 0.
- **If it does not,** that is reported first, and the curve is reported with that caveat. The
  spread of the three 80-clip models is the curve's error bar between subsets.

## 4. Endpoints and decision rule

- **Primary endpoint: ball recall, all labels** (1,249 on the mesh test set). This is the
  largest ball group, so a change of a few points can be resolved.
- **Decision on lc160 minus lc080,** paired on the same labels. The 95% interval comes from a
  bootstrap over episodes, round 2's method (its section 3): runs of consecutive frames with a gap
  of 2 or less within one clip; 10,000 resamples, seed 1.
  - **One addition:** an episode is also cut every 25 frames (1 s). Without the cut, a ball in
    shot all clip long is one episode per clip, which leaves about 6 to resample.
  - Mostly hidden runs average 1.6 frames, so the cut leaves them as round 2 defines them.
- **What this test set can detect.** Measured on the committed round-1 detections:
  - The paired standard error of ball recall (all labels) between two similar models is about
    0.007 (ours-v4 minus ours-v4-ctrl).
  - A step of about 0.02 (2.8 standard errors) is therefore detectable.
  - For scale: ours-v4 minus ours-v3, which is 80 mesh clips added, was +0.027.
  - These were measured on 3 of the 5 clips, the ones whose labels could be checked against the
    freeze (section 6). They are re-measured on all 5 when the curve is scored.
- **The verdict:**
  - The interval lies above 0: **still rising from 80 to 160 clips**; the size of the gain is reported.
  - It contains 0: **no gain shown from 80 to 160**; the smallest gain this test set can detect
    is reported with it.
  - It lies below 0: **more data hurt**; reported as such.
- **Secondary endpoints,** reported whatever they show and never used to change the verdict:
  - mostly hidden balls (82 labels) and mostly hidden players (32), whose intervals are wide;
  - partly hidden balls (186);
  - players (all);
  - false positives, with precision next to every recall;
  - each step: 0 → 20, 20 → 40, 40 → 80.
- **No fitting.** With four points and intervals this wide, no power law and no extrapolation
  is claimed; the curve is shown as measured.

## 5. Runs and cost

The four runs are made one after another on one GPU, with the existing `list:` route. It
fetches exactly the clips a committed list names, so no script changes:

    INIT=runs/train/ours-v3 CONFIG=ninety/vision/finetune-round1.json SSH_PORT=<port> \
      scripts/train-on-gpu.sh root@<host> list:docs/eval/learning-curve/dataset-lc020.json ours-lc020

(the same for 040, 080 and 160).

**Cost.** ours-v4 trained 364 clips for 8 epochs in 83 minutes, which is about 1.7 s per clip
per epoch on the RTX PRO 6000 MIG 1g.24gb slice. At most 8 epochs each:

| Run | Training clips | At most |
|---|---|---|
| lc020 | 304 | ≈ 69 min |
| lc040 | 324 | ≈ 74 min |
| lc080 | 364 | ≈ 83 min |
| lc160 | 444 | ≈ 101 min |
| **All four** | | **≈ 5.5 GPU hours**, less if early stopping triggers |

**After each run:**
- Copy back the checkpoint, `train-manifest.json`, `metrics.csv` and `machine.json`.
- Verify the sha256s.
- Stop the pod.
- Run detections on the 5 test clips, every frame (minutes on the GPU).

**Timing.** The GPU is also needed for round 2 (planned Fri Oct 23), and the feature freeze is
Sun Oct 25. The curve fits on Wed 21 or Thu 22, or right after round 2's two runs on the same pod.

## 6. The labels the curve is scored on

The curve is scored on the **frozen** mesh labels, the same `frames.jsonl` files every committed
mesh report used. Each is checked against its sha256 in the freeze file before scoring. A local
re-render is not a substitute:
- A Windows re-render of this test set at `91d1e3b` gave `frames.jsonl` files that differ from
  the frozen ones for seeds 900003 and 900004.
- The engine's `events.jsonl` matched on all five clips.
- The label files carry per-object pixel counts and visibility measured from the render, which is
  the likely reason. (The capsule test set at `cca498c` re-rendered to identical labels.)

## 7. Caveats, fixed now

- **Validation is on capsule clips.** Early stopping, as for ours-v4 and ours-v4-ctrl, judges on
  dataset v1's capsule clips. That is the price of being comparable with them.
- **One training seed per point.** GPU nondeterminism and the subset drawn both move a point;
  the three 80-clip models (section 3) show by how much.
- **Five test clips.** The hidden-object groups are small, and their curves are noise-limited.
- **k = 0 is ours-v3 as trained,** not a run on dataset v1 alone (section 2).

## 8. Deviations

None yet. Any change after this plan is committed is listed here, with its date and reason,
before results are read.
