# Targeted data round 1: plan

Status: **plan, not rendered.** Rendering on Azure waits for the Coordinator's approval of the
spend. Nothing here has been trained on.

**Rubric:** Technological implementation and Agentic design. The Vision Auditor's clusters go to
the Data agent, which turns them into render requests; the before and after on a fixed test set
shows whether targeted synthetic data raised recall where the detector is weakest.

## 1. The weakness, from the training side only

vision-report-v2 (PR #132) scored ours-v3 on the frozen test set: mostly hidden balls 0.493 recall,
mostly hidden players 0.893. Those are the headline numbers, but the test set's per-frame results
never choose what to render: that would fit round 1 to the test set. The clusters come from
ours-v3's **validation clips** instead: the 24 training seeds held out of fitting (its
train-manifest.json `val_seeds`), fetched exactly as dataset v1 lists them.

    uv run python -m ninety.vision.detect <val>/seed<N> --checkpoint ours-v3 --weights <ours-v3> --stride 5
    uv run python -m ninety.vision.failure_clusters <val>/seed* --detections detections-ours-v3.jsonl \
        --round round1 --out docs/eval/round1/clusters.json

`failure_clusters` refuses any seed that is not a training seed. It matches with the scorer's own
rule (`vision_score.match`, threshold 0.5) and puts every label in one situation from the ground
truth's geometry (its docstring has the rules). Output: [clusters.json](clusters.json) (the Data
agent's input) and [audit.json](audit.json) (every class, visibility group, situation and kit
contrast, with labels and misses).

ours-v3 on its validation clips (1,200 frames at stride 5):

| | labels | missed | recall |
|---|---|---|---|
| Ball, visible | 805 | 14 | 0.983 |
| Ball, partly hidden | 159 | 12 | 0.925 |
| **Ball, mostly hidden** | 129 | 56 | **0.566** |
| Player, visible | 11,091 | 54 | 0.995 |
| Player, partly hidden | 312 | 16 | 0.949 |
| **Player, mostly hidden** | 76 | 18 | **0.763** |

Mostly hidden, by situation:

| Situation | Ball: missed of labels (recall) | Player: missed of labels (recall) |
|---|---|---|
| behind a player | 38 of 95 (0.600) | 11 of 62 (0.823) |
| behind the keeper | 9 of 17 (0.471) | 0 of 0 |
| behind a player in a crowd (3+ within 4 m) | 3 of 6 (0.500) | 4 of 6 (0.333) |
| no occluder found | 6 of 11 (0.455) | 3 of 8 (0.625) |
| behind the goal frame, by the boards, at the edge | none | none |

What it says:
- **A player on the lens's sight line is most of it**: 41 of 56 mostly-hidden ball misses and 15
  of 18 player misses. That is what `occlusion=crowded` aims a window at
  (`scene.crowded_start` ranks windows by frames with a player on the line to the ball).
- **The keeper is the worst-recall situation** (0.471) and nothing aimed at it. A catch, parry or
  dive puts arms and body over the ball, which `crowded` does not look for. This PR adds
  `occlusion=keeper` (below).
- **Low-contrast kits are not the driver.** Mostly hidden balls: 0.519 in low-contrast clips (27
  labels) against 0.578 in normal ones (102), inside the noise at these counts. Round 1 leaves
  `kit_contrast` to each seed's own draw (30% low, `params.HARD_CASE_RATE`).
