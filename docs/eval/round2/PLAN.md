# Targeted data round 2: pre-registered plan

Status: **pre-registered, nothing rendered.** Every number that decides the outcome is fixed here,
before any round-2 clip, test clip or model exists. A deviation is recorded in section 9 with its
date and reason before results are read; it is never made silently.

**Rubric:** Technological implementation and Agentic design. Round 1 showed that data from our
engine helps, but not that targeting helps ([round1/RESULT.md](../round1/RESULT.md)). Round 2 is
designed so that a targeting effect of about 0.05 recall would show if it exists, and so that a
null result is just as clear.

## 1. The question

Does rendering the windows where the detector fails (targeted) raise recall on mostly hidden balls
more than rendering ordinary windows of the same matches (control)?

**Why round 1 could not answer it, and the fix for each:**

| Round 1 weakness | Round 2 design |
|---|---|
| The control drew `crowded` at its seeds' own 30% rate, so it held 7.4% mostly hidden labels against round 1's 9.8% | **Same seeds in both arms.** The targeted arm uses the Data agent's window. The control uses `occlusion=natural` (the hard-case window draw switched off). Matches, kits, cameras and looks are identical; only the window differs |
| Any 80 clips in the new look gave most of the gain | **Both arms start from ours-v4,** which has already seen the mesh look, and both share the same base data |
| 80 clips | **170 clips per arm** |
| Validation on capsule clips | **A mesh validation set** at the render commit |
| 82 mostly hidden test labels: minimum detectable difference about 0.11 | **30 test clips,** about 350 labels: minimum detectable difference about 0.05 |

## 2. The render commit

This plan holds for any single commit. Targeting is an A/B where both arms share one look and one
engine, so the choice of commit (main now, or the look freeze) does not change the design. It
must, however, be one commit for everything in this round:
- the test set;
- the validation set;
- both arms;
- the keeper re-check (section 5).

The Coordinator chooses the commit. It is recorded:
- in the freeze file;
- in every render request;
- in section 9, before the first render.

It must hold this plan's `TEST_SEEDS` (`ninety/render/splits.py`) and
`ninety/vision/finetune-round2.json`, both committed with this plan.

## 3. Primary endpoint and decision rule

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

## 4. Sample size and minimum detectable difference

The test set's size decides the detectable difference; the arm size decides how large an effect
can be. The round-1 detections on the 5-clip mesh test set give the inputs:
- 82 mostly hidden ball labels in 51 episodes (1.6 frames per episode).
- The paired difference between two similar models (ours-v4 against ours-v4-ctrl) has an
  episode-bootstrap standard error of 0.040.
- Labels per test clip: about 22 in clips drawn `crowded`, about 7 otherwise. With the seeds' own
  30% `crowded` draw, about 11.7 per clip. The test split refuses overrides, so its mix is the
  seeds' own.

| Mostly hidden test labels | Standard error | Minimum detectable difference (80% power, two-sided 5%) |
|---|---|---|
| 82 (round 1) | 0.040 | 0.11 |
| 200 | 0.026 | 0.07 |
| **about 350 (30 clips, this plan)** | **0.019** | **0.05** |
| 500 | 0.016 | 0.045 |

The standard error is scaled as 1/√n from round 1, and the detectable difference is 2.8 standard
errors. Round 1's v4 minus v4-ctrl was −0.009, so a gain of about 0.05 is a real ask. This design
detects one that size; a smaller one would not be worth claiming on the demo.

If the frozen test set turns out to hold fewer than 250 mostly hidden labels, the difference this
design can detect rises above 0.06. That is reported, and the test set is **not** enlarged after
any model is scored on it.

## 5. Seeds and sets

All seeds are new: no earlier run used them.

| Set | Seeds | Clips | Rendered | Settings |
|---|---|---|---|---|
| **Test set (round 2)** | 900001–900030 | 30 | locally, software GL, first, at the render commit | each seed's own draws, no overrides (the test split refuses them) |
| Mesh validation | 7401–7424 | 24 | Azure | the seeds' own draws |
| Targeted arm | 7501–7670 | 170 | Azure, run `round2` | the Data agent's split (section 6) |
| Control arm | 7501–7670 | 170 | Azure, run `round2ctrl` | `occlusion=natural` |
| Base data, both arms | round1 7101–7180, round1ctrl 7201–7280 | 160 | already rendered at `91d1e3b` | as rendered |

