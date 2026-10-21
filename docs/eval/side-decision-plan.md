# The side decision per clip, with a confidence that predicts being wrong: the plan (before any run)

Written on branch `vision/side-decision`, stacked on #195 (`vision/camera-bound` at bfde195), before
any of the runs below. Results go under "Outcome" at the end, without editing what is above.
Lesson 178.

## Why

W6's possession layer (`r8-possession-design.md`, shared notes) cannot open its gate.
- **The side is wrong for whole clips.** On validation the detector's per-clip side is wrong
  throughout on 3 of 8 clips with ball spells (108, 120, 121). The attacking direction flips with
  it, since it comes from the side.
- **The confidence does not predict it.** Clip 121 is wrong at 0.88 to 0.97, like attribution's
  wrong-side pass at 0.983. Pooled team agreement peaks at 65%, against the 75% gate.
- **The agents** are held to "no team-level claims" until the side can be trusted.

W6 measured on main. This branch already has #187's brightness kits and mean-position vote, and
#195's camera checks. There, per-track side accuracy is 0.815 (108 0.94, 115 0.73, 116 1.00, 120 0.11,
121 1.00, 2041 0.88, 2042 1.00, 2043 0.83; `docs/eval/detector-derive.md`). **The baseline here is
this branch, not main,** and both are reported.

## Two failures, measured apart

A clip's side can be wrong in two ways, and only one is a naming problem:
1. **Clusters:** the two kit clusters do not each hold one team (120: blue shirts read near-white).
   No naming rule fixes this. It needs `observe.kit_rgb` and the image stage re-run, which is not
   done here (slot jobs).
2. **Naming:** the clusters are sound but named the wrong way round.

**Sound clusters (fixed now):** a clip's clusters are sound when, in each cluster, at least 80% of
its matched track-frames belong to one true side, and the two clusters' majorities differ. The truth
is used offline only, to sort the clips, never as a feature.

## Truth and data

- **Clips:** the 13 observed validation clips of [detector-plan.md](detector-plan.md) (render run v1,
  ours-v2), observations as committed on `pr-assets/detector-validation-observations` (4d42fbf).
- **The engine's convention:** home attacks toward x = 105 in both halves. Render run v1 keeps it
  (home's keeper near x = 5 in every clip, checked in #187).
- **What a decision is:** which kit cluster is home. The attacking direction follows from it.
- **No re-deciding over time:** under this convention a clip's truth never changes within it. A
  decision that changes mid-clip can only add errors, so re-deciding is not a candidate. If a
  rendered clip ever spans half-time with ends swapped, this has to be revisited.

## Candidates for the naming (each from live data only: observations, tracks, spells, detected events)

| Name | Evidence that the cluster is home (attacks toward x = 105) |
|---|---|
| N0 (now) | per frame, the cluster nearer x = 105 on average defends it (A.3; GROUNDING T2, O6) |
| N1 passes | detected passes by each cluster move the ball toward the goal it attacks more often than away: sum of sign(end_x − x) per cluster (teams progress toward the goal they attack; design) |
| N2 carries | within each spell, the sign of the ball's x change from first to last frame, summed per cluster (a carrier moves toward the goal he attacks; design) |
| N3 shots | detected shots head for the goal their side attacks (events.heads_for_goal); one vote each |
| N4 all | the sum of N0 to N3's normalised margins, each source's votes for minus against over its count, so no source dominates by volume |

**Keeper positions are not a candidate.** A keeper wears a third colour and cannot be tied to an
outfield cluster from the picture.

## Confidence candidates (scored, never used to choose the naming)

- **K0 (now):** team_confidence, the weaker of the kit margin and the vote margin.
- **K1:** N4's agreement, the share of sources that agree with the decision (with N4's margin
  breaking ties), times the clusters' soundness proxy. That proxy is the kit separation of #187
  (between-centre distance over within-cluster spread), mapped through sep / (1 + sep) (design).
- **K2:** K1 without the separation term.

## Adoption rule (on validation only)

**Naming:** a candidate qualifies when, on the clips with sound clusters, it names at least as many
clips right as N0, and per-track side accuracy (by frames, all 13 clips) does not fall. Among
qualifying candidates the most per-track accuracy wins, with ties going to the earlier in the
table. If none beats N0, N0 stays.

