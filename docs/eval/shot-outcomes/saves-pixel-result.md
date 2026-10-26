# Saves from the picture: the result (validation, read once)

Plan, committed and pushed before the read: [saves-pixel-plan.md](saves-pixel-plan.md) (1f990641). Rule
code and its planted scenes committed before the read; scored at **c64f3247** from the 80 validation
clips' kept observations (`runs/onepod-1025b/out/score-val2/observations`), events re-run with saves
written, `python -m ninety.eval.shot_outcomes score`, strict (same team, within 1.0 s). One read. No
test clip was read. [saves-pixel-validation.json](saves-pixel-validation.json).

| Validation, 80 clips | Found | False | Precision | Recall (95%) | Bar |
|---|---|---|---|---|---|
| Saves, gated at 0.5 | 19 of 50 | 7 | 0.73 | 0.38 (0.26 to 0.52) | recall at least 0.60: **missed**; false at most 8: met |
| Saves, ungated | 23 of 50 | 10 | 0.70 | 0.46 (0.33 to 0.60) | |
| Goals, gated | 12 of 16 | 6 | 0.67 | 0.75 | no goal lost: met (as at 8ac10a91) |
| At 8ac10a91, saves gated | 0 of 50 | 0 | | 0.0 | |

**The bar is missed, so `events.SAVES_AIR` stays off**: the live path writes a held save as a shot with
no outcome, and the phone does not say "saved". Nothing was tuned after the read.

## Why the 31 missed saves were missed (after the read, for the record; changes nothing)

| Cause | Missed |
|---|---|
| No hold within 4 s after the save, and no track in the clip marked `keeper` | 12 |
| No hold within 4 s after the save (a keeper track exists) | 11 |
| A hold seen but not credited (the move ended first, the line to the keeper missed the posts, or the striker was the keeper) | 4 |
| A save found but for the other side, or under the 0.5 gate | 4 |

So most misses are upstream of the rule: the broadcast does not mark the keeper (`assign_teams` finds
him only as a third kit inside a penalty area), or the ball is not drawn in his box for three frames
running (a parry, or the ball hidden in his hands). A fix there is a change to keeper tracking, and it
would need a split that no rule has been read on: validation now has been, and the test split was
scored once already.

## Independent audit (hard-coding, AGENTS.md)

A reviewer with no knowledge of the intent listed every new constant: `HOLD_FRAMES` (design, the
rules' `OUT_FRAMES`, now held equal by a test), Law 1's posts and penalty area, and the shot rule's
`SHOT_MAX_M` and `SHOT_MARGIN_M`, reused; none fitted, no id special-cased. It found one real defect,
fixed after the read and before this PR: with saves off, a pass the hold made a shot (a caught cross,
a back-pass) still reached the live path as a shot with no outcome. The whole rule now runs only with
saves on, so the live path is byte-for-byte what it was (a test checks it). This changes no number
above: they were read with saves on. Of its 18 mutants, the ones that survived are now killed
(`HOLD_FRAMES`, the frames running, the move ending at another player, the goal guard, the `saves`
gate); still untested by a planted scene: the 35 m reach, the post margin's edge and a cut before the
hold, each the shot rule's own and tested there.
