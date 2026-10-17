# Evaluation

How every number in the README is produced. A number is published only when the command below
generated it and the output file is committed. Rows marked *planned* have no result yet.

| Measure | Command | Output | Status |
|---|---|---|---|
| Simulator realism (passes, shots, tackles, pass completion per match) | `uv run pytest tests/test_sim.py` | test assertions | running |
| Event and frame schema validity | CI `smoke` job | CI log | running |
| Same seed, same match on every machine: the simulator's math pinned bit for bit, and no C math library call where ground truth or a published number is computed | `uv run pytest tests/test_fmath.py tests/test_cues.py`; CI `portable` job on macOS, `test` on Linux | test assertions | running: seeds 1, 2, 3, 11, 42 (3 minutes) and seed 7 (5 minutes, every frame at full precision) are identical on macOS arm64 and Linux arm64 and x86_64, Python 3.11 and 3.12 |
| Ground-truth data meets the data contract (consistency and physics) | `uv run ninety-validate <clip>` | command output | running: the engine meets the contract on full matches (seeds 7, 11, 21); CI runs it on the smoke clip |
| Render checks (projection error, label completeness, determinism, ball occlusion share) | `uv run ninety-render-check <clips> --determinism --report docs/eval/render-checks.json`; CI `render` job on every push | `docs/eval/render-checks.json`, CI log | running |
| Training data against its floors (clips, frames, player and ball boxes, balls by visibility, ball size at the training input, clips per render knob) | `uv run ninety-data-stats <train clips> --stride 5 --input 640x640 --out docs/eval/dataset-stats.json --floors` | `docs/eval/dataset-stats.json` | running: render run v1, 195 training clips (the 25 validation seeds counted apart), rendered by renderer 0.3.0 at commit f481ccf, before #80 made every clip a clear day: these seeds now render differently on main, so this report describes those clips and is superseded by render run v2. Meets every train floor except the hidden balls: 270 mostly hidden (2.8%) against 400 and 5%. Even `occlusion=crowded` clips reach only 4.0%, so more of them cannot close it; that is targeted round 1. The floors were set before any data was counted; the learning curve decides whether they are enough |
| Off-the-shelf detector recall on renders (guide check 2) | planned | `docs/eval/render-checks.json` | planned |
| Detection precision and recall (players, ball) on the fixed test set, by difficulty, strict and lenient matching | planned | `docs/eval/vision-report-v{n}.json` | planned |
| Event precision, recall and F1 per type; possession accuracy; speed error | events: `uv run python -m ninety.eval.event_score --truth <clip>/events.jsonl --frames <clip>/frames.jsonl --detected <detected.jsonl> --report <report.json>` ([format](#event-report-format)); possession and speed planned | `docs/eval/vision-report-v{n}.json` | planned: the harness runs and is tested on damaged simulator events; no detector yet |
| Targeted data rounds, before and after | planned | `docs/eval/vision-report-v{n}.json` | planned |
| Stats engine facts: hand-computed cases, planted defects, citations, size | `uv run pytest tests/test_stats.py` | test assertions | running |
| Fact-checker rules (numbers, players, evidence ids) | `uv run pytest tests/test_factcheck.py` | test assertions | running |
| Ledger versioning, evidence validation, and deterministic cue fixture | `uv run pytest tests/test_ledger.py tests/test_cues.py` | `tests/fixtures/cues-seed7.jsonl` and test assertions | running: 17 tests; 166 cues for seed 7, five minutes (83 passes, 19 of them failed; no shot in these five minutes, so shots and goals are covered by hand-built cases) |
| Fact-checker catch rate on planted false claims, and true claims wrongly rejected, on the published Judge | `uv run python -m ninety.eval.factcheck_eval --seeds 21,33 --foundry`; nightly in `.github/workflows/evals.yml`, recorded in Foundry | `docs/eval/fact-checker.md` | running: held-out seeds 21,33, `ninety-judge:1` at commit `9be98bd`: 136/136 false claims caught (code alone 32/136); 7/105 true claims wrongly rejected excluding service holds (17/115 including them); 19 of 251 Judge calls failed and were held back (fail closed), more than earlier runs, not yet investigated |
| Analyst first drafts that would air (code checks then the Judge), and Foundry's agent evaluators (task adherence, intent resolution, tool call accuracy; model-graded) on the same responses, published agents, held-out seeds | `uv run python -m ninety.agents.analyst_eval --foundry`; nightly in `.github/workflows/evals.yml`, recorded in Foundry | `docs/eval/analyst.md` | running: seeds 21,33, `ninety-analyst:3` (match tools called by Foundry over MCP) at commit `d911c0b`: 5/10 first drafts would air; Foundry evaluators intent resolution 10/10, tool call accuracy 10/10, task adherence 4/10. Ten drafts is a small sample: an identical run minutes earlier gave 6/10 and task adherence 1/10; the nightly history in Foundry is the better guide |
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

### What the data holds

`ninety-data-stats` counts, per split and from the saved labels only, what a dataset can teach the
detector: distinct seeds, frames after the stride, player and ball boxes, balls by visibility
group, ball size in pixels at the training input size, and clips per render knob. With
`--floors` it exits 1 when a split misses a floor. The floors were set before any training clip
was counted, and each one's reason is beside it in `ninety/vision/data_stats.py`. Meeting them
does not prove the data is enough; the learning curve decides that.

```bash
uv run ninety-data-stats <training clips> --stride 5 --input 640x640 --out docs/eval/dataset-stats.json --floors
```

`--input` is the training input size (`resolution` in `ninety/vision/finetune.json`, 640), so the
ball and player sizes in the report are what the detector sees.

The floors are `TRAIN_FLOORS` and `TEST_FLOORS` in `ninety/vision/data_stats.py`, each with its
reason; that file is the only table. `ball_visibility_lt_0_5_share` is the quantity PLAN.md
freezes on and `ninety-render-check` reports (every frame with the ball in shot, not only the
strided ones, fully hidden balls included); the ball-box counts are training labels and
exclude visibility 0, so the train split's hidden-ball floor is `ball_boxes_mostly_hidden_share`,
a share of those labels. Lighting and weather floors cover only the values the renderer can draw
(`PLANNED` in `ninety/render/params.py`).

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
with visibility zero are not labels because they were not drawn.

Only frames the detector ran on are scored. A frame is run when it has a line in the
detections file ([the detections contract](../ninety/vision/detections.py)); a line with an
empty `detections` list is a run frame that found nothing, so its labels are false negatives.
Labels on frames with no line are skipped, not counted as misses, so detecting every 25th frame
scores those frames only. The run set is read before the per-frame lines are flattened, and a
run frame missing from `frames.jsonl` is refused. The report's `frames` block gives `scored`
(run frames) and `label_frames_skipped` (labelled frames with no line). In the flat format (one
detection per line) a frame that found nothing cannot be written, so use the per-frame format.
Run:

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
(25 frames; exactly 1.0 s counts), one to one, the pairs closest in time taken first.
Precision, recall and F1 are reported per type; pass F1 under the strict rule is the headline.
Built in [`ninety/eval/event_score.py`](../ninety/eval/event_score.py).

The detected spot must also be right, and it is judged at the **detected** time: its distance
to where the reference object was at that moment.

| Event type | Reference object |
|---|---|
| pressure, kickoff | the player of the event's team nearest to the detected spot |
| substitution | none: graded on time only |
| every other type | the ball |

| Rule | Spot within | Use |
|---|---|---|
| Strict | 1.0 m | the headline, for the same reason as the ball and player radius above |
| Lenient | 2.0 m | for comparison |
| Time only | not checked | for comparison: how many errors are place errors |

Why the detected time and not the true one: after a pass the ball moves about 10 m/s, so a
pass detected 0.4 s late is several metres from the true event's spot even when vision placed
the ball perfectly. Judging at the true time would turn every timing error into a place error
and quietly tighten the 1.0 s window. The measurements are in
[eval/event-motion.md](eval/event-motion.md).

### Event report format

The handoff to the agents (R4): what the harness reads and what it writes.

```bash
uv run ninety-sim --seed 7 --minutes 5 --out runs/seed7
# fake detections until a detector exists: true events copied as vision output, then damaged
uv run python -c "import json; from pathlib import Path; from ninety.eval.fake_detections import fake_detections; rd = lambda p: [json.loads(l) for l in Path(p).read_text().splitlines() if l.strip()]; det, log = fake_detections(rd('runs/seed7/events.jsonl'), rd('runs/seed7/frames.jsonl'), seed=1, per_damage=1); Path('runs/seed7/detected.jsonl').write_text(''.join(json.dumps(e) + '\n' for e in det))"
uv run python -m ninety.eval.event_score --truth runs/seed7/events.jsonl --frames runs/seed7/frames.jsonl --detected runs/seed7/detected.jsonl --report runs/seed7/event-report.json
```

**Input: detected events.** One JSON object per line, each a valid
[`match_event`](../schemas/match_event.schema.json) with `"source": "vision"` and a
`confidence` from 0 to 1. The harness refuses the file if any line has another source, and
refuses a truth file that is not all `"source": "truth"`. It reads `type`, `team`, `t`, `x`
and `y`; `id` is copied into the pairs.

**Output: one JSON file**, also summarised on the terminal:

| Key | Contents |
|---|---|
| `rules` | `time_window_s` 1.0, `strict_m` 1.0, `lenient_m` 2.0, and `match`, the rule in words |
| `inputs` | `truth`, `frames`, `detected` (the paths as given), `git_commit`, `date` (YYYY-MM-DD) |
| `strict`, `lenient`, `time_only` | one block per rule, each with `per_type` and `pairs` |
| `headline` | `{"rule": "strict", "pass_f1": ...}` |

`per_type` has one entry per event type seen in the truth or the detections:

| Field | Meaning |
|---|---|
| `true`, `detected` | how many of this type are in the truth and in the detections |
| `tp`, `fp`, `fn` | matched; detected but unmatched; true but unmatched |
| `precision`, `recall`, `f1` | `tp / detected`, `tp / true`, and their harmonic mean |
| `time_error_s` | `{"mean", "max"}` of the absolute time error over matched pairs |
| `distance_m` | `{"mean", "max"}` of the distance from the detected spot to the true event's spot, over matched pairs; reported, never used to match |

`null` means undefined because a denominator is zero, never a made-up 0 or 1: precision with
nothing detected, recall with nothing true, F1 when either is `null`, and both error blocks
when nothing matched. When precision and recall are both defined and nothing matched, F1 is 0.

Each of `pairs` is one match:

| Field | Meaning |
|---|---|
| `truth_id`, `detected_id` | the two events' `id` |
| `type`, `team` | shared by both |
| `dt_s` | detected time minus true time, seconds; positive means late |
| `place_error_m` | the spot's distance to the reference object at the detected time; `null` when it cannot be measured: for a substitution, or when `outside_frames` is `true` |
| `outside_frames` | `true` when the detected time is outside the truth frames (usually past the last one), so there is nothing to be right about; such a pair can appear only in `time_only`, since `strict` and `lenient` reject it |
| `distance_m` | the spot's distance to the true event's spot |

Example from the commands above on Windows, on fake detections, so the numbers grade the
harness, not a detector (the same seed simulates a different match on Linux, so the digits may
differ there): under `strict`, `pass` had `true` 69, `detected` 69, `tp` 64 and `f1` 0.928, and an
invented `shot` (none true) had `precision` 0.0 and `recall` and `f1` `null`.

**The test set must be hard enough.** Each report states the share of test frames with the ball
in shot and less than half visible. The target before freezing the test set is at least 5%
(see [PLAN.md](PLAN.md#goals)).

## Rules

- **The test set is fixed and separate.** Clips used to score detection are never used to train it,
  and targeted data rounds never add clips to the test set.
- **Every report records its inputs:** git commit, seeds, model versions and the date.
- **Results are reproducible:** each command runs from a clean clone after `uv sync`, and gives the
  same numbers on any operating system (lesson 29).