- **Boards and the goal frame** miss nothing mostly hidden here: dataset v1 already re-rendered
  the clips with a ball behind the boards (#118).
- "No occluder found" (9 misses) has no render setting; `failure_clusters` lists it as `unmapped`
  so the Data agent never spends clips on it as ordinary footage. The rules see players only, so
  the scorebug and the net are candidates; it is left for a person to look at.

Counts are small (129 and 76 labels). These shares decide where clips go; they are not results.

## 2. Render settings

| Cluster | Setting | Status |
|---|---|---|
| behind a player, behind a player in a crowd (ball and player) | `occlusion=crowded` | on main since #101 |
| behind the keeper | `occlusion=keeper` | **new in this PR** |

`occlusion=keeper` (`ninety/render/scene.py`, `keeper_start`) picks the 10 s window, from the same
search range as `crowded`, with the most frames where a goalkeeper's action is `hands`, `dive` or
`throw` (the engine's names for his touch and his dive), ties broken by frames with the ball in a
penalty area (Law 1: 16.5 m by 40.32 m). It chooses which part of the match to film and changes
nothing in the match. Seeds never draw it; it is an override only, so the test set (which refuses
overrides) is unchanged. Tests: the window choice on planted frames, the outfield player's touch
not counted, the penalty area's size, a simulated match's keeper window busier than its average,
and `choose_start` honouring the override. Each was mutation-checked: every planted defect turned a
test red, with the run's pass and fail counts shown (lesson 95).

## 3. The round

The Data agent splits the budget by misses (`ninety/agents/data_agent.py`, largest remainder):

    uv run python -m ninety.agents.data_agent docs/eval/round1/clusters.json --first-seed 7101 --budget 80 \
        --commit <render commit>

| Clips | Setting | Cluster (misses) |
|---|---|---|
| 47 | `occlusion=crowded` | ball mostly hidden, behind a player (38) |
| 13 | `occlusion=crowded` | player mostly hidden, behind a player (11) |
| 5 | `occlusion=crowded` | player mostly hidden, behind a player in a crowd (4) |
| 4 | `occlusion=crowded` | ball mostly hidden, behind a player in a crowd (3) |
| 11 | `occlusion=keeper` | ball mostly hidden, behind the keeper (9) |

- **80 clips**, 69 crowded and 11 keeper, as 11 requests of up to 10 clips.
- **Seeds 7101 to 7180.** Training seeds (the Data agent and the job refuse any other) and unused:
  dataset v1 ends at 6030, and no run in the `renders` container has a seed in 7000 to 7999.
  7001 to 7004 are this plan's local sample (section 4) and are not part of the round.
- **Cost:** about $0.04 a clip on the Container Apps job, **about $3.20**, plus one fine-tune
  (section 5).
- **Commit:** one commit for the whole round, recorded in every request and in `clip.json`. It must
  hold `occlusion=keeper`, so it is main after this PR merges. Rendering the crowded part from
  today's main (`9b8782e`) and the keeper part later would split one round over two engines.

## 4. Expected effect: local sample

`ninety-data-stats --floors` on a small local sample, one render process at a time (seeds 7001 to
7004, each rendered three ways, renderer at this branch):

SAMPLE_TABLE

## 5. The skinned mesh, and a test set to match

Dataset v1 and the frozen test set (`cca498c`) were drawn with **capsule** players. Main draws the
**skinned kit mesh** since a3d228e, and the engine has also moved since `engine-v1` (#58 kick
error, #90 foot reach). Round 1 rendered from main therefore differs from v3's training data in
look and engine, and so does the demo footage. Scoring the after model only on the capsule test set
would publish numbers for a look the demo no longer shows.

The mesh change did not bump `RENDERER_VERSION` (0.3.2 for both looks): fixed in this PR (0.4.0)
with lesson 97.

**Proposal: round 1 and a re-frozen mesh test set come together, from the same commit.**
1. Re-render the five test seeds (900001 to 900005, their own sampled parameters, no overrides) at
   the round's commit and freeze them as a second test set (`test-frozen-<commit>`, hashes in a new
   freeze file). Check `TEST_FLOORS` (at least 5% of in-shot balls under half visible) before
   freezing. The capsule test set stays frozen and reported, so v1 and v2 keep their meaning.
2. **Before:** ours-v3 on the mesh test set. This is new, and it may drop against v2's numbers:
   that is the look change, measured.
3. **After:** ours-v4, ours-v3 fine-tuned on dataset v1 plus round 1, same schedule as v3.
4. **Control, so the gain is not just the new look:** ours-v4-ctrl, the same fine-tune on dataset
   v1 plus 80 *untargeted* clips from the same commit (seeds 7201 to 7280, their own draws). Round
   1 changes both the look and the situations; only the difference between v4 and v4-ctrl on the
   mostly hidden groups is the targeting. About $3.20 more and one more fine-tune.

Without the control, the before and after would credit targeting for what the mesh did.
Without the re-frozen test set, the published numbers would describe capsules.

## 6. Spend to approve

| Item | Cost |
|---|---|
| Round 1, 80 clips | about $3.20 |
| Control, 80 clips | about $3.20 |
| Mesh test set, 5 clips | about $0.20 |
| Two fine-tunes (v4, v4-ctrl), about 40 min each as v3 | rented GPU, as v3 |

Order: merge this PR, render the 165 clips from that commit, freeze the mesh test set before any
model is scored on it, then train and score.
