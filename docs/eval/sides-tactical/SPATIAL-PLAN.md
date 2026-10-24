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

## Deviations

### Oct 24 (the commit time), before any S number was computed

The decision compares S with T1a. T1a run again at this commit (R4 from #202 on today's stack, the
same `T1-fused` observations, `sides_tactical`) gives **0.731** outfield accuracy
(`T1a-validation-r4stack.json`), where session D's run on their branch gave 0.681: the tracking and
kit code differ between the two. S is judged against T1a **at this same commit**, 0.731: the rule's
intent, the same clips through the same code. The cause of the difference is not chased here.

### Oct 24 (the commit time), after S was adopted and before any number of G: variant G, the possession graph

The Coordinator asked for a third, independent source: the links between players that play makes.
A detected pass's outcome cannot be used, since events call a pass completed exactly when passer and
receiver share a side, which would feed the sides back to themselves. The source used is the ball
going **from one player's possession spell to the next player's** (`events.spells`, consecutive
spells of two different tracks with no cut between them, as `events.detect` reads a pass): most such
transfers are completed passes (GROUNDING R3: completion 75 to 88%), whatever the kits say, so each
is evidence that the two are team-mates. Duels are not detected and are not used.

**The graph evidence of a track:** the mean, over its transfers (to or from it, each counted once), of
`2 p_u - 1`, where `p_u` is the other track's S probability of being home (from S's leave-one-clip-out
weights, never its own clip's fit); 0 with no transfer.

**Variant G:** `logistic(w0 + w1 kit + w2 depth + w3 kickoff + w4 graph)`, fitted as S (maximum
likelihood, track frames as weights, leave one clip out). **Each source alone** is also fitted and
reported the same way (kit; depth and kick-off together, the spatial prior; graph), and the fusion.

**Decision (fixed now):** G replaces S if its leave-one-clip-out outfield accuracy is at least S's
(0.750) and its calibration error is at most 0.05. Reported beside it, for the gate: the number of
tracks at or above 0.96 and their accuracy, against S's 6 tracks at 1.0. Keepers and referees keep
their own handling (kit and position outliers, `assign_teams`). The 0.96 gate is not moved.

### G's result (validation, leave one clip out; `G-validation.json`)

| Source | Outfield accuracy | Calibration error | Tracks at or above 0.96 (right) |
|---|---|---|---|
| kit alone | 0.734 | 0.019 | 0 |
| spatial prior alone (depth, kick-off) | 0.661 | 0.014 | 6 (6) |
| possession graph alone | 0.433 | 0.058 | 0 |
| S (kit + spatial) | 0.750 | 0.037 | 6 (6) |
| **G (all three)** | **0.753** | **0.041** | **13 (12)** |

By the rule as written G replaces S (accuracy at least S's, calibration error at most 0.05). But the
graph's fitted weight is **negative** (-1.68 of `G_weights_all`): a track whose passing partners look
home is pushed toward away, the opposite of the premise the plan registered (transfers are mostly
completed passes, so team-mates). The fit rests on 93 transfers over 23 clips; alone the graph is
worse than a coin (0.433). G's 0.003 gain is therefore evidence working against its own reason, and
it adds a wrong track above the gate (12 of 13 right there, against S's 6 of 6). The rule did not
foresee a sign check; this is put to the Coordinator, not decided here. Until then the live path
keeps S.
