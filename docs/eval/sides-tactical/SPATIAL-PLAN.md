# Team sides with a spatial prior (variant S): pre-registered

Status: **pre-registered**, written before any number of variant S was computed (the commit time).
A change after this commit goes under "Deviations", dated, before any result is read.

**Why:** T1a (the tactical lenses, #202's two-colour kit reader) is the best side so far, 0.681 of
outfield track-frames right on validation ([PLAN.md](PLAN.md)), and the fact-checker's 0.96 gate holds
nearly every team claim. Kit colour is one kind of evidence; where players stand is another, read
from the tracked positions only (no truth).

## Variant S

The same tracks as T1a (the fused tactical views' observations with R4 kits, session D's `T1-fused`,
judged with today's fixed band), the same kit clusters and naming as `track.assign_teams`. Each
outfield track then gets three pieces of evidence that it is **home** (home defends x = 0 in both
halves, the engine's convention, which `assign_teams` already uses to name the clusters):

1. **Kit:** `(d_away - d_home) / (d_away + d_home)` of its median kit against the two cluster
   centres (-1 to 1).
2. **Depth:** the mean over its frames of `-(x - x̄) / 52.5`, where x̄ is the mean x of every tracked
   outfield player in that frame: a team's players stand nearer their own goal than the other team's
   on average, in and out of possession (GROUNDING T2, O6, as `assign_teams`' naming vote).
3. **Kick-off:** over frames where the ball is still within 1.0 m of the centre spot for 3 frames
   running (`outcomes.kickoff`'s test, with E_C replaced by the strict 1.0 m), the share of the
   track's frames in the home half (x < 52.5) minus the share in the other, -1 to 1; 0 when the clip
   shows no kick-off (Law 8: everyone in his own half).

The keeper anchors the naming already (the half he stands in, `assign_teams`); he is not re-sided.

**Combination:** `P(home) = logistic(w0 + w1 kit + w2 depth + w3 kickoff)`, the four weights fitted
by maximum likelihood on validation tracks (each weighted by its frames), against each track's true
team (offline). **Leave one clip out:** every clip's tracks are scored with weights fitted on the
other 22 clips, so no clip is judged by weights that saw it. The side is home when P ≥ 0.5; the
confidence is max(P, 1 − P).

## Measured (validation only, tactical1's 23 clips, as PLAN.md)

The same measures as PLAN.md (outfield side accuracy by track-frames with Wilson 95%, sound and
flipped clips, the confidence distribution for right and wrong tracks, the ordering, the largest
wrong confidence, the share of right tracks above 0.96, and the calibration bins), all from the
leave-one-clip-out predictions; and the weights fitted on all 23 clips, which are what would ship.

## Decision (fixed now)

S replaces T1a's sides if its leave-one-clip-out outfield accuracy is at least T1a's (0.681) **and**
its calibration error is at most 0.05 (the frame-weighted mean, over the bins, of |accuracy − mean
confidence|), so that the 0.96 gate reads a confidence that means what it says. Otherwise T1a stays.
Either way the calibration table goes to the gate's owner. A test number is not part of this plan.
