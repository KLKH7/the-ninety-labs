# Targeted data round 2: pre-registered plan

Status: **pre-registered, nothing rendered.** Committed before the look freeze (renderer 0.4.2 with
#150 and the engine fixes, frozen on Oct 22). Every number below that decides the outcome is fixed
here, before any round-2 clip, test clip or model exists. A deviation is recorded in section 8
with its reason; it is never made silently.

**Rubric:** Technological implementation and Agentic design. Round 1 showed that data from our
engine helps, but not that targeting helps ([round1/RESULT.md](../round1/RESULT.md)). Round 2 is
designed so that a targeting effect of about 0.05 recall would show if it exists, and so that a
null result is just as clear.

## 1. The question

Does rendering the windows where the detector fails (targeted) raise recall on mostly hidden balls
more than rendering the same matches' ordinary windows (control)?

**Why round 1 could not answer it, and the fix for each:**

| Round 1 weakness | Round 2 design |
|---|---|
| The control drew `crowded` at its seeds' own 30% rate, so it held 7.4% mostly hidden labels against round 1's 9.8% | **Same seeds in both arms.** The targeted arm uses the Data agent's window. The control uses `occlusion=natural` (the hard-case window draw switched off), so matches, kits, cameras and looks are identical and only the window differs |
| Any 80 clips in the new look gave most of the gain | **Both arms start from ours-v4,** which has already seen the mesh look, and both share the same base data |
| Only 80 clips | **200 clips per arm** |
| Validation on capsule clips | **A mesh validation set** at the frozen commit |
| 82 mostly hidden test labels: minimum detectable difference about 0.11 | **30 test clips,** about 360 labels: minimum detectable difference about 0.05 |

## 2. Primary endpoint and decision rule

- **Endpoint:** recall on mostly hidden balls (`0 < visibility < 0.5`) on the round-2 frozen test
  set. It uses the scorer's rule (`vision_score.match`, threshold 0.5) on every frame.
- **Comparison:** ours-v5 (targeted arm) minus ours-v5-ctrl (control arm), paired on the same
  labels.
- **Confidence interval:** 95%, from a paired bootstrap over episodes.
  - An episode is a run of mostly hidden labels in consecutive frames (gap of 2 frames or less)
    within one clip. Episodes, not frames, are resampled, because neighbouring frames are not
    independent.
  - 10,000 resamples, random seed 1.
- **Decision:**
  - The interval lies above 0: **targeting gain, measured**, reported with its size.
  - The interval contains 0: **no targeting gain shown at this size**, reported with the minimum
    detectable difference.
  - The interval lies below 0: **targeting hurt**, reported as such.
- **Secondary endpoints,** reported whatever they show and never used to change the verdict:
  - mostly hidden players;
  - partly hidden balls;
  - balls at least half visible;
  - all false positives;
  - each model against ours-v4 (the before).

## 3. Sample size and minimum detectable difference

The round-1 detections on the mesh test set give the inputs:
- 82 mostly hidden ball labels in 51 episodes (1.6 frames per episode).
- The paired difference between two similar models (ours-v4 against ours-v4-ctrl) has an
  episode-bootstrap standard error of 0.040.
- Labels per test clip: about 22 in clips drawn `crowded`, about 7 otherwise. With the seeds'
  30% `crowded` draw, about 11.7 per clip.

| Mostly hidden test labels | Standard error | Minimum detectable difference (80% power, two-sided 5%) |
|---|---|---|
| 82 (round 1) | 0.040 | 0.11 |
| 200 | 0.026 | 0.07 |
| **about 360 (30 clips, this plan)** | **0.019** | **0.05** |
| 500 | 0.016 | 0.045 |

The standard error is scaled as 1/√n from round 1, and the detectable difference is 2.8 standard
errors. Round 1's v4 minus v4-ctrl was −0.009, so a gain of about 0.05 is a real ask. This design
detects one that size; a smaller one would not be worth claiming on the demo.

## 4. Seeds and sets

All seeds are new; no earlier run used them. The test seeds are frozen before anything else.

| Set | Seeds | Clips | Rendered | Settings |
|---|---|---|---|---|
| **Test set (round 2)** | 900001–900030 | 30 | locally, software GL, at the frozen commit | each seed's own draws, no overrides (the test split refuses them) |
| Mesh validation | 7401–7424 | 24 | Azure | the seeds' own draws |
| Targeted arm | 7501–7700 | 200 | Azure | the Data agent's split (section 5) |
| Control arm | 7501–7700 | 200 | Azure | `occlusion=natural` |
| Base data, both arms | round1 7101–7180, round1ctrl 7201–7280 | 160 | already rendered (`91d1e3b`) | as rendered |

- **New test seeds.** 900006 to 900030 join `ninety/render/splits.py`'s `TEST_SEEDS` in the freeze
  PR. They are reserved already (`RESERVED_FROM = 900000`), so no training run can have used them.
- **The old sets stay.** The 5-clip mesh set (`test-set-frozen-91d1e3b.json`) and the capsule set
  stay frozen and reported, so earlier numbers keep their meaning.
- **Same seeds in two arms.** This is allowed: both are training seeds, and each arm's clips go to
  a separate run name (`round2`, `round2ctrl`).

## 5. How the targeted arm is chosen

The steps are fixed now, so no choice is made after seeing results:
1. Run ours-v4 on the mesh validation set (7401–7424, every 5th frame).
2. Run `ninety.vision.failure_clusters` on it, training side only.
3. The Data agent splits 200 clips over the mapped clusters by misses
   (`ninety.agents.data_agent`, largest remainder), first seed 7501. Each targeted seed gets its
   cluster's setting.
4. **Keeper re-check.**
   - At the frozen commit, before step 3, render 4 sample seeds with `occlusion=keeper` and 4 with
     `natural`, one process.
   - `keeper` stays in the mapping only if its share of mostly hidden balls is above `natural`'s.
     Otherwise its cluster moves to `unmapped`.
   - On main after #141 (`d6040af`), simulation shows keepers are not scarcer: across seeds
     7301–7312, the best keeper windows held 363 frames with a keeper handling or diving, against
     182 at `91d1e3b`. This is re-measured at the frozen commit, since the engine is still changing.
5. Run `crowded` with the live-ball rule (#136) as it is. Calibrating the occluder radius to the
   mesh (round-1 follow-up) is not part of this round; it would change the targeted arm after this
   plan.

## 6. Training

The same for both arms. Only the arm's 200 clips differ.

- **Starting point:** ours-v4 (`95d36154…`), already adapted to the mesh look.
- **Data:** the 160 base clips plus the arm's 200, stride 5. About 18,000 training images, as in
  round 1.
- **Validation:** the 24 mesh clips (7401–7424). Early stopping uses the same rule for both runs.
- **Config:** `ninety/vision/finetune-round2.json`, written in the freeze PR. It is
  finetune-round1.json with the new `val_seeds` and nothing else changed.
- **Models:** ours-v5 (targeted) and ours-v5-ctrl, one after the other on one GPU.

## 7. Cost and time

| Item | Amount | Cost |
|---|---|---|
| Azure render: 200 targeted, 200 control, 24 validation | 424 clips at about $0.04 | **about $17** |
| Local render: 25 new test clips and 8 keeper re-check clips | Mac, about 1.6 and 4 min a clip | $0 |
| GPU: two fine-tunes on a 1g.24gb slice | about 83 min each as in round 1, plus about 30 min setup and fetch: **about 3.5 h** | **about $2.50** at round 1's rate (about $0.70 an hour) |
| **Total** | | **about $20** |

Wall time:
- Test render: about 40 min, locally.
- Azure: about 2 h at 40 parallel executions, or about 4 h at round 1's 19.
- Validation detection and clusters: about 30 min.
- Training: about 3.5 h.
- Scoring: about 4 h of detection per model on the Mac, every frame of 30 clips (round 1
  measured about 40 min per 5 clips). The two primary models run as two processes at once
  (about 4 to 5 h, overnight). ours-v4 (secondary) runs after them.
  - Detection must not run on the GPU pod as it is: `detect` reads frame numbers from
    `frames.jsonl`, which is the test set's answer key, and that never leaves our storage.
  - A labels-free frame index (clip, frame, t, image) written at freeze time would let detection
    run on the pod. That needs a small change to `detect`; it is offered, not assumed.

Order:
1. Freeze commit.
2. Render and freeze the test set, before any training clip.
3. Validation set.
4. Clusters and keeper re-check.
5. Both arms.
6. Train.
7. Score.

## 8. Deviations

None yet. Any change after this commit is listed here with its date and reason before results
are read.
