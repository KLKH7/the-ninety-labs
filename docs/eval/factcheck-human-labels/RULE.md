# Human labels for the fact-checker: the sampling rule, fixed before the run's results are seen

Written 2026-10-25, while `factcheck_eval --seeds 21,33` (Judge `ninety-judge:4`) was still running. No row of that run had been read when this was written. The rule does not change after it.

## What is labelled
25 decisions in five strata. Each is drawn with `random.Random(20261025).sample` from its pool, sorted by `(source, seed, kind, claim)`.

| Stratum | n | Pool |
|---|---|---|
| passed | 8 | the run's rows with code_ok and judge_ok (both layers passed it) |
| rejected by code | 5 | the run's rows with code_ok false |
| rejected by the Judge | 6 | the run's rows with code_ok true and judge_ok false, category `unsupported_claim` or `input` (a Judge service error is no decision, and is left out) |
| held | 3 | the 8080 dry-run's vision-detected events (runs/demo-8080-1d0390be-vision, the freeze engine's render), passes and shots that the confidence gate holds (`factcheck.confidence_gate`, category `low_confidence`). The sentence is the offline Tactician's (`describe.as_sentence(cues._text(event, "analyst"))`) |
| rewritten | 3 | the accepted claims of the recorded live workflow (replays/workflow-minute2-plant.json, seed 7, recorded 2026-10-20) that a rejection sent back first. Its record says 3: the planted number, the Judge's rejection and the Challenger's alternative, each rewritten. All are taken |

A pool smaller than its n is taken whole; no other stratum makes up the shortfall.

## What the labeller sees
Each item shows only the sentence and its cited facts in plain words (who, what, the values with their units, the match clock), plus a detection's confidence where there is one. It never shows the verdict, the stratum, the layer or the kind. Items are shown in one order, shuffled with `random.Random(25102026)`, under opaque ids (L01 to L25). The key (item to stratum and verdict) is a separate file that the page does not load.

Answer: "Supported by the facts?" yes / no / unsure, plus an optional note.

## How it is scored (`score.py`)
- **Checker says supported:** passed, and the rewritten final claims.
- **Checker says not:** rejected, by either layer, and held.
- **Agreement:** the share of items, among those answered yes or no, where the label matches the checker.
- **False-pass rate:** among the checker's "supported" items, the share Kian labels no.
- **False-hold rate:** among the checker's "not" items, the share Kian labels yes.
- Each rate is reported with its n and a 95% Wilson interval. "Unsure" answers are counted and left out of every rate. Each stratum is also reported on its own.
- With n near 25 the intervals are wide; the report says so and claims nothing beyond them.

Sources: simulator events only (synthetic, the answer key used here as code facts, which is grading, its allowed use), vision detections of our own render, and our recorded model output. Nothing from a real match.
