# Evaluation

How every number in the README is produced. A number is published only when the command below
generated it and the output file is committed. Rows marked *planned* have no result yet.

| Measure | Command | Output | Status |
|---|---|---|---|
| Simulator realism (passes, shots, tackles, pass completion per match) | `uv run pytest tests/test_sim.py` | test assertions | running |
| Event and frame schema validity | CI `smoke` job | CI log | running |
| Ground-truth data meets the data contract (consistency and physics) | `uv run ninety-validate <clip>` | command output | running: the engine meets the contract on full matches (seeds 7, 11, 21); CI runs it on the smoke clip |
| Render checks (projection error, label completeness, determinism, ball occlusion share) | `uv run ninety-render-check <clips> --determinism --report docs/eval/render-checks.json`; CI `render` job on every push | `docs/eval/render-checks.json`, CI log | running |
| Off-the-shelf detector recall on renders (guide check 2) | planned | `docs/eval/render-checks.json` | planned |
| Detection precision and recall (players, ball) on the fixed test set, by difficulty, strict and lenient matching | planned | `docs/eval/vision-report-v{n}.json` | planned |
| Event precision, recall and F1 per type; possession accuracy; speed error | planned | `docs/eval/vision-report-v{n}.json` | planned |
| Targeted data rounds, before and after | planned | `docs/eval/vision-report-v{n}.json` | planned |
| Stats engine facts: hand-computed cases, planted defects, citations, size | `uv run pytest tests/test_stats.py` | test assertions | running |
| Fact-checker rules (numbers, players, evidence ids) | `uv run pytest tests/test_factcheck.py` | test assertions | running |
| Ledger versioning, evidence validation, and deterministic cue fixture | `uv run pytest tests/test_ledger.py tests/test_cues.py` | `tests/fixtures/cues-seed7.jsonl` and test assertions | running: 17 tests; 148 cues for seed 7, five minutes (74 passes, 10 of them failed; the engine made no shots in that window, so shots and goals are covered by hand-built cases) |
| Fact-checker catch rate on planted false claims, and true claims wrongly rejected | `uv run python -m ninety.eval.factcheck_eval` | `docs/eval/fact-checker.md` | re-run pending: the Judge's instructions and the tone kinds changed after the last run (fact split from tone, tone labels fitted to events, held-out and contradicted tone). Last published run, before that change, on held-out seeds 21,33: 129/129 false caught, 12/99 true rejected excluding service holds, all twelve on tone. |
| Recovery from injected failures | planned | `docs/eval/failure-table.md` | planned |
| Ablation: one agent against the full workflow | planned | `docs/eval/ablation.md` | planned |
| Latency to graphic and to speech (p50, p95); cost per match | planned | `docs/eval/latency-cost.md` | planned |

## Synthetic data

Why we generate data this way: [decision 0001](decisions/0001-synthetic-data.md). The clip and
its labels come from one command; the checks below read only the saved files.

```bash
uv run ninety-dataset --split test --seconds 10          # the fixed 5-clip test set, seeds 900001-900005
uv run ninety-render-check runs/dataset/test/seed9000* --determinism --report docs/eval/render-checks.json
```

| Check | How it is computed | Bar |
|---|---|---|
| Projection | the ball centre, projected through the saved `P`, against the centroid of the ball's drawn pixels; keypoints re-projected through `P`; each player's foot point against their pixel box | under 1 px; every foot inside its box |
| Label completeness | every frame has an image, a camera, 22 players and the ball; every drawn object has a box; no box on an undrawn one | no problems |
| Ball occlusion | share of frames with the ball in shot where its visibility is under 0.5 | above zero |
| Determinism | re-render the first clip; compare `frames.jsonl`, `events.jsonl` and image hashes | identical |
| Split integrity | `ninety/render/splits.py`: test seeds are reserved; overrides are refused on the test set | unit tests |

## Vision scoring

