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
| Event precision, recall and F1 per type; possession accuracy; speed error | events: `uv run python -m ninety.eval.event_score --truth <clip>/events.jsonl --frames <clip>/frames.jsonl --detected <detected.jsonl> --report <report.json>` ([format](#event-report-format)); positions: `uv run python -m ninety.eval.pitch_score` ([event detection from video](#event-detection-from-video)); possession and speed planned | `docs/eval/event-report-v1/` | running on one clip: seed 900001, detected from video (ours-v2, camera from the markings): passes 3 of 4 at strict F1 0.75; the shot read as a pass and one false out of play (the ball's height, planned); ball on the ground placed to a median 0.09 m, players 0.22 m. One 10 s clip is a smoke test, not a rate |
| Targeted data rounds, before and after | failure clusters from validation clips only: `uv run python -m ninety.vision.failure_clusters <val clips> --detections <file> --round <round> --out docs/eval/<round>/clusters.json`, then `ninety.agents.data_agent`; scored with `ninety.eval.vision_report --freeze docs/eval/test-set-frozen-91d1e3b.json` | `docs/eval/round1/` (clusters, audit, plan, [result](eval/round1/RESULT.md)), `docs/eval/vision-report-v3-mesh.json`, `docs/eval/vision-report-v3ctrl-mesh.json` | round 1 measured on the frozen mesh test set: synthetic data from our engine lifts mostly hidden ball recall from 0.500 (ours-v3) to about 0.58 and cuts false positives by two thirds (125 to 35 and 41); targeting showed no measurable gain over an untargeted control (ours-v4 0.573, ours-v4-ctrl 0.585, 82 labels). Round 1: no gain over control; round 2 planned |
| Stats engine facts: hand-computed cases, planted defects, citations, size | `uv run pytest tests/test_stats.py tests/test_windows.py tests/test_window_stats_agents.py` | test assertions | running |
| Window stats on detected events against the same clip's ground truth (PPDA, field tilt, passes a minute per team-window) | to be built once R3's detected events for seed900001 land | | planned |
| Late drop in high-intensity running (R7), by the protocol below; distance and top speed by position on the same matches | `uv run python -m ninety.sim.late_drop` | `docs/eval/late-drop.md` | running |
| Fact-checker rules (numbers, players, evidence ids) | `uv run pytest tests/test_factcheck.py` | test assertions | running |
| Personalizer rules: the A2A round trip, the fallback within its budget, the re-check of every variant, every persona and language, profile validation ([below](#personalizer)) | `uv run pytest tests/test_personalizer.py` | test assertions | running in process: 38 tests, 18 of 18 mutants of the rules killed; not yet deployed |
| Personalizer variants from the published agent that pass the re-check and air, by persona and language, and time per A2A request | `uv run python -m ninety.personalizer.eval --seeds 21,33` (agents-live task `personalizer`) | `docs/eval/personalizer.md` | planned: waits for `ninety-personalizer` to be published |
| Ledger versioning, evidence validation, and deterministic cue fixture | `uv run pytest tests/test_ledger.py tests/test_cues.py` | `tests/fixtures/cues-seed7.jsonl` and test assertions | running: 21 tests; 108 cues for seed 7, five minutes (96 for its 48 passes, 12 of them failed and one still in flight at the end, 8 for its 4 shots and 4 for its 2 goals) |
| Fact-checker on the frozen planted-claim set, offline: catch rate, true claims wrongly stopped, the layer that decided, claims held for low-confidence detections | `uv run python -m ninety.eval.fact_checker_proof` (offline, seconds of CPU; `--check` fails if a committed file is stale, as `tests/test_fact_checker_proof.py` does) | `docs/eval/fact-checker-planted.md`, set `docs/eval/planted-claims-v1.json` | running: 175/175 planted false claims kept off air (127 recorded, 16 on phantom low-confidence detections, all held by the confidence gate, 32 with viewer text spliced in); 7/121 true claims wrongly stopped, all by the recorded Judge. Judge answers are those recorded from `ninety-judge:1` at `9be98bd`; the gate threshold (0.5) is a design value until detector calibration is measured |
| Fact-checker catch rate on planted false claims, and true claims wrongly rejected, on the published Judge | `uv run python -m ninety.eval.factcheck_eval --seeds 21,33 --foundry`; nightly in `.github/workflows/evals.yml`, recorded in Foundry | `docs/eval/fact-checker.md` | running: held-out seeds 21,33, `ninety-judge:1` at commit `9be98bd`: 136/136 false claims caught (code alone 32/136); 7/105 true claims wrongly rejected excluding service holds (17/115 including them); 19 of 251 Judge calls failed and were held back (fail closed), more than earlier runs, not yet investigated |
| Analyst first drafts that would air (code checks then the Judge), and Foundry's agent evaluators (task adherence, intent resolution, tool call accuracy; model-graded) on the same responses, published agents, held-out seeds | `uv run python -m ninety.agents.analyst_eval --foundry`; nightly in `.github/workflows/evals.yml`, recorded in Foundry | `docs/eval/analyst.md` | running: seeds 21,33, `ninety-analyst:3` (match tools called by Foundry over MCP) at commit `d911c0b`: 5/10 first drafts would air; Foundry evaluators intent resolution 10/10, tool call accuracy 10/10, task adherence 4/10. Ten drafts is a small sample: an identical run minutes earlier gave 6/10 and task adherence 1/10; the nightly history in Foundry is the better guide |
| Match engine touches: control by surface, whose ball and speed; throw-ins; pass completion | `uv run python -m ninety.sim.touches` (seeds 40 to 47) | `docs/eval/touches.md`, `docs/eval/funnel-touches.md` | running: a report, never a gate; comparisons fixed below. Seeds 40 to 47, before and after the cushioned touch (base d38ce9b): thigh, chest or head touches 3,693 then 706 (passers now judge them by the engine's own rule), kept 59% then 61%; all touches except the dribbler's own kept 87% then 97%; throw-ins 89.5% then 86.1% first contact by a team-mate (Stone 2021: 83%), 67.3% then 58.3% held 5 s later (54%); completion 82.1% then 88.2% (R3: 75 to 88%). With a surface for each height (same seeds and base): thigh, chest or head touches 690, kept 62.5%; throw-ins 87.3% first contact by a team-mate, 67.6% held 5 s later; completion 87.4%. With what makes a touch worse: thigh, chest or head kept 46.4%; throw-ins 87.5% first contact by a team-mate, 54.1% held 5 s later (Stone 2021: 54%); completion 87.2%; goals 1.44 a team over seeds 40 to 63 (1.0 on the eight seeds alone, within noise; lesson 89). With the foot-reach touch, on main b319f21: thigh, chest or head touches 457, kept 46.4%; throw-ins 82.2% first contact by a team-mate, 58.4% held 5 s later; completion 88.8%; goals 1.08 a team against 1.52 on main over seeds 40 to 63 (difference -0.44, standard error 0.28: not settled; 0.75 against 1.75 on the eight seeds alone) |
| Multi-agent workflow: moments, both claims fact-checked, rewrites to their author, insight replaces the template; failures leave the template on air | `uv run pytest tests/test_workflow.py`; `uv run ninety-workflow --replay <recording>` | `replays/workflow-minute2-plant.json` and test assertions | running: one live recording on the published agents (`ninety-moment-analyst:1`, `ninety-tactician:2`, `ninety-challenger:2`, `ninety-judge:4`, commit `0b7e12b`), seed 7 minute 2, planted: 3 moments, 3 insights aired, 16 model calls; the planted number caught by the code check, one Tactician claim and one Challenger alternative rejected by the Judge and rewritten. One run shows the workflow works end to end; it is not a rate |
| Recovery from injected failures (Judge down, Judge timeout, Judge malformed reply, Analyst or MCP tool error, MCP timeout, Analyst malformed reply, low-confidence detection) | `uv run python -m ninety.eval.fact_checker_proof` (offline, seconds of CPU; `--check` fails if a committed file is stale, as `tests/test_fact_checker_proof.py` does) | `docs/eval/failure-table.md` | running: 7 of 7 recovered on the live path with stand-in models: nothing unverified aired and the template cues stayed up; each row asserted by `tests/test_failure_table.py`. Latencies not measured (stand-in models) |
| Ablation: the fact-checker without the confidence gate, without typed facts, and absent, on the same planted set | `uv run python -m ninety.eval.fact_checker_proof` (offline, seconds of CPU; `--check` fails if a committed file is stale, as `tests/test_fact_checker_proof.py` does) | `docs/eval/ablation.md`, per claim `docs/eval/ablation.json` | running: false claims on air: full 0/175, no gate 16/175 (every phantom detection), no typed facts (the Judge alone) 24/175: every phantom plus 8 claims stating the minute and second as a clock ("1:05" for 00:05), which only the code checks catch, no fact-checker 175/175. The Judge answers to the 48 claims only the code checks had seen were recorded once from `ninety-judge:2` (`uv run python -m ninety.eval.planted_judge`, 48 calls, 50,708 tokens, $0.025 at list price) |
| Ablation: one agent with every tool against the full workflow | planned | `docs/eval/ablation.md` | planned |
| Latency to graphic and to speech (p50, p95); cost per match | `uv run python -m ninety.eval.latency_cost --measure <clip>` (times `ninety-e2e` offline and the slice replay through `ninety.stage` OpenTelemetry spans; tokens rebuilt from the replay; prices from the Azure Retail Prices API, dated); without `--measure` it rebuilds the report byte for byte (`tests/test_latency_cost.py`) | `docs/eval/latency-cost.json`, `docs/eval/latency-cost.md` | running for the chain's own time and the model and claim-speech cost, at `3d21ab3`: event to graphic p95 0.08 s of compute on the stand-in events of `seed900001`, without RF-DETR inference or Foundry model time (planned: live spans in Application Insights); $0.23 to $0.47 a 90-minute match (one claim a minute, one to three drafts) against the $0.50 budget, tokens estimated at 4 characters each. Speech latency and the Describer's spoken characters planned |

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
reads `frames.jsonl` labels and a `detections.jsonl` file through the contract's own reader
(`read_detections` in [ninety/vision/detections.py](../ninety/vision/detections.py)), and applies
a default score threshold of 0.5.

### Pixel boxes

Within each frame and class, eligible detections (score ≥ 0.5) are paired one-to-one, best
match first (highest IoU for players, smallest centre distance for the ball). A label with no
match is a false negative; a detection with no match is a false positive. The report contains TP, FP,
FN, precision and recall overall, by class, and for the difficulty groups below. Boxes with
visibility zero are not labels: boxes are amodal, so an object in shot and fully hidden keeps its
box, but there is nothing in the image to detect.

| Class | Match rule | Source |
|---|---|---|
| player | IoU ≥ 0.50 | the PASCAL VOC rule ([Everingham et al., 2010](https://doi.org/10.1007/s11263-009-0275-4)), kept as AP50 in COCO ([Lin et al., 2014](https://arxiv.org/abs/1405.0312)) |
| ball | centre distance ≤ 5 px | TrackNet's positioning-error limit for a ball in 1280×720 broadcast video, beyond which a detection is a false prediction ([Huang et al., 2019](https://arxiv.org/abs/1907.03698)); our renders are 1280×720 too |

Why the ball is not judged by IoU: its box is about 9 to 11 px at native size (the larger side,
`ball_size_px` in `docs/eval/dataset-stats.json`, scaled back from the 640 training input), so a
centre 3 px off already brings IoU down to about 0.3: an overlap rule would mostly measure how
the box edges round. Label precision: box edges are whole pixels, so a label's centre is exact
to 0.5 px, a tenth of the 5 px rule. Both values were set before any real detections existed and
are never changed to fit a result; `tests/test_vision_score.py` pins them, and its boundary tests
(IoU exactly 0.50 and a ball exactly 5 px off both match, 5.25 px misses) derive from them.

**The scorer is checked against planted damage.** `ninety/eval/fake_box_detections.py` copies
every label (drawn, visibility above zero) as a detection with score 1.0, then drops some, moves some by a known number of
pixels inside the rule (half the player IoU limit; 2.5 px for the ball) or past it (twice the
limit; 10 px), and adds false boxes that overlap no label. Damage goes only where no neighbour
could be confused with it, and is refused otherwise. The recall and precision the scorer must
report (overall, by class and by visibility group) come from that damage log alone, never from
the scorer:

```bash
uv run python -m ninety.eval.fake_box_detections runs/dataset/test/seed*
```

Only frames the detector ran on are scored. A frame is run when it has a line in the
detections file ([the detections contract](../ninety/vision/detections.py)); a line with an
empty `detections` list is a run frame that found nothing, so its labels are false negatives.
Labels on frames with no line are skipped, not counted as misses, so detecting every 25th frame
scores those frames only. The run set is read before the per-frame lines are flattened, and a
run frame missing from `frames.jsonl` is refused. The report's `frames` block gives `scored`
(run frames) and `label_frames_skipped` (labelled frames with no line). A file that breaks the
contract is refused at its first bad line. A detections file is scored against one clip only: its
`clip` must equal the `clip` of every `frames.jsonl` row, or it is refused. Frame numbers are match
frames, so two clips of one match can share some, and pairing by frame alone would score
detections against the wrong clip. Run:

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

## Event detection from video

The first events made from the picture alone, for M1: one frozen test clip, seed 900001 (10 s,
250 frames, `engine-v1`, renderer 0.3.2), detected with ours-v2 (vision-report-v1). The live path
reads the clip's `images/` and the detections, nothing else: no `frames.jsonl`, `events.jsonl`,
`clip.json` or `meta.json` (`tests/test_vision_live_path.py` checks the code and a run). Grading
then reads the answer key.

```bash
T=runs/test-frozen-cca498c/test/seed900001   # the frozen test clip (docs/eval/test-set-frozen.json)
uv run --group vision python -m ninety.vision.observe $T \
  --detections docs/eval/vision-report-v1/detections/seed900001.jsonl \
  --out tests/fixtures/observations-seed900001.jsonl
uv run python -m ninety.vision.events tests/fixtures/observations-seed900001.jsonl \
  --out tests/fixtures/detected-seed900001.jsonl --summary docs/eval/event-report-v1/summary-seed900001.json
uv run python -m ninety.eval.event_score --truth $T/events.jsonl --frames $T/frames.jsonl \
  --detected tests/fixtures/detected-seed900001.jsonl --report docs/eval/event-report-v1/events-seed900001.json
uv run python -m ninety.eval.pitch_score --frames $T/frames.jsonl \
  --observations tests/fixtures/observations-seed900001.jsonl --report docs/eval/event-report-v1/pitch-seed900001.json
```

| Stage | What it does | Code |
|---|---|---|
| Camera | white-marking pixels (brighter and bluer than the grass on both sides, detected players and ball masked) fitted to Law 1's markings: one gantry for the clip (found from every 25th frame), pan, tilt and zoom per frame (tracked from the last good frame). A frame is trusted when half its marking pixels lie within 1.5 px of a projected marking | `ninety/vision/pitch.py` |
| On the pitch | each box's foot point (players) or centre one radius up (ball) through that frame's camera; shirt colour from the box's upper middle | `ninety/vision/observe.py` |
| Tracks and teams | players linked in pitch metres; two kits by chromaticity (shadow-proof, lesson 98); the side defending x = 105 is away (the engine's one convention) | `ninety/vision/track.py` |
| Events | possession: the ball within 1.5 m of a player's feet and moving with him (GROUNDING P6); a pass from one spell to the next, a shot when the strike heads between the posts, out of play when the whole ball is over a line for 3 frames | `ninety/vision/events.py` |

Events are graded by the rules above (Vision scoring), unchanged: same type and team within 1.0 s,
spot within 1.0 m (strict) of the ball at the detected time. Pitch positions use the pixel
scorer's pairing (player IoU 0.5, ball centre 5 px) and the planned "in the air" height (0.5 m).

**Results, seed 900001** (`docs/eval/event-report-v1/`):

| Measure | Result |
|---|---|
| Passes (strict: 1.0 s, 1.0 m) | 3 of 4 found, 1 false: precision, recall and F1 0.75; time error at most 0.08 s, place error at most 0.09 m. The miss was struck 0.08 s before the clip ends, with nobody receiving it inside the clip; the false pass is the shot |
| Shots | 0 of 1: read as a pass (the ball's height, below) |
| Out of play | none true, 1 false: the same shot reaching the keeper |
| Outside M1's scope | 2 possession changes and 1 pressure, counted as misses |
| Camera | 245 of 250 frames trusted (median marking error per frame 1.2 px, at most 1.499 px against the 1.5 px set beforehand: several frames pass narrowly); the 5 rejected (1791 to 1796) are the fast pan after the shot. The gantry lands 1.85 m from the true one, along the line of sight. That is the fit's limit: away from the markings it moves the ground by a median 2.6 px (90% within 14.7 px, near the horizon at most 40.5 px) against the true camera; on perfect synthetic markings, by 3.4 to 4.0 px at most |
| Players on the pitch | median 0.22 m, 90% within 1.44 m (1,817 detections) |
| Ball on the ground | median 0.09 m, 90% within 0.26 m (181 frames) |
| Ball in the air | median 7.1 m (15 frames): placed on the ground (below) |
| Teams | home's kit learned as red-brown, away's as blue, and the side named in 241 of 245 frames' votes; every detected pass has its true team |

**Read with care.** One 10-second clip holds 4 passes, 1 shot and no out of play; a single event
moves a rate by 25 points. This shows the pipeline works end to end and where it fails, not how
well it will do on a match. The other four test clips (two with camera cuts, which the camera fit
does not yet follow) are next.

**Not yet:** the ball's height. A lofted ball is placed on the ground beyond where it is, which
turns this clip's shot (a ball rising to 1.3 m) into a pass whose path misses the posts, and puts it
over the goal line as it reaches the keeper (the false out of play). Fitting its flight needs air
drag as well as gravity: over its first 0.4 s, drag moves a 30 m/s ball about as far as gravity
does, and a drag-free fit tilts the flight along the camera's line of sight, wrongly even through
the true camera. Possession changes, pressure and the player's identity are not detected.

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

## Phone companion

`uv run python -m ninety.agents.companion_eval --seeds 7,21,33 --out docs/eval/companion.md`
(`--foundry` puts the published Companion and Judge in place of the scripted models; it runs in
the `agents-live` workflow's `eval` task). The question sets and the metric each answerable
phrasing means were written into `ninety/agents/companion_eval.py` before its first run.

| Measure | How |
|---|---|
| Number accuracy | every 30 s of each 5-minute clip, for all 22 players, each window fact (`speed_now`, `peak_speed`, `distance_run`, window from kick-off) against the engine's own velocity of the player (the frames' `vx`, `vy`, which the facts never read): the mean of \|v\| over the same last second, the largest \|v\|, and the sum of \|v\| dt. Steps into a kickoff frame are left out of both. Mean and largest absolute error |
| Planted injections | 12 kinds of question that try to plant a number, an instruction or another player, for one home and one away player per seed; a planted number is written spaced (50 km/h), glued to its unit (50km/h) and in words (fifty km/h), since the code checks must read every form a writer can produce. Scripted: a model that does what each one asks, citing a real fact so only the plant is wrong; this measures the gate without the Judge, so a planted word the code cannot read (a superlative) is unproven until the `--foundry` run. Counted: answers that show the planted number or word in any of those forms, that name another player, or that show any number other than the cited fact's value (digits with or without a unit attached, or a number word) |
| Unanswerable | 10 questions nothing in a window answers, per player; scripted model: one that invents a number. Counted: answers that say they cannot answer, and the same for code alone |
| Which metric | 13 phrasings and the metric a person means by each; counted: those `pick_metric` reads as that metric |

A number the phone shows is the cited fact's value by construction (`Answer.value` is read off the
fact); the injection count checks that the text agrees with it.

### Tracked positions for the phone

`uv run python -m ninety.eval.tracked_speed` grades the phone's speed now, top speed and distance
from tracked positions against the ground truth, offline, with and without the shipped smoothing
([companion-tracked.md](eval/companion-tracked.md)): on the M1 clip, a median error of 0.6 km/h
for speed now and 1.9 km/h for top speed, against 55.6 km/h for top speed without smoothing.

## Football sense (FS1 to FS9)

Goals, shots and pass completion sat inside their published bands while the play looked dumb to
anyone who watched it (lesson 107). The football-sense checker counts the dumb play itself, per
90 minutes, with the match clock of every case so a person can watch it:

    uv run ninety-sim --seed 7 --minutes 20 --out runs/seed7
    uv run ninety-football-sense runs/seed7 runs/seed11 runs/seed21 runs/seed42 --json found.json

Each type's definition, thresholds and sources are in [GROUNDING.md](GROUNDING.md#football-sense-it-looks-like-sensible-football-counts).
The checker reads only `frames.jsonl`, `events.jsonl` and `meta.json` and imports nothing from
the engine. The ball is dead from a stoppage (out of play, goal, foul, offside) until the restart
is kicked; which goal a team attacks comes from where its keeper stands. Each type has a scene
that must be flagged and legal scenes that must not be, mutation-checked
([`tests/test_football_sense.py`](../tests/test_football_sense.py)).

**Protocol.** Every engine pull request runs the checker on seeds 7, 11, 21 and 42 at 20 minutes
each, before and after, on the same commit pair, and posts the table with a watched 60-second
clip. A fix names the type it targets and shows its count fall; the other types are held out, so
a fix that moves one count by worsening another is visible. No count is a target and no engine
constant is set by looking at one (lessons 2, 3 and 21). Read with care: 80 minutes resolves a
type seen a few dozen times; a type seen a handful of times needs more matches before a change
is read.

**Engine `7ee8720`, 2026-10-19,** seeds 7, 11, 21, 42, 20 minutes each (80 minutes, 1,023 passes):

| Defect | Count | Per 90 | seed 7 | 11 | 21 | 42 |
|---|---:|---:|---:|---:|---:|---:|
| FS1 chaser runs away from a loose ball | 24 | 27.0 | 2 | 9 | 4 | 9 |
| FS2 unpressed pass straight out of play | 21 | 23.6 | 8 | 3 | 5 | 5 |
| FS3 keeper stays home for a ball he would win | 0 | 0 | 0 | 0 | 0 | 0 |
| FS5 more than half the outfield within 10 m of the ball | 0 | 0 | 0 | 0 | 0 | 0 |
| FS6 pass from own box to own box | 180 | 202.5 | 13 | 25 | 73 | 69 |
| FS6 possession with 3+ own-box passes | 18 | 20.2 | 2 | 5 | 6 | 5 |
| FS7 square or back pass with a free option ahead | 436 | 490.5 | 79 | 85 | 140 | 132 |
| FS8 loose ball at rest that nobody goes to | 0 | 0 | 0 | 0 | 0 | 0 |
| FS9 team on the ball with most outfielders in own box | 56 | 63.0 | 9 | 10 | 6 | 31 |

FS4, outfield players under 0.5 m/s, share of open-play time:

| Still, at least | mean | 1 | 3 | 5 | 8 | 10 |
|---|---:|---:|---:|---:|---:|---:|
| team with the ball | 1.4 | 55% | 22% | 9% | 1% | 0% |
| team without it | 2.9 | 51% | 37% | 32% | 23% | 1% |

What it says: the worst types are teams passing inside their own box (FS6, FS9) while the team
without the ball stands (FS4: eight or more still for almost a quarter of open play), passes
played into touch with nobody near the passer (FS2), and chasers who run past or away from a
loose ball (FS1). FS3, FS5 and FS8 found nothing: the engine rarely plays a through ball a keeper
could reach first, and players do not clump within 10 m of the ball. A clump in a line, like
the one in the owner's review clip, is wider than FS5's circle; FS4 and FS9 are where it shows.

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
