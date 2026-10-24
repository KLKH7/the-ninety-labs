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
| Off-the-shelf detector recall on renders (guide check 2); published off-the-shelf figures for scale: [GROUNDING.md](GROUNDING.md#vision-scoring-how-detections-are-graded) S6 (players) and S7 (ball) | planned | `docs/eval/render-checks.json` | planned |
| Detection precision and recall (players, ball) on the fixed test set, by difficulty, strict and lenient matching | pixel boxes: `uv run python -m ninety.eval.vision_report --test <frozen test clips> --detections <seed<N>.jsonl folder> --out <report.json>`; pitch-level strict and lenient: the same report's `pitch` block, totalled across clips ([below](#pitch-level-matching)); per clip, `uv run python -m ninety.eval.vision_score` | `docs/eval/vision-report-v{n}.json`, `docs/eval/vision-report-v1.md`, `docs/eval/vision-report-v2.md` | running for pixel boxes: ours-v3 on the frozen test set, players 0.994 recall at 0.999 precision, ball at least half visible 0.964 at 0.994, ball mostly hidden 0.493 at 0.841 (v2; ours-v2 in v1). Pitch-level matching built, totalled across clips and checked against planted damage; not measured yet on the frozen test set. The in-the-air and blurred groups (pixel and pitch-level) built, totalled across clips and checked against planted damage; not measured yet on the frozen test set |
| Event precision, recall and F1 per type; possession accuracy; speed error | events: `uv run python -m ninety.eval.event_score --truth <clip>/events.jsonl --frames <clip>/frames.jsonl --detected <detected.jsonl> --report <report.json>` ([format](#event-report-format)); positions: `uv run python -m ninety.eval.pitch_score` ([event detection from video](#event-detection-from-video)); possession and speed planned | `docs/eval/event-report-v2.md` | running on the frozen test set's five clips, scored once (ours-v2; the detector re-derived on validation clips, [detector-plan.md](eval/detector-plan.md)): passes 7 of 13 at strict F1 0.67 (recall 0.54, 95% 0.29 to 0.77), 4 of 9 at F1 0.62 without seed 900001, below PLAN's 0.70; the one shot read as a pass and one false out of play (the ball's height, planned); two clips with camera cuts give no events. 13 passes is too few for a rate |
| Targeted data rounds, before and after | failure clusters from validation clips only: `uv run python -m ninety.vision.failure_clusters <val clips> --detections <file> --audit docs/eval/<round>/audit.json`, then `ninety.agents.vision_auditor` (writes `clusters.json`; without a model the clusters and split are the code's), then `ninety.agents.data_agent`; scored with `ninety.eval.vision_report --freeze docs/eval/test-set-frozen-91d1e3b.json` | `docs/eval/round1/` (clusters, audit, plan, [result](eval/round1/RESULT.md)), `docs/eval/vision-report-v3-mesh.json`, `docs/eval/vision-report-v3ctrl-mesh.json` | round 1 measured on the frozen mesh test set: synthetic data from our engine lifts mostly hidden ball recall from 0.500 (ours-v3) to about 0.58 and cuts false positives by two thirds (125 to 35 and 41); targeting showed no measurable gain over an untargeted control (ours-v4 0.573, ours-v4-ctrl 0.585, 82 labels). Round 1: no gain over control; round 2 planned |
| Stats engine facts: hand-computed cases, planted defects, citations, size | `uv run pytest tests/test_stats.py tests/test_windows.py tests/test_window_stats_agents.py` | test assertions | running |
| Window stats on detected events against the same clip's ground truth (PPDA, field tilt, passes a minute per team-window) | to be built once R3's detected events for seed900001 land | | planned |
| Late drop in high-intensity running (R7), by the protocol below; distance and top speed by position on the same matches | `uv run python -m ninety.sim.late_drop` | `docs/eval/late-drop.md` | running |
| Fact-checker rules (numbers, players, evidence ids) | `uv run pytest tests/test_factcheck.py` | test assertions | running |
| Personalizer rules: the A2A round trip, the fallback within its budget, the re-check of every variant, every persona and language, profile validation ([below](#personalizer)) | `uv run pytest tests/test_personalizer.py` | test assertions | running in process: 46 tests; 18 of 18 mutants of the rules killed, and 16 of 17 of the live path and its evaluation (the survivor is equivalent: an unanswered request never airs); not yet deployed |
| Personalizer variants from the published agent that pass the re-check and air, by persona and language, and time per A2A request | `uv run python -m ninety.personalizer.eval --seeds 21,33` (agents-live task `personalizer`) | `docs/eval/personalizer.md` | planned: `ninety-personalizer:1` is published. The first live run (agents-live 39346085408, 2026-10-20) measured nothing: its sign-in had expired before the first model call, so all 20 requests fell back to the verified text. The evaluation now signs in before it simulates and refuses to write a report when the model never answered |
| Ledger versioning, evidence validation, and deterministic cue fixture | `uv run pytest tests/test_ledger.py tests/test_cues.py` | `tests/fixtures/cues-seed7.jsonl` and test assertions | running: 21 tests; 174 cues for seed 7, five minutes (166 for its 83 passes, 15 of them failed and one still in flight at the end, 6 for its 3 shots and 2 for its 1 goal) |
| Fact-checker on the frozen planted-claim set, offline: catch rate, true claims wrongly stopped, the layer that decided, claims held for low-confidence detections | `uv run python -m ninety.eval.fact_checker_proof` (offline, seconds of CPU; `--check` fails if a committed file is stale, as `tests/test_fact_checker_proof.py` does) | `docs/eval/fact-checker-planted.md`, set `docs/eval/planted-claims-v1.json` | running: 175/175 planted false claims kept off air (127 recorded, 16 on phantom low-confidence detections, all held by the confidence gate, 32 with viewer text spliced in); 7/121 true claims wrongly stopped, all by the recorded Judge. Judge answers are those recorded from `ninety-judge:1` at `9be98bd`; the gate threshold (0.5) is a design value until detector calibration is measured |
| Fact-checker catch rate on planted false claims, and true claims wrongly rejected, on the published Judge | `uv run python -m ninety.eval.factcheck_eval --seeds 21,33 --foundry`; nightly in `.github/workflows/evals.yml`, recorded in Foundry | `docs/eval/fact-checker.md` | running: held-out seeds 21,33, `ninety-judge:1` at commit `9be98bd`: 136/136 false claims caught (code alone 32/136); 7/105 true claims wrongly rejected excluding service holds (17/115 including them); 19 of 251 Judge calls failed and were held back (fail closed), more than earlier runs, not yet investigated |
| Analyst first drafts that would air (code checks then the Judge), and Foundry's agent evaluators (task adherence, intent resolution, tool call accuracy; model-graded) on the same responses, published agents, held-out seeds | `uv run python -m ninety.agents.analyst_eval --foundry`; nightly in `.github/workflows/evals.yml`, recorded in Foundry | `docs/eval/analyst.md` | running: seeds 21,33, `ninety-analyst:3` (match tools called by Foundry over MCP) at commit `d911c0b`: 5/10 first drafts would air; Foundry evaluators intent resolution 10/10, tool call accuracy 10/10, task adherence 4/10. Ten drafts is a small sample: an identical run minutes earlier gave 6/10 and task adherence 1/10; the nightly history in Foundry is the better guide |
| Match engine touches: control by surface, whose ball and speed; throw-ins; pass completion | `uv run python -m ninety.sim.touches` (seeds 40 to 47) | `docs/eval/touches.md`, `docs/eval/funnel-touches.md` | running: a report, never a gate; comparisons fixed below. Seeds 40 to 47, before and after the cushioned touch (base d38ce9b): thigh, chest or head touches 3,693 then 706 (passers now judge them by the engine's own rule), kept 59% then 61%; all touches except the dribbler's own kept 87% then 97%; throw-ins 89.5% then 86.1% first contact by a team-mate (Stone 2021: 83%), 67.3% then 58.3% held 5 s later (54%); completion 82.1% then 88.2% (R3: 75 to 88%). With a surface for each height (same seeds and base): thigh, chest or head touches 690, kept 62.5%; throw-ins 87.3% first contact by a team-mate, 67.6% held 5 s later; completion 87.4%. With what makes a touch worse: thigh, chest or head kept 46.4%; throw-ins 87.5% first contact by a team-mate, 54.1% held 5 s later (Stone 2021: 54%); completion 87.2%; goals 1.44 a team over seeds 40 to 63 (1.0 on the eight seeds alone, within noise; lesson 89). With the foot-reach touch, on main b319f21: thigh, chest or head touches 457, kept 46.4%; throw-ins 82.2% first contact by a team-mate, 58.4% held 5 s later; completion 88.8%; goals 1.08 a team against 1.52 on main over seeds 40 to 63 (difference -0.44, standard error 0.28: not settled; 0.75 against 1.75 on the eight seeds alone) |
| Multi-agent workflow: moments, both claims fact-checked, rewrites to their author, insight replaces the template; failures leave the template on air | `uv run pytest tests/test_workflow.py`; `uv run ninety-workflow --replay <recording>` | `replays/workflow-minute2-plant.json` and test assertions | running: one live recording on the published agents (`ninety-moment-analyst:1`, `ninety-tactician:2`, `ninety-challenger:2`, `ninety-judge:4`, commit `0b7e12b`), seed 7 minute 2, planted: 3 moments, 3 insights aired, 16 model calls; the planted number caught by the code check, one Tactician claim and one Challenger alternative rejected by the Judge and rewritten. One run shows the workflow works end to end; it is not a rate |
| Recovery from injected failures in the multi-agent workflow (Judge timeout, Tactician Foundry outage, Personalizer down, low-confidence detection) | `uv run python -m ninety.eval.workflow_failures` (offline, seconds of CPU, byte for byte; `--check` and `tests/test_workflow_failures.py` fail if stale); live: `--live`, agents-live `task=failures` | `docs/eval/failure-table.md`, `docs/eval/failure-table.json`; live: `docs/eval/failure-table-live.{md,json}` | running offline: 4 of 4 recovered on the workflow (W1's graph) with stand-in models around the real Judge wrapper and the real A2A Personalizer client: the templates stayed (less the unsure detection's), nothing unchecked aired, every moment's claim ended held (verified when only the Personalizer failed), the fallback was in the trace and its badge on screen; the baseline passed, which needs every profile's variant aired: none refused, none missing, and no Spanish one reading as English by function words (`personalizer/language.py`). Offline the stand-in Personalizer's Spanish is a wording written for the table, not a translation. Live: the Analyst gets the minute's events inline under a match id no server serves, and a call to the match tools fails the call (lesson 90); the Personalizer is the published one behind the in-process A2A server. Speech down: planned (on #129). Live run: requested |
| Recovery from injected failures on the M1 live path (Judge down, Judge timeout, Judge malformed reply, Analyst or MCP tool error, MCP timeout, Analyst malformed reply, low-confidence detection) | `uv run python -m ninety.eval.fact_checker_proof` (offline, seconds of CPU; `--check` fails if a committed file is stale, as `tests/test_fact_checker_proof.py` does) | `docs/eval/failure-table-m1.md` | running: 7 of 7 recovered on the live path with stand-in models: nothing unverified aired and the template cues stayed up; each row asserted by `tests/test_failure_table.py`. Latencies not measured (stand-in models) |
| Ablation: the fact-checker without the confidence gate, without typed facts, and absent, on the same planted set | `uv run python -m ninety.eval.fact_checker_proof` (offline, seconds of CPU; `--check` fails if a committed file is stale, as `tests/test_fact_checker_proof.py` does) | `docs/eval/ablation.md`, per claim `docs/eval/ablation.json` | running: false claims on air: full 0/175, no gate 16/175 (every phantom detection), no typed facts (the Judge alone) 24/175: every phantom plus 8 claims stating the minute and second as a clock ("1:05" for 00:05), which only the code checks catch, no fact-checker 175/175. The Judge answers to the 48 claims only the code checks had seen were recorded once from `ninety-judge:2` (`uv run python -m ninety.eval.planted_judge`, 48 calls, 50,708 tokens, $0.025 at list price) |
| Ablation: one agent with every tool against the full workflow | `uv run python -m ninety.eval.agent_ablation --live` (agents-live `task=ablation`, held-out seeds 21 and 33; tested on scripted models in `tests/test_agent_ablation.py`) | `docs/eval/ablation-agents.md`, `docs/eval/ablation-agents.json` | running: agents-live 39521924730 at `58d7a6e` (2026-10-21), seeds 21 and 33, 10 minutes each arm. False claims on air: one agent 7 of 10 (70%: 3 caught by the code checks, 4 by the Judge), the graph 1 of 24 (4%, by the Judge), at 10 against 120 model calls; both arms had an insight in 10 of 10 minutes, and neither lost a minute to a tool call. Both arms get the minute's events inline from the match this commit simulated, the one the grader grades against, under a match id no server serves; an agent that calls the match tools anyway fails that call (lesson 90). Their aired claims are graded the same way (code checks, then the published Judge, the same Judge the graph's fact-checker asks); the arms' model-call budgets differ by design and are reported |
| Describer model upgrade and speech outage (W4, PR #129): on a verified moment the Describer model's line is said only if it passes the whole fact-checking agent (the code checks, then the Judge, which refuses a goal said of a saved shot or a player put on the wrong team; a Judge failure or timeout keeps the code line) and is at most 20 words, else the claim's code line stays and the refusal says why; the model writes words only (SSML, pan and timing are code); a failed speech request keeps the line on the schedule and its cue says `speech: unavailable`; SSML escapes both quotes | `uv run pytest tests/test_describer.py` | test assertions | in progress: runs with stand-in models and speech; each rule's test fails when the rule is mutated (see PR #129). The live run (`ninety-e2e --describer foundry`, the published `ninety-describer`) has not run, so no model latency or tokens yet |
| Latency to graphic and to speech (p50, p95); cost per match | `uv run python -m ninety.eval.latency_cost --measure <clip>` (times `ninety-e2e` offline and the slice replay through `ninety.stage` OpenTelemetry spans; tokens rebuilt from the replay; prices from the Azure Retail Prices API, dated); without `--measure` it rebuilds the report byte for byte (`tests/test_latency_cost.py`) | `docs/eval/latency-cost.json`, `docs/eval/latency-cost.md` | running for the chain's own time and the model and claim-speech cost, at `3d21ab3`: event to graphic p95 0.08 s of compute on the stand-in events of `seed900001`, without RF-DETR inference or Foundry model time (planned: live spans in Application Insights); $0.23 to $0.47 a 90-minute match (one claim a minute, one to three drafts) against the $0.50 budget, tokens estimated at 4 characters each. Speech latency and the Describer's spoken characters planned |

## Agent prompts: held-out seeds (pre-registered Oct 23, 2026)

Seeds 21 and 33 are the agent evaluations' held-out seeds (the rows above, the nightly run). Several
prompt versions have been compared on them, so for a further change to an agent's instructions (an
Analyst v6, a Judge v5) they no longer count as unseen. Any such change is confirmed once on **seeds
920001 and 920002**, written here before it is made: no prompt has been tuned on them, and none will
be. They are not the vision test seeds (900001 to 900030). A result on them is reported with its n,
and a change that helps only on 21 and 33 is reported as that.

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

### Pitch-level matching

Pitch-level matching judges a box by where it puts its object on the pitch, as event detection
does, not by how its pixels overlap. It is reported beside the pixel score, in the `pitch`
block of `vision_score`'s report (one clip) and of `vision_report`'s (counts summed across clips, as
for pixels, with the at-least-half-visible ball under each rule), and is not used to interpret
that score. Built in
[`ninety/eval/vision_pitch_score.py`](../ninety/eval/vision_pitch_score.py).

Every true and every detected box goes to the pitch through that frame's saved camera matrix
(`camera.P`), the way [`ninety/vision/observe.py`](../ninety/vision/observe.py) places a box: a
player at the bottom middle of the box, on the ground; the ball at the box centre, on the ground
with its centre one radius (0.11 m) up. Truth and detection are placed the same way, so the score
measures the detector's boxes, not the camera fit or the ball's height. Within each frame and
class, eligible detections (score ≥ 0.5) are paired one to one with true boxes, nearest on the
pitch first, within the radius below (the edge counts). A label with no match is a false negative,
a detection with no match a false positive, and the difficulty groups follow the pixel scorer's
convention below. A box whose point is not on the ground in front of the camera (above the
horizon) has no place: a label is then a miss and a detection a false alarm, counted under
`unplaced`. Precision and recall are given overall, by class, for each visibility group, for
the ball on the ground and in the air, and for each class on blurred and other frames.

| Rule | Ball | Player | Why |
|---|---|---|---|
| Strict | within 1.0 m | within 1.0 m | possession assigns the ball to the nearest player; two players are often about 2 m apart ([GROUNDING.md](GROUNDING.md#vision-scoring-how-detections-are-graded) S3) |
| Lenient | within 2.0 m | within 1.5 m | a looser comparison radius, reported beside strict, never as the headline ([GROUNDING.md](GROUNDING.md#vision-scoring-how-detections-are-graded) S4) |

The strict radius and the ball's lenient radius are the event scorer's own (`STRICT_M`,
`LENIENT_M` in `ninety/eval/event_score.py`), imported, so the two cannot drift.

**The scorer is checked against planted damage.** `fake_pitch_detections` in
`ninety/eval/fake_box_detections.py` copies every label, then drops some, moves some on the pitch
by half the strict radius (a match under both rules), halfway between the strict and the lenient
radius (a miss and a false alarm under strict only) or twice the lenient radius (both rules), and
adds false boxes further than the lenient radius from every label. A damaged label, and the point
its copy moves to, are further than the lenient radius from every other label of its class, or
the damage is refused. The counts the scorer must report come from the damage log alone; the same
command as above checks both. Each damage also logs its ball height and camera blur group, read
from the clip, and `only={"blur": "blurred"}` (or a height group) plants all of it in one group,
so the per-group counts are checked too, exactly 0.5 m and exactly 3 px among the planted frames:

```bash
uv run python -m ninety.eval.fake_box_detections runs/dataset/test/seed*
```

**Difficulty groups.** Every true ball and player is put in groups using the renderer's
labels. TP, FP, FN, precision, recall and F1 are reported for each visibility group
nested under its class (`visibility.player.visible`, for example), and independently for
each image-boundary group (`image_boundary.player.edge-touching` and
`image_boundary.player.interior`; likewise for `ball`), for the ball's height
(`height.ball.in the air`, `height.ball.on the ground`) and for the camera's blur
(`blur.player.blurred`, `blur.player.not blurred`; likewise for `ball`), as well as overall.
The same groups are reported at pitch level under each rule:

| Group | Rule (from `frames.jsonl`) |
|---|---|
| visible | visibility ≥ 0.9 |
| partly hidden | 0.5 ≤ visibility < 0.9 |
| mostly hidden | 0 < visibility < 0.5 |
| edge-touching | saved bbox reaches any image boundary: x0 ≤ 0, y0 ≤ 0, x1 ≥ camera.width or y1 ≥ camera.height |
| interior | saved bbox reaches none of those boundaries |
| in the air (ball) | true ball centre height (`ball.z`) above 0.5 m, about knee height; the rest, exactly 0.5 m included, is on the ground |
| blurred | camera blur streak (the length of `blur_px`) longer than 3 px, about half the width of a ball at broadcast distance; the rest, exactly 3 px included, is not blurred |

Height and blur are read per frame: every label in a frame with a blurred camera is blurred,
and the ball's height group is its frame's. One cut-off each (`IN_AIR_Z` and `BLUR_PX` in
`ninety/eval/vision_score.py`), imported by the pitch-level scorer and by `pitch_score`. Neither
cites a source yet: each has only the reason in the table, and changing one needs a GROUNDING.md
row first. When no scored frame records the field (`ball.z`, `blur_px`) the group is `null`, and
frames or clips with and without it are refused, so no label drops out unseen.

**A known limit of the 0.5 m cut-off, kept as set.** A ball's pitch position is found by
assuming it lies on the grass (`ninety/vision/observe.py`), so a raised ball is placed beyond its
true spot, along the camera's line of sight. On the local renders' saved cameras, a ball at
exactly 0.5 m is placed 0.83 to 2.45 m from its true spot (median 1.57 m), past the 1.0 m strict
radius. The pitch-level box scorer is not affected: it places the true ball and the detected one
the same way, so the error cancels. `pitch_score` and the events from video compare against the
ball's true position, so their "ball on the ground" errors include balls up to 0.5 m and can
exceed 1.0 m from height alone. The cut-off stays at 0.5 m because it was fixed before any
detector ran. A lower one, derived from the camera's geometry, needs a GROUNDING.md row and a
re-run of every report that uses it.

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

Events made from the picture alone, on the frozen test set's five clips (10 s each, `engine-v1`,
renderer 0.3.2), detected with ours-v2 (vision-report-v1). The live path reads each clip's
`images/` and the detections, nothing else: no `frames.jsonl`, `events.jsonl`, `clip.json` or
`meta.json` (`tests/test_vision_live_path.py` checks the code and a run). Grading then reads the
answer key.

The detector was first developed on test seed 900001, its only clip, so its first numbers were
partly tuned to the test set. It was then re-derived on ours-v2's validation clips (render run v1),
and every constant was frozen before the test set was scored, once
([eval/detector-plan.md](eval/detector-plan.md); measurements in
[eval/detector-derive.md](eval/detector-derive.md)):
- **re-derived on validation:** the side naming, the camera trust test, the side vote and RIVAL_M;
- **tried on validation and kept:** the event and tracker thresholds (none changed on a grid listed
  beforehand);
- **still at the values developed on 900001:** the camera search and its optimiser, the marking
  pixels, the kit colour sampling (`observe.kit_rgb`) and the kit clustering's settings
  (MIN_COLOUR_FRAMES, OUTLIER_FACTOR, CHROMA_NOISE).
So seed 900001 is reported both pooled with the others and left out.

```bash
T=runs/test-frozen-cca498c/test   # the frozen test set (docs/eval/test-set-frozen.json)
for s in 900002 900003 900004 900005; do        # 900001's are tests/fixtures/observations-seed900001.jsonl
  runs/slot.sh uv run --group vision python -m ninety.vision.observe $T/seed$s \
    --detections docs/eval/vision-report-v1/detections/seed$s.jsonl --out docs/eval/attribution/observations-seed$s.jsonl
done
uv run python -m ninety.eval.event_report --test-dir $T --observations docs/eval/attribution \
  --observations tests/fixtures --out docs/eval/event-report-v2
```

Observations made before the trust test changed were re-judged with
`uv run python -m ninety.vision.observe --regate <file> --out <file>`: the camera fit is kept and
only the trust test and the placing run again.

| Stage | What it does | Code |
|---|---|---|
| Camera | white-marking pixels (brighter and bluer than the grass on both sides, detected players and ball masked) fitted to Law 1's markings: one gantry for the clip (found from every 25th frame), pan, tilt and zoom per frame (tracked from the last frame whose markings fit). A frame is trusted when its players are as tall as they should be (the median, over its player boxes, of box height against an upright 1.80 m at the foot point lies in 0.901 to 1.002, the 1st to 99th percentile on validation frames whose ground mapping is within 1.0 m) and its camera agrees with a trusted neighbour's (the ground point at the image centre within 2 m of the nearest other such frame's within 5 frames; [camera-bound-plan.md](eval/camera-bound-plan.md)) | `ninety/vision/pitch.py`, `ninety/vision/observe.py` |
| Camera, a fixed lens (`--fixed`, the tactical camera) | the same marking pixels, voted across the clip: a pixel that is a marking in at least half the frames is static (a missed white kit moves and drops out). One camera for the whole clip, all six parameters fitted from the static pixels (a grid over the rig's ranges, aimed, freed, then a compass search on the position), every frame placed through it: no frame-to-frame jitter. The same height and neighbour tests judge each frame. Measured on drawn scenes against a bar set beforehand ([tactical-fit-plan.md](eval/tactical-fit-plan.md), [tactical-fit.md](eval/tactical-fit.md)); not yet on the tactical renders | `ninety/vision/pitch.py` (`fit_fixed`), `ninety/vision/observe.py`, `ninety/eval/tactical_fit.py` |
| On the pitch | each box's foot point (players) or centre one radius up (ball) through a trusted frame's camera; shirt colour from the box's upper middle | `ninety/vision/observe.py` |
| Two views (tactical camera, planned for the demo) | each lens detected on its own (optionally as a 2 x 2 grid of overlapping tiles, boxes merged back) and placed on the pitch; a player or ball seen by both lenses merged when the two places differ by less than both measurements can miss by (each box's 99th-percentile ground-point error, measured on validation, carried to the pitch through its view's camera; [fuse-gate.md](eval/fuse-gate.md)) | `ninety/vision/tiles.py`, `ninety/vision/fuse.py` |
| Tracks and teams | players linked in pitch metres; two kits told apart by chromaticity (shadow-proof, lesson 98) or by brightness (white against black), whichever separates them more on the clip; the side defending x = 105 is away (the engine's one convention), and it is the side standing nearer it on average (GROUNDING T2, O6) | `ninety/vision/track.py` |
| Events | possession: the ball within 1.5 m of a player's feet and moving with him (GROUNDING P6); a pass from one spell to the next, a shot when the strike heads between the posts, out of play when the whole ball is over a line for 3 frames | `ninety/vision/events.py` |

Events are graded by the rules above (Vision scoring), unchanged: same type and team within 1.0 s,
spot within 1.0 m (strict) of the ball at the detected time. Pitch positions use the pixel
scorer's pairing (player IoU 0.5, ball centre 5 px) and the planned "in the air" height (0.5 m).

**Results, the five test clips, scored once** ([eval/event-report-v2.md](eval/event-report-v2.md)):

| Measure | Result |
|---|---|
| Passes (strict: 1.0 s, 1.0 m) | 7 of 13 found, 1 false: precision 0.88 (95% 0.53 to 0.98), recall 0.54 (95% 0.29 to 0.77), F1 0.67. **Without seed 900001:** 4 of 9 found, none false, recall 0.44 (95% 0.19 to 0.73), F1 0.62. **Both are below PLAN's target of 0.70.** Per clip: 900001 0.75 (3 of 4), 900004 1.00 (1 of 1), 900005 0.86 (3 of 4); 900002 and 900003 none (below). Lenient and time-only give the same |
| Shots | 0 of 1: read as a pass (the ball's height, below) |
| Out of play | none true, 1 false: the same shot reaching the keeper |
| Outside M1's scope | 5 possession changes, 2 pressures, a deflection, a tackle and a set piece, counted as misses |
| Camera trusted | 900001 238 of 250 frames, 900004 194, 900005 248; 900002 none and 900003 4: these two have camera cuts, which the fit does not follow. The neighbour check's worst trusted frame on validation is 8.2 m (observed, under the 8.5 m set beforehand), against 55 m with heights alone. **That is not a bound:** frames wrong the same way agree with each other and pass together, and a wrong frame can make its good neighbour fail instead. On the test set it removes 4 of the 8 frames heights alone trusted there; **the 4 left, on 900003, are about 46 m wrong** (frames 5970 to 5976), wrong the same way, and make no event. A whole clip offset the same way (validation seed 108, 2 to 8 m) passes for the same reason (lesson 159). This is a second look at the test set: the check was planned because #187's test score showed these frames, so 900002's 1 to 0 is not held-out evidence |
| Players on the pitch | median 0.21, 0.23 and 0.14 m on the three clips with a camera, 90% within 1.44, 0.63 and 0.33 m |
| Ball on the ground | median 0.09, 0.14 and 0.05 m, 90% within 0.26, 0.45 and 0.13 m |
| Teams | every matched pass has its true team (7 of 7, 95% 0.65 to 1.00). On validation it is 11 of 16: kit colours are read wrongly on some clips (a blue shirt as near-white, a green one as grey), which the derivation found and did not fix ([eval/detector-plan.md](eval/detector-plan.md), step A) |

**What changed from the published seed-900001 figures, and why.** Those figures (pass F1 0.75,
245 of 250 frames trusted) came from constants developed on that clip. Re-derived on validation:
- the camera trust test is now the players' heights, not the marking error;
- teams can be told apart by brightness as well as by colour;
- the side vote uses each side's mean position, not its deepest player.
The event and tracker thresholds were tried on a grid and none changed. On seed 900001 the pass F1
is the same, 0.75; the camera is trusted on 238 frames instead of 245. The set-wide figure (F1 0.67
on 13 passes) replaces it as the headline.

**Read with care.** Five ten-second clips hold 13 passes and one shot, and two of the clips give no
events at all. A single pass moves the recall by 8 points. This shows the pipeline works end to end
and where it fails, not how well it does on a match.

**Not yet:** the ball's height. A lofted ball is placed on the ground beyond where it is, which
turns this clip's shot (a ball rising to 1.3 m) into a pass whose path misses the posts, and puts it
over the goal line as it reaches the keeper (the false out of play). Fitting its flight needs air
drag as well as gravity: over its first 0.4 s, drag moves a 30 m/s ball about as far as gravity
does, and a drag-free fit tilts the flight along the camera's line of sight, wrongly even through
the true camera. Possession changes and pressure are not detected; who acted is, as a track
(below), never as a shirt number.

### Who: team and track

The agents need to know who did what. A detected pass or shot names its `player`, a completed pass
its `receiver` and a pass the other side took its `interceptor`, as side and track (`h-t12`): the
ids the phone companion's minimap uses, never a shirt number (`ninety/vision/events.py`,
`attribute`).

- The holder of the spell (at the strike, or at the first frame of the next spell) is named only
  when no other track, of either side or none, is within **RIVAL_M = 1.26 m** of his own distance
  from the ball: a rival that close may really be the nearer one. Only a track the companion
  draws (a side, and at least 5 frames) is named.
- Otherwise the name is null and the event keeps its `team` (the holder's kit colour), so the
  agents can still say what a side did. Out of play names nobody; nor does the truth.
- No pass is recorded between two tracks that may be one player the tracker lost and picked up
  again: never seen in the same frame, the second starting within the tracker's 25 frames and
  within reach (10 m/s, a player's top-speed capability, GROUNDING P9, plus RIVAL_M) of where the
  first ended. Otherwise a dribbler reads as passing to himself, named at both ends (lesson 146).

**How the constants were set** ([eval/attribution-plan.md](eval/attribution-plan.md), then
[eval/detector-plan.md](eval/detector-plan.md); each committed before the validation numbers it
plans were read). They come from ours-v2's validation clips, never test clips.
- **RIVAL_M** is the players' pooled 90th-percentile pitch-position error on those clips, on the
  frames the camera trust test passes ([eval/attribution-derive.md](eval/attribution-derive.md)).
  It was 1.89 m with the old marking test, 1.59 m with the height test, and is 1.26 m with the
  height and neighbour checks. It still includes
  validation seed 108, whose camera is about 2 m wrong with players the right height, so it is
  larger than the box error alone and leaves more names null. An earlier 1.44 m had been measured
  on test seed 900001 and is replaced.
- **The track-break rule's form** was chosen on test seed 900004. On validation it was only kept
  or dropped: it removes only self-passes (3 with the height test, 7 with the old one) and never a
  pass between two different players, so it is kept. Each time, matched passes fall by 2. Both lost
  matches are the same two self-passes, which fell within 1 s of the same player's real pass.
- **`attribution_score.truth_role`** was added after the validation run, when it showed that
  render run v1's older ground truth names an interceptor in `receiver`. It changes development
  numbers only: without it, the first validation run's 11 of 11 names reads 9 of 11. The test
  truth has the `interceptor` field, so test numbers are unaffected.

Graded offline by `uv run python -m ninety.eval.attribution_score` (reads the answer key; nothing on
the live path imports it). A detected event is paired with a true event of the same type within
1.0 s, one to one, nearest first: the event scorer's rule without its team condition, since the team
is what is graded. A named track is the true player whose box its detection overlaps most (IoU at
least 0.5, the pixel scorer's player rule); a name whose box pairs with nobody counts as wrong.

| Measure | Validation (13 clips, development) | Test (scored once, [eval/attribution.md](eval/attribution.md)) |
|---|---|---|
| Clips with events | 8 of 13 (109, 114, 122, 3041 and 3042 have no trusted frame, or too few to make one) | 3 of 5: seeds 900002 and 900003 have camera cuts the fit does not follow |
| Passes matched | 16 | 7 |
| Team right | **11 of 16** | 7 of 7 |
| Names given, right | 22 of 24: passers 14 of 14, receivers 6 of 6, interceptors 2 of 4 (the two wrong ones are what a wrong team does: an opponent "taking" his own side's pass) | 14 of 14 (7 passers, 6 receivers, 1 interceptor) |
| Names left null where the truth has one | 9 | 0 |
| False events that name someone | 2 of 3 | **1 of 2**: v00003 on 900001, the shot read as a pass, names its shooter `h-t1` (truly h10). With RIVAL_M 1.59 m it named nobody; at 1.26 m no rival is near enough to hold the name back. The demo fixture carries it |

**Read with care.** Small numbers: 7 matched passes on 3 ten-second test clips. On validation the
side is wrong on 5 of 16 passes, even after the side naming was re-derived ([eval/detector-plan.md](eval/detector-plan.md),
step A). The remaining cause is how the kit's colour is read from the image (`observe.kit_rgb`).
A team-level claim inherits that error, which the fact-checker cannot see.

**Side confidence** (`team_confidence`, an optional field on detected events). It is the weaker of
two margins: how much nearer the holder's kit is to its own side's colour than to the other side's,
and how one-sided the clip's vote on which colour is home was. A keeper's is how far he stands from
halfway. Defined before it was measured; no threshold is set from it. **It does not tell a wrong
side from a right one well:** on validation the 5 wrong sides score 0.431 to 0.96, and the 11 right
ones score 0.447 to 0.985. It ranks a right side above a wrong one in 60% of (wrong, right) pairs,
where 50% is chance ([eval/attribution-derive.md](eval/attribution-derive.md)). Gating on it alone
does not protect a team-level claim.

**The agents do not see it.** `ninety/match/facts.compact`, which shapes every event the agents
read (inline or over MCP), passes `confidence` and drops `team_confidence`; checked by building the
Analyst's prompt from the fixture. Whether to show it to them is the agent layer's call, once it
means something.

## Broadcast framing: a known limit of the metric at set-piece deliveries

**The metric.** `tests/test_render_camera.py` counts a live frame as well framed when the ball is in
the picture's CENTRAL box and the pitch fills at least `PITCH_SHARE_MIN` of the picture. It asserts
85% of live frames on six held-out seeds.

**The finding.** Two corner-camera designs reached the bar on #179's engine, and three blind critics
preferred the camera that missed it. Both designs are parked, unmerged:
- `claude/camera-corner-cut` (#204): a cut to a side camera at the delivery.
- `claude/camera-corner-delivery`: zooming to the receiving area.

The critic reports are not committed; the numbers below are in each branch's commit message.

| Design | Seed 3 (#179's engine), raw | Critic's verdict |
|---|---|---|
| #201: corner framing until the kick | 0.811 | preferred |
| Delivery-aware zoom | 0.905 | worse in both pairs |
| Cut at the delivery | 0.886 | split |

What the critics reported against the designs that scored higher:
- The lens closed in on the taker's group before the kick, so the goal and box were out of the picture for about 4 s across the delivery.
- The camera whip-panned at the strike.
- A cut landed while the ball was in flight.

What they asked for: keep the taker, the penalty area and the goal in the picture until the ball has arrived. Then frame the play.

**What it means.** At a set-piece delivery, "the ball central with 60% pitch" rewards the tight shot viewers dislike, near a near-side corner especially. Lesson 177 has the history.

**Planned, not done.** A revision of the metric for set-piece deliveries, for example the goal and box in the picture from the kick until the ball arrives. It will be set before measuring and reviewed. The test is unchanged until then.

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
for speed now and 1.5 km/h for top speed, against 52.8 km/h for top speed without smoothing
(re-graded with the camera trust test of [detector-plan.md](eval/detector-plan.md)).

### Possession now (the wind map's layer)

`uv run python -m ninety.eval.possession_score calibrate` sets the gate on validation clips, and
only then does `grade` score the test clips with it (GROUNDING S6). The unit is a phone frame
(0.2 s). The truth is the answer key's latest possessor's side, and the true ball's third along
that side's attacking direction. Intervals count true possession spells, not frames (Wilson),
with a bootstrap over clips beside them.

On the 13 validation clips ([possession-calibration.md](eval/possession-calibration.md)), team
agreement peaks at 65% (cut-off 0.2) and falls as the cut-off rises: 30% at 0.7, 0% at 0.9. No cut-off
reaches the 75% target, so SHOW is unset and the layer is off. The cause is the side, decided
once per clip: 3 of the 8 clips with ball spells have it flipped throughout, one of them at a
side confidence of 0.88 to 0.97. The test clips have not been graded and will be only once a
better side decision lets the gate open on validation.

Pre-registered before the official calibration (GROUNDING S6): a bar opens only when the lower
Wilson 95% bound of its agreement over possession spells is at least 0.60, from at least 3 clips
(41 spells at 75% agreement); "attacking" needs its own 75% on the samples it would be shown on,
with the same floor. A preview on the unmerged side fix (#187, #195, #200) would have passed 75%
at 0.582 on only 11 spells (Wilson 46% to 92%), with "attacking" wrong on 4 of 4: these criteria
keep that kind of result shut.

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

## Match engine: open held-out gaps

Held-out checks the engine misses once the October 2026 fixes are all in (#160, #163, #164 and
#166 on main `cf3b17a`), measured and never tuned: the funnel's 12 seeds (7, 11, 21, ..., 111) at
90 minutes, and in brackets 20 matches of 20 minutes (seeds 3, 5, 7, 11, 13, 17, 21, 42, 101 to
112). Each gap is a cause to find, not a number to reach (lesson 21); the likely causes are leads,
not yet confirmed.

| Measure, a match | Main `cf3b17a` | With the fixes | Real | Likely cause |
|---|---:|---:|---|---|
| throw-ins | 34.1 (38.0) | 26.1 (26.6) | 40 to 44 (GROUNDING R1) | fewer misplaced passes reach touch now that receivers meet the pass (#166) and clearances are aimed to stay in (#157); a tackle's poke goes out about 0.7 times a 90; nobody puts the ball out on purpose when pressed, and a clearance is never charged down |
| passes | 1,086 (1,054) | 1,113 (1,168) | about 900 to 1,000 (GROUNDING R3) | too much safe recycling: a short safe pass is valued above a progressive one |
| mean pass length | 15.4 m (15.6) | 13.6 m (13.6) | 15.85 m (Paris Saint-Germain) to 23.42 m (Rotherham), the shortest and longest team averages in 35 European leagues, 2018-19 (CIES Football Observatory Weekly Post 263, 20 May 2019, InStat data; its measure of length is not yet checked against ours, *verify*) | longer passes valued low or never offered: the space factor, the lane race's pessimism about late opponents (D1), or switches and through balls not generated as options |
| passes over 30 m | 8.5% (8.9%) | 7.1% (6.5%) | no sourced figure yet | as above |
| fouls | 33.2 (32.4) | 35.0 (32.4) | free kicks 25 to 35 (GROUNDING R1) | at the top of the range; not yet looked at |

Pass completion is inside its band: 79.7% then 84.0% (R3: 75 to 88%). Goals a team: 1.08 then
1.29 over the 12 matches, both inside the range a real league's 12 matches show (0.75 to 2.33,
R4, lesson 118).

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
- **The live evaluation measures only what the model answered.** A request the model did not
  answer (a client fallback, or a failed model call on the server) counts in its own column, and
  air rates and times are over answered requests only. Past `MAX_UNANSWERED_SHARE` (a fifth, a
  design choice) the run writes no report, because which claims an outage hits depends on when it
  struck (lesson 131).
- **The fallback.** The remote has `BUDGET_S` = 6 s, from measurement: the published
  Personalizer took 3.2 to 4.7 s (median 4.0 s) in 8 calls on 2026-10-20, all over the old 3 s
  budget, so every live request timed out (lesson 147); 6 s is the slowest call plus about a
  quarter (design). The server's own model call ends `SERVER_MARGIN_S` = 0.5 s sooner, so a slow
  model is answered by the server's fallback with its reasons. On a timeout, a 5xx or a refused
  connection the in-process fallback answers with the verified text at once. A 4xx or a malformed
  reply is a defect between our own two programs and raises, so it is seen rather than hidden.
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
validated, extra profile fields allowed. Fact-checker: ordinals not read as numbers (lesson 130).
The length-cap mutant survived the first run; its test was added after.

## Rules

- **The test set is fixed and separate.** Clips used to score detection are never used to train it,
  and targeted data rounds never add clips to the test set.
- **Every report records its inputs:** git commit, seeds, model versions and the date.
- **Results are reproducible:** each command runs from a clean clone after `uv sync`, and gives the
  same numbers on any operating system (lesson 46).
