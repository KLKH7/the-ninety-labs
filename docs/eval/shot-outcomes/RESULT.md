# Shot outcomes from video: the result (goals and saves)

Plan and amendments: [shot-outcomes-plan.md](../shot-outcomes-plan.md). Set:
[shot-outcome-set.md](../shot-outcome-set.md). Scored at the frozen commit **8ac10a91** (main), the
events stage re-run from each clip's kept observations (`scripts/score-shot-outcomes.sh`, then
`python -m ninety.vision.events` and `python -m ninety.eval.shot_outcomes score`), broadcast camera
only. Strict matching: same team, within 1.0 s (the event scorer's window). Gated at 0.5, the
fact-checker's `MIN_CONFIDENCE` (gated and ungated agree on both splits).

**Order, stated:** #271 merged into main (22:28Z, Oct 25) before this measurement; the rules were
pre-registered in the plan before each score, and nothing was changed between the validation read
and the test score (the one early look at 42 test clips, below, changed nothing either). Amendment 6 (a keeper read by the goal, not the kit) was tried on validation
after the re-score, showed no gain and one false save, and was not adopted (#363, closed).

## Test: all 79 clips

The pod ran all 79 test clips (none failed) and only their observations and detected events came back
(`NO_SCORE=1`: no answer key left it). Scored once over all 79, at 8ac10a91, after the copy-back was
confirmed complete.

| | Found | False | Precision (95%) | Recall (95%) |
|---|---|---|---|---|
| Goals | 10 of 15 | 3 | 0.77 (0.50 to 0.92) | 0.67 (0.42 to 0.85) |
| Saves | 2 of 49 | 0 | 1.0 (0.34 to 1.0) | 0.04 (0.01 to 0.14) |

Of the 3 false goals, one is a true goal timed 1.2 s from the truth (outside the 1 s window: one miss
and one false), and two are false. Goal confidence: the 10 right ones 0.815 to 0.89, the 3 false 0.806,
0.86 and 0.862: it does not separate them. Ungated, one false save is added. [test.json](test.json).

**An early look, disclosed.** At 23:47Z, before the copy-back was complete, the test was scored on the
42 clips then on the Mac (the code already frozen at 8ac10a91, nothing changed after it): goals 6 of 8,
2 false (precision and recall 0.75, 95% 0.41 to 0.93); saves 1 of 24, 0 false (recall 0.04, 95% 0.01 to
0.20). It was premature (the pod was still copying back, lesson 257), so it is not the result.
[test-early-42.json](test-early-42.json), the 37 then missing in
[test-early-42-missing.txt](test-early-42-missing.txt).

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
pixels (the ball drawn over the keeper's box); neither is in this commit. The pixel test was built and read once on validation afterwards
(amendment 7): 19 of 50, 7 false, under its bar; saves stay off ([saves-pixel-result.md](saves-pixel-result.md)).

## Known limits

- Goal timing: a goal whose crossing is not seen is timed when the ball is first seen at rest, up to
  about 2.6 s late on validation.
- The kick-off evidence (amendments 2, 4, 5) cannot be measured on this set: every goal clip ends
  5 to 7 s after its goal, before any kick-off.