Fixed before the first detector runs, so no rule is tuned to a result. Every vision report
gives precision and recall (both kinds of error), on the fixed test set only. The pixel scorer
accepts `frames.jsonl` labels and detection records (`frame`, `cls`, `bbox`, `score`) and applies
a default score threshold of 0.5. This is an object-detection AP50-style rule (IoU 0.50 for
players), following the COCO evaluation conventions ([Lin et al., 2014](https://arxiv.org/abs/1405.0312)).

### Pixel boxes

Within each frame and class, eligible detections are paired one-to-one, best-first. Player boxes
match at IoU ≥ 0.50. Ball boxes match when their centre distance is ≤ 5 pixels. A label with no
match is a false negative; a detection with no match is a false positive. The report contains
TP, FP, FN, precision and recall overall, by class, and for the difficulty groups below. Boxes
with visibility zero are not labels because they were not drawn. Run:

```bash
uv run python -m ninety.eval.vision_score --frames runs/seed7/frames.jsonl \
  --detected detections.jsonl --report vision-report.json
```

### Later follow-up: pitch-level matching

Pitch-level matching is a separate future evaluation. It will map detections onto the pitch
through the camera and match them one to one, nearest first, to true positions in the same
frame. It is not part of the pixel-box score above and must not be used to interpret that score.

| Planned comparison rule | Ball | Player | Why |
|---|---|---|---|
| Strict | within 1.0 m | within 1.0 m | possession assigns the ball to the nearest player; two players are often about 2 m apart |
| Lenient | within 2.0 m | within 1.5 m | a looser comparison radius |

**Difficulty groups.** Every true ball and player is put in groups using the renderer's
labels. TP, FP, FN, precision, recall and F1 are reported for each visibility group
nested under its class (`visibility.player.visible`, for example), and independently for
each image-boundary group (`image_boundary.player.edge-touching` and
`image_boundary.player.interior`; likewise for `ball`), as well as overall:

| Group | Rule (from `frames.jsonl`) |
|---|---|
| visible | visibility ≥ 0.9 |
| partly hidden | 0.5 ≤ visibility < 0.9 |
| mostly hidden | 0 < visibility < 0.5 |
| edge-touching | saved bbox reaches any image boundary: x0 ≤ 0, y0 ≤ 0, x1 ≥ camera.width or y1 ≥ camera.height |
| interior | saved bbox reaches none of those boundaries |
| in the air (ball; planned) | height above 0.5 m, about knee height |
| blurred (planned) | camera blur streak longer than 3 px, about half the width of a ball at broadcast distance |

The boundary rule uses each frame's saved camera width and height, with no margin; labelled
frames missing those dimensions fail rather than guessing a resolution. It does not measure
a truncation percentage: saved boxes do not say how much of an object lies outside the image.
A player with bbox `[1041, 705, 1053, 720]` in a 1280×720 image and visibility 1.0 is both
visible and edge-touching. Occlusion visibility and boundary contact are separate axes.

Matching runs once, not once per difficulty group. A matched prediction inherits its true
label's group on each axis. An unmatched prediction is a false positive assigned to the
nearest true label's group in the same frame and class (bbox centre distance; ties use the
first label in saved order), even if that label was already matched. This is an attribution
convention for group precision, not evidence of a false prediction's occlusion or boundary
status. A false positive with no same-frame/class label remains in overall and by-class
counts, but cannot be assigned to a difficulty group; group FP totals can therefore be lower
than by-class FP totals. No prediction is matched twice or discarded from overall metrics.
Unmatched labels count as FN in their groups. Precision is `null` without predictions
(`TP + FP = 0`); recall is `null` without labels (`TP + FN = 0`); F1 follows the existing
convention of `null` when either metric is undefined or both are zero.

The ball target (recall ≥ 0.90) applies to balls at least half visible; the other groups are
reported, never left out.

**Events.** A detected event matches a true event of the same type and team within 1.0 s
(25 frames), one to one. Precision, recall and F1 are reported per type; pass F1 is the
headline.

**The test set must be hard enough.** Each report states the share of test frames with the ball
in shot and less than half visible. The target before freezing the test set is at least 5%
(see [PLAN.md](PLAN.md#goals)).

## Rules

- **The test set is fixed and separate.** Clips used to score detection are never used to train it,
  and targeted data rounds never add clips to the test set.
- **Every report records its inputs:** git commit, seeds, model versions and the date.
- **Results are reproducible:** each command runs from a clean clone after `uv sync`.
