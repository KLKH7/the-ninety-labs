# Evaluation

How every number in the README is produced. A number is published only when the command below
generated it and the output file is committed. Rows marked *planned* have no result yet.

| Measure | Command | Output | Status |
|---|---|---|---|
| Simulator realism (passes, shots, tackles, pass completion per match) | `uv run pytest tests/test_sim.py` | test assertions | running |
| Keeper saves (isolated central shots at 8 to 25 m against the O1 position, and on-target shots in 12 matches) | `uv run python -m ninety.sim.saves` | `docs/eval/saves.md` | running: a report beside GROUNDING O1, never a target |
| Penalties (scored, keeper's side, stops, on target) | `uv run python -m ninety.sim.penalties` | `docs/eval/penalties.md` | running: a report beside published figures, never a target |
| Event and frame schema validity | CI `smoke` job | CI log | running |
| Same seed, same match on every machine: the simulator's math pinned bit for bit, and no C math library call where ground truth or a published number is computed | `uv run pytest tests/test_fmath.py tests/test_cues.py`; CI `portable` job on macOS, `test` on Linux | test assertions | running: seeds 1, 2, 3, 11, 42 (3 minutes) and seed 7 (5 minutes, every frame at full precision) are identical on macOS arm64 and Linux arm64 and x86_64, Python 3.11 and 3.12 |
| Ground-truth data meets the data contract (consistency and physics) | `uv run ninety-validate <clip>` | command output | running: the engine meets the contract on full matches (seeds 7, 11, 21); CI runs it on the smoke clip |
| Render checks (projection error, label completeness, determinism, ball occlusion share) | `uv run ninety-render-check <clips> --determinism --report docs/eval/render-checks.json`; CI `render` job on every push | `docs/eval/render-checks.json`, CI log | running |
| Training data against its floors (clips, frames, player and ball boxes, balls by visibility, ball size at the training input, clips per render knob) | `uv run ninety-data-stats <train clips> --stride 5 --input 640x640 --out docs/eval/dataset-stats.json --floors` | `docs/eval/dataset-stats.json` | running: dataset v1, 308 training clips, all on `engine-v1`'s engine (`docs/eval/dataset-v1.json` lists each clip's run and commit): 248 from v3, 30 from topup1 (`occlusion=crowded`, `kit_contrast=low`), both at `b319f21` with renderer 0.3.1, and 30 at `cca498c` (renderer 0.3.2, #118) replacing the v3 clips whose ball rests behind the boards, labelled visible at 0.3.1 (1,043 of v3's 13,443 ball training labels). 0.3.2 changes labels only, so the two renderers' images mix. Seed 82 is dropped (a blocked shot is touched again after the window's cut, which no clip can show) and seed 111 failed the render checks twice (one foot outside its box). Meets every train floor: 1,579 mostly hidden ball labels of 13,856 (11.4%) against 400 and 5%, low-contrast kits 43.8% and crowded windows 60% against 20%. All 308 meet the data contract (`ninety-render-meta`, then `ninety-validate`'s checks at `0dd5190`, main with #108). The floors were set before any data was counted; the learning curve decides whether they are enough |
| Off-the-shelf detector recall on renders (guide check 2) | planned | `docs/eval/render-checks.json` | planned |
| Detection precision and recall (players, ball) on the fixed test set, by difficulty, strict and lenient matching | pixel boxes: `uv run python -m ninety.eval.vision_report --test <frozen test clips> --detections <seed<N>.jsonl folder> --out <report.json>`; pitch-level strict and lenient matching planned | `docs/eval/vision-report-v{n}.json`, `docs/eval/vision-report-v1.md`, `docs/eval/vision-report-v2.md` | running for pixel boxes: ours-v3 on the frozen test set, players 0.994 recall at 0.999 precision, ball at least half visible 0.964 at 0.994, ball mostly hidden 0.493 at 0.841 (v2; ours-v2 in v1). Pitch-level matching planned |
| Event precision, recall and F1 per type; possession accuracy; speed error | events: `uv run python -m ninety.eval.event_score --truth <clip>/events.jsonl --frames <clip>/frames.jsonl --detected <detected.jsonl> --report <report.json>` ([format](#event-report-format)); possession and speed planned | `docs/eval/vision-report-v{n}.json` | planned: the harness runs and is tested on damaged simulator events; no detector yet |
| Targeted data rounds, before and after | planned | `docs/eval/vision-report-v{n}.json` | planned |
| Stats engine facts: hand-computed cases, planted defects, citations, size | `uv run pytest tests/test_stats.py` | test assertions | running |
| Late drop in high-intensity running (R7), by the protocol below; distance and top speed by position on the same matches | `uv run python -m ninety.sim.late_drop` | `docs/eval/late-drop.md` | running |
| Fact-checker rules (numbers, players, evidence ids) | `uv run pytest tests/test_factcheck.py` | test assertions | running |
| Personalizer rules: the A2A round trip, the fallback within its budget, the re-check of every variant, every persona and language, profile validation ([below](#personalizer)) | `uv run pytest tests/test_personalizer.py` | test assertions | running in process: 38 tests, 18 of 18 mutants of the rules killed; not yet deployed |
| Personalizer variants from the published agent that pass the re-check and air, by persona and language, and time per A2A request | `uv run python -m ninety.personalizer.eval --seeds 21,33` (agents-live task `personalizer`) | `docs/eval/personalizer.md` | planned: waits for `ninety-personalizer` to be published |
| Ledger versioning, evidence validation, and deterministic cue fixture | `uv run pytest tests/test_ledger.py tests/test_cues.py` | `tests/fixtures/cues-seed7.jsonl` and test assertions | running: 21 tests; 108 cues for seed 7, five minutes (96 for its 48 passes, 12 of them failed and one still in flight at the end, 8 for its 4 shots and 4 for its 2 goals) |
| Fact-checker on the frozen planted-claim set, offline: catch rate, true claims wrongly stopped, the layer that decided, claims held for low-confidence detections | `uv run python -m ninety.eval.fact_checker_proof` (offline, seconds of CPU; `--check` fails if a committed file is stale, as `tests/test_fact_checker_proof.py` does) | `docs/eval/fact-checker-planted.md`, set `docs/eval/planted-claims-v1.json` | running: 175/175 planted false claims kept off air (127 recorded, 16 on phantom low-confidence detections, all held by the confidence gate, 32 with viewer text spliced in); 7/121 true claims wrongly stopped, all by the recorded Judge. Judge answers are those recorded from `ninety-judge:1` at `9be98bd`; the gate threshold (0.5) is a design value until detector calibration is measured |
| Fact-checker catch rate on planted false claims, and true claims wrongly rejected, on the published Judge | `uv run python -m ninety.eval.factcheck_eval --seeds 21,33 --foundry`; nightly in `.github/workflows/evals.yml`, recorded in Foundry | `docs/eval/fact-checker.md` | running: held-out seeds 21,33, `ninety-judge:1` at commit `9be98bd`: 136/136 false claims caught (code alone 32/136); 7/105 true claims wrongly rejected excluding service holds (17/115 including them); 19 of 251 Judge calls failed and were held back (fail closed), more than earlier runs, not yet investigated |
| Analyst first drafts that would air (code checks then the Judge), and Foundry's agent evaluators (task adherence, intent resolution, tool call accuracy; model-graded) on the same responses, published agents, held-out seeds | `uv run python -m ninety.agents.analyst_eval --foundry`; nightly in `.github/workflows/evals.yml`, recorded in Foundry | `docs/eval/analyst.md` | running: seeds 21,33, `ninety-analyst:3` (match tools called by Foundry over MCP) at commit `d911c0b`: 5/10 first drafts would air; Foundry evaluators intent resolution 10/10, tool call accuracy 10/10, task adherence 4/10. Ten drafts is a small sample: an identical run minutes earlier gave 6/10 and task adherence 1/10; the nightly history in Foundry is the better guide |
| Match engine touches: control by surface, whose ball and speed; throw-ins; pass completion | `uv run python -m ninety.sim.touches` (seeds 40 to 47) | `docs/eval/touches.md`, `docs/eval/funnel-touches.md` | running: a report, never a gate; comparisons fixed below. Seeds 40 to 47, before and after the cushioned touch (base d38ce9b): thigh, chest or head touches 3,693 then 706 (passers now judge them by the engine's own rule), kept 59% then 61%; all touches except the dribbler's own kept 87% then 97%; throw-ins 89.5% then 86.1% first contact by a team-mate (Stone 2021: 83%), 67.3% then 58.3% held 5 s later (54%); completion 82.1% then 88.2% (R3: 75 to 88%). With a surface for each height (same seeds and base): thigh, chest or head touches 690, kept 62.5%; throw-ins 87.3% first contact by a team-mate, 67.6% held 5 s later; completion 87.4%. With what makes a touch worse: thigh, chest or head kept 46.4%; throw-ins 87.5% first contact by a team-mate, 54.1% held 5 s later (Stone 2021: 54%); completion 87.2%; goals 1.44 a team over seeds 40 to 63 (1.0 on the eight seeds alone, within noise; lesson 89). With the foot-reach touch, on main b319f21: thigh, chest or head touches 457, kept 46.4%; throw-ins 82.2% first contact by a team-mate, 58.4% held 5 s later; completion 88.8%; goals 1.08 a team against 1.52 on main over seeds 40 to 63 (difference -0.44, standard error 0.28: not settled; 0.75 against 1.75 on the eight seeds alone) |
| Recovery from injected failures (Judge down, Judge timeout, Judge malformed reply, Analyst or MCP tool error, MCP timeout, Analyst malformed reply, low-confidence detection) | `uv run python -m ninety.eval.fact_checker_proof` (offline, seconds of CPU; `--check` fails if a committed file is stale, as `tests/test_fact_checker_proof.py` does) | `docs/eval/failure-table.md` | running: 7 of 7 recovered on the live path with stand-in models: nothing unverified aired and the template cues stayed up; each row asserted by `tests/test_failure_table.py`. Latencies not measured (stand-in models) |
| Ablation: the fact-checker without the confidence gate, without typed facts, and absent, on the same planted set | `uv run python -m ninety.eval.fact_checker_proof` (offline, seconds of CPU; `--check` fails if a committed file is stale, as `tests/test_fact_checker_proof.py` does) | `docs/eval/ablation.md`, per claim `docs/eval/ablation.json` | running: false claims on air: full 0/175, no gate 16/175 (every phantom detection), no typed facts (the Judge alone) 24/175: every phantom plus 8 claims stating the minute and second as a clock ("1:05" for 00:05), which only the code checks catch, no fact-checker 175/175. The Judge answers to the 48 claims only the code checks had seen were recorded once from `ninety-judge:2` (`uv run python -m ninety.eval.planted_judge`, 48 calls, 50,708 tokens, $0.025 at list price) |
| Ablation: one agent with every tool against the full workflow | planned | `docs/eval/ablation.md` | planned |
| Latency to graphic and to speech (p50, p95); cost per match | planned | `docs/eval/latency-cost.md` | planned |

## Match engine: touches

How a player meets the ball is about to change (a cushioned first touch, a surface for each height,
and what makes a touch worse; [ENGINE.md](ENGINE.md), layer 7). These comparisons were fixed
**before** the first of those changes, on the engine at `claude/engine-to-main` e8982ef, so no
cushion or error is set after looking at where it lands (lessons 2 and 3).

```bash
uv run python -m ninety.sim.touches                      # seeds 40 to 47; writes docs/eval/touches.md
uv run python -m ninety.sim.funnel --seeds 40,41,42,43,44,45,46,47 --out docs/eval/funnel-touches.md
```

Both run on the same eight seeds after every engine change to touches, and the results are
recorded in `docs/eval/` and [GROUNDING.md](GROUNDING.md) whatever they show.

| Engine number | Compared with | Source |
|---|---|---|
| throw-ins: first contact by a team-mate | 83% | Stone, Smith and Barry 2021, *Int J Sports Sci Coach* 16: 830-839; 16,154 Premier League throw-ins, 2018-19 |
| throw-ins: possession held 5 s after the throw (the team of the last player to have had the ball) | 54% retained | the same study; its own definition of "retained" is not yet checked against our 5 s window (*verify*) |
| pass completion (`touches.md` and the funnel) | 75 to 88% | GROUNDING R3 (*verify*) |

Not compared, only reported: control and keep rates by surface, by whose ball it was and by
arriving speed; where a kept ball ends up; body hits. No published figure for them has been
found. One is added to this table, with its source, before any engine number is read against it.
**Never a target:** a cushion, an error or a skill range is set from a cited measurement or as
design, never moved to bring these numbers onto a published figure.

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
with visibility zero are not labels: boxes are amodal, so an object in shot and fully hidden
keeps its box, but there is nothing in the image to detect.

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
(see [PLAN.md](PLAN.md#goals)). Met: the test set was frozen on Oct 18 at `engine-v1`'s engine with renderer 0.3.2 (`cca498c`,
after the scenery-occlusion fix, #118): 15.0% (188 of 1,250), of which 6.0% (75) are partly drawn and
113 fully hidden. Every clip's hashes and the first freeze are in `docs/eval/test-set-frozen.json`.

## Late drop in high-intensity running (R7)

Fixed on 2026-10-17, before any engine change was measured with it and before the command had
produced a number, so neither the seeds nor the rule can be chosen by their result. Changing any
item below starts a new protocol, recorded here with its date; it never re-runs the old one on
other seeds.

| Item | Fixed value |
|---|---|
| Matches | 30 full matches, seeds 101 to 130, 90 minutes each (`SEEDS` in `ninety/sim/late_drop.py`). None of these seeds was used to judge R7 before |
| Who | outfield players only; frames at a kick-off reset are left out (positions jump) |
| High intensity | running above 5.5 m/s (19.8 km/h), the threshold of the published study |
| Windows | the first 15 minutes of match time (0 to 15) against the last 15 (75 to 90) |
| Per match | drop = 1 − (high-intensity metres in the last 15 minutes ÷ those in the first 15), summed over all 20 outfield players |
| Statistic | the mean of the 30 per-match drops; its spread reported as the standard deviation across matches, a 95% interval for the mean (Student's t, 29 degrees of freedom) and the range of single matches |
| Published band | 20 to 45% (GROUNDING R7): about 20% in Premier League tracking ([Bradley 2009](https://sure.sunderland.ac.uk/id/eprint/3478/), 28 matches) and 35 to 45% in top-class and moderate professionals (Mohr, Krustrup & Bangsbo 2003, *J Sports Sci* 21:519–528). *Verify*: both read from abstracts, not the full papers |
| Verdict | inside the band if the mean lies within 20 to 45%, otherwise outside. If the mean is inside but its 95% interval crosses an edge, the report says so |

**Rules.**

- The protocol is run once per engine change it judges, and the result is recorded in
  GROUNDING.md (R7) whatever it shows. It is a held-out pattern: no constant is set, and no
  change kept or dropped, by looking at it ([LESSONS.md](LESSONS.md), lessons 2 and 3).
- The report records the engine commit and the date, every match's drop, and, from the same
  matches, distance and top speed by position (R2, R6, O8) and how much of the slow store (P10)
  is left at the final whistle, so a better late drop cannot hide a worse neighbour.
- **Known difference from the sources:** the engine plays 90 minutes with no half-time break
  (the real interval lets players recover), no stoppage time and no substitutes. Read the verdict
  with that in mind; the protocol does not adjust for it.

## Personalizer

The Personalizer (`ninety/personalizer`) rewrites one claim the fact-checker already verified for
each viewer profile: analyst, casual, club and player focus, in English and Spanish. The model only
words it; code decides what airs.

- **The re-check.** Every variant is checked by the fact-checker's code half (`factcheck.check`)
  against the verified claim's own evidence, and must still contain every number (as a count, so a
  repeated number cannot be lost) and every player id of the verified claim. A variant that fails,
  or is missing, is replaced by the verified English text for that profile. The client re-checks
  whatever the server returns, so a server that skipped its check still cannot air a changed number.
  The server reports why it replaced a variant; those reasons reach the trace and the evaluation,
  never the decision of what airs.
- **The fallback.** The remote has `BUDGET_S` = 3 s (a design choice: a little over a third of the
  8 s p95 target from event to verified graphic in PLAN.md, to be revisited when
  `latency-cost.md` measures the split). On a timeout, a 5xx or a refused connection the in-process
  fallback answers with the verified text at once. A 4xx or a malformed reply is a defect between
  our own two programs and raises, so it is seen rather than hidden.
- **Viewer input.** A profile is rebuilt with `Profile` on the server, whose every field is an
  allow-list; any other value, or an extra field, is refused with an A2A invalid-params error before
  the model is called. The model sees the profile only as a JSON field.

What the re-check cannot see, so a reader of any number above knows its limits:

- Two numbers of the claim swapped with each other (32.5 m and 12 m traded between two passes):
  both still appear, and both are cited.
- A verb that misstates a pass in Spanish. The fact-checker's role check reads English verbs
  ("finds"); "encuentra a" is not read, so a Spanish variant relies on the model and on the player
  ids being kept.
- A Spanish variant left in English. It is faithful, so it airs.

**Mutation run** (lesson 8), each rule broken in turn against `tests/test_personalizer.py` and
`tests/test_factcheck.py`: all 18 killed. Re-check: no fact-check of the variant, no number survival,
number survival as a set rather than a count, no player survival, no length cap, a dropped variant
still airing, the audio persona rewritten. Client: trusting the server's variants, ignoring which
persona a reply is for, falling back on any error, treating a 4xx as a 5xx, no 5xx rule, no
refused rule, no deadline, waiting for the cancelled call to unwind. Server: profiles not
validated, extra profile fields allowed. Fact-checker: ordinals not read as numbers (lesson 95).
The length-cap mutant survived the first run; its test was added after.

## Rules

- **The test set is fixed and separate.** Clips used to score detection are never used to train it,
  and targeted data rounds never add clips to the test set.
- **Every report records its inputs:** git commit, seeds, model versions and the date.
- **Results are reproducible:** each command runs from a clean clone after `uv sync`, and gives the
  same numbers on any operating system (lesson 46).
