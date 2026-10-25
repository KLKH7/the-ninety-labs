# Shot outcomes from video: the result (goals and saves)

Plan and amendments: [shot-outcomes-plan.md](../shot-outcomes-plan.md). Set:
[shot-outcome-set.md](../shot-outcome-set.md). Scored at the frozen commit **8ac10a91** (main), the
events stage re-run from each clip's kept observations (`scripts/score-shot-outcomes.sh`, then
`python -m ninety.vision.events` and `python -m ninety.eval.shot_outcomes score`), broadcast camera
only. Strict matching: same team, within 1.0 s (the event scorer's window). Gated at 0.5, the
fact-checker's `MIN_CONFIDENCE` (gated and ungated agree on both splits).

**Order, stated:** #271 merged into main (22:28Z, Oct 25) before this measurement; the rules were
pre-registered in the plan before each score, and nothing was changed between the validation read
and the test score. Amendment 6 (a keeper read by the goal, not the kit) was tried on validation
after the re-score, showed no gain and one false save, and was not adopted (#363, closed).

## Test: scored once, 42 of 79 clips

The pod stopped at its fixed time with 42 of the 79 test clips run (seeds 910009 to 910012 and part
of 910013). By the rule written before any test clip was rendered, the score covers every clip that
came back and no other; the 37 missing are listed in [test-missing.txt](test-missing.txt).

| | Found | False | Precision (95%) | Recall (95%) |
|---|---|---|---|---|
| Goals | 6 of 8 | 2 | 0.75 (0.41 to 0.93) | 0.75 (0.41 to 0.93) |
| Saves | 1 of 24 | 0 | 1.0 (0.21 to 1.0) | 0.04 (0.01 to 0.20) |

Of the 2 false goals, one is a true goal timed 1.2 s from the truth (outside the 1 s window: it
counts as one miss and one false), and one is false. [test.json](test.json).

## Validation (80 clips, 16 goals, 50 saves)

| | Found | False | Precision | Recall |
|---|---|---|---|---|
| Goals | 12 of 16 | 6 | 0.667 | 0.75 |
| Saves | 0 of 50 | 0 | | 0.0 |

4 of the 6 false goals are true goals timed more than 1 s from the truth, so about 14 to 16 of the 16
goals are seen at all; 2 are false. Goal confidence on validation: 0.7 to 0.8, 6 of 10 right; 0.8 to
0.9, 6 of 8 right. It does not separate a right goal from a wrong one well. [validation.json](validation.json).

## What does not work: saves

A save is not seen. The ball in the keeper's hands is above the grass, and placed on the ground
through the camera it lands 2 to 7 m from his feet, behind and away from the camera. So the catch
is not a turn of the ball at the keeper, and about 25 of the 50 validation saves read as the ball
going out behind the line. The fix needs the ball's height (its flight, open work) or a test in
pixels (the ball drawn over the keeper's box); neither is in this commit.

## Known limits

- Goal timing: a goal whose crossing is not seen is timed when the ball is first seen at rest, up to
  about 2.6 s late on validation.
- The kick-off evidence (amendments 2, 4, 5) cannot be measured on this set: every goal clip ends
  5 to 7 s after its goal, before any kick-off.
