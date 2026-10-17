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
| Ledger versioning, evidence validation, and deterministic cue fixture | `uv run pytest tests/test_ledger.py tests/test_cues.py` | `tests/fixtures/cues-seed7.jsonl` and test assertions | running: 17 tests; 122 cues for seed 7, five minutes (61 passes, 9 of them failed; the engine made no shots in that window, so shots and goals are covered by hand-built cases) |
| Fact-checker catch rate on planted false claims, and true claims wrongly rejected | `uv run python -m ninety.eval.factcheck_eval` | `docs/eval/fact-checker.md` | re-run pending: the Judge's instructions and the tone kinds changed after the last run (fact split from tone, tone labels fitted to events, held-out and contradicted tone). Last published run, before that change, on held-out seeds 21,33: 129/129 false caught, 12/99 true rejected excluding service holds, all twelve on tone. |
| Match engine touches: control by surface, whose ball and speed; throw-ins; pass completion | `uv run python -m ninety.sim.touches` (seeds 40 to 47) | `docs/eval/touches.md` | running: a report, never a gate; comparisons fixed below |
| Recovery from injected failures | planned | `docs/eval/failure-table.md` | planned |
| Ablation: one agent against the full workflow | planned | `docs/eval/ablation.md` | planned |
| Latency to graphic and to speech (p50, p95); cost per match | planned | `docs/eval/latency-cost.md` | planned |

## Match engine: touches

How a player meets the ball is about to change (a cushioned first touch, a surface for each height,
and what makes a touch worse; [ENGINE.md](ENGINE.md), layer 7). These comparisons were fixed
**before** the first of those changes, on the engine at `claude/engine-to-main` 5aba718, so no
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

## Vision scoring

Fixed before the first detector runs, so no rule is tuned to a result. Every vision report
gives precision and recall (both kinds of error), on the fixed test set only.

**Matching.** A detection is mapped onto the pitch through the camera and matched one to one,
nearest first, to the true positions in the same frame.

| Rule | Ball | Player | Why |
|---|---|---|---|
| Strict (the headline) | within 1.0 m | within 1.0 m | possession assigns the ball to the nearest player; two players are often about 2 m apart, so an error above half that can give the ball to the wrong one |
| Lenient (for comparison) | within 2.0 m | within 1.5 m | the looser radii commonly used for this task, so our numbers can be compared with others |

**Difficulty groups.** Every true ball and player is put in groups using the renderer's
labels, and recall is reported for each group as well as overall:

| Group | Rule (from `frames.jsonl`) |
|---|---|
| visible | visibility ≥ 0.9 |
| partly hidden | 0.5 ≤ visibility < 0.9 |
| mostly hidden | 0 < visibility < 0.5 |
| in the air (ball) | height above 0.5 m, about knee height |
| blurred | camera blur streak longer than 3 px, about half the width of a ball at broadcast distance |

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