**Confidence:** the adopted confidence is the candidate with the highest ordering:
- the share of (wrong, right) pairs of matched passes on validation whose wrong one scores lower;
- ties count half;
- the same measure as #187's 0.55, 0.80 and 0.60.

It is reported as predictive only if that ordering is at least 0.80. Otherwise the outcome says the
confidence still does not predict, and W6's gate stays closed.

## Reported (per clip, with intervals)

- Per clip: sound or not, the decision right or wrong for each candidate, and per-track side
  accuracy with a Wilson 95% interval over track-frames. That interval is optimistic, since frames
  within a track are not independent, so the interval over tracks is given as well.
- Pooled: clips named right (with a Wilson interval over clips), per-track accuracy, pass team
  accuracy, and the confidence's ordering.
- Seen before this was written, from #187 and #195: the per-clip accuracies above. W6's results are
  on main and are not reused.

## Then

- Freeze, and score the test set once:
  - `attribution_score`: team on matched passes;
  - per-clip side accuracy with the test truth: a new offline report, in the same form as validation.
- Update EVALUATION, CHALLENGE_MAP, the W6 note and the agents' interim limit:
  - lifted only if the confidence is predictive by the rule above;
  - otherwise kept, and said plainly.
- Lesson 178.

## Outcome

### Validation ([side-decision.md](side-decision.md))

**The naming is already right where the clusters are sound.** On the 4 validation clips whose kit
clusters are sound (108, 116, 121, 2042), today's mean-position vote (N0) names the sides right on all
4 (95% 0.51 to 1.00). Every remaining side error is a cluster failure: the two clusters don't each
hold one team. Those clips are 115 (0.73), 120 (0.11), 2041 (0.88) and 2043 (0.78), by track-frames.

| Naming | Sound clips right | Side accuracy, track-frames | Pass teams right |
|---|---|---|---|
| **N0 mean position (kept)** | 4 of 4 | 0.815 | 11 of 16 |
| N1 pass direction | 1 of 4 | 0.496 | 7 of 16 |
| N2 carries | 4 of 4 | 0.691 | 9 of 16 |
| N3 shots | 4 of 4 | 0.815 | 11 of 16 |
| N4 all | 3 of 4 | 0.633 | 10 of 16 |

- **No candidate beats N0,** so N0 stays.
- **Too few votes:** passes, carries and shots give 0 to 6 votes per clip, against N0's 29 to 250
  frames.
- **N3 abstains everywhere:** no strike on these clips heads for one goal and not the other, so it
  equals N0.

**Confidence: none predicts being wrong.** The orderings (0.5 is chance):

| Confidence | Ordering |
|---|---|
| K0, today's team_confidence | 0.62 |
| K1, agreement times separation | 0.33 |
| K2, agreement only | 0.23 |

K0 is the best, but under the 0.80 the plan set. So **W6's possession gate and the agents' "no
team-level claims" stay**: nothing here makes a team-level claim safe yet.

**Why:** the errors left are cluster errors, and nothing measured here sees them. Today's confidence
is built from the kit margin and the vote, and a wrong cluster can be confident in both. A
confidence that predicts these errors would have to measure cluster soundness from the picture: kit
colour read correctly (`observe.kit_rgb`) and each cluster's spread. That is the follow-up below.

**Follow-up, tied to dataset v2 (after the freeze render):** fix how kit colour is read
(`observe.kit_rgb` drops a green shirt's pixels as grass, reads blue as near-white and white as cyan
on some clips), re-run the image stage on the validation clips, then measure a cluster-soundness
confidence the same way.

### Frozen for the test score

The measurement code and every constant are frozen at the commit that adds this section. Nothing in
the live path changed (N0 and K0 kept), so the test set gets the new per-clip side report only.

### The test set, scored once (code frozen at d24e370; [side-decision-test.md](side-decision-test.md))

Side accuracy by track-frames over the three clips with tracks: 0.889 (95% 0.88 to 0.90).

| Test clip | Clusters | Named | Accuracy |
|---|---|---|---|
| 900001 | sound | right | 0.98 |
| 900004 | not sound | | 0.83 |
| 900005 | not sound | | 0.84 |
| 900002, 900003 | no tracks (camera cuts) | | |

Same pattern as validation: the naming is right where the clusters are sound, and the errors are
cluster errors.