- **New test seeds.** 900006 to 900030 join `TEST_SEEDS` with this plan. They were reserved
  already (`RESERVED_FROM = 900000`), so no training run used them. The 5-clip mesh set and the
  capsule set stay frozen and reported.
- **The test set renders locally,** as both earlier test sets did. Its pixels must not depend on
  the machine, and the Azure job refuses test seeds by design (`job_config`). 30 clips at about
  1.6 minutes is about 50 minutes on the Mac. The test set is frozen, hashed and uploaded (by a
  maintainer) before any training clip of this round is rendered.
- **Same seeds in two arms.** This is allowed: both are training seeds, and each arm renders to
  its own run name.

## 6. How the targeted arm is chosen

The steps are fixed now, so no choice is made after seeing results:
1. Run ours-v4 on the mesh validation set (every 5th frame).
2. Run `ninety.vision.failure_clusters` on it, training side only.
3. The Data agent splits 170 clips over the mapped clusters by misses (largest remainder),
   first seed 7501. Each targeted seed gets its cluster's setting.
4. **Keeper re-check, after #141.**
   - At the render commit, before step 3, render seeds 7491–7494 locally with `occlusion=keeper`
     and with `occlusion=natural`, one process.
   - `keeper` stays in the mapping only if its every-frame share of mostly hidden balls is above
     `natural`'s on those 4 seeds. Otherwise its cluster moves to `unmapped`.
   - Simulation alone on main `d6040af` (after #141): across seeds 7301–7312, the best keeper
     windows held 363 frames with a keeper handling or diving, against 182 at `91d1e3b`. So
     #141 did not make keeper windows scarcer in these matches. The render check decides.
5. Run `crowded` with the live-ball rule (#136) as it is. Calibrating the occluder radius to the
   mesh (a round-1 follow-up) is not part of this round; it would change the targeted arm after
   this plan.

## 7. Training

The same for both arms. Only the arm's 170 clips differ.

- **Starting point: ours-v4** (`95d36154…`). It already knows the mesh look, so neither arm gains
  from simply seeing that look for the first time. That is what hid targeting in round 1.
  - Starting from ours-v3 would put the look change back into both arms.
  - Starting from ours-v4-ctrl would work equally well; ours-v4 is chosen because it is the model
    whose validation failures choose the targeted windows (section 6).
- **Data:** the 160 base clips plus the arm's 170 clips, stride 5. About 330 clips, 16,500 images.
- **Validation:** the 24 mesh clips (7401–7424). Early stopping uses the same rule for both runs
  (patience 3, at most 8 epochs).
- **Config:** [finetune-round2.json](../../../ninety/vision/finetune-round2.json). It is
  finetune-round1.json with the new `val_seeds` and nothing else changed.
- **Models:** ours-v5 (targeted) and ours-v5-ctrl, one after the other on one 24 GB GPU.

## 8. Cost and time

| Item | Amount | Cost |
|---|---|---|
| Azure render: 170 targeted, 170 control, 24 validation | 364 clips at about $0.04 | **about $14.60** |
| Local render: 30 test clips and 8 keeper re-check clips | Mac, about 50 and 32 min | $0 |
| GPU: two fine-tunes on a 1g.24gb slice | about 80 min each as in round 1, plus about 30 min setup and fetch: about 3.2 h | **about $2.20** at $0.69 an hour |
| **Total** | | **about $17** |

Wall time from the go:

| Step | Time |
|---|---|
| Test render and freeze (local) | about 1 h, plus a maintainer's upload |
| Validation clips (Azure) and the control arm, which needs no clusters | together, about 1 h |
| ours-v4 on validation, clusters, keeper check | about 1.5 h |
| Targeted arm (Azure) | about 1 h at 20 parallel executions |
| Training | about 3.2 h |
| Scoring, every frame of 30 clips | about 4 h per model on the Mac; the two primary models run at once (about 4 to 5 h) |

Scoring caveat:
- Detection cannot run on the GPU pod as it is: `detect` reads frame numbers from `frames.jsonl`,
  which is the test set's answer key, and that never leaves our storage.
- A labels-free frame index (clip, frame, t, image) written at freeze time would let detection run
  on the pod. That is a small change to `detect`; it is offered, not assumed.

## 9. Deviations and the render commit

- **Render commit:** not chosen yet (section 2).
- **Deviations:** none yet. Any change after this commit is listed here with its date and reason,
  before results are read.
